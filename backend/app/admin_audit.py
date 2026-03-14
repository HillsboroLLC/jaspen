import os
import json
from datetime import datetime, timezone

from flask import has_request_context, request

from app import db
from app.models import AdminAuditEvent

AUDIT_DIR = "admin_audit_data"
AUDIT_FILE = os.path.join(AUDIT_DIR, "events.jsonl")


def _ensure_dir():
    if not os.path.exists(AUDIT_DIR):
        os.makedirs(AUDIT_DIR)


def _normalize_limit(value, default=50, minimum=1, maximum=200):
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _parse_timestamp(value):
    text = str(value or "").strip()
    if not text:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _backfill_legacy_events():
    _ensure_dir()
    if not os.path.exists(AUDIT_FILE):
        return
    if AdminAuditEvent.query.limit(1).first() is not None:
        return

    with open(AUDIT_FILE, "r", encoding="utf-8") as handle:
        lines = handle.readlines()

    imported = 0
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        db.session.add(AdminAuditEvent(
            timestamp=_parse_timestamp(payload.get("timestamp")),
            actor_user_id=str(payload.get("actor_user_id") or "").strip() or None,
            actor_email=str(payload.get("actor_email") or "").strip().lower() or None,
            action=str(payload.get("action") or "").strip() or "unknown",
            target_user_id=str(payload.get("target_user_id") or "").strip() or None,
            target_email=str(payload.get("target_email") or "").strip().lower() or None,
            details=payload.get("details") if isinstance(payload.get("details"), dict) else {},
            remote_addr=str(payload.get("remote_addr") or "").strip() or None,
            user_agent=str(payload.get("user_agent") or "").strip() or None,
        ))
        imported += 1

    if imported:
        db.session.commit()


def append_admin_audit_event(
    *,
    actor_user_id=None,
    actor_email=None,
    action="",
    target_user_id=None,
    target_email=None,
    details=None,
    remote_addr=None,
    user_agent=None,
):
    _backfill_legacy_events()
    event = AdminAuditEvent(
        timestamp=datetime.now(timezone.utc),
        actor_user_id=str(actor_user_id or "").strip() or None,
        actor_email=str(actor_email or "").strip().lower() or None,
        action=str(action or "").strip() or "unknown",
        target_user_id=str(target_user_id or "").strip() or None,
        target_email=str(target_email or "").strip().lower() or None,
        details=details if isinstance(details, dict) else {},
        remote_addr=str(
            (request.remote_addr if has_request_context() else None)
            or remote_addr
            or ""
        ).strip() or None,
        user_agent=str(
            (request.user_agent if has_request_context() else None)
            or user_agent
            or ""
        ).strip() or None,
    )
    db.session.add(event)
    db.session.commit()
    return event


def list_admin_audit_events(*, user_id=None, limit=50):
    _backfill_legacy_events()
    target_user_id = str(user_id or "").strip() or None
    max_items = _normalize_limit(limit)

    query = AdminAuditEvent.query.order_by(AdminAuditEvent.timestamp.desc())
    if target_user_id:
        query = query.filter_by(target_user_id=target_user_id)

    return [event.to_dict() for event in query.limit(max_items).all()]
