import copy
from datetime import datetime

from sqlalchemy.orm.attributes import set_committed_value

from app import db
from app.models import UserSession
from app.session_access import (
    RevisionConflict,
    SessionForbidden,
    can_write_session,
    check_revision,
    revision_required_for,
)

REVISION_UNSET = object()


class ScenariosData(dict):
    """Scenario payloads plus private canonical-row metadata."""

    def __init__(self):
        super().__init__()
        self.row_ids = {}
        self.revisions = {}
        self.canonical_ids = {}

    def remember(self, key, row):
        key = str(key)
        self.row_ids[key] = row.id
        self.revisions[key] = int(row.revision or 1)
        self.canonical_ids[key] = str(row.session_id)


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


def _actor(user_id):
    from app.models import User
    return User.query.get(str(user_id)) if user_id else None


def _active_organization_id(user_id):
    user = _actor(user_id)
    return getattr(user, "active_organization_id", None) or None


def _canonical_row_for(user_id, session_id):
    """The organization's canonical row, using the shared resolution rule."""
    from app.session_access import canonical_row
    user = _actor(user_id)
    if user is None:
        return None
    return canonical_row(user, session_id, include_archived=True)


def _attributed_rows(user_id, path):
    """The caller's own rows, minus organization work they cannot reach."""
    from app.session_access import reachable_by_attribution
    return [
        row for row in UserSession.query.filter_by(user_id=str(user_id)).all()
        if reachable_by_attribution(row, user_id, path=path)
    ]


def load_scenarios_data(user_id):
    rows = _attributed_rows(user_id, 'load_scenarios')
    out = ScenariosData()
    for row in rows:
        payload = row.scenarios_json if isinstance(row.scenarios_json, dict) else None
        if payload:
            db_sid = str(row.session_id)
            out[db_sid] = copy.deepcopy(payload)
            out.remember(db_sid, row)
            row_payload = row.payload if isinstance(row.payload, dict) else {}
            payload_sid = str(row_payload.get('session_id') or '').strip()
            if payload_sid and payload_sid != db_sid:
                out[payload_sid] = out[db_sid]
                out.remember(payload_sid, row)
    return out


def _row_from_source(user_id, project_id, source):
    row_id = source.row_ids.get(project_id) if isinstance(source, ScenariosData) else None
    if row_id is not None:
        row = db.session.get(UserSession, row_id)
        if row is not None:
            return row
    return _canonical_row_for(user_id, project_id)


def _new_row(user_id, project_id):
    row = UserSession(
        user_id=str(user_id),
        session_id=str(project_id),
        name="Jaspen Intake",
        document_type="strategy",
        status="in_progress",
        organization_id=_active_organization_id(user_id),
        created_by_user_id=str(user_id),
        last_edited_by_user_id=str(user_id),
        revision=1,
        payload=_base_session_payload(user_id, project_id),
        scenarios_json={},
    )
    db.session.add(row)
    return row


def _compare_and_swap(row, expected, next_payload, user_id):
    """The single database CAS used by project-scoped scenario writes."""
    return UserSession.query.filter(
        UserSession.id == row.id,
        UserSession.revision == expected,
    ).update({
        UserSession.scenarios_json: next_payload,
        UserSession.revision: UserSession.revision + 1,
        UserSession.last_edited_by_user_id: str(user_id),
        UserSession.updated_at: datetime.utcnow(),
    }, synchronize_session=False)


def save_project_scenarios_data(
    user_id,
    project_id,
    project_data=None,
    *,
    source=None,
    base_revision=REVISION_UNSET,
    updater=None,
    max_attempts=3,
):
    """Atomically write scenario data for exactly one canonical project.

    Snapshot writes use the revision captured by ``load_scenarios_data`` and
    never retry. Updater writes re-read and re-apply to current data after a
    lost race, unless the caller declared ``base_revision``. Returns the new
    revision.
    """
    sid = str(project_id or '').strip()
    if not sid:
        raise ValueError('project_id is required')
    if updater is not None and not callable(updater):
        raise TypeError('updater must be callable')

    revision_was_supplied = base_revision is not REVISION_UNSET
    explicit_revision = (
        revision_was_supplied
        and base_revision is not None
        and str(base_revision).strip() != ''
    )
    snapshot_revision = source.revisions.get(sid) if isinstance(source, ScenariosData) else None
    attempts = 1 if explicit_revision or snapshot_revision is not None or updater is None else max(1, int(max_attempts))

    for attempt in range(attempts):
        try:
            row = _row_from_source(user_id, sid, source)
            actor = _actor(user_id)
            if actor is None:
                raise SessionForbidden('User not found')

            if row is None:
                if isinstance(source, ScenariosData) and sid in source.canonical_ids:
                    raise RevisionConflict(
                        source.revisions.get(sid), None,
                        session_id=source.canonical_ids.get(sid),
                    )
                row = _new_row(user_id, sid)
                if not can_write_session(row, actor):
                    raise SessionForbidden()
                next_payload = updater({}) if updater is not None else project_data
                if not isinstance(next_payload, dict):
                    raise ValueError('project scenario data must be a dict')
                row.scenarios_json = copy.deepcopy(next_payload)
                db.session.commit()
                return int(row.revision or 1)

            if not can_write_session(row, actor):
                raise SessionForbidden()

            if revision_was_supplied:
                check_revision(row, base_revision)
            expected_claim = base_revision if explicit_revision else snapshot_revision
            if expected_claim is None and revision_required_for(row):
                # Internal updater-style writes re-read on every attempt, so
                # their basis is the row revision just read in this attempt.
                check_revision(row, row.revision)
            if expected_claim is not None:
                check_revision(row, expected_claim)
            expected = int(row.revision or 1)

            current = copy.deepcopy(row.scenarios_json) if isinstance(row.scenarios_json, dict) else {}
            next_payload = updater(current) if updater is not None else project_data
            if not isinstance(next_payload, dict):
                raise ValueError('project scenario data must be a dict')
            next_payload = copy.deepcopy(next_payload)

            changed = _compare_and_swap(row, expected, next_payload, user_id)
            if changed != 1:
                db.session.rollback()
                current_row = db.session.get(UserSession, row.id)
                conflict = RevisionConflict(
                    expected,
                    int(current_row.revision or 1) if current_row is not None else None,
                    session_id=row.session_id,
                )
                if attempt + 1 >= attempts:
                    raise conflict
                continue

            db.session.commit()
            set_committed_value(row, 'revision', expected + 1)
            set_committed_value(row, 'scenarios_json', next_payload)
            return expected + 1
        except RevisionConflict:
            db.session.rollback()
            raise
        except Exception:
            db.session.rollback()
            raise

    raise RevisionConflict(None, None, session_id=sid)


def clear_all_scenarios_data(user_id):
    """Deliberately clear every reachable attributed project's scenario data."""
    try:
        actor = _actor(user_id)
        for row in _attributed_rows(user_id, 'clear_all_scenarios'):
            if actor is None or not can_write_session(row, actor):
                continue
            expected = int(row.revision or 1)
            changed = UserSession.query.filter(
                UserSession.id == row.id,
                UserSession.revision == expected,
            ).update({
                UserSession.scenarios_json: {},
                UserSession.revision: UserSession.revision + 1,
                UserSession.last_edited_by_user_id: str(user_id),
                UserSession.updated_at: datetime.utcnow(),
            }, synchronize_session=False)
            if changed != 1:
                raise RevisionConflict(expected, None, session_id=row.session_id)
        db.session.commit()
        return True
    except Exception:
        db.session.rollback()
        raise
