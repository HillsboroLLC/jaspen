"""Shared active-organization scope resolution for customer reporting surfaces."""

from flask import current_app

from app.admin_policy import is_global_admin
from app.orgs import can_manage_org, normalize_org_role, resolve_active_org_for_user


def resolve_customer_scope(user, requested_scope="organization"):
    """Return the active org and the strongest reporting scope the actor may use.

    Non-managers asking for organization scope intentionally fall back to their
    own activity. Callers still apply the resource-specific read predicate.
    """
    organization, membership = resolve_active_org_for_user(user)
    if not organization or not membership:
        return None

    role = normalize_org_role(membership.role)
    global_admin = is_global_admin(user, app_config=current_app.config)
    manager = bool(global_admin or can_manage_org(role))
    requested = "mine" if str(requested_scope or "").strip().lower() == "mine" else "organization"
    effective = "organization" if requested == "organization" and manager else "mine"
    return {
        "organization": organization,
        "membership": membership,
        "role": role,
        "can_manage": manager,
        "is_global_admin": bool(global_admin),
        "requested_scope": requested,
        "scope": effective,
    }
