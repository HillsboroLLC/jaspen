"""Authenticated API for emailing a user's existing decision artifacts."""

import re
from datetime import datetime, timedelta

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy.exc import IntegrityError

from app import db, limiter
from app.decision_asset_email_service import (
    DeliveryError,
    SUPPORTED_OUTPUT_TYPES,
    delivery_json,
    load_authorized_context,
    mask_email,
    record_telemetry,
    start_delivery,
)
from app.evaluation_telemetry import evaluation_id_for_scorecard
from app.models import DecisionAssetEmail, User


decision_asset_email_bp = Blueprint("decision_asset_email", __name__)
_IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


def _current_verified_user():
    user = User.query.filter_by(id=str(get_jwt_identity())).first()
    if not user:
        return None, (jsonify({"error": "User not found", "code": "user_not_found"}), 404)
    if not bool(user.email_verified) or not str(user.email or "").strip():
        return None, (
            jsonify({
                "error": "Verify your account email before emailing results.",
                "code": "verified_email_required",
            }),
            403,
        )
    return user, None


@decision_asset_email_bp.route("/recipient", methods=["GET"])
@jwt_required()
def email_asset_recipient():
    user, error = _current_verified_user()
    if error:
        return error
    return jsonify({"recipient_masked": mask_email(user.email)})


@decision_asset_email_bp.route("/<delivery_id>", methods=["GET"])
@jwt_required()
def email_asset_status(delivery_id):
    user, error = _current_verified_user()
    if error:
        return error
    delivery = DecisionAssetEmail.query.filter_by(id=delivery_id, user_id=user.id).first()
    if not delivery:
        return jsonify({"error": "Email request not found", "code": "delivery_not_found"}), 404
    return jsonify(delivery_json(delivery))


@decision_asset_email_bp.route("/threads/<thread_id>", methods=["POST"])
@jwt_required()
@limiter.limit("5 per hour")
def request_email_assets(thread_id):
    user, error = _current_verified_user()
    if error:
        return error

    body = request.get_json(silent=True) or {}
    idempotency_key = str(body.get("idempotency_key") or "").strip()
    if not _IDEMPOTENCY_PATTERN.fullmatch(idempotency_key):
        return jsonify({
            "error": "A valid idempotency key is required.",
            "code": "invalid_idempotency_key",
        }), 400

    requested_types = body.get("output_types")
    if not isinstance(requested_types, list):
        return jsonify({"error": "output_types must be a list.", "code": "invalid_output_types"}), 400
    output_types = sorted({str(item).strip() for item in requested_types if str(item).strip()})
    if not output_types or not set(output_types).issubset(SUPPORTED_OUTPUT_TYPES):
        return jsonify({
            "error": "One or more requested output types are unsupported.",
            "code": "unsupported_output_type",
            "supported_output_types": sorted(SUPPORTED_OUTPUT_TYPES),
        }), 400

    existing = DecisionAssetEmail.query.filter_by(
        user_id=user.id,
        idempotency_key=idempotency_key,
    ).first()
    if existing:
        requested_scorecard_id = str(body.get("scorecard_id") or "").strip() or None
        if (
            existing.thread_id != thread_id
            or sorted(existing.output_types or []) != output_types
            or (requested_scorecard_id and existing.scorecard_id != requested_scorecard_id)
        ):
            return jsonify({
                "error": "That idempotency key was already used for a different request.",
                "code": "idempotency_conflict",
            }), 409
        if existing.status == "failed":
            existing.status = "preparing"
            existing.error_category = None
            existing.provider_response = None
            existing.sent_at = None
            record_telemetry(existing, "email_assets_requested")
            db.session.commit()
            start_delivery(existing.id)
            return jsonify(delivery_json(existing)), 202
        return jsonify(delivery_json(existing)), 200 if existing.status == "sent" else 202

    scorecard_id = str(body.get("scorecard_id") or "").strip() or None
    try:
        context = load_authorized_context(user, thread_id, scorecard_id)
    except DeliveryError as exc:
        status = 403 if exc.category == "workspace_access_denied" else 404
        return jsonify({
            "error": "You do not have access to the requested decision output.",
            "code": exc.category,
        }), status

    hourly_limit = max(1, int(current_app.config.get("DECISION_ASSET_EMAIL_RATE_LIMIT_PER_HOUR") or 5))
    cutoff = datetime.utcnow() - timedelta(hours=1)
    recent_count = DecisionAssetEmail.query.filter(
        DecisionAssetEmail.user_id == user.id,
        DecisionAssetEmail.created_at >= cutoff,
    ).count()
    if recent_count >= hourly_limit:
        return jsonify({
            "error": "Too many email requests. Please try again later.",
            "code": "email_assets_rate_limited",
            "retry_after_seconds": 3600,
        }), 429

    effective_scorecard_id = context.get("scorecard_id")
    delivery = DecisionAssetEmail(
        user_id=user.id,
        organization_id=context.get("organization_id"),
        thread_id=thread_id,
        evaluation_id=evaluation_id_for_scorecard(user.id, effective_scorecard_id),
        scorecard_id=effective_scorecard_id,
        recipient_email=user.email,
        idempotency_key=idempotency_key,
        output_types=output_types,
        status="preparing",
    )
    try:
        db.session.add(delivery)
        db.session.flush()
        record_telemetry(delivery, "email_assets_requested")
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = DecisionAssetEmail.query.filter_by(
            user_id=user.id,
            idempotency_key=idempotency_key,
        ).first()
        if existing:
            return jsonify(delivery_json(existing)), 200 if existing.status == "sent" else 202
        raise
    start_delivery(delivery.id)
    return jsonify(delivery_json(delivery)), 202
