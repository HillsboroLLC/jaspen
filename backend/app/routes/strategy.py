from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
import anthropic
import json
import os
import re
import time
from datetime import datetime, timedelta
import uuid
from types import SimpleNamespace
from app import db, limiter
from app.admin_audit import append_user_audit_event
from app.models import User
from app.scenarios_store import load_scenarios_data, save_scenarios_data
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


def _audit_strategy_event(action, *, user=None, user_id=None, details=None):
    append_user_audit_event(
        actor_user=user,
        actor_user_id=getattr(user, 'id', None) if user is not None else user_id,
        actor_email=getattr(user, 'email', None) if user is not None else None,
        action=action,
        target_user_id=getattr(user, 'id', None) if user is not None else user_id,
        target_email=getattr(user, 'email', None) if user is not None else None,
        details=details if isinstance(details, dict) else {},
    )

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


_SCORES_SORT_BY_OPTIONS = {'date', 'score', 'category', 'name'}
_SCORES_SORT_DIR_OPTIONS = {'asc', 'desc'}
_SCORES_CATEGORY_OPTIONS = {'Excellent', 'Good', 'Fair', 'At Risk'}


def _scores_parse_int(value, default, min_value=0, max_value=None):
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    if parsed < min_value:
        parsed = min_value
    if max_value is not None and parsed > max_value:
        parsed = max_value
    return parsed


def _scores_parse_iso(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        candidate = text[:-1] + '+00:00' if text.endswith('Z') else text
        parsed = datetime.fromisoformat(candidate)
        return parsed.isoformat()
    except Exception:
        return text


def _scores_timestamp(value):
    if not value:
        return 0.0
    try:
        text = str(value).strip()
        candidate = text[:-1] + '+00:00' if text.endswith('Z') else text
        return datetime.fromisoformat(candidate).timestamp()
    except Exception:
        return 0.0


def _scores_extract_numeric_score(result):
    if not isinstance(result, dict):
        return None
    candidates = [
        result.get('jaspen_score'),
        result.get('overall_score'),
        result.get('score'),
        (result.get('compat') or {}).get('score') if isinstance(result.get('compat'), dict) else None,
    ]
    for candidate in candidates:
        try:
            parsed = float(candidate)
        except Exception:
            continue
        if parsed == parsed:
            return int(round(parsed))
    return None


def _collect_completed_scores(
    user_id,
    *,
    sort_by='date',
    sort_dir='desc',
    category_filter=None,
    search='',
):
    sessions = load_user_sessions(user_id) or {}
    scenarios_by_thread = _load_scenarios(user_id) or {}

    scores = []
    for key, session in (sessions.items() if isinstance(sessions, dict) else []):
        if not isinstance(session, dict):
            continue

        thread_id = str(session.get('session_id') or key or '').strip()
        if not thread_id:
            continue

        session_status = str(session.get('status') or '').strip().lower()
        session_completed = session_status == 'completed'

        thread_data = scenarios_by_thread.get(thread_id) if isinstance(scenarios_by_thread, dict) else None
        thread_data = thread_data if isinstance(thread_data, dict) else {}
        scenarios = thread_data.get('scenarios')
        scenarios = scenarios if isinstance(scenarios, dict) else {}
        adopted_scenario_id = thread_data.get('adopted_scenario_id')
        adopted_raw = scenarios.get(adopted_scenario_id) if adopted_scenario_id else None
        adopted_raw = adopted_raw if isinstance(adopted_raw, dict) else None

        adopted_scenario = None
        if adopted_raw:
            adopted_scenario = {
                'scenario_id': str(adopted_raw.get('scenario_id') or adopted_scenario_id),
                'label': adopted_raw.get('label') or 'Adopted scenario',
                'deltas': adopted_raw.get('deltas') if isinstance(adopted_raw.get('deltas'), dict) else {},
                'result': adopted_raw.get('result') if isinstance(adopted_raw.get('result'), dict) else None,
                'created_at': _scores_parse_iso(adopted_raw.get('created_at')),
                'updated_at': _scores_parse_iso(adopted_raw.get('updated_at')),
                'adopted': True,
            }

        analyses = _scores_analysis_entries(session, thread_id)
        for analysis in analyses:
            result = analysis.get('result') if isinstance(analysis, dict) else None
            if not isinstance(result, dict):
                continue

            jaspen_score = _scores_extract_numeric_score(result)
            if jaspen_score is None and not session_completed:
                continue

            project_name = str(
                result.get('project_name')
                or result.get('name')
                or result.get('title')
                or session.get('name')
                or f'Thread {thread_id}'
            ).strip()

            score_category = _scores_category_from_values(
                jaspen_score,
                explicit_category=result.get('score_category'),
            )
            component_scores = result.get('component_scores')
            if not isinstance(component_scores, dict):
                component_scores = result.get('scores') if isinstance(result.get('scores'), dict) else {}
            financial_impact = result.get('financial_impact')
            if not isinstance(financial_impact, dict):
                financial_impact = {}

            created_at = _scores_parse_iso(
                analysis.get('created_at')
                or result.get('timestamp')
                or session.get('created')
                or session.get('timestamp')
            )
            updated_at = _scores_parse_iso(
                analysis.get('updated_at')
                or session.get('timestamp')
                or result.get('timestamp')
                or created_at
            )

            row = {
                'thread_id': thread_id,
                'project_name': project_name,
                'jaspen_score': jaspen_score,
                'score_category': score_category,
                'component_scores': component_scores,
                'adopted_scenario': adopted_scenario,
                'financial_impact': financial_impact,
                'created_at': created_at,
                'updated_at': updated_at,
            }

            if category_filter and row['score_category'] != category_filter:
                continue
            if search and search not in row['project_name'].lower():
                continue
            scores.append(row)

    reverse = sort_dir == 'desc'
    if sort_by == 'score':
        scores.sort(
            key=lambda row: (
                row.get('jaspen_score') is None,
                row.get('jaspen_score') if row.get('jaspen_score') is not None else -1,
            ),
            reverse=reverse,
        )
    elif sort_by == 'category':
        scores.sort(key=lambda row: str(row.get('score_category') or '').lower(), reverse=reverse)
    elif sort_by == 'name':
        scores.sort(key=lambda row: str(row.get('project_name') or '').lower(), reverse=reverse)
    else:
        scores.sort(
            key=lambda row: _scores_timestamp(row.get('updated_at') or row.get('created_at')),
            reverse=reverse,
        )

    return scores


def _portfolio_agent_score_rows(scores, max_rows=30):
    prioritized = sorted(
        [row for row in (scores or []) if isinstance(row, dict)],
        key=lambda row: (
            row.get('jaspen_score') is None,
            -(row.get('jaspen_score') or -1),
            -_scores_timestamp(row.get('updated_at') or row.get('created_at')),
        ),
    )
    trimmed = prioritized[:max_rows]
    payload = []
    for row in trimmed:
        component_scores = row.get('component_scores') if isinstance(row.get('component_scores'), dict) else {}
        financial_impact = row.get('financial_impact') if isinstance(row.get('financial_impact'), dict) else {}
        payload.append({
            'thread_id': row.get('thread_id'),
            'project_name': row.get('project_name'),
            'jaspen_score': row.get('jaspen_score'),
            'score_category': row.get('score_category'),
            'updated_at': row.get('updated_at') or row.get('created_at'),
            'adopted_scenario': (
                row.get('adopted_scenario', {}).get('label')
                if isinstance(row.get('adopted_scenario'), dict)
                else None
            ),
            'component_scores': component_scores,
            'financial_impact': financial_impact,
        })
    return payload


def _scores_category_from_values(score, explicit_category=None):
    if isinstance(explicit_category, str):
        cleaned = explicit_category.strip()
        if cleaned in _SCORES_CATEGORY_OPTIONS:
            return cleaned
    if score is None:
        return 'At Risk'
    if score >= 80:
        return 'Excellent'
    if score >= 60:
        return 'Good'
    if score >= 40:
        return 'Fair'
    return 'At Risk'


def _scores_analysis_entries(session, thread_id):
    if not isinstance(session, dict):
        return []

    history = session.get('analysis_history')
    if not isinstance(history, list):
        history = session.get('analyses')
    if not isinstance(history, list):
        history = []

    normalized = []
    for item in history:
        if not isinstance(item, dict):
            continue
        analysis_id = item.get('analysis_id') or item.get('id')
        result = item.get('result')
        if not isinstance(result, dict):
            continue
        if not analysis_id:
            analysis_id = result.get('analysis_id') or result.get('id') or thread_id
        normalized.append({
            'analysis_id': str(analysis_id),
            'created_at': item.get('created_at') or item.get('timestamp') or result.get('timestamp') or session.get('timestamp') or session.get('created'),
            'updated_at': item.get('updated_at') or result.get('timestamp') or session.get('timestamp'),
            'result': result,
        })

    if normalized:
        normalized.sort(key=lambda row: _scores_timestamp(row.get('created_at')), reverse=True)
        return normalized

    session_result = session.get('result')
    if isinstance(session_result, dict):
        analysis_id = (
            session_result.get('analysis_id')
            or session_result.get('id')
            or session.get('adopted_analysis_id')
            or session.get('session_id')
            or thread_id
        )
        return [{
            'analysis_id': str(analysis_id),
            'created_at': session_result.get('timestamp') or session.get('timestamp') or session.get('created'),
            'updated_at': session.get('timestamp') or session_result.get('timestamp'),
            'result': session_result,
        }]
    return []

def _anthropic_api_key():
    return (
        current_app.config.get('ANTHROPIC_API_KEY')
        or current_app.config.get('CLAUDE_API_KEY')
        or os.getenv('ANTHROPIC_API_KEY')
        or os.getenv('CLAUDE_API_KEY')
    )


def _anthropic_model_candidates(preferred_model=None):
    configured = (
        preferred_model,
        current_app.config.get('AI_AGENT_ANTHROPIC_MODEL'),
        os.getenv('AI_AGENT_ANTHROPIC_MODEL'),
    )
    fallbacks = (
        'claude-3-7-sonnet-latest',
        'claude-3-7-sonnet-20250219',
        'claude-3-5-sonnet-20241022',
        'claude-3-5-haiku-latest',
    )
    seen = set()
    out = []
    for model_name in [*configured, *fallbacks]:
        cleaned = str(model_name or '').strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out


class _AnthropicCompatClient:
    def __init__(self, api_key):
        self._client = anthropic.Anthropic(api_key=api_key)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model=None, messages=None, max_tokens=800, temperature=0.2, **_kwargs):
        prompt_messages = messages if isinstance(messages, list) else []
        system_parts = []
        turn_messages = []
        for msg in prompt_messages:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get('role') or '').strip().lower()
            content = str(msg.get('content') or '').strip()
            if not content:
                continue
            if role == 'system':
                system_parts.append(content)
                continue
            if role in {'user', 'assistant'}:
                turn_messages.append({'role': role, 'content': content})
        if not turn_messages:
            turn_messages = [{'role': 'user', 'content': ''}]

        last_error = None
        for candidate in _anthropic_model_candidates(model):
            try:
                response = self._client.messages.create(
                    model=candidate,
                    system='\n'.join(system_parts).strip() or None,
                    messages=turn_messages,
                    max_tokens=max(64, int(max_tokens or 800)),
                    temperature=float(temperature if temperature is not None else 0.2),
                )
                text_parts = []
                for block in getattr(response, 'content', []) or []:
                    if getattr(block, 'type', None) == 'text':
                        txt = str(getattr(block, 'text', '') or '')
                        if txt:
                            text_parts.append(txt)
                text = '\n'.join(text_parts).strip()
                usage = getattr(response, 'usage', None)
                prompt_tokens = int(getattr(usage, 'input_tokens', 0) or 0)
                completion_tokens = int(getattr(usage, 'output_tokens', 0) or 0)
                total_tokens = prompt_tokens + completion_tokens
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
                    usage=SimpleNamespace(
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                    ),
                    model=candidate,
                )
            except Exception as exc:
                last_error = exc
                continue
        if last_error:
            raise last_error
        raise RuntimeError('No valid Anthropic model candidates configured')


def get_llm_client():
    api_key = _anthropic_api_key()
    if not api_key:
        raise RuntimeError('ANTHROPIC_API_KEY not set in environment')
    return _AnthropicCompatClient(api_key)


def _extract_json_object(text):
    """Parse JSON object from model output (raw JSON or fenced/embedded JSON)."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if not json_match:
            raise ValueError("Could not parse JSON from LLM response")
        return json.loads(json_match.group())


def _clean_scorecard_text(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_int(value):
    parsed = _safe_float(value)
    if parsed is None:
        return None
    return int(round(parsed))


def _normalize_score_value(value):
    parsed = _safe_float(value)
    if parsed is None:
        return None
    return max(0, min(100, int(round(parsed))))


def _normalize_metric_field(value, kind='text'):
    raw = _clean_scorecard_text(value)
    numeric = None

    if kind in {'currency', 'percentage'}:
        numeric = _safe_float(value)
    elif kind == 'duration':
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            numeric = float(value)
        elif isinstance(value, str):
            match = re.search(r'-?\d+(?:\.\d+)?', value.replace(',', ''))
            if match:
                try:
                    numeric = float(match.group())
                except Exception:
                    numeric = None
    elif kind == 'number':
        numeric = _safe_float(value)

    return raw, numeric


def _normalize_metric_group(raw_group, field_types):
    source = raw_group if isinstance(raw_group, dict) else {}
    normalized = {}
    numeric_map = {}
    for key, kind in field_types.items():
        raw_value, numeric_value = _normalize_metric_field(source.get(key), kind=kind)
        normalized[key] = raw_value
        numeric_map[key] = numeric_value
    normalized['_numeric'] = numeric_map
    return normalized


def _metric_numeric_value(group, key):
    if not isinstance(group, dict):
        return None
    numeric_map = group.get('_numeric')
    if isinstance(numeric_map, dict):
        numeric_value = _safe_float(numeric_map.get(key))
        if numeric_value is not None:
            return numeric_value
    return _safe_float(group.get(key))


def _group_has_values(group):
    if not isinstance(group, dict):
        return False
    for key, value in group.items():
        if key == '_numeric':
            continue
        if value not in (None, '', []):
            return True
    return False


def _list_has_values(items):
    return isinstance(items, list) and any(item not in (None, '', [], {}) for item in items)


def _section_provenance(has_values, *, estimated=False, uploaded=False):
    if not has_values:
        return 'missing'
    if uploaded:
        return 'uploaded_data'
    if estimated:
        return 'estimated'
    return 'derived_from_conversation'


def _normalize_scorecard_payload(payload):
    source = payload if isinstance(payload, dict) else {}
    normalized = dict(source)

    jaspen_score = _normalize_score_value(
        source.get('jaspen_score')
        if source.get('jaspen_score') is not None
        else source.get('overall_score')
    )
    normalized['jaspen_score'] = jaspen_score if jaspen_score is not None else 0
    normalized['score_category'] = _scores_category_from_values(
        normalized['jaspen_score'],
        explicit_category=source.get('score_category'),
    )

    component_source = source.get('component_scores') if isinstance(source.get('component_scores'), dict) else {}
    component_fallback = source.get('scores') if isinstance(source.get('scores'), dict) else {}
    component_scores = {}
    for key in ('financial_health', 'operational_efficiency', 'market_position', 'execution_readiness'):
        component_scores[key] = _normalize_score_value(component_source.get(key))
        if component_scores[key] is None:
            component_scores[key] = _normalize_score_value(component_fallback.get(key))
        if component_scores[key] is None:
            component_scores[key] = 0
    normalized['component_scores'] = component_scores

    component_rationale_source = source.get('component_rationale') if isinstance(source.get('component_rationale'), dict) else {}
    normalized['component_rationale'] = {
        key: _clean_scorecard_text(component_rationale_source.get(key))
        for key in ('financial_health', 'operational_efficiency', 'market_position', 'execution_readiness')
    }
    normalized['executive_summary'] = _clean_scorecard_text(
        source.get('executive_summary') or source.get('executive_narrative')
    )

    normalized['financial_impact'] = _normalize_metric_group(
        source.get('financial_impact'),
        {
            'ebitda_at_risk': 'percentage',
            'potential_loss': 'currency',
            'roi_opportunity': 'percentage',
            'projected_ebitda': 'currency',
            'time_to_market_impact': 'duration',
        },
    )

    before_after_source = source.get('before_after_financials') if isinstance(source.get('before_after_financials'), dict) else {}
    normalized['before_after_financials'] = {
        'before': _normalize_metric_group(
            before_after_source.get('before'),
            {
                'revenue': 'currency',
                'ebitda': 'currency',
                'margin': 'percentage',
                'growth_rate': 'percentage',
            },
        ),
        'after': _normalize_metric_group(
            before_after_source.get('after'),
            {
                'revenue': 'currency',
                'ebitda': 'currency',
                'margin': 'percentage',
                'growth_rate': 'percentage',
            },
        ),
    }

    normalized['investment_analysis'] = _normalize_metric_group(
        source.get('investment_analysis'),
        {
            'total_investment_required': 'currency',
            'expected_annual_return': 'currency',
            'payback_period': 'duration',
            'cost_of_inaction': 'currency',
        },
    )

    normalized['npv_irr_analysis'] = _normalize_metric_group(
        source.get('npv_irr_analysis'),
        {
            'npv_3_year': 'currency',
            'irr': 'percentage',
            'discount_rate_used': 'percentage',
            'break_even_month': 'number',
        },
    )

    normalized['valuation'] = _normalize_metric_group(
        source.get('valuation'),
        {
            'enterprise_value': 'currency',
            'multiple': 'number',
            'basis': 'text',
            'comparable_range': 'text',
        },
    )

    decision_source = source.get('decision_framework') if isinstance(source.get('decision_framework'), dict) else {}
    decision_confidence_raw, decision_confidence_numeric = _normalize_metric_field(
        decision_source.get('confidence_level'),
        kind='percentage',
    )
    normalized['decision_framework'] = {
        'go_no_go': _clean_scorecard_text(decision_source.get('go_no_go')),
        'confidence_level': decision_confidence_raw,
        'key_condition': _clean_scorecard_text(decision_source.get('key_condition')),
        'downside_scenario': _clean_scorecard_text(decision_source.get('downside_scenario')),
        'upside_scenario': _clean_scorecard_text(decision_source.get('upside_scenario')),
        '_numeric': {
            'confidence_level': decision_confidence_numeric,
        },
    }

    def _normalize_string_list(value):
        if not isinstance(value, list):
            return []
        items = []
        for item in value:
            cleaned = _clean_scorecard_text(item)
            if cleaned:
                items.append(cleaned)
        return items

    normalized['key_insights'] = _normalize_string_list(source.get('key_insights'))
    normalized['assumptions'] = _normalize_string_list(source.get('assumptions'))
    assumptions_joined = ' '.join(normalized['assumptions']).lower()
    has_financial_assumptions = any(
        token in assumptions_joined
        for token in (
            'financial', 'ebitda', 'roi', 'loss', 'revenue', 'margin',
            'cost', 'payback', 'npv', 'irr', 'valuation', 'budget',
        )
    )

    risk_items = []
    for item in source.get('top_risks') if isinstance(source.get('top_risks'), list) else []:
        if not isinstance(item, dict):
            cleaned = _clean_scorecard_text(item)
            if cleaned:
                risk_items.append({
                    'risk': cleaned,
                    'probability': None,
                    'impact_dollars': None,
                    'impact_category': None,
                    'impact': None,
                    'mitigation': None,
                    'mitigation_cost': None,
                    'residual_risk': None,
                })
            continue
        impact_raw, impact_numeric = _normalize_metric_field(
            item.get('impact_dollars') if item.get('impact_dollars') is not None else item.get('impact'),
            kind='currency',
        )
        mitigation_cost_raw, mitigation_cost_numeric = _normalize_metric_field(
            item.get('mitigation_cost'),
            kind='currency',
        )
        risk_text = _clean_scorecard_text(item.get('risk'))
        mitigation = _clean_scorecard_text(item.get('mitigation'))
        probability = _clean_scorecard_text(item.get('probability'))
        if probability not in {'High', 'Medium', 'Low'}:
            probability = None
        residual_risk = _clean_scorecard_text(item.get('residual_risk'))
        if residual_risk not in {'High', 'Medium', 'Low'}:
            residual_risk = None
        impact_category = _clean_scorecard_text(item.get('impact_category'))
        if impact_category not in {'financial_health', 'operational_efficiency', 'market_position', 'execution_readiness'}:
            impact_category = None
        if not any((risk_text, impact_raw, mitigation, probability, residual_risk, impact_category)):
            continue
        risk_items.append({
            **item,
            'risk': risk_text,
            'probability': probability,
            'impact_dollars': impact_raw,
            'impact_category': impact_category,
            'impact': impact_raw,
            'impact_numeric': impact_numeric,
            'mitigation': mitigation,
            'mitigation_cost': mitigation_cost_raw,
            'mitigation_cost_numeric': mitigation_cost_numeric,
            'residual_risk': residual_risk,
        })
    normalized['top_risks'] = risk_items

    recommendation_items = []
    raw_recommendations = source.get('recommendations') if isinstance(source.get('recommendations'), list) else []
    for index, item in enumerate(raw_recommendations, start=1):
        if not isinstance(item, dict):
            action = _clean_scorecard_text(item)
            if not action:
                continue
            recommendation_items.append({
                'action': action,
                'expected_impact': None,
                'effort': None,
                'timeline': None,
                'priority': index,
            })
            continue
        action = _clean_scorecard_text(item.get('action'))
        impact = _clean_scorecard_text(item.get('expected_impact'))
        effort = _clean_scorecard_text(item.get('effort'))
        timeline = _clean_scorecard_text(item.get('timeline'))
        priority = _safe_int(item.get('priority')) or index
        if not any((action, impact, effort, timeline)):
            continue
        recommendation_items.append({
            **item,
            'action': action,
            'expected_impact': impact,
            'effort': effort,
            'timeline': timeline,
            'priority': max(1, priority),
        })
    recommendation_items.sort(key=lambda item: item.get('priority') or 9999)
    normalized['recommendations'] = recommendation_items

    normalized['ai_insights'] = source.get('ai_insights') if isinstance(source.get('ai_insights'), list) else []
    normalized['section_provenance'] = {
        'component_scores': _section_provenance(any(value > 0 for value in normalized['component_scores'].values())),
        'component_rationale': _section_provenance(any(normalized['component_rationale'].values())),
        'financial_impact': _section_provenance(_group_has_values(normalized['financial_impact']), estimated=has_financial_assumptions),
        'before_after_financials': _section_provenance(
            _group_has_values(normalized['before_after_financials'].get('before')) or _group_has_values(normalized['before_after_financials'].get('after')),
            estimated=has_financial_assumptions,
        ),
        'investment_analysis': _section_provenance(_group_has_values(normalized['investment_analysis']), estimated=has_financial_assumptions),
        'npv_irr_analysis': _section_provenance(_group_has_values(normalized['npv_irr_analysis']), estimated=has_financial_assumptions),
        'valuation': _section_provenance(_group_has_values(normalized['valuation']), estimated=has_financial_assumptions),
        'decision_framework': _section_provenance(_group_has_values(normalized['decision_framework']), estimated=bool(normalized['assumptions'])),
        'executive_summary': _section_provenance(bool(normalized['executive_summary'])),
        'key_insights': _section_provenance(_list_has_values(normalized['key_insights'])),
        'top_risks': _section_provenance(_list_has_values(normalized['top_risks'])),
        'recommendations': _section_provenance(_list_has_values(normalized['recommendations'])),
        'ai_insights': _section_provenance(_list_has_values(normalized['ai_insights']), uploaded=True),
        'assumptions': _section_provenance(_list_has_values(normalized['assumptions']), estimated=bool(normalized['assumptions'])),
    }

    return normalized


def _merge_scorecard_patch(base_scorecard, patch):
    base = base_scorecard if isinstance(base_scorecard, dict) else {}
    update = patch if isinstance(patch, dict) else {}
    merged = dict(base)

    editable_dict_keys = {'component_rationale', 'decision_framework'}
    editable_list_keys = {'key_insights', 'top_risks', 'recommendations', 'assumptions'}
    editable_scalar_keys = {'executive_summary'}

    for key in editable_dict_keys:
        value = update.get(key)
        if isinstance(value, dict):
            merged[key] = value

    for key in editable_list_keys:
        value = update.get(key)
        if isinstance(value, list):
            merged[key] = value

    for key in editable_scalar_keys:
        value = _clean_scorecard_text(update.get(key))
        if value:
            merged[key] = value

    return _normalize_scorecard_payload(merged)


def _scorecard_snapshot_state(scorecard_result, thread_id):
    result = scorecard_result if isinstance(scorecard_result, dict) else {}
    baseline = result.get('_baseline_scorecard') if isinstance(result.get('_baseline_scorecard'), dict) else None
    snapshots = result.get('scorecard_snapshots') if isinstance(result.get('scorecard_snapshots'), list) else []
    selected_id = str(result.get('selected_scorecard_id') or '').strip() or None
    normalized_snapshots = []

    if baseline:
        normalized_baseline = _normalize_scorecard_payload(baseline)
        normalized_baseline.setdefault('id', str(normalized_baseline.get('analysis_id') or thread_id))
        normalized_baseline['isBaseline'] = True
        normalized_baseline['label'] = normalized_baseline.get('label') or 'Baseline'
        normalized_baseline['createdAt'] = normalized_baseline.get('createdAt') or normalized_baseline.get('timestamp')
        normalized_snapshots.append(normalized_baseline)
    else:
        normalized_baseline = None

    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        normalized_snapshot = _normalize_scorecard_payload(snapshot)
        normalized_snapshot['id'] = str(
            normalized_snapshot.get('id')
            or normalized_snapshot.get('analysis_id')
            or uuid.uuid4()
        )
        normalized_snapshot['label'] = normalized_snapshot.get('label') or (
            'Baseline' if normalized_snapshot.get('isBaseline') else 'Edited scorecard'
        )
        normalized_snapshot['isBaseline'] = bool(normalized_snapshot.get('isBaseline'))
        normalized_snapshot['createdAt'] = normalized_snapshot.get('createdAt') or normalized_snapshot.get('timestamp')
        if normalized_snapshot['isBaseline']:
            if normalized_baseline is None:
                normalized_baseline = normalized_snapshot
            continue
        normalized_snapshots.append(normalized_snapshot)

    if normalized_baseline is None:
        normalized_baseline = _normalize_scorecard_payload(result)
        normalized_baseline['id'] = str(normalized_baseline.get('analysis_id') or thread_id)
        normalized_baseline['isBaseline'] = True
        normalized_baseline['label'] = normalized_baseline.get('label') or 'Baseline'
        normalized_baseline['createdAt'] = normalized_baseline.get('createdAt') or normalized_baseline.get('timestamp')
        normalized_snapshots.insert(0, normalized_baseline)

    deduped = []
    seen_ids = set()
    for snapshot in normalized_snapshots:
        snapshot_id = str(snapshot.get('id') or '')
        if not snapshot_id or snapshot_id in seen_ids:
            continue
        seen_ids.add(snapshot_id)
        deduped.append(snapshot)

    selected_snapshot = None
    if selected_id:
        selected_snapshot = next((item for item in deduped if item.get('id') == selected_id), None)
    if not selected_snapshot:
        selected_snapshot = normalized_baseline
        selected_id = selected_snapshot.get('id')

    return {
        'baseline': normalized_baseline,
        'snapshots': deduped,
        'selected_id': selected_id,
        'selected_snapshot': selected_snapshot,
    }


def _load_thread_conversation(user_id, thread_id):
    """
    Load stored conversation history for a thread from user session storage.
    Returns [] when no matching thread/session is found.
    """
    try:
        sessions = load_user_sessions(user_id) or {}
    except Exception as e:
        current_app.logger.error("[strategy.analyze] failed reading sessions for user %s: %s", user_id, e)
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


def _generate_jaspen_scorecard(
    client,
    project_description,
    llm_model,
    *,
    model_selection=None,
    strategy_objective='balanced',
):
    """Run the existing LLM scoring flow and return parsed scorecard JSON."""
    system_prompt = (
        "You are a Jaspen strategy analyst specializing in commercialization strategy. "
        "Always respond with valid JSON only."
    )
    analysis_prompt = f"""
You are a Jaspen strategy analyst specializing in commercialization strategy and financial impact assessment. Analyze the following project and provide a comprehensive strategy score and breakdown.

Project Description: {project_description}

Strategy Objective: {_normalize_strategy_objective(strategy_objective)}
Objective Guidance: {_scorecard_objective_guidance(strategy_objective)}

Return a single valid JSON object only. Do not include markdown fences, commentary, or explanatory text outside the JSON.

Use null for any field that cannot be supported from the provided information. Do not invent benchmarks or placeholder prose.

Every numeric, currency, percentage, or time-based field must contain an actual numeric value when present. Do not use words like "significant", "varies", "material", or "TBD". Examples of acceptable values:
- "$250000"
- "18%"
- "6 months"
- 14
- 7.5

If a field is null because information is missing, add a short explanation to the assumptions array describing what data would be needed.

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
    "component_rationale": {{
        "financial_health": "<2-3 sentence explanation or null>",
        "operational_efficiency": "<2-3 sentence explanation or null>",
        "market_position": "<2-3 sentence explanation or null>",
        "execution_readiness": "<2-3 sentence explanation or null>"
    }},
    "executive_summary": "<2-4 sentence board-ready summary of the score, current opportunity, and biggest constraint or null>",
    "financial_impact": {{
        "ebitda_at_risk": "<percentage or null>",
        "potential_loss": "<dollar amount or null>",
        "roi_opportunity": "<percentage or null>",
        "projected_ebitda": "<dollar amount or null>",
        "time_to_market_impact": "<numeric duration impact or null>"
    }},
    "before_after_financials": {{
        "before": {{
            "revenue": "<dollar amount or null>",
            "ebitda": "<dollar amount or null>",
            "margin": "<percentage or null>",
            "growth_rate": "<percentage or null>"
        }},
        "after": {{
            "revenue": "<dollar amount or null>",
            "ebitda": "<dollar amount or null>",
            "margin": "<percentage or null>",
            "growth_rate": "<percentage or null>"
        }}
    }},
    "investment_analysis": {{
        "total_investment_required": "<dollar amount or null>",
        "expected_annual_return": "<dollar amount or null>",
        "payback_period": "<numeric duration or null>",
        "cost_of_inaction": "<dollar amount per year or null>"
    }},
    "npv_irr_analysis": {{
        "npv_3_year": "<dollar amount or null>",
        "irr": "<percentage or null>",
        "discount_rate_used": "<percentage or null>",
        "break_even_month": <integer or null>
    }},
    "valuation": {{
        "enterprise_value": "<dollar amount or null>",
        "multiple": <number or null>,
        "basis": "<revenue|ebitda|arr|null>",
        "comparable_range": "<numeric dollar range or null>"
    }},
    "decision_framework": {{
        "go_no_go": "<GO|CONDITIONAL|NO-GO|null>",
        "confidence_level": "<percentage or null>",
        "key_condition": "<single biggest prerequisite or null>",
        "downside_scenario": "<worst-case outcome or null>",
        "upside_scenario": "<best-case outcome or null>"
    }},
    "key_insights": [
        "<insight 1>",
        "<insight 2>",
        "<insight 3>"
    ],
    "top_risks": [
        {{
            "risk": "<risk description>",
            "probability": "<High|Medium|Low|null>",
            "impact_dollars": "<numeric dollar amount or null>",
            "impact_category": "<financial_health|operational_efficiency|market_position|execution_readiness|null>",
            "mitigation": "<mitigation strategy or null>",
            "mitigation_cost": "<numeric dollar amount or null>",
            "residual_risk": "<High|Medium|Low|null>"
        }}
    ],
    "recommendations": [
        {{
            "action": "<action description>",
            "expected_impact": "<expected quantified outcome>",
            "effort": "<Low/Medium/High>",
            "timeline": "<timeframe>",
            "priority": <positive integer>
        }}
    ],
    "assumptions": [
        "<short note describing any missing data, null field, or estimation dependency>"
    ]
}}

Focus on:
1. EBITDA protection and optimization
2. ROI maximization opportunities
3. Time-to-market acceleration
4. Operational efficiency improvements
5. Market positioning and competitive advantage

Provide specific, actionable insights with quantified financial impacts where the conversation supports them. When it does not, keep the affected field null and explain the gap in assumptions.

The executive_summary must read like a concise leadership briefing. It should never repeat raw prompt text or user questions.
"""

    if isinstance(model_selection, dict):
        try:
            from .ai_agent import _generate_routed_chat_reply

            routed_text, _usage = _generate_routed_chat_reply(
                [{"role": "user", "content": analysis_prompt}],
                model_selection,
                system_prompt=system_prompt,
                strategy_objective=strategy_objective,
                max_tokens=4000,
                temperature=0.2,
            )
            return _normalize_scorecard_payload(_extract_json_object(routed_text))
        except Exception as routed_exc:
            current_app.logger.warning(
                "[strategy.analyze] routed scorecard generation failed, falling back to legacy client: %s",
                routed_exc,
            )

    response = client.chat.completions.create(
        model=llm_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": analysis_prompt}
        ],
        temperature=0.7,
        max_tokens=4000
    )

    analysis_text = response.choices[0].message.content
    return _normalize_scorecard_payload(_extract_json_object(analysis_text))


@strategy_bp.route('/analyze', methods=['POST'])
@jwt_required()
@limiter.limit("5 per minute")
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

        client = get_llm_client()
        session_key, current_session = _resolve_session_entry(
            load_user_sessions(current_user_id) or {},
            thread_id,
        ) if thread_id else (None, None)
        strategy_objective = _normalize_strategy_objective(
            data.get('strategy_objective')
            or (current_session or {}).get('strategy_objective')
            or 'balanced'
        )
        analysis_result = _generate_jaspen_scorecard(
            client,
            effective_description,
            llm_model=model_selection['llm_model'],
            model_selection=model_selection,
            strategy_objective=strategy_objective,
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
        _audit_strategy_event(
            'scorecard.generated',
            user=user,
            details={
                'thread_id': resolved_thread_id,
                'analysis_id': analysis_id,
                'project_name': project_name,
                'credits_charged': analysis_credit_cost,
                'model_type': model_selection['model_type'],
            },
        )

        return jsonify({
            'analysis': analysis,
            'thread_id': resolved_thread_id,
            'session_id': resolved_thread_id,
            'model_type': model_selection['model_type'],
            'allowed_model_types': model_selection['allowed_model_types'],
        }), 200

    except Exception as e:
        current_app.logger.error("Error in Jaspen analysis: %s", e)
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
        
        # Initialize Anthropic-backed LLM client
        client = get_llm_client()
        
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

        # Call LLM API
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
        current_app.logger.error("Error in Jaspen chat: %s", e)
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
        current_app.logger.error("Error retrieving analysis history: %s", e)
        return jsonify({'error': 'Failed to retrieve history.'}), 500


@strategy_bp.route('/scores', methods=['GET'])
@jwt_required()
def get_completed_scores():
    """Return completed score rows for the authenticated user."""
    try:
        current_user_id = get_jwt_identity()

        sort_by = str(request.args.get('sort_by', 'date') or 'date').strip().lower()
        if sort_by not in _SCORES_SORT_BY_OPTIONS:
            sort_by = 'date'

        sort_dir = str(request.args.get('sort_dir', 'desc') or 'desc').strip().lower()
        if sort_dir not in _SCORES_SORT_DIR_OPTIONS:
            sort_dir = 'desc'

        category_filter = request.args.get('category')
        if isinstance(category_filter, str):
            category_filter = category_filter.strip()
            if category_filter.lower() in ('', 'all'):
                category_filter = None
            elif category_filter not in _SCORES_CATEGORY_OPTIONS:
                return jsonify({'error': 'category must be one of Excellent, Good, Fair, At Risk'}), 400
        else:
            category_filter = None

        search = str(request.args.get('search', '') or '').strip().lower()
        limit = _scores_parse_int(request.args.get('limit'), default=50, min_value=1, max_value=500)
        offset = _scores_parse_int(request.args.get('offset'), default=0, min_value=0)

        scores = _collect_completed_scores(
            current_user_id,
            sort_by=sort_by,
            sort_dir=sort_dir,
            category_filter=category_filter,
            search=search,
        )
        total = len(scores)
        paged = scores[offset:offset + limit]
        return jsonify({
            'scores': paged,
            'total': total,
            'limit': limit,
            'offset': offset,
        }), 200
    except Exception as e:
        current_app.logger.error("[get_completed_scores] %s", e)
        return jsonify({'error': 'Failed to load completed scores'}), 500


@strategy_bp.route('/scores/portfolio-agent', methods=['POST'])
@jwt_required()
@limiter.limit("10 per minute")
def portfolio_scores_agent():
    try:
        data = request.get_json() or {}
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        if bootstrap_legacy_credits(user, current_app.config):
            db.session.commit()

        message = str(data.get('message') or '').strip()
        if not message:
            return jsonify({'error': 'Message is required'}), 400

        requested_model_type = data.get('model_type')
        model_selection, model_error = _resolve_user_model_selection(user, requested_model_type=requested_model_type)
        if model_error:
            return jsonify(model_error), 403

        sort_by = str(data.get('sort_by', 'date') or 'date').strip().lower()
        if sort_by not in _SCORES_SORT_BY_OPTIONS:
            sort_by = 'date'

        sort_dir = str(data.get('sort_dir', 'desc') or 'desc').strip().lower()
        if sort_dir not in _SCORES_SORT_DIR_OPTIONS:
            sort_dir = 'desc'

        category_filter = data.get('category')
        if isinstance(category_filter, str):
            category_filter = category_filter.strip()
            if category_filter.lower() in ('', 'all'):
                category_filter = None
            elif category_filter not in _SCORES_CATEGORY_OPTIONS:
                return jsonify({'error': 'category must be one of Excellent, Good, Fair, At Risk'}), 400
        else:
            category_filter = None

        search = str(data.get('search', '') or '').strip().lower()
        strategy_objective = _normalize_strategy_objective(data.get('strategy_objective'), default='balanced')

        scores = _collect_completed_scores(
            current_user_id,
            sort_by=sort_by,
            sort_dir=sort_dir,
            category_filter=category_filter,
            search=search,
        )
        if not scores:
            return jsonify({
                'reply': (
                    "I don't have any scored projects in this view yet. "
                    "Broaden the filters or complete a few analyses first, then I can help you prioritize what to do next."
                ),
                'usage': {'provider': 'heuristic', 'model': None, 'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0},
                'credits': {'charged': 0, 'remaining': int(user.credits_remaining or 0)},
                'context': {'total_matching': 0, 'analyzed_count': 0, 'category': category_filter or 'All', 'search': search},
                'model_type': model_selection['model_type'],
                'strategy_objective': strategy_objective,
            }), 200

        history = data.get('messages') if isinstance(data.get('messages'), list) else []
        sanitized_history = []
        for item in history[-8:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get('role') or '').strip().lower()
            if role not in {'user', 'assistant'}:
                continue
            content = str(item.get('content') or '').strip()
            if not content:
                continue
            sanitized_history.append({'role': role, 'content': content[:4000]})

        summarized_rows = _portfolio_agent_score_rows(scores, max_rows=30)
        system_prompt = (
            "You are Jaspen's portfolio agent for strategic prioritization. "
            "Your job is to recommend what the user should do next across their scored project portfolio. "
            "Do not simply pick the highest score. Prefer one of the stronger-scoring projects when it also has better readiness, "
            "clearer upside, fewer unresolved gaps, stronger timing, or a more compelling execution path. "
            "If the absolute top score is not the best next move, say that directly and explain why. "
            "Use only the portfolio data provided. Be decisive, practical, and specific. "
            "Keep the answer concise, usually 2-4 short paragraphs or a compact bullet list."
        )
        context_prompt = (
            f"Portfolio scope: {len(scores)} matching scored projects.\n"
            f"Current filters: category={category_filter or 'All'}, search={search or 'none'}, sort={sort_by} {sort_dir}.\n"
            "Scored projects:\n"
            f"{json.dumps(summarized_rows, ensure_ascii=True)}\n\n"
            "When recommending the next project, weigh Jaspen score alongside component strengths/weaknesses, "
            "financial impact clues, recency, and whether an adopted scenario suggests the path is more executable."
        )
        routed_messages = [
            *sanitized_history,
            {'role': 'user', 'content': f"{context_prompt}\n\nUser request: {message}"},
        ]

        from .ai_agent import _estimate_usage_credit_charge, _generate_routed_chat_reply

        reply, usage = _generate_routed_chat_reply(
            routed_messages,
            model_selection,
            system_prompt=system_prompt,
            strategy_objective=strategy_objective,
            max_tokens=900,
            temperature=0.2,
        )
        credits_charged = _estimate_usage_credit_charge((usage or {}).get('total_tokens'), model_selection['model_type'])
        charged, remaining = consume_credits(user, credits_charged)
        if not charged:
            db.session.rollback()
            return jsonify({
                'error': 'Insufficient credits.',
                'code': 'insufficient_credits',
                'required_credits': credits_charged,
                'remaining_credits': int(user.credits_remaining or 0),
            }), 402

        _audit_strategy_event(
            'scores.portfolio_agent_used',
            user=user,
            details={
                'matching_scores': len(scores),
                'analyzed_count': len(summarized_rows),
                'model_type': model_selection['model_type'],
                'provider': usage.get('provider') if isinstance(usage, dict) else None,
                'model': usage.get('model') if isinstance(usage, dict) else None,
                'credits_charged': credits_charged,
            },
        )
        db.session.commit()
        return jsonify({
            'reply': reply,
            'usage': usage,
            'credits': {'charged': credits_charged, 'remaining': remaining},
            'context': {
                'total_matching': len(scores),
                'analyzed_count': len(summarized_rows),
                'category': category_filter or 'All',
                'search': search,
            },
            'model_type': model_selection['model_type'],
            'strategy_objective': strategy_objective,
        }), 200
    except Exception as e:
        current_app.logger.error("[portfolio_scores_agent] %s", e)
        return jsonify({'error': 'Portfolio agent failed. Please try again.'}), 500


def _load_scenarios(user_id):
    return load_scenarios_data(user_id) or {}

def _save_scenarios(user_id, data):
    return save_scenarios_data(user_id, data)

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


def _thread_levers_for_scenario_ai(user_id, thread_id, baseline_inputs, suggested_deltas=None):
    """
    Build lever metadata using the same internal helper as
    GET /api/v1/ai-agent/threads/<thread_id>/levers when possible.
    """
    try:
        from .ai_agent import _build_thread_levers as _agent_build_thread_levers
        from .ai_agent import _resolve_user_session as _agent_resolve_user_session
    except Exception:
        _agent_build_thread_levers = None
        _agent_resolve_user_session = None

    lever_rows = []
    if _agent_build_thread_levers and _agent_resolve_user_session:
        try:
            sessions = load_user_sessions(user_id) or {}
            _, session = _agent_resolve_user_session(sessions, thread_id)
            if isinstance(session, dict):
                lever_rows = _agent_build_thread_levers(session) or []
        except Exception:
            lever_rows = []

    if not lever_rows:
        lever_rows = _build_lever_context(baseline_inputs, suggested_deltas)
    else:
        suggested_map = suggested_deltas if isinstance(suggested_deltas, dict) else {}
        normalized = []
        for row in lever_rows:
            if not isinstance(row, dict) or not row.get('key'):
                continue
            key = str(row.get('key'))
            current = _safe_float(row.get('current'))
            if current is None:
                current = _safe_float((baseline_inputs or {}).get(key))
            if current is None:
                continue
            lever_type = str(row.get('type') or _infer_lever_type(key))
            bounds = _lever_bounds(current, lever_type)
            suggested = _safe_float(suggested_map.get(key))
            normalized.append({
                'key': key,
                'label': str(row.get('label') or key).strip() or key,
                'type': lever_type,
                'current': current,
                'suggested': suggested if suggested is not None else current,
                'min': _safe_float(row.get('min')) if _safe_float(row.get('min')) is not None else bounds['min'],
                'max': _safe_float(row.get('max')) if _safe_float(row.get('max')) is not None else bounds['max'],
                'step': _safe_float(row.get('step')) if _safe_float(row.get('step')) is not None else bounds['step'],
            })
        lever_rows = normalized

    return lever_rows


def _scenario_adjustments_payload(baseline_inputs, deltas, per_lever_rationale=None):
    per_lever = per_lever_rationale if isinstance(per_lever_rationale, dict) else {}
    rows = []
    for lever_id, new_value in (deltas or {}).items():
        old_value = _safe_float((baseline_inputs or {}).get(lever_id))
        reason = str(per_lever.get(lever_id) or '').strip()
        rows.append({
            'lever_id': lever_id,
            'old_value': old_value,
            'new_value': _safe_float(new_value),
            'reason': reason or f"Adjusted {str(lever_id).replace('_', ' ')} per requested outcome.",
        })
    return rows


def _objective_guidance(objective):
    target = _normalize_strategy_objective(objective)
    if target == 'cost':
        return 'Focus on cost optimization: reduce spend and execution drag while protecting outcomes.'
    if target == 'speed':
        return 'Focus on speed-to-market: shorten timeline and unblock dependencies, even if spend increases moderately.'
    if target == 'growth':
        return 'Focus on growth: prioritize demand, expansion, and revenue acceleration.'
    return 'Keep tradeoffs balanced across cost, speed, and growth.'


def _scorecard_objective_guidance(objective):
    target = _normalize_strategy_objective(objective)
    if target == 'cost':
        return (
            "Weight the scorecard toward cost reduction, margin expansion, and capital efficiency. "
            "Financial projections should emphasize savings, avoided waste, and cost-per-unit improvement."
        )
    if target == 'speed':
        return (
            "Weight the scorecard toward time-to-market, execution velocity, and quick wins. "
            "Recommendations should prioritize fast impact, dependency removal, and shorter payback horizons."
        )
    if target == 'growth':
        return (
            "Weight the scorecard toward revenue growth, market expansion, and customer acquisition. "
            "Financial projections should emphasize top-line upside, adoption, and addressable-market capture."
        )
    return (
        "Provide an even-weighted analysis across financial health, operational efficiency, "
        "market position, and execution readiness."
    )


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
        return {
            'label': 'AI Scenario',
            'summary': 'No baseline levers available.',
            'deltas': {},
            'rationale': 'No compatible levers were available for this request.',
            'reasons': {},
        }

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
    reason_text = (
        f"Adjusted {lever_key.replace('_', ' ')} by about {int(round(pct * 100))}% "
        f"to support a {objective} objective."
    )
    return {
        'label': 'AI Suggested Scenario',
        'summary': f'Generated from your request with a {objective} objective profile.',
        'deltas': deltas,
        'rationale': reason_text,
        'reasons': {lever_key: reason_text},
    }


def _generate_ai_scenario_suggestion(
    client,
    llm_model,
    instruction,
    baseline_inputs,
    objective='balanced',
    baseline_scorecard=None,
    lever_definitions=None,
):
    objective = _normalize_strategy_objective(objective)
    lever_catalog = []
    source_rows = lever_definitions if isinstance(lever_definitions, list) else []
    if source_rows:
        for row in source_rows:
            if not isinstance(row, dict) or not row.get('key'):
                continue
            key = str(row.get('key'))
            current = _safe_float(row.get('current'))
            if current is None:
                current = _safe_float((baseline_inputs or {}).get(key))
            if current is None:
                continue
            lever_type = str(row.get('type') or _infer_lever_type(key))
            bounds = _lever_bounds(current, lever_type)
            lever_catalog.append({
                'lever_id': key,
                'current': current,
                'type': lever_type,
                'min': _safe_float(row.get('min')) if _safe_float(row.get('min')) is not None else bounds.get('min'),
                'max': _safe_float(row.get('max')) if _safe_float(row.get('max')) is not None else bounds.get('max'),
                'step': _safe_float(row.get('step')) if _safe_float(row.get('step')) is not None else bounds.get('step'),
            })
    else:
        for key, val in (baseline_inputs or {}).items():
            num = _safe_float(val)
            if num is None:
                continue
            lever_type = _infer_lever_type(key)
            bounds = _lever_bounds(num, lever_type)
            lever_catalog.append({
                'lever_id': key,
                'current': num,
                'type': lever_type,
                'min': bounds.get('min'),
                'max': bounds.get('max'),
                'step': bounds.get('step'),
            })

    if not lever_catalog:
        return _heuristic_scenario_suggestion(instruction, baseline_inputs, objective=objective)

    score_context = {}
    if isinstance(baseline_scorecard, dict):
        score_context = {
            'jaspen_score': baseline_scorecard.get('jaspen_score'),
            'score_category': baseline_scorecard.get('score_category'),
            'component_scores': baseline_scorecard.get('component_scores') if isinstance(baseline_scorecard.get('component_scores'), dict) else {},
            'financial_impact': baseline_scorecard.get('financial_impact') if isinstance(baseline_scorecard.get('financial_impact'), dict) else {},
        }

    prompt = f"""
You are helping create a strategy scenario using existing baseline levers.

User request:
{instruction}

Objective profile:
{objective}

Objective guidance:
{_objective_guidance(objective)}

Baseline score context:
{json.dumps(score_context, indent=2)}

Available levers (MUST use only these lever_id values):
{json.dumps(lever_catalog, indent=2)}

Return JSON only in this shape:
{{
  "label": "short scenario label",
  "deltas": {{
    "lever_id": 123.45
  }},
  "rationale": "short explanation of why the combined lever changes satisfy the request",
  "reasons": {{
    "lever_id": "why this specific lever changed"
  }}
}}

Rules:
- Suggest 1-6 lever changes.
- Keep values realistic relative to current levels.
- Always include rationale for every lever inside reasons.
- Do not invent new lever ids.
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
    reasons = {}
    raw_deltas = parsed.get('deltas') if isinstance(parsed, dict) else {}
    if isinstance(raw_deltas, dict):
        for raw_lever, raw_value in raw_deltas.items():
            lever_key = str(raw_lever or '').strip()
            if not lever_key:
                continue
            lever = lever_key if lever_key in baseline_inputs else by_lower.get(lever_key.lower())
            if not lever:
                continue
            value = _safe_float(raw_value)
            if value is None:
                continue
            deltas[lever] = value

    raw_reasons = parsed.get('reasons') if isinstance(parsed, dict) else {}
    if isinstance(raw_reasons, dict):
        for raw_lever, reason in raw_reasons.items():
            lever_key = str(raw_lever or '').strip()
            if not lever_key:
                continue
            lever = lever_key if lever_key in baseline_inputs else by_lower.get(lever_key.lower())
            if not lever:
                continue
            reason_text = str(reason or '').strip()
            if reason_text:
                reasons[lever] = reason_text

    if not deltas and isinstance(parsed, dict):
        # Backward compatibility: old "changes" response shape.
        for change in parsed.get('changes', []):
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
            reason_text = str(change.get('rationale') or '').strip()
            if reason_text:
                reasons[lever] = reason_text

    if not deltas:
        return _heuristic_scenario_suggestion(instruction, baseline_inputs, objective=objective)

    summary = str(parsed.get('summary') or '').strip() if isinstance(parsed, dict) else ''
    rationale = str(parsed.get('rationale') or '').strip() if isinstance(parsed, dict) else ''
    if not rationale:
        if summary:
            rationale = summary
        else:
            rationale = (
                f"Generated lever adjustments to support the {objective} objective "
                f"and the user request."
            )

    for key in deltas.keys():
        reasons.setdefault(key, f"Adjusted {key.replace('_', ' ')} to align with the requested outcome.")

    return {
        'label': str(parsed.get('label') or 'AI Suggested Scenario').strip() or 'AI Suggested Scenario',
        'summary': summary,
        'deltas': deltas,
        'rationale': rationale,
        'reasons': reasons,
    }


def _heuristic_wbs_suggestion(scorecard, instruction, scenario_payload=None):
    comps = (scorecard or {}).get('component_scores') if isinstance(scorecard, dict) else {}
    comps = comps if isinstance(comps, dict) else {}
    tasks = [
        {
            'id': 'kickoff_alignment',
            'title': 'Kickoff alignment and success criteria',
            'description': 'Align stakeholders on scope, objectives, and measurable outcomes.',
            'priority': 'high',
            'estimated_days': 5,
            'suggested_role': 'Project Manager',
            'depends_on': [],
            'risk_area': 'execution_readiness',
        },
        {
            'id': 'dependency_map',
            'title': 'Create execution cadence and dependency map',
            'description': 'Map workstream dependencies and establish execution cadence.',
            'priority': 'high',
            'estimated_days': 7,
            'suggested_role': 'Program Manager',
            'depends_on': ['kickoff_alignment'],
            'risk_area': 'execution_readiness',
        },
    ]

    if float(comps.get('financial_health') or 0) < 70:
        tasks.append({
            'id': 'financial_guardrails',
            'title': 'Run budget guardrail and ROI checkpoint',
            'description': 'Validate investment assumptions and define financial checkpoints.',
            'priority': 'high',
            'estimated_days': 7,
            'suggested_role': 'Finance Analyst',
            'depends_on': ['kickoff_alignment'],
            'risk_area': 'financial_health',
        })
    if float(comps.get('market_position') or 0) < 70:
        tasks.append({
            'id': 'market_validation',
            'title': 'Validate customer value and market assumptions',
            'description': 'Run customer and market validation to sharpen value proposition.',
            'priority': 'medium',
            'estimated_days': 10,
            'suggested_role': 'Product Marketing',
            'depends_on': ['kickoff_alignment'],
            'risk_area': 'market_position',
        })
    if float(comps.get('operational_efficiency') or 0) < 70:
        tasks.append({
            'id': 'process_optimization',
            'title': 'Map process bottlenecks and automate handoffs',
            'description': 'Identify bottlenecks and improve process handoffs.',
            'priority': 'medium',
            'estimated_days': 14,
            'suggested_role': 'Operations Lead',
            'depends_on': ['dependency_map'],
            'risk_area': 'operational_efficiency',
        })
    if float(comps.get('execution_readiness') or 0) < 70:
        tasks.append({
            'id': 'staffing_plan',
            'title': 'Staff critical roles and contingency owners',
            'description': 'Assign owners and contingency coverage for critical tasks.',
            'priority': 'high',
            'estimated_days': 6,
            'suggested_role': 'Project Manager',
            'depends_on': ['dependency_map'],
            'risk_area': 'execution_readiness',
        })

    tasks.append({
        'id': 'weekly_risk_review',
        'title': 'Weekly risk review and mitigation updates',
        'description': 'Review risk register and update mitigations weekly.',
        'priority': 'medium',
        'estimated_days': 30,
        'suggested_role': 'PMO',
        'depends_on': ['dependency_map'],
        'risk_area': 'execution_readiness',
    })

    scenario_note = ''
    if isinstance(scenario_payload, dict) and scenario_payload.get('label'):
        scenario_note = f" using scenario '{scenario_payload.get('label')}'"

    return {
        'name': 'AI Generated WBS',
        'description': str(instruction or '').strip() or 'Generated from scorecard drivers and risk profile.',
        'summary': f"Generated{scenario_note} using component score priorities and risk hotspots.",
        'phases': [
            {
                'name': 'Initiation',
                'tasks': tasks[:2],
            },
            {
                'name': 'Execution',
                'tasks': tasks[2:],
            },
        ],
    }


def _generate_ai_wbs_suggestion(client, llm_model, scorecard, instruction, scenario_payload=None):
    scorecard_payload = scorecard if isinstance(scorecard, dict) else {}
    scenario_context = scenario_payload if isinstance(scenario_payload, dict) else {}
    top_risks = scorecard_payload.get('top_risks') if isinstance(scorecard_payload.get('top_risks'), list) else scorecard_payload.get('risks')
    if not isinstance(top_risks, list):
        top_risks = []
    recommendations = scorecard_payload.get('recommendations') if isinstance(scorecard_payload.get('recommendations'), list) else []

    prompt = f"""
You are generating a project WBS from a strategy scorecard.

Instruction:
{instruction or "Generate an actionable WBS from this scorecard."}

Scorecard context:
{json.dumps(scorecard_payload, indent=2)}

Key insights:
{json.dumps(scorecard_payload.get('key_insights') or [], indent=2)}

Top risks:
{json.dumps(top_risks, indent=2)}

Recommendations:
{json.dumps(recommendations, indent=2)}

Scenario context (if provided):
{json.dumps(scenario_context, indent=2)}

Return JSON only:
{{
  "name": "WBS title",
  "description": "one paragraph",
  "summary": "short summary",
  "phases": [
    {{
      "name": "Phase Name",
      "tasks": [
        {{
          "id": "unique-task-id",
          "title": "Task title",
          "description": "What this task involves",
          "priority": "high|medium|low",
          "estimated_days": 5,
          "suggested_role": "Project Manager|Developer|Analyst|etc",
          "dependencies": ["other-task-id"],
          "risk_area": "which component score this addresses"
        }}
      ]
    }}
  ]
}}

Rules:
- Return 5-20 tasks total.
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
        if not isinstance(parsed, dict):
            raise ValueError('invalid_wbs_response')
        if not isinstance(parsed.get('phases'), list) and not isinstance(parsed.get('tasks'), list):
            raise ValueError('invalid_wbs_response')
        return parsed
    except Exception:
        return _heuristic_wbs_suggestion(scorecard, instruction, scenario_payload=scenario_context)


def _materialize_ai_wbs(wbs_payload):
    now = datetime.utcnow()
    tasks_in = []
    phases_in = []
    if isinstance(wbs_payload, dict):
        if isinstance(wbs_payload.get('phases'), list):
            phases_in = wbs_payload.get('phases')
        elif isinstance(wbs_payload.get('tasks'), list):
            phases_in = [{'name': 'Generated Plan', 'tasks': wbs_payload.get('tasks')}]

    created = []
    id_aliases = {}
    phase_rows = []
    running_order = 1

    for phase in phases_in:
        if not isinstance(phase, dict):
            continue
        phase_name = str(phase.get('name') or 'Phase').strip() or 'Phase'
        phase_task_ids = []
        raw_tasks = phase.get('tasks') if isinstance(phase.get('tasks'), list) else []

        for raw in raw_tasks:
            if not isinstance(raw, dict):
                continue
            title = str(raw.get('title') or '').strip()
            if not title:
                continue

            requested_id = str(raw.get('id') or '').strip()
            task_id = requested_id or f"task_{uuid.uuid4().hex[:10]}"
            owner = str(raw.get('owner') or raw.get('suggested_role') or raw.get('owner_role') or '').strip()
            priority = str(raw.get('priority') or '').strip().lower()
            if priority not in {'high', 'medium', 'low'}:
                priority = None
            estimated_days = raw.get('estimated_days')
            if estimated_days is None:
                estimated_days = raw.get('timeline_days')
            try:
                estimated_days = max(1, int(estimated_days)) if estimated_days is not None else None
            except Exception:
                estimated_days = None
            due_date = (now + timedelta(days=estimated_days)).date().isoformat() if estimated_days else None

            task = {
                'id': task_id,
                'title': title,
                'status': 'todo',
                'owner': owner,
                'suggested_role': owner,
                'due_date': due_date,
                'depends_on': [],
                'order': running_order,
                'phase': phase_name,
                'external_refs': {},
            }
            running_order += 1
            if priority:
                task['priority'] = priority
            if estimated_days:
                task['timeline_days'] = estimated_days
                task['estimated_days'] = estimated_days
            description = str(raw.get('description') or '').strip()
            if description:
                task['description'] = description
            rationale = str(raw.get('rationale') or '').strip()
            if rationale:
                task['rationale'] = rationale
            risk_area = str(raw.get('risk_area') or '').strip()
            if risk_area:
                task['risk_area'] = risk_area

            created.append(task)
            phase_task_ids.append(task_id)
            id_aliases[task_id.lower()] = task_id
            id_aliases[title.lower()] = task_id
            if requested_id:
                id_aliases[requested_id.lower()] = task_id

        if phase_task_ids:
            phase_rows.append({'name': phase_name, 'task_ids': phase_task_ids})

    for phase in phases_in:
        if not isinstance(phase, dict):
            continue
        raw_tasks = phase.get('tasks') if isinstance(phase.get('tasks'), list) else []
        for raw in raw_tasks:
            if not isinstance(raw, dict):
                continue
            requested_id = str(raw.get('id') or '').strip().lower()
            title_key = str(raw.get('title') or '').strip().lower()
            task_id = id_aliases.get(requested_id) or id_aliases.get(title_key)
            if not task_id:
                continue
            task = next((item for item in created if item.get('id') == task_id), None)
            if not isinstance(task, dict):
                continue
            raw_deps = raw.get('dependencies')
            if not isinstance(raw_deps, list):
                raw_deps = raw.get('depends_on') if isinstance(raw.get('depends_on'), list) else []
            deps = []
            for dep in raw_deps:
                dep_key = str(dep or '').strip().lower()
                dep_id = id_aliases.get(dep_key)
                if dep_id and dep_id != task_id and dep_id not in deps:
                    deps.append(dep_id)
            task['depends_on'] = deps

    return {
        'name': str(wbs_payload.get('name') or 'AI Generated WBS').strip() or 'AI Generated WBS',
        'description': str(wbs_payload.get('description') or '').strip(),
        'summary': str(wbs_payload.get('summary') or '').strip(),
        'phases': phase_rows,
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

    owner = str(raw_task.get('owner') or raw_task.get('suggested_role') or raw_task.get('owner_role') or '').strip()
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
    if timeline_days is None:
        timeline_days = raw_task.get('estimated_days')
    try:
        timeline_days = int(timeline_days) if timeline_days is not None else None
    except Exception:
        timeline_days = None
    if timeline_days is not None and timeline_days < 1:
        timeline_days = None

    rationale = str(raw_task.get('rationale') or '').strip() or None
    description = str(raw_task.get('description') or '').strip() or None
    suggested_role = str(raw_task.get('suggested_role') or raw_task.get('owner_role') or owner or '').strip() or None
    risk_area = str(raw_task.get('risk_area') or '').strip() or None
    phase = str(raw_task.get('phase') or '').strip() or None

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
        task['estimated_days'] = timeline_days
    if rationale:
        task['rationale'] = rationale
    if description:
        task['description'] = description
    if suggested_role:
        task['suggested_role'] = suggested_role
    if risk_area:
        task['risk_area'] = risk_area
    if phase:
        task['phase'] = phase
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
    incoming_phases = payload.get('phases')
    if not isinstance(incoming_phases, list):
        incoming_phases = base.get('phases') if isinstance(base.get('phases'), list) else []

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
        'summary': str(payload.get('summary') or base.get('summary') or '').strip(),
        'phases': incoming_phases,
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


def _fmt_percentage(num):
    if num is None:
        return None
    return f"{float(num):.1f}%"


def _fmt_months(num):
    if num is None:
        return None
    value = float(num)
    label = 'month' if abs(value) == 1 else 'months'
    if value.is_integer():
        return f"{int(value)} {label}"
    return f"{value:.1f} {label}"


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

    base_fin = baseline.get('financial_impact') if isinstance(baseline.get('financial_impact'), dict) else {}
    fin_raw = {}
    for field in ('ebitda_at_risk', 'potential_loss', 'roi_opportunity', 'projected_ebitda'):
        num = _metric_numeric_value(base_fin, field)
        if num is None:
            fin_raw[field] = _clean_scorecard_text(base_fin.get(field))
            continue
        adjusted = num / financial_factor if field in ('ebitda_at_risk', 'potential_loss') else num * financial_factor
        fin_raw[field] = _fmt_percentage(adjusted) if field in ('ebitda_at_risk', 'roi_opportunity') else _fmt_currency(adjusted)

    time_to_market_num = _metric_numeric_value(base_fin, 'time_to_market_impact')
    if time_to_market_num is not None:
        adjusted_ttm = max(0.0, time_to_market_num / max(0.75, min(1.5, financial_factor)))
        fin_raw['time_to_market_impact'] = _fmt_months(adjusted_ttm)
    else:
        fin_raw['time_to_market_impact'] = _clean_scorecard_text(base_fin.get('time_to_market_impact'))

    projected_ebitda_num = _metric_numeric_value({'_numeric': {'projected_ebitda': _safe_float(fin_raw.get('projected_ebitda'))}}, 'projected_ebitda')
    roi_num = _metric_numeric_value({'_numeric': {'roi_opportunity': _safe_float(fin_raw.get('roi_opportunity'))}}, 'roi_opportunity')

    before_after_source = baseline.get('before_after_financials') if isinstance(baseline.get('before_after_financials'), dict) else {}
    before_group = before_after_source.get('before') if isinstance(before_after_source.get('before'), dict) else {}
    after_group = before_after_source.get('after') if isinstance(before_after_source.get('after'), dict) else {}

    before_after = {'before': {}, 'after': {}}
    for phase, group in (('before', before_group), ('after', after_group)):
        for field in ('revenue', 'ebitda', 'margin', 'growth_rate'):
            num = _metric_numeric_value(group, field)
            if num is None:
                before_after[phase][field] = _clean_scorecard_text(group.get(field))
                continue
            adjusted = num if phase == 'before' else num * financial_factor
            before_after[phase][field] = _fmt_percentage(adjusted) if field in ('margin', 'growth_rate') else _fmt_currency(adjusted)

    investment_source = baseline.get('investment_analysis') if isinstance(baseline.get('investment_analysis'), dict) else {}
    total_investment_required = _metric_numeric_value(investment_source, 'total_investment_required')
    expected_annual_return = _metric_numeric_value(investment_source, 'expected_annual_return')
    cost_of_inaction = _metric_numeric_value(investment_source, 'cost_of_inaction')
    if expected_annual_return is None and projected_ebitda_num is not None:
        expected_annual_return = projected_ebitda_num
    if cost_of_inaction is None and _metric_numeric_value(base_fin, 'potential_loss') is not None:
        cost_of_inaction = _metric_numeric_value(base_fin, 'potential_loss')
    investment_analysis = {
        'total_investment_required': _fmt_currency(total_investment_required) if total_investment_required is not None else _clean_scorecard_text(investment_source.get('total_investment_required')),
        'expected_annual_return': _fmt_currency(expected_annual_return) if expected_annual_return is not None else _clean_scorecard_text(investment_source.get('expected_annual_return')),
        'cost_of_inaction': _fmt_currency(cost_of_inaction) if cost_of_inaction is not None else _clean_scorecard_text(investment_source.get('cost_of_inaction')),
        'payback_period': _clean_scorecard_text(investment_source.get('payback_period')),
    }
    if total_investment_required is not None and expected_annual_return and expected_annual_return > 0:
        investment_analysis['payback_period'] = _fmt_months((total_investment_required / expected_annual_return) * 12.0)

    npv_source = baseline.get('npv_irr_analysis') if isinstance(baseline.get('npv_irr_analysis'), dict) else {}
    discount_rate = _metric_numeric_value(npv_source, 'discount_rate_used')
    if discount_rate is None:
        discount_rate = 10.0
    npv_3_year = None
    if expected_annual_return is not None:
        yearly_rate = max(0.0, discount_rate) / 100.0
        npv_3_year = sum(expected_annual_return / ((1 + yearly_rate) ** year) for year in range(1, 4))
        if total_investment_required is not None:
            npv_3_year -= total_investment_required
    break_even_month = None
    if total_investment_required is not None and expected_annual_return and expected_annual_return > 0:
        break_even_month = int(round((total_investment_required / expected_annual_return) * 12.0))
    npv_irr_analysis = {
        'npv_3_year': _fmt_currency(npv_3_year) if npv_3_year is not None else _clean_scorecard_text(npv_source.get('npv_3_year')),
        'irr': _fmt_percentage(roi_num) if roi_num is not None else _clean_scorecard_text(npv_source.get('irr')),
        'discount_rate_used': _fmt_percentage(discount_rate),
        'break_even_month': break_even_month,
    }

    valuation_source = baseline.get('valuation') if isinstance(baseline.get('valuation'), dict) else {}
    enterprise_value = _metric_numeric_value(valuation_source, 'enterprise_value')
    if enterprise_value is not None:
        enterprise_value *= financial_factor
    multiple = _metric_numeric_value(valuation_source, 'multiple')
    valuation = {
        'enterprise_value': _fmt_currency(enterprise_value) if enterprise_value is not None else _clean_scorecard_text(valuation_source.get('enterprise_value')),
        'multiple': multiple,
        'basis': _clean_scorecard_text(valuation_source.get('basis')),
        'comparable_range': _clean_scorecard_text(valuation_source.get('comparable_range')),
    }

    result = {
        'jaspen_score': overall_int,
        'score_category': category,
        'component_scores': components,
        'financial_impact': fin_raw,
        'before_after_financials': before_after,
        'investment_analysis': investment_analysis,
        'npv_irr_analysis': npv_irr_analysis,
        'valuation': valuation,
        'inputs': deltas,
    }
    for narrative_key in (
        'project_name',
        'project_description',
        'key_insights',
        'top_risks',
        'recommendations',
        'component_rationale',
        'decision_framework',
        'assumptions',
        'ai_insights',
    ):
        if narrative_key in baseline:
            result[narrative_key] = baseline[narrative_key]

    return _normalize_scorecard_payload(result)


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
        user, plan_key, access_err = _require_tool_access(user_id, 'scenario_create', access='write')
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

        lever_context = _thread_levers_for_scenario_ai(user_id, thread_id, baseline_inputs, manual_deltas or None)

        if manual_deltas:
            suggestion = {
                'label': str(payload.get('label') or 'AI Scenario (Modified)').strip() or 'AI Scenario (Modified)',
                'summary': str(
                    payload.get('summary')
                    or f'Scenario built from your manual lever adjustments ({strategy_objective} objective).'
                ).strip(),
                'deltas': manual_deltas,
                'rationale': f"Adjusted {len(manual_deltas)} levers based on your requested edits.",
                'reasons': {
                    key: f"Set by user adjustment from {baseline_inputs.get(key)} to {value}."
                    for key, value in manual_deltas.items()
                },
            }
        else:
            client = get_llm_client()
            suggestion = _generate_ai_scenario_suggestion(
                client,
                model_selection['llm_model'],
                instruction=instruction,
                baseline_inputs=baseline_inputs,
                objective=strategy_objective,
                baseline_scorecard=baseline,
                lever_definitions=lever_context,
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
        preview['scenario_id'] = None

        reasons = suggestion.get('reasons') if isinstance(suggestion, dict) and isinstance(suggestion.get('reasons'), dict) else {}
        lever_adjustments = _scenario_adjustments_payload(baseline_inputs, deltas, reasons)
        rationale_text = str(
            (suggestion or {}).get('rationale')
            or (suggestion or {}).get('summary')
            or f"Generated {len(lever_adjustments)} lever adjustments based on your prompt."
        ).strip()

        response_payload = {
            'success': True,
            'thread_id': thread_id,
            'model_type': model_selection['model_type'],
            'strategy_objective': strategy_objective,
            'objective_options': list(STRATEGY_OBJECTIVE_OPTIONS),
            'rationale': rationale_text,
            'lever_adjustments': lever_adjustments,
            'suggestion': {
                'label': preview['label'],
                'summary': str(suggestion.get('summary') or '').strip(),
                'deltas': deltas,
                'rationale': rationale_text,
                'reasons': reasons,
            },
            'preview_scorecard': preview,
            'lever_context': _thread_levers_for_scenario_ai(user_id, thread_id, baseline_inputs, deltas),
        }

        if 'commit' in payload:
            commit = bool(payload.get('commit'))
        elif 'accept' in payload:
            commit = bool(payload.get('accept'))
        elif 'preview' in payload:
            commit = not bool(payload.get('preview'))
        else:
            # Default to create scenario unless explicitly previewing.
            commit = True

        if commit:
            scenario_id = str(payload.get('scenario_id') or uuid.uuid4())
            scenario_result = {
                **preview,
                'analysis_id': scenario_id,
                'scenario_id': scenario_id,
                'label': preview['label'],
            }
            try:
                created = _create_scenario_record(
                    user_id,
                    thread_id,
                    deltas=deltas,
                    label=preview['label'],
                    baseline=baseline,
                    scenario_id=scenario_id,
                    plan_key=plan_key,
                    result=scenario_result,
                    metadata={
                        'ai_summary': str(suggestion.get('summary') or '').strip(),
                        'ai_rationale': rationale_text,
                        'ai_reasons': reasons,
                        'ai_instruction': instruction or None,
                        'strategy_objective': strategy_objective,
                    },
                )
            except PermissionError as limit_error:
                payload = {}
                try:
                    payload = json.loads(str(limit_error))
                except Exception:
                    payload = {'error': str(limit_error)}
                return jsonify(payload), 403

            response_payload['scenario_id'] = scenario_id
            response_payload['scenario'] = created
            response_payload['committed'] = True
        else:
            response_payload['scenario'] = {
                'scenario_id': None,
                'thread_id': thread_id,
                'label': preview['label'],
                'deltas': deltas,
                'result': preview,
            }
            response_payload['committed'] = False

        return jsonify(response_payload), 200
    except Exception as e:
        current_app.logger.error("[create_ai_scenario] %s", e)
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
        scenario_id = str(payload.get('scenario_id') or '').strip() or None

        all_data, thread_data, baseline, _baseline_inputs, session, _strategy_objective = _resolve_thread_baseline(user_id, thread_id)
        scenarios = thread_data.get('scenarios') if isinstance(thread_data.get('scenarios'), dict) else {}
        adopted_id = thread_data.get('adopted_scenario_id')
        adopted_scenario = None

        current_scorecard = baseline if isinstance(baseline, dict) else None
        if scenario_id and scenario_id in scenarios and isinstance((scenarios.get(scenario_id) or {}).get('result'), dict):
            adopted_scenario = scenarios.get(scenario_id)
            current_scorecard = adopted_scenario.get('result')
        elif adopted_id and adopted_id in scenarios and isinstance((scenarios.get(adopted_id) or {}).get('result'), dict):
            adopted_scenario = scenarios.get(adopted_id)
            current_scorecard = adopted_scenario.get('result')
        if current_scorecard is None and isinstance(session, dict) and isinstance(session.get('result'), dict):
            current_scorecard = session.get('result')
        if not isinstance(current_scorecard, dict):
            return jsonify({'error': 'No scorecard context found for this thread.'}), 404

        client = get_llm_client()
        raw_wbs = _generate_ai_wbs_suggestion(
            client,
            model_selection['llm_model'],
            scorecard=current_scorecard,
            instruction=instruction,
            scenario_payload=adopted_scenario,
        )
        materialized = _materialize_ai_wbs(raw_wbs)
        normalized_wbs = _normalize_project_wbs({'project_wbs': materialized}, existing=None)
        normalized_wbs['ai_generated'] = True
        normalized_wbs['ai_generated_at'] = datetime.utcnow().isoformat()
        normalized_wbs['ai_summary'] = str(raw_wbs.get('summary') or '').strip()
        if scenario_id:
            normalized_wbs['source_scenario_id'] = scenario_id

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
            _audit_strategy_event(
                'wbs.generated',
                user_id=user_id,
                details={
                    'thread_id': thread_id,
                    'task_count': len(normalized_wbs.get('tasks', [])),
                    'dependency_count': _wbs_dependency_count(normalized_wbs),
                    'source_scenario_id': scenario_id,
                },
            )

        return jsonify({
            'success': True,
            'thread_id': thread_id,
            'committed': commit,
            'scenario_id': scenario_id,
            'generated_wbs': raw_wbs if isinstance(raw_wbs, dict) else {},
            'project_wbs': normalized_wbs,
            'model_type': model_selection['model_type'],
            'limits': limits,
        }), 200
    except Exception as e:
        current_app.logger.error("[generate_ai_wbs] %s", e)
        return jsonify({'error': str(e)}), 500


# ============================================================
# SCENARIO CRUD ROUTES
# ============================================================

def _create_scenario_record(
    user_id,
    thread_id,
    *,
    deltas,
    label='Scenario',
    baseline=None,
    scenario_id=None,
    plan_key=None,
    result=None,
    metadata=None,
):
    all_data = _load_scenarios(user_id)
    if thread_id not in all_data or not isinstance(all_data.get(thread_id), dict):
        all_data[thread_id] = _thread_entry()
    td = all_data[thread_id]

    if baseline and not td.get('baseline'):
        td['baseline'] = baseline
        td['baseline_inputs'] = _extract_baseline_inputs(baseline)
    elif baseline and isinstance(baseline, dict) and isinstance(td.get('baseline_inputs'), dict) and not td.get('baseline_inputs'):
        td['baseline_inputs'] = _extract_baseline_inputs(baseline)

    scenarios = td.get('scenarios')
    if not isinstance(scenarios, dict):
        scenarios = {}
        td['scenarios'] = scenarios

    scenario_limits = get_scenario_limits_for_plan(plan_key).get('max_scenarios_per_thread') if plan_key else None
    existing = scenarios.get(str(scenario_id)) if scenario_id else None
    creating_new = not isinstance(existing, dict)
    if creating_new and isinstance(scenario_limits, int) and len(scenarios) >= scenario_limits:
        raise PermissionError(json.dumps({
            'error': 'Scenario limit reached for current plan',
            'code': 'scenario_limit_reached',
            'plan_key': plan_key,
            'thread_id': thread_id,
            'max_scenarios_per_thread': scenario_limits,
        }))

    sid = str(scenario_id or uuid.uuid4())
    now_iso = datetime.utcnow().isoformat()
    scenario = existing if isinstance(existing, dict) else {
        'scenario_id': sid,
        'thread_id': thread_id,
        'created_at': now_iso,
    }
    scenario['label'] = str(label or 'Scenario').strip() or 'Scenario'
    scenario['deltas'] = deltas if isinstance(deltas, dict) else {}
    scenario['result'] = result if isinstance(result, dict) else scenario.get('result')
    scenario['updated_at'] = now_iso
    if isinstance(metadata, dict):
        for key, value in metadata.items():
            scenario[key] = value

    scenarios[sid] = scenario
    td['scenarios'] = scenarios
    all_data[thread_id] = td

    if not _save_scenarios(user_id, all_data):
        raise RuntimeError('Failed to persist scenario.')
    return scenario


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

        label = data.get('label', 'Scenario')
        deltas = data.get('deltas') if isinstance(data.get('deltas'), dict) else {}
        baseline = data.get('baseline') if isinstance(data.get('baseline'), dict) else None

        try:
            created = _create_scenario_record(
                user_id,
                thread_id,
                deltas=deltas,
                label=label,
                baseline=baseline,
                plan_key=plan_key,
            )
        except PermissionError as limit_error:
            payload = {}
            try:
                payload = json.loads(str(limit_error))
            except Exception:
                payload = {'error': str(limit_error)}
            return jsonify(payload), 403

        _audit_strategy_event(
            'scenario.created',
            user_id=user_id,
            details={
                'thread_id': thread_id,
                'scenario_id': created.get('scenario_id'),
                'label': created.get('label'),
            },
        )

        return jsonify({
            'scenario_id': created.get('scenario_id'),
            'thread_id': thread_id,
            'label': created.get('label'),
            'created_at': created.get('created_at'),
        }), 201

    except Exception as e:
        current_app.logger.error("[create_scenario] %s", e)
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
        current_app.logger.error("[list_scenarios] %s", e)
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
        current_app.logger.error("[update_scenario] %s", e)
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
        current_app.logger.error("[delete_scenario] %s", e)
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
        current_app.logger.error("[apply_scenario] %s", e)
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
        _audit_strategy_event(
            'scenario.adopted',
            user_id=user_id,
            details={
                'thread_id': thread_id,
                'scenario_id': scenario_id,
            },
        )
        return jsonify({'success': True, 'adopted_scenario_id': scenario_id}), 200

    except Exception as e:
        current_app.logger.error("[adopt_scenario] %s", e)
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
        current_app.logger.error("[get_thread_wbs] %s", e)
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

        prior_tasks = existing_wbs.get('tasks') if isinstance(existing_wbs, dict) and isinstance(existing_wbs.get('tasks'), list) else []
        next_tasks = normalized_wbs.get('tasks') if isinstance(normalized_wbs.get('tasks'), list) else []
        td['project_wbs'] = normalized_wbs
        all_data[thread_id] = td
        _save_scenarios(user_id, all_data)
        _audit_strategy_event(
            'wbs.updated',
            user_id=user_id,
            details={
                'thread_id': thread_id,
                'task_count_before': len(prior_tasks),
                'task_count_after': len(next_tasks),
                'dependency_count': _wbs_dependency_count(normalized_wbs),
            },
        )

        return jsonify({
            'success': True,
            'thread_id': thread_id,
            'project_wbs': normalized_wbs,
            'limits': limits,
            'jira_sync': sync_result,
        }), 200
    except Exception as e:
        current_app.logger.error("[upsert_thread_wbs] %s", e)
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
        snapshot_state = _scorecard_snapshot_state(session_result, thread_id) if isinstance(session_result, dict) else None
        strategy_objective = _normalize_strategy_objective(
            (session.get('strategy_objective') if isinstance(session, dict) else None)
            or td.get('strategy_objective')
        )
        td['strategy_objective'] = strategy_objective
        baseline_inputs = td.get('baseline_inputs') or (
            session.get('baseline_inputs') if isinstance(session, dict) and isinstance(session.get('baseline_inputs'), dict) else {}
        )
        if snapshot_state:
            baseline = snapshot_state['baseline']
        elif baseline is None and session_result:
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
        if snapshot_state and isinstance(snapshot_state.get('selected_snapshot'), dict):
            current_scorecard = snapshot_state['selected_snapshot']
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
            'scorecard_snapshots': snapshot_state['snapshots'] if snapshot_state else [],
            'selected_scorecard_id': snapshot_state['selected_id'] if snapshot_state else None,
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
        current_app.logger.error("[get_thread_bundle] %s", e)
        return jsonify({'error': str(e)}), 500


@strategy_bp.route('/threads/<thread_id>', methods=['PATCH'])
@jwt_required()
def update_strategy_thread(thread_id):
    try:
        user_id = get_jwt_identity()
        payload = request.get_json() or {}
        next_name = str(payload.get('name') or payload.get('project_name') or '').strip()
        if not next_name:
            return jsonify({'error': 'name is required'}), 400

        sessions = load_user_sessions(user_id) or {}
        session_key, session = _resolve_session_entry(sessions, thread_id)
        if not isinstance(session, dict):
            return jsonify({'error': 'Thread not found'}), 404

        now_iso = datetime.utcnow().isoformat()
        session['name'] = next_name
        session['timestamp'] = now_iso

        if isinstance(session.get('result'), dict):
            result = dict(session['result'])
            result['project_name'] = next_name

            compat = result.get('compat')
            if isinstance(compat, dict):
                compat = dict(compat)
                compat['title'] = next_name
                result['compat'] = compat

            baseline_scorecard = result.get('_baseline_scorecard')
            if isinstance(baseline_scorecard, dict):
                patched_baseline = dict(baseline_scorecard)
                patched_baseline['project_name'] = next_name
                result['_baseline_scorecard'] = patched_baseline

            snapshots = result.get('scorecard_snapshots')
            if isinstance(snapshots, list):
                next_snapshots = []
                for snapshot in snapshots:
                    if isinstance(snapshot, dict):
                        patched_snapshot = dict(snapshot)
                        patched_snapshot['project_name'] = next_name
                        next_snapshots.append(patched_snapshot)
                    else:
                        next_snapshots.append(snapshot)
                result['scorecard_snapshots'] = next_snapshots

            session['result'] = result

        history = session.get('analysis_history')
        if isinstance(history, list):
            next_history = []
            for entry in history:
                if not isinstance(entry, dict):
                    next_history.append(entry)
                    continue
                patched_entry = dict(entry)
                if isinstance(patched_entry.get('result'), dict):
                    patched_result = dict(patched_entry['result'])
                    patched_result['project_name'] = next_name
                    if isinstance(patched_result.get('compat'), dict):
                        compat = dict(patched_result['compat'])
                        compat['title'] = next_name
                        patched_result['compat'] = compat
                    patched_entry['result'] = patched_result
                next_history.append(patched_entry)
            session['analysis_history'] = next_history

        sessions[session_key or thread_id] = session
        save_user_sessions(user_id, sessions)

        all_data = _load_scenarios(user_id)
        thread_data = all_data.get(thread_id)
        if isinstance(thread_data, dict):
            baseline = thread_data.get('baseline')
            if isinstance(baseline, dict):
                patched_baseline = dict(baseline)
                patched_baseline['project_name'] = next_name
                thread_data['baseline'] = patched_baseline

            scenarios = thread_data.get('scenarios')
            if isinstance(scenarios, dict):
                next_scenarios = {}
                for scenario_id, scenario in scenarios.items():
                    if isinstance(scenario, dict):
                        patched_scenario = dict(scenario)
                        if isinstance(patched_scenario.get('result'), dict):
                            patched_result = dict(patched_scenario['result'])
                            patched_result['project_name'] = next_name
                            patched_scenario['result'] = patched_result
                        next_scenarios[scenario_id] = patched_scenario
                    else:
                        next_scenarios[scenario_id] = scenario
                thread_data['scenarios'] = next_scenarios

            all_data[thread_id] = thread_data
            _save_scenarios(user_id, all_data)

        return jsonify({
            'success': True,
            'thread': {
                'id': thread_id,
                'session_id': thread_id,
                'name': next_name,
                'status': session.get('status') or 'in_progress',
                'timestamp': now_iso,
            },
        }), 200

    except Exception as e:
        current_app.logger.error("[update_strategy_thread] %s", e)
        return jsonify({'error': str(e)}), 500


@strategy_bp.route('/threads/<thread_id>/scorecard-assistant', methods=['POST'])
@jwt_required()
@limiter.limit("20 per minute")
def scorecard_assistant(thread_id):
    try:
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404

        payload = request.get_json() or {}
        instruction = str(payload.get('instruction') or '').strip()
        if not instruction:
            return jsonify({'error': 'instruction is required'}), 400

        model_selection, model_error = _resolve_user_model_selection(
            user,
            requested_model_type=payload.get('model_type'),
        )
        if model_error:
            return model_error

        sessions = load_user_sessions(user_id) or {}
        session_key, session = _resolve_session_entry(sessions, thread_id)
        if not isinstance(session, dict):
            return jsonify({'error': 'Thread not found'}), 404

        session_result = session.get('result') if isinstance(session.get('result'), dict) else {}
        snapshot_state = _scorecard_snapshot_state(session_result, thread_id)
        base_scorecard = payload.get('scorecard') if isinstance(payload.get('scorecard'), dict) else snapshot_state['selected_snapshot']
        base_scorecard = _normalize_scorecard_payload(base_scorecard)

        recent_history = _load_thread_conversation(user_id, thread_id)
        recent_excerpt = []
        for item in recent_history[-8:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get('role') or '').strip() or 'user'
            content = str(item.get('content') or item.get('text') or '').strip()
            if not content:
                continue
            recent_excerpt.append({'role': role, 'content': content[:500]})

        objective = _normalize_strategy_objective(
            payload.get('strategy_objective')
            or session.get('strategy_objective')
            or snapshot_state['selected_snapshot'].get('strategy_objective')
        )

        editable_scorecard = {
            'project_name': base_scorecard.get('project_name') or session.get('name') or 'Jaspen Scorecard',
            'jaspen_score': base_scorecard.get('jaspen_score'),
            'score_category': base_scorecard.get('score_category'),
            'executive_summary': base_scorecard.get('executive_summary'),
            'component_scores': base_scorecard.get('component_scores'),
            'component_rationale': base_scorecard.get('component_rationale'),
            'financial_impact': base_scorecard.get('financial_impact'),
            'key_insights': base_scorecard.get('key_insights'),
            'top_risks': base_scorecard.get('top_risks'),
            'recommendations': base_scorecard.get('recommendations'),
            'decision_framework': base_scorecard.get('decision_framework'),
            'assumptions': base_scorecard.get('assumptions'),
        }

        system_prompt = (
            "You are Jaspen's scorecard editor. "
            "You can answer questions about the current scorecard and, when the user asks, rewrite scorecard wording. "
            "Return valid JSON only."
        )
        editor_prompt = f"""
You are reviewing an existing Jaspen scorecard.

User request:
{instruction}

Objective profile:
{objective}

Objective guidance:
{_scorecard_objective_guidance(objective)}

Current scorecard:
{json.dumps(editable_scorecard, indent=2)}

Recent thread context:
{json.dumps(recent_excerpt, indent=2)}

Return one valid JSON object only in this format:
{{
  "reply": "<short, polished response to the user>",
  "updated_scorecard": {{
    "executive_summary": "<optional rewritten executive summary or null>",
    "component_rationale": {{
      "financial_health": "<optional rewritten rationale or null>",
      "operational_efficiency": "<optional rewritten rationale or null>",
      "market_position": "<optional rewritten rationale or null>",
      "execution_readiness": "<optional rewritten rationale or null>"
    }},
    "key_insights": ["<optional replacement insight list>"],
    "top_risks": [
      {{
        "risk": "<risk wording>",
        "probability": "<High|Medium|Low|null>",
        "impact_dollars": "<currency or null>",
        "impact_category": "<financial_health|operational_efficiency|market_position|execution_readiness|null>",
        "mitigation": "<mitigation or null>",
        "mitigation_cost": "<currency or null>",
        "residual_risk": "<High|Medium|Low|null>"
      }}
    ],
    "recommendations": [
      {{
        "action": "<recommendation wording>",
        "expected_impact": "<impact wording or quantified outcome>",
        "effort": "<Low|Medium|High|null>",
        "timeline": "<timeframe or null>",
        "priority": <positive integer>
      }}
    ],
    "decision_framework": {{
      "go_no_go": "<GO|CONDITIONAL|NO-GO|null>",
      "confidence_level": "<percentage or null>",
      "key_condition": "<single prerequisite or null>",
      "downside_scenario": "<downside wording or null>",
      "upside_scenario": "<upside wording or null>"
    }},
    "assumptions": ["<optional updated assumption list>"]
  }},
  "updated_sections": ["<section keys you changed>"]
}}

Rules:
- If the user is only asking a question and not asking to rewrite or reword the scorecard, set updated_scorecard to null and updated_sections to [].
- Never change numeric scores, category scores, or financial values in the scorecard.
- Only rewrite wording or organization for text sections.
- Preserve the original meaning unless the user explicitly asks to change the substance.
- If you update a list section, return the full replacement list for that section.
- Keep the reply crisp and professional.
""".strip()

        assistant_text = None
        try:
            from .ai_agent import _generate_routed_chat_reply

            assistant_text, _usage = _generate_routed_chat_reply(
                [{"role": "user", "content": editor_prompt}],
                model_selection,
                system_prompt=system_prompt,
                strategy_objective=objective,
                max_tokens=2200,
                temperature=0.2,
            )
        except Exception as routed_exc:
            current_app.logger.warning(
                "[strategy.scorecard_assistant] routed generation failed, falling back to legacy client: %s",
                routed_exc,
            )
            client = get_llm_client()
            legacy_response = client.chat.completions.create(
                model=model_selection['llm_model'],
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": editor_prompt},
                ],
                temperature=0.2,
                max_tokens=2200,
            )
            assistant_text = legacy_response.choices[0].message.content

        parsed = _extract_json_object(assistant_text)
        reply = _clean_scorecard_text(parsed.get('reply')) or 'Updated the scorecard wording.'
        updated_patch = parsed.get('updated_scorecard') if isinstance(parsed.get('updated_scorecard'), dict) else None
        updated_sections = parsed.get('updated_sections') if isinstance(parsed.get('updated_sections'), list) else []

        updated_scorecard = None
        selected_scorecard_id = snapshot_state['selected_id']

        if updated_patch:
            updated_scorecard = _merge_scorecard_patch(base_scorecard, updated_patch)
            current_selected = snapshot_state['selected_snapshot'] or snapshot_state['baseline']
            current_selected_id = str(
                payload.get('selected_scorecard_id')
                or current_selected.get('id')
                or snapshot_state['selected_id']
                or thread_id
            )
            edited_id = current_selected_id if current_selected_id.endswith('__edited') else f"{current_selected_id}__edited"
            edited_label = (
                current_selected.get('label')
                or ('Baseline' if current_selected.get('isBaseline') else 'Edited scorecard')
            )
            edited_snapshot = {
                **updated_scorecard,
                'id': edited_id,
                'label': edited_label if edited_label.endswith('(Edited)') else f"{edited_label} (Edited)",
                'isBaseline': False,
                'createdAt': int(time.time() * 1000),
            }

            next_snapshots = []
            replaced = False
            for snapshot in snapshot_state['snapshots']:
                snapshot_id = str(snapshot.get('id') or '')
                if snapshot_id == edited_id:
                    next_snapshots.append(edited_snapshot)
                    replaced = True
                else:
                    next_snapshots.append(snapshot)
            if not replaced:
                next_snapshots.append(edited_snapshot)

            session_result = {
                **session_result,
                '_baseline_scorecard': session_result.get('_baseline_scorecard') or snapshot_state['baseline'],
                'scorecard_snapshots': next_snapshots,
                'selected_scorecard_id': edited_id,
            }
            session['result'] = session_result
            session['timestamp'] = datetime.utcnow().isoformat()
            sessions[session_key or thread_id] = session
            save_user_sessions(user_id, sessions)

            selected_scorecard_id = edited_id

        return jsonify({
            'success': True,
            'reply': reply,
            'updated_scorecard': updated_scorecard,
            'updated_sections': updated_sections,
            'selected_scorecard_id': selected_scorecard_id,
        }), 200

    except Exception as e:
        current_app.logger.error("[scorecard_assistant] %s", e)
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
        current_app.logger.error("[adopt_analysis_for_thread] %s", e)
        return jsonify({'error': str(e)}), 500
