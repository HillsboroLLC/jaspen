"""Public business utilities (tools) — authenticated persistence.

Backs the public calculators' optional "Save this estimate"
flow. The utility itself is fully usable anonymously; this endpoint only stores
an estimate for a signed-in user and associates it with their existing account.

The table (`saved_utility_estimates`) is created by its Alembic migration. If the
migration has not been applied yet, the endpoints degrade to HTTP 503 rather
than 500 — and the frontend already falls back to a local save — so deploying
this code before running the migration cannot break the app.
"""

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.exc import ProgrammingError, OperationalError

from app import db
from app.models import SavedUtilityEstimate, User

tools_bp = Blueprint("tools", __name__)

ALLOWED_UTILITY_TYPES = {"cost_of_turnover", "mortgage", "rent"}
MAX_PAYLOAD_BYTES = 64 * 1024


def _current_user():
    return User.query.get(get_jwt_identity())


def _clean_int(value):
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


@tools_bp.route("/estimates", methods=["POST"])
@jwt_required()
def create_estimate():
    if request.content_length and request.content_length > MAX_PAYLOAD_BYTES:
        return jsonify({"error": "Payload too large."}), 413
    if not request.is_json:
        return jsonify({"error": "Request body must be JSON."}), 400

    user = _current_user()
    if user is None:
        return jsonify({"error": "User not found."}), 404

    data = request.get_json(silent=True) or {}
    utility_type = str(data.get("utility_type") or "cost_of_turnover")
    if utility_type not in ALLOWED_UTILITY_TYPES:
        return jsonify({"error": "Unknown utility type."}), 400

    estimate = SavedUtilityEstimate(
        user_id=user.id,
        utility_type=utility_type,
        source=str(data.get("source") or "")[:80] or None,
        calculator_version=str(data.get("calculator_version") or "")[:32] or None,
        benchmark_version=str(data.get("benchmark_version") or "")[:32] or None,
        user_inputs=data.get("user_inputs") or {},
        defaults_used=data.get("defaults_used") or {},
        result_breakdown=data.get("result_breakdown") or [],
        built_using=data.get("built_using") or {},
        total_low=_clean_int(data.get("total_low")),
        total_mid=_clean_int(data.get("total_mid")),
        total_high=_clean_int(data.get("total_high")),
    )
    try:
        db.session.add(estimate)
        db.session.commit()
    except (ProgrammingError, OperationalError):
        db.session.rollback()
        current_app.logger.warning("saved_utility_estimates table missing; migration not applied")
        return jsonify({"error": "Estimate storage is not available yet."}), 503
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to save utility estimate")
        return jsonify({"error": "Internal server error"}), 500

    return jsonify({"ok": True, "id": estimate.id}), 201


@tools_bp.route("/estimates", methods=["GET"])
@jwt_required()
def list_estimates():
    user = _current_user()
    if user is None:
        return jsonify({"error": "User not found."}), 404
    utility_type = request.args.get("utility_type")
    try:
        query = SavedUtilityEstimate.query.filter_by(user_id=user.id)
        if utility_type:
            query = query.filter_by(utility_type=utility_type)
        rows = query.order_by(SavedUtilityEstimate.created_at.desc()).limit(50).all()
    except (ProgrammingError, OperationalError):
        db.session.rollback()
        return jsonify({"estimates": []}), 200
    return jsonify({"estimates": [r.to_dict() for r in rows]}), 200
