"""Personal execution-sync ownership and lifecycle safeguards."""

from datetime import datetime

from sqlalchemy.orm.attributes import flag_modified

from app import db
from app.models import OrganizationMember, User


def binding_owner_payload(binding):
    owner = User.query.get(str(binding.user_id))
    if owner is None:
        return {"user_id": str(binding.user_id), "name": None, "email": None, "available": False}
    return {
        "user_id": str(owner.id),
        "name": str(getattr(owner, "name", "") or "").strip() or None,
        "email": str(getattr(owner, "email", "") or "").strip() or None,
        "available": not bool(getattr(owner, "deactivated_at", None)),
    }


def binding_owner_pause_reason(binding):
    owner = User.query.get(str(binding.user_id))
    if owner is None or getattr(owner, "deactivated_at", None):
        return "sync_owner_unavailable"
    organization_id = str(binding.organization_id or "").strip()
    if organization_id:
        membership = OrganizationMember.query.filter_by(
            organization_id=organization_id,
            user_id=str(binding.user_id),
            status="active",
        ).first()
        if membership is None:
            return "sync_owner_left_organization"
    return None


def mark_binding(binding, *, status=None, warning_code=None, pause_reason=None):
    if status:
        binding.status = status
    config = dict(binding.config or {})
    if warning_code:
        config["sync_warning_code"] = warning_code
    else:
        config.pop("sync_warning_code", None)
    if pause_reason:
        config["pause_reason"] = pause_reason
        config["paused_at"] = datetime.utcnow().isoformat()
    elif status == "active":
        config.pop("pause_reason", None)
        config.pop("paused_at", None)
    binding.config = config
    flag_modified(binding, "config")
    return binding


def enforce_binding_owner(binding, *, actor_user_id=None):
    if actor_user_id is not None and str(actor_user_id) != str(binding.user_id):
        raise PermissionError("This Jira sync belongs to another person.")
    reason = binding_owner_pause_reason(binding)
    if reason:
        mark_binding(binding, status="paused", warning_code=reason, pause_reason=reason)
        db.session.commit()
        raise PermissionError(reason)
    return binding


def pause_personal_bindings(user_id, connector_id, reason):
    from app.models_pm_sync import PmSyncBinding

    rows = PmSyncBinding.query.filter_by(
        user_id=str(user_id), connector_id=str(connector_id)
    ).all()
    for binding in rows:
        mark_binding(binding, status="paused", warning_code=reason, pause_reason=reason)
    return rows


def resume_personal_bindings(user_id, connector_id):
    from app.models_pm_sync import PmSyncBinding

    rows = PmSyncBinding.query.filter_by(
        user_id=str(user_id), connector_id=str(connector_id), status="paused"
    ).all()
    resumed = []
    for binding in rows:
        if (binding.config or {}).get("pause_reason") != "credential_disconnected":
            continue
        mark_binding(binding, status="active")
        resumed.append(binding)
    return resumed
