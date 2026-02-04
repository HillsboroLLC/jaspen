from __future__ import annotations
import hashlib, json
from decimal import Decimal, ROUND_HALF_UP
try:
    import numpy as np
except Exception:
    np = None

def canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def make_fingerprint(payload: dict) -> str:
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()

def seeded_rng(fp: str):
    if np is None:
        return None
    seed = int(fp[:16], 16) & 0x7FFFFFFF
    return np.random.default_rng(seed)

def dround(x, q: str = "0.1") -> float:
    return float(Decimal(str(x)).quantize(Decimal(q), rounding=ROUND_HALF_UP))
