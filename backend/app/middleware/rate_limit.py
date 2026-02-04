from __future__ import annotations
import os
from typing import Optional
from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

def _default_limits() -> list[str]:
    # e.g. "120 per minute"
    d = os.getenv("RATE_LIMIT_DEFAULT", "120 per minute")
    return [d] if d else []

def init_rate_limiter(app: Flask) -> Optional[Limiter]:
    """
    Returns a configured Limiter or None if ENABLE_RATE_LIMIT != true.
    Never raises; logs to app.logger on issues and returns None.
    """
    if os.getenv("ENABLE_RATE_LIMIT", "false").lower() != "true":
        return None

    storage_uri = os.getenv("RATE_LIMIT_STORAGE", "").strip()  # e.g. redis://127.0.0.1:6379/2
    strategy    = os.getenv("RATE_LIMIT_STRATEGY", "fixed-window").strip()

    kwargs = {
        "key_func": get_remote_address,
        "default_limits": _default_limits(),
        "strategy": strategy or "fixed-window",
    }
    if storage_uri:
        kwargs["storage_uri"] = storage_uri

    try:
        limiter = Limiter(**kwargs)
        limiter.init_app(app)
        app.logger.info("rate limiter initialized (storage=%s, strategy=%s, defaults=%s)",
                        storage_uri or "memory", kwargs["strategy"], kwargs["default_limits"])
        return limiter
    except Exception as e:
        try:
            app.logger.warning("rate limiter init failed: %s", e)
        except Exception:
            pass
        return None

def apply_blueprint_limits(app: Flask, limiter: Limiter) -> None:
    """
    Apply per-blueprint limits if the blueprints exist.
    Reads RATE_LIMIT_AUTH and RATE_LIMIT_ANALYZE from env.
    """
    if not limiter:
        return

    auth_limit    = os.getenv("RATE_LIMIT_AUTH", "5 per minute")
    analyze_limit = os.getenv("RATE_LIMIT_ANALYZE", "20 per minute")

    try:
        from app.routes.auth import auth_bp
        limiter.limit(auth_limit)(auth_bp)
        app.logger.info("rate limit applied: auth_bp = %s", auth_limit)
    except Exception as e:
        app.logger.info("rate limit: auth_bp not applied (%s)", e)

## TEMP_DISABLE_ANALYZE_BP     try:
## TEMP_DISABLE_ANALYZE_BP         from app.routes.market_iq_analyze import market_iq_analyze_bp
## TEMP_DISABLE_ANALYZE_BP         limiter.limit(analyze_limit)(market_iq_analyze_bp)
## TEMP_DISABLE_ANALYZE_BP         app.logger.info("rate limit applied: market_iq_analyze_bp = %s", analyze_limit)
    except Exception as e:
        app.logger.info("rate limit: market_iq_analyze_bp not applied (%s)", e)
