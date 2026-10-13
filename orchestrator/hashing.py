"""ERC-8004 request commitments.

ERC-8004 defines ``requestHash`` as ``keccak256`` of the request payload. The divergence
library deliberately stays free of crypto dependencies, so keccak-256 lives here as a
self-contained implementation with published test vectors.

The alternative - pulling in ``pycryptodome`` or ``eth-hash`` - would make the demo depend on
a compiled wheel for something used in exactly one place. The implementation below is
validated against the canonical empty-string digest in ``tests/test_hashing.py``.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

# Keccak-f[1600] round constants.
_RC = (
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
)

# Rotation offsets, indexed [_ROT[x][y]] with lanes addressed as A[x][y].
_ROT = (
    (0, 36, 3, 41, 18),
    (1, 44, 10, 45, 2),
    (62, 6, 43, 15, 61),
    (28, 55, 25, 21, 56),
    (27, 20, 39, 8, 14),
)

_MASK = (1 << 64) - 1

#: Keccak-256 rate in bytes (1600 - 2*256 bits, as bytes).
_RATE = 136

#: Digest length in bytes.
_DIGEST = 32


def _rot(value: int, shift: int) -> int:
    if shift == 0:
        return value
    return ((value << shift) | (value >> (64 - shift))) & _MASK


def _keccak_f1600(state: list[list[int]]) -> None:
    """In-place Keccak-f[1600] permutation over a 5x5 lane matrix."""
    for rnd in range(24):
        # theta
        c = [state[x][0] ^ state[x][1] ^ state[x][2] ^ state[x][3] ^ state[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rot(c[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                state[x][y] ^= d[x]

        # rho + pi
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                b[y][(2 * x + 3 * y) % 5] = _rot(state[x][y], _ROT[x][y])

        # chi
        for x in range(5):
            for y in range(5):
                state[x][y] = b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y] & _MASK)

        # iota
        state[0][0] ^= _RC[rnd]


def keccak256(data: bytes) -> bytes:
    """Keccak-256 digest (the Ethereum variant, not NIST SHA3-256)."""
    padded = bytearray(data)
    padded.append(0x01)  # Keccak domain separation
    while len(padded) % _RATE != 0:
        padded.append(0x00)
    padded[-1] |= 0x80

    state = [[0] * 5 for _ in range(5)]
    for offset in range(0, len(padded), _RATE):
        block = padded[offset : offset + _RATE]
        for lane_index in range(_RATE // 8):
            lane = int.from_bytes(block[lane_index * 8 : (lane_index + 1) * 8], "little")
            state[lane_index % 5][lane_index // 5] ^= lane
        _keccak_f1600(state)

    out = bytearray()
    while len(out) < _DIGEST:
        for lane_index in range(_RATE // 8):
            if len(out) >= _DIGEST:
                break
            out += state[lane_index % 5][lane_index // 5].to_bytes(8, "little")
        if len(out) < _DIGEST:
            _keccak_f1600(state)
    return bytes(out[:_DIGEST])


def keccak256_hex(data: bytes) -> str:
    """``0x``-prefixed lowercase keccak-256 digest."""
    return "0x" + keccak256(data).hex()


def canonical_json(payload: Mapping[str, Any]) -> bytes:
    """Deterministic JSON encoding used for every commitment in this repository."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def request_hash(payload: Mapping[str, Any]) -> str:
    """ERC-8004 ``requestHash`` for a request payload: keccak256 of its canonical JSON."""
    return keccak256_hex(canonical_json(payload))


def request_payload(task: Any, cohort_names: list[str]) -> dict[str, Any]:
    """The canonical off-chain payload a ``requestHash`` commits to.

    Includes the task definition *and* the cohort, so two runs with the same task but a
    different validator set are distinct requests - which is what makes the idempotency
    guarantee meaningful rather than accidental.

    ``task.payload["nonce"]`` (default ``0``) is included for the same reason a real requester
    would include one: ``openCohortValidation`` reverts with ``RequestAlreadyExists`` on a
    repeated ``requestHash``, so re-running the *same* task against the *same* registry needs a
    fresh id. Raising the nonce - ``run_demo.py --nonce 2`` - does exactly that, without
    weakening the guarantee that an unchanged request maps to an unchanged id.
    """
    return {
        "schema": "agenttrust.request/v1",
        "task_id": task.task_id,
        "description": task.description,
        "proposed_actions": list(task.actions),
        "constraints": list(task.constraints),
        "observation_space": task.observation_space,
        "max_steps": task.max_steps,
        "d_base": task.d_base,
        "nonce": int(task.payload.get("nonce", 0) or 0),
        "cohort": sorted(cohort_names),
    }
