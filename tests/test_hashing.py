"""keccak-256 tests.

ERC-8004 identifies a request by ``keccak256`` of its payload, so this implementation is on the
critical path for on-chain correctness. Validated against published Ethereum vectors.
"""

from __future__ import annotations

import pytest

from orchestrator.hashing import (
    canonical_json,
    keccak256,
    keccak256_hex,
    request_hash,
    request_payload,
)
from validators.base import TaskRequest

# Published keccak-256 vectors (the Ethereum variant, not NIST SHA3-256).
VECTORS = [
    (b"", "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"),
    (
        b"abc",
        "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45",
    ),
    (
        b"The quick brown fox jumps over the lazy dog",
        "4d741b6f1eb29cb2a9b9911c82f56fa8d73b04959d3d9d222895df6c0b28aa15",
    ),
]


@pytest.mark.parametrize(("payload", "expected"), VECTORS)
def test_keccak256_matches_published_vectors(payload: bytes, expected: str) -> None:
    assert keccak256(payload).hex() == expected


def test_keccak256_hex_prefixes_with_0x() -> None:
    digest = keccak256_hex(b"agenttrust")
    assert digest.startswith("0x")
    assert len(digest) == 66


def test_output_is_32_bytes() -> None:
    assert len(keccak256(b"anything")) == 32


def test_not_sha3_256() -> None:
    """Guards against someone 'fixing' the padding to the NIST variant."""
    import hashlib

    assert keccak256(b"") != hashlib.sha3_256(b"").digest()


def test_long_input_crosses_the_rate_boundary() -> None:
    """Exercises multi-block absorption (rate is 136 bytes)."""
    payload = bytes(range(256)) * 3
    first = keccak256(payload)
    assert len(first) == 32
    assert keccak256(payload) == first  # deterministic
    assert keccak256(payload[:-1]) != first


def test_canonical_json_is_key_order_independent() -> None:
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})


def test_request_hash_is_deterministic() -> None:
    payload = {"task_id": "t", "cohort": ["a", "b"]}
    assert request_hash(payload) == request_hash(payload)
    assert request_hash(payload).startswith("0x")


def test_request_payload_includes_task_and_cohort() -> None:
    task = TaskRequest(task_id="t1", description="d", actions=["a"], constraints=["c"], d_base=0.5)
    payload = request_payload(task, ["z-validator", "a-validator"])
    assert payload["task_id"] == "t1"
    assert payload["cohort"] == ["a-validator", "z-validator"]  # sorted -> order independent


def test_different_cohorts_produce_different_request_hashes() -> None:
    task = TaskRequest(task_id="t1", description="d", d_base=0.5)
    assert request_hash(request_payload(task, ["a", "b"])) != request_hash(
        request_payload(task, ["a", "c"])
    )


def test_nonce_makes_a_repeat_run_a_distinct_request() -> None:
    """The registry reverts on a repeated requestHash, so a re-run needs a fresh nonce."""
    cohort = ["a", "b"]
    default = TaskRequest(task_id="t1", description="d", d_base=0.5)
    same = TaskRequest(task_id="t1", description="d", d_base=0.5)
    assert request_payload(default, cohort)["nonce"] == 0
    assert request_hash(request_payload(default, cohort)) == request_hash(request_payload(same, cohort))

    replayed = TaskRequest(task_id="t1", description="d", d_base=0.5, payload={"nonce": 2})
    assert request_payload(replayed, cohort)["nonce"] == 2
    assert request_hash(request_payload(replayed, cohort)) != request_hash(
        request_payload(default, cohort)
    )
