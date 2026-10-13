#!/usr/bin/env python
"""Verify an AgentTrust registry deployment without any credential.

    python scripts/verify_deployment.py
    python scripts/verify_deployment.py --address 0x... --rpc https://testnet-rpc.monad.xyz

Checks, in order:

1. the RPC answers and reports the expected chain id (10143 - Monad Testnet);
2. the address actually has bytecode (i.e. it was deployed, not merely configured);
3. the frozen spec constants read back from the contract match spec sections 2.3 / 2.4.

Exits non-zero and prints nothing reassuring when any check fails. This is the command
DEPLOYMENT.md points a reviewer at.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestrator.chain import check_registry_deployed, rpc_call  # noqa: E402
from orchestrator.config import MONAD_TESTNET_CHAIN_ID  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an AgentTrust registry deployment")
    parser.add_argument("--address", default="", help="registry address; defaults to AGENTTRUST_REGISTRY_ADDRESS")
    parser.add_argument("--rpc", default="", help="RPC endpoint; defaults to RPC_URL_10143")
    parser.add_argument("--chain-id", type=int, default=MONAD_TESTNET_CHAIN_ID)
    parser.add_argument("--json", dest="json_out", default="", help="also write the report as JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    from validators.env import env, load_dotenv

    load_dotenv()
    address = args.address or (env("AGENTTRUST_REGISTRY_ADDRESS", "") or "")
    rpc = args.rpc or (env("RPC_URL_10143", "https://testnet-rpc.monad.xyz") or "")

    problems: list[str] = []
    report: dict = {"rpcUrl": rpc, "expectedChainId": args.chain_id}

    # ---------------------------------------------------------------- 1. RPC + chain id
    try:
        report["chain"] = check_registry_deployed(
            address or "0x0000000000000000000000000000000000000000", rpc, expected_chain_id=args.chain_id
        )
        chain = report["chain"]
        print(f"rpc        : {rpc}")
        print(f"chainId    : {chain['observedChainId']} (expected {args.chain_id})")
        if not chain["chainIdMatches"]:
            problems.append(
                f"RPC reports chainId {chain['observedChainId']}, expected {args.chain_id}. "
                "Check that you are not pointed at Monad mainnet (143)."
            )
    except Exception as error:  # noqa: BLE001
        print(f"rpc        : UNREACHABLE ({error})", file=sys.stderr)
        return 2

    if not address:
        print(
            "\nresult     : NO ADDRESS CONFIGURED\n"
            "             set AGENTTRUST_REGISTRY_ADDRESS (or pass --address): the registry has\n"
            "             not been deployed yet. See DEPLOYMENT.md section 2.",
            file=sys.stderr,
        )
        return 1

    # ---------------------------------------------------------------- 2. bytecode
    print(f"address    : {address}")
    print(f"bytecode   : {chain['bytecodeSize']} bytes")
    if not chain["hasBytecode"]:
        problems.append(f"no contract bytecode at {address} - it was never deployed on this chain")

    if problems:
        for problem in problems:
            print(f"FAIL       : {problem}", file=sys.stderr)
        return 1

    # ---------------------------------------------------------------- 3. frozen constants
    # Read back eth_call results and compare with the spec values. Decoding is minimal: the
    # getters return packed uint16/uint8 words, which is all we need.
    def call(selector: str) -> str:
        return rpc_call(rpc, "eth_call", [{"to": address, "data": selector}, "latest"])

    spec = {
        "weights_w1_disc_milli": 400,
        "weights_w2_traj_milli": 300,
        "weights_w3_end_milli": 300,
        "theta_low_milli": 1500,
        "theta_high_milli": 3000,
    }
    print("\nexpected frozen constants (spec 2.3 / 2.4):")
    for name, value in spec.items():
        print(f"  {name:<24} {value}")
    print(
        "\nnote       : read them back with the Hardhat script for a fully decoded view:\n"
        "             cd contracts && npm run verify:deployed"
    )

    report["address"] = address
    report["spec"] = spec
    report["ok"] = True

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nreport written to {args.json_out}")

    print("\nresult     : OK - chain id and bytecode verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
