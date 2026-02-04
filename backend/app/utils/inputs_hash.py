# app/utils/inputs_hash.py
# Deterministic fingerprint for input payloads to stabilize scoring/cache keys.
# - Canonicalizes JSON (sorted keys, trimmed strings, rounded floats)
# - Lets you ignore volatile fields (e.g., session_id, timestamps)
# - Versioned so you can rotate the hash recipe without breaking old keys

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Tuple, Set

_STABLE_VERSION = "inputs-v1"


def _round_float(x: float, places: int = 6) -> float:
    """Round floats to a fixed precision for stability."""
    try:
        return round(float(x), places)
    except Exception:
        return x  # if it can't be coerced, leave it


def _canonicalize(
    value: Any, *, ignore_keys: Set[str] | None = None
) -> Any:
    """
    Convert value into a canonical, JSON-serializable structure:
      - dict -> sorted list of (key, value) pairs
      - list/tuple/set -> list with canonicalized elements (sets sorted)
      - float -> rounded
      - str -> stripped of surrounding whitespace
      - other scalars left as-is
    """
    if isinstance(value, dict):
        out: List[Tuple[str, Any]] = []
        for k in sorted(value.keys()):
            if ignore_keys and k in ignore_keys:
                continue
            out.append((k, _canonicalize(value[k], ignore_keys=ignore_keys)))
        return out

    if isinstance(value, (list, tuple)):
        return [_canonicalize(v, ignore_keys=ignore_keys) for v in value]

    if isinstance(value, set):
        return sorted([_canonicalize(v, ignore_keys=ignore_keys) for v in value])

    if isinstance(value, float):
        return _round_float(value)

    if isinstance(value, str):
        return value.strip()

    # ints, bools, None, Decimal, etc. (as long as json can handle after conversion)
    return value


def compute_inputs_fingerprint(
    payload: Dict[str, Any],
    *,
    version: str = _STABLE_VERSION,
    ignore: Iterable[str] | None = None,
) -> str:
    """
    Create a stable fingerprint for a payload.

    Args:
        payload: dict of inputs used to compute scores/analysis.
        version: recipe version string; change to invalidate old hashes.
        ignore: iterable of top-level keys to drop (e.g., ["session_id","timestamp"]).

    Returns:
        Hex digest string (blake2b/128-bit).
    """
    ignore_keys: Set[str] = set(ignore or [])

    canon = _canonicalize(payload, ignore_keys=ignore_keys)

    # Compact JSON to ensure byte-for-byte stability
    blob = json.dumps(
        {"v": version, "data": canon},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,  # already sorted by _canonicalize
    )

    h = hashlib.blake2b(blob.encode("utf-8"), digest_size=16)  # 128-bit
    return h.hexdigest()


__all__ = ["compute_inputs_fingerprint"]
