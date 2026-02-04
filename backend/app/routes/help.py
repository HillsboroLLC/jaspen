# app/routes/help.py

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
import anthropic
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

help_bp = Blueprint('help', __name__)

def _get_claude_client():
    """Get Claude API client"""
    key = (
        os.environ.get("CLAUDE_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
    )
    if not key:
        raise ValueError("CLAUDE_API_KEY not configured")
    return anthropic.Anthropic(api_key=key)

@help_bp.route('/chat', methods=['POST'])
@jwt_required()
def help_chat():
    """
    AI assistant for general help questions
    Request: {message: string, context?: string}
    Response: {response: string}
    """
    try:
        current_user_id = get_jwt_identity()
        data = request.get_json()
        
        user_message = data.get('message', '').strip()
        if not user_message:
            return jsonify({'error': 'Message is required'}), 400
        
        context = data.get('context', '')
        
        # Build system prompt
        system_prompt = """You are a helpful assistant for the Sekki platform, which provides:
        - Market IQ: Business idea validation and scoring
        - PM Dashboard: Project management tools
        - LSS Dashboard: Lean Six Sigma improvement tools
        
        Help users understand features, navigate the platform, and answer questions about business analysis, project management, and process improvement."""
        
        # Build messages
        messages = [
            {
                "role": "user",
                "content": f"{context}\n\n{user_message}" if context else user_message
            }
        ]
        
        # Call Claude
        client = _get_claude_client()
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=1024,
            system=system_prompt,
            messages=messages
        )
        parts = []
        for blk in response.content:
            if getattr(blk, "type", None) == "text":
                parts.append(blk.text)
        assistant_response = ("".join(parts)).strip()

        
        logger.info(f"Help chat for user {current_user_id}")
        
        return jsonify({
            'success': True,
            'response': assistant_response
        })
        
    except Exception as e:
        logger.error(f"Error in help chat: {e}")
        return jsonify({'error': str(e)}), 500
