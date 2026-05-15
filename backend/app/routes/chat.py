# app/routes/chat.py

import json
import logging
import os
from datetime import datetime

import anthropic
from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

chat_bp = Blueprint('chat', __name__)


def _model_type_from_resolved_model(model_name):
    text = str(model_name or '').strip().lower()
    if 'opus' in text:
        return 'titan'
    if 'sonnet' in text:
        return 'orbit'
    return 'pluto'


def _public_usage_payload(usage, resolved_model):
    usage = usage if isinstance(usage, dict) else {}
    model_type = _model_type_from_resolved_model(resolved_model)
    label = {'pluto': 'Pluto', 'orbit': 'Orbit', 'titan': 'Titan'}.get(model_type, 'Pluto')
    return {
        'model_type': model_type,
        'model_label': label,
        'input_tokens': int(usage.get('input_tokens') or 0),
        'output_tokens': int(usage.get('output_tokens') or 0),
        'total_tokens': int(usage.get('total_tokens') or 0),
    }


def _anthropic_api_key():
    return (
        current_app.config.get('ANTHROPIC_API_KEY')
        or current_app.config.get('CLAUDE_API_KEY')
        or os.getenv('ANTHROPIC_API_KEY')
        or os.getenv('CLAUDE_API_KEY')
    )


def _anthropic_model_candidates(preferred=None):
    configured = (
        preferred,
        current_app.config.get('AI_AGENT_ANTHROPIC_MODEL'),
        os.getenv('AI_AGENT_ANTHROPIC_MODEL'),
        current_app.config.get('MODEL_TYPE_BACKING_IDS', {}).get('pluto') if isinstance(current_app.config.get('MODEL_TYPE_BACKING_IDS'), dict) else None,
    )
    fallbacks = (
        'claude-sonnet-4-5-20250929',
        'claude-3-7-sonnet-latest',
        'claude-3-7-sonnet-20250219',
        'claude-3-5-sonnet-20241022',
        'claude-haiku-4-5',
    )
    out = []
    seen = set()
    for model in [*configured, *fallbacks]:
        m = str(model or '').strip()
        if not m or m in seen:
            continue
        seen.add(m)
        out.append(m)
    return out


# Initialize Claude client
def get_claude_client():
    api_key = _anthropic_api_key()
    if not api_key:
        raise ValueError('ANTHROPIC_API_KEY not found in configuration')
    return anthropic.Anthropic(api_key=api_key)


def _anthropic_text_completion(system_prompt, user_prompt, *, max_tokens=1000, temperature=0.7, model=None):
    client = get_claude_client()
    last_error = None
    for candidate in _anthropic_model_candidates(model):
        try:
            response = client.messages.create(
                model=candidate,
                max_tokens=max(64, int(max_tokens or 1000)),
                temperature=float(temperature if temperature is not None else 0.7),
                system=str(system_prompt or '').strip() or None,
                messages=[{"role": "user", "content": str(user_prompt or '').strip()}],
            )
            text_parts = []
            for block in getattr(response, 'content', []) or []:
                if getattr(block, 'type', None) == 'text':
                    txt = str(getattr(block, 'text', '') or '').strip()
                    if txt:
                        text_parts.append(txt)
            text = '\n'.join(text_parts).strip()
            usage = getattr(response, 'usage', None)
            usage_payload = {
                'prompt_tokens': int(getattr(usage, 'input_tokens', 0) or 0),
                'completion_tokens': int(getattr(usage, 'output_tokens', 0) or 0),
                'total_tokens': int(getattr(usage, 'input_tokens', 0) or 0) + int(getattr(usage, 'output_tokens', 0) or 0),
            }
            return text, usage_payload, candidate
        except Exception as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    raise RuntimeError('No Anthropic model candidates configured')


@chat_bp.route('/chat', methods=['POST'], strict_slashes=False)
@jwt_required()
def chat():
    """
    Handle chat requests from the Wizard component.
    Anthropic-only implementation.
    """
    try:
        current_user_id = get_jwt_identity()

        payload = request.get_json() or {}
        user_message = payload.get('message', '').strip()
        doc_type = payload.get('docType', 'market_analysis')
        detailed = payload.get('detailed', True)
        system_prompt = payload.get('systemPrompt', '')
        phase = payload.get('phase', 1)

        if not user_message:
            return jsonify({'error': 'Message is required'}), 400

        if not system_prompt:
            system_prompt = 'You are a helpful business analyst assistant. Provide detailed, professional advice.'

        logger.info(
            'Chat request from user %s: doc_type=%s, phase=%s, detailed=%s',
            current_user_id,
            doc_type,
            phase,
            detailed,
        )

        reply, usage, resolved_model = _anthropic_text_completion(
            system_prompt,
            user_message,
            max_tokens=2000,
            temperature=0.7,
        )

        if not reply:
            return jsonify({'error': 'No response from AI'}), 500

        logger.info('Anthropic response received for user %s via %s', current_user_id, resolved_model)
        return jsonify({
            'success': True,
            'reply': reply,
            'usage': _public_usage_payload(usage, resolved_model),
        })

    except Exception as e:
        logger.error('Chat endpoint error: %s', e)
        return jsonify({'error': f'Server error: {str(e)}'}), 500


@chat_bp.route('', methods=['POST'])
@jwt_required()
def chat_main():
    """
    Enhanced main chat route that handles both Wizard and FloatingAI requests.
    Supports statistical analysis context and tool-specific responses.
    """
    try:
        current_user_id = get_jwt_identity()
        payload = request.get_json() or {}

        tool = payload.get('tool', '').lower()
        context = payload.get('context', {})

        if tool and context:
            return handle_floating_ai_chat(payload, current_user_id)
        return chat()

    except Exception as e:
        logger.error(f'Chat main endpoint error: {e}')
        return jsonify({'error': f'Server error: {str(e)}'}), 500


def handle_floating_ai_chat(payload, user_id):
    """
    Handle FloatingAI chat requests with tool-specific context awareness.
    """
    try:
        message = payload.get('message', '').strip()
        tool = payload.get('tool', 'unknown').lower()
        context = payload.get('context', {})

        if not message:
            return jsonify({'error': 'Message is required'}), 400

        page = context.get('page', 'unknown')
        form_data = context.get('formData', {})
        statistical_context = context.get('statisticalContext', None)

        logger.info(f'FloatingAI request from user {user_id}: tool={tool}, page={page}')

        if tool == 'statistics':
            response_text = generate_statistical_response(message, statistical_context, user_id)
        elif tool in ['a3', 'finy', 'sipoc']:
            response_text = generate_form_response(message, tool, form_data, user_id)
        else:
            response_text = generate_general_response(message, tool, context, user_id)

        return jsonify({
            'success': True,
            'response': response_text,
            'tool': tool,
            'timestamp': datetime.utcnow().isoformat(),
        })

    except Exception as e:
        logger.error(f'FloatingAI chat error: {str(e)}')
        return jsonify({'success': False, 'error': 'Failed to generate AI response', 'fallback': True}), 500


def generate_statistical_response(message, statistical_context, user_id):
    """
    Generate AI response for statistical analysis with context awareness.
    """
    try:
        system_prompt = build_statistical_system_prompt(statistical_context)
        text, _usage, _model = _anthropic_text_completion(
            system_prompt,
            message,
            max_tokens=1000,
            temperature=0.7,
        )
        return text or generate_statistical_fallback_response(message, statistical_context)
    except Exception as err:
        logger.warning('Statistical response fallback: %s', err)
        return generate_statistical_fallback_response(message, statistical_context)


def build_statistical_system_prompt(statistical_context):
    """
    Build context-aware system prompt for statistical analysis.
    """
    base_prompt = """You are Kii, an expert statistical analysis assistant. You help users choose appropriate statistical methods, interpret results, and guide them through data analysis workflows.

Your expertise includes:
- Descriptive statistics and data exploration
- Hypothesis testing (t-tests, ANOVA, chi-square)
- Correlation and regression analysis
- Data visualization recommendations
- Statistical significance and effect sizes
- Choosing appropriate tests based on data types

Always provide practical, actionable guidance and explain statistical concepts in simple terms."""

    if not statistical_context:
        return base_prompt + '\n\nThe user has not uploaded data yet. Encourage them to upload a CSV file and explain what you can help with once they have data.'

    dataset = statistical_context.get('dataset', {})
    analysis = statistical_context.get('analysis', {})
    recommendations = statistical_context.get('recommendations', [])

    if not dataset.get('hasData'):
        return base_prompt + '\n\nThe user has not uploaded data yet. Encourage them to upload a CSV file.'

    context_info = f"""
Current Dataset Context:
- File: {dataset.get('fileName', 'Unknown')}
- Rows: {dataset.get('rowCount', 0)}
- Columns: {dataset.get('columnCount', 0)}
- Numeric variables: {', '.join(dataset.get('numericColumns', []))}
- Categorical variables: {', '.join(dataset.get('categoricalColumns', []))}

Current Analysis:
- Goal: {analysis.get('goal', 'Not set')}
- Target variable: {analysis.get('targetCol', 'Not selected')}
- Group variable: {analysis.get('groupCol', 'Not selected')}

Recommended methods: {', '.join(recommendations)}

Use this context to provide specific, relevant guidance. Reference the actual variable names and data structure in your responses."""

    return base_prompt + context_info


def generate_form_response(message, tool, form_data, user_id):
    """
    Generate AI response for form-based tools (A3, FinY, SIPOC).
    """
    try:
        system_prompt = build_form_system_prompt(tool, form_data)
        text, _usage, _model = _anthropic_text_completion(
            system_prompt,
            message,
            max_tokens=800,
            temperature=0.7,
        )
        return text or generate_form_fallback_response(message, tool, form_data)
    except Exception as e:
        logger.error(f'Form AI error: {str(e)}')
        return generate_form_fallback_response(message, tool, form_data)


def build_form_system_prompt(tool, form_data):
    """
    Build system prompt for form-based tools.
    """
    prompts = {
        'a3': """You are Kii, an expert A3 Problem Solving assistant. Help users fill out their A3 form by extracting information from conversations and providing guidance on problem-solving methodology.

A3 sections: Project Title, Problem Owner, Team Members, Background, Problem Statement, Business Impact, Current State, Goal Statement, Target State, Results, Lessons Learned, Next Steps.

Extract relevant information and suggest what to fill in next.""",

        'finy': """You are Kii, a FinY (Financial Analysis) assistant. Help users calculate financial benefits and ROI for their improvement projects.

FinY sections: Project Title, Baseline Performance, Target Performance, Timeframe, Investment Cost, Expected Savings, ROI Calculation.

Focus on quantifiable financial metrics and business value.""",

        'sipoc': """You are Kii, a SIPOC (Suppliers, Inputs, Process, Outputs, Customers) assistant. Help users map their business processes systematically.

SIPOC sections: Suppliers, Inputs, Process Steps, Outputs, Customers.

Guide users through each section methodically.""",
    }

    base_prompt = prompts.get(tool, prompts['a3'])

    if form_data:
        filled_fields = [f"{k}: {v}" for k, v in form_data.items() if v and str(v).strip()]
        if filled_fields:
            base_prompt += '\n\nCurrent form data:\n' + '\n'.join(filled_fields)

    return base_prompt


def generate_general_response(message, tool, context, user_id):
    """
    Generate AI response for general/unknown tools.
    """
    try:
        system_prompt = f'You are Kii, a helpful assistant for the {tool} tool. Provide guidance and support for user questions.'
        text, _usage, _model = _anthropic_text_completion(
            system_prompt,
            message,
            max_tokens=600,
            temperature=0.7,
        )
        return text or f"I'm here to help with {tool}. Could you tell me more about what you're working on?"
    except Exception as e:
        logger.error(f'General AI error: {str(e)}')
        return f"I'm here to help with {tool}. Could you tell me more about what you're working on?"


def generate_statistical_fallback_response(message, statistical_context):
    """
    Fallback response for statistical analysis when AI APIs fail.
    """
    message_lower = message.lower()

    if not statistical_context or not statistical_context.get('dataset', {}).get('hasData'):
        return "I'd love to help with your statistical analysis. Please upload a dataset first so I can provide specific guidance based on your data structure."

    dataset = statistical_context.get('dataset', {})

    if 'correlation' in message_lower or 'relationship' in message_lower:
        if len(dataset.get('numericColumns', [])) >= 2:
            return f"For correlation analysis, I can see you have {len(dataset.get('numericColumns', []))} numeric columns. Set your goal to 'Association / Relationships' to compute Pearson correlations between numeric pairs."
        return 'For correlation analysis, you need at least 2 numeric variables. Consider converting categorical variables to numeric if appropriate.'

    if 'compare' in message_lower or 'group' in message_lower:
        if len(dataset.get('numericColumns', [])) >= 1 and len(dataset.get('categoricalColumns', [])) >= 1:
            return "For group comparisons, set your goal to 'Compare Groups', then select a numeric target variable and a categorical grouping variable."
        return 'For group comparisons, you need at least one numeric variable and one categorical variable.'

    if 'describe' in message_lower or 'summary' in message_lower:
        return "For descriptive statistics, set your goal to 'Describe / Summarize'. This will provide summary statistics for numeric variables and frequency tables for categorical variables."

    return f"I can help analyze your dataset with {dataset.get('rowCount', 0)} rows and {dataset.get('columnCount', 0)} columns. What type of analysis are you interested in?"


def generate_form_fallback_response(message, tool, form_data):
    """
    Fallback response for form tools when AI APIs fail.
    """
    return f"I'm here to help you complete your {tool.upper()} form. Tell me about your project details and I'll help organize the information."


@chat_bp.route('/statistical-insights', methods=['POST'])
@jwt_required()
def statistical_insights():
    """
    Dedicated endpoint for generating statistical insights from analysis results.
    """
    try:
        data = request.get_json()

        analysis_results = data.get('results', {})
        dataset_info = data.get('dataset', {})
        analysis_goal = data.get('goal', 'describe')

        insights = generate_analysis_insights(analysis_results, dataset_info, analysis_goal)

        return jsonify({'success': True, 'insights': insights, 'timestamp': datetime.utcnow().isoformat()})

    except Exception as e:
        logger.error(f'Statistical insights error: {str(e)}')
        return jsonify({'success': False, 'error': 'Failed to generate insights'}), 500


def generate_analysis_insights(results, dataset_info, goal):
    """
    Generate statistical insights from analysis results.
    """
    try:
        system_prompt = """You are a statistical expert. Analyze the provided statistical results and generate clear, actionable insights. Focus on:

1. What the results mean in practical terms
2. Statistical significance and effect sizes
3. Recommendations for next steps
4. Potential limitations or caveats
5. Business implications

Explain everything in simple, non-technical language."""

        context = f"""
Dataset: {dataset_info.get('fileName', 'Unknown')} ({dataset_info.get('rowCount', 0)} rows)
Analysis Goal: {goal}
Results: {json.dumps(results, indent=2)}
"""

        text, _usage, _model = _anthropic_text_completion(
            system_prompt,
            f'Please analyze these statistical results and provide insights:\n\n{context}',
            max_tokens=1200,
            temperature=0.7,
        )
        return text or 'Analysis complete. Review your results above and consider running additional analyses to validate assumptions.'

    except Exception as e:
        logger.error(f'Insights generation error: {str(e)}')
        return 'Analysis complete. Review your results above and consider running additional analyses or visualizations to explore your data further.'


@chat_bp.route('/test', methods=['GET'])
def test_chat():
    """
    Test endpoint to verify chat route is working.
    """
    return jsonify({
        'message': 'Chat route is working',
        'ai_configured': bool(_anthropic_api_key()),
        'default_model_type': 'pluto',
    })


@chat_bp.route('/models', methods=['GET'])
@jwt_required()
def get_available_models():
    """
    Get available Anthropic model candidates configured for this deployment.
    """
    try:
        return jsonify({
            'success': True,
            'model_types': ['pluto', 'orbit', 'titan'],
        })
    except Exception as e:
        logger.error(f'Error fetching models: {e}')
        return jsonify({'error': str(e)}), 500
