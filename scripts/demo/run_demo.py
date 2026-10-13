#!/usr/bin/env python
"""AgentTrust end-to-end demo (deliverable D8).

One command runs the whole pre-execution verification loop:

    step 1  submit a validation request            -> ERC-8004 requestHash
    step 2  fan out to the heterogeneous cohort    -> concurrent independent rehearsals
    step 3  quantify divergence                    -> D_disc / D_traj / D_end / D_total / D_rel
    step 4  tri-level decision + K-round upgrade   -> Approved / Rehearse / Rejected / Escalate
    step 5  write the record on-chain              -> registry (live) or dry-run ledger

Examples:

    python scripts/demo/run_demo.py                     # every sample task, offline cohort
    python scripts/demo/run_demo.py --task warehouse-pick-001
    python scripts/demo/run_demo.py --cohort live       # needs DASHSCOPE_API_KEY / MOONSHOT_API_KEY
    python scripts/demo/run_demo.py --chain live        # needs RPC + registry + deployer key
    python scripts/demo/run_demo.py --json artifacts/demo-run.json

The demo never invents numbers. When the offline cohort is used, every verdict is labelled
``provider="offline-deterministic"`` and the chain receipt is labelled ``mode="dry-run"``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestrator import (  # noqa: E402
    ConfigError,
    LedgerWriter,
    Orchestrator,
    load_settings,
    make_chain_writer,
)
from validators import TaskRequest, describe_cohort, load_cohort  # noqa: E402

try:  # run as a script (`python scripts/demo/run_demo.py`): same-directory import
    from tasks import TASKS, task_by_id  # type: ignore[import-not-found]
except ModuleNotFoundError:  # imported as a package
    from .tasks import TASKS, task_by_id  # type: ignore[no-redef]


# ----------------------------------------------------------------------------- console
class Palette:
    """Minimal ANSI helper; disabled when not a TTY or ``--no-color`` is passed."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def green(self, text: str) -> str:
        return self._wrap("32", text)

    def red(self, text: str) -> str:
        return self._wrap("31", text)

    def amber(self, text: str) -> str:
        return self._wrap("33", text)

    def violet(self, text: str) -> str:
        return self._wrap("35", text)


DECISION_STYLE = {
    "Approved": "green",
    "Rehearse": "amber",
    "Rejected": "red",
    "Escalated": "violet",
    "InsufficientValidators": "amber",
    "InsufficientBaseline": "amber",
}


def paint(palette: Palette, decision: str | None) -> str:
    name = DECISION_STYLE.get(str(decision))
    text = str(decision)
    return getattr(palette, name)(text) if name else palette.bold(text)


# ----------------------------------------------------------------------------- emitter
def make_emitter(palette: Palette, *, verbose: bool) -> "object":
    def emitter(event: str, payload: dict) -> None:
        if event == "validation_started":
            print(
                f"\n{palette.bold('request')} {payload['task_id']}  "
                f"{palette.dim('validationId=' + payload['validationId'][:18] + '...')}"
            )
            print(
                palette.dim(
                    f"  cohort: {payload['cohort_mode']} "
                    f"({len(payload['cohort'])} members, K={payload['max_rounds']})"
                )
            )
        elif event == "round_started":
            print(palette.dim(f"  round {payload['round']} (tag={payload['tag']}) fanning out ..."))
        elif event == "verdict":
            usable = "ok " if payload["usable"] else "ERR"
            agent = payload["agent"][:22].ljust(22)
            detail = payload["error"] or f"response={payload['response']:>3}  {payload['latency_ms']}ms"
            print(palette.dim(f"    [{usable}] {agent} {detail}"))
        elif event == "round_scored":
            d_rel = payload.get("D_rel")
            d_rel_text = "n/a" if d_rel is None else f"{d_rel:.4f}"
            print(
                f"    D_disc={payload['D_disc']:.4f} D_traj={payload['D_traj']:.4f} "
                f"D_end={payload['D_end']:.4f} -> D_total={payload['D_total']:.4f} "
                f"D_base={payload['D_base']} D_rel={d_rel_text}  "
                f"{paint(palette, payload['decision'])}"
            )
            if verbose and payload.get("kendall"):
                k = payload["kendall"]
                print(
                    palette.dim(
                        f"      Kendall W={k['W']:.4f} chi2={k['chi_square']:.4f} "
                        f"df={k['df']} significant={k['significant_at_0.05']}"
                    )
                )
            if verbose and payload.get("degraded"):
                print(palette.dim(f"      degraded: {'; '.join(payload['degraded'])}"))
        elif event == "round_escalated":
            print(palette.dim(f"    -> {payload['reason']}"))
        elif event == "validation_scored":
            print(
                f"  {palette.bold('decision')} {paint(palette, payload['final_decision'])}  "
                f"{palette.dim(payload['escalation_reason'])}"
            )
        elif event == "chain_written":
            mode = payload.get("mode", "?")
            if mode == "live":
                print(f"  chain      {palette.green('LIVE')} tx {payload.get('txHash')}")
            else:
                print(f"  chain      {palette.amber('DRY-RUN')} ledger only, no transaction sent")

    return emitter


# ----------------------------------------------------------------------------- main
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AgentTrust end-to-end pre-execution verification demo",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--task",
        default="all",
        help="sample task id to run, or 'all' for every fixture",
    )
    parser.add_argument(
        "--cohort",
        choices=["auto", "live", "offline"],
        default=None,
        help="validator cohort: live model adapters, the deterministic offline fixture, or auto",
    )
    parser.add_argument(
        "--chain",
        choices=["dry-run", "live"],
        default=None,
        help="write the record to the dry-run ledger, or to Monad Testnet 10143",
    )
    parser.add_argument("--json", dest="json_out", default="", help="also write the run summary as JSON")
    parser.add_argument(
        "--nonce",
        type=int,
        default=0,
        help=(
            "request nonce mixed into the ERC-8004 requestHash. The registry reverts with "
            "RequestAlreadyExists on a repeated hash, so raise this to re-run the same task "
            "against the same deployed registry (e.g. --nonce 2 for a second recording)."
        ),
    )
    parser.add_argument("--quiet", action="store_true", help="one summary line per task")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colour")
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="exit non-zero unless every task reached a final decision",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    palette = Palette(enabled=not args.no_color and sys.stdout.isatty())

    try:
        settings = load_settings(require_live_chain=(args.chain == "live"))
    except ConfigError as error:
        print(palette.red(f"configuration error: {error}"), file=sys.stderr)
        return 2

    chain_mode = args.chain or settings.chain_mode
    cohort_mode = args.cohort or settings.cohort_mode
    settings.chain_mode = chain_mode

    cohort = load_cohort(cohort_mode)
    description = describe_cohort(cohort)

    print(palette.bold("AgentTrust - pre-execution verification demo"))
    print(palette.dim("  ERC-8004 Validation Registry | Monad Testnet chainId 10143"))
    print(
        f"  cohort   : {cohort_mode} ({'offline deterministic fixture' if cohort.offline else 'live model adapters'})"
        f"  members={len(cohort.members)}  K={cohort.max_rounds}  min_usable={cohort.min_usable}"
    )
    print(f"  chain    : {chain_mode}")
    print(f"  events   : {settings.artifacts_dir}")
    live = description.get("live_heterogeneity") or description["heterogeneity"]
    print(
        "  triad    : "
        + ("satisfied" if live.get("ok") else "NOT satisfied")
        + f"  families={', '.join(live.get('model_families') or []) or 'n/a'}"
        + f"  endpoints={len(live.get('providers') or [])}"
        + f"  frameworks={len(live.get('frameworks') or [])}"
        + f"  strict={live.get('strict_ok')}"
    )
    for note in live.get("notes") or []:
        print(palette.dim(f"             note: {note}"))
    if cohort.offline:
        print(
            palette.amber(
                "             note: offline fixtures are not model outputs; "
                "set DASHSCOPE_API_KEY / MOONSHOT_API_KEY and pass --cohort live for real rehearsals"
            )
        )

    chain_writer = make_chain_writer(settings, frontend_dir=REPO_ROOT / "frontend")
    if not isinstance(chain_writer, LedgerWriter):
        print(
            f"  registry : {settings.registry_address} (real transactions on chainId "
            f"{settings.chain_id})"
        )

    orchestrator = Orchestrator(
        cohort,
        settings,
        chain_writer=chain_writer,
        emitter=make_emitter(palette, verbose=not args.quiet),
    )

    tasks: list[TaskRequest] = TASKS if args.task == "all" else [task_by_id(args.task)]
    for task in tasks:
        task.payload["nonce"] = args.nonce
    if args.nonce:
        print(palette.dim(f"  nonce    : {args.nonce} (distinct requestHash for this run)"))

    records = []
    for task in tasks:
        records.append(orchestrator.run(task))

    # ---------------------------------------------------------------- published feeds
    cohort_feed = {
        "cohort_mode": "offline" if cohort.offline else "live",
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **description,
    }
    data_dir = REPO_ROOT / "frontend" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "cohort.json").write_text(
        json.dumps(cohort_feed, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    summary = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "chainId": settings.chain_id,
        "chainMode": chain_mode,
        "cohortMode": "offline" if cohort.offline else "live",
        "cohort": cohort_feed,
        "constants": {
            "weights": {"w1_disc": 0.4, "w2_traj": 0.3, "w3_end": 0.3},
            "theta_low": settings.theta_low,
            "theta_high": settings.theta_high,
            "max_rounds": cohort.max_rounds,
        },
        "records": [r.as_dict() for r in records],
    }
    if args.json_out:
        target = Path(args.json_out)
        if not target.is_absolute():
            target = REPO_ROOT / target
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nsummary written to {target}")

    # ---------------------------------------------------------------- summary table
    print("\n" + palette.bold("summary"))
    header = f"  {'task':<28} {'rounds':>6} {'D_total':>9} {'D_rel':>8}  decision"
    print(palette.dim(header))
    for record in records:
        d_total = "n/a" if record.d_total is None else f"{record.d_total:.4f}"
        d_rel = "n/a" if record.d_rel is None else f"{record.d_rel:.4f}"
        decision = record.final_decision.value if record.final_decision else "None"
        print(
            f"  {record.task.task_id:<28} {record.round_count:>6} {d_total:>9} {d_rel:>8}  "
            f"{paint(palette, decision)}"
        )

    print("\n" + palette.bold("artifacts"))
    if isinstance(chain_writer, LedgerWriter):
        print(f"  ledger    : {chain_writer.ledger_path}")
        print(f"  latest    : {chain_writer.latest_path}")
    else:
        print(f"  registry  : {getattr(chain_writer, 'contract', None) and settings.registry_address}")
        print(f"  explorer  : {settings.explorer_url.rstrip('/')}/address/{settings.registry_address}")
    print(f"  panel feed: {data_dir / 'records.json'}")
    print(f"  cohort    : {data_dir / 'cohort.json'}")
    print(
        "\nnext: open frontend/index.html (or `python -m http.server` inside frontend/) to view the panel."
    )

    if args.non_interactive:
        unresolved = [
            r.task.task_id
            for r in records
            if r.final_decision is None
            or r.final_decision.value in {"InsufficientValidators", "InsufficientBaseline"}
        ]
        if unresolved:
            print(palette.red(f"\nunresolved decisions: {', '.join(unresolved)}"), file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
