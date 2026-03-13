import secrets
import re
from datetime import datetime, timedelta

from sqlalchemy import case, func

from app import db
from app.billing_config import normalize_plan_key, to_public_plan
from app.models import Organization, OrganizationInvitation, OrganizationMember, User


ORG_ROLE_OWNER = "owner"
ORG_ROLE_ADMIN = "admin"
ORG_ROLE_CREATOR = "creator"
ORG_ROLE_COLLABORATOR = "collaborator"
ORG_ROLE_VIEWER = "viewer"

ORG_ROLES = [
    ORG_ROLE_OWNER,
    ORG_ROLE_ADMIN,
    ORG_ROLE_CREATOR,
    ORG_ROLE_COLLABORATOR,
    ORG_ROLE_VIEWER,
]
ORG_ROLE_SET = set(ORG_ROLES)

ORG_MANAGE_ROLES = {ORG_ROLE_OWNER, ORG_ROLE_ADMIN}
ORG_EDIT_ROLES = {ORG_ROLE_OWNER, ORG_ROLE_ADMIN, ORG_ROLE_CREATOR, ORG_ROLE_COLLABORATOR}

TEAM_SEAT_POLICY = {
    "team": {
        ORG_ROLE_OWNER: 1,
        ORG_ROLE_ADMIN: 2,
        ORG_ROLE_CREATOR: 5,
        ORG_ROLE_COLLABORATOR: 10,
        ORG_ROLE_VIEWER: None,
    },
    "enterprise": {
        ORG_ROLE_OWNER: 1,
        ORG_ROLE_ADMIN: 5,
        ORG_ROLE_CREATOR: 25,
        ORG_ROLE_COLLABORATOR: None,
        ORG_ROLE_VIEWER: None,
    },
    # Baseline for self-serve accounts that still need a valid org policy.
    "essential": {
        ORG_ROLE_OWNER: 1,
        ORG_ROLE_ADMIN: 1,
        ORG_ROLE_CREATOR: 2,
        ORG_ROLE_COLLABORATOR: 3,
        ORG_ROLE_VIEWER: None,
    },
    "free": {
        ORG_ROLE_OWNER: 1,
        ORG_ROLE_ADMIN: 1,
        ORG_ROLE_CREATOR: 1,
        ORG_ROLE_COLLABORATOR: 2,
        ORG_ROLE_VIEWER: None,
    },
}

_ROLE_DISPLAY_LABEL = {
    ORG_ROLE_OWNER: "Owner",
    ORG_ROLE_ADMIN: "Admin",
    ORG_ROLE_CREATOR: "Creator",
    ORG_ROLE_COLLABORATOR: "Collaborator",
    ORG_ROLE_VIEWER: "Viewer",
}

_ROLE_ALIAS = {
    "member": ORG_ROLE_COLLABORATOR,
    "teammate": ORG_ROLE_COLLABORATOR,
    "editor": ORG_ROLE_CREATOR,
}
_INVALID_SEAT_LIMIT = object()


def utcnow():
    return datetime.utcnow()


def normalize_org_role(value, default=ORG_ROLE_VIEWER):
    key = str(value or "").strip().lower()
    if not key:
        return default
    key = _ROLE_ALIAS.get(key, key)
    return key if key in ORG_ROLE_SET else default


def role_label(role):
    normalized = normalize_org_role(role)
    return _ROLE_DISPLAY_LABEL.get(normalized, normalized.title())


def can_manage_org(role):
    return normalize_org_role(role) in ORG_MANAGE_ROLES


def can_edit_projects(role):
    return normalize_org_role(role) in ORG_EDIT_ROLES


def seat_policy_for_plan(plan_key):
    canonical = normalize_plan_key(plan_key)
    return TEAM_SEAT_POLICY.get(canonical, TEAM_SEAT_POLICY["essential"])


def normalize_seat_limit_value(value):
    if value is None:
        return None
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"", "none", "null", "unlimited"}:
            return None
        value = token
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return _INVALID_SEAT_LIMIT
    if parsed < 0:
        return _INVALID_SEAT_LIMIT
    return parsed


def seat_policy_overrides_for_org(org):
    if not isinstance(org, Organization):
        return {}
    raw = org.seat_policy_overrides if isinstance(org.seat_policy_overrides, dict) else {}
    output = {}
    for role in ORG_ROLES:
        if role == ORG_ROLE_OWNER:
            continue
        if role not in raw:
            continue
        parsed = normalize_seat_limit_value(raw.get(role))
        if parsed is _INVALID_SEAT_LIMIT:
            continue
        output[role] = parsed
    return output


def seat_policy_for_org(org):
    if not isinstance(org, Organization):
        return dict(seat_policy_for_plan(org))

    policy = dict(seat_policy_for_plan(org.plan_key))
    for role, limit in seat_policy_overrides_for_org(org).items():
        policy[role] = limit
    policy[ORG_ROLE_OWNER] = 1
    return policy


def serialize_seat_policy(plan_or_org):
    policy = seat_policy_for_org(plan_or_org)
    output = {}
    for role in ORG_ROLES:
        limit = policy.get(role)
        output[role] = {
            "label": role_label(role),
            "limit": limit,
            "is_unlimited": limit is None,
        }
    return output


def _slugify(value):
    token = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return token[:96] or f"org-{secrets.token_hex(3)}"


def _build_default_org_name(user):
    display = str(user.name or "").strip()
    if not display:
        base = str(user.email or "").split("@")[0] or "Jaspen"
        display = base.replace(".", " ").replace("_", " ").strip().title() or "Jaspen"
    suffix = "Team" if not display.lower().endswith("team") else ""
    return f"{display} {suffix}".strip()


def _build_unique_slug(base_text):
    base = _slugify(base_text)
    slug = base
    counter = 2
    while Organization.query.filter_by(slug=slug).first() is not None:
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def _ensure_owner_membership(org, user_id):
    member = OrganizationMember.query.filter_by(
        organization_id=org.id,
        user_id=str(user_id),
        status="active",
    ).first()
    if member is None:
        member = OrganizationMember(
            organization_id=org.id,
            user_id=str(user_id),
            role=ORG_ROLE_OWNER,
            status="active",
            joined_at=utcnow(),
            last_active_at=utcnow(),
        )
        db.session.add(member)
        return member, True
    changed = False
    if member.role != ORG_ROLE_OWNER:
        member.role = ORG_ROLE_OWNER
        changed = True
    if member.joined_at is None:
        member.joined_at = utcnow()
        changed = True
    return member, changed


def ensure_default_organization_for_user(user):
    """
    Ensure each user has at least one organization and active membership.
    Returns (org, membership, changed).
    """
    if not isinstance(user, User):
        return None, None, False

    changed = False
    org = None
    membership = None

    if user.active_organization_id:
        membership = OrganizationMember.query.filter_by(
            organization_id=user.active_organization_id,
            user_id=user.id,
            status="active",
        ).first()
        if membership:
            org = Organization.query.filter_by(id=membership.organization_id).first()

    if org is None:
        role_order = case(
            (OrganizationMember.role == ORG_ROLE_OWNER, 0),
            (OrganizationMember.role == ORG_ROLE_ADMIN, 1),
            (OrganizationMember.role == ORG_ROLE_CREATOR, 2),
            (OrganizationMember.role == ORG_ROLE_COLLABORATOR, 3),
            (OrganizationMember.role == ORG_ROLE_VIEWER, 4),
            else_=9,
        )
        membership = (
            OrganizationMember.query
            .filter_by(user_id=user.id, status="active")
            .order_by(role_order, OrganizationMember.created_at.asc())
            .first()
        )
        if membership:
            org = Organization.query.filter_by(id=membership.organization_id).first()

    if org is None:
        org = Organization(
            name=_build_default_org_name(user),
            slug=_build_unique_slug(user.email or user.name or "jaspen-org"),
            owner_user_id=user.id,
            plan_key=normalize_plan_key(user.subscription_plan),
        )
        db.session.add(org)
        db.session.flush()
        membership = OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role=ORG_ROLE_OWNER,
            status="active",
            joined_at=utcnow(),
            last_active_at=utcnow(),
        )
        db.session.add(membership)
        changed = True
    else:
        if org.owner_user_id == user.id:
            owner_member, owner_changed = _ensure_owner_membership(org, user.id)
            if membership is None:
                membership = owner_member
            if owner_changed:
                changed = True
        if membership is None:
            membership = OrganizationMember.query.filter_by(
                organization_id=org.id,
                user_id=user.id,
                status="active",
            ).first()

    if org and org.owner_user_id == user.id:
        owner_plan = normalize_plan_key(user.subscription_plan)
        if owner_plan and org.plan_key != owner_plan:
            org.plan_key = owner_plan
            changed = True

    if org and user.active_organization_id != org.id:
        user.active_organization_id = org.id
        changed = True

    return org, membership, changed


def resolve_active_org_for_user(user):
    org, membership, changed = ensure_default_organization_for_user(user)
    if changed:
        db.session.commit()
    return org, membership


def touch_member_activity(membership):
    if not isinstance(membership, OrganizationMember):
        return
    membership.last_active_at = utcnow()
    db.session.commit()


def build_seat_usage(org):
    if not isinstance(org, Organization):
        return {}

    counts_query = (
        db.session.query(OrganizationMember.role, func.count(OrganizationMember.id))
        .filter(OrganizationMember.organization_id == org.id, OrganizationMember.status == "active")
        .group_by(OrganizationMember.role)
        .all()
    )
    role_counts = {normalize_org_role(role): int(count or 0) for role, count in counts_query}

    policy = seat_policy_for_org(org)
    usage = {}
    owner_used = int(role_counts.get(ORG_ROLE_OWNER, 0))
    for role in ORG_ROLES:
        used = int(role_counts.get(role, 0))
        if role == ORG_ROLE_ADMIN:
            # Owner counts against admin seat capacity.
            used += owner_used
        limit = policy.get(role)
        usage[role] = {
            "label": role_label(role),
            "used": used,
            "limit": limit,
            "available": None if limit is None else max(int(limit) - used, 0),
            "is_unlimited": limit is None,
        }
    return usage


def role_has_capacity(org, role, exclude_member_id=None):
    role = normalize_org_role(role)
    limit = seat_policy_for_org(org).get(role)
    if limit is None:
        return True

    if role == ORG_ROLE_ADMIN:
        query = OrganizationMember.query.filter(
            OrganizationMember.organization_id == org.id,
            OrganizationMember.status == "active",
            OrganizationMember.role.in_([ORG_ROLE_OWNER, ORG_ROLE_ADMIN]),
        )
        used = query.count()
        if exclude_member_id is not None:
            excluded = OrganizationMember.query.filter_by(
                id=int(exclude_member_id),
                organization_id=org.id,
                status="active",
            ).first()
            if excluded and normalize_org_role(excluded.role) in {ORG_ROLE_OWNER, ORG_ROLE_ADMIN}:
                used = max(0, used - 1)
    else:
        query = OrganizationMember.query.filter_by(
            organization_id=org.id,
            role=role,
            status="active",
        )
        if exclude_member_id is not None:
            query = query.filter(OrganizationMember.id != int(exclude_member_id))
        used = query.count()

    return used < int(limit)


def invitation_is_expired(invitation):
    if not isinstance(invitation, OrganizationInvitation):
        return True
    return bool(invitation.expires_at and invitation.expires_at < utcnow())


def new_invitation_expiry(days=14):
    return utcnow() + timedelta(days=int(days or 14))


def active_membership_for_user(org_id, user_id):
    return OrganizationMember.query.filter_by(
        organization_id=str(org_id),
        user_id=str(user_id),
        status="active",
    ).first()


def organization_access_payload_for_user(user):
    if not isinstance(user, User):
        return {
            "active_organization_plan_key": None,
            "can_access_team": False,
            "can_access_enterprise_admin": False,
        }

    active_org = None
    if user.active_organization_id:
        active_org = Organization.query.filter_by(id=user.active_organization_id).first()

    membership_plans = (
        db.session.query(Organization.plan_key)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .filter(
            OrganizationMember.user_id == user.id,
            OrganizationMember.status == "active",
        )
        .all()
    )
    normalized_plans = {
        to_public_plan(plan_key)
        for (plan_key,) in membership_plans
        if str(plan_key or "").strip()
    }

    return {
        "active_organization_plan_key": to_public_plan(active_org.plan_key) if active_org else None,
        "can_access_team": bool(normalized_plans.intersection({"team", "enterprise"})),
        "can_access_enterprise_admin": "enterprise" in normalized_plans,
    }


def invitation_payload(invite):
    if not isinstance(invite, OrganizationInvitation):
        return {}
    return {
        "id": invite.id,
        "organization_id": invite.organization_id,
        "email": invite.email,
        "role": normalize_org_role(invite.role),
        "status": invite.status,
        "token": invite.token,
        "invited_by_user_id": invite.invited_by_user_id,
        "accepted_by_user_id": invite.accepted_by_user_id,
        "expires_at": invite.expires_at.isoformat() if invite.expires_at else None,
        "accepted_at": invite.accepted_at.isoformat() if invite.accepted_at else None,
        "created_at": invite.created_at.isoformat() if invite.created_at else None,
        "updated_at": invite.updated_at.isoformat() if invite.updated_at else None,
    }


def org_payload(org):
    if not isinstance(org, Organization):
        return {}
    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "owner_user_id": org.owner_user_id,
        "plan_key": to_public_plan(org.plan_key),
        "seat_policy_defaults": serialize_seat_policy(org.plan_key),
        "seat_policy": serialize_seat_policy(org),
        "seat_policy_overrides": seat_policy_overrides_for_org(org),
    }
