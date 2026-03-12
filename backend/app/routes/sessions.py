# app/routes/sessions.py

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
import json
import os
from datetime import datetime
import logging

from app import db
from app.models import UserSession


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

sessions_bp = Blueprint('sessions', __name__)

# Legacy file storage path used before DB persistence.
SESSIONS_DIR = 'sessions_data'
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


def _ensure_sessions_dir():
    if not os.path.exists(SESSIONS_DIR):
        os.makedirs(SESSIONS_DIR)


def _legacy_sessions_file(user_id):
    _ensure_sessions_dir()
    return os.path.join(SESSIONS_DIR, f'user_{user_id}_sessions.json')


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


def _migrate_legacy_file_to_db(user_id):
    sessions_file = _legacy_sessions_file(user_id)
    if not os.path.exists(sessions_file):
        return False

    try:
        with open(sessions_file, 'r') as f:
            legacy = json.load(f) or {}
    except Exception as e:
        logger.error(f"Failed reading legacy session file for user {user_id}: {e}")
        return False

    if not isinstance(legacy, dict) or not legacy:
        return False

    if not save_user_sessions(user_id, legacy):
        return False

    try:
        os.rename(sessions_file, f"{sessions_file}.migrated")
    except Exception:
        # Keep original file if rename fails; DB has source of truth now.
        pass
    logger.info(f"Migrated {len(legacy)} legacy sessions for user {user_id} to database")
    return True


def load_user_sessions(user_id):
    """Load sessions for a user from DB, with one-time migration from legacy files."""
    user_id = str(user_id)

    rows = (
        UserSession.query
        .filter_by(user_id=user_id)
        .order_by(UserSession.updated_at.desc(), UserSession.id.desc())
        .all()
    )

    if not rows and _migrate_legacy_file_to_db(user_id):
        rows = (
            UserSession.query
            .filter_by(user_id=user_id)
            .order_by(UserSession.updated_at.desc(), UserSession.id.desc())
            .all()
        )

    sessions = {}
    for row in rows:
        payload = _session_row_to_payload(row)
        sessions[str(payload.get('session_id') or row.session_id)] = payload
    return sessions


def save_user_sessions(user_id, sessions):
    """Persist the complete session map for a user into DB."""
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

        for sid, row in existing_rows.items():
            if sid not in incoming_ids:
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
        sessions = load_user_sessions(current_user_id)
        sessions_list = list(sessions.values())
        sessions_list.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        return jsonify({'success': True, 'sessions': sessions_list})
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
