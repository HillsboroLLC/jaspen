from functools import wraps
from flask import jsonify
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

def _is_subscribed(user) -> bool:
    """Minimal gate; replace with your real fields (status/period_end)."""
    status = getattr(user, "subscription_status", None)
    if status in {"active", "trialing"}:
        return True
    plan = getattr(user, "subscription_plan", None)
    return plan not in (None, "", "free", "essential")

def subscription_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        # BYPASS_UNAUTH_BEGIN: allow unauthenticated callers to proceed
        try:
            verify_jwt_in_request(optional=True)
            _uid = get_jwt_identity()
        except Exception:
            _uid = None
        if _uid is None:
            # Unauthenticated (e.g., external helper). Do NOT enforce subscription.
            return fn(*args, **kwargs)
        # BYPASS_UNAUTH_END
        # Lazy import to break circular import: app -> routes -> decorators -> models -> app
        try:
            from app.models import User  # imported after app + db are initialized
        except Exception:
            User = None

        uid = get_jwt_identity()
        user = User.query.get(uid) if (User and uid) else None
        if not user or not _is_subscribed(user):
            # Enforce only for authenticated users; otherwise it was already bypassed above
            return jsonify({"error":"subscription_required"}), 402
        return fn(*args, **kwargs)
    return wrapper
