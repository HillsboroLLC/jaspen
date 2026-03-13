import uuid

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import or_

from app import db
from app.models import SavedStarter, User
from app.orgs import resolve_active_org_for_user

from .sessions import load_user_sessions

starters_bp = Blueprint("starters", __name__)

OBJECTIVE_ALIASES = {
    "balanced": "balanced",
    "default": "balanced",
    "general": "balanced",
    "cost": "cost",
    "cost optimization": "cost",
    "cost-optimization": "cost",
    "efficiency": "cost",
    "profitability": "cost",
    "speed": "speed",
    "speed to market": "speed",
    "speed-to-market": "speed",
    "timeline": "speed",
    "delivery": "speed",
    "growth": "growth",
    "revenue": "growth",
    "expansion": "growth",
}


def _normalize_objective(value, default="balanced"):
    text = str(value or "").strip().lower()
    if not text:
        return default
    if text in OBJECTIVE_ALIASES:
        return OBJECTIVE_ALIASES[text]
    compact = text.replace("_", " ").replace("-", " ")
    return OBJECTIVE_ALIASES.get(compact, default)


def _clean_json_dict(value):
    return value if isinstance(value, dict) else {}


def _resolve_thread_session(sessions, thread_id):
    tid = str(thread_id or "").strip()
    if not tid or not isinstance(sessions, dict):
        return None
    if tid in sessions and isinstance(sessions.get(tid), dict):
        return sessions.get(tid)
    for candidate in sessions.values():
        if str((candidate or {}).get("session_id", "")).strip() == tid and isinstance(candidate, dict):
            return candidate
    return None


def _extract_lever_defaults(session):
    baseline_inputs = session.get("baseline_inputs")
    if isinstance(baseline_inputs, dict) and baseline_inputs:
        return baseline_inputs

    result = session.get("result")
    if isinstance(result, dict):
        inputs = result.get("inputs")
        if isinstance(inputs, dict) and inputs:
            return inputs

        compat = result.get("compat")
        if isinstance(compat, dict):
            numeric_compat = {}
            for key, value in compat.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    numeric_compat[key] = value
            if numeric_compat:
                return numeric_compat

    return {}


def _extract_scoring_weights(session):
    result = session.get("result")
    if isinstance(result, dict):
        if isinstance(result.get("scoring_weights"), dict):
            return result.get("scoring_weights")
        meta = result.get("meta")
        if isinstance(meta, dict) and isinstance(meta.get("scoring_weights"), dict):
            return meta.get("scoring_weights")
    return {}


def _extract_intake_context(session):
    context = session.get("intake_context")
    if isinstance(context, dict):
        return context
    objective = _normalize_objective(session.get("strategy_objective"))
    return {"objective": objective}


@starters_bp.route("", methods=["POST"])
@jwt_required()
def create_starter():
    user_id = str(get_jwt_identity() or "").strip()
    user = User.query.get(user_id) if user_id else None
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json() or {}
    thread_id = str(data.get("thread_id") or "").strip()
    name = str(data.get("name") or "").strip()
    description = str(data.get("description") or "").strip()

    if not thread_id:
        return jsonify({"error": "thread_id is required"}), 400
    if not name:
        return jsonify({"error": "name is required"}), 400

    sessions = load_user_sessions(user_id) or {}
    session = _resolve_thread_session(sessions, thread_id)
    if not isinstance(session, dict):
        return jsonify({"error": "Thread not found"}), 404

    active_org, _ = resolve_active_org_for_user(user)
    active_org_id = active_org.id if active_org else user.active_organization_id

    objective = _normalize_objective(
        data.get("objective")
        or session.get("strategy_objective")
        or (session.get("intake_context") or {}).get("objective")
    )
    intake_context = _extract_intake_context(session)
    intake_context["objective"] = objective

    lever_defaults = _clean_json_dict(data.get("lever_defaults")) or _extract_lever_defaults(session)
    scoring_weights = _clean_json_dict(data.get("scoring_weights")) or _extract_scoring_weights(session)

    starter = SavedStarter(
        id=str(uuid.uuid4()),
        user_id=user_id,
        organization_id=active_org_id,
        name=name[:255],
        description=description or None,
        objective=objective,
        lever_defaults=lever_defaults if isinstance(lever_defaults, dict) else {},
        scoring_weights=scoring_weights if isinstance(scoring_weights, dict) else {},
        intake_context=intake_context if isinstance(intake_context, dict) else {"objective": objective},
        is_shared=bool(data.get("is_shared")),
        source_thread_id=thread_id,
    )
    db.session.add(starter)
    db.session.commit()

    return jsonify({"starter": starter.to_dict()}), 201


@starters_bp.route("", methods=["GET"])
@jwt_required()
def list_starters():
    user_id = str(get_jwt_identity() or "").strip()
    user = User.query.get(user_id) if user_id else None
    if not user:
        return jsonify({"error": "User not found"}), 404

    active_org, _ = resolve_active_org_for_user(user)
    active_org_id = active_org.id if active_org else user.active_organization_id

    conditions = [SavedStarter.user_id == user_id]
    if active_org_id:
        conditions.append(
            (SavedStarter.organization_id == str(active_org_id))
            & (SavedStarter.is_shared.is_(True))
        )

    query = SavedStarter.query.filter(or_(*conditions))

    starters = query.order_by(SavedStarter.created_at.desc()).all()
    return jsonify({"starters": [item.to_dict() for item in starters]}), 200


@starters_bp.route("/<starter_id>", methods=["PATCH"])
@jwt_required()
def update_starter(starter_id):
    user_id = str(get_jwt_identity() or "").strip()
    starter = SavedStarter.query.filter_by(id=str(starter_id)).first()
    if not starter:
        return jsonify({"error": "Starter not found"}), 404
    if str(starter.user_id) != user_id:
        return jsonify({"error": "Only the starter owner can edit this starter"}), 403

    data = request.get_json() or {}
    if "name" in data:
        name = str(data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name cannot be empty"}), 400
        starter.name = name[:255]

    if "description" in data:
        description = str(data.get("description") or "").strip()
        starter.description = description or None

    if "is_shared" in data:
        starter.is_shared = bool(data.get("is_shared"))
        if starter.is_shared and not starter.organization_id:
            user = User.query.get(user_id)
            if user:
                active_org, _ = resolve_active_org_for_user(user)
                starter.organization_id = active_org.id if active_org else user.active_organization_id

    db.session.commit()
    return jsonify({"starter": starter.to_dict()}), 200


@starters_bp.route("/<starter_id>", methods=["DELETE"])
@jwt_required()
def delete_starter(starter_id):
    user_id = str(get_jwt_identity() or "").strip()
    starter = SavedStarter.query.filter_by(id=str(starter_id)).first()
    if not starter:
        return jsonify({"error": "Starter not found"}), 404
    if str(starter.user_id) != user_id:
        return jsonify({"error": "Only the starter owner can delete this starter"}), 403

    db.session.delete(starter)
    db.session.commit()
    return jsonify({"success": True}), 200
