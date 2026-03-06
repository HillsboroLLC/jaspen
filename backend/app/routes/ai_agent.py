from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
import openai
import json
import os
import re
import time
from datetime import datetime
import uuid

ai_agent_bp = Blueprint('ai_agent', __name__)

# Set OpenAI API key from config
def get_openai_client():
    openai.api_key = current_app.config['OPENAI_API_KEY']
    return openai

@ai_agent_bp.route('/analyze', methods=['POST'])
@jwt_required()
def analyze_project():
    try:
        data = request.get_json()
        project_description = data.get('description', '')
        
        if not project_description:
            return jsonify({'error': 'Project description is required'}), 400
        
        # Get current user
        current_user_id = get_jwt_identity()
        
        # Initialize OpenAI
        client = get_openai_client()
        
        # Create the analysis prompt
        analysis_prompt = f"""
You are a Market IQ analyst specializing in commercialization strategy and financial impact assessment. Analyze the following project and provide a comprehensive Market IQ score and breakdown.

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

        # Call OpenAI API
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a Market IQ analyst specializing in commercialization strategy. Always respond with valid JSON only."},
                {"role": "user", "content": analysis_prompt}
            ],
            temperature=0.7,
            max_tokens=2000
        )
        
        # Parse the response
        analysis_text = response.choices[0].message.content
        
        # Try to parse JSON from the response
        try:
            analysis_result = json.loads(analysis_text)
        except json.JSONDecodeError:
            # If JSON parsing fails, extract JSON from the response
            import re
            json_match = re.search(r'\{.*\}', analysis_text, re.DOTALL)
            if json_match:
                analysis_result = json.loads(json_match.group())
            else:
                raise ValueError("Could not parse JSON from OpenAI response")
        
        # Add metadata
        analysis_result['analysis_id'] = str(uuid.uuid4())
        analysis_result['timestamp'] = datetime.utcnow().isoformat()
        analysis_result['user_id'] = current_user_id
        analysis_result['project_description'] = project_description
        
        # TODO: Save to database for history
        
        return jsonify(analysis_result), 200
        
    except Exception as e:
        print(f"Error in Market IQ analysis: {str(e)}")
        return jsonify({'error': 'Analysis failed. Please try again.'}), 500

@ai_agent_bp.route('/chat', methods=['POST'])
@jwt_required()
def chat_with_analysis():
    try:
        data = request.get_json()
        message = data.get('message', '')
        analysis_context = data.get('analysis_context', {})
        
        if not message:
            return jsonify({'error': 'Message is required'}), 400
        
        # Initialize OpenAI
        client = get_openai_client()
        
        # Create context from analysis
        context_prompt = f"""
You are a Market IQ analyst assistant. The user has received the following analysis:

Market IQ Score: {analysis_context.get('market_iq_score', 'N/A')}
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
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a Market IQ analyst assistant specializing in commercialization strategy and financial optimization."},
                {"role": "user", "content": context_prompt}
            ],
            temperature=0.7,
            max_tokens=800
        )
        
        ai_response = response.choices[0].message.content
        
        return jsonify({
            'response': ai_response,
            'timestamp': datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        print(f"Error in Market IQ chat: {str(e)}")
        return jsonify({'error': 'Chat failed. Please try again.'}), 500

@ai_agent_bp.route('/history', methods=['GET'])
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
# FILE-BASED SESSION/THREAD STORAGE (unified with sessions.py)
# ============================================================
SESSIONS_DIR = 'sessions_data'

def _ensure_sessions_dir():
    if not os.path.exists(SESSIONS_DIR):
        os.makedirs(SESSIONS_DIR)

def _sessions_file(user_id):
    _ensure_sessions_dir()
    return os.path.join(SESSIONS_DIR, f'user_{user_id}_sessions.json')

def _load_sessions(user_id):
    path = _sessions_file(user_id)
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"[sessions] load error for {user_id}: {e}")
    return {}

def _save_sessions(user_id, data):
    path = _sessions_file(user_id)
    try:
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        print(f"[sessions] save error for {user_id}: {e}")
        return False


# ============================================================
# THREAD CRUD ROUTES
# ============================================================

@ai_agent_bp.route('/threads', methods=['GET'])
@jwt_required()
def list_threads():
    """List all threads/sessions for the current user."""
    try:
        user_id = get_jwt_identity()
        sessions = _load_sessions(user_id)

        sessions_list = sorted(
            sessions.values(),
            key=lambda s: s.get('timestamp', s.get('created', '')),
            reverse=True
        )

        return jsonify({'success': True, 'sessions': sessions_list}), 200
    except Exception as e:
        print(f"[list_threads] {e}")
        return jsonify({'error': str(e)}), 500


@ai_agent_bp.route('/threads/<thread_id>', methods=['GET'])
@jwt_required()
def get_thread(thread_id):
    """Get a single thread/session by ID."""
    try:
        user_id = get_jwt_identity()
        sessions = _load_sessions(user_id)

        if thread_id not in sessions:
            return jsonify({'error': 'Thread not found'}), 404

        return jsonify({'success': True, 'session': sessions[thread_id]}), 200
    except Exception as e:
        print(f"[get_thread] {e}")
        return jsonify({'error': str(e)}), 500


@ai_agent_bp.route('/threads/<thread_id>', methods=['PATCH'])
@jwt_required()
def update_thread(thread_id):
    """Rename or update thread metadata."""
    try:
        user_id = get_jwt_identity()
        data = request.get_json() or {}
        sessions = _load_sessions(user_id)

        if thread_id not in sessions:
            return jsonify({'error': 'Thread not found'}), 404

        if 'name' in data:
            sessions[thread_id]['name'] = data['name']
        sessions[thread_id]['timestamp'] = datetime.utcnow().isoformat()

        _save_sessions(user_id, sessions)
        return jsonify({'success': True, 'session': sessions[thread_id]}), 200
    except Exception as e:
        print(f"[update_thread] {e}")
        return jsonify({'error': str(e)}), 500


@ai_agent_bp.route('/threads/<thread_id>', methods=['DELETE'])
@jwt_required()
def delete_thread(thread_id):
    """Delete a single thread and its scenario data."""
    try:
        user_id = get_jwt_identity()

        # Remove from sessions
        sessions = _load_sessions(user_id)
        if thread_id in sessions:
            del sessions[thread_id]
            _save_sessions(user_id, sessions)

        # Remove from scenarios
        scenarios = _load_scenarios(user_id)
        if thread_id in scenarios:
            del scenarios[thread_id]
            _save_scenarios(user_id, scenarios)

        return jsonify({'success': True}), 200
    except Exception as e:
        print(f"[delete_thread] {e}")
        return jsonify({'error': str(e)}), 500


@ai_agent_bp.route('/threads/clear', methods=['POST'])
@jwt_required()
def clear_threads():
    """
    Clear ALL threads, sessions, and scenarios for the current user.
    Uses POST (not DELETE) to survive reverse-proxy method restrictions.
    """
    try:
        user_id = get_jwt_identity()
        cleared = {'sessions': False, 'scenarios': False}

        # Wipe sessions file
        sessions_path = _sessions_file(user_id)
        if os.path.exists(sessions_path):
            os.remove(sessions_path)
            cleared['sessions'] = True

        # Wipe scenarios file
        scenarios_path = _scenarios_file(user_id)
        if os.path.exists(scenarios_path):
            os.remove(scenarios_path)
            cleared['scenarios'] = True

        print(f"[clear_threads] user={user_id} cleared={cleared}")
        return jsonify({'success': True, 'cleared': cleared}), 200
    except Exception as e:
        print(f"[clear_threads] {e}")
        return jsonify({'error': str(e)}), 500


@ai_agent_bp.route('/threads/<thread_id>/levers', methods=['GET'])
@jwt_required()
def get_thread_levers(thread_id):
    """
    Return scenario lever definitions from the stored baseline.
    Same logic as the bundle endpoint's lever extraction,
    exposed as a standalone route for the ScenarioModeler.
    """
    try:
        user_id = get_jwt_identity()
        td = _load_scenarios(user_id).get(thread_id, {})

        scenario_levers = []
        for key, val in (td.get('baseline_inputs') or {}).items():
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

        return jsonify({'levers': scenario_levers}), 200
    except Exception as e:
        print(f"[get_thread_levers] {e}")
        return jsonify({'error': str(e)}), 500


@ai_agent_bp.route('/threads/<thread_id>/analyses', methods=['GET'])
@jwt_required()
def list_thread_analyses(thread_id):
    """List scored analyses/scorecards for a thread."""
    try:
        user_id = get_jwt_identity()
        td = _load_scenarios(user_id).get(thread_id, {})

        analyses = []
        # Baseline counts as the first analysis
        baseline = td.get('baseline')
        if baseline:
            analyses.append({
                'id': thread_id,
                'label': 'Baseline',
                'market_iq_score': baseline.get('market_iq_score'),
                'created_at': baseline.get('timestamp'),
                'is_baseline': True,
            })

        # Each applied scenario with a cached result is also an analysis
        for sid, scn in (td.get('scenarios') or {}).items():
            if scn.get('result'):
                analyses.append({
                    'id': sid,
                    'label': scn.get('label', 'Scenario'),
                    'market_iq_score': scn['result'].get('market_iq_score'),
                    'created_at': scn.get('created_at'),
                    'is_baseline': False,
                })

        return jsonify({'analyses': analyses}), 200
    except Exception as e:
        print(f"[list_thread_analyses] {e}")
        return jsonify({'error': str(e)}), 500


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
    }


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

@ai_agent_bp.route('/threads/<thread_id>/scenarios', methods=['POST'])
@jwt_required()
def create_scenario(thread_id):
    """Create a scenario. Stores baseline on first call for this thread."""
    try:
        user_id = get_jwt_identity()
        data = request.get_json() or {}

        all_data = _load_scenarios(user_id)
        if thread_id not in all_data:
            all_data[thread_id] = _thread_entry()
        td = all_data[thread_id]

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


@ai_agent_bp.route('/threads/<thread_id>/scenarios', methods=['GET'])
@jwt_required()
def list_scenarios(thread_id):
    """List scenarios for a thread, with pagination."""
    try:
        user_id = get_jwt_identity()
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


@ai_agent_bp.route('/scenarios/<scenario_id>', methods=['PATCH'])
@jwt_required()
def update_scenario(scenario_id):
    """Update label / deltas. Invalidates cached result if deltas change."""
    try:
        user_id  = get_jwt_identity()
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


@ai_agent_bp.route('/scenarios/<scenario_id>', methods=['DELETE'])
@jwt_required()
def delete_scenario(scenario_id):
    """Delete a scenario. Clears adoption if it was the adopted one."""
    try:
        user_id  = get_jwt_identity()
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

@ai_agent_bp.route('/scenarios/<scenario_id>/apply', methods=['POST'])
@jwt_required()
def apply_scenario(scenario_id):
    """
    Deterministically score a scenario against the stored baseline.
    Caches the result on the scenario object.
    """
    try:
        user_id   = get_jwt_identity()
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


@ai_agent_bp.route('/scenarios/<scenario_id>/adopt', methods=['POST'])
@jwt_required()
def adopt_scenario(scenario_id):
    """Mark a scenario as the adopted (current) analysis for its thread."""
    try:
        user_id   = get_jwt_identity()
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
# THREAD BUNDLE  (hydrates the Scenarios tab + ScoreDashboard)
# ============================================================

@ai_agent_bp.route('/threads/<thread_id>/bundle', methods=['GET'])
@jwt_required()
def get_thread_bundle(thread_id):
    """
    Return everything the frontend needs to render the Scenarios tab:
      baseline_scorecard, current_scorecard, scenarios[], scenario_levers[].
    """
    try:
        user_id = get_jwt_identity()
        scn_limit = int(request.args.get('scn_limit', 50))

        td = _load_scenarios(user_id).get(thread_id, {})

        baseline         = td.get('baseline')
        scenarios_dict   = td.get('scenarios', {})
        adopted_id       = td.get('adopted_scenario_id')

        # Sorted scenario list
        scenarios_list = sorted(scenarios_dict.values(),
                                key=lambda s: s.get('created_at', ''), reverse=True)[:scn_limit]

        # Current scorecard = adopted scenario result if set, else baseline
        current_scorecard = baseline
        if adopted_id and adopted_id in scenarios_dict:
            current_scorecard = scenarios_dict[adopted_id].get('result') or baseline

        # Build scenario_levers from baseline inputs
        scenario_levers = []
        for key, val in (td.get('baseline_inputs') or {}).items():
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
            'thread': {'id': thread_id},
            'messages': [],                      # handled by AI-Agent service
            'baseline_scorecard': baseline,
            'current_scorecard': current_scorecard,
            'scenarios': scenarios_list,
            'scenario_levers': scenario_levers,
            'adopted_scenario_id': adopted_id,
        }), 200

    except Exception as e:
        print(f"[get_thread_bundle] {e}")
        return jsonify({'error': str(e)}), 500


# ============================================================
# THREAD-LEVEL ADOPT  (used by ThreadEditModal)
# ============================================================

@ai_agent_bp.route('/threads/<thread_id>/adopt', methods=['POST'])
@jwt_required()
def adopt_analysis_for_thread(thread_id):
    """
    Adopt an analysis (baseline or scenario) as current for the thread.
    If analysis_id matches a scenario, that scenario becomes adopted;
    otherwise adoption is cleared (baseline becomes current).
    """
    try:
        user_id = get_jwt_identity()
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
