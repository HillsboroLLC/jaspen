from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
import openai
import json
import os
import re
import time
from datetime import datetime
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
from .sessions import load_user_sessions, save_user_sessions

market_iq_bp = Blueprint('market_iq', __name__)

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
        print(f"[market_iq.analyze] failed reading sessions for user {user_id}: {e}")
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


def _generate_market_iq_scorecard(client, project_description, llm_model):
    """Run the existing LLM scoring flow and return parsed scorecard JSON."""
    analysis_prompt = f"""
You are a Jaspen strategy analyst specializing in commercialization strategy and financial impact assessment. Analyze the following project and provide a comprehensive strategy score and breakdown.

Project Description: {project_description}

Please provide your analysis in the following JSON format:

{{
    "market_iq_score": <number between 0-100>,
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


@market_iq_bp.route('/analyze', methods=['POST'])
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

        thread_id = data.get('thread_id') or request.headers.get('X-Session-ID')
        project_name = data.get('name') or data.get('project_name') or 'Jaspen Project'
        framework_id = data.get('framework_id')
        project_description = (data.get('description') or '').strip()

        # Build analysis input from thread conversation when thread_id is provided.
        conversation_history = []
        transcript = ''
        if thread_id:
            conversation_history = _load_thread_conversation(current_user_id, str(thread_id))
            transcript = _conversation_to_transcript(conversation_history).strip()

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
        analysis_result = _generate_market_iq_scorecard(
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
                'document_type': 'market_iq',
                'model_type': model_selection['model_type'],
                'current_phase': 1,
                'chat_history': conversation_history if isinstance(conversation_history, list) else [],
                'notes': {},
                'created': generated_at,
                'timestamp': generated_at,
                'status': 'in_progress',
                'user_id': str(current_user_id),
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
        session['document_type'] = session.get('document_type') or 'market_iq'
        session['model_type'] = model_selection['model_type']
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

@market_iq_bp.route('/chat', methods=['POST'])
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

Jaspen Score: {analysis_context.get('market_iq_score', 'N/A')}
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

@market_iq_bp.route('/history', methods=['GET'])
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

    return {
        'id': task_id,
        'title': title,
        'status': status,
        'owner': owner,
        'due_date': due_date,
        'depends_on': deduped_dep_ids,
        'order': order,
    }


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
    'market_iq_score', 'score_category', 'component_scores', 'financial_impact',
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
        'market_iq_score': overall_int,
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
# SCENARIO CRUD ROUTES
# ============================================================

@market_iq_bp.route('/threads/<thread_id>/scenarios', methods=['POST'])
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


@market_iq_bp.route('/threads/<thread_id>/scenarios', methods=['GET'])
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


@market_iq_bp.route('/scenarios/<scenario_id>', methods=['PATCH'])
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


@market_iq_bp.route('/scenarios/<scenario_id>', methods=['DELETE'])
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

@market_iq_bp.route('/scenarios/<scenario_id>/apply', methods=['POST'])
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
            'market_iq_score': result['market_iq_score'],
            'component_scores': result['component_scores'],
            'financial_impact': result['financial_impact'],
            'analysis_id': scenario_id,
        }), 200

    except Exception as e:
        print(f"[apply_scenario] {e}")
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@market_iq_bp.route('/scenarios/<scenario_id>/adopt', methods=['POST'])
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

@market_iq_bp.route('/threads/<thread_id>/wbs', methods=['GET'])
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


@market_iq_bp.route('/threads/<thread_id>/wbs', methods=['PUT', 'PATCH'])
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

        td['project_wbs'] = normalized_wbs
        all_data[thread_id] = td
        _save_scenarios(user_id, all_data)

        return jsonify({
            'success': True,
            'thread_id': thread_id,
            'project_wbs': normalized_wbs,
            'limits': limits,
        }), 200
    except Exception as e:
        print(f"[upsert_thread_wbs] {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================
# THREAD BUNDLE  (hydrates the Scenarios tab + ScoreDashboard)
# ============================================================

@market_iq_bp.route('/threads/<thread_id>/bundle', methods=['GET'])
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
        }), 200

    except Exception as e:
        print(f"[get_thread_bundle] {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================
# THREAD-LEVEL ADOPT  (used by ThreadEditModal)
# ============================================================

@market_iq_bp.route('/threads/<thread_id>/adopt', methods=['POST'])
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
