"""On-chain layer: writes validation records to the AgentTrust ERC-8004 registry.

Two modes, selected by ``CHAIN_MODE`` / ``--chain``:

``dry-run`` (default)
    Appends the full record to ``artifacts/ledger.jsonl`` and refreshes
    ``frontend/data/records.json``. Every receipt is tagged ``mode: "dry-run"`` and carries
    ``txHash: null``. This is deliberately *not* dressed up as a chain write - the panel and
    the demo say "simulated" out loud (quality redline 1).

``live``
    Signs and sends real transactions to the deployed registry on Monad Testnet (10143) via
    ``web3.py``. Requires ``RPC_URL_10143``, ``AGENTTRUST_REGISTRY_ADDRESS`` and
    ``DEPLOYER_PRIVATE_KEY``; :meth:`Settings.validate_for_live_chain` fails fast when any is
    missing, and Monad mainnet (143) is refused outright.

``check_registry_deployed()`` uses a dependency-free JSON-RPC call, so deployment status can
be verified against a public RPC without any credential - that check is what
``DEPLOYMENT.md`` documents.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ConfigError, Settings
from .hashing import keccak256

logger = logging.getLogger("agenttrust.chain")

#: Number of criteria the cohort is ordered on; told to the contract so it can evaluate the
#: Kendall's W significance test with `df = RANKED_OBJECTS - 1`.
RANKED_OBJECTS = 4

#: Decision enum ordinals as encoded in the Solidity contract (see contracts/interfaces).
#: 0 = None, 1 = Approved, 2 = Rejected, 3 = Escalated, 4 = InsufficientValidators,
#: 5 = InsufficientBaseline.
DECISION_CODE: dict[str, int] = {
    "Approved": 1,
    "Rejected": 2,
    "Escalated": 3,
    "InsufficientValidators": 4,
    "InsufficientBaseline": 5,
}

#: Fixed-point scale used for divergence readings on-chain (milli-units).
MILLI = 1000

#: Gas headroom over `eth_estimateGas`, as a fraction. Monad bills the full gas limit, so this
#: is kept tight on purpose: 20% over the estimate rather than a blanket ceiling.
GAS_HEADROOM_NUM = 12
GAS_HEADROOM_DEN = 10

#: Gas limit used only when `eth_estimateGas` fails. Deliberately below the old blanket
#: 3,000,000: the cohort calls measured here land far under it.
GAS_FALLBACK = 500_000

#: Cohort on-chain identity sources, in resolution order. See
#: :func:`resolve_cohort_identities` for why there are three.
COHORT_ADDRESSES_ENV = "AGENTTRUST_COHORT_ADDRESSES"
COHORT_ADDRESS_ENV_PREFIX = "AGENTTRUST_VALIDATOR_ADDRESS_"
COHORT_KEY_ENV_PREFIX = "AGENTTRUST_VALIDATOR_PRIVATE_KEY_"
COHORT_SEED_ENV = "AGENTTRUST_COHORT_SEED"



def decision_code(decision: Any) -> int:
    """Map a :class:`divergence.core.Decision` (or its string) to the on-chain ordinal."""
    value = getattr(decision, "value", decision)
    return DECISION_CODE.get(str(value), 0)


def to_milli(value: float | None) -> int:
    """Scale a divergence reading to a non-negative integer for on-chain storage."""
    if value is None:
        return 0
    return max(0, int(round(float(value) * MILLI)))


class LedgerWriter:
    """``dry-run`` chain writer: an append-only local ledger with a machine-readable shape.

    Not a fake blockchain. The ledger file records ``mode``, ``chainId`` and a ``simulated``
    flag so no reader can confuse it with a transaction receipt.
    """

    def __init__(self, artifacts_dir: Path, chain_id: int, *, frontend_dir: Path | None = None) -> None:
        self.artifacts_dir = Path(artifacts_dir)
        self.frontend_dir = Path(frontend_dir) if frontend_dir else None
        self.chain_id = chain_id
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.artifacts_dir / "ledger.jsonl"
        self.latest_path = self.artifacts_dir / "latest-record.json"
        #: Entries written by *this* instance. The panel feed is published from this list, not
        #: from the whole ledger: the ledger is an append-only history and would otherwise make
        #: the dashboard show every run ever recorded instead of the one just produced.
        self.session_entries: list[dict[str, Any]] = []

    def submit(self, record: Any) -> dict[str, Any]:
        receipt = {
            "mode": "dry-run",
            "simulated": True,
            "chainId": self.chain_id,
            "registryAddress": None,
            "validationId": record.validation_id,
            "txHash": None,
            "explorerUrl": None,
            "note": (
                "dry-run ledger write: no transaction was sent. Set CHAIN_MODE=live with "
                "RPC_URL_10143 + AGENTTRUST_REGISTRY_ADDRESS + DEPLOYER_PRIVATE_KEY to write "
                "to Monad Testnet 10143."
            ),
            "writtenAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        # The receipt is embedded in the record itself so each ledger line is self-describing
        # and the panel can label a record's chain status without joining two files.
        payload = {**record.as_dict(), "chain": receipt}
        entry = {"receipt": receipt, "record": payload}

        with self.ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self.latest_path.write_text(
            json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        self.session_entries.append(entry)
        self._publish_frontend_feed()

        logger.info("dry-run ledger appended: %s", self.ledger_path)
        return receipt

    def read_ledger(self) -> list[dict[str, Any]]:
        if not self.ledger_path.is_file():
            return []
        entries: list[dict[str, Any]] = []
        for line in self.ledger_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("skipping malformed ledger line")
        return entries

    def _publish_frontend_feed(self) -> None:
        """Refresh ``frontend/data/records.json`` so the static panel has real data.

        Only the records produced by this writer instance are published. ``ledger.jsonl``
        keeps the full append-only history for auditing, while the panel feed always reflects
        the run that just happened - a dashboard that accumulates every historical run is not
        a verification panel.
        """
        if self.frontend_dir is None:
            return
        entries = self.session_entries or self.read_ledger()
        feed = {
            "source": "dry-run-ledger",
            "simulated": True,
            "chainId": self.chain_id,
            "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "run": {
                "recordsInThisRun": len(entries),
                "ledgerEntriesTotal": len(self.read_ledger()),
                "ledger": str(self.ledger_path),
            },
            "records": [entry["record"] for entry in entries],
        }
        data_dir = self.frontend_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "records.json").write_text(
            json.dumps(feed, indent=2, ensure_ascii=False), encoding="utf-8"
        )


@dataclass(frozen=True)
class CohortIdentity:
    """One cohort member's on-chain identity, in ``validators/cohort.yaml`` order."""

    agent: str
    address: str
    private_key: str | None = None
    source: str = "unknown"

    @property
    def can_self_submit(self) -> bool:
        """``True`` when this member can sign its own ``submitCohortVerdict`` transaction."""
        return self.private_key is not None


def _address_of(private_key: str) -> str:
    """Derive the checksummed address for a private key (needs the web3 signing stack)."""
    try:
        from eth_account import Account
    except ImportError as exc:  # pragma: no cover - live mode only
        raise ConfigError(
            "deriving cohort addresses needs eth-account: pip install -r requirements-chain.txt"
        ) from exc
    return Account.from_key(private_key).address


def derive_cohort_key(seed: str, index: int) -> str:
    """Deterministic testnet key for cohort member ``index`` (1-based) from a shared seed.

    A proof-of-concept convenience, and labelled as one: it lets a single funded deployer run a
    full cohort on testnet without custodying five separate secrets. Real deployments give each
    validation agent its own key and set ``AGENTTRUST_VALIDATOR_ADDRESS_<n>`` (plus the matching
    key) instead - the contract does not care which route produced the address, only that the
    attestation recovers to a member of the cohort.
    """
    if index < 1:
        raise ConfigError(f"cohort index must be 1-based, got {index}")
    return "0x" + keccak256(f"{seed}:{index}".encode("utf-8")).hex()


def resolve_cohort_identities(record: Any) -> list[CohortIdentity]:
    """Resolve one on-chain identity per cohort member, honouring this resolution order.

    1. ``AGENTTRUST_VALIDATOR_PRIVATE_KEY_<n>`` - explicit per-member keys. The addresses are
       derived from them, so the pair can never be mismatched.
    2. ``AGENTTRUST_COHORT_ADDRESSES`` (comma separated) or ``AGENTTRUST_VALIDATOR_ADDRESS_<n>``
       - addresses only. Valid only when the submitting account *is* that address, because
       without a key the orchestrator cannot produce an attestation.
    3. ``AGENTTRUST_COHORT_SEED`` - derive all members deterministically (see
       :func:`derive_cohort_key`).

    Raises :class:`ConfigError` when no source is configured, when a source yields fewer
    identities than the cohort has members, or when two members resolve to the same address -
    the contract rejects a duplicate cohort member, so failing here keeps the error readable.
    """
    names = [str(member.get("agent")) for member in record.cohort]
    count = len(names)
    if count == 0:
        raise ConfigError("record carries no cohort members; nothing to resolve")

    identities: list[CohortIdentity] = []

    # --- 1. explicit per-member private keys
    keys = [
        (os.environ.get(f"{COHORT_KEY_ENV_PREFIX}{i}", "") or "").strip()
        for i in range(1, count + 1)
    ]
    if any(keys):
        missing = [i + 1 for i, value in enumerate(keys) if not value]
        if missing:
            raise ConfigError(
                f"{COHORT_KEY_ENV_PREFIX}n is set for some members but missing for "
                f"{missing}. Set all {count} or none."
            )
        for name, key in zip(names, keys):
            identities.append(CohortIdentity(name, _address_of(key), key, "per-member key"))

    # --- 2. addresses only
    if not identities:
        declared = _declared_addresses(count)
        if declared:
            for name, address in zip(names, declared):
                identities.append(CohortIdentity(name, address, None, "declared address"))

    # --- 3. seed-derived
    if not identities:
        seed = (os.environ.get(COHORT_SEED_ENV, "") or "").strip()
        if seed:
            for index, name in enumerate(names, start=1):
                key = derive_cohort_key(seed, index)
                identities.append(CohortIdentity(name, _address_of(key), key, "derived from seed"))

    if not identities:
        raise ConfigError(
            "no cohort on-chain identities: set one of "
            f"{COHORT_KEY_ENV_PREFIX}n (per-member keys), {COHORT_ADDRESSES_ENV} / "
            f"{COHORT_ADDRESS_ENV_PREFIX}n (addresses), or {COHORT_SEED_ENV} "
            "(deterministic testnet keys). Required only for --chain live."
        )

    lowered = [identity.address.lower() for identity in identities]
    duplicates = {a for a in lowered if lowered.count(a) > 1}
    if duplicates:
        raise ConfigError(
            f"duplicate cohort address(es) {sorted(duplicates)}: the registry rejects a repeated "
            "cohort member, and two identical validators are one validator anyway."
        )
    return identities


def _declared_addresses(count: int) -> list[str]:
    """Read addresses from the comma list, then from the indexed vars; '' when unset."""
    combined = (os.environ.get(COHORT_ADDRESSES_ENV, "") or "").strip()
    if combined:
        parts = [part.strip() for part in combined.split(",") if part.strip()]
        if len(parts) != count:
            raise ConfigError(
                f"{COHORT_ADDRESSES_ENV} lists {len(parts)} addresses but the cohort has "
                f"{count} members."
            )
        return parts
    indexed = [
        (os.environ.get(f"{COHORT_ADDRESS_ENV_PREFIX}{i}", "") or "").strip()
        for i in range(1, count + 1)
    ]
    if any(indexed):
        missing = [i + 1 for i, value in enumerate(indexed) if not value]
        if missing:
            raise ConfigError(
                f"{COHORT_ADDRESS_ENV_PREFIX}n is set for some members but missing for "
                f"{missing}. Set all {count} or none."
            )
        return indexed
    return []


def resolve_cohort_addresses(record: Any) -> list[str]:
    """The cohort's addresses, in member order. See :func:`resolve_cohort_identities`."""
    return [identity.address for identity in resolve_cohort_identities(record)]


def _as_bytes32(value: Any) -> bytes:
    """Coerce a ``0x``-prefixed 32-byte hex string to bytes, loudly on a wrong length."""
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
    else:
        text = str(value)
        if text.startswith("0x") or text.startswith("0X"):
            text = text[2:]
        try:
            raw = bytes.fromhex(text)
        except ValueError as exc:
            raise ConfigError(f"not valid hex for bytes32: {value!r}") from exc
    if len(raw) != 32:
        raise ConfigError(f"bytes32 requires 32 bytes, got {len(raw)} from {value!r}")
    return raw


def verdict_attestation_digest(
    request_hash: str,
    validator_address: str,
    response: int,
    verdict_hash: Any,
) -> bytes:
    """The digest a cohort member signs so the orchestrator may relay its verdict.

    Mirrors the contract exactly: ``keccak256(abi.encode(requestHash, validator, response,
    verdictHash))``. ``abi.encode`` pads every value to a 32-byte word, so the encoding is
    built by hand rather than by pulling in an ABI codec - it is four words, and doing it
    explicitly is what makes it checkable against the Solidity line.

    The contract then wraps this in the EIP-191 personal-sign envelope
    (``keccak256("\\x19Ethereum Signed Message:\\n32" || digest)``), which is what
    ``eth_account.messages.encode_defunct`` produces.
    """
    digest_input = (
        _as_bytes32(request_hash)
        + b"\x00" * 12
        + bytes.fromhex(validator_address[2:])
        + int(response).to_bytes(32, "big")
        + _as_bytes32(verdict_hash)
    )
    return keccak256(digest_input)


def sign_verdict_attestation(
    request_hash: str,
    validator_address: str,
    response: int,
    verdict_hash: Any,
    private_key: str,
) -> str:
    """EIP-191 signature bytes (``0x``-prefixed) for :func:`verdict_attestation_digest`."""
    try:
        from eth_account import Account
        from eth_account.messages import encode_defunct
    except ImportError as exc:  # pragma: no cover - live mode only
        raise ConfigError(
            "signing a relayed verdict needs eth-account: pip install -r requirements-chain.txt"
        ) from exc
    digest = verdict_attestation_digest(request_hash, validator_address, response, verdict_hash)
    signed = Account.sign_message(encode_defunct(primitive=digest), private_key=private_key)
    return "0x" + signed.signature.hex()


class RegistryClient:
    """``live`` chain writer: signs transactions against the deployed registry.

    Requires ``web3`` (``pip install -r requirements-chain.txt``). Kept out of the core
    requirements so the demo and test suite stay dependency-free and reproducible.
    """

    def __init__(self, settings: Settings, abi_path: Path | None = None) -> None:
        settings.validate_for_live_chain()
        try:
            from web3 import Web3  # noqa: F401
        except ImportError as exc:  # pragma: no cover - exercised only in live mode
            raise ConfigError(
                "live chain mode needs web3: pip install -r requirements-chain.txt"
            ) from exc

        from web3 import Web3
        from web3.middleware import ExtraDataToPOAMiddleware  # type: ignore[import-not-found]

        self.settings = settings
        self.w3 = Web3(Web3.HTTPProvider(settings.rpc_url, request_kwargs={"timeout": 30}))
        try:  # Monad is an EVM chain with a non-zero block extraData field
            self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        except Exception:  # noqa: BLE001 - middleware name differs across web3 versions
            logger.warning("could not install the PoA middleware; continuing without it")
        self.abi = json.loads(
            (abi_path or default_abi_path()).read_text(encoding="utf-8")
        )
        self.contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(settings.registry_address), abi=self.abi
        )
        self.account = self.w3.eth.account.from_key(settings.requester_private_key)

    def submit(self, record: Any) -> dict[str, Any]:  # pragma: no cover - network path
        """Open the cohort request, submit each verdict, then finalise with the decision.

        Signatures mirror ``AgentTrustValidationRegistry`` exactly. The cohort addresses come
        from the per-member ``address_env`` declarations in ``cohort.yaml`` (see
        :func:`resolve_cohort_addresses`); live mode refuses to run without them rather than
        reusing one address for every member, which the contract would reject as a duplicate.
        """
        cohort_identities = resolve_cohort_identities(record)
        by_name = {identity.agent: identity for identity in cohort_identities}
        declared_names = [str(member.get("agent")) for member in record.cohort]
        if [identity.agent for identity in cohort_identities] != declared_names:
            raise ConfigError(
                "cohort identity order does not match the record's cohort order "
                f"({[i.agent for i in cohort_identities]} vs {declared_names}); "
                "the contract requires the cohort array in this exact order."
            )
        cohort_addresses = [identity.address for identity in cohort_identities]
        tx_hashes: list[dict[str, str]] = []

        tx_hashes.append(
            self._send(
                self.contract.functions.openCohortValidation(
                    record.validation_id,
                    self._agent_id(record),
                    record.task.description,
                    to_milli(record.d_base or 0),
                    len(record.rounds),
                    cohort_addresses,
                ),
                "openCohortValidation",
            )
        )

        # Verdicts can arrive two ways, and the contract accepts both:
        #   * `submitCohortVerdict` - the member submits from its own address;
        #   * `attestCohortVerdict`  - anyone relays the member's EIP-191 signature, so the
        #     validation agents need no gas. This is the path a locally-run cohort uses.
        # Which one applies is a property of the identity, not a flag, so it cannot drift.
        verdicts = record.rounds[-1].verdicts if record.rounds else []
        for verdict in verdicts:
            identity = by_name.get(verdict.agent)
            if identity is None:
                raise ConfigError(
                    f"verdict from {verdict.agent!r} has no cohort identity; the registry would "
                    "reject it with NotACohortMember"
                )
            verdict_hash = verdict.verdict_hash()
            layers = verdict_layers(verdict)
            response = int(verdict.response)
            d_disc, d_traj, d_end = (to_milli(layer) for layer in layers)

            if identity.address.lower() == self.account.address.lower():
                tx_hashes.append(
                    self._send(
                        self.contract.functions.submitCohortVerdict(
                            record.validation_id,
                            response,
                            _as_bytes32(verdict_hash),
                            verdict.evidence_uri,
                            verdict.tag,
                            d_disc,
                            d_traj,
                            d_end,
                        ),
                        f"submitCohortVerdict({verdict.agent})",
                    )
                )
                continue

            if not identity.private_key:
                raise ConfigError(
                    f"cohort member {verdict.agent!r} resolves to {identity.address} "
                    f"(source: {identity.source}) but no private key is available to attest for "
                    "it, and the requester account is a different address. Set "
                    f"{COHORT_KEY_ENV_PREFIX}n or {COHORT_SEED_ENV}."
                )
            signature = sign_verdict_attestation(
                record.validation_id, identity.address, response, verdict_hash,
                identity.private_key,
            )
            tx_hashes.append(
                self._send(
                    self.contract.functions.attestCohortVerdict(
                        record.validation_id,
                        identity.address,
                        response,
                        _as_bytes32(verdict_hash),
                        verdict.evidence_uri,
                        verdict.tag,
                        d_disc,
                        d_traj,
                        d_end,
                        signature,
                    ),
                    f"attestCohortVerdict({verdict.agent} -> {identity.address})",
                )
            )

        final = record.rounds[-1].reading if record.rounds else None
        divergence_input = {
            "dDiscMilli": to_milli(final.d_disc if final else 0),
            "dTrajMilli": to_milli(final.d_traj if final else 0),
            "dEndMilli": to_milli(final.d_end if final else 0),
            "dTotalMilli": to_milli(final.d_total if final else 0),
            "dRelMilli": to_milli(record.d_rel),
            "kendallWMilli": min(to_milli(final.kendall.w if final and final.kendall else 0), 65535),
            "chiSquareMilli": int(
                round((final.kendall.chi_square if final and final.kendall else 0.0) * MILLI)
            ),
        }
        tx_hashes.append(
            self._send(
                self.contract.functions.finalizeValidation(
                    record.validation_id,
                    decision_code(record.final_decision),
                    len(record.rounds),
                    RANKED_OBJECTS,
                    divergence_input,
                ),
                "finalizeValidation",
            )
        )

        return {
            "mode": "live",
            "simulated": False,
            "chainId": self.settings.chain_id,
            "registryAddress": self.settings.registry_address,
            "validationId": record.validation_id,
            "txHash": tx_hashes[-1]["txHash"] if tx_hashes else None,
            "transactions": tx_hashes,
            "explorerUrl": f"{self.settings.explorer_url.rstrip('/')}/tx/"
            + (tx_hashes[-1]["txHash"] if tx_hashes else ""),
        }

    def _agent_id(self, record: Any) -> int:
        raw = record.task.payload.get("agentId", 0)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    def _send(self, function: Any, label: str) -> dict[str, str]:  # pragma: no cover
        """Estimate, price, pre-flight the balance, then send.

        The gas limit is estimated rather than fixed, because Monad Testnet bills the full gas
        *limit*, not the gas used: a confirmed transaction on 10143 reports
        `gasUsed == gasLimit`, so a blanket 3,000,000 limit costs
        ``3_000_000 x gasPrice`` whether the call needed 60,000 or 600,000. A hard-coded limit
        is therefore not a safety margin - it is the invoice.
        """
        from_address = self.account.address
        try:
            estimated = int(function.estimate_gas({"from": from_address}))
        except Exception as exc:  # noqa: BLE001 - estimation is best-effort, not essential
            logger.warning("gas estimation failed for %s (%s); using the fallback limit", label, exc)
            estimated = 0
        gas = (estimated * GAS_HEADROOM_NUM) // GAS_HEADROOM_DEN + 1_000 if estimated else GAS_FALLBACK
        gas_price = int(self.w3.eth.gas_price)
        cost = gas * gas_price

        balance = int(self.w3.eth.get_balance(from_address))
        if balance < cost:
            raise ConfigError(
                f"insufficient balance for {label}: {gas} gas at {gas_price / 1e9:.1f} gwei "
                f"costs {cost / 1e18:.6f} MON, and {from_address} holds {balance / 1e18:.6f} MON. "
                "Top up from https://faucet.monad.xyz. Monad bills the full gas limit, so the "
                "estimate above is the actual charge, not an upper bound."
            )

        tx = function.build_transaction(
            {
                "from": from_address,
                "nonce": self.w3.eth.get_transaction_count(from_address),
                "chainId": self.settings.chain_id,
                "gas": gas,
                "gasPrice": gas_price,
            }
        )
        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
        digest = tx_hash.hex()
        if not digest.startswith("0x"):
            digest = "0x" + digest
        logger.info("%s confirmed in block %s", label, receipt.get("blockNumber"))
        return {"label": label, "txHash": digest, "block": str(receipt.get("blockNumber"))}


def verdict_layers(verdict: Any) -> tuple[float, float, float]:
    """Per-verdict layer readings recorded on-chain alongside the aggregated score.

    A single verdict has no pairwise distance of its own, so its recorded layers are the
    magnitudes that feed the layer metrics: plan length, path length and terminal magnitude,
    normalised into the same milli scale. Kept explicit so nobody misreads them as the
    aggregate ``D_*`` values.
    """
    actions = list(getattr(verdict, "actions", []) or [])
    trajectory = list(getattr(verdict, "trajectory", []) or [])
    terminal = getattr(verdict, "terminal", None) or []
    return (
        float(len(actions)),
        float(len(trajectory)),
        float(sum(float(v) * float(v) for v in terminal) ** 0.5),
    )


def default_abi_path() -> Path:
    return Path(__file__).resolve().parent.parent / "contracts" / "abis" / "AgentTrustValidationRegistry.json"


def make_chain_writer(
    settings: Settings,
    *,
    frontend_dir: Path | None = None,
) -> LedgerWriter | RegistryClient:
    if settings.chain_mode == "live":
        return RegistryClient(settings)
    return LedgerWriter(settings.artifacts_dir, settings.chain_id, frontend_dir=frontend_dir)


# --------------------------------------------------------------------------- RPC helpers
def rpc_call(rpc_url: str, method: str, params: list[Any], *, timeout: float = 15.0) -> Any:
    """Minimal JSON-RPC 2.0 call. No credential, no dependency."""
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request(
        rpc_url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"RPC {method} failed: HTTP {exc.code}") from exc
    if "error" in payload:
        raise RuntimeError(f"RPC {method} error: {payload['error']}")
    return payload.get("result")


def check_registry_deployed(
    address: str,
    rpc_url: str,
    *,
    expected_chain_id: int = 10143,
) -> dict[str, Any]:
    """Verify a registry address actually has bytecode on the expected chain.

    This is the check ``DEPLOYMENT.md`` documents and the acceptance criterion "the contract
    address is queryable on the 10143 explorer" reduces to. Runs with no credential against a
    public RPC.
    """
    observed_chain_id = int(rpc_call(rpc_url, "eth_chainId", []), 16)
    code = rpc_call(rpc_url, "eth_getCode", [address, "latest"])
    deployed = bool(code) and code not in ("0x", "0x0")
    return {
        "address": address,
        "rpcUrl": rpc_url,
        "expectedChainId": expected_chain_id,
        "observedChainId": observed_chain_id,
        "chainIdMatches": observed_chain_id == expected_chain_id,
        "hasBytecode": deployed,
        "bytecodeSize": max(len(code) - 2, 0) // 2 if isinstance(code, str) else 0,
        "checkedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def wait_for_rpc(rpc_url: str, *, attempts: int = 5, delay: float = 1.5) -> bool:
    """Poll ``eth_chainId`` until the endpoint answers (or give up)."""
    for attempt in range(attempts):
        try:
            rpc_call(rpc_url, "eth_chainId", [])
            return True
        except Exception:  # noqa: BLE001
            if attempt == attempts - 1:
                return False
            time.sleep(delay)
    return False
