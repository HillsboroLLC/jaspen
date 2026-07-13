from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app import db, limiter
from app.decision_profile_service import (
    create_user_decision_profile,
    get_current_profile_for_user,
    serialize_decision_profile,
)
from app.models import User


decision_profile_bp = Blueprint("decision_profile", __name__)


def _current_user():
    user_id = get_jwt_identity()
    if not user_id:
        return None
    return db.session.get(User, str(user_id))


@decision_profile_bp.route("", methods=["GET"])
@decision_profile_bp.route("/", methods=["GET"])
@jwt_required()
def get_decision_profile():
    user = _current_user()
    if user is None:
        return jsonify({"error": "Unauthorized"}), 401
    profile = get_current_profile_for_user(user)
    if profile is not None:
        db.session.commit()
    return jsonify(serialize_decision_profile(profile)), 200


@decision_profile_bp.route("", methods=["POST"])
@decision_profile_bp.route("/", methods=["POST"])
@jwt_required()
@limiter.limit("12 per hour")
def save_decision_profile():
    user = _current_user()
    if user is None:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    answers = data.get("assessment_answers") or data.get("answers")
    try:
        profile = create_user_decision_profile(user, answers)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"error": "Invalid assessment answers.", "code": str(exc)}), 400
    except Exception:
        db.session.rollback()
        raise
    return jsonify(serialize_decision_profile(profile)), 201
