import secrets
import re
from datetime import datetime, timedelta

from sqlalchemy import case, func, or_

from app import db
from app.billing_config import (
    PLAN_RANK,
    is_sales_only_plan,
    normalize_plan_key,
    subscription_in_good_standing,
    to_public_plan,
)
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

DEFAULT_SEAT_POLICIES = {
    "team": {
        ORG_ROLE_OWNER: 1,
        ORG_ROLE_ADMIN: 3,
        ORG_ROLE_CREATOR: None,
        ORG_ROLE_COLLABORATOR: None,
        ORG_ROLE_VIEWER: None,
    },
    "business": {
        ORG_ROLE_OWNER: 1,
        ORG_ROLE_ADMIN: 5,
        ORG_ROLE_CREATOR: None,
        ORG_ROLE_COLLABORATOR: None,
        ORG_ROLE_VIEWER: None,
    },
    "enterprise_custom": {
        ORG_ROLE_OWNER: 1,
        ORG_ROLE_ADMIN: None,
        ORG_ROLE_CREATOR: None,
        ORG_ROLE_COLLABORATOR: None,
        ORG_ROLE_VIEWER: None,
    },
    # Baseline for self-serve accounts that still need a valid org policy.
    # Collaboration is a Team-or-higher entitlement, so every sub-Team plan
    # seats the owner and nobody else. These zeros are defence in depth: the
    # authoritative check is plan_allows_collaboration(), because per-org
    # seat_policy_overrides can raise these numbers back up.
    "essential": {
        ORG_ROLE_OWNER: 1,
        ORG_ROLE_ADMIN: 1,
        ORG_ROLE_CREATOR: 0,
        ORG_ROLE_COLLABORATOR: 0,
        ORG_ROLE_VIEWER: 0,
    },
    "starter": {
        ORG_ROLE_OWNER: 1,
        ORG_ROLE_ADMIN: 1,
        ORG_ROLE_CREATOR: 0,
        ORG_ROLE_COLLABORATOR: 0,
        ORG_ROLE_VIEWER: 0,
    },
    "free": {
        ORG_ROLE_OWNER: 1,
        ORG_ROLE_ADMIN: 1,
        ORG_ROLE_CREATOR: 0,
        ORG_ROLE_COLLABORATOR: 0,
        ORG_ROLE_VIEWER: 0,
    },
}

MFA_POLICY_OPTIONAL = "optional"
MFA_POLICY_ENCOURAGED = "encouraged"
MFA_POLICY_REQUIRED = "required"
MFA_POLICY_SET = {MFA_POLICY_OPTIONAL, MFA_POLICY_ENCOURAGED, MFA_POLICY_REQUIRED}

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
    return DEFAULT_SEAT_POLICIES.get(canonical, DEFAULT_SEAT_POLICIES["essential"])


# --- Collaboration entitlement -------------------------------------------
#
# Collaboration (inviting anyone else into an organization, in any role) is a
# Team-or-higher *subscription* entitlement.
#
# This is deliberately keyed on subscription plan rank and nothing else. The
# 300K limited-time offer, the founder offer, advisory packages and persistent
# credit grants all confer Thinking Power and individual output capabilities,
# but never collaboration. Note in particular that effective_plan_key() lifts a
# 300K holder to Essential-equivalent access for entitlement checks -- that lift
# stops below Team, and org.plan_key is synced from the raw subscription_plan,
# so neither path can reach collaboration. Do not re-key this on entitlements,
# credit balances or "has ever paid us" without changing that rule on purpose.

COLLABORATION_MIN_PLAN = "team"

COLLABORATION_DENIED_PLAN = "plan_not_eligible"
COLLABORATION_DENIED_BILLING = "subscription_not_current"


def plan_allows_collaboration(plan_key):
    """True when a plan key carries the collaboration entitlement (Team+)."""
    canonical = normalize_plan_key(plan_key)
    return PLAN_RANK.get(canonical, 0) >= PLAN_RANK[COLLABORATION_MIN_PLAN]


def org_collaboration_state(org, app_config=None):
    """Resolve whether an org may collaborate, and whether it may invite now.

    Two independent gates, kept separate on purpose:

    * ``entitled``        -- the plan carries collaboration at all (Team+).
    * ``billing_current`` -- the owner's subscription is in good standing.

    A past-due Team org stays ``entitled`` but loses ``can_invite``: new invites
    are blocked immediately while Stripe retries, and existing members are left
    alone for the dunning grace period. Nothing here removes a member; that is
    intentional and callers must not infer removal from ``can_invite``.
    """
    plan_key = normalize_plan_key(getattr(org, "plan_key", None))
    owner_id = getattr(org, "owner_user_id", None)
    owner = User.query.filter_by(id=owner_id).first() if owner_id else None
    status = getattr(owner, "subscription_status", None) if owner is not None else None
    return _collaboration_state(plan_key, status, app_config)


def user_collaboration_state(user, app_config=None):
    """org_collaboration_state() for a user who has no organization yet.

    Used when creating an organization, so a plan that cannot collaborate
    cannot mint a Team-plan org and collaborate through it instead.
    """
    plan_key = normalize_plan_key(getattr(user, "subscription_plan", None))
    return _collaboration_state(
        plan_key, getattr(user, "subscription_status", None), app_config
    )


def _collaboration_state(plan_key, subscription_status, app_config=None):
    entitled = plan_allows_collaboration(plan_key)

    billing_current = True
    if entitled and subscription_status is not None:
        if subscription_in_good_standing(subscription_status):
            billing_current = True
        elif app_config is not None and is_sales_only_plan(plan_key, app_config):
            # Sales-led plans are provisioned outside Stripe consumer billing,
            # so a stale consumer status must not lock them out.
            billing_current = True
        else:
            billing_current = False

    if not entitled:
        reason = COLLABORATION_DENIED_PLAN
    elif not billing_current:
        reason = COLLABORATION_DENIED_BILLING
    else:
        reason = None

    return {
        "plan_key": plan_key,
        "public_plan_key": to_public_plan(plan_key),
        "entitled": entitled,
        "billing_current": billing_current,
        "can_invite": bool(entitled and billing_current),
        "reason": reason,
    }


def collaboration_denied_message(state):
    """Human-readable refusal matching an org_collaboration_state() reason."""
    if (state or {}).get("reason") == COLLABORATION_DENIED_BILLING:
        return (
            "Collaborator invitations are paused while this subscription's "
            "payment is being retried. Existing members keep their access."
        )
    return (
        "Collaborator invitations require an active Team plan or higher. "
        "Upgrade to Team to invite people into this workspace."
    )


def pending_invitation_counts(org, now=None):
    """Count unexpired pending invitations per role.

    A pending invitation holds a seat. Without this an org can over-invite far
    past its seat count and the overflow invitees only discover it when they
    click their link and the accept fails.
    """
    if not isinstance(org, Organization):
        return {}

    moment = now or utcnow()
    rows = (
        db.session.query(OrganizationInvitation.role, func.count(OrganizationInvitation.id))
        .filter(
            OrganizationInvitation.organization_id == org.id,
            OrganizationInvitation.status == "pending",
            or_(
                OrganizationInvitation.expires_at.is_(None),
                OrganizationInvitation.expires_at >= moment,
            ),
        )
        .group_by(OrganizationInvitation.role)
        .all()
    )
    return {normalize_org_role(role): int(count or 0) for role, count in rows}


def default_mfa_policy_for_plan(plan_key):
    canonical = normalize_plan_key(plan_key)
    if canonical == "business":
        return MFA_POLICY_REQUIRED
    if canonical == "team":
        return MFA_POLICY_OPTIONAL
    if canonical == "free":
        return MFA_POLICY_OPTIONAL
    return MFA_POLICY_OPTIONAL


def normalize_mfa_policy(value, default=None):
    token = str(value or "").strip().lower()
    if token in MFA_POLICY_SET:
        return token
    return default


def mfa_policy_for_org(org):
    if not isinstance(org, Organization):
        return MFA_POLICY_OPTIONAL
    settings = org.settings if isinstance(org.settings, dict) else {}
    configured = normalize_mfa_policy(settings.get("mfa_policy"))
    if configured:
        return configured
    return default_mfa_policy_for_plan(org.plan_key)


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

    # One implementation, shared with the by-id endpoints. Reads the OWNER's
    # plan, so this is correct no matter who triggered the resolution.
    if org is not None and sync_org_plan_from_owner(org):
        changed = True

    if org and user.active_organization_id != org.id:
        user.active_organization_id = org.id
        changed = True

    return org, membership, changed


def sync_org_plan_from_owner(org):
    """Bring org.plan_key in line with its OWNER's current subscription.

    The single plan-sync implementation. An organization's entitlement follows
    the person who pays for it, never whoever happens to be making the request
    -- a member's own subscription must not move someone else's org between
    plans.

    Returns True when the row changed, so callers can decide whether to commit.

    Why this is called from the gates and not only at org resolution: a
    subscription change writes `user.subscription_plan` and nothing else, so
    `org.plan_key` is stale until something syncs it. Endpoints that address an
    organization by id (app.routes.teams._require_org_access, invitation
    accept) never went through org resolution, so they evaluated the
    collaboration gate against a stale plan. On an upgrade that failed closed
    and was merely annoying; on a DOWNGRADE it failed open -- a just-downgraded
    owner could still invite, and the invitee could still accept, because both
    read the same stale 'team'.
    """
    if not isinstance(org, Organization) or not org.owner_user_id:
        return False
    owner = User.query.filter_by(id=org.owner_user_id).first()
    if owner is None:
        return False
    owner_plan = normalize_plan_key(getattr(owner, "subscription_plan", None))
    if owner_plan and org.plan_key != owner_plan:
        org.plan_key = owner_plan
        return True
    return False


def sync_org_plan_and_commit(org):
    """sync_org_plan_from_owner() for callers outside a write transaction."""
    if sync_org_plan_from_owner(org):
        db.session.commit()
        return True
    return False


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
    pending_counts = pending_invitation_counts(org)

    policy = seat_policy_for_org(org)
    usage = {}
    owner_used = int(role_counts.get(ORG_ROLE_OWNER, 0))
    total_paid_used = 0
    total_paid_reserved = 0
    for role in ORG_ROLES:
        used = int(role_counts.get(role, 0))
        if role == ORG_ROLE_ADMIN:
            # Owner counts against admin seat capacity.
            used += owner_used
        pending = int(pending_counts.get(role, 0))
        # An outstanding invitation holds its seat until it is accepted,
        # revoked or expires, so capacity is measured against `reserved`.
        reserved = used + pending
        limit = policy.get(role)
        usage[role] = {
            "label": role_label(role),
            "used": used,
            "pending": pending,
            "reserved": reserved,
            "limit": limit,
            "available": None if limit is None else max(int(limit) - reserved, 0),
            "is_unlimited": limit is None,
        }
        if role in {ORG_ROLE_ADMIN, ORG_ROLE_CREATOR, ORG_ROLE_COLLABORATOR}:
            total_paid_used += used
            total_paid_reserved += reserved
    total_paid_limit = getattr(org, "max_total_paid_seats", None)
    usage["total_paid_used"] = total_paid_used
    usage["total_paid_pending"] = total_paid_reserved - total_paid_used
    usage["total_paid_reserved"] = total_paid_reserved
    usage["total_paid_limit"] = total_paid_limit
    usage["total_paid_available"] = (
        None if total_paid_limit is None else max(int(total_paid_limit) - total_paid_reserved, 0)
    )
    return usage


def role_has_capacity(org, role, exclude_member_id=None):
    role = normalize_org_role(role)
    public_plan = to_public_plan(getattr(org, "plan_key", None))
    policy = seat_policy_for_org(org)
    limit = policy.get(role)

    excluded = None
    if exclude_member_id is not None:
        excluded = OrganizationMember.query.filter_by(
            id=int(exclude_member_id),
            organization_id=org.id,
            status="active",
        ).first()

    if public_plan in {"team", "business"}:
        usage = build_seat_usage(org)
        if role == ORG_ROLE_ADMIN:
            # `reserved` counts active members plus outstanding invitations.
            admin_used = int((usage.get(ORG_ROLE_ADMIN) or {}).get("reserved") or 0)
            if excluded and normalize_org_role(excluded.role) in {ORG_ROLE_OWNER, ORG_ROLE_ADMIN}:
                admin_used = max(0, admin_used - 1)
            if limit is not None and admin_used >= int(limit):
                return False

        if role in {ORG_ROLE_ADMIN, ORG_ROLE_CREATOR, ORG_ROLE_COLLABORATOR}:
            paid_used = int(usage.get("total_paid_reserved") or 0)
            if excluded and normalize_org_role(excluded.role) in {ORG_ROLE_OWNER, ORG_ROLE_ADMIN, ORG_ROLE_CREATOR, ORG_ROLE_COLLABORATOR}:
                paid_used = max(0, paid_used - 1)
            total_paid_limit = getattr(org, "max_total_paid_seats", None)
            if total_paid_limit is not None and paid_used >= int(total_paid_limit):
                return False
        return True

    if limit is None:
        return True

    if role == ORG_ROLE_ADMIN:
        query = OrganizationMember.query.filter(
            OrganizationMember.organization_id == org.id,
            OrganizationMember.status == "active",
            OrganizationMember.role.in_([ORG_ROLE_OWNER, ORG_ROLE_ADMIN]),
        )
        used = query.count()
        if excluded is not None:
            if normalize_org_role(excluded.role) in {ORG_ROLE_OWNER, ORG_ROLE_ADMIN}:
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

    # Outstanding invitations hold their seat until accepted, revoked or expired.
    used += int(pending_invitation_counts(org).get(role, 0))

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
            "active_organization_name": None,
            "active_organization_role": None,
            "active_organization_plan_key": None,
            "can_access_team": False,
            "can_access_enterprise_admin": False,
        }

    active_org = None
    active_membership = None
    if user.active_organization_id:
        active_org = Organization.query.filter_by(id=user.active_organization_id).first()
        if active_org:
            active_membership = OrganizationMember.query.filter_by(
                organization_id=active_org.id,
                user_id=user.id,
                status="active",
            ).first()

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
        "active_organization_name": active_org.name if active_org else None,
        "active_organization_role": active_membership.role if active_membership else None,
        "active_organization_plan_key": to_public_plan(active_org.plan_key) if active_org else None,
        "active_organization_mfa_policy": mfa_policy_for_org(active_org) if active_org else None,
        "can_access_team": bool(normalized_plans.intersection({"team", "business", "enterprise_custom"})),
        "can_access_enterprise_admin": "enterprise_custom" in normalized_plans,
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
        "max_total_paid_seats": getattr(org, "max_total_paid_seats", None),
        "settings": org.settings if isinstance(org.settings, dict) else {},
        "mfa_policy": mfa_policy_for_org(org),
    }
