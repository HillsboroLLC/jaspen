from datetime import datetime

from app import db
from app.models import UserSession


def _base_session_payload(user_id, session_id):
    now = datetime.utcnow().isoformat()
    return {
        "session_id": str(session_id),
        "name": "Jaspen Intake",
        "document_type": "strategy",
        "status": "in_progress",
        "current_phase": 1,
        "chat_history": [],
        "notes": {},
        "created": now,
        "timestamp": now,
        "user_id": str(user_id),
        "visibility": "private",
        "shared_with_user_ids": [],
    }


def load_scenarios_data(user_id):
    rows = UserSession.query.filter_by(user_id=str(user_id)).all()
    out = {}
    for row in rows:
        payload = row.scenarios_json if isinstance(row.scenarios_json, dict) else None
        if payload:
            db_sid = str(row.session_id)
            out[db_sid] = payload
            # Also alias by the payload's session_id if the session payload uses a different UUID
            # (e.g. DB key = 'thread_1755649fe585', payload.session_id = '378d472a-...')
            row_payload = row.payload if isinstance(row.payload, dict) else {}
            payload_sid = str(row_payload.get('session_id') or '').strip()
            if payload_sid and payload_sid != db_sid:
                out[payload_sid] = payload
    return out


def save_scenarios_data(user_id, data):
    payloads = data if isinstance(data, dict) else {}
    try:
        existing = {
            row.session_id: row
            for row in UserSession.query.filter_by(user_id=str(user_id)).all()
        }
        incoming = set()
        for thread_id, thread_payload in payloads.items():
            sid = str(thread_id or "").strip()
            if not sid or not isinstance(thread_payload, dict):
                continue
            incoming.add(sid)
            row = existing.get(sid)
            if row is None:
                row = UserSession(
                    user_id=str(user_id),
                    session_id=sid,
                    name="Jaspen Intake",
                    document_type="strategy",
                    status="in_progress",
                    payload=_base_session_payload(user_id, sid),
                )
                db.session.add(row)
                existing[sid] = row
            row.scenarios_json = thread_payload

        for sid, row in existing.items():
            if sid not in incoming and isinstance(row.scenarios_json, dict) and row.scenarios_json:
                row.scenarios_json = {}

        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        print(f"[scenarios_store] save error for {user_id}: {e}")
        return False
