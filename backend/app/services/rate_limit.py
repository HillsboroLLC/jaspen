import os, time, threading
from functools import wraps

# Optional Redis
try:
    from redis import Redis
except Exception:
    Redis = None

_REDIS = None
_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
if Redis:
    try:
        _REDIS = Redis.from_url(_URL, decode_responses=True, socket_timeout=0.5)
        _REDIS.ping()
    except Exception:
        _REDIS = None

_store = {}
_lock = threading.Lock()

def _now() -> int:
    return int(time.time())

def _client_id(request) -> str:
    # Deterministic per-session if provided (useful for tests)
    sid = request.headers.get("X-Session-ID")
    if sid:
        return f"sid:{sid}"
    # Otherwise key by client IP (respect proxy headers)
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        ip = xff.split(",")[0].strip()
    else:
        ip = request.headers.get("X-Real-IP") or request.remote_addr or "unknown"
    return f"ip:{ip}"

def _key(bucket: str, client: str) -> str:
    return f"sekki:rl:{bucket}:{client}"

def _bump(bucket: str, limit: int, window: int, request):
    client = _client_id(request)
    key = _key(bucket, client)
    now = _now()

    if _REDIS:
        pipe = _REDIS.pipeline(True)
        pipe.incr(key)
        pipe.expire(key, window)
        count, _ = pipe.execute()
        remaining = max(0, limit - int(count))
        return int(count), remaining

    # In-memory fallback (fixed window)
    with _lock:
        count, exp = _store.get(key, (0, now + window))
        if exp < now:
            count, exp = 0, now + window
        count += 1
        _store[key] = (count, exp)
        remaining = max(0, limit - count)
        return count, remaining

def guard_or_429(bucket: str, limit: int = 20, window: int = 60):
    from flask import request, jsonify
    count, remaining = _bump(bucket, limit, window, request)
    if count > limit:
        body = {"error": "rate_limited", "bucket": bucket, "limit": limit,
                "remaining": remaining, "count": count}
        resp = jsonify(body)
        try:
            resp.headers["Retry-After"] = str(window)
            resp.headers["X-RateLimit-Limit"] = str(limit)
            resp.headers["X-RateLimit-Remaining"] = str(remaining)
        except Exception:
            pass
        return resp, 429
    return None

def rate_limit(bucket: str, limit: int = 20, window: int = 60):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            hit = guard_or_429(bucket, limit=limit, window=window)
            if hit is not None:
                return hit
            return fn(*a, **kw)
        return wrapper
    return deco
# writable-by-sekki

def _ctx_preamble():
    """Build a one-line system preamble from discuss context (if any)."""
    try:
        from flask import request
        from app.services.context_store import get_context
        sid = request.cookies.get("sekki_sid") or request.headers.get("X-Session-ID") or ""
        ctx = get_context(sid) if sid else None
    except Exception:
        ctx = None
    if not isinstance(ctx, dict):
        return ""
    name  = (ctx.get("meta") or {}).get("name") or ""
    summ  = ctx.get("summary") or ""
    aid   = ctx.get("analysis_id") or ""
    score = ctx.get("score")
    parts = [
        "You are discussing a specific analysis with the user.",
        f"Analysis ID: {aid}" if aid else "",
        f"Name: {name}"       if name else "",
        f"Summary: {summ}"    if summ else "",
        f"Score: {score}"     if isinstance(score, (int, float)) else "",
        "Use these details when answering. Avoid repeating the same overview.",
    ]
    return " ".join(p for p in parts if p)

def _build_ctx_preamble():
    """One-line grounding string from discuss context (if any)."""
    try:
        from flask import request
        from app.services.context_store import get_context
        sid = request.cookies.get("sekki_sid") or request.headers.get("X-Session-ID") or ""
        ctx = get_context(sid) if sid else None
    except Exception:
        ctx = None
    if not isinstance(ctx, dict):
        return ""
    name  = (ctx.get("meta") or {}).get("name") or ""
    summ  = ctx.get("summary") or ""
    aid   = ctx.get("analysis_id") or ""
    score = ctx.get("score")
    parts = [
        "You are discussing a specific analysis with the user.",
        f"Analysis ID: {aid}" if aid else "",
        f"Name: {name}"       if name else "",
        f"Summary: {summ}"    if summ else "",
        f"Score: {score}"     if isinstance(score, (int, float)) else "",
        "Use these details when answering; avoid repeating the same overview.",
    ]
    return " ".join(p for p in parts if p)
