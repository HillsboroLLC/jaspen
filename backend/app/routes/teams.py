"""Organization-scoped team routes, mounted at /api/v1/teams.

Addresses an organization explicitly by id (/api/v1/teams/<org_id>/...) and
owns invitation send/resend/cancel/accept and member role changes.

Its sibling, app.routes.team (singular, /api/v1/team), addresses the caller's
*active* organization implicitly and owns the summary, seat policy, org
switching and shared-project surface. The frontend currently reads through the
singular prefix and writes through this one.

Roles, seat accounting, capacity and the collaboration entitlement all live in
app.orgs and must stay there. Both blueprints previously carried their own
copies which drifted apart, so the same organization could get two different
answers depending on which prefix was called. Do not reintroduce a local copy;
extend app.orgs instead.

Collapsing the two route surfaces into one, and pointing the frontend at it,
is still outstanding.
"""
import re
import uuid
from datetime import datetime, timedelta

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_mail import Message
from sqlalchemy import func

from app import db, limiter, mail
from app.billing_config import get_plan_catalog, normalize_plan_key, to_public_plan
from app.models import Organization, OrganizationInvitation, OrganizationMember, User
from app.orgs import (
    COLLABORATION_MIN_PLAN,
    MFA_POLICY_REQUIRED,
    ORG_MANAGE_ROLES,
    ORG_ROLE_ADMIN,
    ORG_ROLE_COLLABORATOR,
    ORG_ROLE_CREATOR,
    ORG_ROLE_OWNER,
    ORG_ROLE_VIEWER,
    build_seat_usage,
    collaboration_denied_message,
    ensure_default_organization_for_user,
    sync_org_plan_and_commit,
    mfa_policy_for_org,
    normalize_mfa_policy,
    normalize_org_role,
    org_collaboration_state,
    role_has_capacity,
    user_collaboration_state,
)


teams_bp = Blueprint("teams", __name__)

# Roles, seat accounting and capacity all live in app.orgs. This blueprint
# used to carry its own copies, which drifted: its caps came from the plan
# catalog and the per-role Organization columns, while app.orgs used
# DEFAULT_SEAT_POLICIES plus seat_policy_overrides. The two disagreed about
# how many seats an org had. These are aliases now, not a second source.
ROLE_OWNER = ORG_ROLE_OWNER
ROLE_ADMIN = ORG_ROLE_ADMIN
ROLE_CREATOR = ORG_ROLE_CREATOR
ROLE_COLLABORATOR = ORG_ROLE_COLLABORATOR
ROLE_VIEWER = ORG_ROLE_VIEWER

MANAGE_ROLES = ORG_MANAGE_ROLES


def _pagination_params():
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 25, type=int), 100)
    return max(page, 1), max(per_page, 1)


def _now():
    return datetime.utcnow()


def _deep_merge_dict(existing, incoming):
    base = dict(existing) if isinstance(existing, dict) else {}
    if not isinstance(incoming, dict):
        return base
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_merge_dict(base.get(key), value)
        else:
            base[key] = value
    return base


def _normalize_org_mfa_settings(org, incoming_settings):
    if not isinstance(incoming_settings, dict):
        return incoming_settings, None
    if "mfa_policy" not in incoming_settings:
        return incoming_settings, None
    policy = normalize_mfa_policy(incoming_settings.get("mfa_policy"))
    if not policy:
        return None, "mfa_policy must be one of: optional, encouraged, required"
    plan = to_public_plan(org.plan_key)
    if plan in {"free", "starter", "essential"} and policy == MFA_POLICY_REQUIRED:
        return None, "MFA enforcement is only available on Team or Business plans"
    if plan == "business":
        policy = MFA_POLICY_REQUIRED
    next_settings = dict(incoming_settings)
    next_settings["mfa_policy"] = policy
    return next_settings, None


def _slugify(name):
    token = re.sub(r"[^a-z0-9]+", "-", str(name or "").strip().lower()).strip("-")
    return token[:200] or f"org-{uuid.uuid4().hex[:8]}"


def _unique_slug(name):
    base = _slugify(name)
    slug = base
    counter = 2
    while Organization.query.filter_by(slug=slug).first() is not None:
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def _auth_user():
    user_id = str(get_jwt_identity() or "").strip()
    user = User.query.get(user_id) if user_id else None
    if not user:
        return None, (jsonify({"error": "User not found"}), 404)
    return user, None


def _active_membership(org_id, user_id):
    return (
        OrganizationMember.query
        .filter_by(organization_id=str(org_id), user_id=str(user_id), status="active")
        .first()
    )


def _require_org_access(org_id):
    user, err = _auth_user()
    if err:
        return None, None, None, err

    org = Organization.query.filter_by(id=str(org_id)).first()
    if not org:
        return None, None, None, (jsonify({"error": "Organization not found"}), 404)

    # Bring the organization's entitlement up to date BEFORE any gate reads it.
    # This blueprint addresses orgs by id and so never went through org
    # resolution, which is where the plan sync used to live -- leaving
    # _collaboration_gate() evaluating a stale plan_key. Harmless on an upgrade
    # (fails closed), but fail-OPEN on a downgrade: a just-downgraded owner
    # could still invite. Syncs from the OWNER's subscription, never the
    # caller's.
    sync_org_plan_and_commit(org)

    membership = _active_membership(org.id, user.id)
    if not membership:
        return None, None, None, (jsonify({"error": "Not a member of this organization"}), 403)

    return user, org, membership, None


def _org_payload(org, membership_role=None):
    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "owner_id": org.owner_user_id,
        "plan": to_public_plan(org.plan_key),
        "max_admin_seats": getattr(org, "max_admin_seats", None),
        "max_total_paid_seats": getattr(org, "max_total_paid_seats", None),
        "max_creator_seats": getattr(org, "max_creator_seats", None),
        "max_collaborator_seats": getattr(org, "max_collaborator_seats", None),
        "settings": org.settings if isinstance(org.settings, dict) else {},
        "mfa_policy": mfa_policy_for_org(org),
        "created_at": org.created_at.isoformat() if org.created_at else None,
        "updated_at": org.updated_at.isoformat() if org.updated_at else None,
        "user_role": normalize_org_role(membership_role, default=ROLE_VIEWER),
    }


def _member_payload(member):
    user = User.query.get(member.user_id)
    return {
        "id": member.id,
        "organization_id": member.organization_id,
        "user_id": member.user_id,
        "name": (user.name if user else "Unknown"),
        "email": (user.email if user else None),
        "role": normalize_org_role(member.role, default=ROLE_VIEWER),
        "status": member.status or "active",
        "last_active": member.last_active_at.isoformat() if member.last_active_at else None,
        "joined_at": member.joined_at.isoformat() if member.joined_at else None,
        "created_at": member.created_at.isoformat() if member.created_at else None,
    }


def _invitation_payload(invite):
    inviter = User.query.get(invite.invited_by_user_id) if invite.invited_by_user_id else None
    return {
        "id": invite.id,
        "organization_id": invite.organization_id,
        "email": invite.email,
        "role": normalize_org_role(invite.role, default=ROLE_COLLABORATOR),
        "invited_by": invite.invited_by_user_id,
        "invited_by_name": inviter.name if inviter else None,
        "status": invite.status,
        "token": invite.token,
        "expires_at": invite.expires_at.isoformat() if invite.expires_at else None,
        "created_at": invite.created_at.isoformat() if invite.created_at else None,
        "updated_at": invite.updated_at.isoformat() if invite.updated_at else None,
    }


def _send_invitation_email(invite, org):
    frontend_base = (
        current_app.config.get("FRONTEND_BASE_URL")
        or current_app.config.get("APP_FRONTEND_URL")
        or "https://www.jaspen.ai"
    )
    accept_link = f"{str(frontend_base).rstrip('/')}/team?invite={invite.token}"

    subject = f"You were invited to join {org.name} on Jaspen"
    body = (
        f"You've been invited to join {org.name} as a {invite.role}.\n\n"
        f"Accept your invitation:\n{accept_link}\n\n"
        f"This link expires on {invite.expires_at.isoformat() if invite.expires_at else 'soon'}."
    )

    msg = Message(subject=subject, recipients=[invite.email])
    msg.body = body
    mail.send(msg)
    return accept_link


def _collaboration_gate(org):
    """403 payload when this org may not add members right now, else None."""
    state = org_collaboration_state(org, current_app.config)
    if state["can_invite"]:
        return None
    return jsonify({
        "error": collaboration_denied_message(state),
        "reason": state["reason"],
        "plan_key": state["public_plan_key"],
        "required_plan": COLLABORATION_MIN_PLAN,
    }), 403


@teams_bp.route("", methods=["POST"])
@jwt_required()
def create_team_org():
    user, err = _auth_user()
    if err:
        return err

    data = request.get_json() or {}
    name = str(data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    # An org is the vehicle for collaboration, so creating one needs the same
    # entitlement as inviting into one. Without this check a sub-Team user
    # could mint a Team-plan org here and invite through it.
    state = user_collaboration_state(user, current_app.config)
    if not state["can_invite"]:
        return jsonify({
            "error": collaboration_denied_message(state),
            "reason": state["reason"],
            "plan_key": state["public_plan_key"],
            "required_plan": COLLABORATION_MIN_PLAN,
        }), 403

    # UPGRADE IN PLACE, never mint a second owned organization.
    #
    # Every user already owns an organization from signup
    # (orgs.ensure_default_organization_for_user), and their projects, Decision
    # Records, outcomes, lessons and organizational memory are all attached to
    # its id. Creating a fresh Organization here and repointing
    # active_organization_id at it would strand every one of those in an org
    # the user can no longer reach -- silently, because retrieval is scoped to
    # the active organization. Going solo -> team is an UPGRADE of the
    # organization they already have, not a replacement for it.
    #
    # Owning several organizations is not a supported model: billing funds one
    # active org's Thinking Power pool, default resolution always returns the
    # oldest owned org, and nothing in the product enumerates owned orgs.
    # Belonging to other organizations is untouched and stays valid -- that is
    # membership, resolved separately by the organization switcher.
    existing_org, membership, changed = ensure_default_organization_for_user(user)
    if existing_org is not None and existing_org.owner_user_id == user.id:
        # Naming the team is the legitimate part of this request; the identity
        # of the organization is not up for negotiation.
        if name and existing_org.name != name:
            existing_org.name = name
            changed = True
        if changed:
            db.session.commit()
        return jsonify({
            "organization": _org_payload(existing_org, membership_role=ROLE_OWNER),
            # Explicit, so a caller can tell an upgrade from a creation rather
            # than inferring it from the status code.
            "created": False,
            "reused_existing_organization": True,
        }), 200

    plan_key = to_public_plan(normalize_plan_key(user.subscription_plan))
    if plan_key not in {"team", "business"}:
        plan_key = "team"

    catalog = get_plan_catalog(current_app.config)
    plan_cfg = catalog.get(plan_key) or {}

    org = Organization(
        id=str(uuid.uuid4()),
        name=name,
        slug=_unique_slug(name),
        owner_user_id=user.id,
        plan_key=plan_key,
        max_admin_seats=int(plan_cfg.get("max_admin_seats") or 2),
        max_total_paid_seats=(
            int(plan_cfg.get("min_seats"))
            if plan_cfg.get("price_model") == "per_seat" and plan_cfg.get("min_seats") is not None
            else plan_cfg.get("max_total_paid_seats")
        ),
    )
    db.session.add(org)
    db.session.flush()

    member = OrganizationMember(
        organization_id=org.id,
        user_id=user.id,
        role=ROLE_OWNER,
        status="active",
        joined_at=_now(),
        last_active_at=_now(),
    )
    db.session.add(member)

    user.active_organization_id = org.id
    db.session.commit()

    return jsonify({"organization": _org_payload(org, membership_role=ROLE_OWNER)}), 201


@teams_bp.route("", methods=["GET"])
@jwt_required()
def list_team_orgs():
    user, err = _auth_user()
    if err:
        return err

    memberships = (
        OrganizationMember.query
        .filter_by(user_id=user.id, status="active")
        .order_by(OrganizationMember.created_at.asc())
        .all()
    )

    orgs = []
    for membership in memberships:
        org = Organization.query.filter_by(id=membership.organization_id).first()
        if not org:
            continue
        payload = _org_payload(org, membership_role=membership.role)
        payload["is_active"] = (str(user.active_organization_id or "") == str(org.id))
        orgs.append(payload)

    return jsonify(orgs), 200


@teams_bp.route("/<org_id>", methods=["GET"])
@jwt_required()
def get_team_org(org_id):
    user, org, membership, err = _require_org_access(org_id)
    if err:
        return err

    membership.last_active_at = _now()
    db.session.commit()

    page, per_page = _pagination_params()
    member_pagination = (
        OrganizationMember.query
        .filter_by(organization_id=org.id, status="active")
        .order_by(OrganizationMember.created_at.asc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )
    member_items = [_member_payload(item) for item in member_pagination.items]

    invitations = (
        OrganizationInvitation.query
        .filter_by(organization_id=org.id)
        .order_by(OrganizationInvitation.created_at.desc())
        .limit(200)
        .all()
    )

    return jsonify({
        "organization": _org_payload(org, membership_role=membership.role),
        "seat_usage": build_seat_usage(org),
        "items": member_items,
        "members": member_items,
        "total": member_pagination.total,
        "page": member_pagination.page,
        "per_page": member_pagination.per_page,
        "pages": member_pagination.pages,
        "invitations": [_invitation_payload(item) for item in invitations],
    }), 200


@teams_bp.route("/<org_id>", methods=["PATCH"])
@jwt_required()
def update_team_org(org_id):
    _, org, membership, err = _require_org_access(org_id)
    if err:
        return err
    if normalize_org_role(membership.role) not in MANAGE_ROLES:
        return jsonify({"error": "Only owner/admin can update organization"}), 403

    data = request.get_json() or {}
    touched = False
    if "name" in data:
        next_name = str(data.get("name") or "").strip()
        if not next_name:
            return jsonify({"error": "name cannot be empty"}), 400
        org.name = next_name
        touched = True
        if data.get("regenerate_slug"):
            org.slug = _unique_slug(next_name)

    if "settings" in data:
        incoming_settings = data.get("settings")
        if not isinstance(incoming_settings, dict):
            return jsonify({"error": "settings must be an object"}), 400
        normalized_settings, error = _normalize_org_mfa_settings(org, incoming_settings)
        if error:
            return jsonify({"error": error}), 400
        current_settings = org.settings if isinstance(org.settings, dict) else {}
        org.settings = _deep_merge_dict(current_settings, normalized_settings)
        touched = True

    if not touched:
        return jsonify({"error": "name or settings is required"}), 400

    org.updated_at = _now()
    db.session.commit()

    return jsonify({
        "organization": _org_payload(org, membership_role=membership.role),
        "seat_usage": build_seat_usage(org),
    }), 200


@teams_bp.route("/<org_id>/settings", methods=["PATCH"])
@jwt_required()
def update_team_org_settings(org_id):
    _, org, membership, err = _require_org_access(org_id)
    if err:
        return err
    if normalize_org_role(membership.role) not in MANAGE_ROLES:
        return jsonify({"error": "Only owner/admin can update organization settings"}), 403

    data = request.get_json() or {}
    incoming_settings = data.get("settings")
    if not isinstance(incoming_settings, dict):
        return jsonify({"error": "settings must be an object"}), 400

    normalized_settings, error = _normalize_org_mfa_settings(org, incoming_settings)
    if error:
        return jsonify({"error": error}), 400
    current_settings = org.settings if isinstance(org.settings, dict) else {}
    org.settings = _deep_merge_dict(current_settings, normalized_settings)
    org.updated_at = _now()
    db.session.commit()

    return jsonify({
        "organization": _org_payload(org, membership_role=membership.role),
        "settings": org.settings if isinstance(org.settings, dict) else {},
    }), 200


@teams_bp.route("/<org_id>/invite", methods=["POST"])
@jwt_required()
def invite_member(org_id):
    user, org, membership, err = _require_org_access(org_id)
    if err:
        return err
    if normalize_org_role(membership.role) not in MANAGE_ROLES:
        return jsonify({"error": "Only owner/admin can invite members"}), 403

    denied = _collaboration_gate(org)
    if denied:
        return denied

    data = request.get_json() or {}
    email = str(data.get("email") or "").strip().lower()
    role = normalize_org_role(data.get("role"), default=ROLE_COLLABORATOR)

    if not email or "@" not in email:
        return jsonify({"error": "Valid email is required"}), 400
    if role == ROLE_OWNER:
        return jsonify({"error": "Cannot invite owner role"}), 400
    if role not in {ROLE_ADMIN, ROLE_CREATOR, ROLE_COLLABORATOR, ROLE_VIEWER}:
        return jsonify({"error": "Invalid role"}), 400

    existing_user = User.query.filter(func.lower(User.email) == email).first()
    if existing_user:
        existing_membership = _active_membership(org.id, existing_user.id)
        if existing_membership:
            return jsonify({"error": "User is already a member"}), 409

    if not role_has_capacity(org, role):
        return jsonify({"error": f"No available seats for role '{role}'"}), 409

    invite = (
        OrganizationInvitation.query
        .filter_by(organization_id=org.id, email=email, status="pending")
        .order_by(OrganizationInvitation.created_at.desc())
        .first()
    )

    if invite is None:
        invite = OrganizationInvitation(
            organization_id=org.id,
            email=email,
            role=role,
            invited_by_user_id=user.id,
            token=str(uuid.uuid4()),
            status="pending",
            expires_at=_now() + timedelta(days=7),
        )
        db.session.add(invite)
    else:
        invite.role = role
        invite.invited_by_user_id = user.id
        invite.status = "pending"
        invite.expires_at = _now() + timedelta(days=7)
        invite.updated_at = _now()

    db.session.commit()

    email_error = None
    accept_link = None
    try:
        accept_link = _send_invitation_email(invite, org)
    except Exception as exc:
        email_error = str(exc)

    payload = _invitation_payload(invite)
    if accept_link:
        payload["accept_link"] = accept_link

    result = {"invitation": payload}
    if email_error:
        result["email_error"] = email_error

    return jsonify(result), 201


@teams_bp.route("/invitations/<token>/accept", methods=["POST"])
@jwt_required()
def accept_team_invitation(token):
    user, err = _auth_user()
    if err:
        return err

    invite = (
        OrganizationInvitation.query
        .filter_by(token=str(token or "").strip(), status="pending")
        .first()
    )
    if not invite:
        return jsonify({"error": "Invitation not found"}), 404

    if invite.expires_at and invite.expires_at < _now():
        invite.status = "expired"
        db.session.commit()
        return jsonify({"error": "Invitation has expired"}), 410

    if str(user.email or "").strip().lower() != str(invite.email or "").strip().lower():
        return jsonify({"error": "Invitation email does not match signed-in user"}), 403

    org = Organization.query.filter_by(id=invite.organization_id).first()
    if not org:
        return jsonify({"error": "Organization not found"}), 404

    # Same reason as _require_org_access: the invitee is not a member yet, so
    # this path never went through org resolution either. Without the sync the
    # accept gate below would read a stale plan and let someone join an
    # organization that has since downgraded.
    sync_org_plan_and_commit(org)

    # Re-checked at accept: the org may have downgraded below Team, or gone
    # past due, between the invitation being sent and this link being clicked.
    denied = _collaboration_gate(org)
    if denied:
        return denied

    role = normalize_org_role(invite.role, default=ROLE_COLLABORATOR)
    existing = _active_membership(org.id, user.id)

    if existing:
        if role != existing.role:
            if not role_has_capacity(org, role, exclude_member_id=existing.id):
                return jsonify({"error": f"No available seats for role '{role}'"}), 409
            existing.role = role
            existing.updated_at = _now()
        member = existing
    else:
        if not role_has_capacity(org, role):
            return jsonify({"error": f"No available seats for role '{role}'"}), 409
        member = OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role=role,
            status="active",
            invited_by_user_id=invite.invited_by_user_id,
            joined_at=_now(),
            last_active_at=_now(),
        )
        db.session.add(member)

    invite.status = "accepted"
    invite.accepted_by_user_id = user.id
    invite.accepted_at = _now()
    invite.updated_at = _now()

    user.active_organization_id = org.id

    db.session.commit()

    return jsonify({
        "organization": _org_payload(org, membership_role=member.role),
        "member": _member_payload(member),
        "seat_usage": build_seat_usage(org),
    }), 200


@teams_bp.route("/<org_id>/members/<member_id>", methods=["PATCH"])
@jwt_required()
def update_team_member_role(org_id, member_id):
    _, org, membership, err = _require_org_access(org_id)
    if err:
        return err
    if normalize_org_role(membership.role) not in MANAGE_ROLES:
        return jsonify({"error": "Only owner/admin can change roles"}), 403

    try:
        member_pk = int(str(member_id))
    except Exception:
        return jsonify({"error": "Invalid member_id"}), 400

    target = (
        OrganizationMember.query
        .filter_by(id=member_pk, organization_id=org.id, status="active")
        .first()
    )
    if not target:
        return jsonify({"error": "Member not found"}), 404

    if str(target.user_id) == str(org.owner_user_id):
        return jsonify({"error": "Cannot change owner role"}), 400

    data = request.get_json() or {}
    next_role = normalize_org_role(data.get("role"), default="")
    if next_role not in {ROLE_ADMIN, ROLE_CREATOR, ROLE_COLLABORATOR, ROLE_VIEWER}:
        return jsonify({"error": "Invalid role"}), 400

    if not role_has_capacity(org, next_role, exclude_member_id=target.id):
        return jsonify({"error": f"No available seats for role '{next_role}'"}), 409

    target.role = next_role
    target.updated_at = _now()
    db.session.commit()

    return jsonify({"member": _member_payload(target)}), 200


@teams_bp.route("/<org_id>/members/<member_id>", methods=["DELETE"])
@jwt_required()
def remove_team_member(org_id, member_id):
    user, org, membership, err = _require_org_access(org_id)
    if err:
        return err
    if normalize_org_role(membership.role) not in MANAGE_ROLES:
        return jsonify({"error": "Only owner/admin can remove members"}), 403

    try:
        member_pk = int(str(member_id))
    except Exception:
        return jsonify({"error": "Invalid member_id"}), 400

    target = (
        OrganizationMember.query
        .filter_by(id=member_pk, organization_id=org.id, status="active")
        .first()
    )
    if not target:
        return jsonify({"error": "Member not found"}), 404

    if str(target.user_id) == str(org.owner_user_id):
        return jsonify({"error": "Owner cannot be removed"}), 400

    if str(target.user_id) == str(user.id):
        return jsonify({"error": "Use leave flow to remove yourself"}), 400

    from app.models_pm_sync import PmSyncBinding
    from app.pm_sync.access import mark_binding
    for binding in PmSyncBinding.query.filter_by(
        user_id=str(target.user_id), organization_id=str(org.id)
    ).all():
        mark_binding(
            binding,
            status="paused",
            warning_code="sync_owner_left_organization",
            pause_reason="sync_owner_left_organization",
        )
    db.session.delete(target)
    db.session.commit()
    return jsonify({"success": True}), 200


@teams_bp.route("/<org_id>/seat-usage", methods=["GET"])
@jwt_required()
def team_seat_usage(org_id):
    _, org, _, err = _require_org_access(org_id)
    if err:
        return err

    # The shared engine already returns every role plus the paid-seat totals,
    # so return it whole rather than re-projecting a subset of it here.
    return jsonify(build_seat_usage(org)), 200


# Additional helpers used by Team UI for pending-invitation workflows.
@teams_bp.route("/<org_id>/invitations", methods=["GET"])
@jwt_required()
def list_team_invitations(org_id):
    _, org, _, err = _require_org_access(org_id)
    if err:
        return err

    invitations = (
        OrganizationInvitation.query
        .filter_by(organization_id=org.id)
        .order_by(OrganizationInvitation.created_at.desc())
        .limit(200)
        .all()
    )
    return jsonify({"invitations": [_invitation_payload(item) for item in invitations]}), 200


@teams_bp.route("/<org_id>/invitations/<invitation_id>/resend", methods=["POST"])
@jwt_required()
def resend_team_invitation(org_id, invitation_id):
    _, org, membership, err = _require_org_access(org_id)
    if err:
        return err
    if normalize_org_role(membership.role) not in MANAGE_ROLES:
        return jsonify({"error": "Only owner/admin can resend invitations"}), 403

    # Resending is an invite action. An org that dropped below Team, or fell
    # past due, must not keep pushing out links that accept_team_invitation
    # would refuse anyway.
    denied = _collaboration_gate(org)
    if denied:
        return denied

    invite = (
        OrganizationInvitation.query
        .filter_by(id=str(invitation_id), organization_id=org.id)
        .first()
    )
    if not invite:
        return jsonify({"error": "Invitation not found"}), 404
    if invite.status != "pending":
        return jsonify({"error": "Only pending invitations can be resent"}), 400

    invite.expires_at = _now() + timedelta(days=7)
    invite.updated_at = _now()
    db.session.commit()

    email_error = None
    accept_link = None
    try:
        accept_link = _send_invitation_email(invite, org)
    except Exception as exc:
        email_error = str(exc)

    payload = _invitation_payload(invite)
    if accept_link:
        payload["accept_link"] = accept_link
    out = {"invitation": payload}
    if email_error:
        out["email_error"] = email_error
    return jsonify(out), 200


@teams_bp.route("/<org_id>/invitations/<invitation_id>", methods=["DELETE"])
@jwt_required()
def cancel_team_invitation(org_id, invitation_id):
    _, org, membership, err = _require_org_access(org_id)
    if err:
        return err
    if normalize_org_role(membership.role) not in MANAGE_ROLES:
        return jsonify({"error": "Only owner/admin can cancel invitations"}), 403

    invite = (
        OrganizationInvitation.query
        .filter_by(id=str(invitation_id), organization_id=org.id)
        .first()
    )
    if not invite:
        return jsonify({"error": "Invitation not found"}), 404

    if invite.status != "pending":
        return jsonify({"error": "Only pending invitations can be cancelled"}), 400

    invite.status = "revoked"
    invite.updated_at = _now()
    db.session.commit()
    return jsonify({"success": True}), 200


# ── Enterprise SSO settings ─────────────────────────────────────────────────
#
# Organization owners/admins manage their own SSO boundary here. Jaspen staff
# activate SSO for a signed customer separately (admin route); until then the
# org stays "off" and nothing here can enforce it. Every change is audited.

def _sso_settings_payload(org):
    return {
        "enabled": bool(current_app.config.get("SSO_ENABLED")),
        "status": org.sso_status or "off",
        "enforced": bool(org.sso_enforced),
        "enforced_at": org.sso_enforced_at.isoformat() if org.sso_enforced_at else None,
        "grace_until": org.sso_grace_until.isoformat() if org.sso_grace_until else None,
        "mfa_attested": bool(org.sso_mfa_attested_at),
        "mfa_attested_at": org.sso_mfa_attested_at.isoformat() if org.sso_mfa_attested_at else None,
        "recovery_admin_user_id": org.sso_recovery_admin_user_id,
        "sessions_revoked_at": org.sso_sessions_revoked_at.isoformat() if org.sso_sessions_revoked_at else None,
    }


def _require_sso_manager(org_id):
    """Owner/admin of the org, reached through SSO or the recovery path."""
    from app.org_access import sso_allows, sso_recovery_permitted

    user, err = _auth_user()
    if err:
        return None, None, err
    org = Organization.query.filter_by(id=str(org_id)).first()
    # Direct membership lookup: the recovery admin must still reach these
    # settings while the org refuses non-SSO sessions everywhere else.
    membership = OrganizationMember.query.filter_by(
        organization_id=str(org_id), user_id=str(user.id), status="active",
    ).first() if org else None
    if not org or membership is None:
        return None, None, (jsonify({"error": "Organization not found"}), 404)
    if normalize_org_role(membership.role) not in MANAGE_ROLES:
        return None, None, (jsonify({"error": "Only owners and admins can manage SSO"}), 403)
    if not (sso_allows(org.id) or sso_recovery_permitted(org, user)):
        return None, None, (jsonify({"error": "Sign in with your organization's SSO", "code": "sso_required"}), 403)
    return user, org, None


@teams_bp.route("/<org_id>/sso", methods=["GET"])
@jwt_required()
def get_org_sso_settings(org_id):
    _user, org, err = _require_sso_manager(org_id)
    if err:
        return err
    return jsonify({"sso": _sso_settings_payload(org)}), 200


@teams_bp.route("/<org_id>/sso", methods=["PATCH"])
@jwt_required()
def update_org_sso_settings(org_id):
    from app.admin_audit import append_admin_audit_event

    user, org, err = _require_sso_manager(org_id)
    if err:
        return err
    body = request.get_json(silent=True) or {}
    now = datetime.utcnow()
    changes = {}

    if "recovery_admin_user_id" in body:
        target_id = str(body.get("recovery_admin_user_id") or "").strip() or None
        if target_id:
            target = OrganizationMember.query.filter_by(
                organization_id=org.id, user_id=target_id, status="active",
            ).first()
            target_user = User.query.get(target_id)
            if not target or normalize_org_role(target.role) not in MANAGE_ROLES:
                return jsonify({"error": "The recovery admin must be an owner or admin of this organization"}), 400
            if not target_user or not bool(getattr(target_user, "mfa_enabled", False)):
                return jsonify({"error": "The recovery admin must have two-factor authentication turned on", "code": "recovery_admin_mfa_required"}), 400
        org.sso_recovery_admin_user_id = target_id
        changes["recovery_admin_user_id"] = target_id

    if "mfa_attested" in body:
        attested = bool(body.get("mfa_attested"))
        org.sso_mfa_attested_at = now if attested else None
        org.sso_mfa_attested_by = user.id if attested else None
        changes["mfa_attested"] = attested

    if "enforced" in body:
        enforce = bool(body.get("enforced"))
        if enforce:
            if not current_app.config.get("SSO_ENABLED") or org.sso_status != "active" or not org.workos_organization_id:
                return jsonify({"error": "SSO is not active for this organization yet", "code": "sso_not_active"}), 409
            if not org.sso_recovery_admin_user_id:
                return jsonify({"error": "Choose a recovery admin before enforcing SSO", "code": "recovery_admin_required"}), 409
            try:
                grace_hours = max(0, min(168, int(body.get("grace_hours") or 0)))
            except (TypeError, ValueError):
                return jsonify({"error": "grace_hours must be a whole number of hours"}), 400
            org.sso_enforced = True
            org.sso_enforced_at = now
            org.sso_grace_until = now + timedelta(hours=grace_hours) if grace_hours else None
            changes["enforced"] = True
            changes["grace_hours"] = grace_hours
        else:
            org.sso_enforced = False
            org.sso_grace_until = None
            changes["enforced"] = False

    if body.get("revoke_sessions") is True:
        org.sso_sessions_revoked_at = now
        changes["revoke_sessions"] = True

    if not changes:
        return jsonify({"error": "No supported SSO setting was provided"}), 400

    append_admin_audit_event(
        actor_user_id=user.id,
        actor_email=user.email,
        action="org_sso_settings_changed",
        details={"organization_id": org.id, "changes": changes},
    )
    db.session.commit()
    return jsonify({"sso": _sso_settings_payload(org)}), 200


# ── Data-sharing choices (privacy) ──────────────────────────────────────────

@teams_bp.route("/<org_id>/data-sharing", methods=["GET"])
@jwt_required()
def get_org_data_sharing(org_id):
    from app.data_sharing import data_sharing_choices
    _user, org, _membership, err = _require_org_access(org_id)
    if err:
        return err
    return jsonify({"data_sharing": data_sharing_choices(org)}), 200


@teams_bp.route("/<org_id>/data-sharing", methods=["PUT", "PATCH"])
@jwt_required()
def update_org_data_sharing(org_id):
    from app.admin_audit import append_admin_audit_event
    from app.data_sharing import DEFAULTS, data_sharing_choices

    user, org, membership, err = _require_org_access(org_id)
    if err:
        return err
    if normalize_org_role(membership.role) not in MANAGE_ROLES:
        return jsonify({"error": "Only owners and admins can change data-sharing choices"}), 403
    body = request.get_json(silent=True) or {}
    changes = {key: body[key] for key in DEFAULTS if key in body}
    if not changes or any(not isinstance(value, bool) for value in changes.values()):
        return jsonify({"error": "Send improve_jaspen and/or decision_sharing_allowed as true or false"}), 400
    before = data_sharing_choices(org)
    settings = dict(org.settings) if isinstance(org.settings, dict) else {}
    stored = dict(settings.get("data_sharing") or {})
    stored.update(changes)
    stored["updated_at"] = _now().isoformat()
    stored["updated_by"] = user.id
    settings["data_sharing"] = stored
    org.settings = settings
    org.updated_at = _now()
    append_admin_audit_event(
        actor_user_id=user.id,
        actor_email=user.email,
        action="org_data_sharing_changed",
        details={
            "organization_id": org.id,
            "changes": {key: {"from": before[key], "to": value} for key, value in changes.items()},
        },
    )
    db.session.commit()
    return jsonify({"data_sharing": data_sharing_choices(org)}), 200


# ── Organization data export (privacy) ──────────────────────────────────────
#
# An organization owner can download the organization's work as JSON. The
# export never widens access: it contains only what the owner can already
# read (other members' private projects stay with those members), and never
# includes share-link tokens, connector credentials, or staff-only data.
# Deletion stays a support request until a reviewed self-serve flow exists.

_EXPORT_DELETION_NOTE = (
    "To delete your organization's data, email support@jaspen.ai from an owner "
    "account. Deleted data leaves database backups within 7 days."
)


def _iso_or_none(value):
    return value.isoformat() if value else None


@teams_bp.route("/<org_id>/export", methods=["GET"])
@jwt_required()
@limiter.limit("5 per hour")
def export_org_data(org_id):
    from app.admin_audit import append_admin_audit_event
    from app.decision_records import can_read_record
    from app.models import Scorecard, SharedArtifact, SharedArtifactOwnership, UserSession
    from app.models_decision_record import DecisionRecord
    from app.session_access import can_read_session

    user, org, membership, err = _require_org_access(org_id)
    if err:
        return err
    if normalize_org_role(membership.role) != "owner":
        return jsonify({"error": "Only the organization owner can export its data"}), 403

    projects = []
    readable_threads = set()
    for row in UserSession.query.filter_by(organization_id=org.id).order_by(UserSession.created_at.asc()).all():
        if not can_read_session(row, user, membership=membership):
            continue
        readable_threads.add(row.session_id)
        projects.append({
            "session_id": row.session_id,
            "name": row.name,
            "visibility": row.visibility,
            "created_at": _iso_or_none(row.created_at),
            "updated_at": _iso_or_none(row.updated_at),
            "archived_at": _iso_or_none(row.archived_at),
            "payload": row.payload if isinstance(row.payload, dict) else {},
            "scenarios": row.scenarios_json if isinstance(row.scenarios_json, dict) else {},
        })

    scorecards = [
        {"id": card.id, "thread_id": card.thread_id, "created_at": _iso_or_none(card.created_at),
         "archived_at": _iso_or_none(card.archived_at), "data": card.data if isinstance(card.data, dict) else {}}
        for card in Scorecard.query.filter_by(organization_id=org.id).all()
        if card.thread_id in readable_threads
    ]

    records = [
        record.to_dict()
        for record in DecisionRecord.query.filter_by(organization_id=org.id).all()
        if can_read_record(record, user, membership=membership)
    ]

    share_links = [
        {"id": link.id, "artifact_type": link.artifact_type, "title": link.title,
         "thread_id": link.thread_id, "created_at": _iso_or_none(link.created_at),
         "expires_at": _iso_or_none(link.expires_at), "revoked_at": _iso_or_none(link.revoked_at)}
        for link in SharedArtifact.query.join(
            SharedArtifactOwnership, SharedArtifactOwnership.shared_artifact_id == SharedArtifact.id,
        ).filter(SharedArtifactOwnership.organization_id == org.id).all()
        if link.thread_id in readable_threads
    ]

    members = [
        {"user_id": m.user_id, "role": m.role, "joined_at": _iso_or_none(m.joined_at),
         "email": getattr(db.session.get(User, m.user_id), "email", None)}
        for m in OrganizationMember.query.filter_by(organization_id=org.id, status="active").all()
    ]

    append_admin_audit_event(
        actor_user_id=user.id,
        actor_email=user.email,
        action="org_data_exported",
        details={"organization_id": org.id, "projects": len(projects), "scorecards": len(scorecards),
                 "decision_records": len(records), "share_links": len(share_links)},
    )
    db.session.commit()

    from app.data_sharing import data_sharing_choices
    response = jsonify({
        "exported_at": _now().isoformat(),
        "organization": {"id": org.id, "name": org.name, "plan_key": org.plan_key},
        "data_sharing": data_sharing_choices(org),
        "members": members,
        "projects": projects,
        "scorecards": scorecards,
        "decision_records": records,
        "share_links": share_links,
        "excluded": [
            "Other members' private projects (they can export their own)",
            "Share-link access tokens",
            "Connector credentials and synced connector caches",
        ],
        "deletion": _EXPORT_DELETION_NOTE,
    })
    response.headers["Content-Disposition"] = f'attachment; filename="jaspen-export-{org.id}.json"'
    response.headers["Cache-Control"] = "no-store"
    return response, 200
