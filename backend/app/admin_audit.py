import json
import os
from datetime import datetime


AUDIT_DIR = "admin_audit_data"
AUDIT_FILE = os.path.join(AUDIT_DIR, "events.jsonl")


def _iso_now():
    return datetime.utcnow().isoformat()


def _ensure_dir():
    if not os.path.exists(AUDIT_DIR):
        os.makedirs(AUDIT_DIR)


def _normalize_limit(value, default=50, minimum=1, maximum=200):
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


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
    _ensure_dir()
    payload = {
        "timestamp": _iso_now(),
        "actor_user_id": str(actor_user_id or "").strip() or None,
        "actor_email": str(actor_email or "").strip().lower() or None,
        "action": str(action or "").strip() or "unknown",
        "target_user_id": str(target_user_id or "").strip() or None,
        "target_email": str(target_email or "").strip().lower() or None,
        "details": details if isinstance(details, dict) else {},
        "remote_addr": str(remote_addr or "").strip() or None,
        "user_agent": str(user_agent or "").strip() or None,
    }
    with open(AUDIT_FILE, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")


def list_admin_audit_events(*, user_id=None, limit=50):
    _ensure_dir()
    if not os.path.exists(AUDIT_FILE):
        return []

    target_user_id = str(user_id or "").strip() or None
    max_items = _normalize_limit(limit)
    collected = []

    with open(AUDIT_FILE, "r", encoding="utf-8") as handle:
        lines = handle.readlines()

    for raw in reversed(lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            event = json.loads(raw)
        except Exception:
            continue
        if not isinstance(event, dict):
            continue
        if target_user_id:
            event_target = str(event.get("target_user_id") or "").strip()
            if event_target != target_user_id:
                continue
        collected.append(event)
        if len(collected) >= max_items:
            break

    return collected
