from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models import AppSetting, User


ACCESS_CONTROLS_SETTING_KEY = "access_controls"
APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_REJECTED = "rejected"
APPROVAL_STATUSES = {
    APPROVAL_PENDING,
    APPROVAL_APPROVED,
    APPROVAL_REJECTED,
}


def _to_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def default_access_controls(app_config):
    return {
        "open_signup": _to_bool((app_config or {}).get("OPEN_SIGNUP"), default=True),
        "require_invite_code": _to_bool((app_config or {}).get("REQUIRE_INVITE_CODE"), default=False),
        "require_admin_approval": _to_bool((app_config or {}).get("REQUIRE_ADMIN_APPROVAL"), default=False),
        "require_email_verification": _to_bool((app_config or {}).get("REQUIRE_EMAIL_VERIFICATION"), default=False),
    }


def normalize_access_controls(values, app_config=None):
    defaults = default_access_controls(app_config or {})
    incoming = values if isinstance(values, dict) else {}
    return {
        "open_signup": _to_bool(incoming.get("open_signup"), default=defaults["open_signup"]),
        "require_invite_code": _to_bool(incoming.get("require_invite_code"), default=defaults["require_invite_code"]),
        "require_admin_approval": _to_bool(incoming.get("require_admin_approval"), default=defaults["require_admin_approval"]),
        "require_email_verification": _to_bool(incoming.get("require_email_verification"), default=defaults["require_email_verification"]),
    }


def get_access_controls(app_config=None):
    defaults = default_access_controls(app_config or {})
    try:
        row = db.session.get(AppSetting, ACCESS_CONTROLS_SETTING_KEY)
    except SQLAlchemyError:
        return defaults
    if not row or not isinstance(row.value, dict):
        return defaults
    merged = dict(defaults)
    merged.update(normalize_access_controls(row.value, app_config=app_config))
    return merged


def save_access_controls(values, app_config=None):
    normalized = normalize_access_controls(values, app_config=app_config)
    row = db.session.get(AppSetting, ACCESS_CONTROLS_SETTING_KEY)
    if not row:
        row = AppSetting(key=ACCESS_CONTROLS_SETTING_KEY, value=normalized)
        db.session.add(row)
    else:
        row.value = normalized
        row.updated_at = datetime.utcnow()
    return row


def access_review_summary(limit=25):
    query = User.query.filter(User.access_approval_status.in_([APPROVAL_PENDING, APPROVAL_REJECTED]))
    pending_count = query.filter(User.access_approval_status == APPROVAL_PENDING).count()
    rejected_count = query.filter(User.access_approval_status == APPROVAL_REJECTED).count()
    items = []
    for user in query.order_by(User.updated_at.desc(), User.created_at.desc()).limit(max(1, min(int(limit or 25), 100))).all():
        status = str(user.access_approval_status or APPROVAL_APPROVED).strip().lower()
        items.append({
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "access_approval_status": status,
            "email_verified": bool(user.email_verified),
            "signup_referral_code_used": user.signup_referral_code_used,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        })
    return {
        "pending_count": pending_count,
        "rejected_count": rejected_count,
        "items": items,
    }
