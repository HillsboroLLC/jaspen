from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import or_

from app import db
from app.admin_policy import is_global_admin_email
from app.billing_config import apply_plan_to_user, get_plan_catalog, normalize_plan_key, to_public_plan
from app.models import User


admin_bp = Blueprint("admin", __name__)


def _to_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _serialize_user(user):
    if not user:
        return None
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "subscription_plan": to_public_plan(user.subscription_plan),
        "credits_remaining": user.credits_remaining,
        "seat_limit": user.seat_limit,
        "max_seats": user.max_seats,
        "unlimited_analysis": bool(user.unlimited_analysis),
        "max_concurrent_sessions": user.max_concurrent_sessions,
        "stripe_customer_id": user.stripe_customer_id,
        "stripe_subscription_id": user.stripe_subscription_id,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
    }


def _current_user():
    user = User.query.get(get_jwt_identity())
    if not user:
        return None, (jsonify({"error": "User not found"}), 404)
    return user, None


def _require_admin():
    user, err = _current_user()
    if err:
        return None, err
    if not is_global_admin_email(user.email, current_app.config):
        return None, (jsonify({"error": "Admin access required"}), 403)
    return user, None


@admin_bp.route("/capabilities", methods=["GET"])
@jwt_required()
def capabilities():
    user, err = _current_user()
    if err:
        return err
    return jsonify({
        "is_admin": is_global_admin_email(user.email, current_app.config),
        "email": user.email,
        "admin_scope": "global",
        "org_admin_enabled": False,
    }), 200


@admin_bp.route("/users", methods=["GET"])
@jwt_required()
def list_users():
    _, err = _require_admin()
    if err:
        return err

    query = str(request.args.get("q") or "").strip()
    limit = request.args.get("limit", 50)
    try:
        limit = int(limit)
    except Exception:
        limit = 50
    limit = max(1, min(200, limit))

    q = User.query
    if query:
        like = f"%{query}%"
        q = q.filter(or_(User.email.ilike(like), User.name.ilike(like)))

    users = q.order_by(User.updated_at.desc()).limit(limit).all()
    return jsonify({
        "users": [_serialize_user(user) for user in users],
        "count": len(users),
    }), 200


@admin_bp.route("/users/<user_id>", methods=["GET"])
@jwt_required()
def get_user(user_id):
    _, err = _require_admin()
    if err:
        return err

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    return jsonify({"user": _serialize_user(user)}), 200


@admin_bp.route("/users/<user_id>", methods=["PATCH"])
@jwt_required()
def patch_user(user_id):
    _, err = _require_admin()
    if err:
        return err

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json(silent=True) or {}
    plan_catalog = get_plan_catalog(current_app.config)
    allowed_plans = set(plan_catalog.keys())

    if "name" in data:
        name = str(data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name cannot be empty"}), 400
        if len(name) > 255:
            return jsonify({"error": "name is too long"}), 400
        user.name = name

    if "subscription_plan" in data:
        desired_plan = normalize_plan_key(data.get("subscription_plan"))
        if desired_plan not in allowed_plans:
            return jsonify({"error": f"subscription_plan must be one of {sorted(allowed_plans)}"}), 400
        user.subscription_plan = desired_plan

    if "credits_remaining" in data:
        value = data.get("credits_remaining")
        if value in (None, "", "null"):
            user.credits_remaining = None
        else:
            try:
                credits = int(value)
            except Exception:
                return jsonify({"error": "credits_remaining must be an integer or null"}), 400
            if credits < 0:
                return jsonify({"error": "credits_remaining cannot be negative"}), 400
            user.credits_remaining = credits

    if "seat_limit" in data:
        try:
            seat_limit = int(data.get("seat_limit"))
        except Exception:
            return jsonify({"error": "seat_limit must be an integer"}), 400
        if seat_limit < 0:
            return jsonify({"error": "seat_limit cannot be negative"}), 400
        user.seat_limit = seat_limit

    if "max_seats" in data:
        try:
            max_seats = int(data.get("max_seats"))
        except Exception:
            return jsonify({"error": "max_seats must be an integer"}), 400
        if max_seats < 0:
            return jsonify({"error": "max_seats cannot be negative"}), 400
        user.max_seats = max_seats

    if "unlimited_analysis" in data:
        user.unlimited_analysis = _to_bool(data.get("unlimited_analysis"), default=False)

    if "max_concurrent_sessions" in data:
        value = data.get("max_concurrent_sessions")
        if value in (None, "", "null"):
            user.max_concurrent_sessions = None
        else:
            try:
                sessions = int(value)
            except Exception:
                return jsonify({"error": "max_concurrent_sessions must be an integer or null"}), 400
            if sessions < 1:
                return jsonify({"error": "max_concurrent_sessions must be at least 1 when set"}), 400
            user.max_concurrent_sessions = sessions

    if "stripe_customer_id" in data:
        user.stripe_customer_id = str(data.get("stripe_customer_id") or "").strip() or None
    if "stripe_subscription_id" in data:
        user.stripe_subscription_id = str(data.get("stripe_subscription_id") or "").strip() or None

    db.session.commit()
    return jsonify({"success": True, "user": _serialize_user(user)}), 200


@admin_bp.route("/users/<user_id>/force-plan", methods=["POST"])
@jwt_required()
def force_plan(user_id):
    _, err = _require_admin()
    if err:
        return err

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json(silent=True) or {}
    desired_plan = normalize_plan_key(data.get("plan_key") or "essential")
    plan_catalog = get_plan_catalog(current_app.config)
    if desired_plan not in plan_catalog:
        return jsonify({"error": f"plan_key must be one of {sorted(plan_catalog.keys())}"}), 400

    reset_credits = _to_bool(data.get("reset_credits"), default=True)
    apply_plan_to_user(user, desired_plan, current_app.config, reset_credits=reset_credits)
    db.session.commit()
    return jsonify({"success": True, "user": _serialize_user(user)}), 200
