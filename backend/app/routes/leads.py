import hashlib
import re

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.exceptions import BadRequest, UnsupportedMediaType

from app import db, limiter
from app.models import Lead


leads_bp = Blueprint("leads", __name__)

MAX_LEAD_PAYLOAD_BYTES = 8 * 1024
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
HONEYPOT_FIELDS = ("website", "url", "hp_name")
FIELD_LIMITS = {
    "email": 255,
    "source": 80,
    "first_name": 120,
    "last_name": 120,
    "company": 160,
    "title": 160,
    "utm_source": 120,
    "utm_medium": 120,
    "utm_campaign": 160,
    "referrer": 512,
}
OPTIONAL_TEXT_FIELDS = (
    "first_name",
    "last_name",
    "company",
    "title",
    "utm_source",
    "utm_medium",
    "utm_campaign",
)


def _lead_fingerprint(email):
    return hashlib.sha256(email.encode("utf-8")).hexdigest()[:12]


def _bad_request(code, message):
    current_app.logger.info("Lead capture validation failed: %s", code)
    return jsonify({"error": message, "code": code}), 400


def _normalized_text(data, field, *, required=False):
    value = data.get(field)
    if value is None:
        if required:
            raise ValueError(f"{field}_required")
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field}_invalid_type")

    value = value.strip()
    if not value:
        if required:
            raise ValueError(f"{field}_required")
        return None
    if len(value) > FIELD_LIMITS[field]:
        raise OverflowError(f"{field}_too_long")
    return value


def _parse_payload():
    if request.content_length is not None and request.content_length > MAX_LEAD_PAYLOAD_BYTES:
        return None, _bad_request("payload_too_large", "Payload is too large.")

    if not request.is_json:
        return None, _bad_request("invalid_json", "Request body must be a JSON object.")

    try:
        data = request.get_json(silent=False)
    except (BadRequest, UnsupportedMediaType):
        return None, _bad_request("invalid_json", "Request body must be valid JSON.")

    if not isinstance(data, dict):
        return None, _bad_request("invalid_payload", "Request body must be a JSON object.")

    for field in HONEYPOT_FIELDS:
        value = data.get(field)
        if isinstance(value, str) and value.strip():
            return None, _bad_request("invalid_payload", "Invalid lead submission.")

    try:
        email = _normalized_text(data, "email", required=True).lower()
        source = _normalized_text(data, "source") or "unknown"
        optional = {field: _normalized_text(data, field) for field in OPTIONAL_TEXT_FIELDS}
    except ValueError as exc:
        return None, _bad_request(str(exc), "Email is required.")
    except TypeError as exc:
        return None, _bad_request(str(exc), "Lead fields must be strings.")
    except OverflowError as exc:
        return None, _bad_request(str(exc), "Lead field is too long.")

    if not EMAIL_RE.match(email):
        return None, _bad_request("invalid_email", "Email must be valid.")

    referrer = request.referrer
    if referrer:
        referrer = referrer.strip()[:FIELD_LIMITS["referrer"]]
    elif isinstance(data.get("referrer"), str):
        referrer = data["referrer"].strip() or None
        if referrer and len(referrer) > FIELD_LIMITS["referrer"]:
            return None, _bad_request("referrer_too_long", "Lead field is too long.")

    payload = {
        "email": email,
        "source": source,
        "referrer": referrer,
        **optional,
    }
    return payload, None


def _apply_non_empty_metadata(lead, payload):
    changed = False
    for field in (*OPTIONAL_TEXT_FIELDS, "referrer"):
        value = payload.get(field)
        if value and getattr(lead, field) != value:
            setattr(lead, field, value)
            changed = True
    return changed


def _commit_existing_lead(payload):
    lead = Lead.query.filter_by(email=payload["email"], source=payload["source"]).one_or_none()
    if lead is None:
        return None
    _apply_non_empty_metadata(lead, payload)
    db.session.commit()
    current_app.logger.info(
        "Lead capture duplicate handled",
        extra={"lead_source": lead.source, "lead_fingerprint": _lead_fingerprint(lead.email)},
    )
    return lead


@leads_bp.route("/leads", methods=["POST"])
@limiter.limit("5 per minute")
@limiter.limit("30 per hour")
def capture_lead():
    payload, error_response = _parse_payload()
    if error_response is not None:
        return error_response

    try:
        existing = _commit_existing_lead(payload)
        if existing is not None:
            return jsonify({"ok": True}), 200

        lead = Lead(**payload)
        db.session.add(lead)
        db.session.commit()
        current_app.logger.info(
            "Lead captured",
            extra={"lead_source": lead.source, "lead_fingerprint": _lead_fingerprint(lead.email)},
        )
        return jsonify({"ok": True}), 201
    except IntegrityError:
        db.session.rollback()
        try:
            existing = _commit_existing_lead(payload)
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception("Lead capture duplicate recovery failed")
            return jsonify({"error": "Internal server error"}), 500
        if existing is not None:
            return jsonify({"ok": True}), 200
        current_app.logger.exception("Lead capture uniqueness conflict could not be recovered")
        return jsonify({"error": "Internal server error"}), 500
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Lead capture database error")
        return jsonify({"error": "Internal server error"}), 500
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Lead capture unexpected error")
        return jsonify({"error": "Internal server error"}), 500
