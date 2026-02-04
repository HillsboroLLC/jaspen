import os
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

def _user_or_ip_key():
    """Request-safe key: cookie 'sekki_access' -> Bearer token -> IP."""
    from flask import request
    tok = request.cookies.get('sekki_access')
    if not tok:
        auth = request.headers.get('Authorization') or ''
        parts = auth.split()
        if len(parts) == 2 and parts[0].lower() == 'bearer':
            tok = parts[1]
        elif parts:
            tok = parts[-1]
        else:
            tok = None
    if tok:
        # short suffix is plenty to separate users/sessions
        return "sess:" + tok[-24:]
    ip = request.headers.get("X-Forwarded-For", request.remote_addr) or "unknown"
    return "ip:" + ip

def bind_per_user_limits(app):
    """
    Idempotently bind POST /api/market-iq/analyze to Limiter with per-user key.
    Crucial bit: reassign app.view_functions[endpoint] to the wrapped callable.
    """
    # create/reuse limiter
    try:
        lim = app.extensions.get('limiter')
    except Exception:
        lim = None
    if not lim:
        lim = Limiter(
            key_func=get_remote_address,
            app=app,
            storage_uri=os.environ.get("RATE_LIMIT_STORAGE","redis://127.0.0.1:6379/2"),
            strategy=os.environ.get("RATE_LIMIT_STRATEGY","fixed-window"),
            default_limits=[os.environ.get("RATE_LIMIT_DEFAULT","120 per minute")]
        )
        try: app.logger.info("rl_bind_once: limiter instance created")
        except Exception: pass

    # find rule
    try:
        rule = next((r for r in app.url_map.iter_rules()
                     if r.rule.endswith("/api/market-iq/analyze") and "POST" in (r.methods or [])), None)
        if not rule:
            try: app.logger.warning("rl_bind_once: analyze rule not found")
            except Exception: pass
            return
        vf = app.view_functions.get(rule.endpoint)
        if not vf:
            try: app.logger.warning("rl_bind_once: view func missing for %s", rule.endpoint)
            except Exception: pass
            return

        if getattr(vf, "_sekki_rl_bound", False):
            try: app.logger.info("rl_bind_once: already bound %s", rule.endpoint)
            except Exception: pass
            return

        limit_str = os.environ.get("RATE_LIMIT_ANALYZE", "3 per minute")
        wrapped = lim.limit(limit_str, key_func=_user_or_ip_key)(vf)
        setattr(wrapped, "_sekki_rl_bound", True)
        app.view_functions[rule.endpoint] = wrapped  # <- the key: reassign

        try: app.logger.info("rl_bind_once: bound %s -> %s", rule.endpoint, limit_str)
        except Exception: pass
    except Exception as e:
        try: app.logger.warning("rl_bind_once: binding failed: %s", e)
        except Exception: pass
