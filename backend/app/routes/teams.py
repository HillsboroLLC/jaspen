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

from app import db, mail
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
