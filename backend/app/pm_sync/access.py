"""Personal execution-sync ownership and lifecycle safeguards."""

from datetime import datetime

from sqlalchemy.orm.attributes import flag_modified

from app import db
from app.models import OrganizationMember, User


class BindingPaused(PermissionError):
    """A binding that may not sync now. ``reason`` is its stored pause reason.

    Subclasses PermissionError so existing callers that catch the owner check
    keep working; routes turn it into one structured 409 that carries the
    binding, so the interface shows the approved sentence for the reason.
    """

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


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


def binding_project_row(binding):
    """The canonical project row this binding belongs to, or None.

    Matched on the binding's own organization (or, for a personal binding,
    its owner's rows that carry no organization), never on the owner's
    active organization. Switching organizations must not move a binding
    onto another organization's project that shares the thread id (N1).
    Same rule as ``decision_records.record_project_row``.
    """
    from app.models import UserSession

    query = UserSession.query.filter_by(session_id=str(binding.thread_id))
    if binding.organization_id:
        query = query.filter_by(organization_id=str(binding.organization_id))
    else:
        query = query.filter(
            UserSession.organization_id.is_(None), UserSession.user_id == str(binding.user_id),
        )
    return query.order_by(UserSession.created_at.asc(), UserSession.id.asc()).first()


def binding_scenarios(binding):
    """``(data, row)``: the binding's own project as scenario data.

    ``data`` holds that one row, remembered, so a project-scoped save given
    ``source=data`` writes exactly that row and never re-resolves through
    the owner's active organization. ``row`` is None when the project is gone.
    """
    from app.project_scope import project_scenarios_into
    from app.scenarios_store import ScenariosData

    data = ScenariosData()
    row = binding_project_row(binding)
    if row is not None:
        project_scenarios_into(data, row)
        data.remember(str(row.session_id), row)
    return data, row


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
    # Current role decides (H-2e-2b): an owner who may no longer edit the
    # project cannot keep syncing it. The project is the binding's own, in the
    # binding's organization, whatever organization the owner has active (N1).
    # A missing project is not a pause reason; a sync then finds no plan and
    # stops before any Jira call.
    from app.session_access import can_write_session

    row = binding_project_row(binding)
    if row is not None and not can_write_session(row, owner):
        return "sync_owner_read_only"
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
        raise BindingPaused(reason)
    return binding


def ensure_not_paused(binding):
    """A paused binding never syncs or reactivates itself; only resume does."""
    if binding.status == "paused":
        raise BindingPaused((binding.config or {}).get("pause_reason") or "paused")
    return binding


def _owner_connection_ok(binding):
    """The owner's connection as every sync checks it (no external call)."""
    from app.pm_sync.provider import get_provider

    try:
        get_provider(binding.connector_id).assert_connected(binding.user_id, binding.external_container_id)
    except ValueError:
        return False
    return True


def resume_binding(binding, *, actor_user_id):
    """Explicit resume by the binding's owner, only once nothing still blocks it.

    Checks what is true now, never only the stored reason: the owner check
    (membership, current editing role) and the owner's Jira connection. A
    blocker found here is stored as the pause reason, so status and reason
    stay consistent and the interface shows the right sentence.
    """
    enforce_binding_owner(binding, actor_user_id=actor_user_id)
    if binding.status != "paused":
        return binding
    if not _owner_connection_ok(binding):
        mark_binding(binding, status="paused", warning_code="credential_disconnected",
                     pause_reason="credential_disconnected")
        db.session.commit()
        raise BindingPaused("credential_disconnected")
    mark_binding(binding, status="active")
    db.session.commit()
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
        # Reconnecting restores the credential only. If the owner may still
        # not sync this plan (role, membership), it stays paused for that
        # reason instead.
        owner_reason = binding_owner_pause_reason(binding)
        if owner_reason:
            mark_binding(binding, status="paused", warning_code=owner_reason, pause_reason=owner_reason)
            continue
        mark_binding(binding, status="active")
        resumed.append(binding)
    return resumed
