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
    """
    Save or update a session
    Request body should include session_id and any fields to update
    """
    try:
        current_user_id = get_jwt_identity()
        data = request.get_json()
        
        session_id = data.get('session_id')
        if not session_id:
            return jsonify({'error': 'session_id is required'}), 400
        
        # Load existing sessions
        sessions = _load_user_sessions(current_user_id)
        
        # Get existing session or create new one
        existing_session = sessions.get(session_id, {})
        
        # Update session with new data
        sessions[session_id] = {
            'session_id': session_id,
            'name': data.get('name', existing_session.get('name', '')),
            'description': data.get('description', existing_session.get('description', '')),
            'document_type': data.get('document_type', existing_session.get('document_type', '')),
            'current_phase': data.get('current_phase', existing_session.get('current_phase', 1)),
            'chat_history': data.get('chat_history', existing_session.get('chat_history', [])),
            'readiness': data.get('readiness', existing_session.get('readiness')),
            'collected_data': data.get('collected_data', existing_session.get('collected_data', {})),
            'notes': data.get('notes', existing_session.get('notes', {})),
            'created': existing_session.get('created', data.get('created', datetime.now().isoformat())),
            'timestamp': datetime.now().isoformat(),
            'status': data.get('status', existing_session.get('status', 'in_progress')),
            'score': data.get('score', existing_session.get('score')),
            'user_id': current_user_id
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
