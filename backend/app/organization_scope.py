"""Shared active-organization scope resolution for customer reporting surfaces."""

from flask import current_app

from app.admin_policy import is_global_admin
from app.orgs import (
    can_manage_org,
    normalize_org_role,
    plan_allows_collaboration,
    resolve_active_org_for_user,
)
from app.models import OrganizationMember


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
    active_member_count = OrganizationMember.query.filter_by(
        organization_id=organization.id, status="active"
    ).count()
    can_view_organization = bool(
        plan_allows_collaboration(organization.plan_key)
        and (can_manage_org(role) or global_admin)
    )
    show_scope_control = bool(can_view_organization and active_member_count > 1)
    requested = "mine" if str(requested_scope or "").strip().lower() == "mine" else "organization"
    effective = "organization" if requested == "organization" and can_view_organization else "mine"
    return {
        "organization": organization,
        "membership": membership,
        "role": role,
        "can_manage": manager,
        "can_view_organization": can_view_organization,
        "show_scope_control": show_scope_control,
        "active_member_count": active_member_count,
        "is_global_admin": bool(global_admin),
        "requested_scope": requested,
        "scope": effective,
    }
