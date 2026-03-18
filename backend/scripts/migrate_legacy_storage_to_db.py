import json
from pathlib import Path

from app import create_app, db
from app.models import UserSession
from app.routes.sessions import _normalize_session_payload, _upsert_session_row


ROOT = Path(__file__).resolve().parents[1]
SESSIONS_DIR = ROOT / "sessions_data"
SCENARIOS_DIR = ROOT / "scenarios_data"


def _load_json(path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def migrate_sessions():
    migrated = 0
    for path in SESSIONS_DIR.glob("user_*_sessions.json"):
        user_id = path.name.replace("user_", "").replace("_sessions.json", "")
        payload = _load_json(path)
        if not isinstance(payload, dict):
            continue
        existing = {
            row.session_id: row
            for row in UserSession.query.filter_by(user_id=str(user_id)).all()
        }
        for key, session_payload in payload.items():
            if not isinstance(session_payload, dict):
                continue
            sid = str(session_payload.get("session_id") or key or "").strip()
            if not sid:
                continue
            normalized = _normalize_session_payload(user_id, sid, session_payload)
            row = _upsert_session_row(user_id, sid, normalized, existing=existing.get(sid))
            if row.id is None:
                db.session.add(row)
            migrated += 1
    return migrated


def migrate_scenarios():
    migrated = 0
    for path in SCENARIOS_DIR.glob("user_*_scenarios.json"):
        user_id = path.name.replace("user_", "").replace("_scenarios.json", "")
        payload = _load_json(path)
        if not isinstance(payload, dict):
            continue
        existing = {
            row.session_id: row
            for row in UserSession.query.filter_by(user_id=str(user_id)).all()
        }
        for thread_id, thread_payload in payload.items():
            if not isinstance(thread_payload, dict):
                continue
            sid = str(thread_id or "").strip()
            if not sid:
                continue
            row = existing.get(sid)
            if row is None:
                normalized = _normalize_session_payload(
                    user_id,
                    sid,
                    {
                        "session_id": sid,
                        "name": "Jaspen Intake",
                        "document_type": "strategy",
                        "status": "in_progress",
                    },
                )
                row = _upsert_session_row(user_id, sid, normalized, existing=None)
                db.session.add(row)
                existing[sid] = row
            row.scenarios_json = thread_payload
            migrated += 1
    return migrated


def main():
    app = create_app()
    with app.app_context():
        session_count = migrate_sessions()
        scenario_count = migrate_scenarios()
        db.session.commit()
        print(
            json.dumps(
                {
                    "migrated_sessions": session_count,
                    "migrated_scenarios": scenario_count,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
