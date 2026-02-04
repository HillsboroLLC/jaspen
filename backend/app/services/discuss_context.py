import os, json, time, threading, secrets

# Public API (do not change signatures)
__all__ = ["new_sid", "set_ctx", "get_ctx"]

_TTL_SEC = 2 * 60 * 60  # 2h default
_REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
_NS = "sekki:ctx:"  # key namespace

# Try Redis first; if not available, fall back to in-memory.
_redis = None
try:
    from redis import Redis
    _redis = Redis.from_url(_REDIS_URL, decode_responses=True, socket_timeout=2.0)
    # quick probe
    _redis.ping()
except Exception:
    _redis = None

# In-memory fallback store
_store = {}
_lock = threading.Lock()

def new_sid() -> str:
    return f"conv_{secrets.token_hex(8)}"

def set_ctx(sid: str, ctx: dict, ttl: int = _TTL_SEC) -> None:
    ttl = max(60, int(ttl or _TTL_SEC))
    if _redis:
        _redis.setex(_NS + sid, ttl, json.dumps(ctx, ensure_ascii=False))
        return
    exp = time.time() + ttl
    with _lock:
        _store[sid] = (exp, ctx)

def get_ctx(sid: str) -> dict | None:
    if not sid:
        return None
    if _redis:
        data = _redis.get(_NS + sid)
        if not data:
            return None
        try:
            return json.loads(data)
        except Exception:
            return None
    now = time.time()
    with _lock:
        rec = _store.get(sid)
        if not rec:
            return None
        exp, ctx = rec
        if exp < now:
            _store.pop(sid, None)
            return None
        return ctx


# --- begin: minimal reply memory (idempotent) ---
def remember_reply(sid: str, text: str, n: int = 6):
    key = _NS + f"mem:{sid}"
    if _redis:
        _redis.lpush(key, (text or "")[:600])
        _redis.ltrim(key, 0, n-1)
        _redis.expire(key, _TTL_SEC)
        return
    with _lock:
        arr = _store.setdefault("mem:"+sid, [])
        arr.insert(0, (text or "")[:600]); del arr[n:]

def recent_replies(sid: str, n: int = 6):
    key = _NS + f"mem:{sid}"
    if _redis:
        vals = _redis.lrange(key, 0, n-1)
        return vals or []
    with _lock:
        return list(_store.get("mem:"+sid, []))[:n]
# --- end: minimal reply memory ---
