from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
import openai
import json
import os
import re
import time
from datetime import datetime, timedelta
import uuid
from app import db
from app.models import User
from app.billing_config import (
    bootstrap_legacy_credits,
    consume_credits,
    get_allowed_model_types,
    get_default_model_type,
    get_model_catalog,
    get_monthly_credit_limit,
    normalize_model_type,
    to_public_plan,
)
from app.tool_registry import (
    get_scenario_limits_for_plan,
    get_tool_min_tier,
    get_wbs_limits_for_plan,
    is_tool_allowed,
)
from app.jira_sync import sync_wbs_to_jira
from app.connector_store import get_thread_sync_profile
from app.orgs import resolve_active_org_for_user
from .sessions import load_user_sessions, save_user_sessions

strategy_bp = Blueprint('strategy', __name__)

STRATEGY_OBJECTIVE_OPTIONS = ('balanced', 'cost', 'speed', 'growth')
STRATEGY_OBJECTIVE_ALIASES = {
    'balanced': 'balanced',
    'default': 'balanced',
    'general': 'balanced',
    'cost': 'cost',
    'cost optimization': 'cost',
    'cost-optimization': 'cost',
    'efficiency': 'cost',
    'profitability': 'cost',
    'speed': 'speed',
    'speed to market': 'speed',
    'speed-to-market': 'speed',
    'timeline': 'speed',
    'delivery': 'speed',
    'growth': 'growth',
    'revenue': 'growth',
    'expansion': 'growth',
}


def _normalize_strategy_objective(value, default='balanced'):
    text = str(value or '').strip().lower()
    if not text:
        return default
    if text in STRATEGY_OBJECTIVE_ALIASES:
        return STRATEGY_OBJECTIVE_ALIASES[text]
    compact = text.replace('_', ' ').replace('-', ' ')
    return STRATEGY_OBJECTIVE_ALIASES.get(compact, default)

# Set OpenAI API key from config
def get_openai_client():
    openai.api_key = current_app.config['OPENAI_API_KEY']
    return openai


def _extract_json_object(text):
    """Parse JSON object from model output (raw JSON or fenced/embedded JSON)."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if not json_match:
            raise ValueError("Could not parse JSON from OpenAI response")
        return json.loads(json_match.group())


def _load_thread_conversation(user_id, thread_id):
    """
    Load stored conversation history for a thread from user session storage.
    Returns [] when no matching thread/session is found.
    """
    try:
        sessions = load_user_sessions(user_id) or {}
    except Exception as e:
        print(f"[strategy.analyze] failed reading sessions for user {user_id}: {e}")
        return []

    if not isinstance(sessions, dict):
        return []

    session = sessions.get(thread_id)
    if not session:
        # Fallback: match by stored session_id field if key differs.
        for candidate in sessions.values():
            if str((candidate or {}).get('session_id', '')) == str(thread_id):
                session = candidate
                break

    if not isinstance(session, dict):
        return []

    history = session.get('chat_history')
    if isinstance(history, list):
        return history

    result_blob = session.get('result')
    if isinstance(result_blob, dict) and isinstance(result_blob.get('chat_history'), list):
        return result_blob.get('chat_history')

    return []


def _load_thread_ai_insights(user_id, thread_id, limit=2):
    try:
        sessions = load_user_sessions(user_id) or {}
    except Exception:
        return []
    if not isinstance(sessions, dict):
        return []

    session = sessions.get(thread_id)
    if not isinstance(session, dict):
        for candidate in sessions.values():
            if str((candidate or {}).get('session_id', '')) == str(thread_id):
                session = candidate
                break
    if not isinstance(session, dict):
        return []

    insights = session.get('ai_insights')
    if not isinstance(insights, list):
        return []
    trimmed = [item for item in insights if isinstance(item, dict)]
    trimmed.sort(key=lambda x: str(x.get('timestamp') or ''), reverse=True)
    return trimmed[:max(0, int(limit))]


def _conversation_to_transcript(history):
    """Normalize mixed message shapes into a plain text transcript."""
    lines = []
    for msg in history or []:
        if isinstance(msg, str):
            text = msg.strip()
            if text:
                lines.append(f"User: {text}")
            continue

        if not isinstance(msg, dict):
            continue

        role = str(msg.get('role') or msg.get('sender') or 'user').lower()
        content = msg.get('content')
        text = ''

        if isinstance(content, str):
            text = content
        elif isinstance(content, dict):
            text = content.get('text') or content.get('message') or ''
        elif isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    part = item.get('text') or item.get('content') or item.get('message')
                    if isinstance(part, str):
                        parts.append(part)
            text = ' '.join(parts)

        if not text:
            text = msg.get('text') or msg.get('message') or ''

        text = str(text).strip()
        if not text:
            continue

        speaker = 'User' if role == 'user' else 'Assistant' if role in ('assistant', 'ai', 'bot') else 'System' if role == 'system' else 'User'
        lines.append(f"{speaker}: {text}")

    return '\n'.join(lines)


def _resolve_session_entry(sessions, thread_id):
    """Resolve a session payload by map key or embedded session_id."""
    tid = str(thread_id or '').strip()
    if not tid or not isinstance(sessions, dict):
        return None, None
    if tid in sessions:
        return tid, sessions.get(tid)
    for key, candidate in sessions.items():
        if str((candidate or {}).get('session_id', '')).strip() == tid:
            return key, candidate
    return None, None


def _resolve_user_model_selection(user, requested_model_type=None):
    plan_key = to_public_plan(user.subscription_plan)
    allowed_model_types = get_allowed_model_types(plan_key, current_app.config)
    default_model_type = get_default_model_type(plan_key, current_app.config)
    selected_model_type = normalize_model_type(requested_model_type or default_model_type)

    if selected_model_type not in allowed_model_types:
        return None, {
            'error': f"Model '{requested_model_type}' is not available on your {plan_key} plan.",
            'code': 'model_type_not_allowed',
            'plan_key': plan_key,
            'allowed_model_types': allowed_model_types,
            'default_model_type': default_model_type,
        }

    model_catalog = get_model_catalog(current_app.config)
    model_meta = model_catalog.get(selected_model_type, {})
    return {
        'model_type': selected_model_type,
        'llm_model': model_meta.get('llm_model'),
        'allowed_model_types': allowed_model_types,
        'default_model_type': default_model_type,
    }, None


def _tool_access_error_response(plan_key, tool_id, access='read'):
    required_min_tier = get_tool_min_tier(tool_id)
    return jsonify({
        'error': f"Tool '{tool_id}' requires at least the {required_min_tier} tier.",
        'code': 'tool_not_allowed',
        'tool_id': tool_id,
        'requested_access': access,
        'required_min_tier': required_min_tier,
        'plan_key': plan_key,
    }), 403


def _require_tool_access(user_id, tool_id, access='read'):
    user = User.query.get(user_id)
    if not user:
        return None, None, (jsonify({'error': 'User not found'}), 404)

    plan_key = to_public_plan(user.subscription_plan)
    if not is_tool_allowed(plan_key, tool_id, access):
        return user, plan_key, _tool_access_error_response(plan_key, tool_id, access=access)

    return user, plan_key, None


def _generate_jaspen_scorecard(client, project_description, llm_model):
    """Run the existing LLM scoring flow and return parsed scorecard JSON."""
    analysis_prompt = f"""
You are a Jaspen strategy analyst specializing in commercialization strategy and financial impact assessment. Analyze the following project and provide a comprehensive strategy score and breakdown.

Project Description: {project_description}

Please provide your analysis in the following JSON format:

{{
    "jaspen_score": <number between 0-100>,
    "score_category": "<Excellent/Good/Needs Improvement>",
    "component_scores": {{
        "financial_health": <0-100>,
        "operational_efficiency": <0-100>,
        "market_position": <0-100>,
        "execution_readiness": <0-100>
    }},
    "financial_impact": {{
        "ebitda_at_risk": "<percentage>",
        "potential_loss": "<dollar amount>",
        "roi_opportunity": "<percentage>",
        "projected_ebitda": "<dollar amount>",
        "time_to_market_impact": "<description>"
    }},
    "key_insights": [
        "<insight 1>",
        "<insight 2>",
        "<insight 3>"
    ],
    "top_risks": [
        {{
            "risk": "<risk description>",
            "impact": "<financial impact>",
            "mitigation": "<mitigation strategy>"
        }}
    ],
    "recommendations": [
        {{
            "action": "<action description>",
            "expected_impact": "<expected outcome>",
            "effort": "<Low/Medium/High>",
            "timeline": "<timeframe>"
        }}
    ]
}}

Focus on:
1. EBITDA protection and optimization
2. ROI maximization opportunities
3. Time-to-market acceleration
4. Operational efficiency improvements
5. Market positioning and competitive advantage

Provide specific, actionable insights with quantified financial impacts where possible.
"""

    response = client.chat.completions.create(
        model=llm_model,
        messages=[
            {"role": "system", "content": "You are a Jaspen strategy analyst specializing in commercialization strategy. Always respond with valid JSON only."},
            {"role": "user", "content": analysis_prompt}
        ],
        temperature=0.7,
        max_tokens=2000
    )

    analysis_text = response.choices[0].message.content
    return _extract_json_object(analysis_text)


@strategy_bp.route('/analyze', methods=['POST'])
@jwt_required()
def analyze_project():
    try:
        data = request.get_json() or {}
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        if bootstrap_legacy_credits(user, current_app.config):
            db.session.commit()
        active_org, _ = resolve_active_org_for_user(user)
        active_org_id = active_org.id if active_org else user.active_organization_id

        thread_id = data.get('thread_id') or request.headers.get('X-Session-ID')
        project_name = data.get('name') or data.get('project_name') or 'Jaspen Project'
        framework_id = data.get('framework_id')
        project_description = (data.get('description') or '').strip()

        # Build analysis input from thread conversation when thread_id is provided.
        conversation_history = []
        transcript = ''
        ai_insights = []
        if thread_id:
            conversation_history = _load_thread_conversation(current_user_id, str(thread_id))
            transcript = _conversation_to_transcript(conversation_history).strip()
            ai_insights = _load_thread_ai_insights(current_user_id, str(thread_id), limit=2)
            insight_lines = []
            for item in ai_insights:
                summary = str(item.get('summary') or '').strip()
                if summary:
                    insight_lines.append(summary)
            if insight_lines:
                transcript = f"{transcript}\n\nAI Data Insights:\n- " + "\n- ".join(insight_lines) if transcript else "AI Data Insights:\n- " + "\n- ".join(insight_lines)

            if not transcript and not project_description:
                return jsonify({'error': 'No conversation found for thread_id'}), 404

        analysis_input_parts = []
        if project_name:
            analysis_input_parts.append(f"Project Name: {project_name}")
        if framework_id:
            analysis_input_parts.append(f"Framework ID: {framework_id}")
        if thread_id:
            analysis_input_parts.append(f"Thread ID: {thread_id}")

        if transcript:
            analysis_input_parts.append(f"Conversation Transcript:\n{transcript}")
        elif project_description:
            analysis_input_parts.append(f"Project Description: {project_description}")

        if not analysis_input_parts:
            return jsonify({'error': 'thread_id or description is required'}), 400

        effective_description = "\n\n".join(analysis_input_parts)

        analysis_credit_cost = int(current_app.config.get('MARKET_IQ_ANALYSIS_CREDIT_COST', 25))
        if user.credits_remaining is not None and user.credits_remaining < analysis_credit_cost:
            return jsonify({
                'error': 'Insufficient credits',
                'required_credits': analysis_credit_cost,
                'credits_remaining': user.credits_remaining,
                'plan_key': to_public_plan(user.subscription_plan),
                'monthly_credit_limit': get_monthly_credit_limit(user.subscription_plan, current_app.config),
                'suggestion': 'Purchase an overage pack or upgrade your plan.',
            }), 402

        model_selection, model_error = _resolve_user_model_selection(
            user,
            requested_model_type=data.get('model_type'),
        )
        if model_error:
            return jsonify(model_error), 403

        client = get_openai_client()
        analysis_result = _generate_jaspen_scorecard(
            client,
            effective_description,
            llm_model=model_selection['llm_model'],
        )

        analysis_id = str(uuid.uuid4())
        generated_at = datetime.utcnow().isoformat()
        resolved_thread_id = str(thread_id or f"thread_{uuid.uuid4().hex[:12]}")

        prior_meta = analysis_result.get('meta') if isinstance(analysis_result.get('meta'), dict) else {}
        analysis = {
            **analysis_result,
            'id': analysis_id,
            'analysis_id': analysis_id,
            'thread_id': resolved_thread_id,
            'framework_id': framework_id,
            'project_name': project_name,
            'project_description': effective_description,
            'timestamp': generated_at,
            'user_id': current_user_id,
            'ai_insights': ai_insights,
            'meta': {
                **prior_meta,
                'thread_id': resolved_thread_id,
                'framework_id': framework_id,
                'name': project_name,
                'conversation_turns': len(conversation_history),
                'generated_at': generated_at,
                'model_type': model_selection['model_type'],
                'llm_model': model_selection['llm_model'],
            }
        }

        charged, remaining = consume_credits(user, analysis_credit_cost)
        if not charged:
            return jsonify({
                'error': 'Insufficient credits',
                'required_credits': analysis_credit_cost,
                'credits_remaining': user.credits_remaining,
            }), 402

        db.session.commit()
        analysis['meta']['credits_charged'] = analysis_credit_cost
        analysis['meta']['credits_remaining'] = remaining

        # Persist analysis onto the thread/session so Finish & Analyze creates a real thread bundle.
        sessions = load_user_sessions(current_user_id) or {}
        session_key, session = _resolve_session_entry(sessions, resolved_thread_id)
        if not isinstance(session, dict):
            session = {
                'session_id': resolved_thread_id,
                'name': project_name or 'Jaspen Intake',
                'document_type': 'strategy',
                'model_type': model_selection['model_type'],
                'current_phase': 1,
                'chat_history': conversation_history if isinstance(conversation_history, list) else [],
                'notes': {},
                'created': generated_at,
                'timestamp': generated_at,
                'status': 'in_progress',
                'user_id': str(current_user_id),
                'created_by_user_id': str(current_user_id),
                'organization_id': active_org_id,
                'visibility': 'private',
                'shared_with_user_ids': [],
            }
            session_key = resolved_thread_id

        history = session.get('analysis_history')
        if not isinstance(history, list):
            history = session.get('analyses')
        if not isinstance(history, list):
            history = []
        history = [
            {
                'analysis_id': analysis_id,
                'id': analysis_id,
                'created_at': generated_at,
                'label': 'Baseline',
                'thread_id': resolved_thread_id,
                'result': analysis,
            },
            *[h for h in history if isinstance(h, dict) and str(h.get('analysis_id') or h.get('id')) != analysis_id],
        ][:50]

        session['session_id'] = resolved_thread_id
        session['name'] = project_name or session.get('name') or 'Jaspen Intake'
        session['document_type'] = session.get('document_type') or 'strategy'
        session['model_type'] = model_selection['model_type']
        session['organization_id'] = session.get('organization_id') or active_org_id
        session['created_by_user_id'] = session.get('created_by_user_id') or str(current_user_id)
        session['visibility'] = str(session.get('visibility') or 'private').strip().lower() or 'private'
        if not isinstance(session.get('shared_with_user_ids'), list):
            session['shared_with_user_ids'] = []
        session['strategy_objective'] = _normalize_strategy_objective(session.get('strategy_objective'))
        if 'objective_explicitly_set' not in session:
            session['objective_explicitly_set'] = False
        session['result'] = analysis
        session['analysis_history'] = history
        session['analyses'] = history
        session['adopted_analysis_id'] = analysis_id
        session['baseline_inputs'] = _extract_baseline_inputs(analysis)
        session['timestamp'] = generated_at
        session['completed_at'] = generated_at
        session['status'] = 'completed'
        if not session.get('created'):
            session['created'] = generated_at
        if not isinstance(session.get('chat_history'), list):
            session['chat_history'] = conversation_history if isinstance(conversation_history, list) else []
        if not isinstance(session.get('notes'), dict):
            session['notes'] = {}

        sessions[session_key or resolved_thread_id] = session
        persisted_session = save_user_sessions(current_user_id, sessions)

        # Ensure scenario-thread storage exists, even before any scenario/WBS is created.
        all_data = _load_scenarios(current_user_id)
        td = all_data.get(resolved_thread_id)
        if not isinstance(td, dict):
            td = _thread_entry()
        if not isinstance(td.get('scenarios'), dict):
            td['scenarios'] = {}
        if not isinstance(td.get('baseline_inputs'), dict):
            td['baseline_inputs'] = {}
        if 'adopted_scenario_id' not in td:
            td['adopted_scenario_id'] = None
        if td.get('baseline') is None or not td.get('scenarios'):
            td['baseline'] = analysis
            td['baseline_inputs'] = _extract_baseline_inputs(analysis)
            td['adopted_scenario_id'] = None
        if 'project_wbs' not in td:
            td['project_wbs'] = None
        td['strategy_objective'] = _normalize_strategy_objective(
            td.get('strategy_objective') or session.get('strategy_objective')
        )
        all_data[resolved_thread_id] = td
        persisted_bundle = _save_scenarios(current_user_id, all_data)
        analysis['meta']['thread_bundle_persisted'] = bool(persisted_session and persisted_bundle)

        return jsonify({
            'analysis': analysis,
            'thread_id': resolved_thread_id,
            'session_id': resolved_thread_id,
            'model_type': model_selection['model_type'],
            'allowed_model_types': model_selection['allowed_model_types'],
        }), 200

    except Exception as e:
        print(f"Error in Jaspen analysis: {str(e)}")
        return jsonify({'error': 'Analysis failed. Please try again.'}), 500

@strategy_bp.route('/chat', methods=['POST'])
@jwt_required()
def chat_with_analysis():
    try:
        data = request.get_json() or {}
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        if bootstrap_legacy_credits(user, current_app.config):
            db.session.commit()

        message = data.get('message', '')
        analysis_context = data.get('analysis_context', {})
        
        if not message:
            return jsonify({'error': 'Message is required'}), 400

        requested_model_type = data.get('model_type') or analysis_context.get('model_type')
        model_selection, model_error = _resolve_user_model_selection(
            user,
            requested_model_type=requested_model_type,
        )
        if model_error:
            return jsonify(model_error), 403
        
        # Initialize OpenAI
        client = get_openai_client()
        
        # Create context from analysis
        context_prompt = f"""
You are a Jaspen strategy assistant. The user has received the following analysis:

Jaspen Score: {analysis_context.get('jaspen_score', 'N/A')}
Component Scores: {json.dumps(analysis_context.get('component_scores', {}), indent=2)}
Financial Impact: {json.dumps(analysis_context.get('financial_impact', {}), indent=2)}

User Question: {message}

Provide a detailed, helpful response that:
1. References specific data from their analysis
2. Offers actionable recommendations
3. Quantifies financial impacts where possible
4. Maintains focus on EBITDA, ROI, and operational efficiency
5. Uses a professional, consultative tone

Keep responses concise but comprehensive (2-3 paragraphs maximum).
"""

        # Call OpenAI API
        response = client.chat.completions.create(
            model=model_selection['llm_model'],
            messages=[
                {"role": "system", "content": "You are a Jaspen strategy assistant specializing in commercialization strategy and financial optimization."},
                {"role": "user", "content": context_prompt}
            ],
            temperature=0.7,
            max_tokens=800
        )
        
        ai_response = response.choices[0].message.content
        
        return jsonify({
            'response': ai_response,
            'model_type': model_selection['model_type'],
            'timestamp': datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        print(f"Error in Jaspen chat: {str(e)}")
        return jsonify({'error': 'Chat failed. Please try again.'}), 500

@strategy_bp.route('/history', methods=['GET'])
@jwt_required()
def get_analysis_history():
    try:
        current_user_id = get_jwt_identity()
        
        # TODO: Implement database retrieval of user's analysis history
        # For now, return empty array
        return jsonify([]), 200
        
    except Exception as e:
        print(f"Error retrieving analysis history: {str(e)}")
        return jsonify({'error': 'Failed to retrieve history.'}), 500


# ============================================================
# FILE-BASED SCENARIO STORAGE (mirrors sessions.py pattern)
# ============================================================
SCENARIOS_DIR = 'scenarios_data'

def _ensure_scenarios_dir():
    if not os.path.exists(SCENARIOS_DIR):
        os.makedirs(SCENARIOS_DIR)

def _scenarios_file(user_id):
    _ensure_scenarios_dir()
    return os.path.join(SCENARIOS_DIR, f'user_{user_id}_scenarios.json')

def _load_scenarios(user_id):
    path = _scenarios_file(user_id)
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"[scenarios] load error for {user_id}: {e}")
    return {}

def _save_scenarios(user_id, data):
    path = _scenarios_file(user_id)
    try:
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"[scenarios] save error for {user_id}: {e}")
        return False

def _thread_entry():
    """Return a fresh empty thread data structure."""
    return {
        'baseline': None,
        'baseline_inputs': {},
        'scenarios': {},
        'adopted_scenario_id': None,
        'project_wbs': None,
        'strategy_objective': 'balanced',
    }


def _infer_lever_type(key):
    k = str(key).lower()
    if any(p in k for p in ('budget', 'invest', 'cost', 'price', 'revenue', 'value')):
        return 'currency'
    if any(p in k for p in ('month', 'timeline', 'period', 'duration')):
        return 'months'
    if any(p in k for p in ('percent', 'rate', 'margin', 'growth', 'penetrat')):
        return 'percentage'
    return 'number'


def _safe_float(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        parsed = _parse_currency(value)
        if parsed is not None:
            return float(parsed)
    return None


def _resolve_thread_baseline(user_id, thread_id):
    all_data = _load_scenarios(user_id)
    thread_data = all_data.get(thread_id)
    if not isinstance(thread_data, dict):
        thread_data = _thread_entry()
        all_data[thread_id] = thread_data

    baseline = thread_data.get('baseline') if isinstance(thread_data.get('baseline'), dict) else None
    baseline_inputs = thread_data.get('baseline_inputs') if isinstance(thread_data.get('baseline_inputs'), dict) else {}

    sessions = load_user_sessions(user_id) or {}
    _, session = _resolve_session_entry(sessions, thread_id)
    session_result = session.get('result') if isinstance(session, dict) and isinstance(session.get('result'), dict) else None

    if baseline is None and session_result:
        baseline = session_result
        thread_data['baseline'] = baseline

    if not isinstance(baseline_inputs, dict) or not baseline_inputs:
        session_inputs = session.get('baseline_inputs') if isinstance(session, dict) and isinstance(session.get('baseline_inputs'), dict) else {}
        if session_inputs:
            baseline_inputs = session_inputs
        elif isinstance(baseline, dict):
            baseline_inputs = _extract_baseline_inputs(baseline)
        else:
            baseline_inputs = {}
        thread_data['baseline_inputs'] = baseline_inputs

    session_objective = _normalize_strategy_objective(session.get('strategy_objective')) if isinstance(session, dict) else 'balanced'
    thread_objective = _normalize_strategy_objective(thread_data.get('strategy_objective'))
    objective = session_objective or thread_objective or 'balanced'
    thread_data['strategy_objective'] = objective

    return all_data, thread_data, baseline, baseline_inputs, session, objective


def _sanitize_deltas(baseline_inputs, raw_deltas):
    clean = {}
    if not isinstance(raw_deltas, dict):
        return clean
    by_lower = {str(k).lower(): k for k in baseline_inputs.keys()}
    for raw_key, raw_value in raw_deltas.items():
        key = str(raw_key or '').strip()
        if not key:
            continue
        lever_key = key if key in baseline_inputs else by_lower.get(key.lower())
        if not lever_key:
            continue
        value = _safe_float(raw_value)
        if value is None:
            continue
        clean[lever_key] = value
    return clean


def _lever_bounds(current, lever_type):
    cur = float(current if current is not None else 0.0)
    if lever_type == 'currency':
        base = abs(cur) if abs(cur) > 1 else 10000.0
        minimum = 0.0 if cur >= 0 else cur * 2.0
        maximum = max(cur + base * 2.0, base * 3.0)
        step = max(1.0, round(base * 0.01, 2))
    elif lever_type == 'months':
        minimum = 1.0
        maximum = max(24.0, cur * 3.0 if cur > 0 else 24.0)
        step = 1.0
    elif lever_type == 'percentage':
        if 0.0 <= cur <= 1.0:
            minimum = 0.0
            maximum = 1.0
            step = 0.01
        else:
            minimum = 0.0 if cur >= 0 else cur * 2.0
            maximum = max(100.0, cur * 2.0 if cur > 0 else 100.0)
            step = 0.5
    else:
        base = abs(cur) if abs(cur) > 1 else 10.0
        minimum = 0.0 if cur >= 0 else cur * 2.0
        maximum = max(cur + base * 2.0, base * 3.0)
        step = 1.0
    return {
        'min': round(float(minimum), 6),
        'max': round(float(maximum), 6),
        'step': round(float(step), 6),
    }


def _build_lever_context(baseline_inputs, suggested_deltas):
    context = []
    suggestions = suggested_deltas if isinstance(suggested_deltas, dict) else {}
    for key, raw_current in (baseline_inputs or {}).items():
        current = _safe_float(raw_current)
        if current is None:
            continue
        lever_type = _infer_lever_type(key)
        bounds = _lever_bounds(current, lever_type)
        suggested = _safe_float(suggestions.get(key))
        context.append({
            'key': key,
            'label': str(key).replace('_', ' ').title(),
            'type': lever_type,
            'current': current,
            'suggested': suggested if suggested is not None else current,
            **bounds,
        })
    return context


def _objective_guidance(objective):
    target = _normalize_strategy_objective(objective)
    if target == 'cost':
        return 'Focus on cost optimization: reduce spend and execution drag while protecting outcomes.'
    if target == 'speed':
        return 'Focus on speed-to-market: shorten timeline and unblock dependencies, even if spend increases moderately.'
    if target == 'growth':
        return 'Focus on growth: prioritize demand, expansion, and revenue acceleration.'
    return 'Keep tradeoffs balanced across cost, speed, and growth.'


def _heuristic_scenario_suggestion(instruction, baseline_inputs, objective='balanced'):
    objective = _normalize_strategy_objective(objective)
    instruction_text = str(instruction or '').strip()
    instruction_lower = instruction_text.lower()
    pct_match = re.search(r'(-?\d+(\.\d+)?)\s*%', instruction_lower)
    pct = abs(float(pct_match.group(1))) / 100.0 if pct_match else 0.15
    increase = any(term in instruction_lower for term in ('increase', 'raise', 'boost', 'grow', 'more'))
    decrease = any(term in instruction_lower for term in ('decrease', 'reduce', 'cut', 'lower', 'less'))
    explicit_direction = -1.0 if decrease and not increase else 1.0 if increase and not decrease else None
    objective_tokens = {
        'cost': ('cost', 'budget', 'cac', 'opex', 'expense', 'burn', 'run_rate'),
        'speed': ('timeline', 'month', 'duration', 'cycle', 'lead', 'resource', 'capacity', 'team'),
        'growth': ('revenue', 'market', 'growth', 'price', 'pipeline', 'demand', 'adoption'),
        'balanced': ('budget', 'timeline', 'revenue', 'margin'),
    }

    lever_key = None
    for key in baseline_inputs:
        normalized = str(key).replace('_', ' ').lower()
        if normalized in instruction_lower or any(token and token in instruction_lower for token in normalized.split()):
            lever_key = key
            break
    if lever_key is None:
        for key in baseline_inputs:
            if any(token in str(key).lower() for token in objective_tokens.get(objective, ())):
                lever_key = key
                break
    if lever_key is None and baseline_inputs:
        lever_key = next(iter(baseline_inputs.keys()))

    if lever_key is None:
        return {'label': 'AI Scenario', 'summary': 'No baseline levers available.', 'deltas': {}, 'rationale': {}}

    base = _safe_float(baseline_inputs.get(lever_key))
    if base is None:
        base = 100.0

    lk = str(lever_key).lower()
    direction = explicit_direction
    if direction is None:
        if objective == 'cost':
            direction = 1.0 if any(token in lk for token in ('revenue', 'price', 'margin')) else -1.0
        elif objective == 'speed':
            if any(token in lk for token in ('timeline', 'month', 'duration', 'cycle', 'lead')):
                direction = -1.0
            elif any(token in lk for token in ('resource', 'team', 'budget', 'capacity')):
                direction = 1.0
            else:
                direction = 1.0
        elif objective == 'growth':
            direction = 1.0
        else:
            direction = 1.0

    if _infer_lever_type(lever_key) == 'months':
        value = max(1.0, round(base + (base * pct * direction), 1))
    else:
        value = round(base * (1.0 + pct * direction), 2)

    deltas = {lever_key: value}
    rationale = {
        lever_key: (
            f"Adjusted {lever_key.replace('_', ' ')} by about {int(round(pct * 100))}% "
            f"to support a {objective} objective."
        )
    }
    return {
        'label': 'AI Suggested Scenario',
        'summary': f'Generated from your request with a {objective} objective profile.',
        'deltas': deltas,
        'rationale': rationale,
    }


def _generate_ai_scenario_suggestion(client, llm_model, instruction, baseline_inputs, objective='balanced'):
    objective = _normalize_strategy_objective(objective)
    lever_catalog = []
    for key, val in (baseline_inputs or {}).items():
        num = _safe_float(val)
        if num is None:
            continue
        lever_catalog.append({
            'key': key,
            'current': num,
            'type': _infer_lever_type(key),
        })

    if not lever_catalog:
        return _heuristic_scenario_suggestion(instruction, baseline_inputs, objective=objective)

    prompt = f"""
You are helping create a strategy scenario using existing baseline levers.

User request:
{instruction}

Objective profile:
{objective}

Objective guidance:
{_objective_guidance(objective)}

Available levers (MUST use only these keys):
{json.dumps(lever_catalog, indent=2)}

Return JSON only in this shape:
{{
  "label": "short scenario label",
  "summary": "one paragraph summary",
  "changes": [
    {{
      "lever": "exact_key_from_catalog",
      "value": 123.45,
      "rationale": "why this change helps the requested outcome"
    }}
  ]
}}

Rules:
- Suggest 1-6 lever changes.
- Keep values realistic relative to current levels.
- Always include rationale for every lever.
- Do not invent new lever keys.
- Align the recommendation with the objective profile while still honoring the user's request.
""".strip()

    try:
        response = client.chat.completions.create(
            model=llm_model,
            messages=[
                {"role": "system", "content": "You are a strategy scenario planner. Return strict JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=900,
        )
        parsed = _extract_json_object(response.choices[0].message.content)
    except Exception:
        return _heuristic_scenario_suggestion(instruction, baseline_inputs, objective=objective)

    by_lower = {str(k).lower(): k for k in baseline_inputs.keys()}
    deltas = {}
    rationale = {}
    for change in parsed.get('changes', []) if isinstance(parsed, dict) else []:
        if not isinstance(change, dict):
            continue
        raw_lever = str(change.get('lever') or '').strip()
        if not raw_lever:
            continue
        lever = raw_lever if raw_lever in baseline_inputs else by_lower.get(raw_lever.lower())
        if not lever:
            continue
        value = _safe_float(change.get('value'))
        if value is None:
            continue
        deltas[lever] = value
        rationale[lever] = str(change.get('rationale') or '').strip() or f"Adjusted {lever.replace('_', ' ')}."

    if not deltas:
        return _heuristic_scenario_suggestion(instruction, baseline_inputs, objective=objective)

    return {
        'label': str(parsed.get('label') or 'AI Suggested Scenario').strip() or 'AI Suggested Scenario',
        'summary': str(parsed.get('summary') or '').strip(),
        'deltas': deltas,
        'rationale': rationale,
    }


def _heuristic_wbs_suggestion(scorecard, instruction):
    comps = (scorecard or {}).get('component_scores') if isinstance(scorecard, dict) else {}
    comps = comps if isinstance(comps, dict) else {}
    tasks = [
        {
            'title': 'Kickoff alignment and success criteria',
            'owner_role': 'Program Manager',
            'priority': 'high',
            'timeline_days': 5,
            'depends_on': [],
            'rationale': 'Establishes shared scope and measurable outcomes early.',
        },
        {
            'title': 'Create execution cadence and dependency map',
            'owner_role': 'Delivery Lead',
            'priority': 'high',
            'timeline_days': 7,
            'depends_on': ['Kickoff alignment and success criteria'],
            'rationale': 'Converts strategic intent into an executable sequence.',
        },
    ]

    if float(comps.get('financial_health') or 0) < 70:
        tasks.append({
            'title': 'Run budget guardrail and ROI checkpoint',
            'owner_role': 'Finance Partner',
            'priority': 'high',
            'timeline_days': 7,
            'depends_on': ['Kickoff alignment and success criteria'],
            'rationale': 'Addresses financial risk and improves return confidence.',
        })
    if float(comps.get('market_position') or 0) < 70:
        tasks.append({
            'title': 'Validate customer value and market assumptions',
            'owner_role': 'Product Marketing',
            'priority': 'medium',
            'timeline_days': 10,
            'depends_on': ['Kickoff alignment and success criteria'],
            'rationale': 'Reduces go-to-market uncertainty before scaling execution.',
        })
    if float(comps.get('operational_efficiency') or 0) < 70:
        tasks.append({
            'title': 'Map process bottlenecks and automate handoffs',
            'owner_role': 'Operations Lead',
            'priority': 'medium',
            'timeline_days': 14,
            'depends_on': ['Create execution cadence and dependency map'],
            'rationale': 'Improves throughput and predictability for delivery.',
        })
    if float(comps.get('execution_readiness') or 0) < 70:
        tasks.append({
            'title': 'Staff critical roles and contingency owners',
            'owner_role': 'Program Manager',
            'priority': 'high',
            'timeline_days': 6,
            'depends_on': ['Create execution cadence and dependency map'],
            'rationale': 'Strengthens ownership and risk response capability.',
        })

    tasks.append({
        'title': 'Weekly risk review and mitigation updates',
        'owner_role': 'PMO',
        'priority': 'medium',
        'timeline_days': 30,
        'depends_on': ['Create execution cadence and dependency map'],
        'rationale': 'Maintains momentum and catches execution drift quickly.',
    })

    return {
        'name': 'AI Generated WBS',
        'description': str(instruction or '').strip() or 'Generated from scorecard drivers and risk profile.',
        'summary': 'Generated using component score priorities and risk hotspots.',
        'tasks': tasks[:12],
    }


def _generate_ai_wbs_suggestion(client, llm_model, scorecard, instruction):
    scorecard_payload = scorecard if isinstance(scorecard, dict) else {}
    prompt = f"""
You are generating a project WBS from a strategy scorecard.

Instruction:
{instruction or "Generate an actionable WBS from this scorecard."}

Scorecard context:
{json.dumps(scorecard_payload, indent=2)}

Return JSON only:
{{
  "name": "WBS title",
  "description": "one paragraph",
  "summary": "short summary",
  "tasks": [
    {{
      "title": "task title",
      "owner_role": "role",
      "priority": "high|medium|low",
      "timeline_days": 7,
      "depends_on": ["optional title references"],
      "rationale": "why this task matters"
    }}
  ]
}}

Rules:
- Return 5-14 tasks.
- Ensure dependencies are realistic and avoid circular references.
- Include at least one risk-mitigation task and one value-capture task.
""".strip()

    try:
        response = client.chat.completions.create(
            model=llm_model,
            messages=[
                {"role": "system", "content": "You are a WBS planning assistant. Return strict JSON only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.25,
            max_tokens=1200,
        )
        parsed = _extract_json_object(response.choices[0].message.content)
        if not isinstance(parsed, dict) or not isinstance(parsed.get('tasks'), list) or not parsed.get('tasks'):
            raise ValueError('invalid_wbs_response')
        return parsed
    except Exception:
        return _heuristic_wbs_suggestion(scorecard, instruction)


def _materialize_ai_wbs(wbs_payload):
    now = datetime.utcnow()
    tasks_in = wbs_payload.get('tasks') if isinstance(wbs_payload, dict) else []
    if not isinstance(tasks_in, list):
        tasks_in = []

    created = []
    by_title = {}
    for idx, raw in enumerate(tasks_in):
        if not isinstance(raw, dict):
            continue
        title = str(raw.get('title') or '').strip()
        if not title:
            continue
        task_id = f"task_{uuid.uuid4().hex[:10]}"
        owner = str(raw.get('owner_role') or raw.get('owner') or '').strip()
        priority = str(raw.get('priority') or '').strip().lower()
        if priority not in {'high', 'medium', 'low'}:
            priority = None
        timeline_days = raw.get('timeline_days')
        try:
            timeline_days = max(1, int(timeline_days)) if timeline_days is not None else None
        except Exception:
            timeline_days = None
        due_date = (now + timedelta(days=timeline_days)).date().isoformat() if timeline_days else None

        task = {
            'id': task_id,
            'title': title,
            'status': 'todo',
            'owner': owner,
            'due_date': due_date,
            'depends_on': [],
            'order': idx + 1,
            'external_refs': {},
        }
        if priority:
            task['priority'] = priority
        if timeline_days:
            task['timeline_days'] = timeline_days
        rationale = str(raw.get('rationale') or '').strip()
        if rationale:
            task['rationale'] = rationale
        created.append(task)
        by_title[title.lower()] = task_id

    for idx, raw in enumerate(tasks_in):
        if idx >= len(created) or not isinstance(raw, dict):
            continue
        raw_deps = raw.get('depends_on')
        if not isinstance(raw_deps, list):
            continue
        deps = []
        for dep in raw_deps:
            dep_title = str(dep or '').strip().lower()
            dep_id = by_title.get(dep_title)
            if dep_id and dep_id != created[idx]['id'] and dep_id not in deps:
                deps.append(dep_id)
        created[idx]['depends_on'] = deps

    return {
        'name': str(wbs_payload.get('name') or 'AI Generated WBS').strip() or 'AI Generated WBS',
        'description': str(wbs_payload.get('description') or '').strip(),
        'tasks': created,
    }


ALLOWED_WBS_STATUSES = {'todo', 'in_progress', 'blocked', 'done'}


def _normalize_wbs_task(raw_task):
    if not isinstance(raw_task, dict):
        return None

    task_id = str(raw_task.get('id') or uuid.uuid4().hex[:12]).strip()
    title = str(raw_task.get('title') or raw_task.get('name') or '').strip()
    if not title:
        return None

    status = str(raw_task.get('status') or 'todo').strip().lower()
    if status not in ALLOWED_WBS_STATUSES:
        status = 'todo'

    owner = str(raw_task.get('owner') or '').strip()
    due_date = str(raw_task.get('due_date') or '').strip() or None
    order = raw_task.get('order')
    try:
        order = int(order) if order is not None else None
    except Exception:
        order = None

    priority = str(raw_task.get('priority') or '').strip().lower() or None
    if priority not in {'high', 'medium', 'low'}:
        priority = None

    timeline_days = raw_task.get('timeline_days')
    try:
        timeline_days = int(timeline_days) if timeline_days is not None else None
    except Exception:
        timeline_days = None
    if timeline_days is not None and timeline_days < 1:
        timeline_days = None

    rationale = str(raw_task.get('rationale') or '').strip() or None

    depends_on = raw_task.get('depends_on')
    if not isinstance(depends_on, list):
        depends_on = []
    dep_ids = []
    for dep in depends_on:
        dep_id = str(dep or '').strip()
        if dep_id:
            dep_ids.append(dep_id)
    deduped_dep_ids = []
    seen = set()
    for dep_id in dep_ids:
        if dep_id in seen or dep_id == task_id:
            continue
        seen.add(dep_id)
        deduped_dep_ids.append(dep_id)

    external_refs = raw_task.get('external_refs') if isinstance(raw_task.get('external_refs'), dict) else {}
    jira_issue_key = str(
        raw_task.get('jira_issue_key')
        or external_refs.get('jira_issue_key')
        or ''
    ).strip()
    normalized_refs = {}
    if jira_issue_key:
        normalized_refs['jira_issue_key'] = jira_issue_key

    task = {
        'id': task_id,
        'title': title,
        'status': status,
        'owner': owner,
        'due_date': due_date,
        'depends_on': deduped_dep_ids,
        'order': order,
        'external_refs': normalized_refs,
    }
    if priority:
        task['priority'] = priority
    if timeline_days:
        task['timeline_days'] = timeline_days
    if rationale:
        task['rationale'] = rationale
    return task


def _normalize_project_wbs(payload, existing=None):
    base = existing if isinstance(existing, dict) else {}
    now = datetime.utcnow().isoformat()

    if isinstance(payload, dict) and isinstance(payload.get('project_wbs'), dict):
        payload = payload.get('project_wbs')
    elif not isinstance(payload, dict):
        payload = {}

    incoming_tasks = payload.get('tasks')
    if not isinstance(incoming_tasks, list):
        incoming_tasks = []

    tasks = []
    for idx, raw_task in enumerate(incoming_tasks):
        task = _normalize_wbs_task(raw_task)
        if not task:
            continue
        if task.get('order') is None:
            task['order'] = idx + 1
        tasks.append(task)

    # Ensure dependency ids refer to tasks in this WBS.
    valid_ids = {t['id'] for t in tasks}
    for task in tasks:
        task['depends_on'] = [dep for dep in task.get('depends_on', []) if dep in valid_ids]

    return {
        'version': int(base.get('version') or payload.get('version') or 1),
        'name': str(payload.get('name') or base.get('name') or 'Execution WBS').strip(),
        'description': str(payload.get('description') or base.get('description') or '').strip(),
        'tasks': tasks,
        'created_at': base.get('created_at') or now,
        'updated_at': now,
    }


def _wbs_dependency_count(project_wbs):
    tasks = project_wbs.get('tasks') if isinstance(project_wbs, dict) else []
    if not isinstance(tasks, list):
        return 0
    return sum(len(t.get('depends_on', [])) for t in tasks if isinstance(t, dict))


# ============================================================
# DETERMINISTIC SCORING ENGINE
# ============================================================

# How each lever category affects component scores (pattern -> {component: sensitivity})
_LEVER_SENSITIVITY = {
    'budget':      {'financial_health': 0.50, 'execution_readiness': 0.20},
    'investment':  {'financial_health': 0.40, 'market_position': 0.15},
    'cost':        {'financial_health': 0.40, 'operational_efficiency': 0.35},
    'price':       {'financial_health': 0.30, 'market_position': 0.25},
    'revenue':     {'financial_health': 0.40, 'market_position': 0.20},
    'timeline':    {'execution_readiness': 0.45, 'market_position': 0.10},
    'month':       {'execution_readiness': 0.35},
    'penetrat':    {'market_position': 0.45},
    'customer':    {'market_position': 0.30, 'financial_health': 0.10},
    'efficienc':   {'operational_efficiency': 0.45},
    'utilizat':    {'operational_efficiency': 0.35},
    'margin':      {'financial_health': 0.40, 'operational_efficiency': 0.20},
    'growth':      {'market_position': 0.35, 'financial_health': 0.15},
    'cac':         {'financial_health': 0.30, 'market_position': 0.15},
}

_COMPONENT_WEIGHTS = {
    'financial_health': 0.30,
    'operational_efficiency': 0.25,
    'market_position': 0.25,
    'execution_readiness': 0.20,
}

# Fields that are outputs, not editable inputs
_OUTPUT_FIELDS = {
    'jaspen_score', 'score_category', 'component_scores', 'financial_impact',
    'analysis_id', 'user_id', 'timestamp', 'project_description',
    'key_insights', 'top_risks', 'recommendations', 'project_name',
    'risks', 'compat', 'inputs', 'id', 'label', 'thread_id', 'scenario_id',
    'overall_score', 'scores', 'name', 'status', 'framework_id',
}


def _get_lever_sensitivities(key):
    """Map a lever key to component sensitivities via pattern matching."""
    key_lower = key.lower()
    sensitivities = {}
    for pattern, mapping in _LEVER_SENSITIVITY.items():
        if pattern in key_lower:
            for comp, weight in mapping.items():
                sensitivities[comp] = sensitivities.get(comp, 0) + weight
    # Fallback: spread small uniform effect if no pattern matched
    if not sensitivities:
        for comp in _COMPONENT_WEIGHTS:
            sensitivities[comp] = 0.08
    return sensitivities


def _parse_currency(val):
    """Parse '$15.2M' or '250%' to a float. Returns None on failure."""
    if val is None:
        return None
    s = str(val).replace('$', '').replace(',', '').strip()
    multiplier = 1.0
    if s.upper().endswith('B'):
        multiplier = 1e9; s = s[:-1]
    elif s.upper().endswith('M'):
        multiplier = 1e6; s = s[:-1]
    elif s.upper().endswith('K'):
        multiplier = 1e3; s = s[:-1]
    elif s.endswith('%'):
        s = s[:-1]   # keep multiplier = 1 (value IS the percentage number)
    try:
        return float(s) * multiplier
    except (ValueError, TypeError):
        return None


def _fmt_currency(num):
    """Format a number back to a currency string."""
    if num is None:
        return 'N/A'
    if abs(num) >= 1e9:
        return f"${num/1e9:.1f}B"
    if abs(num) >= 1e6:
        return f"${num/1e6:.1f}M"
    if abs(num) >= 1e3:
        return f"${num/1e3:.1f}K"
    return f"${num:,.0f}"


def _extract_baseline_inputs(baseline):
    """Pull numeric lever values out of a baseline scorecard."""
    inputs = {}
    # Walk inputs -> compat -> top-level, first-seen wins
    for source in (baseline.get('inputs') or {}, baseline.get('compat') or {}, baseline):
        if not isinstance(source, dict):
            continue
        for key, val in source.items():
            if key in inputs or key in _OUTPUT_FIELDS or key.startswith('_'):
                continue
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                inputs[key] = val
    return inputs


def _compute_scenario_scorecard(baseline, deltas, baseline_inputs):
    """
    Deterministic scenario scoring.
    Takes baseline scorecard + lever deltas -> returns a new scorecard.
    """
    _defaults = {
        'financial_health': 50.0,
        'operational_efficiency': 50.0,
        'market_position': 50.0,
        'execution_readiness': 50.0,
    }

    # Start from baseline component scores, fill any missing with defaults
    base_comps = baseline.get('component_scores') or {}
    components = {k: float(base_comps.get(k, _defaults[k])) for k in _defaults}

    financial_factor = 1.0   # cumulative multiplier for financial metrics

    for key, new_val in (deltas or {}).items():
        try:
            new_val = float(new_val)
        except (ValueError, TypeError):
            continue

        base_val = float(baseline_inputs.get(key, 0) or 0)

        # --- compute relative change, clamped to [-1, +1] ---
        if base_val == 0:
            if new_val == 0:
                continue
            # Pick a reference scale by lever category
            k = key.lower()
            ref = 100_000 if any(p in k for p in ('budget','invest','cost','price','revenue','value')) else \
                  100      if any(p in k for p in ('percent','rate','margin','growth','penetrat'))        else 1_000
            pct_change = (new_val - base_val) / ref
        else:
            pct_change = (new_val - base_val) / abs(base_val)
        pct_change = max(-1.0, min(1.0, pct_change))

        # --- accumulate financial factor ---
        k = key.lower()
        if any(p in k for p in ('budget', 'invest', 'revenue')):
            financial_factor += pct_change * 0.25
        elif any(p in k for p in ('cost', 'cac')):
            financial_factor -= pct_change * 0.20
        elif 'price' in k:
            financial_factor += pct_change * 0.15

        # --- adjust component scores (max +-15 pts per lever) ---
        for comp, sensitivity in _get_lever_sensitivities(key).items():
            if comp in components:
                components[comp] = max(0.0, min(100.0, components[comp] + pct_change * sensitivity * 15.0))

    # Clamp financial factor to sane range
    financial_factor = max(0.5, min(2.0, financial_factor))

    # Round components
    components = {k: round(v, 1) for k, v in components.items()}

    # Weighted overall score
    overall = sum(components.get(k, 0) * w for k, w in _COMPONENT_WEIGHTS.items())
    overall_int = max(0, min(100, int(round(overall))))

    category = 'Excellent' if overall_int >= 80 else 'Good' if overall_int >= 60 else 'Fair' if overall_int >= 40 else 'At Risk'

    # --- adjust financial-impact strings from baseline ---
    base_fin = baseline.get('financial_impact') or {}
    adj_fin = {}
    for field in ('ebitda_at_risk', 'potential_loss', 'roi_opportunity', 'projected_ebitda'):
        raw = base_fin.get(field)
        num = _parse_currency(raw)
        if num is None:
            adj_fin[field] = raw if raw else 'N/A'
            continue
        # Risk/loss fields move inversely to financial health
        adjusted = num / financial_factor if field in ('ebitda_at_risk', 'potential_loss') else num * financial_factor
        # Preserve format hint
        if raw and '%' in str(raw):
            adj_fin[field] = f"{adjusted:.1f}%"
        else:
            adj_fin[field] = _fmt_currency(adjusted)

    # Synthetic numeric fields the frontend ScenarioModeler reads directly
    proj_num = _parse_currency(adj_fin.get('projected_ebitda'))
    base_proj = _parse_currency(base_fin.get('projected_ebitda'))
    if proj_num is not None and base_proj is not None:
        adj_fin['npv'] = round(proj_num - base_proj, 2)

    roi_num = _parse_currency(adj_fin.get('roi_opportunity'))
    if roi_num is not None:
        adj_fin['irr'] = round(roi_num, 1)

    # Synthetic payback from budget/investment lever if present
    for lk in (deltas or {}):
        if 'budget' in lk.lower() or 'invest' in lk.lower():
            inv = float((deltas or {}).get(lk, 0) or 0)
            if inv > 0 and proj_num and proj_num > 0:
                adj_fin['payback_months'] = round((inv / proj_num) * 12, 1)
            break

    adj_fin['time_to_market_impact'] = base_fin.get('time_to_market_impact', 'N/A')

    # Build result, preserving narrative fields from baseline
    result = {
        'jaspen_score': overall_int,
        'score_category': category,
        'component_scores': components,
        'financial_impact': adj_fin,
        'inputs': deltas,
    }
    for narrative_key in ('project_name', 'project_description', 'key_insights', 'top_risks', 'recommendations'):
        if narrative_key in baseline:
            result[narrative_key] = baseline[narrative_key]

    return result


# ============================================================
# AI-ASSISTED STRATEGY ROUTES
# ============================================================

@strategy_bp.route('/threads/<thread_id>/ai-scenario', methods=['POST'])
@jwt_required()
def create_ai_scenario(thread_id):
    """
    Generate AI-suggested scenario lever adjustments for a thread.
    Optional commit mode writes the suggestion as a real scenario row.
    """
    try:
        user_id = get_jwt_identity()
        user, _, access_err = _require_tool_access(user_id, 'scenario_create', access='write')
        if access_err:
            return access_err

        payload = request.get_json() or {}
        instruction = str(
            payload.get('instruction')
            or payload.get('message')
            or payload.get('prompt')
            or ''
        ).strip()
        requested_deltas = payload.get('deltas')

        model_selection, model_error = _resolve_user_model_selection(
            user,
            requested_model_type=payload.get('model_type'),
        )
        if model_error:
            return jsonify(model_error), 403

        all_data, thread_data, baseline, baseline_inputs, _session, stored_objective = _resolve_thread_baseline(user_id, thread_id)
        if not isinstance(baseline, dict):
            return jsonify({'error': 'No baseline scorecard found for this thread.'}), 404
        if not isinstance(baseline_inputs, dict) or not baseline_inputs:
            return jsonify({'error': 'No baseline levers found for this thread.'}), 400

        objective_supplied = any(key in payload for key in ('strategy_objective', 'objective'))
        strategy_objective = (
            _normalize_strategy_objective(payload.get('strategy_objective') or payload.get('objective'))
            if objective_supplied
            else _normalize_strategy_objective(stored_objective)
        )
        if thread_data.get('strategy_objective') != strategy_objective:
            thread_data['strategy_objective'] = strategy_objective
            all_data[thread_id] = thread_data
            _save_scenarios(user_id, all_data)

        manual_deltas = _sanitize_deltas(baseline_inputs, requested_deltas)
        if not instruction and not manual_deltas:
            return jsonify({'error': 'Provide instruction/message or deltas for scenario generation.'}), 400

        if manual_deltas:
            suggestion = {
                'label': str(payload.get('label') or 'AI Scenario (Modified)').strip() or 'AI Scenario (Modified)',
                'summary': str(
                    payload.get('summary')
                    or f'Scenario built from your manual lever adjustments ({strategy_objective} objective).'
                ).strip(),
                'deltas': manual_deltas,
                'rationale': {
                    key: f"Set by user adjustment from {baseline_inputs.get(key)} to {value}."
                    for key, value in manual_deltas.items()
                },
            }
        else:
            client = get_openai_client()
            suggestion = _generate_ai_scenario_suggestion(
                client,
                model_selection['llm_model'],
                instruction=instruction,
                baseline_inputs=baseline_inputs,
                objective=strategy_objective,
            )

        deltas = suggestion.get('deltas') if isinstance(suggestion, dict) else {}
        deltas = _sanitize_deltas(baseline_inputs, deltas)
        if not deltas:
            return jsonify({'error': 'Unable to generate lever adjustments from request.'}), 422

        label_override = str(payload.get('label') or '').strip()
        preview = _compute_scenario_scorecard(baseline, deltas, baseline_inputs)
        preview['analysis_id'] = f"preview_{uuid.uuid4().hex[:10]}"
        preview['thread_id'] = thread_id
        preview['label'] = label_override or str(suggestion.get('label') or 'AI Suggested Scenario')

        response_payload = {
            'success': True,
            'thread_id': thread_id,
            'model_type': model_selection['model_type'],
            'strategy_objective': strategy_objective,
            'objective_options': list(STRATEGY_OBJECTIVE_OPTIONS),
            'suggestion': {
                'label': preview['label'],
                'summary': str(suggestion.get('summary') or '').strip(),
                'deltas': deltas,
                'rationale': suggestion.get('rationale') if isinstance(suggestion.get('rationale'), dict) else {},
            },
            'preview_scorecard': preview,
            'lever_context': _build_lever_context(baseline_inputs, deltas),
        }

        commit = bool(payload.get('commit') or payload.get('accept'))
        if commit:
            scenario_id = str(payload.get('scenario_id') or uuid.uuid4())
            scenarios = thread_data.setdefault('scenarios', {})
            existing = scenarios.get(scenario_id) if isinstance(scenarios, dict) else None
            if not isinstance(existing, dict):
                existing = {
                    'scenario_id': scenario_id,
                    'thread_id': thread_id,
                    'created_at': datetime.utcnow().isoformat(),
                }
            existing['label'] = preview['label']
            existing['deltas'] = deltas
            existing['result'] = {
                **preview,
                'analysis_id': scenario_id,
                'scenario_id': scenario_id,
                'label': preview['label'],
            }
            existing['updated_at'] = datetime.utcnow().isoformat()
            existing['ai_rationale'] = response_payload['suggestion']['rationale']
            existing['ai_summary'] = response_payload['suggestion']['summary']
            existing['ai_instruction'] = instruction or None
            existing['strategy_objective'] = strategy_objective

            scenarios[scenario_id] = existing
            thread_data['scenarios'] = scenarios
            thread_data['strategy_objective'] = strategy_objective
            all_data[thread_id] = thread_data
            _save_scenarios(user_id, all_data)

            response_payload['scenario_id'] = scenario_id
            response_payload['scenario'] = existing
            response_payload['committed'] = True
        else:
            response_payload['committed'] = False

        return jsonify(response_payload), 200
    except Exception as e:
        print(f"[create_ai_scenario] {e}")
        return jsonify({'error': str(e)}), 500


@strategy_bp.route('/threads/<thread_id>/ai-wbs', methods=['POST'])
@jwt_required()
def generate_ai_wbs(thread_id):
    """
    Generate an AI-driven WBS from baseline/adopted scorecard context.
    `commit=true` writes to thread WBS; otherwise returns a preview.
    """
    try:
        user_id = get_jwt_identity()
        user, plan_key, read_access_err = _require_tool_access(user_id, 'wbs_read', access='read')
        if read_access_err:
            return read_access_err

        payload = request.get_json() or {}
        commit = bool(payload.get('commit', True))
        if commit:
            _, plan_key, write_access_err = _require_tool_access(user_id, 'wbs_write', access='write')
            if write_access_err:
                return write_access_err

        model_selection, model_error = _resolve_user_model_selection(
            user,
            requested_model_type=payload.get('model_type'),
        )
        if model_error:
            return jsonify(model_error), 403

        instruction = str(
            payload.get('instruction')
            or payload.get('message')
            or payload.get('prompt')
            or ''
        ).strip()

        all_data, thread_data, baseline, _baseline_inputs, session, _strategy_objective = _resolve_thread_baseline(user_id, thread_id)
        scenarios = thread_data.get('scenarios') if isinstance(thread_data.get('scenarios'), dict) else {}
        adopted_id = thread_data.get('adopted_scenario_id')
        current_scorecard = baseline if isinstance(baseline, dict) else None
        if adopted_id and adopted_id in scenarios and isinstance((scenarios.get(adopted_id) or {}).get('result'), dict):
            current_scorecard = scenarios[adopted_id]['result']
        if current_scorecard is None and isinstance(session, dict) and isinstance(session.get('result'), dict):
            current_scorecard = session.get('result')
        if not isinstance(current_scorecard, dict):
            return jsonify({'error': 'No scorecard context found for this thread.'}), 404

        client = get_openai_client()
        raw_wbs = _generate_ai_wbs_suggestion(
            client,
            model_selection['llm_model'],
            scorecard=current_scorecard,
            instruction=instruction,
        )
        materialized = _materialize_ai_wbs(raw_wbs)
        normalized_wbs = _normalize_project_wbs({'project_wbs': materialized}, existing=None)
        normalized_wbs['ai_generated'] = True
        normalized_wbs['ai_generated_at'] = datetime.utcnow().isoformat()
        normalized_wbs['ai_summary'] = str(raw_wbs.get('summary') or '').strip()

        limits = get_wbs_limits_for_plan(plan_key)
        max_tasks = limits.get('max_tasks_per_wbs')
        max_deps = limits.get('max_dependencies_per_wbs')
        task_count = len(normalized_wbs.get('tasks', []))
        dep_count = _wbs_dependency_count(normalized_wbs)

        if isinstance(max_tasks, int) and task_count > max_tasks:
            return jsonify({
                'error': 'Generated WBS exceeds task limit for current plan',
                'code': 'wbs_task_limit_reached',
                'plan_key': plan_key,
                'max_tasks_per_wbs': max_tasks,
                'task_count': task_count,
            }), 403

        if isinstance(max_deps, int) and dep_count > max_deps:
            return jsonify({
                'error': 'Generated WBS exceeds dependency limit for current plan',
                'code': 'wbs_dependency_limit_reached',
                'plan_key': plan_key,
                'max_dependencies_per_wbs': max_deps,
                'dependency_count': dep_count,
            }), 403

        if commit:
            thread_data['project_wbs'] = normalized_wbs
            all_data[thread_id] = thread_data
            _save_scenarios(user_id, all_data)

        return jsonify({
            'success': True,
            'thread_id': thread_id,
            'committed': commit,
            'project_wbs': normalized_wbs,
            'model_type': model_selection['model_type'],
            'limits': limits,
        }), 200
    except Exception as e:
        print(f"[generate_ai_wbs] {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================
# SCENARIO CRUD ROUTES
# ============================================================

@strategy_bp.route('/threads/<thread_id>/scenarios', methods=['POST'])
@jwt_required()
def create_scenario(thread_id):
    """Create a scenario. Stores baseline on first call for this thread."""
    try:
        user_id = get_jwt_identity()
        _, plan_key, access_err = _require_tool_access(user_id, 'scenario_create', access='write')
        if access_err:
            return access_err

        data = request.get_json() or {}

        all_data = _load_scenarios(user_id)
        if thread_id not in all_data:
            all_data[thread_id] = _thread_entry()
        td = all_data[thread_id]

        max_scenarios = get_scenario_limits_for_plan(plan_key).get('max_scenarios_per_thread')
        current_count = len(td.get('scenarios', {}))
        if isinstance(max_scenarios, int) and current_count >= max_scenarios:
            return jsonify({
                'error': 'Scenario limit reached for current plan',
                'code': 'scenario_limit_reached',
                'plan_key': plan_key,
                'thread_id': thread_id,
                'max_scenarios_per_thread': max_scenarios,
            }), 403

        # Persist baseline the first time it arrives
        baseline = data.get('baseline')
        if baseline and not td.get('baseline'):
            td['baseline'] = baseline
            td['baseline_inputs'] = _extract_baseline_inputs(baseline)

        scenario_id = str(uuid.uuid4())
        td['scenarios'][scenario_id] = {
            'scenario_id': scenario_id,
            'thread_id': thread_id,
            'label': data.get('label', 'Scenario'),
            'deltas': data.get('deltas', {}),
            'result': None,
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat(),
        }

        _save_scenarios(user_id, all_data)
        return jsonify({
            'scenario_id': scenario_id,
            'thread_id': thread_id,
            'label': td['scenarios'][scenario_id]['label'],
            'created_at': td['scenarios'][scenario_id]['created_at'],
        }), 201

    except Exception as e:
        print(f"[create_scenario] {e}")
        return jsonify({'error': str(e)}), 500


@strategy_bp.route('/threads/<thread_id>/scenarios', methods=['GET'])
@jwt_required()
def list_scenarios(thread_id):
    """List scenarios for a thread, with pagination."""
    try:
        user_id = get_jwt_identity()
        _, _, access_err = _require_tool_access(user_id, 'scenario_create', access='read')
        if access_err:
            return access_err

        td = _load_scenarios(user_id).get(thread_id, {})
        scenarios = sorted(td.get('scenarios', {}).values(),
                           key=lambda s: s.get('created_at', ''), reverse=True)

        limit  = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))

        return jsonify({
            'scenarios': scenarios[offset:offset + limit],
            'total': len(scenarios),
        }), 200

    except Exception as e:
        print(f"[list_scenarios] {e}")
        return jsonify({'error': str(e)}), 500


@strategy_bp.route('/scenarios/<scenario_id>', methods=['PATCH'])
@jwt_required()
def update_scenario(scenario_id):
    """Update label / deltas. Invalidates cached result if deltas change."""
    try:
        user_id  = get_jwt_identity()
        _, _, access_err = _require_tool_access(user_id, 'scenario_create', access='write')
        if access_err:
            return access_err

        thread_id = request.args.get('thread_id')
        if not thread_id:
            return jsonify({'error': 'thread_id query param required'}), 400

        data = request.get_json() or {}
        all_data = _load_scenarios(user_id)
        td = all_data.get(thread_id, {})
        scenario = td.get('scenarios', {}).get(scenario_id)
        if not scenario:
            return jsonify({'error': 'Scenario not found'}), 404

        if 'label' in data:
            scenario['label'] = data['label']
        if 'deltas' in data:
            scenario['deltas'] = data['deltas']
            scenario['result'] = None   # must re-apply after delta change

        scenario['updated_at'] = datetime.utcnow().isoformat()
        _save_scenarios(user_id, all_data)
        return jsonify(scenario), 200

    except Exception as e:
        print(f"[update_scenario] {e}")
        return jsonify({'error': str(e)}), 500


@strategy_bp.route('/scenarios/<scenario_id>', methods=['DELETE'])
@jwt_required()
def delete_scenario(scenario_id):
    """Delete a scenario. Clears adoption if it was the adopted one."""
    try:
        user_id  = get_jwt_identity()
        _, _, access_err = _require_tool_access(user_id, 'scenario_delete', access='write')
        if access_err:
            return access_err

        thread_id = request.args.get('thread_id')
        if not thread_id:
            return jsonify({'error': 'thread_id query param required'}), 400

        all_data = _load_scenarios(user_id)
        td = all_data.get(thread_id, {})
        if scenario_id not in td.get('scenarios', {}):
            return jsonify({'error': 'Scenario not found'}), 404

        del td['scenarios'][scenario_id]
        if td.get('adopted_scenario_id') == scenario_id:
            td['adopted_scenario_id'] = None

        _save_scenarios(user_id, all_data)
        return jsonify({'success': True}), 200

    except Exception as e:
        print(f"[delete_scenario] {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================
# SCENARIO APPLY / ADOPT
# ============================================================

@strategy_bp.route('/scenarios/<scenario_id>/apply', methods=['POST'])
@jwt_required()
def apply_scenario(scenario_id):
    """
    Deterministically score a scenario against the stored baseline.
    Caches the result on the scenario object.
    """
    try:
        user_id   = get_jwt_identity()
        _, _, access_err = _require_tool_access(user_id, 'scenario_apply', access='write')
        if access_err:
            return access_err

        thread_id = request.args.get('thread_id')
        if not thread_id:
            return jsonify({'error': 'thread_id query param required'}), 400

        all_data = _load_scenarios(user_id)
        td = all_data.get(thread_id, {})
        scenario = td.get('scenarios', {}).get(scenario_id)
        if not scenario:
            return jsonify({'error': 'Scenario not found'}), 404

        baseline = td.get('baseline')
        if not baseline:
            return jsonify({'error': 'No baseline stored for this thread. Ensure baseline is sent with the first createScenario call.'}), 400

        result = _compute_scenario_scorecard(baseline, scenario['deltas'], td.get('baseline_inputs', {}))
        result['analysis_id']  = scenario_id
        result['scenario_id']  = scenario_id
        result['thread_id']    = thread_id
        result['label']        = scenario['label']

        # Cache
        scenario['result'] = result
        scenario['updated_at'] = datetime.utcnow().isoformat()
        _save_scenarios(user_id, all_data)

        # Return in the shape ScenarioModeler.normalizeApplied() expects
        return jsonify({
            'scenario_id': scenario_id,
            'scenario': {
                'scorecard': result,
                'scenario_id': scenario_id,
                'label': scenario['label'],
            },
            'jaspen_score': result['jaspen_score'],
            'component_scores': result['component_scores'],
            'financial_impact': result['financial_impact'],
            'analysis_id': scenario_id,
        }), 200

    except Exception as e:
        print(f"[apply_scenario] {e}")
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@strategy_bp.route('/scenarios/<scenario_id>/adopt', methods=['POST'])
@jwt_required()
def adopt_scenario(scenario_id):
    """Mark a scenario as the adopted (current) analysis for its thread."""
    try:
        user_id   = get_jwt_identity()
        _, _, access_err = _require_tool_access(user_id, 'scenario_adopt', access='write')
        if access_err:
            return access_err

        data      = request.get_json() or {}
        thread_id = data.get('thread_id') or request.args.get('thread_id')

        all_data = _load_scenarios(user_id)

        if thread_id:
            td = all_data.get(thread_id, {})
            if scenario_id not in td.get('scenarios', {}):
                return jsonify({'error': 'Scenario not found'}), 404
            td['adopted_scenario_id'] = scenario_id
        else:
            # Search all threads
            found = False
            for tid, td in all_data.items():
                if scenario_id in td.get('scenarios', {}):
                    td['adopted_scenario_id'] = scenario_id
                    found = True
                    break
            if not found:
                return jsonify({'error': 'Scenario not found in any thread'}), 404

        _save_scenarios(user_id, all_data)
        return jsonify({'success': True, 'adopted_scenario_id': scenario_id}), 200

    except Exception as e:
        print(f"[adopt_scenario] {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================
# WBS ROUTES
# ============================================================

@strategy_bp.route('/threads/<thread_id>/wbs', methods=['GET'])
@jwt_required()
def get_thread_wbs(thread_id):
    try:
        user_id = get_jwt_identity()
        _, plan_key, access_err = _require_tool_access(user_id, 'wbs_read', access='read')
        if access_err:
            return access_err

        all_data = _load_scenarios(user_id)
        td = all_data.get(thread_id, {}) if isinstance(all_data, dict) else {}
        project_wbs = td.get('project_wbs') if isinstance(td, dict) else None

        return jsonify({
            'thread_id': thread_id,
            'project_wbs': project_wbs,
            'limits': get_wbs_limits_for_plan(plan_key),
        }), 200
    except Exception as e:
        print(f"[get_thread_wbs] {e}")
        return jsonify({'error': str(e)}), 500


@strategy_bp.route('/threads/<thread_id>/wbs', methods=['PUT', 'PATCH'])
@jwt_required()
def upsert_thread_wbs(thread_id):
    try:
        user_id = get_jwt_identity()
        _, plan_key, access_err = _require_tool_access(user_id, 'wbs_write', access='write')
        if access_err:
            return access_err

        payload = request.get_json() or {}

        all_data = _load_scenarios(user_id)
        if thread_id not in all_data:
            all_data[thread_id] = _thread_entry()
        td = all_data[thread_id]

        existing_wbs = td.get('project_wbs') if isinstance(td.get('project_wbs'), dict) else None
        normalized_wbs = _normalize_project_wbs(payload, existing=existing_wbs)

        limits = get_wbs_limits_for_plan(plan_key)
        max_tasks = limits.get('max_tasks_per_wbs')
        max_deps = limits.get('max_dependencies_per_wbs')
        task_count = len(normalized_wbs.get('tasks', []))
        dep_count = _wbs_dependency_count(normalized_wbs)

        if isinstance(max_tasks, int) and task_count > max_tasks:
            return jsonify({
                'error': 'WBS task limit reached for current plan',
                'code': 'wbs_task_limit_reached',
                'plan_key': plan_key,
                'max_tasks_per_wbs': max_tasks,
                'task_count': task_count,
            }), 403

        if isinstance(max_deps, int) and dep_count > max_deps:
            return jsonify({
                'error': 'WBS dependency limit reached for current plan',
                'code': 'wbs_dependency_limit_reached',
                'plan_key': plan_key,
                'max_dependencies_per_wbs': max_deps,
                'dependency_count': dep_count,
            }), 403

        sync_result = None
        profile = get_thread_sync_profile(user_id, thread_id)
        jira_selected = isinstance(profile.get('connector_ids'), list) and 'jira_sync' in [
            str(item or '').strip().lower() for item in profile.get('connector_ids', [])
        ]
        if jira_selected or str(profile.get('sync_mode') or '').strip().lower() in ('push', 'two_way'):
            try:
                sync_result = sync_wbs_to_jira(
                    user_id=user_id,
                    thread_id=thread_id,
                    project_wbs=normalized_wbs,
                    thread_sync_profile=profile,
                )
                if isinstance(sync_result, dict) and isinstance(sync_result.get('project_wbs'), dict):
                    normalized_wbs = sync_result.get('project_wbs')
            except Exception as sync_error:
                sync_result = {
                    'success': False,
                    'skipped': False,
                    'errors': [{'error': str(sync_error)}],
                }

        td['project_wbs'] = normalized_wbs
        all_data[thread_id] = td
        _save_scenarios(user_id, all_data)

        return jsonify({
            'success': True,
            'thread_id': thread_id,
            'project_wbs': normalized_wbs,
            'limits': limits,
            'jira_sync': sync_result,
        }), 200
    except Exception as e:
        print(f"[upsert_thread_wbs] {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================
# THREAD BUNDLE  (hydrates the Scenarios tab + ScoreDashboard)
# ============================================================

@strategy_bp.route('/threads/<thread_id>/bundle', methods=['GET'])
@jwt_required()
def get_thread_bundle(thread_id):
    """
    Return everything the frontend needs to render the Scenarios tab:
      baseline_scorecard, current_scorecard, scenarios[], scenario_levers[].
    """
    try:
        user_id = get_jwt_identity()
        scn_limit = int(request.args.get('scn_limit', 50))

        all_data = _load_scenarios(user_id)
        td = all_data.get(thread_id, {})
        if not isinstance(td, dict):
            td = {}
        sessions = load_user_sessions(user_id) or {}
        _, session = _resolve_session_entry(sessions, thread_id)

        baseline = td.get('baseline')
        scenarios_dict = td.get('scenarios', {})
        adopted_id = td.get('adopted_scenario_id')
        session_result = session.get('result') if isinstance(session, dict) and isinstance(session.get('result'), dict) else None
        strategy_objective = _normalize_strategy_objective(
            (session.get('strategy_objective') if isinstance(session, dict) else None)
            or td.get('strategy_objective')
        )
        td['strategy_objective'] = strategy_objective
        baseline_inputs = td.get('baseline_inputs') or (
            session.get('baseline_inputs') if isinstance(session, dict) and isinstance(session.get('baseline_inputs'), dict) else {}
        )
        if baseline is None and session_result:
            baseline = session_result
        if not isinstance(scenarios_dict, dict):
            scenarios_dict = {}
        if not isinstance(baseline_inputs, dict):
            baseline_inputs = {}

        # Sorted scenario list
        scenarios_list = sorted(scenarios_dict.values(),
                                key=lambda s: s.get('created_at', ''), reverse=True)[:scn_limit]

        # Current scorecard = adopted scenario result if set, else baseline
        current_scorecard = baseline
        if adopted_id and adopted_id in scenarios_dict:
            current_scorecard = scenarios_dict[adopted_id].get('result') or baseline

        # Build scenario_levers from baseline inputs
        scenario_levers = []
        for key, val in baseline_inputs.items():
            if not isinstance(val, (int, float)):
                continue
            k = key.lower()
            ltype = ('currency'    if any(p in k for p in ('budget','invest','cost','price','revenue','value'))
                     else 'months'     if any(p in k for p in ('month','timeline','period','duration'))
                     else 'percentage' if any(p in k for p in ('percent','rate','margin','growth'))
                     else 'number')
            scenario_levers.append({
                'key': key,
                'label': key.replace('_', ' ').title(),
                'current': val,
                'value': val,
                'type': ltype,
                'display_multiplier': 1,
            })

        return jsonify({
            'thread': {
                'id': thread_id,
                'session_id': thread_id,
                'name': (session or {}).get('name') if isinstance(session, dict) else None,
                'strategy_objective': strategy_objective,
                'status': (session or {}).get('status') if isinstance(session, dict) else 'in_progress',
            },
            'messages': (session.get('chat_history') if isinstance(session, dict) and isinstance(session.get('chat_history'), list) else []),
            'baseline_scorecard': baseline,
            'current_scorecard': current_scorecard,
            'scenarios': scenarios_list,
            'scenario_levers': scenario_levers,
            'adopted_scenario_id': adopted_id,
            'project_wbs': td.get('project_wbs'),
            'status': (session or {}).get('status') if isinstance(session, dict) else 'in_progress',
            'result': session_result,
            'strategy_objective': strategy_objective,
            'objective_options': list(STRATEGY_OBJECTIVE_OPTIONS),
        }), 200

    except Exception as e:
        print(f"[get_thread_bundle] {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================
# THREAD-LEVEL ADOPT  (used by ThreadEditModal)
# ============================================================

@strategy_bp.route('/threads/<thread_id>/adopt', methods=['POST'])
@jwt_required()
def adopt_analysis_for_thread(thread_id):
    """
    Adopt an analysis (baseline or scenario) as current for the thread.
    If analysis_id matches a scenario, that scenario becomes adopted;
    otherwise adoption is cleared (baseline becomes current).
    """
    try:
        user_id = get_jwt_identity()
        _, _, access_err = _require_tool_access(user_id, 'scenario_adopt', access='write')
        if access_err:
            return access_err

        data    = request.get_json() or {}
        analysis_id = data.get('analysis_id')
        if not analysis_id:
            return jsonify({'error': 'analysis_id required'}), 400

        all_data = _load_scenarios(user_id)
        if thread_id not in all_data:
            all_data[thread_id] = _thread_entry()

        td = all_data[thread_id]
        td['adopted_scenario_id'] = analysis_id if analysis_id in td.get('scenarios', {}) else None

        _save_scenarios(user_id, all_data)
        return jsonify({'success': True, 'adopted_analysis_id': analysis_id}), 200

    except Exception as e:
        print(f"[adopt_analysis_for_thread] {e}")
        return jsonify({'error': str(e)}), 500
