# app/routes/sessions.py

from flask import Blueprint, g, has_app_context, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime
import json
import logging
import random
import time

from sqlalchemy import event

from app import db
from app.models import User, UserSession
from app.project_changes import ConflictingChange, apply_request_changes, changed_paths
from app.session_access import (
    LostRace,
    RevisionConflict,
    attributed_scope_clause,
    SessionAccessError,
    SessionForbidden,
    SessionNotFound,
    can_archive_session,
    can_read_session,
    can_write_session,
    canonical_row,
    check_revision,
    extract_base_revision,
    hide_for_user,
    is_hidden_for,
    is_personal_session_id,
    lock_project_row,
    reachable_by_attribution,
    resolve_session_for_actor,
    stamp_write,
    unhide_for_user,
    uses_personal_hide,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

sessions_bp = Blueprint('sessions', __name__)

SESSION_VISIBILITY_PRIVATE = 'private'
SESSION_VISIBILITY_TEAM = 'team'
SESSION_VISIBILITY_SPECIFIC = 'specific'
SESSION_VISIBILITY_OPTIONS = {
    SESSION_VISIBILITY_PRIVATE,
    SESSION_VISIBILITY_TEAM,
    SESSION_VISIBILITY_SPECIFIC,
}


def _iso_now():
    return datetime.utcnow().isoformat()


def _parse_dt(value):
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        text = str(value).strip()
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _as_int(value, default=1):
    try:
        return int(value)
    except Exception:
        return default


def _normalize_visibility(value):
    key = str(value or '').strip().lower()
    return key if key in SESSION_VISIBILITY_OPTIONS else SESSION_VISIBILITY_PRIVATE


def _normalize_user_id_list(value):
    if not isinstance(value, (list, tuple, set)):
        return []
    out = []
    seen = set()
    for raw in value:
        candidate = str(raw or '').strip()
        if not candidate or candidate in seen:
            continue
        out.append(candidate)
        seen.add(candidate)
    return out


def _server_organization_id(user_id, session_id, src):
    """Resolve the organization that owns this row, server-side.

    The client used to supply `organization_id` and a save that omitted it
    silently detached the project from its organization. Ownership is now
    derived from the caller's membership; the client value is only a fallback
    for callers that legitimately carry it (e.g. a row being re-saved).

    Personal-scope sessions -- the `__user_memory__` sentinel -- are never
    given an organization. See app/session_access.PERSONAL_SESSION_IDS.
    """
    if is_personal_session_id(session_id):
        return None

    supplied = str((src or {}).get('organization_id') or '').strip() or None
    if supplied:
        return supplied

    user = User.query.get(str(user_id)) if user_id else None
    return getattr(user, 'active_organization_id', None) or None


def _normalize_session_payload(user_id, session_id, payload, *, derive_organization=True):
    now_iso = _iso_now()
    src = payload if isinstance(payload, dict) else {}

    created = src.get('created') or src.get('timestamp') or now_iso
    timestamp = src.get('timestamp') or now_iso

    normalized = {
        **src,
        'session_id': str(src.get('session_id') or session_id),
        'name': src.get('name') or 'Jaspen Intake',
        'document_type': src.get('document_type') or 'strategy',
        'current_phase': _as_int(src.get('current_phase'), default=1),
        'chat_history': src.get('chat_history') if isinstance(src.get('chat_history'), list) else [],
        'notes': src.get('notes') if isinstance(src.get('notes'), dict) else {},
        'created': created,
        'timestamp': timestamp,
        'status': src.get('status') or 'in_progress',
        'user_id': str(user_id),
        'organization_id': (
            _server_organization_id(user_id, session_id, src)
            if derive_organization
            else (str(src.get('organization_id') or '').strip() or None)
        ),
        'created_by_user_id': str(src.get('created_by_user_id') or src.get('owner_user_id') or user_id),
        'visibility': _normalize_visibility(src.get('visibility')),
        'shared_with_user_ids': _normalize_user_id_list(src.get('shared_with_user_ids')),
    }
    return normalized


def _pagination_params():
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 25, type=int), 100)
    return max(page, 1), max(per_page, 1)


def _session_row_to_payload(row):
    payload = row.payload if isinstance(row.payload, dict) else {}
    # derive_organization=False: the row's own column is authoritative here and
    # is assigned below. Deriving would issue a User lookup per row and turn
    # every history load into an N+1.
    normalized = _normalize_session_payload(
        row.user_id, row.session_id, payload, derive_organization=False
    )

    if row.name:
        normalized['name'] = row.name
    if row.document_type:
        normalized['document_type'] = row.document_type
    if row.status:
        normalized['status'] = row.status
    normalized['organization_id'] = row.organization_id
    normalized['created_by_user_id'] = row.created_by_user_id
    normalized['visibility'] = _normalize_visibility(row.visibility)
    normalized['shared_with_user_ids'] = _normalize_user_id_list(row.shared_with_user_ids)
    # Concurrency + attribution surfaced to the client. `revision` is what a
    # client must echo back as `base_revision` on write.
    normalized['revision'] = int(row.revision or 1)
    normalized['last_edited_by_user_id'] = row.last_edited_by_user_id
    normalized['hidden_for_user_ids'] = _normalize_user_id_list(row.hidden_for_user_ids)
    if row.created_at:
        normalized['created'] = row.created_at.isoformat()
    if row.updated_at:
        normalized['timestamp'] = row.updated_at.isoformat()

    return normalized


# Keys that are not project CONTENT, and so must not count as a change when
# deciding whether to bump `revision`:
#   timestamp / revision / last_edited_by_user_id -- move on every write.
#   base_revision                -- a request-only assertion, never stored.
#   hidden_for_user_ids          -- per-member view state that lives in its own
#                                   column; the read path adds it to the payload
#                                   for the client, so comparing it would make
#                                   every re-save look like an edit.
_VOLATILE_PAYLOAD_KEYS = (
    'timestamp',
    'revision',
    'base_revision',
    'last_edited_by_user_id',
    'hidden_for_user_ids',
)


def _payload_content(payload):
    if not isinstance(payload, dict):
        return {}
    return {k: v for k, v in payload.items() if k not in _VOLATILE_PAYLOAD_KEYS}


def _upsert_session_row(user_id, session_id, payload, existing=None):
    normalized = _normalize_session_payload(user_id, session_id, payload)
    is_new = existing is None
    row = existing or UserSession(user_id=str(user_id), session_id=str(session_id))

    row.name = normalized.get('name') or 'Jaspen Intake'
    row.document_type = normalized.get('document_type') or 'strategy'
    row.status = normalized.get('status') or 'in_progress'
    row.visibility = _normalize_visibility(normalized.get('visibility'))
    row.shared_with_user_ids = _normalize_user_id_list(normalized.get('shared_with_user_ids'))

    if is_new:
        row.organization_id = normalized.get('organization_id')
        row.created_by_user_id = normalized.get('created_by_user_id') or str(user_id)
        row.revision = 1
    else:
        # ATTRIBUTION IS IMMUTABLE. A collaborator writing the canonical row
        # must not become its creator or its home user -- that is precisely the
        # confusion this phase exists to remove. Ownership stays with the
        # organization; only `last_edited_by_user_id` moves.
        if row.organization_id is None and normalized.get('organization_id'):
            row.organization_id = normalized.get('organization_id')
        if not row.created_by_user_id:
            row.created_by_user_id = normalized.get('created_by_user_id') or str(row.user_id)

        # The creation date belongs to the row, not to whatever the client
        # happened to send. A partial save (say `{session_id, name}`) would
        # otherwise re-stamp `created` with "now" and read as a content change
        # on every request.
        if row.created_at is not None:
            normalized['created'] = row.created_at.isoformat()

        # Bump ONLY when the content actually changed. save_user_sessions() is
        # routinely handed the caller's whole session dict to persist one
        # edit; stamping every row in it would inflate revisions on untouched
        # projects, fire spurious conflicts, and -- worse -- rewrite
        # `last_edited_by_user_id` on work this caller never opened.
        if _payload_content(normalized) != _payload_content(row.payload):
            stamp_write(row, user_id)

    # Keep the stored payload consistent with the row's authoritative columns
    # rather than with whatever the caller sent.
    normalized['organization_id'] = row.organization_id
    normalized['created_by_user_id'] = row.created_by_user_id
    normalized['user_id'] = str(row.user_id)
    normalized['revision'] = int(row.revision or 1)
    normalized.pop('base_revision', None)
    row.payload = normalized

    created_dt = _parse_dt(normalized.get('created'))
    if created_dt and (existing is None or existing.created_at is None):
        row.created_at = created_dt
    if row.created_at is None:
        row.created_at = datetime.utcnow()

    updated_dt = _parse_dt(normalized.get('timestamp')) or datetime.utcnow()
    row.updated_at = updated_dt

    return row


def load_user_sessions(user_id, include_archived=False):
    """Load sessions for a user from the database.

    By default archived sessions (soft-deleted via "Delete from my history")
    are filtered out. Set ``include_archived=True`` for admin / restore /
    purge-sweep flows that need to see them.
    """
    user_id = str(user_id)

    query = (
        UserSession.query
        .filter_by(user_id=user_id)
    )
    if not include_archived:
        query = query.filter(UserSession.archived_at.is_(None))
    rows = query.order_by(UserSession.updated_at.desc(), UserSession.id.desc()).all()

    sessions = {}
    for row in rows:
        if is_hidden_for(row, user_id):
            # Removed from THIS member's history without archiving the
            # organization's canonical row.
            continue
        if not reachable_by_attribution(row, user_id, path='load_user_sessions'):
            # Organization work this user created before leaving the
            # organization (or losing their seat).
            continue
        payload = _session_row_to_payload(row)
        _remember_read(payload)
        sessions[str(payload.get('session_id') or row.session_id)] = payload
    return sessions


def load_sessions_for_thread(user, thread_id, include_archived=False):
    """The caller's own sessions, plus the canonical organization row for one
    thread when that thread is owned by the org rather than by the caller.

    This is the compatibility shim that lets the existing
    ``sessions = load_user_sessions(uid); _resolve_user_session(sessions, tid)``
    idiom keep working at ~39 single-session call sites while resolving the
    ONE canonical row. `load_user_sessions` itself deliberately keeps its
    personal-only semantics, because history lists, exports, dashboard counts
    and the `__user_memory__` sentinel all depend on it staying personal.

    Authorization still happens at the endpoint via resolve_session_for_actor();
    the organization row is added only when the caller may read it, so an
    endpoint that tolerates a missing row can never pick up an unreadable one.
    """
    if user is None:
        return {}

    sessions = load_user_sessions(str(user.id), include_archived=include_archived)

    sid = str(thread_id or '').strip()
    if not sid or is_personal_session_id(sid):
        return sessions

    row = canonical_row(user, sid, include_archived=include_archived)
    if row is None:
        own_payload = sessions.get(sid)
        if isinstance(own_payload, dict) and own_payload.get('organization_id'):
            # A report-mode attribution row may still appear in the caller's
            # personal list after org membership changes. It is not a
            # canonical project for the caller's active org.
            sessions.pop(sid, None)
        return sessions

    # The canonical row is the project for this id. A personal row the caller
    # still holds under the same id (a fork written before saves resolved by
    # organization) is never authoritative for it: left in place, it would be
    # what the endpoint reads and then saves over the canonical row. The fork
    # itself is not changed or deleted; it is only not used here.
    if is_hidden_for(row, str(user.id)) or not can_read_session(row, user):
        sessions.pop(sid, None)
        return sessions

    payload = _session_row_to_payload(row)
    _remember_read(payload)
    sessions[str(payload.get('session_id') or row.session_id)] = payload
    return sessions


def archive_user_session(user_id, session_id, grace_days=30):
    """Remove a session from this member's history.

    Two distinct outcomes, deliberately separated (audit risk R6):

    * **Personal hide** -- when the row is organization-owned, shared, and the
      organization has more than one active member. The caller's id is added to
      `hidden_for_user_ids`. `archived_at` and `purge_after` are NOT set, so
      the purge sweep can never destroy shared organizational work because one
      member tidied their own list.
    * **Organization archive** -- every other case, including every solo user.
      Sets `archived_at` + `purge_after` exactly as before, so single-member
      behaviour is byte-for-byte what it was.

    Requires archive permission for the organization-archive path. Returns the
    row (or None) so callers can still read payload fields for ledger
    distillation in the same transaction.
    """
    from datetime import timedelta
    user_id = str(user_id)
    sid = str(session_id)
    actor = User.query.get(user_id)

    row = canonical_row(actor, sid, include_archived=True) if actor else None
    if row is None:
        row = (
            UserSession.query
            .filter_by(user_id=user_id, session_id=sid)
            .first()
        )
    if row is None:
        return None

    if actor is not None and uses_personal_hide(row, actor):
        hide_for_user(row, user_id)
        db.session.commit()
        return row

    if actor is not None and not can_archive_session(row, actor):
        raise SessionForbidden(
            'Only an organization owner, admin, or the project creator can '
            'archive this project for the organization.'
        )

    now = datetime.utcnow()
    row.archived_at = now
    row.purge_after = now + timedelta(days=max(1, int(grace_days)))
    db.session.commit()
    return row


def restore_user_session(user_id, session_id):
    """Undo archive_user_session(), in whichever mode it ran.

    Clears this member's personal hide and, when they may archive, lifts the
    organization-level archive too.
    """
    user_id = str(user_id)
    sid = str(session_id)
    actor = User.query.get(user_id)

    row = canonical_row(actor, sid, include_archived=True) if actor else None
    if row is None:
        row = (
            UserSession.query
            .filter_by(user_id=user_id, session_id=sid)
            .first()
        )
    if row is None:
        return None

    unhide_for_user(row, user_id)
    if row.archived_at is not None and (actor is None or can_archive_session(row, actor)):
        row.archived_at = None
        row.purge_after = None
    db.session.commit()
    return row


def hard_delete_user_session(user_id, session_id):
    """Hard-delete a single canonical session row (no soft-delete
    intermediate). Use for "Purge permanently" and for the purge sweep past
    the grace window. Returns True if a row was removed.

    Permission-checked: a collaborator cannot permanently destroy the
    organization's canonical work product.
    """
    user_id = str(user_id)
    sid = str(session_id)
    actor = User.query.get(user_id)

    row = canonical_row(actor, sid, include_archived=True) if actor else None
    if row is None:
        row = (
            UserSession.query
            .filter_by(user_id=user_id, session_id=sid)
            .first()
        )
    if row is None:
        return False
    if actor is not None and not can_archive_session(row, actor):
        raise SessionForbidden(
            'Only an organization owner, admin, or the project creator can '
            'permanently delete this project.'
        )
    try:
        db.session.delete(row)
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error hard-deleting session {sid} for user {user_id}: {e}")
        return False


def _session_query_for_user(user_id):
    user_id = str(user_id)
    query = UserSession.query.filter_by(user_id=user_id)
    scope = attributed_scope_clause(user_id)
    if scope is not None:
        query = query.filter(scope)
    return query.order_by(UserSession.updated_at.desc(), UserSession.id.desc())


# ---------------------------------------------------------------------------
# One project per write (P3)
#
# A route reads a project, changes part of it and saves it. Every project a
# route loads is remembered for the rest of the request (the version it read,
# by revision), so the store can tell what THIS request changed. When someone
# else saved the same project in between, only this request's changes are
# applied to the stored project (app.project_changes); a part both writers
# changed differently is refused with the approved conflict message, never
# overwritten.
# ---------------------------------------------------------------------------

PROJECT_WRITE_ATTEMPTS = 3
_RETRY_PAUSE_SECONDS = 0.02
_REQUEST_RECORDS = ('_p3_project_reads', '_p3_own_paths', '_p3_uncommitted')


@sessions_bp.before_app_request
def _start_project_write_record():
    """The record belongs to one request, even where an application context
    outlives it (tests, CLI); it is never shared between requests."""
    for name in _REQUEST_RECORDS:
        g.pop(name, None)


@sessions_bp.teardown_app_request
def _end_project_write_record(_exc=None):
    for name in _REQUEST_RECORDS:
        g.pop(name, None)


def _project_reads():
    if not has_app_context():
        return None
    reads = getattr(g, '_p3_project_reads', None)
    if reads is None:
        reads = {}
        g._p3_project_reads = reads
    return reads


def _own_paths(row):
    """Parts of this project the current request has already saved."""
    if not has_app_context():
        return set()
    own = getattr(g, '_p3_own_paths', None)
    if own is None:
        own = {}
        g._p3_own_paths = own
    return own.setdefault((str(row.user_id or ''), str(row.session_id or '')), set())


def _remember_read(payload):
    """Record the version of a project this request was handed."""
    reads = _project_reads()
    if reads is None or not isinstance(payload, dict):
        return
    try:
        revision = int(payload.get('revision'))
    except (TypeError, ValueError):
        return
    key = (str(payload.get('user_id') or ''), str(payload.get('session_id') or ''), revision)
    is_new = key not in reads
    reads[key] = json.dumps(_payload_content(payload), default=str)
    return key if is_new else None


def _uncommitted():
    """What this request recorded for writes its open transaction holds."""
    if not has_app_context():
        return None
    pending = getattr(g, '_p3_uncommitted', None)
    if pending is None:
        pending = []
        g._p3_uncommitted = pending
    return pending


@event.listens_for(db.session, 'after_commit')
def _keep_committed_records(_session):
    """The writes are stored: their records stay for the rest of the request."""
    if has_app_context():
        g.pop('_p3_uncommitted', None)


@event.listens_for(db.session, 'after_rollback')
def _forget_rolled_back_records(_session):
    """The writes were rolled back (a lost race re-running its unit, a refusal,
    an error): forget the versions and own paths they recorded, so a retry
    neither treats a version that was never stored as read nor wins a
    conflict over a path it never wrote. Versions the request loaded stay."""
    if not has_app_context():
        return
    pending = g.pop('_p3_uncommitted', None) or []
    reads = getattr(g, '_p3_project_reads', None) or {}
    own = getattr(g, '_p3_own_paths', None) or {}
    for kind, key, value in reversed(pending):
        if kind == 'read':
            reads.pop(key, None)
        elif kind == 'own' and key in own:
            own[key].discard(value)


def _version_read(payload, row):
    """The version of this project the request read at the payload's revision."""
    reads = _project_reads()
    if not reads:
        return None
    try:
        revision = int(payload.get('revision'))
    except (TypeError, ValueError):
        return None
    owner = str(payload.get('user_id') or row.user_id or '')
    for sid in {str(payload.get('session_id') or ''), str(row.session_id or '')}:
        stored = reads.get((owner, sid, revision))
        if stored is not None:
            return json.loads(stored)
    return None


def _apply_to_current(row, payload):
    """Apply only this request's changes when the project moved on.

    Returns the payload to write. Raises RevisionConflict when this request
    and another writer changed the same part differently.

    * A declared ``base_revision`` (already checked against the stored row) is
      the caller's own claim that it builds on the current version: written
      as given.
    * A copy this request loaded (its ``revision`` matches a version this
      request was handed) has only its changes applied to what is stored.
    * Anything else carries no usable starting point and is written as
      given, exactly as before P3.
    """
    if extract_base_revision(payload) is not None:
        return payload
    original = _version_read(payload, row)
    if original is None:
        return payload

    current = _session_row_to_payload(row)
    if _payload_content(current) == _payload_content(original):
        return payload

    current_revision = int(row.revision or 1)
    try:
        merged = apply_request_changes(
            _payload_content(original),
            _payload_content(payload),
            _payload_content(current),
            own_paths=_own_paths(row),
        )
    except ConflictingChange as conflict:
        logger.info(
            "Same-object conflict on project %s at %s", row.session_id, conflict.paths[:5]
        )
        raise RevisionConflict(payload.get('revision'), current_revision, session_id=row.session_id)

    for key in _VOLATILE_PAYLOAD_KEYS:
        if key in payload:
            merged[key] = payload[key]
    return merged


def _resolve_write_target(actor, user_id, sid):
    existing = canonical_row(actor, sid, include_archived=True) if actor else None
    if existing is not None:
        return existing
    if actor is None:
        # Preserve the old fallback only when there is no actor record.
        return (
            UserSession.query
            .filter_by(user_id=user_id, session_id=sid)
            .first()
        )
    # For a known actor, canonical_row already returns their unbound legacy
    # row; an org-bound row from another active org must not be overwritten
    # as a fallback.
    own = (
        UserSession.query
        .filter_by(user_id=user_id, session_id=sid)
        .first()
    )
    if own is not None and own.organization_id:
        raise SessionNotFound(denied=True)
    return own


def _write_one_project(actor, user_id, key, payload):
    """Stage one project's write in the current transaction. Returns the row."""
    sid = str(payload.get('session_id') or key or '').strip()
    if not sid:
        return None

    existing = _resolve_write_target(actor, user_id, sid)
    if existing is None:
        row = _upsert_session_row(user_id, sid, payload, existing=None)
        db.session.add(row)
        db.session.flush()
        _after_write(payload, row, before=None)
        return row

    for attempt in range(PROJECT_WRITE_ATTEMPTS):
        # Decide against what is stored now, locked until this transaction
        # ends (session_access.lock_project_row). Comments, sharing and the
        # activity feed change the payload without a new revision, so the
        # compare-and-swap alone cannot see them; with the lock they wait for
        # this save, or this save waits for them and applies its changes on
        # top of theirs.
        lock_project_row(existing)
        # Access is decided on the locked row, so a project unshared a moment
        # ago is not written by someone who just lost access.
        if actor is not None and not can_read_session(existing, actor):
            raise SessionNotFound(denied=True)
        if actor is not None and not can_write_session(existing, actor):
            raise SessionForbidden(
                'Your role on this project is read-only.'
            )
        # Only validate an EXPLICIT claim here. Whether a revision is
        # *required* is an endpoint-level decision: endpoints call
        # check_revision() directly and then strip `base_revision` before
        # handing the payload over, so re-applying the requirement at this
        # depth would reject the very write the endpoint just authorized.
        # This still catches an internal caller that passes a stale
        # base_revision through.
        declared = extract_base_revision(payload)
        if declared is not None:
            check_revision(existing, declared)
        to_write = _apply_to_current(existing, payload)
        before = _payload_content(_session_row_to_payload(existing))
        try:
            row = _upsert_session_row(user_id, sid, to_write, existing=existing)
        except LostRace:
            # Another save landed between the read above and the
            # compare-and-swap. The merge needs only stored data, so the
            # store can redo it without re-running the caller.
            db.session.expire(existing)
            if attempt + 1 >= PROJECT_WRITE_ATTEMPTS:
                raise
            continue
        db.session.flush()
        _after_write(payload, row, before=before)
        return row
    return None


def _after_write(payload, row, *, before):
    """Keep the caller's copy and this request's record on the saved version."""
    revision = int(row.revision or 1)
    if isinstance(payload, dict):
        payload['revision'] = revision
    saved = _session_row_to_payload(row)
    pending = _uncommitted()
    read_key = _remember_read(saved)
    if read_key is not None and pending is not None:
        pending.append(('read', read_key, None))
    own = _own_paths(row)
    paths = {'/'} if before is None else changed_paths(before, _payload_content(saved))
    own_key = (str(row.user_id or ''), str(row.session_id or ''))
    for path in paths - own:
        if pending is not None:
            pending.append(('own', own_key, path))
    own.update(paths)


def save_project_session(user_id, session_id, payload, *, commit=True):
    """Save exactly one project. The single-project entry to the store.

    Resolves the organization's canonical row, enforces read and write access
    and any declared ``base_revision``, then writes only what this request
    changed (see the section comment above). Returns True, or False on an
    unexpected storage error; raises SessionAccessError (403/404/409) when the
    write is refused.
    """
    user_id = str(user_id)
    actor = User.query.get(user_id)
    try:
        if isinstance(payload, dict):
            _write_one_project(actor, user_id, session_id, payload)
        if commit:
            db.session.commit()
        return True
    except SessionAccessError:
        db.session.rollback()
        raise
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error saving project {session_id} for user {user_id}: {e}")
        return False


def save_one_project(user_id, sessions, key, *, commit=True):
    """Save ``sessions[key]`` only: the route's working set stays in memory."""
    payload = sessions.get(key) if isinstance(sessions, dict) else None
    if not isinstance(payload, dict):
        return False
    return save_project_session(user_id, key, payload, commit=commit)


def delete_user_sessions(user_id, session_ids, *, commit=True):
    """Delete the named projects (permission-checked). Writes nothing else."""
    return save_user_sessions(user_id, {}, session_ids_to_delete=session_ids, commit=commit)


def run_project_write(unit, *, attempts=PROJECT_WRITE_ATTEMPTS):
    """Run a read-modify-write unit, re-running it after a lost race.

    ``unit`` reads the project, checks what the caller asserted, applies the
    change and saves, all inside the call. When another save lands between
    its read and its compare-and-swap (LostRace), the transaction is rolled
    back, including any staged session change, and the whole unit runs again
    on fresh data, up to ``attempts`` times. A conflict the caller asserted, or
    a change to the same object, is never retried. The unit must not have
    side effects outside the database before its save.
    """
    attempts = max(1, int(attempts))
    for attempt in range(attempts):
        try:
            return unit()
        except LostRace:
            db.session.rollback()
            if attempt + 1 >= attempts:
                raise
            # A short, random pause so writers that collided do not collide
            # again in lockstep.
            time.sleep(random.uniform(0, _RETRY_PAUSE_SECONDS) * (attempt + 1))
    return None


def save_user_sessions(user_id, sessions, session_ids_to_delete=None, *, commit=True):
    """Upsert provided sessions; delete only explicitly requested session ids.

    Compatibility entry. Routes save through ``save_project_session`` /
    ``save_one_project`` (one project per write) and delete through
    ``delete_user_sessions``; tests/test_p3_one_project_writes.py enforces it.
    Each project in ``sessions`` is written exactly as ``save_project_session``
    writes it, so a stale copy of a project this caller did not change is
    never written back over newer work.

    Canonical-ownership behaviour (Phase 1):

    * The target row is resolved by ORGANIZATION, not by the caller's user_id.
      An authorized collaborator saving a shared project therefore UPDATES the
      organization's one canonical row instead of inserting a second row under
      their own user_id -- the silent fork this phase removes.
    * Attribution is never rewritten. `user_id` and `created_by_user_id` stay
      as they were; the writer is recorded in `last_edited_by_user_id`.
    * A payload carrying an explicit `base_revision` is checked against the
      stored revision and refused on mismatch rather than overwriting.
    * Deletes are permission-checked. A collaborator cannot destroy the
      organization's canonical row through the bulk-save path.

    Raises SessionAccessError (403/409) rather than returning False when a
    write is refused, so the reason reaches the caller instead of looking like
    a generic save failure.
    """
    user_id = str(user_id)
    sessions = sessions if isinstance(sessions, dict) else {}
    actor = User.query.get(user_id)

    try:
        resolved = {}

        for key, payload in sessions.items():
            if not isinstance(payload, dict):
                continue
            row = _write_one_project(actor, user_id, key, payload)
            if row is not None:
                resolved[str(row.session_id)] = row

        explicit_deletes = {
            str(sid).strip()
            for sid in (session_ids_to_delete or [])
            if str(sid or "").strip()
        }
        for sid in explicit_deletes:
            row = resolved.get(sid)
            if row is None:
                row = canonical_row(actor, sid, include_archived=True) if actor else None
            if row is None:
                row = (
                    UserSession.query
                    .filter_by(user_id=user_id, session_id=sid)
                    .first()
                )
            if row is None:
                continue
            if actor is not None and not can_archive_session(row, actor):
                raise SessionForbidden(
                    'Only an organization owner, admin, or the project creator '
                    'can delete this project for the organization.'
                )
            db.session.delete(row)

        if commit:
            db.session.commit()
        else:
            db.session.flush()
        return True
    except SessionAccessError:
        db.session.rollback()
        raise
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error saving sessions for user {user_id}: {e}")
        return False


@sessions_bp.route('', methods=['POST'])
@jwt_required()
def save_session():
    """Save a single session."""
    try:
        current_user_id = get_jwt_identity()
        data = request.get_json() or {}
        session_id = str(data.get('session_id') or '').strip()
        if not session_id:
            return jsonify({'error': 'Session ID is required'}), 400

        actor = User.query.get(str(current_user_id))
        if actor is None:
            return jsonify({'error': 'User not found', 'code': 'not_found'}), 404

        existing = canonical_row(actor, session_id, include_archived=True)
        if existing is not None:
            # Authorize before writing, and refuse a stale write outright.
            resolve_session_for_actor(
                actor, session_id, require_write=True, include_archived=True
            )
            check_revision(existing, extract_base_revision(data))

        sessions = load_sessions_for_thread(actor, session_id)
        normalized = _normalize_session_payload(current_user_id, session_id, data)
        normalized.pop('base_revision', None)
        # The client's whole copy replaces the project, exactly as before; a
        # stale copy is refused above through `base_revision`, so the echoed
        # `revision` is not a second claim.
        normalized.pop('revision', None)
        sessions[session_id] = normalized

        if save_one_project(current_user_id, sessions, session_id):
            row = canonical_row(actor, session_id, include_archived=True)
            logger.info(f"Session {session_id} saved for user {current_user_id}")
            return jsonify({
                'success': True,
                'session_id': session_id,
                'revision': int(row.revision or 1) if row is not None else 1,
            })
        return jsonify({'error': 'Failed to save session'}), 500
    except SessionAccessError as exc:
        body, status = exc.to_response()
        return jsonify(body), status
    except Exception as e:
        logger.error(f"Error saving session: {e}")
        return jsonify({'error': str(e)}), 500


@sessions_bp.route('', methods=['GET'])
@jwt_required()
def get_sessions():
    """Get all sessions for the current user."""
    try:
        current_user_id = get_jwt_identity()
        page, per_page = _pagination_params()
        pagination = _session_query_for_user(current_user_id).paginate(
            page=page,
            per_page=per_page,
            error_out=False,
        )
        items = [
            _session_row_to_payload(row)
            for row in pagination.items
            if not is_hidden_for(row, current_user_id)
            and reachable_by_attribution(row, current_user_id, path='list_sessions')
        ]
        return jsonify({
            'success': True,
            'items': items,
            'sessions': items,
            'total': pagination.total,
            'page': pagination.page,
            'per_page': pagination.per_page,
            'pages': pagination.pages,
        })
    except Exception as e:
        logger.error(f"Error getting sessions: {e}")
        return jsonify({'error': str(e)}), 500


@sessions_bp.route('/<session_id>', methods=['GET'])
@jwt_required()
def get_session(session_id):
    """Get a specific session.

    Resolves the ORGANIZATION's canonical row and authorizes before returning
    it, so an authorized collaborator opens the same object the owner sees.
    """
    try:
        current_user_id = get_jwt_identity()
        actor = User.query.get(str(current_user_id))
        if actor is None:
            return jsonify({'error': 'User not found', 'code': 'not_found'}), 404

        row, _membership = resolve_session_for_actor(actor, session_id)
        return jsonify({'success': True, 'session': _session_row_to_payload(row)})
    except SessionAccessError as exc:
        body, status = exc.to_response()
        return jsonify(body), status
    except Exception as e:
        logger.error(f"Error getting session {session_id}: {e}")
        return jsonify({'error': str(e)}), 500


@sessions_bp.route('/complete', methods=['POST'])
@jwt_required()
def complete_session():
    """Mark a session as completed."""
    try:
        current_user_id = get_jwt_identity()
        data = request.get_json() or {}
        session_id = str(data.get('session_id') or '').strip()
        if not session_id:
            return jsonify({'error': 'Session ID is required'}), 400

        actor = User.query.get(str(current_user_id))
        if actor is None:
            return jsonify({'error': 'User not found', 'code': 'not_found'}), 404

        row, _membership = resolve_session_for_actor(actor, session_id, require_write=True)
        check_revision(row, extract_base_revision(data))

        sessions = load_sessions_for_thread(actor, session_id)
        if session_id not in sessions:
            return jsonify({'error': 'Session not found', 'code': 'not_found'}), 404

        sessions[session_id]['status'] = 'completed'
        sessions[session_id]['completed_at'] = _iso_now()
        sessions[session_id]['timestamp'] = _iso_now()

        if save_one_project(current_user_id, sessions, session_id):
            logger.info(f"Session {session_id} marked as completed for user {current_user_id}")
            return jsonify({'success': True})
        return jsonify({'error': 'Failed to update session'}), 500
    except SessionAccessError as exc:
        body, status = exc.to_response()
        return jsonify(body), status
    except Exception as e:
        logger.error(f"Error completing session: {e}")
        return jsonify({'error': str(e)}), 500


@sessions_bp.route('/<session_id>', methods=['DELETE'])
@jwt_required()
def delete_session(session_id):
    """Remove a session from the caller's history.

    For a shared organization project in a multi-member org this hides the
    project for this member only. For everything else -- including every solo
    user -- it archives with the usual purge grace window. See
    archive_user_session().
    """
    try:
        current_user_id = get_jwt_identity()
        actor = User.query.get(str(current_user_id))
        if actor is None:
            return jsonify({'error': 'User not found', 'code': 'not_found'}), 404

        sid = str(session_id)
        resolve_session_for_actor(actor, sid, include_archived=True)

        row = archive_user_session(current_user_id, sid, grace_days=30)
        if row is not None:
            hidden_only = row.archived_at is None
            if not hidden_only:
                # Scorecards follow the project only when the ORGANIZATION
                # archived it, never when one member hid it from their list.
                from app.scorecards import archive_thread_scorecards
                archive_thread_scorecards(current_user_id, sid)
                db.session.commit()
            logger.info(f"Session {sid} removed for user {current_user_id}")
            return jsonify({
                'success': True,
                'scope': 'personal' if hidden_only else 'organization',
            })
        return jsonify({'error': 'Failed to delete session'}), 500
    except SessionAccessError as exc:
        body, status = exc.to_response()
        return jsonify(body), status
    except Exception as e:
        logger.error(f"Error deleting session: {e}")
        return jsonify({'error': str(e)}), 500
