# app/routes/sessions.py

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
import os
import json
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

sessions_bp = Blueprint('sessions', __name__)

SESSIONS_DIR = os.path.join(os.path.dirname(__file__), '../../sessions_data')
os.makedirs(SESSIONS_DIR, exist_ok=True)

def _get_user_sessions_file(user_id):
    """Get the path to a user's sessions file"""
    return os.path.join(SESSIONS_DIR, f'{user_id}_sessions.json')

def _load_user_sessions(user_id):
    """Load all sessions for a user"""
    filepath = _get_user_sessions_file(user_id)
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading sessions for user {user_id}: {e}")
        return {}

def _save_user_sessions(user_id, sessions):
    """Save all sessions for a user"""
    filepath = _get_user_sessions_file(user_id)
    try:
        with open(filepath, 'w') as f:
            json.dump(sessions, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving sessions for user {user_id}: {e}")
        return False

@sessions_bp.route('', methods=['GET'])
@jwt_required()
def get_sessions():
    """
    Get all sessions for the current user
    Returns sessions sorted by timestamp (most recent first)
    """
    try:
        current_user_id = get_jwt_identity()
        sessions = _load_user_sessions(current_user_id)
        # Optional filter: /api/sessions?status=in_progress (or status=active)
        status = (request.args.get('status') or '').strip().lower()
        if status:
            if status in ('active', 'open', 'inprogress'):
                status = 'in_progress'

            sessions = {
                sid: s for sid, s in sessions.items()
                if (s.get('status') or '').strip().lower() == status
            }

        # Convert to list and sort by timestamp (desc)
        session_list = list(sessions.values())
        session_list.sort(key=lambda x: x.get('timestamp', ''), reverse=True)

        # Shape the response and include readiness + collected_data
        items = []
        for row in session_list:
            readiness_val = row.get('readiness', 0)

            # Normalize readiness to a dict with 'percent'
            if isinstance(readiness_val, dict):
                readiness_obj = {
                    'percent': int(readiness_val.get('percent', 0)),
                    'categories': readiness_val.get('categories', []),
                    'updated_at': readiness_val.get('updated_at'),
                }
            else:
                # handle int/float/str gracefully
                try:
                    pct = int(float(readiness_val or 0))
                except Exception:
                    pct = 0
                readiness_obj = {'percent': pct}

            items.append({
                'session_id':   row.get('session_id'),
                'name':         row.get('name'),
                'status':       row.get('status', 'in_progress'),
                'score':        row.get('score'),
                'created':      row.get('created', ''),
                'timestamp':    row.get('timestamp', ''),
                'chat_history': row.get('chat_history', []),
                'readiness':    readiness_obj,
                'collected_data': row.get('collected_data', {}),
            })

        return jsonify({'success': True, 'sessions': items})
    except Exception as e:
        logger.error(f"Error getting sessions: {e}")
        return jsonify({'error': str(e)}), 500
@sessions_bp.route('', methods=['POST'])
@jwt_required()
def save_session():
    try:
        current_user_id = get_jwt_identity()

        import json as _json

        raw_bytes = request.get_data(cache=True) or b""
        raw_text = raw_bytes.decode("utf-8", errors="ignore")

        # Try normal JSON parsing first
        data = request.get_json(silent=True) or {}

        # Fallback: if JSON parsing failed, find where JSON starts and parse from there
        if not isinstance(data, dict) or not data:
            i_obj = raw_text.find("{")
            i_arr = raw_text.find("[")
            starts = [i for i in (i_obj, i_arr) if i != -1]
            start = min(starts) if starts else -1
            if start != -1:
                try:
                    parsed = _json.loads(raw_text[start:])
                    if isinstance(parsed, dict):
                        data = parsed
                except Exception:
                    data = {}

        logger.info(f"[sessions.post] content_type={request.content_type} raw={raw_bytes[:500]!r}")
        logger.info(f"[sessions.post] json={data}")

        session_id = data.get('session_id')
        if not session_id:
            return jsonify({'error': 'session_id is required'}), 400

        # Load existing sessions
        sessions = _load_user_sessions(current_user_id)

        # Get existing session or create new one
        existing_session = sessions.get(session_id, {})

        # --- chat_history merge (single source of truth) ---
        existing_history = existing_session.get('chat_history', [])
        if not isinstance(existing_history, list):
            existing_history = []

        incoming_history = data.get('chat_history')
        if incoming_history is not None and not isinstance(incoming_history, list):
            incoming_history = [incoming_history]

        append_messages = data.get('append_messages') or data.get('append_chat_history') or None
        if append_messages is not None and not isinstance(append_messages, list):
            append_messages = [append_messages]

        # Priority:
        # 1) If client sends chat_history explicitly, replace with that
        # 2) Else if client sends append_messages, append to existing
        # 3) Else keep existing
        if isinstance(incoming_history, list) and incoming_history:
            chat_history = incoming_history
        elif isinstance(append_messages, list) and append_messages:
            chat_history = existing_history + append_messages
        else:
            chat_history = existing_history

        # Safety cap to prevent unbounded growth
        if isinstance(chat_history, list) and len(chat_history) > 400:
            chat_history = chat_history[-400:]

        # Update session with new data (do not clobber existing values with None)
        sessions[session_id] = {
            'session_id': session_id,
            'user_id': current_user_id,

            'name': data.get('name', existing_session.get('name', '')),
            'description': data.get('description', existing_session.get('description', '')),
            'document_type': data.get('document_type', existing_session.get('document_type', '')),
            'current_phase': data.get('current_phase', existing_session.get('current_phase', '')),
            'chat_history': chat_history,
            'readiness': data.get('readiness', existing_session.get('readiness')),
            'collected_data': data.get('collected_data', existing_session.get('collected_data')),

            # Persist the full scorecard and keep it if this POST doesn't include it
            'result': data.get('result', existing_session.get('result')),
            'component_scores': data.get('component_scores', existing_session.get('component_scores')),
            'financial_impact': data.get('financial_impact', existing_session.get('financial_impact')),
            'notes': data.get('notes', existing_session.get('notes', {})),

            # Preserve original created timestamp if present; otherwise use incoming or now
            'created': existing_session.get('created', data.get('created', datetime.now().isoformat())),

            # Always refresh last-updated timestamp
            'timestamp': datetime.now().isoformat(),
            'status': data.get('status', existing_session.get('status', 'in_progress')),
            'score': data.get('score', existing_session.get('score')),
        }

        # Save to file
        if _save_user_sessions(current_user_id, sessions):
            return jsonify({
                'success': True,
                'session': sessions[session_id]
            })
        else:
            return jsonify({'error': 'Failed to save session'}), 500
    except Exception as e:
        logger.error(f"Error saving session: {e}")
        return jsonify({'error': str(e)}), 500

@sessions_bp.route('/queue', methods=['GET'])
@jwt_required()
def list_queue():
    """
    Lightweight list of active threads for the UI "In the Queue" view.
    Defaults to status=in_progress.
    """
    try:
        current_user_id = get_jwt_identity()
        sessions = _load_user_sessions(current_user_id) or {}

        # default filter = in_progress
        status_filter = (request.args.get('status') or 'in_progress').strip().lower()
        limit = int(request.args.get('limit') or 50)

        items = []
        for sid, s in sessions.items():
            if not isinstance(s, dict):
                continue

            st = (s.get('status') or '').strip().lower()
            if status_filter and st != status_filter:
                continue

            chat = s.get('chat_history') or []
            last_msg = chat[-1] if isinstance(chat, list) and chat else None
            last_preview = None
            if isinstance(last_msg, dict):
                last_preview = (last_msg.get('content') or '')[:180] or None

            readiness = s.get('readiness') or {}
            readiness_pct = None
            if isinstance(readiness, dict):
                readiness_pct = readiness.get('percent')

            items.append({
                "session_id": sid,
                "name": s.get("name") or "",
                "status": s.get("status") or "",
                "score": s.get("score"),
                "readiness_percent": readiness_pct,
                "timestamp": s.get("timestamp") or s.get("created"),
                "last_message_preview": last_preview,
                "message_count": len(chat) if isinstance(chat, list) else 0,
                "has_result": bool(s.get("result")),
            })

        # newest first
        def _ts(x):
            return x.get("timestamp") or ""
        items.sort(key=_ts, reverse=True)
        return jsonify({"success": True, "sessions": items[:limit], "items": items[:limit]}), 200

    except Exception as e:
        logger.error(f"Error listing queue: {e}")
        return jsonify({"error": str(e)}), 500

@sessions_bp.route('/<session_id>', methods=['GET'])
@jwt_required()
def get_session(session_id):
    """Get a specific session by ID"""
    try:
        current_user_id = get_jwt_identity()
        sessions = _load_user_sessions(current_user_id)

        session = sessions.get(session_id)
        if not session:
            return jsonify({'error': 'Session not found'}), 404
        
        return jsonify({
            'success': True,
            'session': session
        })
    except Exception as e:
        logger.error(f"Error getting session: {e}")
        return jsonify({'error': str(e)}), 500
@sessions_bp.route('/<session_id>/bundle', methods=['GET'])
@jwt_required()
def get_session_bundle(session_id):
    """Return a 'bundle' for a session: session + convenience fields for UI hydration."""
    try:
        current_user_id = get_jwt_identity()
        sessions = _load_user_sessions(current_user_id)

        session = sessions.get(session_id)
        if not session:
            return jsonify({'error': 'Session not found'}), 404

        # Normalize basics
        chat_history = session.get('chat_history') or []
        if not isinstance(chat_history, list):
            chat_history = []

        scenarios = session.get('scenarios') or session.get('scenario_variants') or []
        if not isinstance(scenarios, list):
            scenarios = []

        active_variant_id = session.get('active_variant_id') or session.get('selected_variant_id') or 'baseline'

        # Score variants dropdown support:
        # If the session already stores variants, pass them through.
        # Otherwise, synthesize a baseline from the session's result (if any).
        score_variants = session.get('score_variants') or session.get('variants') or []
        if not isinstance(score_variants, list):
            score_variants = []

        if not score_variants:
            base_result = session.get('result') or session.get('analysis_result') or None
            if base_result:
                score_variants = [{
                    "id": "baseline",
                    "label": "Baseline",
                    "result": base_result
                }]

        bundle = {
            "thread_id": session_id,          # canonical thread id for UI
            "session_id": session_id,
            "session": session,               # original persisted object
            "messages": chat_history,         # convenience alias
            "score_variants": score_variants, # dropdown population
            "scenarios": scenarios,           # scenarios tab hydration
            "active_variant_id": active_variant_id,
        }

        return jsonify({"success": True, "bundle": bundle}), 200

    except Exception as e:
        logger.error(f"Error getting session bundle: {e}")
        return jsonify({'error': str(e)}), 500

@sessions_bp.route('/<session_id>', methods=['DELETE'])
@jwt_required()
def delete_session(session_id):
    """Delete a specific session"""
    try:
        current_user_id = get_jwt_identity()
        sessions = _load_user_sessions(current_user_id)
        
        if session_id not in sessions:
            return jsonify({'error': 'Session not found'}), 404
        
        del sessions[session_id]
        
        if _save_user_sessions(current_user_id, sessions):
            return jsonify({
                'success': True,
                'message': 'Session deleted'
            })
        else:
            return jsonify({'error': 'Failed to delete session'}), 500
            
    except Exception as e:
        logger.error(f"Error deleting session: {e}")
        return jsonify({'error': str(e)}), 500
