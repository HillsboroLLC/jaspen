import os


AI_CONVERSATION_SCOPE = "ai-conversation"
_REDIS_SCHEMES = ("redis://", "rediss://", "redis+unix://")


def is_production_runtime():
    environment = (
        os.getenv("APP_ENV")
        or os.getenv("ENV")
        or os.getenv("FLASK_ENV")
        or ""
    ).strip().lower()
    stripe_secret = str(os.getenv("STRIPE_SECRET_KEY") or "").strip()
    return environment in {"production", "prod"} or stripe_secret.startswith("sk_live_")


def resolve_rate_limit_storage_uri():
    """Return the limiter backend, refusing process-local storage in production."""
    storage_uri = str(os.getenv("RATELIMIT_STORAGE_URI") or "").strip()
    if is_production_runtime():
        if not storage_uri:
            raise RuntimeError(
                "RATELIMIT_STORAGE_URI must be configured with a shared Redis URL in production."
            )
        if not storage_uri.startswith(_REDIS_SCHEMES):
            raise RuntimeError(
                "RATELIMIT_STORAGE_URI must use Redis in production; "
                "process-local memory storage is not allowed."
            )
        return storage_uri
    return storage_uri or "memory://"


def assert_rate_limit_storage_available(limiter):
    """Fail startup when the production limiter backend cannot be reached."""
    if not is_production_runtime():
        return
    try:
        available = limiter.limiter.storage.check()
    except Exception as exc:
        raise RuntimeError("The shared rate-limit Redis backend is unavailable.") from exc
    if not available:
        raise RuntimeError("The shared rate-limit Redis backend is unavailable.")


def shared_limit_usage(limiter, rate_key, limit_item, scope=AI_CONVERSATION_SCOPE):
    """Read the same shared counter used by Flask-Limiter enforcement."""
    storage = limiter.limiter.storage
    key = limit_item.key_for(rate_key, scope)
    count = int(storage.get(key) or 0)
    expiry = storage.get_expiry(key) if count else None
    return count, expiry
