import secrets
from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import func

from app import db
from app.orgs import (
    ORG_ROLE_OWNER,
    ORG_ROLES,
    active_membership_for_user,
    build_seat_usage,
    can_edit_projects,
    can_manage_org,
    ensure_default_organization_for_user,
    invitation_is_expired,
    invitation_payload,
    new_invitation_expiry,
    normalize_org_role,
    org_payload,
    resolve_active_org_for_user,
    role_has_capacity,
    role_label,
    touch_member_activity,
)
from app.models import Organization, OrganizationInvitation, OrganizationMember, User, UserSession


team_bp = Blueprint("team", __name__)
PROJECT_VISIBILITY_VALUES = {"private", "team", "specific"}


def _now_iso():
    return datetime.utcnow().isoformat()


def _auth_context():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return None, None, None, (jsonify({"error": "User not found"}), 404)

    org, membership = resolve_active_org_for_user(user)
    if not org or not membership:
        return user, None, None, (jsonify({"error": "No active organization"}), 404)

    return user, org, membership, None


def _membership_payload(member, include_user=True):
    payload = {
        "id": member.id,
        "organization_id": member.organization_id,
        "user_id": member.user_id,
        "role": normalize_org_role(member.role),
        "role_label": role_label(member.role),
        "status": member.status,
        "joined_at": member.joined_at.isoformat() if member.joined_at else None,
        "last_active_at": member.last_active_at.isoformat() if member.last_active_at else None,
        "created_at": member.created_at.isoformat() if member.created_at else None,
        "updated_at": member.updated_at.isoformat() if member.updated_at else None,
    }
    if include_user:
        user = User.query.get(member.user_id)
        payload["user"] = {
            "id": user.id if user else member.user_id,
            "email": user.email if user else None,
            "name": user.name if user else "Unknown",
            "subscription_plan": user.subscription_plan if user else None,
        }
    return payload


def _get_project_row(org_id, session_id):
    return (
        UserSession.query
        .filter_by(organization_id=str(org_id), session_id=str(session_id))
        .order_by(UserSession.updated_at.desc(), UserSession.id.desc())
        .first()
    )


def _project_payload(row):
    payload = row.payload if isinstance(row.payload, dict) else {}
    owner_id = row.created_by_user_id or row.user_id
    owner = User.query.get(owner_id) if owner_id else None
    comments = payload.get("comments") if isinstance(payload.get("comments"), list) else []
    activity = payload.get("activity_feed") if isinstance(payload.get("activity_feed"), list) else []
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    return {
        "session_id": row.session_id,
        "name": payload.get("name") or result.get("project_name") or "Untitled project",
        "status": payload.get("status") or row.status or "in_progress",
        "visibility": row.visibility or payload.get("visibility") or "private",
        "shared_with_user_ids": row.shared_with_user_ids if isinstance(row.shared_with_user_ids, list) else [],
        "organization_id": row.organization_id,
        "created_by_user_id": owner_id,
        "owner_name": owner.name if owner else "Unknown",
        "owner_email": owner.email if owner else None,
        "analysis_id": result.get("analysis_id") or result.get("id"),
        "score": result.get("jaspen_score") or result.get("overall_score") or result.get("score"),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "comment_count": len(comments),
        "activity_count": len(activity),
    }


def _can_access_project(row, user_id):
    if not isinstance(row, UserSession):
        return False
    uid = str(user_id)
    owner_id = str(row.created_by_user_id or row.user_id or "")
    if uid == owner_id or uid == str(row.user_id or ""):
        return True
    visibility = str(row.visibility or "private").strip().lower()
    if visibility == "team":
        return True
    if visibility == "specific":
        allowed = row.shared_with_user_ids if isinstance(row.shared_with_user_ids, list) else []
        return uid in {str(item or "").strip() for item in allowed if str(item or "").strip()}
    return False


def _append_activity(row, actor, action, details=None):
    payload = row.payload if isinstance(row.payload, dict) else {}
    feed = payload.get("activity_feed")
    if not isinstance(feed, list):
        feed = []
    feed.insert(0, {
        "id": f"act_{secrets.token_hex(6)}",
        "timestamp": _now_iso(),
        "action": str(action or "").strip() or "updated",
        "actor_user_id": actor.id if actor else None,
        "actor_name": actor.name if actor else "Unknown",
        "details": details if isinstance(details, dict) else {},
    })
    payload["activity_feed"] = feed[:250]
    row.payload = payload


@team_bp.route("/summary", methods=["GET"])
@jwt_required()
def team_summary():
    user, org, membership, error = _auth_context()
    if error:
        return error

    touch_member_activity(membership)

    pending_invites = (
        OrganizationInvitation.query
        .filter_by(organization_id=org.id, status="pending")
        .count()
    )
    member_count = (
        OrganizationMember.query
        .filter_by(organization_id=org.id, status="active")
        .count()
    )

    return jsonify({
        "success": True,
        "organization": org_payload(org),
        "membership": _membership_payload(membership),
        "seat_usage": build_seat_usage(org),
        "member_count": member_count,
        "pending_invitation_count": pending_invites,
        "permissions": {
            "can_manage_members": can_manage_org(membership.role),
        },
        "timestamp": _now_iso(),
    }), 200


@team_bp.route("/organizations", methods=["GET"])
@jwt_required()
def list_user_organizations():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    org, membership, changed = ensure_default_organization_for_user(user)
    if changed:
        db.session.commit()

    memberships = (
        OrganizationMember.query
        .filter_by(user_id=user.id, status="active")
        .order_by(OrganizationMember.created_at.asc())
        .all()
    )

    rows = []
    for item in memberships:
        org_row = Organization.query.get(item.organization_id)
        if not org_row:
            continue
        rows.append({
            "organization": org_payload(org_row),
            "membership": _membership_payload(item, include_user=False),
            "is_active": user.active_organization_id == org_row.id,
        })

    return jsonify({"success": True, "organizations": rows}), 200


@team_bp.route("/organizations/active", methods=["POST"])
@jwt_required()
def set_active_organization():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json() or {}
    org_id = str(data.get("organization_id") or "").strip()
    if not org_id:
        return jsonify({"error": "organization_id is required"}), 400

    membership = active_membership_for_user(org_id, user.id)
    if not membership:
        return jsonify({"error": "No membership for selected organization"}), 403

    user.active_organization_id = org_id
    touch_member_activity(membership)
    return jsonify({
        "success": True,
        "organization_id": org_id,
    }), 200


@team_bp.route("/members", methods=["GET"])
@jwt_required()
def list_members():
    _, org, membership, error = _auth_context()
    if error:
        return error

    touch_member_activity(membership)

    members = (
        OrganizationMember.query
        .filter_by(organization_id=org.id, status="active")
        .order_by(OrganizationMember.role.asc(), OrganizationMember.created_at.asc())
        .all()
    )

    return jsonify({
        "success": True,
        "organization": org_payload(org),
        "seat_usage": build_seat_usage(org),
        "members": [_membership_payload(item) for item in members],
    }), 200


@team_bp.route("/members/<int:member_id>", methods=["PATCH"])
@jwt_required()
def update_member_role(member_id):
    user, org, actor_membership, error = _auth_context()
    if error:
        return error
    if not can_manage_org(actor_membership.role):
        return jsonify({"error": "Only org owners/admins can update roles"}), 403

    target = OrganizationMember.query.filter_by(
        id=int(member_id),
        organization_id=org.id,
        status="active",
    ).first()
    if not target:
        return jsonify({"error": "Member not found"}), 404

    if target.user_id == org.owner_user_id:
        return jsonify({"error": "Owner role cannot be modified from this endpoint"}), 400

    data = request.get_json() or {}
    next_role = normalize_org_role(data.get("role"))
    if next_role not in ORG_ROLES or next_role == ORG_ROLE_OWNER:
        return jsonify({"error": "Invalid role"}), 400

    if target.role == next_role:
        return jsonify({
            "success": True,
            "member": _membership_payload(target),
            "seat_usage": build_seat_usage(org),
        }), 200

    if not role_has_capacity(org, next_role, exclude_member_id=target.id):
        return jsonify({"error": f"No available seats for role '{next_role}'"}), 409

    target.role = next_role
    target.updated_at = datetime.utcnow()
    touch_member_activity(actor_membership)

    return jsonify({
        "success": True,
        "member": _membership_payload(target),
        "seat_usage": build_seat_usage(org),
    }), 200


@team_bp.route("/members/<int:member_id>", methods=["DELETE"])
@jwt_required()
def remove_member(member_id):
    user, org, actor_membership, error = _auth_context()
    if error:
        return error
    if not can_manage_org(actor_membership.role):
        return jsonify({"error": "Only org owners/admins can remove members"}), 403

    target = OrganizationMember.query.filter_by(
        id=int(member_id),
        organization_id=org.id,
        status="active",
    ).first()
    if not target:
        return jsonify({"error": "Member not found"}), 404

    if target.user_id == org.owner_user_id:
        return jsonify({"error": "Owner cannot be removed"}), 400
    if target.user_id == user.id:
        return jsonify({"error": "Use leave-organization flow to remove yourself"}), 400

    removed_user = User.query.get(target.user_id)
    db.session.delete(target)
    if removed_user and removed_user.active_organization_id == org.id:
        removed_user.active_organization_id = None
        ensure_default_organization_for_user(removed_user)
    touch_member_activity(actor_membership)

    return jsonify({
        "success": True,
        "removed_member_id": member_id,
        "seat_usage": build_seat_usage(org),
    }), 200


@team_bp.route("/invitations", methods=["GET"])
@jwt_required()
def list_invitations():
    _, org, membership, error = _auth_context()
    if error:
        return error

    touch_member_activity(membership)

    invites = (
        OrganizationInvitation.query
        .filter_by(organization_id=org.id)
        .order_by(OrganizationInvitation.created_at.desc())
        .limit(100)
        .all()
    )
    payload = []
    for invite in invites:
        row = invitation_payload(invite)
        inviter = User.query.get(invite.invited_by_user_id) if invite.invited_by_user_id else None
        row["invited_by_name"] = inviter.name if inviter else None
        row["is_expired"] = invitation_is_expired(invite)
        payload.append(row)

    return jsonify({
        "success": True,
        "invitations": payload,
    }), 200


@team_bp.route("/invitations", methods=["POST"])
@jwt_required()
def create_invitation():
    actor, org, membership, error = _auth_context()
    if error:
        return error
    if not can_manage_org(membership.role):
        return jsonify({"error": "Only org owners/admins can send invites"}), 403

    data = request.get_json() or {}
    email = str(data.get("email") or "").strip().lower()
    role = normalize_org_role(data.get("role"), default="collaborator")

    if not email or "@" not in email:
        return jsonify({"error": "Valid email is required"}), 400
    if role == ORG_ROLE_OWNER:
        return jsonify({"error": "Owner invites are not supported"}), 400
    if not role_has_capacity(org, role):
        return jsonify({"error": f"No available seats for role '{role}'"}), 409

    existing_user = User.query.filter(func.lower(User.email) == email).first()
    if existing_user:
        existing_member = active_membership_for_user(org.id, existing_user.id)
        if existing_member:
            return jsonify({"error": "User is already an active member"}), 409

    invite = (
        OrganizationInvitation.query
        .filter_by(organization_id=org.id, email=email, status="pending")
        .order_by(OrganizationInvitation.created_at.desc())
        .first()
    )
    if invite and invitation_is_expired(invite):
        invite.status = "expired"
        db.session.flush()
        invite = None

    if invite is None:
        invite = OrganizationInvitation(
            organization_id=org.id,
            email=email,
            role=role,
            token=secrets.token_urlsafe(24),
            status="pending",
            invited_by_user_id=actor.id,
            expires_at=new_invitation_expiry(14),
        )
        db.session.add(invite)
    else:
        invite.role = role
        invite.invited_by_user_id = actor.id
        invite.expires_at = new_invitation_expiry(14)
        invite.updated_at = datetime.utcnow()

    touch_member_activity(membership)
    row = invitation_payload(invite)
    row["accept_path"] = f"/team?invite={invite.token}"
    return jsonify({"success": True, "invitation": row}), 201


@team_bp.route("/invitations/<invitation_id>/revoke", methods=["POST"])
@jwt_required()
def revoke_invitation(invitation_id):
    _, org, membership, error = _auth_context()
    if error:
        return error
    if not can_manage_org(membership.role):
        return jsonify({"error": "Only org owners/admins can revoke invites"}), 403

    invite = OrganizationInvitation.query.filter_by(
        id=str(invitation_id),
        organization_id=org.id,
    ).first()
    if not invite:
        return jsonify({"error": "Invitation not found"}), 404
    if invite.status != "pending":
        return jsonify({"error": "Only pending invitations can be revoked"}), 400

    invite.status = "revoked"
    invite.updated_at = datetime.utcnow()
    touch_member_activity(membership)

    return jsonify({"success": True, "invitation": invitation_payload(invite)}), 200


@team_bp.route("/invitations/accept", methods=["POST"])
@jwt_required()
def accept_invitation():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json() or {}
    token = str(data.get("token") or "").strip()
    if not token:
        return jsonify({"error": "token is required"}), 400

    invite = OrganizationInvitation.query.filter_by(token=token, status="pending").first()
    if not invite:
        return jsonify({"error": "Invitation not found"}), 404
    if invitation_is_expired(invite):
        invite.status = "expired"
        db.session.commit()
        return jsonify({"error": "Invitation has expired"}), 410
    if str(user.email or "").strip().lower() != str(invite.email or "").strip().lower():
        return jsonify({"error": "Invitation email does not match signed-in user"}), 403

    org = Organization.query.get(invite.organization_id)
    if not org:
        return jsonify({"error": "Organization not found"}), 404

    next_role = normalize_org_role(invite.role, default="collaborator")
    existing = active_membership_for_user(org.id, user.id)
    if existing:
        if existing.role != next_role:
            if not role_has_capacity(org, next_role, exclude_member_id=existing.id):
                return jsonify({"error": f"No available seats for role '{next_role}'"}), 409
            existing.role = next_role
            existing.updated_at = datetime.utcnow()
        member = existing
    else:
        if not role_has_capacity(org, next_role):
            return jsonify({"error": f"No available seats for role '{next_role}'"}), 409
        member = OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role=next_role,
            status="active",
            invited_by_user_id=invite.invited_by_user_id,
            joined_at=datetime.utcnow(),
            last_active_at=datetime.utcnow(),
        )
        db.session.add(member)

    invite.status = "accepted"
    invite.accepted_at = datetime.utcnow()
    invite.accepted_by_user_id = user.id
    invite.updated_at = datetime.utcnow()

    if not user.active_organization_id:
        user.active_organization_id = org.id

    db.session.commit()

    return jsonify({
        "success": True,
        "organization": org_payload(org),
        "membership": _membership_payload(member),
        "seat_usage": build_seat_usage(org),
    }), 200


@team_bp.route("/projects", methods=["GET"])
@jwt_required()
def list_shared_projects():
    user, org, membership, error = _auth_context()
    if error:
        return error

    touch_member_activity(membership)

    candidates = (
        UserSession.query
        .filter(UserSession.organization_id == org.id)
        .order_by(UserSession.updated_at.desc(), UserSession.id.desc())
        .limit(500)
        .all()
    )
    projects = [_project_payload(row) for row in candidates if _can_access_project(row, user.id)]
    return jsonify({
        "success": True,
        "projects": projects,
    }), 200


@team_bp.route("/projects/<session_id>/sharing", methods=["PATCH"])
@jwt_required()
def update_project_sharing(session_id):
    user, org, membership, error = _auth_context()
    if error:
        return error

    row = _get_project_row(org.id, session_id)
    if not row:
        return jsonify({"error": "Project session not found"}), 404
    if not _can_access_project(row, user.id):
        return jsonify({"error": "Not authorized for this project"}), 403
    if not (can_manage_org(membership.role) or can_edit_projects(membership.role)):
        return jsonify({"error": "Role does not allow sharing updates"}), 403
    owner_id = str(row.created_by_user_id or row.user_id or "")
    if not can_manage_org(membership.role) and owner_id != str(user.id):
        return jsonify({"error": "Only project owner or org admin can update sharing"}), 403

    data = request.get_json() or {}
    next_visibility = str(data.get("visibility") or row.visibility or "private").strip().lower()
    if next_visibility not in PROJECT_VISIBILITY_VALUES:
        return jsonify({"error": "visibility must be one of private, team, specific"}), 400

    raw_shared = data.get("shared_with_user_ids")
    shared_ids = row.shared_with_user_ids if isinstance(row.shared_with_user_ids, list) else []
    if isinstance(raw_shared, list):
        valid_member_ids = {
            str(item.user_id)
            for item in OrganizationMember.query.filter_by(organization_id=org.id, status="active").all()
        }
        deduped = []
        seen = set()
        for candidate in raw_shared:
            uid = str(candidate or "").strip()
            if not uid or uid in seen or uid not in valid_member_ids:
                continue
            deduped.append(uid)
            seen.add(uid)
        shared_ids = deduped

    row.visibility = next_visibility
    row.shared_with_user_ids = shared_ids
    payload = row.payload if isinstance(row.payload, dict) else {}
    payload["visibility"] = next_visibility
    payload["shared_with_user_ids"] = shared_ids
    row.payload = payload
    _append_activity(
        row,
        user,
        "sharing_updated",
        {"visibility": next_visibility, "shared_with_user_ids": shared_ids},
    )

    db.session.commit()
    return jsonify({"success": True, "project": _project_payload(row)}), 200


@team_bp.route("/projects/<session_id>/activity", methods=["GET"])
@jwt_required()
def get_project_activity(session_id):
    user, org, membership, error = _auth_context()
    if error:
        return error
    row = _get_project_row(org.id, session_id)
    if not row:
        return jsonify({"error": "Project session not found"}), 404
    if not _can_access_project(row, user.id):
        return jsonify({"error": "Not authorized for this project"}), 403

    payload = row.payload if isinstance(row.payload, dict) else {}
    feed = payload.get("activity_feed") if isinstance(payload.get("activity_feed"), list) else []
    touch_member_activity(membership)
    return jsonify({"success": True, "activity_feed": feed}), 200


@team_bp.route("/projects/<session_id>/comments", methods=["GET"])
@jwt_required()
def get_project_comments(session_id):
    user, org, membership, error = _auth_context()
    if error:
        return error
    row = _get_project_row(org.id, session_id)
    if not row:
        return jsonify({"error": "Project session not found"}), 404
    if not _can_access_project(row, user.id):
        return jsonify({"error": "Not authorized for this project"}), 403

    payload = row.payload if isinstance(row.payload, dict) else {}
    comments = payload.get("comments") if isinstance(payload.get("comments"), list) else []
    touch_member_activity(membership)
    return jsonify({"success": True, "comments": comments}), 200


@team_bp.route("/projects/<session_id>/comments", methods=["POST"])
@jwt_required()
def add_project_comment(session_id):
    user, org, membership, error = _auth_context()
    if error:
        return error
    row = _get_project_row(org.id, session_id)
    if not row:
        return jsonify({"error": "Project session not found"}), 404
    if not _can_access_project(row, user.id):
        return jsonify({"error": "Not authorized for this project"}), 403

    data = request.get_json() or {}
    body = str(data.get("body") or "").strip()
    if not body:
        return jsonify({"error": "body is required"}), 400
    if len(body) > 3000:
        return jsonify({"error": "Comment is too long"}), 400

    payload = row.payload if isinstance(row.payload, dict) else {}
    comments = payload.get("comments")
    if not isinstance(comments, list):
        comments = []
    comment = {
        "id": f"cmt_{secrets.token_hex(6)}",
        "timestamp": _now_iso(),
        "author_user_id": user.id,
        "author_name": user.name,
        "body": body,
    }
    comments.insert(0, comment)
    payload["comments"] = comments[:500]
    row.payload = payload
    _append_activity(
        row,
        user,
        "comment_added",
        {"comment_id": comment["id"]},
    )

    db.session.commit()
    return jsonify({"success": True, "comment": comment}), 201
