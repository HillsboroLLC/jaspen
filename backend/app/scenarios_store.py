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


def _readable_by(user_id, row):
    from app.models import User
    from app.session_access import can_read_session
    user = User.query.get(str(user_id)) if user_id else None
    return user is not None and can_read_session(row, user)


def _active_organization_id(user_id):
    """The organization a new scenario-backed row belongs to."""
    from app.models import User
    user = User.query.get(str(user_id)) if user_id else None
    return getattr(user, "active_organization_id", None) or None


def _canonical_row_for(user_id, session_id):
    """The organization's canonical row for this thread, if any.

    Deliberately routed through app.session_access rather than re-deriving the
    rule here: one canonical-resolution implementation, so this path and the
    session save path can never disagree about which row is the real one.
    """
    from app.models import User
    from app.session_access import canonical_row

    user = User.query.get(str(user_id)) if user_id else None
    if user is None:
        return None
    return canonical_row(user, session_id, include_archived=True)


def _attributed_rows(user_id, path):
    """The caller's own rows, minus organization work they can no longer reach.

    Load and save must agree: a row hidden from the load must also be left out
    of the save, or saving would clear its scenario data.
    """
    from app.session_access import reachable_by_attribution
    return [
        row for row in UserSession.query.filter_by(user_id=str(user_id)).all()
        if reachable_by_attribution(row, user_id, path=path)
    ]


def load_scenarios_data(user_id):
    rows = _attributed_rows(user_id, 'load_scenarios')
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
            for row in _attributed_rows(user_id, 'save_scenarios')
        }
        incoming = set()
        for thread_id, thread_payload in payloads.items():
            sid = str(thread_id or "").strip()
            if not sid or not isinstance(thread_payload, dict):
                continue
            incoming.add(sid)
            row = existing.get(sid)
            if row is None:
                # Canonical resolution before creating anything. This path
                # writes scenario data onto a UserSession row, and looking the
                # row up by the CALLER's user_id would miss the organization's
                # canonical row for a shared project -- inserting a second row
                # under the collaborator instead, which is precisely the silent
                # fork Phase 1 removed from the session save path. Scenario
                # writes are reachable by any member with edit rights, so this
                # would have reintroduced fork debt through a side door.
                row = _canonical_row_for(user_id, sid)
                if row is not None:
                    if not _readable_by(user_id, row):
                        # Never write onto, or fork, a project this caller
                        # cannot read.
                        continue
                    existing[sid] = row

            if row is None:
                row = UserSession(
                    user_id=str(user_id),
                    session_id=sid,
                    name="Jaspen Intake",
                    document_type="strategy",
                    status="in_progress",
                    organization_id=_active_organization_id(user_id),
                    created_by_user_id=str(user_id),
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
