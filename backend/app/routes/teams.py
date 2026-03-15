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


teams_bp = Blueprint("teams", __name__)

ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_CREATOR = "creator"
ROLE_COLLABORATOR = "collaborator"
ROLE_VIEWER = "viewer"

ROLE_SET = {ROLE_OWNER, ROLE_ADMIN, ROLE_CREATOR, ROLE_COLLABORATOR, ROLE_VIEWER}
MANAGE_ROLES = {ROLE_OWNER, ROLE_ADMIN}


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


def _normalize_role(value, default=ROLE_COLLABORATOR):
    role = str(value or "").strip().lower()
    return role if role in ROLE_SET else default


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


def _plan_caps_for_org(org):
    plan_key = to_public_plan(org.plan_key)
    catalog = get_plan_catalog(current_app.config)
    plan = catalog.get(plan_key) or {}

    default_admin = plan.get("max_admin_seats")
    default_viewer = plan.get("max_viewer_seats")

    admin_cap = org.max_admin_seats if getattr(org, "max_admin_seats", None) is not None else default_admin
    creator_cap = None if plan_key in {"team", "enterprise"} else (
        org.max_creator_seats if getattr(org, "max_creator_seats", None) is not None else plan.get("max_creator_seats")
    )
    collaborator_cap = None if plan_key in {"team", "enterprise"} else (
        org.max_collaborator_seats if getattr(org, "max_collaborator_seats", None) is not None else plan.get("max_collaborator_seats")
    )
    total_paid_cap = getattr(org, "max_total_paid_seats", None)
    if total_paid_cap is None:
        total_paid_cap = plan.get("max_total_paid_seats")

    return {
        ROLE_ADMIN: admin_cap,
        ROLE_CREATOR: creator_cap,
        ROLE_COLLABORATOR: collaborator_cap,
        ROLE_VIEWER: default_viewer,
        "total_paid": total_paid_cap,
    }


def _seat_usage(org):
    rows = (
        db.session.query(OrganizationMember.role, func.count(OrganizationMember.id))
        .filter(OrganizationMember.organization_id == org.id, OrganizationMember.status == "active")
        .group_by(OrganizationMember.role)
        .all()
    )
    counts = {str(role or "").lower(): int(count or 0) for role, count in rows}

    owner_used = int(counts.get(ROLE_OWNER, 0))
    admin_used = int(counts.get(ROLE_ADMIN, 0)) + owner_used
    creator_used = int(counts.get(ROLE_CREATOR, 0))
    collaborator_used = int(counts.get(ROLE_COLLABORATOR, 0))
    viewer_used = int(counts.get(ROLE_VIEWER, 0))

    caps = _plan_caps_for_org(org)
    total_paid_used = admin_used + creator_used + collaborator_used
    return {
        ROLE_ADMIN: {"used": admin_used, "max": caps.get(ROLE_ADMIN)},
        ROLE_CREATOR: {"used": creator_used, "max": caps.get(ROLE_CREATOR)},
        ROLE_COLLABORATOR: {"used": collaborator_used, "max": caps.get(ROLE_COLLABORATOR)},
        ROLE_VIEWER: {"used": viewer_used, "max": caps.get(ROLE_VIEWER)},
        ROLE_OWNER: {"used": owner_used, "max": 1},
        "total_paid_used": total_paid_used,
        "total_paid_limit": caps.get("total_paid"),
    }


def _role_has_capacity(org, role, exclude_member=None):
    role = _normalize_role(role, default="")
    if role == ROLE_OWNER:
        return False

    usage = _seat_usage(org)
    plan_key = to_public_plan(org.plan_key)
    ex_role = _normalize_role(getattr(exclude_member, "role", ""), default="") if exclude_member is not None else ""

    if plan_key in {"team", "enterprise"}:
        if role == ROLE_ADMIN:
            admin_used = int((usage.get(ROLE_ADMIN) or {}).get("used") or 0)
            if ex_role in {ROLE_OWNER, ROLE_ADMIN}:
                admin_used = max(0, admin_used - 1)
            admin_cap = (usage.get(ROLE_ADMIN) or {}).get("max")
            if admin_cap is not None and admin_used >= int(admin_cap):
                return False

        if role in {ROLE_ADMIN, ROLE_CREATOR, ROLE_COLLABORATOR}:
            total_paid_used = int(usage.get("total_paid_used") or 0)
            if ex_role in {ROLE_OWNER, ROLE_ADMIN, ROLE_CREATOR, ROLE_COLLABORATOR}:
                total_paid_used = max(0, total_paid_used - 1)
            total_paid_limit = usage.get("total_paid_limit")
            if total_paid_limit is not None and total_paid_used >= int(total_paid_limit):
                return False
        return True

    target = usage.get(role) or {"used": 0, "max": None}
    used = int(target.get("used") or 0)
    max_allowed = target.get("max")

    if role == ROLE_ADMIN and ex_role in {ROLE_OWNER, ROLE_ADMIN}:
        used = max(0, used - 1)
    elif role == ex_role:
        used = max(0, used - 1)

    if max_allowed is None:
        return True
    return used < int(max_allowed)


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
        "created_at": org.created_at.isoformat() if org.created_at else None,
        "updated_at": org.updated_at.isoformat() if org.updated_at else None,
        "user_role": _normalize_role(membership_role, default=ROLE_VIEWER),
    }


def _member_payload(member):
    user = User.query.get(member.user_id)
    return {
        "id": member.id,
        "organization_id": member.organization_id,
        "user_id": member.user_id,
        "name": (user.name if user else "Unknown"),
        "email": (user.email if user else None),
        "role": _normalize_role(member.role, default=ROLE_VIEWER),
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
        "role": _normalize_role(invite.role, default=ROLE_COLLABORATOR),
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

    plan_key = to_public_plan(normalize_plan_key(user.subscription_plan))
    if plan_key not in {"team", "enterprise"}:
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
        max_creator_seats=int(plan_cfg.get("max_creator_seats") or 5),
        max_collaborator_seats=int(plan_cfg.get("max_collaborator_seats") or 10),
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
        "seat_usage": _seat_usage(org),
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
    if _normalize_role(membership.role) not in MANAGE_ROLES:
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
        current_settings = org.settings if isinstance(org.settings, dict) else {}
        org.settings = _deep_merge_dict(current_settings, incoming_settings)
        touched = True

    if not touched:
        return jsonify({"error": "name or settings is required"}), 400

    org.updated_at = _now()
    db.session.commit()

    return jsonify({
        "organization": _org_payload(org, membership_role=membership.role),
        "seat_usage": _seat_usage(org),
    }), 200


@teams_bp.route("/<org_id>/settings", methods=["PATCH"])
@jwt_required()
def update_team_org_settings(org_id):
    _, org, membership, err = _require_org_access(org_id)
    if err:
        return err
    if _normalize_role(membership.role) not in MANAGE_ROLES:
        return jsonify({"error": "Only owner/admin can update organization settings"}), 403

    data = request.get_json() or {}
    incoming_settings = data.get("settings")
    if not isinstance(incoming_settings, dict):
        return jsonify({"error": "settings must be an object"}), 400

    current_settings = org.settings if isinstance(org.settings, dict) else {}
    org.settings = _deep_merge_dict(current_settings, incoming_settings)
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
    if _normalize_role(membership.role) not in MANAGE_ROLES:
        return jsonify({"error": "Only owner/admin can invite members"}), 403

    data = request.get_json() or {}
    email = str(data.get("email") or "").strip().lower()
    role = _normalize_role(data.get("role"), default=ROLE_COLLABORATOR)

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

    if not _role_has_capacity(org, role):
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

    role = _normalize_role(invite.role, default=ROLE_COLLABORATOR)
    existing = _active_membership(org.id, user.id)

    if existing:
        if role != existing.role:
            if not _role_has_capacity(org, role, exclude_member=existing):
                return jsonify({"error": f"No available seats for role '{role}'"}), 409
            existing.role = role
            existing.updated_at = _now()
        member = existing
    else:
        if not _role_has_capacity(org, role):
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
        "seat_usage": _seat_usage(org),
    }), 200


@teams_bp.route("/<org_id>/members/<member_id>", methods=["PATCH"])
@jwt_required()
def update_team_member_role(org_id, member_id):
    _, org, membership, err = _require_org_access(org_id)
    if err:
        return err
    if _normalize_role(membership.role) not in MANAGE_ROLES:
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
    next_role = _normalize_role(data.get("role"), default="")
    if next_role not in {ROLE_ADMIN, ROLE_CREATOR, ROLE_COLLABORATOR, ROLE_VIEWER}:
        return jsonify({"error": "Invalid role"}), 400

    if not _role_has_capacity(org, next_role, exclude_member=target):
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
    if _normalize_role(membership.role) not in MANAGE_ROLES:
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

    usage = _seat_usage(org)
    return jsonify({
        ROLE_ADMIN: usage.get(ROLE_ADMIN),
        ROLE_CREATOR: usage.get(ROLE_CREATOR),
        ROLE_COLLABORATOR: usage.get(ROLE_COLLABORATOR),
        ROLE_VIEWER: usage.get(ROLE_VIEWER),
    }), 200


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
    if _normalize_role(membership.role) not in MANAGE_ROLES:
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
    if _normalize_role(membership.role) not in MANAGE_ROLES:
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
