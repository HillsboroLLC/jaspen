# app/routes/sessions.py

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime
import logging

from app import db
from app.models import UserSession


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


def _normalize_session_payload(user_id, session_id, payload):
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
        'organization_id': str(src.get('organization_id') or '').strip() or None,
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
    normalized = _normalize_session_payload(row.user_id, row.session_id, payload)

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
    if row.created_at:
        normalized['created'] = row.created_at.isoformat()
    if row.updated_at:
        normalized['timestamp'] = row.updated_at.isoformat()

    return normalized


def _upsert_session_row(user_id, session_id, payload, existing=None):
    normalized = _normalize_session_payload(user_id, session_id, payload)
    row = existing or UserSession(user_id=str(user_id), session_id=str(session_id))

    row.name = normalized.get('name') or 'Jaspen Intake'
    row.document_type = normalized.get('document_type') or 'strategy'
    row.status = normalized.get('status') or 'in_progress'
    row.organization_id = normalized.get('organization_id')
    row.created_by_user_id = normalized.get('created_by_user_id') or str(user_id)
    row.visibility = _normalize_visibility(normalized.get('visibility'))
    row.shared_with_user_ids = _normalize_user_id_list(normalized.get('shared_with_user_ids'))
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
        payload = _session_row_to_payload(row)
        sessions[str(payload.get('session_id') or row.session_id)] = payload
    return sessions


def archive_user_session(user_id, session_id, grace_days=30):
    """Soft-delete a session: mark archived_at + schedule purge_after.

    Returns the SQLAlchemy row (or None if not found) so callers can read
    payload fields for ledger distillation in the same transaction.
    """
    from datetime import timedelta
    user_id = str(user_id)
    sid = str(session_id)
    row = (
        UserSession.query
        .filter_by(user_id=user_id, session_id=sid)
        .first()
    )
    if row is None:
        return None
    now = datetime.utcnow()
    row.archived_at = now
    row.purge_after = now + timedelta(days=max(1, int(grace_days)))
    db.session.commit()
    return row


def hard_delete_user_session(user_id, session_id):
    """Hard-delete a single user session row (no soft-delete intermediate).
    Use for "Purge permanently" and for the purge sweep past the grace
    window. Returns True if a row was removed.
    """
    user_id = str(user_id)
    sid = str(session_id)
    row = (
        UserSession.query
        .filter_by(user_id=user_id, session_id=sid)
        .first()
    )
    if row is None:
        return False
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
    query = (
        UserSession.query
        .filter_by(user_id=user_id)
        .order_by(UserSession.updated_at.desc(), UserSession.id.desc())
    )
    return query


def save_user_sessions(user_id, sessions, session_ids_to_delete=None):
    """Upsert provided sessions; delete only explicitly requested session ids."""
    user_id = str(user_id)
    sessions = sessions if isinstance(sessions, dict) else {}

    try:
        existing_rows = {
            row.session_id: row
            for row in UserSession.query.filter_by(user_id=user_id).all()
        }
        incoming_ids = set()

        for key, payload in sessions.items():
            if not isinstance(payload, dict):
                continue

            sid = str(payload.get('session_id') or key or '').strip()
            if not sid:
                continue

            incoming_ids.add(sid)
            row = _upsert_session_row(user_id, sid, payload, existing=existing_rows.get(sid))
            if row.id is None:
                db.session.add(row)

        explicit_deletes = {
            str(sid).strip()
            for sid in (session_ids_to_delete or [])
            if str(sid or "").strip()
        }
        if explicit_deletes:
            for sid, row in existing_rows.items():
                if sid in explicit_deletes:
                    db.session.delete(row)

        db.session.commit()
        return True
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

        sessions = load_user_sessions(current_user_id)
        sessions[session_id] = _normalize_session_payload(current_user_id, session_id, data)

        if save_user_sessions(current_user_id, sessions):
            logger.info(f"Session {session_id} saved for user {current_user_id}")
            return jsonify({'success': True, 'session_id': session_id})
        return jsonify({'error': 'Failed to save session'}), 500
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
        items = [_session_row_to_payload(row) for row in pagination.items]
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
    """Get a specific session."""
    try:
        current_user_id = get_jwt_identity()
        sessions = load_user_sessions(current_user_id)
        sid = str(session_id)
        if sid not in sessions:
            return jsonify({'error': 'Session not found'}), 404
        return jsonify({'success': True, 'session': sessions[sid]})
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

        sessions = load_user_sessions(current_user_id)
        if session_id not in sessions:
            return jsonify({'error': 'Session not found'}), 404

        sessions[session_id]['status'] = 'completed'
        sessions[session_id]['completed_at'] = _iso_now()
        sessions[session_id]['timestamp'] = _iso_now()

        if save_user_sessions(current_user_id, sessions):
            logger.info(f"Session {session_id} marked as completed for user {current_user_id}")
            return jsonify({'success': True})
        return jsonify({'error': 'Failed to update session'}), 500
    except Exception as e:
        logger.error(f"Error completing session: {e}")
        return jsonify({'error': str(e)}), 500


@sessions_bp.route('/<session_id>', methods=['DELETE'])
@jwt_required()
def delete_session(session_id):
    """Delete a session."""
    try:
        current_user_id = get_jwt_identity()
        sessions = load_user_sessions(current_user_id)
        sid = str(session_id)
        if sid not in sessions:
            return jsonify({'error': 'Session not found'}), 404

        del sessions[sid]
        if save_user_sessions(current_user_id, sessions):
            logger.info(f"Session {sid} deleted for user {current_user_id}")
            return jsonify({'success': True})
        return jsonify({'error': 'Failed to delete session'}), 500
    except Exception as e:
        logger.error(f"Error deleting session: {e}")
        return jsonify({'error': str(e)}), 500
