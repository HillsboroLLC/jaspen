from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
import anthropic
import hashlib
import json
import os
import re
import threading
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
    effective_plan_key,
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


class ScorecardConflictError(Exception):
    def __init__(self, message, payload=None):
        super().__init__(message)
        self.payload = payload if isinstance(payload, dict) else {}


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


def _scores_display_result(result, thread_id):
    if not isinstance(result, dict):
        return result if isinstance(result, dict) else {}

    snapshot_state = _scorecard_snapshot_state(result, thread_id)
    selected_snapshot = snapshot_state.get('selected_snapshot') if isinstance(snapshot_state, dict) else None
    baseline_snapshot = snapshot_state.get('baseline') if isinstance(snapshot_state, dict) else None

    chosen = selected_snapshot if isinstance(selected_snapshot, dict) else None
    if not isinstance(chosen, dict):
        chosen = baseline_snapshot if isinstance(baseline_snapshot, dict) else None
    if not isinstance(chosen, dict):
        return result

    merged = {
        **result,
        **chosen,
    }
    merged.setdefault('_owner_thread_id', str(thread_id or '').strip() or None)
    merged.setdefault('project_name', result.get('project_name') or chosen.get('project_name'))
    merged.setdefault('analysis_id', chosen.get('analysis_id') or chosen.get('id') or result.get('analysis_id'))
    return merged


_SCENARIO_LETTER = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'


def _variant_display_name(base_project_name, snapshot, index):
    """Build display name: 'Project Name' for baseline, 'Project Name A' for first scenario, etc."""
    if snapshot.get('isBaseline'):
        return base_project_name
    if index < len(_SCENARIO_LETTER):
        return f'{base_project_name} {_SCENARIO_LETTER[index]}'
    return f'{base_project_name} Variant {index + 1}'


def _row_from_snapshot(snapshot, thread_id, base_project_name, variant_index, session_created_at):
    """Build a scores row dict from a single scorecard snapshot."""
    jaspen_score = _scores_extract_numeric_score(snapshot)
    score_category = _scores_category_from_values(
        jaspen_score,
        explicit_category=snapshot.get('score_category'),
    )
    component_scores = snapshot.get('component_scores')
    if not isinstance(component_scores, dict):
        component_scores = snapshot.get('scores') if isinstance(snapshot.get('scores'), dict) else {}
    financial_impact = snapshot.get('financial_impact')
    if not isinstance(financial_impact, dict):
        financial_impact = {}

    created_at = _scores_parse_iso(
        snapshot.get('createdAt') or snapshot.get('timestamp') or session_created_at
    )

    snapshot_id = str(snapshot.get('id') or snapshot.get('analysis_id') or '')
    display_name = _variant_display_name(base_project_name, snapshot, variant_index)
    variant_label = snapshot.get('label') or ('Baseline' if snapshot.get('isBaseline') else f'Scenario {_SCENARIO_LETTER[variant_index] if variant_index < len(_SCENARIO_LETTER) else variant_index + 1}')

    return {
        'thread_id': thread_id,
        'snapshot_id': snapshot_id,
        'project_name': display_name,
        'base_project_name': base_project_name,
        'variant_label': variant_label,
        'is_baseline': bool(snapshot.get('isBaseline')),
        'jaspen_score': jaspen_score,
        'score_category': score_category,
        'component_scores': component_scores,
        'financial_impact': financial_impact,
        'scoring_rubric_version': snapshot.get('scoring_rubric_version') or 'v3',
        'data_confidence': _safe_int(snapshot.get('data_confidence')),
        'created_at': created_at,
        'updated_at': created_at,
    }


def _collect_completed_scores(
    user_id,
    *,
    sort_by='date',
    sort_dir='desc',
    category_filter=None,
    search='',
):
    sessions = load_user_sessions(user_id) or {}
    all_scenarios = _load_scenarios(user_id)

    scores = []
    for key, session in (sessions.items() if isinstance(sessions, dict) else []):
        if not isinstance(session, dict):
            continue

        thread_id = str(session.get('session_id') or key or '').strip()
        if not thread_id:
            continue

        session_status = str(session.get('status') or '').strip().lower()
        session_completed = session_status == 'completed'

        # Get the session result which contains _baseline_scorecard and scorecard_snapshots
        analyses = _scores_analysis_entries(session, thread_id)

        # Fall back to scenarios_json baseline when payload has no analysis entries
        if not analyses:
            thread_data = all_scenarios.get(thread_id) or all_scenarios.get(key)
            if isinstance(thread_data, dict):
                baseline = thread_data.get('baseline')
                if isinstance(baseline, dict) and (
                    baseline.get('jaspen_score') is not None
                    or baseline.get('project_name')
                    or session_completed
                ):
                    analyses = [{
                        'analysis_id': thread_id,
                        'created_at': baseline.get('timestamp') or session.get('created') or session.get('timestamp'),
                        'updated_at': baseline.get('timestamp') or session.get('timestamp'),
                        'result': baseline,
                    }]

        if not analyses:
            continue

        # Use the most recent analysis result
        analysis = analyses[0]
        result = analysis.get('result') if isinstance(analysis, dict) else None
        if not isinstance(result, dict):
            continue

        # Check that at least the baseline has a score
        baseline_score = _scores_extract_numeric_score(result)
        if baseline_score is None and not session_completed:
            continue

        base_project_name = str(
            result.get('project_name')
            or result.get('name')
            or result.get('title')
            or session.get('name')
            or f'Thread {thread_id}'
        ).strip()

        session_created_at = (
            analysis.get('created_at')
            or result.get('timestamp')
            or session.get('created')
            or session.get('timestamp')
        )

        # Use _scorecard_snapshot_state to get all variants (baseline + scenarios)
        snapshot_state = _scorecard_snapshot_state(result, thread_id)
        all_snapshots = snapshot_state.get('snapshots') or []

        if all_snapshots:
            # We have structured snapshots — emit one row per variant
            scenario_index = 0
            for snapshot in all_snapshots:
                if not isinstance(snapshot, dict):
                    continue
                is_baseline = bool(snapshot.get('isBaseline'))
                idx = 0 if is_baseline else scenario_index
                if not is_baseline:
                    scenario_index += 1

                row = _row_from_snapshot(snapshot, thread_id, base_project_name, idx, session_created_at)
                if row['jaspen_score'] is None and not session_completed:
                    continue
                if category_filter and row['score_category'] != category_filter:
                    continue
                if search and search not in row['project_name'].lower():
                    continue
                scores.append(row)
        else:
            # Fallback: no snapshots, emit single baseline row
            jaspen_score = baseline_score
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

            created_at = _scores_parse_iso(session_created_at)

            row = {
                'thread_id': thread_id,
                'snapshot_id': str(result.get('analysis_id') or thread_id),
                'project_name': base_project_name,
                'base_project_name': base_project_name,
                'variant_label': 'Baseline',
                'is_baseline': True,
                'jaspen_score': jaspen_score,
                'score_category': score_category,
                'component_scores': component_scores,
                'financial_impact': financial_impact,
                'scoring_rubric_version': result.get('scoring_rubric_version') or 'v3',
                'data_confidence': _safe_int(result.get('data_confidence')),
                'created_at': created_at,
                'updated_at': created_at,
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
        if result.get('source_scenario_id') or result.get('isBaseline') is False:
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
        'claude-sonnet-4-5-20250929',
        'claude-3-7-sonnet-latest',
        'claude-3-7-sonnet-20250219',
        'claude-3-5-sonnet-20241022',
        'claude-haiku-4-5',
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


def _strategy_generate_reply(
    messages,
    *,
    system_prompt,
    model_selection=None,
    llm_model=None,
    strategy_objective='balanced',
    max_tokens=900,
    temperature=0.2,
):
    """
    Unified generation helper for strategy routes.
    Prefer routed generation when model_selection is available; fall back to legacy compat client.
    Returns tuple: (reply_text, usage_dict_or_none)
    """
    sanitized = []
    for item in messages or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get('role') or '').strip().lower()
        if role not in {'user', 'assistant'}:
            continue
        content = str(item.get('content') or '').strip()
        if not content:
            continue
        sanitized.append({'role': role, 'content': content})

    if not sanitized:
        raise ValueError('At least one user/assistant message is required.')

    if isinstance(model_selection, dict):
        from .ai_agent import _generate_routed_chat_reply

        return _generate_routed_chat_reply(
            sanitized,
            model_selection,
            system_prompt=system_prompt,
            strategy_objective=_normalize_strategy_objective(strategy_objective),
            max_tokens=max_tokens,
            temperature=temperature,
        )

    client = get_llm_client()
    model_name = str(llm_model or '').strip()
    if not model_name:
        raise ValueError('llm_model is required for legacy fallback generation.')
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {'role': 'system', 'content': system_prompt},
            *sanitized,
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    usage_payload = getattr(response, 'usage', None)
    usage = None
    if usage_payload is not None:
        if isinstance(usage_payload, dict):
            usage = usage_payload
        else:
            usage = {
                'input_tokens': int(getattr(usage_payload, 'input_tokens', 0) or 0),
                'output_tokens': int(getattr(usage_payload, 'output_tokens', 0) or 0),
                'total_tokens': int(getattr(usage_payload, 'total_tokens', 0) or 0),
            }
    return response.choices[0].message.content, usage


def _repair_json_text(text):
    """Apply common repairs to LLM-generated JSON before parsing."""
    if not isinstance(text, str):
        return text
    cleaned = text.strip()
    # Strip markdown fences if present
    if cleaned.startswith('```'):
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'\s*```\s*$', '', cleaned)
    # Remove trailing commas before closing brackets/braces
    cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)
    # Insert missing comma between `}` or `]` or `"` and the next quoted key on a new line
    # e.g.  "...},\n    "key":  → unchanged
    #       "...}\n    "key":  → "...},\n    "key":
    cleaned = re.sub(r'([}\]"\d])\s*\n(\s*)(")', r'\1,\n\2\3', cleaned)
    return cleaned


def _extract_json_object(text):
    """Parse JSON object from model output (raw JSON or fenced/embedded JSON).

    Resilient to: trailing commas, missing commas between fields, markdown
    fences, and trailing prose after the JSON object. If the body still won't
    parse, raise ValueError with the original snippet for logging.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Empty LLM response")

    # Pass 1: try as-is
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Pass 2: locate the outermost JSON object
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    candidate = json_match.group() if json_match else text

    # Pass 3: try parsing the candidate directly
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # Pass 4: apply common repairs
    repaired = _repair_json_text(candidate)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError as exc:
        # Final fallback: truncate to last valid `}` and try again
        last_brace = repaired.rfind('}')
        if last_brace > 0:
            try:
                return json.loads(repaired[: last_brace + 1])
            except json.JSONDecodeError:
                pass
        raise ValueError(
            f"Could not parse JSON from LLM response: {exc}; first 200 chars: {candidate[:200]!r}"
        )


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

    normalized['scoring_rubric_version'] = str(
        source.get('scoring_rubric_version')
        or 'v3'
    ).strip() or 'v3'

    financial_numeric = normalized.get('financial_impact', {}).get('_numeric') if isinstance(normalized.get('financial_impact'), dict) else {}
    has_financials = bool(
        isinstance(financial_numeric, dict)
        and any(_safe_float(financial_numeric.get(key)) is not None for key in ('roi_opportunity', 'projected_ebitda', 'potential_loss'))
    )
    component_scores = normalized.get('component_scores') if isinstance(normalized.get('component_scores'), dict) else {}
    has_team_context = _safe_int(component_scores.get('execution_readiness')) is not None
    assumptions_count = len(normalized.get('assumptions') or [])
    conversation_turns = 0
    source_meta = source.get('meta') if isinstance(source.get('meta'), dict) else {}
    if isinstance(source_meta, dict):
        conversation_turns = _safe_int(source_meta.get('conversation_turns')) or 0

    confidence_pct = min(
        100,
        max(
            20,
            (30 if conversation_turns >= 5 else 10)
            + (25 if has_financials else 0)
            + (20 if has_team_context else 0)
            + (25 if assumptions_count < 3 else 10),
        ),
    )
    normalized['data_confidence'] = int(confidence_pct)

    score_value = _safe_int(normalized.get('jaspen_score')) or 0
    risks = normalized.get('top_risks') if isinstance(normalized.get('top_risks'), list) else []
    recommendations = normalized.get('recommendations') if isinstance(normalized.get('recommendations'), list) else []
    top_risk = risks[0] if risks and isinstance(risks[0], dict) else {}
    top_rec = recommendations[0] if recommendations and isinstance(recommendations[0], dict) else {}
    top_rec_action = _clean_scorecard_text(top_rec.get('action')) or 'refine the financial model'
    top_risk_label = _clean_scorecard_text(top_risk.get('risk')) or 'execution risk'
    weakest_component = 'execution_readiness'
    if isinstance(component_scores, dict) and component_scores:
        weakest_component = min(component_scores, key=lambda key: _safe_int(component_scores.get(key)) or 0)

    if score_value >= 75:
        proactive_hint = (
            f"This scores {score_value} — strong execution candidate. "
            f"Your highest-priority action: {top_rec_action}."
        )
    elif score_value >= 55:
        proactive_hint = (
            f"This scores {score_value} — promising, but the biggest lever is {top_risk_label}. "
            f"Want me to score a version where you address that?"
        )
    else:
        proactive_hint = (
            f"This scores {score_value} — the gap is primarily in {weakest_component}. "
            "Want me to walk through how to close that gap and re-score?"
        )
    normalized['proactive_next_step'] = proactive_hint

    return normalized


def _merge_scorecard_patch(base_scorecard, patch):
    base = base_scorecard if isinstance(base_scorecard, dict) else {}
    update = patch if isinstance(patch, dict) else {}
    merged = dict(base)

    editable_dict_keys = {
        'component_rationale',
        'decision_framework',
        'financial_impact',
        'investment_analysis',
        'npv_irr_analysis',
        'valuation',
    }
    editable_list_keys = {'key_insights', 'top_risks', 'recommendations', 'assumptions'}
    editable_scalar_keys = {'executive_summary', 'executive_narrative'}

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
        # Workspace (Beta) cosmetic overrides — pass through to the snapshot.
        if isinstance(baseline.get('display_overrides'), dict):
            normalized_baseline['display_overrides'] = baseline['display_overrides']
        normalized_snapshots.append(normalized_baseline)
    else:
        normalized_baseline = None

    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        normalized_snapshot = _normalize_scorecard_payload(snapshot)
        snap_id = str(
            normalized_snapshot.get('id')
            or normalized_snapshot.get('analysis_id')
            or ''
        ).strip()
        if not snap_id:
            continue
        normalized_snapshot['id'] = snap_id
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


def _snapshot_identity(snapshot, fallback_id=None):
    if not isinstance(snapshot, dict):
        return str(fallback_id or '').strip()
    for key in ('id', 'analysis_id', 'analysisId'):
        value = str(snapshot.get(key) or '').strip()
        if value:
            return value
    return str(fallback_id or '').strip()


def _snapshot_revision_token(snapshot):
    if not isinstance(snapshot, dict):
        return ''
    for key in ('createdAt', 'updated_at', 'timestamp'):
        value = snapshot.get(key)
        if value is None:
            continue
        token = str(value).strip()
        if token:
            return token
    return ''


def _find_snapshot_by_id(snapshot_state, snapshot_id, fallback_thread_id=None):
    target = str(snapshot_id or '').strip()
    if not target:
        return None
    state = snapshot_state if isinstance(snapshot_state, dict) else {}
    baseline = state.get('baseline') if isinstance(state.get('baseline'), dict) else None
    snapshots = state.get('snapshots') if isinstance(state.get('snapshots'), list) else []
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        if _snapshot_identity(snapshot) == target:
            return snapshot
    if baseline is not None:
        baseline_ids = {
            _snapshot_identity(baseline, fallback_thread_id),
            str(fallback_thread_id or '').strip(),
        }
        if target in baseline_ids:
            return baseline
    return None


def _assert_scorecard_write_fresh(
    snapshot_state,
    resolved_thread_id,
    *,
    expected_selected_scorecard_id=None,
    expected_snapshot_id=None,
    expected_snapshot_revision=None,
):
    state = snapshot_state if isinstance(snapshot_state, dict) else {}
    selected_snapshot = state.get('selected_snapshot') if isinstance(state.get('selected_snapshot'), dict) else None
    baseline = state.get('baseline') if isinstance(state.get('baseline'), dict) else None
    effective_selected = selected_snapshot or baseline
    current_selected_id = _snapshot_identity(effective_selected, resolved_thread_id)
    current_selected_revision = _snapshot_revision_token(effective_selected)

    expected_selected = str(expected_selected_scorecard_id or '').strip()
    if expected_selected and expected_selected != current_selected_id:
        raise ScorecardConflictError(
            "This scorecard changed in another session. Refresh and try again.",
            payload={
                'error': "This scorecard changed in another session. Refresh and try again.",
                'code': 'scorecard_conflict_selected_changed',
                'current_selected_scorecard_id': current_selected_id,
                'current_selected_revision': current_selected_revision or None,
            },
        )

    expected_revision = str(expected_snapshot_revision or '').strip()
    if expected_revision:
        target_id = str(expected_snapshot_id or expected_selected or current_selected_id or '').strip()
        target_snapshot = _find_snapshot_by_id(state, target_id, resolved_thread_id)
        if not isinstance(target_snapshot, dict):
            raise ScorecardConflictError(
                "That scorecard version no longer exists. Refresh and try again.",
                payload={
                    'error': "That scorecard version no longer exists. Refresh and try again.",
                    'code': 'scorecard_conflict_snapshot_missing',
                    'snapshot_id': target_id or None,
                    'current_selected_scorecard_id': current_selected_id,
                },
            )
        current_revision = _snapshot_revision_token(target_snapshot)
        if current_revision and current_revision != expected_revision:
            raise ScorecardConflictError(
                "This scorecard was updated by someone else. Refresh to review their edits before saving.",
                payload={
                    'error': "This scorecard was updated by someone else. Refresh to review their edits before saving.",
                    'code': 'scorecard_conflict_revision_changed',
                    'snapshot_id': target_id or _snapshot_identity(target_snapshot, resolved_thread_id),
                    'expected_snapshot_revision': expected_revision,
                    'current_snapshot_revision': current_revision,
                    'current_selected_scorecard_id': current_selected_id,
                },
            )


def _snapshot_meta_from_result(result_payload, thread_id, snapshot=None, deleted_snapshot_id=None):
    snapshot_state = _scorecard_snapshot_state(result_payload, thread_id) if isinstance(result_payload, dict) else None
    if not snapshot_state:
        return {
            'snapshot': snapshot,
            'deleted_snapshot_id': deleted_snapshot_id,
            'scorecard_snapshots': [],
            'selected_scorecard_id': None,
        }
    return {
        'snapshot': snapshot,
        'deleted_snapshot_id': deleted_snapshot_id,
        'scorecard_snapshots': snapshot_state.get('snapshots') or [],
        'selected_scorecard_id': snapshot_state.get('selected_id'),
    }


def _upsert_snapshot_entry(snapshots, snapshot):
    items = snapshots if isinstance(snapshots, list) else []
    if not isinstance(snapshot, dict):
        return items

    snapshot_id = str(snapshot.get('id') or snapshot.get('analysis_id') or '').strip()
    if not snapshot_id:
        return items

    next_items = []
    replaced = False
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get('id') or item.get('analysis_id') or '').strip()
        if item_id == snapshot_id:
            next_items.append(snapshot)
            replaced = True
        else:
            next_items.append(item)

    if not replaced:
        next_items.append(snapshot)
    return next_items


def _remove_snapshot_entry(snapshots, snapshot_id):
    target = str(snapshot_id or '').strip()
    if not target:
        return snapshots if isinstance(snapshots, list) else []
    items = snapshots if isinstance(snapshots, list) else []
    return [
        item for item in items
        if isinstance(item, dict) and str(item.get('id') or item.get('analysis_id') or '').strip() != target
    ]


def _scenario_snapshot_payload(result, scenario, thread_id):
    scorecard = _normalize_scorecard_payload(result if isinstance(result, dict) else {})
    scenario_obj = scenario if isinstance(scenario, dict) else {}
    scenario_id = str(
        scorecard.get('analysis_id')
        or scorecard.get('id')
        or scenario_obj.get('scenario_id')
        or ''
    ).strip()
    if not scenario_id:
        return None

    created_at = (
        scenario_obj.get('updated_at')
        or scenario_obj.get('created_at')
        or scorecard.get('createdAt')
        or scorecard.get('timestamp')
        or datetime.utcnow().isoformat()
    )

    snapshot = {
        **scorecard,
        'id': scenario_id,
        'analysis_id': scenario_id,
        'thread_id': thread_id,
        'label': str(
            scenario_obj.get('label')
            or scorecard.get('label')
            or 'Scenario'
        ).strip() or 'Scenario',
        'createdAt': created_at,
        'timestamp': created_at,
        'isBaseline': False,
        'source_scenario_id': scenario_id,
    }
    # Guarantee stable identifiers before persisting snapshot entries.
    if not str(snapshot.get('id') or '').strip():
        snapshot['id'] = scenario_id
    if not str(snapshot.get('analysis_id') or '').strip():
        snapshot['analysis_id'] = scenario_id
    return snapshot


def _persist_scenario_snapshot_to_session(user_id, thread_id, scenario, result, *, select=False):
    sessions = load_user_sessions(user_id) or {}
    resolved_thread_id, session_key, session = _resolve_strategy_thread_state(sessions, _load_scenarios(user_id), thread_id)
    resolved_thread_id = resolved_thread_id or thread_id
    snapshot = _scenario_snapshot_payload(result, scenario, resolved_thread_id)
    if not snapshot:
        return None

    if not isinstance(session, dict):
        now_iso = datetime.utcnow().isoformat()
        session = {
            'session_id': resolved_thread_id,
            'name': str(snapshot.get('project_name') or scenario.get('label') or 'Jaspen Analysis').strip() or 'Jaspen Analysis',
            'document_type': 'strategy',
            'created': now_iso,
            'timestamp': now_iso,
            'status': 'completed',
            'chat_history': [],
            'result': {},
            'analysis_history': [],
        }
        session_key = resolved_thread_id

    result_payload = session.get('result') if isinstance(session.get('result'), dict) else {}
    snapshot_state = _scorecard_snapshot_state(result_payload, resolved_thread_id) if result_payload else None
    baseline_snapshot = None
    if snapshot_state and isinstance(snapshot_state.get('baseline'), dict):
        baseline_snapshot = snapshot_state['baseline']
    elif isinstance(result_payload, dict) and result_payload:
        baseline_snapshot = _normalize_scorecard_payload(result_payload)
        baseline_snapshot['id'] = str(baseline_snapshot.get('analysis_id') or resolved_thread_id)
        baseline_snapshot['analysis_id'] = baseline_snapshot['id']
        baseline_snapshot['isBaseline'] = True
        baseline_snapshot['label'] = baseline_snapshot.get('label') or 'Baseline'

    baseline_scorecard = (
        result_payload.get('_baseline_scorecard') if isinstance(result_payload.get('_baseline_scorecard'), dict) else None
    ) or baseline_snapshot or result_payload or None
    if isinstance(baseline_scorecard, dict):
        baseline_scorecard = {**baseline_scorecard}

    existing_snapshots = snapshot_state['snapshots'] if snapshot_state else (
        result_payload.get('scorecard_snapshots') if isinstance(result_payload.get('scorecard_snapshots'), list) else []
    )
    non_baseline_snapshots = [
        item for item in existing_snapshots
        if isinstance(item, dict) and not item.get('isBaseline')
    ]
    next_snapshots = _upsert_snapshot_entry(non_baseline_snapshots, snapshot)

    baseline_id = (
        baseline_scorecard.get('analysis_id')
        or baseline_scorecard.get('id')
        or resolved_thread_id
    ) if isinstance(baseline_scorecard, dict) else resolved_thread_id
    selected_scorecard_id = (
        snapshot['id']
        if select
        else (
            result_payload.get('selected_scorecard_id')
            or baseline_id
        )
    )
    project_name = (
        result_payload.get('project_name')
        or (baseline_scorecard.get('project_name') if isinstance(baseline_scorecard, dict) else None)
        or session.get('name')
        or snapshot.get('project_name')
    )

    next_result = {
        **result_payload,
        '_baseline_scorecard': baseline_scorecard,
        'scorecard_snapshots': next_snapshots,
        'selected_scorecard_id': selected_scorecard_id,
        'project_name': project_name,
    }
    session['result'] = next_result
    session['status'] = session.get('status') or 'completed'
    session['timestamp'] = datetime.utcnow().isoformat()

    sessions[session_key or resolved_thread_id] = session
    persisted = save_user_sessions(user_id, sessions)
    if not persisted:
        raise RuntimeError('Failed to persist scenario snapshot.')

    return _snapshot_meta_from_result(next_result, resolved_thread_id, snapshot=snapshot)


def _rename_snapshot_in_session(
    user_id,
    thread_id,
    snapshot_id,
    label,
    *,
    expected_selected_scorecard_id=None,
    expected_snapshot_id=None,
    expected_snapshot_revision=None,
):
    sessions = load_user_sessions(user_id) or {}
    all_data = _load_scenarios(user_id)
    resolved_thread_id, session_key, session = _resolve_strategy_thread_state(sessions, all_data, thread_id)
    resolved_thread_id = resolved_thread_id or thread_id
    if not isinstance(session, dict):
        return None

    next_label = str(label or '').strip()
    if not next_label:
        return None

    result_payload = session.get('result') if isinstance(session.get('result'), dict) else {}
    snapshot_state = _scorecard_snapshot_state(result_payload, resolved_thread_id) if result_payload else None
    _assert_scorecard_write_fresh(
        snapshot_state,
        resolved_thread_id,
        expected_selected_scorecard_id=expected_selected_scorecard_id,
        expected_snapshot_id=expected_snapshot_id,
        expected_snapshot_revision=expected_snapshot_revision,
    )
    snapshots = snapshot_state['snapshots'] if snapshot_state else []
    next_snapshots = []
    renamed_snapshot = None

    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        candidate_id = str(snapshot.get('id') or snapshot.get('analysis_id') or '').strip()
        if candidate_id == str(snapshot_id or '').strip():
            updated = {**snapshot, 'label': next_label}
            renamed_snapshot = updated
            if not updated.get('isBaseline'):
                next_snapshots.append(updated)
        elif not snapshot.get('isBaseline'):
            next_snapshots.append(snapshot)

    if not renamed_snapshot:
        return None

    baseline_snapshot = snapshot_state.get('baseline') if snapshot_state and isinstance(snapshot_state.get('baseline'), dict) else None
    baseline_scorecard = (
        result_payload.get('_baseline_scorecard') if isinstance(result_payload.get('_baseline_scorecard'), dict) else None
    ) or baseline_snapshot or result_payload or None

    if renamed_snapshot.get('isBaseline') and isinstance(baseline_scorecard, dict):
        baseline_scorecard = {**baseline_scorecard, 'label': next_label}

    next_result = {
        **result_payload,
        '_baseline_scorecard': baseline_scorecard,
        'scorecard_snapshots': next_snapshots,
        'selected_scorecard_id': result_payload.get('selected_scorecard_id') or (
            snapshot_state.get('selected_id') if snapshot_state else renamed_snapshot.get('id')
        ),
    }
    session['result'] = next_result

    analysis_history = session.get('analysis_history') if isinstance(session.get('analysis_history'), list) else []
    next_history = []
    for entry in analysis_history:
        if not isinstance(entry, dict):
            continue
        entry_id = str(entry.get('analysis_id') or entry.get('id') or '').strip()
        if entry_id == str(snapshot_id or '').strip():
            next_history.append({
                **entry,
                'label': next_label,
                'result': {**(entry.get('result') if isinstance(entry.get('result'), dict) else {}), 'label': next_label},
            })
        else:
            next_history.append(entry)
    session['analysis_history'] = next_history

    sessions[session_key or resolved_thread_id] = session
    persisted = save_user_sessions(user_id, sessions)
    if not persisted:
        raise RuntimeError('Failed to persist snapshot rename.')

    return _snapshot_meta_from_result(next_result, resolved_thread_id, snapshot=renamed_snapshot)


def _delete_snapshot_from_session(
    user_id,
    thread_id,
    snapshot_id,
    *,
    expected_selected_scorecard_id=None,
    expected_snapshot_id=None,
    expected_snapshot_revision=None,
):
    sessions = load_user_sessions(user_id) or {}
    all_data = _load_scenarios(user_id)
    resolved_thread_id, session_key, session = _resolve_strategy_thread_state(sessions, all_data, thread_id)
    resolved_thread_id = resolved_thread_id or thread_id
    if not isinstance(session, dict):
        return None

    result_payload = session.get('result') if isinstance(session.get('result'), dict) else {}
    snapshot_state = _scorecard_snapshot_state(result_payload, resolved_thread_id) if result_payload else None
    if not snapshot_state:
        return None
    _assert_scorecard_write_fresh(
        snapshot_state,
        resolved_thread_id,
        expected_selected_scorecard_id=expected_selected_scorecard_id,
        expected_snapshot_id=expected_snapshot_id,
        expected_snapshot_revision=expected_snapshot_revision,
    )

    target_id = str(snapshot_id or '').strip()
    baseline_snapshot = snapshot_state.get('baseline') if isinstance(snapshot_state.get('baseline'), dict) else None
    if baseline_snapshot and str(baseline_snapshot.get('id') or '').strip() == target_id:
        raise ValueError('Baseline snapshot cannot be deleted.')

    next_snapshots = _remove_snapshot_entry(
        [item for item in snapshot_state.get('snapshots', []) if isinstance(item, dict) and not item.get('isBaseline')],
        target_id,
    )
    baseline_scorecard = (
        result_payload.get('_baseline_scorecard') if isinstance(result_payload.get('_baseline_scorecard'), dict) else None
    ) or baseline_snapshot or result_payload or None

    selected_id = result_payload.get('selected_scorecard_id') or snapshot_state.get('selected_id')
    if str(selected_id or '').strip() == target_id:
        selected_id = str((baseline_snapshot or {}).get('id') or resolved_thread_id)

    next_result = {
        **result_payload,
        '_baseline_scorecard': baseline_scorecard,
        'scorecard_snapshots': next_snapshots,
        'selected_scorecard_id': selected_id,
    }
    session['result'] = next_result

    analysis_history = session.get('analysis_history') if isinstance(session.get('analysis_history'), list) else []
    session['analysis_history'] = [
        entry for entry in analysis_history
        if isinstance(entry, dict) and str(entry.get('analysis_id') or entry.get('id') or '').strip() != target_id
    ]

    sessions[session_key or resolved_thread_id] = session
    persisted = save_user_sessions(user_id, sessions)
    if not persisted:
        raise RuntimeError('Failed to persist snapshot deletion.')

    return _snapshot_meta_from_result(next_result, resolved_thread_id, deleted_snapshot_id=target_id)


def _set_selected_snapshot_in_session(
    user_id,
    thread_id,
    snapshot_id,
    *,
    expected_selected_scorecard_id=None,
    expected_snapshot_id=None,
    expected_snapshot_revision=None,
):
    sessions = load_user_sessions(user_id) or {}
    all_data = _load_scenarios(user_id)
    resolved_thread_id, session_key, session = _resolve_strategy_thread_state(sessions, all_data, thread_id)
    resolved_thread_id = resolved_thread_id or thread_id
    if not isinstance(session, dict):
        return None

    result_payload = session.get('result') if isinstance(session.get('result'), dict) else {}
    snapshot_state = _scorecard_snapshot_state(result_payload, resolved_thread_id) if result_payload else None
    if not snapshot_state:
        return None
    _assert_scorecard_write_fresh(
        snapshot_state,
        resolved_thread_id,
        expected_selected_scorecard_id=expected_selected_scorecard_id,
        expected_snapshot_id=expected_snapshot_id,
        expected_snapshot_revision=expected_snapshot_revision,
    )

    target_id = str(snapshot_id or '').strip()
    def _match_snapshot_id(item, target_value):
        if not isinstance(item, dict):
            return False
        for key in ('id', 'analysis_id', 'analysisId'):
            value = str(item.get(key) or '').strip()
            if value and value == target_value:
                return True
        return False

    selected_snapshot = next(
        (
            item for item in snapshot_state.get('snapshots', [])
            if _match_snapshot_id(item, target_id)
        ),
        None,
    )
    if not selected_snapshot:
        baseline = snapshot_state.get('baseline')
        baseline_candidates = {
            str((baseline or {}).get('id') or '').strip(),
            str((baseline or {}).get('analysis_id') or '').strip(),
            str(resolved_thread_id or '').strip(),
        }
        if isinstance(baseline, dict) and target_id in baseline_candidates:
            selected_snapshot = baseline
    if not selected_snapshot:
        return None

    next_result = {
        **result_payload,
        '_baseline_scorecard': (
            result_payload.get('_baseline_scorecard') if isinstance(result_payload.get('_baseline_scorecard'), dict) else None
        ) or snapshot_state.get('baseline') or result_payload or None,
        'scorecard_snapshots': [
            item for item in snapshot_state.get('snapshots', [])
            if isinstance(item, dict) and not item.get('isBaseline')
        ],
        'selected_scorecard_id': target_id,
    }
    session['result'] = next_result
    sessions[session_key or resolved_thread_id] = session
    persisted = save_user_sessions(user_id, sessions)
    if not persisted:
        raise RuntimeError('Failed to persist active snapshot selection.')

    return _snapshot_meta_from_result(next_result, resolved_thread_id, snapshot=selected_snapshot)


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


def _persist_scorecard_assistant_turn(session, session_result, instruction, reply):
    user_text = str(instruction or '').strip()
    assistant_text = str(reply or '').strip()
    if not user_text or not assistant_text:
        return

    timestamp = datetime.utcnow().isoformat()
    chat_history = session.get('chat_history')
    if not isinstance(chat_history, list):
        chat_history = session_result.get('chat_history') if isinstance(session_result, dict) else None
    if not isinstance(chat_history, list):
        chat_history = []

    chat_history = list(chat_history)
    chat_history.append({
        'role': 'user',
        'text': user_text,
        'content': user_text,
        'timestamp': timestamp,
    })
    chat_history.append({
        'role': 'assistant',
        'text': assistant_text,
        'content': assistant_text,
        'timestamp': timestamp,
    })

    session['chat_history'] = chat_history
    if isinstance(session_result, dict):
        session_result['chat_history'] = chat_history


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


def _resolve_strategy_thread_state(sessions, all_data, thread_id):
    """Resolve a strategy thread across session/history storage and scenario bundle storage."""
    tid = str(thread_id or '').strip()
    if not tid:
        return None, None, None

    session_key, session = _resolve_session_entry(sessions, tid)
    if isinstance(session, dict):
        thread_data = all_data.get(tid) if isinstance(all_data, dict) else None
        return tid, session_key, session if isinstance(session, dict) else None

    if isinstance(sessions, dict):
        for key, candidate in sessions.items():
            if not isinstance(candidate, dict):
                continue
            result = candidate.get('result')
            if isinstance(result, dict):
                meta = result.get('meta') if isinstance(result.get('meta'), dict) else {}
                candidate_tid = str(result.get('thread_id') or meta.get('thread_id') or '').strip()
                if candidate_tid == tid:
                    return tid, key, candidate
            history = candidate.get('analysis_history')
            if not isinstance(history, list):
                history = candidate.get('analyses')
            if not isinstance(history, list):
                continue
            for entry in history:
                if not isinstance(entry, dict):
                    continue
                entry_result = entry.get('result') if isinstance(entry.get('result'), dict) else {}
                entry_meta = entry_result.get('meta') if isinstance(entry_result.get('meta'), dict) else {}
                candidate_tid = str(
                    entry.get('thread_id')
                    or entry_result.get('thread_id')
                    or entry_meta.get('thread_id')
                    or ''
                ).strip()
                if candidate_tid == tid:
                    return tid, key, candidate

    if isinstance(all_data, dict):
        if tid in all_data and isinstance(all_data.get(tid), dict):
            return tid, None, None
        for key, candidate in all_data.items():
            if not isinstance(candidate, dict):
                continue
            baseline = candidate.get('baseline') if isinstance(candidate.get('baseline'), dict) else {}
            baseline_meta = baseline.get('meta') if isinstance(baseline.get('meta'), dict) else {}
            candidate_tid = str(baseline.get('thread_id') or baseline_meta.get('thread_id') or '').strip()
            if candidate_tid == tid:
                return str(key), None, None
            scenarios = candidate.get('scenarios')
            if not isinstance(scenarios, dict):
                continue
            for scenario in scenarios.values():
                if not isinstance(scenario, dict):
                    continue
                scenario_result = scenario.get('result') if isinstance(scenario.get('result'), dict) else {}
                scenario_meta = scenario_result.get('meta') if isinstance(scenario_result.get('meta'), dict) else {}
                candidate_tid = str(scenario_result.get('thread_id') or scenario_meta.get('thread_id') or '').strip()
                if candidate_tid == tid:
                    return str(key), None, None

    return None, None, None


def _resolve_user_model_selection(user, requested_model_type=None):
    plan_key = effective_plan_key(user, current_app.config)
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

    model_catalog = get_model_catalog(current_app.config, include_backing_ids=True)
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

    plan_key = effective_plan_key(user, current_app.config)
    if not is_tool_allowed(plan_key, tool_id, access):
        return user, plan_key, _tool_access_error_response(plan_key, tool_id, access=access)

    return user, plan_key, None


# Confidence → max allowed dimension score. The model assigns a raw 0-100 and a
# confidence; Python enforces the cap so an "assumed" dimension can never inflate
# the score. Kept in lockstep with the cap rules stated in the scoring prompt.
_CONFIDENCE_CAPS = {"high": 100, "medium": 75, "low": 60, "assumed": 45}

# component_scores is a flat mirror of four dimension scores — keep it in sync so
# downstream readers that use component_scores see the same capped values.
_COMPONENT_DIMENSION_MIRROR = (
    ("financial_health", "financial_viability"),
    ("operational_efficiency", "execution_readiness"),
    ("market_position", "market_opportunity"),
    ("execution_readiness", "execution_readiness"),
)


def _recompute_jaspen_score(payload, weights):
    """Make scoring deterministic: same dimensions + objective → same score.

    The LLM judges each dimension (a 0-100 score + a confidence). Python — not the
    model — then (1) applies the confidence cap, (2) computes the weighted average
    using the objective's `weights`, and (3) derives score_category. This removes
    LLM arithmetic drift and guarantees the published caps are actually enforced.

    Defensive: if the payload has no usable dimensions we leave the model's value
    untouched rather than zeroing a card we can't recompute.
    """
    if not isinstance(payload, dict):
        return payload
    dims = payload.get("dimensions")
    if not isinstance(dims, dict) or not dims:
        return payload

    acc = 0.0
    total_w = 0.0
    for dim_key, w in (weights or {}).items():
        dim = dims.get(dim_key)
        if not isinstance(dim, dict):
            continue
        try:
            raw_val = float(dim.get("score"))
        except (TypeError, ValueError):
            continue
        raw_val = max(0.0, min(100.0, raw_val))
        conf = str(dim.get("confidence") or "").strip().lower()
        cap = _CONFIDENCE_CAPS.get(conf, 100)
        capped = min(raw_val, cap)
        # Write the capped value back so the dimension bar matches what fed the
        # score (otherwise the UI would show an uncapped bar above a capped total).
        dim["score"] = int(round(capped))
        acc += capped * float(w)
        total_w += float(w)

    if total_w <= 0:
        return payload

    score = int(round(acc / total_w))
    score = max(0, min(100, score))
    payload["jaspen_score"] = score
    payload["score_category"] = (
        "Excellent" if score >= 80
        else "Good" if score >= 60
        else "Fair" if score >= 40
        else "At Risk"
    )

    comp = payload.get("component_scores")
    if isinstance(comp, dict):
        for comp_key, dim_key in _COMPONENT_DIMENSION_MIRROR:
            dim = dims.get(dim_key)
            if isinstance(dim, dict) and dim.get("score") is not None:
                comp[comp_key] = dim["score"]

    return payload


def _generate_jaspen_scorecard(
    client,
    project_description,
    llm_model,
    *,
    model_selection=None,
    strategy_objective='balanced',
):
    """Run the existing LLM scoring flow and return parsed scorecard JSON.

    Scorecards are large structured JSON; always force a Sonnet-class model
    regardless of the user's chat tier. Haiku models (including 4.5) produce
    unreliable JSON at this output size.
    """
    # Force a high-reliability, currently-valid model for structured scoring
    # output, ignoring whatever Pluto/chat tier the user has selected.
    # ANTHROPIC_MODEL takes precedence (set to claude-sonnet-4-5 in prod);
    # AI_AGENT_ANTHROPIC_MODEL may point at a deprecated alias.
    _scoring_model = (
        os.getenv('ANTHROPIC_MODEL')
        or current_app.config.get('ANTHROPIC_MODEL')
        or 'claude-sonnet-4-5-20250929'
    )
    llm_model = _scoring_model
    if isinstance(model_selection, dict):
        model_selection = {**model_selection, 'llm_model': _scoring_model}

    # Objective-based dimension weights
    _DIM_WEIGHTS = {
        "cost_optimization":  {"market_opportunity": 0.12, "financial_viability": 0.25, "execution_readiness": 0.20, "strategic_alignment": 0.15, "risk_profile": 0.20, "evidence_quality": 0.08},
        "growth":             {"market_opportunity": 0.25, "financial_viability": 0.18, "execution_readiness": 0.20, "strategic_alignment": 0.15, "risk_profile": 0.12, "evidence_quality": 0.10},
        "operational":        {"market_opportunity": 0.10, "financial_viability": 0.18, "execution_readiness": 0.28, "strategic_alignment": 0.18, "risk_profile": 0.18, "evidence_quality": 0.08},
        "innovation":         {"market_opportunity": 0.22, "financial_viability": 0.15, "execution_readiness": 0.18, "strategic_alignment": 0.20, "risk_profile": 0.15, "evidence_quality": 0.10},
        "balanced":           {"market_opportunity": 0.18, "financial_viability": 0.20, "execution_readiness": 0.18, "strategic_alignment": 0.16, "risk_profile": 0.16, "evidence_quality": 0.12},
    }
    obj_key = _normalize_strategy_objective(strategy_objective) or "balanced"
    weights = _DIM_WEIGHTS.get(obj_key, _DIM_WEIGHTS["balanced"])
    weights_note = " | ".join(f"{k}: {int(v*100)}%" for k, v in weights.items())

    system_prompt = (
        "You are a Jaspen strategy analyst specializing in commercialization strategy. "
        "Always respond with valid JSON only. Temperature is 0 — be deterministic and evidence-based."
    )
    analysis_prompt = f"""
You are a Jaspen strategy analyst. Analyze the following initiative and return a comprehensive confidence-weighted scorecard.

Project Description: {project_description}

Strategy Objective: {obj_key}
Objective Guidance: {_scorecard_objective_guidance(strategy_objective)}
Dimension Weights for this objective: {weights_note}

Return a single valid JSON object only. No markdown fences, no commentary outside the JSON.

Rules:
- Use null only when information is genuinely absent — never invent data.
- Every numeric field must be an actual number, not prose ("18" not "significant").
- For each dimension, assign a confidence level: "high" (evidence from conversation), "medium" (reasonable inference), "low" (limited signal), or "assumed" (no direct evidence — extrapolated from patterns).
- For each dimension, identify the source: "conversation" (explicitly stated), "connector" (from connected data source), "inferred" (logical derivation), or "assumed" (industry/pattern-based).
- For any dimension with confidence "low" or "assumed", populate what_would_improve with a specific, actionable suggestion.
- MISSING-VARIABLE PENALTY (critical): the score must reward how well-evidenced an idea is, not how good it sounds. Score only what THIS idea actually gives you — never borrow context from other ideas. When the inputs needed to judge a dimension are absent or only "assumed", that dimension's score MUST be depressed, not given the benefit of the doubt:
    - confidence "high"   → no penalty.
    - confidence "medium" → cap that dimension at 75.
    - confidence "low"    → cap that dimension at 60.
    - confidence "assumed"→ cap that dimension at 45.
  Apply the cap to the dimension score itself (so it flows into the weighted jaspen_score). evidence_quality must reflect the share of dimensions backed by real signal: if most dimensions are "assumed", evidence_quality is low (≤40). A vague or under-specified idea must end up with a meaningfully lower jaspen_score than a fully-evidenced one — that gap is the whole point of the trade-off.
- Score EACH dimension honestly with its confidence; the system computes jaspen_score and score_category deterministically from your dimension scores + confidence caps + the objective weights. Do NOT try to back-solve dimensions to hit a target overall score — judge each dimension on its own merits. (For reference only: jaspen_score is the weighted average of the 6 capped dimension scores; categories are Excellent 80-100, Good 60-79, Fair 40-59, At Risk 0-39. Provide your best estimate of jaspen_score and score_category, but the system value is authoritative.)

JSON format:

{{
    "name": "<a short, specific name for THIS idea — derived from the conversation, max 60 chars. Never use generic phrases like 'Baseline Analysis', 'Jaspen Project', 'Strategy Analysis', 'Initiative', or 'Untitled'. Use the actual product, market, or initiative the user is describing (e.g. 'AI HR analytics for mid-market', 'Usage-based AP invoice PLG', 'Restaurant inventory copilot').>",
    "jaspen_score": <weighted average of 6 dimension scores, 0-100>,
    "score_category": "<Excellent|Good|Fair|At Risk>",
    "dimensions": {{
        "market_opportunity": {{
            "score": <0-100>,
            "confidence": "<high|medium|low|assumed>",
            "source": "<conversation|connector|inferred|assumed>",
            "rationale": "<1-2 sentences>",
            "what_would_improve": "<specific action or null if confidence is high>"
        }},
        "financial_viability": {{
            "score": <0-100>,
            "confidence": "<high|medium|low|assumed>",
            "source": "<conversation|connector|inferred|assumed>",
            "rationale": "<1-2 sentences>",
            "what_would_improve": "<specific action or null if confidence is high>"
        }},
        "execution_readiness": {{
            "score": <0-100>,
            "confidence": "<high|medium|low|assumed>",
            "source": "<conversation|connector|inferred|assumed>",
            "rationale": "<1-2 sentences>",
            "what_would_improve": "<specific action or null if confidence is high>"
        }},
        "strategic_alignment": {{
            "score": <0-100>,
            "confidence": "<high|medium|low|assumed>",
            "source": "<conversation|connector|inferred|assumed>",
            "rationale": "<1-2 sentences>",
            "what_would_improve": "<specific action or null if confidence is high>"
        }},
        "risk_profile": {{
            "score": <0-100, where higher = lower risk>,
            "confidence": "<high|medium|low|assumed>",
            "source": "<conversation|connector|inferred|assumed>",
            "rationale": "<1-2 sentences>",
            "what_would_improve": "<specific action or null if confidence is high>"
        }},
        "evidence_quality": {{
            "score": <0-100>,
            "confidence": "<high|medium|low|assumed>",
            "source": "<conversation|connector|inferred|assumed>",
            "rationale": "<1-2 sentences>",
            "what_would_improve": "<specific action or null if confidence is high>"
        }}
    }},
    "component_scores": {{
        "financial_health": <same as financial_viability score>,
        "operational_efficiency": <same as execution_readiness score>,
        "market_position": <same as market_opportunity score>,
        "execution_readiness": <same as execution_readiness score>
    }},
    "component_rationale": {{
        "financial_health": "<same as financial_viability rationale or null>",
        "operational_efficiency": "<same as execution_readiness rationale or null>",
        "market_position": "<same as market_opportunity rationale or null>",
        "execution_readiness": "<same as execution_readiness rationale or null>"
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

    analysis_text = None
    try:
        analysis_text, _usage = _strategy_generate_reply(
            [{"role": "user", "content": analysis_prompt}],
            system_prompt=system_prompt,
            model_selection=model_selection,
            llm_model=llm_model,
            strategy_objective=strategy_objective,
            max_tokens=8000,
            temperature=0,
        )
    except Exception as routed_exc:
        if isinstance(model_selection, dict):
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
            temperature=0,  # Deterministic — same input → same scores
            max_tokens=4000
        )
        analysis_text = response.choices[0].message.content

    parsed = _normalize_scorecard_payload(_extract_json_object(analysis_text))
    # Deterministic final step: recompute the score from the (capped) dimensions
    # in Python instead of trusting the model's arithmetic. `weights` is the
    # objective-specific weight map resolved above.
    return _recompute_jaspen_score(parsed, weights)


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
        # Caller-provided name (request body) takes precedence; otherwise we
        # let the LLM-derived `name` field in analysis_result win further
        # below. `requested_name` distinguishes "user picked this" from
        # "use whatever the AI produced".
        requested_name = (data.get('name') or data.get('project_name') or '').strip() or None
        project_name = requested_name  # may be None — resolved after scoring
        framework_id = data.get('framework_id')
        project_description = (data.get('description') or '').strip()
        # When true: save result as a scenario/version rather than overwriting the baseline session result
        create_as_version = bool(data.get('create_as_version', False))
        version_label = str(data.get('version_label') or '').strip() or None

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
                'error': 'Thinking power limit reached',
                'required_credits': analysis_credit_cost,
                'credits_remaining': user.credits_remaining,
                'plan_key': to_public_plan(user.subscription_plan),
                'monthly_credit_limit': get_monthly_credit_limit(user.subscription_plan, current_app.config),
                'suggestion': 'Purchase a credit pack or upgrade your plan.',
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

        # Resolve the final project_name. Priority:
        #   1. Caller-provided name (request body)
        #   2. AI-generated `name` in analysis_result (preferred default)
        #   3. First user message snippet from the transcript
        #   4. 'Untitled idea' as the absolute last resort
        # Never default to 'Baseline Analysis' or 'Jaspen Project'.
        _BANNED_PLACEHOLDER_NAMES = {
            'baseline analysis', 'baseline', 'jaspen project', 'jaspen analysis',
            'strategy analysis', 'initiative', 'untitled', 'untitled idea', 'project',
        }

        def _is_meaningful_name(candidate):
            s = str(candidate or '').strip()
            if not s:
                return False
            if s.lower() in _BANNED_PLACEHOLDER_NAMES:
                return False
            return True

        ai_name = None
        if isinstance(analysis_result, dict):
            ai_name = (
                _clean_scorecard_text(analysis_result.get('name'))
                or _clean_scorecard_text(analysis_result.get('project_name'))
                or _clean_scorecard_text(analysis_result.get('initiative_name'))
            )

        if _is_meaningful_name(requested_name):
            project_name = requested_name
        elif _is_meaningful_name(ai_name):
            project_name = ai_name
        else:
            # Derive from the first non-trivial user message in the transcript.
            derived = None
            for line in str(transcript or '').splitlines():
                clean = line.strip()
                if not clean:
                    continue
                # Strip leading speaker labels like "User:" or "u:"
                if ':' in clean[:8]:
                    clean = clean.split(':', 1)[1].strip()
                if len(clean) >= 12:
                    derived = clean[:60].rstrip('.,;: ') + ('…' if len(clean) > 60 else '')
                    break
            project_name = derived or 'Untitled idea'

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
            }
        }

        charged, remaining = consume_credits(user, analysis_credit_cost)
        if not charged:
            return jsonify({
                'error': 'Thinking power limit reached',
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
        # Persist the bare analysis as the session result AND embed the
        # baseline scorecard so every downstream consumer (get_thread_bundle,
        # _persist_scenario_snapshot_to_session, frontend refreshBundle) can
        # find it without falling back through reconstruction heuristics.
        normalized_baseline = _normalize_scorecard_payload(analysis)
        analysis['_baseline_scorecard'] = normalized_baseline
        analysis['scorecard_snapshots'] = []
        analysis['selected_scorecard_id'] = analysis_id

        if create_as_version:
            # Version mode: preserve the baseline — only add to analysis history and
            # save as a named scenario so it appears in bundle.scenarios on restore.
            session['analysis_history'] = history
            session['analyses'] = history
            session['timestamp'] = generated_at
            sessions[session_key or resolved_thread_id] = session
            persisted_session = save_user_sessions(current_user_id, sessions)

            # Store as a named scenario so the bundle surfaces it in scorecardSnapshots
            _snap_label = version_label or f'Version {len(history)}'
            try:
                _create_scenario_record(
                    current_user_id,
                    resolved_thread_id,
                    deltas={},
                    label=_snap_label,
                    baseline=session.get('result') or None,
                    result=analysis,
                    plan_key=None,
                )
            except Exception as _e:
                current_app.logger.warning('create_as_version scenario save failed: %s', _e)
        else:
            session['result'] = analysis
            session['analysis_history'] = history
            session['analyses'] = history
            session['adopted_analysis_id'] = analysis_id
            session_baseline_inputs = _extract_baseline_inputs(analysis)
            session_baseline_inputs, session_lever_catalog = _build_scenario_lever_catalog(analysis, session_baseline_inputs)
            session['baseline_inputs'] = session_baseline_inputs
            session['lever_catalog'] = session_lever_catalog
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

        # Fire-and-forget: extract business facts from this score into persistent user memory.
        try:
            from app.routes.ai_agent import extract_and_update_user_memory
            _score_val = analysis_result.get('jaspen_score')
            _industry_val = str(
                (session.get('intake_context') or {}).get('industry')
                or (session.get('result') or {}).get('industry')
                or ''
            ).strip()
            _mem_thread = threading.Thread(
                target=extract_and_update_user_memory,
                args=(
                    current_user_id,
                    project_name,
                    effective_description,
                    _score_val,
                    _industry_val,
                    model_selection,
                ),
                daemon=True,
            )
            _mem_thread.start()
        except Exception:
            current_app.logger.exception("Failed to start user memory extraction thread")

        # Ensure scenario-thread storage exists, even before any scenario/WBS is created.
        all_data = _load_scenarios(current_user_id)
        td = all_data.get(resolved_thread_id)
        if not isinstance(td, dict):
            td = _thread_entry()
        if not isinstance(td.get('scenarios'), dict):
            td['scenarios'] = {}
        if not isinstance(td.get('baseline_inputs'), dict):
            td['baseline_inputs'] = {}
        if not isinstance(td.get('lever_catalog'), list):
            td['lever_catalog'] = []
        if 'adopted_scenario_id' not in td:
            td['adopted_scenario_id'] = None
        if td.get('baseline') is None or not td.get('scenarios'):
            td['baseline'] = analysis
            td['baseline_inputs'] = dict(session_baseline_inputs)
            td['lever_catalog'] = list(session_lever_catalog)
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

        from .ai_agent import (
            _estimate_usage_credit_charge,
            _persist_credit_deduction,
            _release_reserved_credits,
            _reserve_preflight_credits,
            _settle_reserved_credits,
        )

        preflight_token_hint = int(current_app.config.get('AI_AGENT_PREFLIGHT_TOKEN_HINT') or 2500)
        credit_reservation = _reserve_preflight_credits(
            user,
            model_selection['model_type'],
            token_hint=preflight_token_hint,
        )
        if not credit_reservation.get('ok'):
            payload = dict(credit_reservation.get('payload') or {})
            payload['code'] = payload.get('code') or 'thinking_power_exhausted'
            payload['remaining_credits'] = int(user.credits_remaining or 0)
            return jsonify(payload), 402
        reserved_credits = int(
            credit_reservation.get('reserved')
            or credit_reservation.get('required')
            or 0
        )
        
        # Create context from analysis
        strategy_objective = analysis_context.get('strategy_objective') or 'balanced'
        key_insights = analysis_context.get('key_insights') if isinstance(analysis_context.get('key_insights'), list) else []
        recommendations = analysis_context.get('recommendations') if isinstance(analysis_context.get('recommendations'), list) else []
        top_risks = analysis_context.get('top_risks') if isinstance(analysis_context.get('top_risks'), list) else []
        assumptions = analysis_context.get('assumptions') if isinstance(analysis_context.get('assumptions'), list) else []

        context_prompt = f"""
You are a Jaspen strategy assistant helping a user interpret an existing scorecard.

SCORECARD SNAPSHOT
- Strategy objective: {strategy_objective}
- Jaspen score: {analysis_context.get('jaspen_score', 'N/A')}
- Component scores: {json.dumps(analysis_context.get('component_scores', {}), indent=2)}
- Financial impact: {json.dumps(analysis_context.get('financial_impact', {}), indent=2)}
- Executive summary: {analysis_context.get('executive_summary') or 'Not provided'}
- Key insights (max 5): {json.dumps(key_insights[:5], indent=2)}
- Recommendations (max 5): {json.dumps(recommendations[:5], indent=2)}
- Top risks (max 5): {json.dumps(top_risks[:5], indent=2)}
- Assumptions/gaps (max 5): {json.dumps(assumptions[:5], indent=2)}

USER QUESTION
{message}

RESPONSE RULES
1) Answer the user's exact question first.
2) Cite scorecard evidence explicitly (metric names, score values, risk/recommendation text).
3) Quantify where possible; if missing data prevents quantification, say exactly which input is missing.
4) Keep it concise and practical:
   - "Direct answer" (2-4 sentences)
   - "Why this matters" (1-2 bullets)
   - "Next actions" (up to 3 bullets)
5) Never claim external data access in this endpoint; rely on provided scorecard context only.
"""

        # Call LLM API
        try:
            ai_response, usage = _strategy_generate_reply(
                [{"role": "user", "content": context_prompt}],
                system_prompt="You are a Jaspen strategy assistant specializing in commercialization strategy and financial optimization.",
                model_selection=model_selection,
                llm_model=model_selection.get('llm_model'),
                strategy_objective=strategy_objective,
                max_tokens=900,
                temperature=0.2,
            )
        except Exception:
            _release_reserved_credits(user, reserved_credits)
            db.session.commit()
            raise

        total_tokens = (usage or {}).get('total_tokens') if isinstance(usage, dict) else None

        credits_charged = _estimate_usage_credit_charge(
            total_tokens,
            model_selection['model_type'],
            (usage or {}).get('provider') if isinstance(usage, dict) else None,
        )
        credit_settlement = _settle_reserved_credits(
            user,
            reserved_credits=reserved_credits,
            actual_credits=credits_charged,
        )
        if not credit_settlement.get('ok'):
            db.session.rollback()
            return jsonify({
                'error': 'Thinking power limit reached.',
                'code': 'thinking_power_exhausted',
                'required_credits': credits_charged,
                'remaining_credits': int(user.credits_remaining or 0),
            }), 402
        remaining = credit_settlement.get('remaining')
        credits_charged = int(credit_settlement.get('charged') or 0)
        _persist_credit_deduction(current_user_id, remaining)

        return jsonify({
            'response': ai_response,
            'model_type': model_selection['model_type'],
            'timestamp': datetime.utcnow().isoformat(),
            'credits': {'charged': credits_charged, 'remaining': remaining},
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


@strategy_bp.route('/scores/<thread_id>/<snapshot_id>', methods=['DELETE'])
@jwt_required()
def delete_score_entry(thread_id, snapshot_id):
    """Delete a single scorecard variant (snapshot) from a thread's score history."""
    try:
        current_user_id = get_jwt_identity()
        sessions = load_user_sessions(current_user_id) or {}
        if not isinstance(sessions, dict):
            return jsonify({'error': 'No sessions found'}), 404

        session = sessions.get(thread_id)
        if not session:
            for k, v in sessions.items():
                if str((v or {}).get('session_id', '')) == str(thread_id):
                    session = v
                    thread_id = k
                    break

        if not isinstance(session, dict):
            return jsonify({'error': 'Thread not found'}), 404

        result = session.get('result')
        if not isinstance(result, dict):
            return jsonify({'error': 'No analysis result for this thread'}), 404

        snapshot_state = _scorecard_snapshot_state(result, thread_id)
        all_snapshots = snapshot_state.get('snapshots') or []

        # Find the snapshot to delete
        target = None
        for s in all_snapshots:
            if str(s.get('id') or s.get('analysis_id') or '') == str(snapshot_id):
                target = s
                break

        if target is None:
            return jsonify({'error': 'Snapshot not found'}), 404

        is_baseline = bool(target.get('isBaseline'))

        if is_baseline:
            # Deleting baseline means removing the entire thread/session
            del sessions[thread_id]
            save_user_sessions(current_user_id, sessions)
            return jsonify({'deleted': 'thread', 'thread_id': thread_id}), 200

        # Deleting a non-baseline snapshot: remove it from scorecard_snapshots
        existing_snapshots = result.get('scorecard_snapshots')
        if isinstance(existing_snapshots, list):
            result['scorecard_snapshots'] = [
                s for s in existing_snapshots
                if str(s.get('id') or s.get('analysis_id') or '') != str(snapshot_id)
            ]
        session['result'] = result
        sessions[thread_id] = session
        save_user_sessions(current_user_id, sessions)

        return jsonify({'deleted': 'snapshot', 'thread_id': thread_id, 'snapshot_id': snapshot_id}), 200

    except Exception as e:
        current_app.logger.error("[delete_score_entry] %s", e)
        return jsonify({'error': 'Failed to delete score entry'}), 500


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
        from .ai_agent import _public_usage_payload

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
                'usage': _public_usage_payload(
                    {},
                    model_type=model_selection['model_type'],
                    credits_charged=0,
                    credits_remaining=int(user.credits_remaining or 0),
                ),
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

        from .ai_agent import (
            _estimate_usage_credit_charge,
            _generate_routed_chat_reply,
            _persist_credit_deduction,
            _release_reserved_credits,
            _reserve_preflight_credits,
            _settle_reserved_credits,
        )

        preflight_token_hint = int(current_app.config.get('AI_AGENT_PREFLIGHT_TOKEN_HINT') or 2500)
        credit_reservation = _reserve_preflight_credits(
            user,
            model_selection['model_type'],
            token_hint=preflight_token_hint,
        )
        if not credit_reservation.get('ok'):
            payload = dict(credit_reservation.get('payload') or {})
            payload['code'] = payload.get('code') or 'thinking_power_exhausted'
            payload['remaining_credits'] = int(user.credits_remaining or 0)
            return jsonify(payload), 402
        reserved_credits = int(
            credit_reservation.get('reserved')
            or credit_reservation.get('required')
            or 0
        )

        try:
            reply, usage = _generate_routed_chat_reply(
                routed_messages,
                model_selection,
                system_prompt=system_prompt,
                strategy_objective=strategy_objective,
                max_tokens=900,
                temperature=0.2,
            )
        except Exception:
            _release_reserved_credits(user, reserved_credits)
            db.session.commit()
            raise

        credits_charged = _estimate_usage_credit_charge(
            (usage or {}).get('total_tokens'),
            model_selection['model_type'],
            (usage or {}).get('provider'),
        )
        credit_settlement = _settle_reserved_credits(
            user,
            reserved_credits=reserved_credits,
            actual_credits=credits_charged,
        )
        if not credit_settlement.get('ok'):
            db.session.rollback()
            return jsonify({
                'error': 'Thinking power limit reached.',
                'code': 'thinking_power_exhausted',
                'required_credits': credits_charged,
                'remaining_credits': int(user.credits_remaining or 0),
            }), 402
        remaining = credit_settlement.get('remaining')
        credits_charged = int(credit_settlement.get('charged') or 0)
        _persist_credit_deduction(current_user_id, remaining)

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
            'usage': _public_usage_payload(
                usage,
                model_type=model_selection['model_type'],
                credits_charged=credits_charged,
                credits_remaining=remaining,
            ),
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
        'lever_catalog': [],
        'scenarios': {},
        'adopted_scenario_id': None,
        'project_wbs': None,
        'strategy_objective': 'balanced',
    }


def _infer_lever_type(key):
    k = str(key).lower()
    if any(p in k for p in ('budget', 'invest', 'cost', 'price', 'revenue', 'value', 'ebitda', 'npv')):
        return 'currency'
    if any(p in k for p in ('month', 'timeline', 'period', 'duration')):
        return 'months'
    if any(p in k for p in ('percent', 'rate', 'margin', 'growth', 'penetrat', 'roi', 'irr', 'adoption')):
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

    sessions = load_user_sessions(user_id) or {}
    session_key, session = _resolve_session_entry(sessions, thread_id)

    # If the thread_id is an internal UUID alias, fall back to the canonical session key
    # (e.g. thread_id='378d472a-...' → session stored at key='thread_1755649fe585')
    canonical_key = str(session_key or thread_id)
    if not isinstance(thread_data, dict) and canonical_key != str(thread_id):
        thread_data = all_data.get(canonical_key)

    if not isinstance(thread_data, dict):
        thread_data = _thread_entry()
        all_data[thread_id] = thread_data

    baseline = thread_data.get('baseline') if isinstance(thread_data.get('baseline'), dict) else None
    baseline_inputs = thread_data.get('baseline_inputs') if isinstance(thread_data.get('baseline_inputs'), dict) else {}
    lever_catalog = thread_data.get('lever_catalog') if isinstance(thread_data.get('lever_catalog'), list) else []

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

    if isinstance(baseline, dict):
        baseline_inputs, generated_catalog = _build_scenario_lever_catalog(baseline, baseline_inputs)
        thread_data['baseline_inputs'] = baseline_inputs
        # Regenerate if stored catalog is missing any standard levers (not just when completely empty)
        stored_keys = {row.get('key') for row in lever_catalog if isinstance(row, dict)}
        std_keys = set(_STANDARD_SCENARIO_LEVERS.keys())
        if not lever_catalog or not std_keys.issubset(stored_keys):
            thread_data['lever_catalog'] = generated_catalog

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


def _coerce_positive(value, fallback):
    parsed = _safe_float(value)
    if parsed is None or parsed <= 0:
        return float(fallback)
    return float(parsed)


def _baseline_financial_value(baseline, key):
    if not isinstance(baseline, dict):
        return None
    return _metric_numeric_value(baseline.get('financial_impact') if isinstance(baseline.get('financial_impact'), dict) else {}, key)


def _infer_standard_scenario_inputs(baseline, baseline_inputs):
    observed = dict(baseline_inputs or {})
    projected_ebitda = _baseline_financial_value(baseline, 'projected_ebitda')
    roi_percent = _baseline_financial_value(baseline, 'roi_opportunity')
    potential_loss = _baseline_financial_value(baseline, 'potential_loss')

    initial_investment = _coerce_positive(
        observed.get('initial_investment') or observed.get('total_investment') or observed.get('capex'),
        _metric_numeric_value(
            baseline.get('investment_analysis') if isinstance(baseline.get('investment_analysis'), dict) else {},
            'total_investment_required',
        ) or (
            projected_ebitda / max((roi_percent or 25.0) / 100.0, 0.05) * 0.3
            if projected_ebitda
            else (potential_loss * 0.2 if potential_loss else 150000.0)
        ),
    )
    implementation_timeline = _coerce_positive(
        observed.get('implementation_timeline') or observed.get('timeline_months'),
        6.0,
    )
    team_size = _coerce_positive(
        observed.get('team_size') or observed.get('team_capacity_fte') or observed.get('headcount'),
        3.0,
    )
    target_adoption_rate = _coerce_positive(
        observed.get('target_adoption_rate') or observed.get('adoption_rate'),
        70.0,
    )
    expected_annual_return = _coerce_positive(
        observed.get('expected_annual_return') or observed.get('expected_annual_savings') or observed.get('annual_revenue'),
        projected_ebitda or max(initial_investment * 0.3, 50000.0),
    )
    annual_operational_cost = _coerce_positive(
        observed.get('annual_operational_cost') or observed.get('opex') or observed.get('annual_cost'),
        max(initial_investment * 0.15, 25000.0),
    )

    inferred = {
        'initial_investment': initial_investment,
        'implementation_timeline': implementation_timeline,
        'team_size': team_size,
        'target_adoption_rate': target_adoption_rate,
        'expected_annual_return': expected_annual_return,
        'annual_operational_cost': annual_operational_cost,
    }
    observed_keys = {str(k) for k, v in observed.items() if _safe_float(v) is not None}
    return inferred, observed_keys


def _build_scenario_lever_catalog(baseline, baseline_inputs):
    inferred_inputs, observed_keys = _infer_standard_scenario_inputs(baseline, baseline_inputs)
    merged_inputs = dict(baseline_inputs or {})
    merged_inputs.update(inferred_inputs)
    catalog = []
    seen = set()

    for key, value in merged_inputs.items():
        if key in SCENARIO_OUTPUT_FIELDS or key in _OUTPUT_FIELDS:
            continue
        numeric_value = _safe_float(value)
        if numeric_value is None:
            continue
        seen.add(key)
        meta = _STANDARD_SCENARIO_LEVERS.get(key, {})
        lever_type = str(meta.get('type') or _infer_lever_type(key))
        bounds = _lever_bounds(numeric_value, lever_type)
        catalog.append({
            'id': key,
            'key': key,
            'label': str(meta.get('label') or str(key).replace('_', ' ').title()),
            'type': lever_type,
            'value': round(float(numeric_value), 6),
            'current': round(float(numeric_value), 6),
            'min': bounds['min'],
            'max': bounds['max'],
            'step': bounds['step'],
            'description': str(meta.get('description') or f"Scenario lever for {str(key).replace('_', ' ')}."),
            'source': 'observed' if key in observed_keys else 'estimated',
            'readonly': False,
            'display_multiplier': 1,
        })

    for key, meta in _STANDARD_SCENARIO_LEVERS.items():
        if key in seen:
            continue
        numeric_value = inferred_inputs.get(key)
        if numeric_value is None:
            continue
        lever_type = str(meta.get('type') or _infer_lever_type(key))
        bounds = _lever_bounds(numeric_value, lever_type)
        catalog.append({
            'id': key,
            'key': key,
            'label': str(meta.get('label') or str(key).replace('_', ' ').title()),
            'type': lever_type,
            'value': round(float(numeric_value), 6),
            'current': round(float(numeric_value), 6),
            'min': bounds['min'],
            'max': bounds['max'],
            'step': bounds['step'],
            'description': str(meta.get('description') or f"Scenario lever for {str(key).replace('_', ' ')}."),
            'source': 'estimated',
            'readonly': False,
            'display_multiplier': 1,
        })

    # If catalog is sparse, supplement with assumption-derived levers.
    if len(catalog) < 4:
        assumption_levers = _extract_assumption_levers(baseline)
        existing_keys = {row['key'] for row in catalog}
        for lever in assumption_levers:
            if lever['key'] in existing_keys:
                continue
            catalog.append(lever)
            existing_keys.add(lever['key'])
            if len(catalog) >= 8:
                break

    catalog.sort(key=lambda row: (0 if row['key'] in _STANDARD_SCENARIO_LEVERS else 1, row['label']))
    return merged_inputs, catalog


def _build_lever_context(baseline_inputs, suggested_deltas):
    context = []
    suggestions = suggested_deltas if isinstance(suggested_deltas, dict) else {}
    for key, raw_current in (baseline_inputs or {}).items():
        if key in SCENARIO_OUTPUT_FIELDS or key in _OUTPUT_FIELDS:
            continue
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
            if key in SCENARIO_OUTPUT_FIELDS or key in _OUTPUT_FIELDS:
                continue
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
    model_selection=None,
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
    "lever_id": "why this specific lever changed and what the new value achieves"
  }}
}}

CRITICAL — delta values are ABSOLUTE NEW TARGET VALUES, not change amounts:
- If team_size current=3 and you want it to become 5, set "team_size": 5 (not 2).
- If target_adoption_rate current=70 and you want it to reach 85, set "target_adoption_rate": 85 (not 15).
- If implementation_timeline current=6 and you want it shortened to 4, set "implementation_timeline": 4 (not -2).
- Always set the value you want the lever to BE, not the amount to change by.

Rules:
- Suggest 1-6 lever changes.
- Keep values within realistic bounds (use the min/max/step from the lever catalog).
- Values must be numeric and represent the absolute new state of the lever.
- Always include rationale for every lever inside reasons.
- Reasons should describe the lever's change: e.g. "Increased from 3 to 5 to support faster rollout".
- Do not invent new lever ids.
- Align the recommendation with the objective profile while still honoring the user's request.
""".strip()

    try:
        raw_reply, _usage = _strategy_generate_reply(
            [{"role": "user", "content": prompt}],
            system_prompt="You are a strategy scenario planner. Return strict JSON only.",
            model_selection=model_selection,
            llm_model=llm_model,
            strategy_objective=objective,
            temperature=0.2,
            max_tokens=900,
        )
        parsed = _extract_json_object(raw_reply)
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


def _infer_wbs_planning_mode(scorecard, instruction, scenario_payload=None):
    text_parts = []
    if isinstance(instruction, str):
        text_parts.append(instruction)
    if isinstance(scorecard, dict):
        for key in ('project_name', 'executive_summary', 'what_drove_this_score', 'summary'):
            value = scorecard.get(key)
            if isinstance(value, str):
                text_parts.append(value)
    if isinstance(scenario_payload, dict):
        for key in ('label', 'rationale'):
            value = scenario_payload.get(key)
            if isinstance(value, str):
                text_parts.append(value)
    haystack = " ".join(text_parts).lower()
    program_markers = (
        'program',
        'portfolio',
        'multi-workstream',
        'cross-functional',
        'transformation',
        'enterprise-wide',
        'enterprise wide',
        'multi department',
        'multi-team',
        'multi team',
    )
    return 'program' if any(marker in haystack for marker in program_markers) else 'project'


def _heuristic_wbs_text(value, limit=140):
    """Pull readable text out of a risk/recommendation entry (str or dict)."""
    if isinstance(value, str):
        return value.strip()[:limit]
    if isinstance(value, dict):
        for key in ('text', 'risk', 'recommendation', 'action', 'description', 'title', 'name'):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()[:limit]
    return ''


def _heuristic_wbs_suggestion(scorecard, instruction, scenario_payload=None, chat_history=None):
    comps = (scorecard or {}).get('component_scores') if isinstance(scorecard, dict) else {}
    comps = comps if isinstance(comps, dict) else {}
    planning_mode = _infer_wbs_planning_mode(scorecard, instruction, scenario_payload=scenario_payload)
    is_program_mode = planning_mode == 'program'

    # Pull the idea-specific drivers so even the deterministic fallback varies
    # with THIS scorecard: its weak dimensions, its named risks, and its
    # recommendations — not a one-size-fits-all skeleton.
    _sc = scorecard if isinstance(scorecard, dict) else {}
    top_risks_raw = _sc.get('top_risks') if isinstance(_sc.get('top_risks'), list) else _sc.get('risks')
    top_risks = [t for t in (_heuristic_wbs_text(r) for r in (top_risks_raw or [])) if t][:4]
    recommendations_raw = _sc.get('recommendations') if isinstance(_sc.get('recommendations'), list) else []
    recommendations = [t for t in (_heuristic_wbs_text(r, 160) for r in recommendations_raw) if t][:3]

    initiative = str(
        (scorecard or {}).get('initiative_name')
        or (scorecard or {}).get('project_name')
        or (scorecard or {}).get('business_description', '')[:60]
        or 'the initiative'
    ).strip()

    # Phase 1: Discovery & Alignment
    discovery_tasks = [
        {
            'id': 'kickoff_alignment',
            'title': f'Kickoff alignment and success criteria for {initiative}',
            'description': 'Align stakeholders on scope, objectives, and measurable outcomes. Define RACI and communication cadence.',
            'priority': 'high',
            'estimated_days': 5,
            'suggested_role': 'Project Manager',
            'function': 'PMO',
            'activity_type': 'governance',
            'depends_on': [],
            'risk_area': 'execution_readiness',
        },
        {
            'id': 'current_state_assessment',
            'title': 'Current state assessment and gap analysis',
            'description': 'Document as-is state, identify gaps against target, and validate assumptions from the scorecard.',
            'priority': 'high',
            'estimated_days': 7,
            'suggested_role': 'Business Analyst',
            'function': 'PMO',
            'activity_type': 'planning',
            'depends_on': ['kickoff_alignment'],
            'risk_area': 'execution_readiness',
        },
    ]

    # Phase 2: Planning & Design
    planning_tasks = [
        {
            'id': 'dependency_map',
            'title': 'Create execution roadmap and dependency map',
            'description': 'Map workstream dependencies, establish execution cadence, and sequence deliverables.',
            'priority': 'high',
            'estimated_days': 5,
            'suggested_role': 'Program Manager' if is_program_mode else 'Project Manager',
            'function': 'PMO',
            'activity_type': 'planning',
            'depends_on': ['current_state_assessment'],
            'risk_area': 'execution_readiness',
        },
        {
            'id': 'resource_plan',
            'title': 'Resource and budget allocation plan',
            'description': 'Identify required resources, assign owners, and validate budget against execution roadmap.',
            'priority': 'high',
            'estimated_days': 6,
            'suggested_role': 'Finance Analyst',
            'function': 'Finance',
            'activity_type': 'financial_modeling',
            'depends_on': ['dependency_map'],
            'risk_area': 'financial_health',
        },
        {
            'id': 'risk_register',
            'title': 'Build risk register and mitigation playbook',
            'description': 'Catalog top risks from the scorecard, assign owners, and define mitigation actions.',
            'priority': 'high',
            'estimated_days': 4,
            'suggested_role': 'Risk Manager',
            'function': 'PMO',
            'activity_type': 'risk_management',
            'depends_on': ['current_state_assessment'],
            'risk_area': 'execution_readiness',
        },
    ]
    if is_program_mode:
        planning_tasks.append({
            'id': 'governance_rhythm',
            'title': 'Establish program governance and steering committee rhythm',
            'description': 'Set up steering committee cadence, workstream leads, escalation paths, and decision rights.',
            'priority': 'high',
            'estimated_days': 6,
            'suggested_role': 'Program Director',
            'function': 'PMO',
            'activity_type': 'governance',
            'depends_on': ['kickoff_alignment'],
            'risk_area': 'execution_readiness',
        })

    # Phase 3: Execution (score-driven tasks)
    # Priority scales with how far below target a dimension is: the weaker the
    # score, the higher the priority. Deterministic for a given scorecard.
    def _priority_for(score):
        s = float(score or 0)
        if s < 50:
            return 'high'
        if s < 65:
            return 'high'
        return 'medium'

    execution_tasks = []
    if float(comps.get('market_position') or 0) < 75:
        execution_tasks.append({
            'id': 'market_validation',
            'title': f'Customer and market assumption validation for {initiative}',
            'description': f'Run structured customer interviews and market tests to sharpen the value proposition (market position scored {int(float(comps.get("market_position") or 0))}/100).',
            'priority': _priority_for(comps.get('market_position')),
            'estimated_days': 10,
            'suggested_role': 'Product Marketing',
            'function': 'Marketing',
            'activity_type': 'market_validation',
            'depends_on': ['dependency_map'],
            'risk_area': 'market_position',
        })
    if float(comps.get('operational_efficiency') or 0) < 75:
        execution_tasks.append({
            'id': 'process_optimization',
            'title': 'Process bottleneck mapping and handoff automation',
            'description': f'Identify and remediate top process bottlenecks; automate manual handoffs (operational efficiency scored {int(float(comps.get("operational_efficiency") or 0))}/100).',
            'priority': _priority_for(comps.get('operational_efficiency')),
            'estimated_days': 12,
            'suggested_role': 'Operations Lead',
            'function': 'Operations',
            'activity_type': 'process_optimization',
            'depends_on': ['dependency_map'],
            'risk_area': 'operational_efficiency',
        })
    if float(comps.get('financial_health') or 0) < 75:
        execution_tasks.append({
            'id': 'financial_model_hardening',
            'title': f'Financial model hardening and payback validation for {initiative}',
            'description': f'Pressure-test unit economics, ramp/payback assumptions, and sensitivity ranges (financial health scored {int(float(comps.get("financial_health") or 0))}/100).',
            'priority': _priority_for(comps.get('financial_health')),
            'estimated_days': 8,
            'suggested_role': 'Finance Analyst',
            'function': 'Finance',
            'activity_type': 'financial_modeling',
            'depends_on': ['resource_plan'],
            'risk_area': 'financial_health',
        })
    if float(comps.get('execution_readiness') or 0) < 75:
        execution_tasks.append({
            'id': 'staffing_plan',
            'title': 'Staff critical roles and contingency coverage',
            'description': f'Confirm owners and contingency coverage for all critical path tasks (execution readiness scored {int(float(comps.get("execution_readiness") or 0))}/100).',
            'priority': _priority_for(comps.get('execution_readiness')),
            'estimated_days': 6,
            'suggested_role': 'HR Business Partner',
            'function': 'HR',
            'activity_type': 'staffing',
            'depends_on': ['resource_plan'],
            'risk_area': 'execution_readiness',
        })
    # Risk-driven mitigation tasks — one per named top risk on the scorecard.
    for _i, _risk in enumerate(top_risks):
        execution_tasks.append({
            'id': f'risk_mitigation_{_i + 1}',
            'title': f'Mitigate: {_risk}',
            'description': f'Define and execute a mitigation for the scorecard risk "{_risk}", with a named owner and a measurable exit criterion.',
            'priority': 'high' if _i == 0 else 'medium',
            'estimated_days': 6,
            'suggested_role': 'Risk Manager',
            'function': 'PMO',
            'activity_type': 'risk_management',
            'depends_on': ['risk_register'],
            'risk_area': 'execution_readiness',
        })
    # Always include a core delivery task
    execution_tasks.append({
        'id': 'core_delivery',
        'title': f'Core delivery and implementation sprint for {initiative}',
        'description': 'Execute primary deliverables per the roadmap; track against milestones weekly.',
        'priority': 'high',
        'estimated_days': 21,
        'suggested_role': 'Project Lead',
        'function': 'Operations',
        'activity_type': 'delivery',
        'depends_on': ['dependency_map', 'resource_plan'],
        'risk_area': 'execution_readiness',
    })
    # Recommendation-driven tasks — operationalize what the scorecard advised.
    for _i, _rec in enumerate(recommendations):
        execution_tasks.append({
            'id': f'recommendation_{_i + 1}',
            'title': f'Action recommendation: {_rec}',
            'description': f'Operationalize the scorecard recommendation "{_rec}" into concrete deliverables with an owner and due date.',
            'priority': 'medium',
            'estimated_days': 7,
            'suggested_role': 'Project Lead',
            'function': 'Operations',
            'activity_type': 'delivery',
            'depends_on': ['core_delivery'],
            'risk_area': 'execution_readiness',
        })

    # Phase 4: Change Management & Enablement
    change_tasks = [
        {
            'id': 'change_management',
            'title': 'Stakeholder change management and communication plan',
            'description': 'Develop and execute change management plan covering training, comms, and adoption milestones.',
            'priority': 'medium',
            'estimated_days': 14,
            'suggested_role': 'Change Manager',
            'function': 'HR',
            'activity_type': 'change_management',
            'depends_on': ['core_delivery'],
            'risk_area': 'execution_readiness',
        },
        {
            'id': 'training_rollout',
            'title': 'Training and enablement rollout',
            'description': 'Deliver training sessions, job aids, and knowledge base for impacted teams.',
            'priority': 'medium',
            'estimated_days': 10,
            'suggested_role': 'Training Lead',
            'function': 'HR',
            'activity_type': 'training',
            'depends_on': ['change_management'],
            'risk_area': 'execution_readiness',
        },
    ]

    # Phase 5: Validation & Launch
    validation_tasks = [
        {
            'id': 'uat_validation',
            'title': 'User acceptance testing and quality validation',
            'description': 'Run UAT with key stakeholders, document findings, and close critical gaps before launch.',
            'priority': 'high',
            'estimated_days': 8,
            'suggested_role': 'QA Lead',
            'function': 'Operations',
            'activity_type': 'quality',
            'depends_on': ['core_delivery'],
            'risk_area': 'execution_readiness',
        },
        {
            'id': 'launch_readiness',
            'title': 'Launch readiness review and go/no-go checkpoint',
            'description': 'Conduct formal readiness review with sponsors; confirm all launch criteria are met.',
            'priority': 'high',
            'estimated_days': 3,
            'suggested_role': 'Project Manager',
            'function': 'PMO',
            'activity_type': 'governance',
            'depends_on': ['uat_validation', 'training_rollout'],
            'risk_area': 'execution_readiness',
        },
    ]

    # Phase 6: Measurement & Value Capture
    measurement_tasks = [
        {
            'id': 'kpi_baseline',
            'title': 'Establish KPI baseline and value-capture tracking',
            'description': 'Define measurement framework, baseline current KPIs, and set up tracking dashboards.',
            'priority': 'medium',
            'estimated_days': 7,
            'suggested_role': 'Analytics Lead',
            'function': 'Finance',
            'activity_type': 'reporting',
            'depends_on': ['launch_readiness'],
            'risk_area': 'financial_health',
        },
        {
            'id': 'post_launch_review',
            'title': '30-day post-launch review and lessons learned',
            'description': 'Assess adoption, value realization, and document lessons learned for continuous improvement.',
            'priority': 'medium',
            'estimated_days': 5,
            'suggested_role': 'Program Manager',
            'function': 'PMO',
            'activity_type': 'reporting',
            'depends_on': ['kpi_baseline'],
            'risk_area': 'execution_readiness',
        },
    ]

    scenario_note = ''
    if isinstance(scenario_payload, dict) and scenario_payload.get('label'):
        scenario_note = f" using scenario '{scenario_payload.get('label')}'"

    phases = [
        {'name': 'Discovery & Alignment', 'tasks': discovery_tasks},
        {'name': 'Planning & Design', 'tasks': planning_tasks},
        {'name': 'Execution', 'tasks': execution_tasks},
        {'name': 'Change Management', 'tasks': change_tasks},
        {'name': 'Validation & Launch', 'tasks': validation_tasks},
        {'name': 'Measurement', 'tasks': measurement_tasks},
    ]

    return {
        'name': 'AI Generated Program Plan' if is_program_mode else 'AI Generated Project Plan',
        'description': str(instruction or '').strip() or 'Generated from scorecard drivers and risk profile.',
        'summary': f"Generated{scenario_note} using {planning_mode} planning mode, component score priorities, and risk hotspots.",
        'phases': phases,
        'planning_mode': planning_mode,
    }


def _generate_ai_wbs_suggestion(
    client,
    llm_model,
    scorecard,
    instruction,
    scenario_payload=None,
    model_selection=None,
    strategy_objective='balanced',
    chat_history=None,
):
    scorecard_payload = scorecard if isinstance(scorecard, dict) else {}
    scenario_context = scenario_payload if isinstance(scenario_payload, dict) else {}
    planning_mode = _infer_wbs_planning_mode(scorecard_payload, instruction, scenario_payload=scenario_context)
    planning_brief = (
        "Program mode: include governance, workstream coordination, dependency/risk controls, and cross-functional ownership."
        if planning_mode == 'program'
        else "Project mode: include focused linear execution from discovery to delivery with clear owners and dependencies."
    )
    top_risks = scorecard_payload.get('top_risks') if isinstance(scorecard_payload.get('top_risks'), list) else scorecard_payload.get('risks')
    if not isinstance(top_risks, list):
        top_risks = []
    recommendations = scorecard_payload.get('recommendations') if isinstance(scorecard_payload.get('recommendations'), list) else []

    # Trim scorecard to essential fields to keep the prompt concise
    scorecard_summary = {
        k: scorecard_payload[k]
        for k in ('initiative_name', 'project_name', 'jaspen_score', 'executive_summary',
                  'strategy_objective', 'component_scores', 'key_insights', 'recommendations',
                  'top_risks', 'business_description', 'industry', 'company_size')
        if k in scorecard_payload
    }
    # Derive the canonical initiative name so the AI uses it in every task title
    _initiative_name = str(
        scorecard_payload.get('initiative_name')
        or scorecard_payload.get('project_name')
        or ''
    ).strip()

    conversation_block = ''
    if isinstance(chat_history, list) and chat_history:
        conversation_block = '\nConversation context (use this to make tasks specific to this initiative):\n' + '\n'.join(chat_history) + '\n'

    _initiative_label = f'Initiative name: {_initiative_name}\n' if _initiative_name else ''
    prompt = f"""
You are generating a project WBS from a live strategy session.
Planning mode: {planning_mode}
Planning guidance: {planning_brief}
{_initiative_label}
Instruction:
{instruction or "Generate an actionable WBS from this scorecard and conversation."}
{conversation_block}
Scorecard context:
{json.dumps(scorecard_summary, indent=2)}

Top risks:
{json.dumps(top_risks[:5], indent=2)}

Recommendations:
{json.dumps(recommendations[:5], indent=2)}

Scenario context (if provided):
{json.dumps({k: scenario_context[k] for k in ('name', 'lever_changes', 'rationale', 'result') if k in scenario_context} if scenario_context else {}, indent=2)}

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
          "function": "PMO|Finance|Operations|HR|IT|Marketing|Sales|Product|Legal|Security|Other",
          "activity_type": "governance|planning|delivery|risk_management|financial_modeling|change_management|training|integration|quality|reporting|other",
          "dependencies": ["other-task-id"],
          "risk_area": "which component score this addresses"
        }}
      ]
    }}
  ]
}}

Rules:
- Return 10-18 tasks total spread across 4-6 meaningful phases.
- Phases must follow a logical sequence: Discovery -> Planning -> Build/Execute -> Validate -> Launch -> Operate.
- CRITICAL: Every task title must be specific to THIS initiative — no generic titles like "Research" or "Planning". Use the conversation, scorecard, and the initiative name above to name exactly what is being done, by whom, for what outcome. Never use "Baseline Analysis" in a task title; use the actual initiative or project name.
- DETERMINISM: Given the same scorecard, scenario, and instruction, produce the SAME plan every time. Derive tasks mechanically from the inputs below — do not invent variety for its own sake.
- DRIVE TASKS FROM THE SCORECARD, do not emit a generic template:
  * For EACH component score below 75, include at least one remediation task that names the weak dimension and the specific gap it closes (lower score = higher priority).
  * For EACH of the top risks, include a mitigation task that names the risk and its owner.
  * For EACH key insight / recommendation, include a task that operationalizes it.
  * Component scores at or above 75 are strengths — reference them to sequence and de-risk, not to create busywork tasks.
- The number and shape of Execution-phase tasks MUST vary with the scorecard: a weak, high-risk initiative gets more remediation tasks than a strong one. Two different scorecards should not yield interchangeable plans.
- Assign a realistic suggested_role to every task.
- Include function and activity_type for every task.
- Include at least 1 risk-mitigation task, 1 change-management task, and 1 value-capture/measurement task.
- Estimated_days should be realistic for the task complexity (range: 1-15).
- Dependencies must reference real task IDs in the list; avoid circular references.
- Use context from the conversation turns, key_insights, and recommendations to name tasks after REAL work items from this session.
- If a scenario was provided, weight tasks toward the scenario's adopted assumptions and lever changes.
- MINIMUM 10 tasks. If you return fewer than 10 the response will be rejected.
""".strip()

    try:
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FuturesTimeout
        def _call_llm():
            return _strategy_generate_reply(
                [{"role": "user", "content": prompt}],
                system_prompt="You are a senior project planning assistant. Generate initiative-specific execution plans with 10-18 tasks across 4-6 phases. Every task title must be specific and actionable. Return strict JSON only.",
                model_selection=model_selection,
                llm_model=llm_model,
                strategy_objective=strategy_objective,
                temperature=0,  # Deterministic — same scorecard/scenario/instruction → same plan
                max_tokens=4096,
            )
        with ThreadPoolExecutor(max_workers=1) as _pool:
            _future = _pool.submit(_call_llm)
            try:
                raw_reply, _usage = _future.result(timeout=55)
            except _FuturesTimeout:
                raise ValueError('wbs_ai_timeout')
        parsed = _extract_json_object(raw_reply)
        if not isinstance(parsed, dict):
            raise ValueError('invalid_wbs_response')
        if not isinstance(parsed.get('phases'), list) and not isinstance(parsed.get('tasks'), list):
            raise ValueError('invalid_wbs_response')
        # Reject thin plans — AI must return at least 6 tasks or we use the heuristic
        all_tasks = []
        if isinstance(parsed.get('phases'), list):
            for phase in parsed['phases']:
                all_tasks.extend(phase.get('tasks') or [])
        elif isinstance(parsed.get('tasks'), list):
            all_tasks = parsed['tasks']
        if len(all_tasks) < 6:
            raise ValueError('wbs_too_thin')
        return parsed
    except Exception:
        return _heuristic_wbs_suggestion(scorecard, instruction, scenario_payload=scenario_context, chat_history=chat_history)


def _stable_wbs_task_id(phase_name, title, used_ids):
    """Content-derived task id so an identical plan always yields identical ids.

    Hashing (phase + title) keeps a task's id stable across regenerations AND
    across reordering/insertions (unlike a positional counter), which is what
    lets Jira/Smartsheet sync recognize the same task instead of duplicating it.
    On the rare duplicate (same title in the same phase) we append a numeric
    suffix to stay unique within this plan — still fully deterministic.
    """
    basis = f"{str(phase_name or '').strip().lower()}|{str(title or '').strip().lower()}"
    digest = hashlib.sha1(basis.encode('utf-8')).hexdigest()[:10]
    base_id = f"task_{digest}"
    candidate = base_id
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base_id}_{suffix}"
        suffix += 1
    return candidate


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
    used_ids = set()
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
            # Deterministic, content-derived id (not a random UUID) so an
            # identical plan always materializes to identical task ids. The
            # model's requested_id is preserved as an alias below so dependency
            # references still resolve.
            task_id = _stable_wbs_task_id(phase_name, title, used_ids)
            used_ids.add(task_id)
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
            due_date = None

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
            function_name = str(raw.get('function') or raw.get('owner_function') or '').strip()
            if function_name:
                task['function'] = function_name
            activity_type = str(raw.get('activity_type') or '').strip().lower()
            if activity_type:
                task['activity_type'] = activity_type

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

    # Dependency-aware scheduling: forward pass through the dependency graph.
    task_map = {str(item.get('id') or ''): item for item in created if isinstance(item, dict)}
    finish_cache = {}

    def _task_finish(task_id, visiting=None):
        if not task_id or task_id not in task_map:
            return now
        if task_id in finish_cache:
            return finish_cache[task_id]
        visiting = visiting or set()
        if task_id in visiting:
            # Circular dependency guard: fall back to current timestamp.
            return now
        visiting.add(task_id)
        task = task_map[task_id]
        deps = task.get('depends_on') if isinstance(task.get('depends_on'), list) else []
        start_at = now
        for dep_id in deps:
            dep_finish = _task_finish(str(dep_id), visiting)
            if dep_finish > start_at:
                start_at = dep_finish
        est_days = task.get('estimated_days')
        try:
            est_days = max(1, int(est_days)) if est_days is not None else None
        except Exception:
            est_days = None
        finish_at = start_at + timedelta(days=est_days or 1)
        task['start_date'] = start_at.date().isoformat()
        task['due_date'] = finish_at.date().isoformat()
        finish_cache[task_id] = finish_at
        visiting.discard(task_id)
        return finish_at

    for t in created:
        _task_finish(str(t.get('id') or ''))

    return {
        'name': str(wbs_payload.get('name') or 'AI Generated WBS').strip() or 'AI Generated WBS',
        'description': str(wbs_payload.get('description') or '').strip(),
        'summary': str(wbs_payload.get('summary') or '').strip(),
        'planning_mode': str(wbs_payload.get('planning_mode') or '').strip() or None,
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
    function_name = str(raw_task.get('function') or raw_task.get('owner_function') or '').strip() or None
    activity_type = str(raw_task.get('activity_type') or '').strip().lower() or None
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
    if function_name:
        task['function'] = function_name
    if activity_type:
        task['activity_type'] = activity_type
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

SCENARIO_OUTPUT_FIELDS = {
    'roi_opportunity', 'projected_ebitda', 'ebitda_at_risk',
    'potential_loss', 'npv_3_year', 'irr', 'payback_period',
    'break_even_month', 'enterprise_value', 'jaspen_score',
    'time_to_market_impact', 'cost_of_inaction',
    'score_category',
}

_STANDARD_SCENARIO_LEVERS = {
    'initial_investment': {
        'label': 'Initial Investment',
        'type': 'currency',
        'description': 'Estimated upfront capital required to launch or implement this initiative.',
    },
    'implementation_timeline': {
        'label': 'Implementation Timeline (Months)',
        'type': 'months',
        'description': 'Estimated months to complete implementation and reach full operation.',
    },
    'team_size': {
        'label': 'Team Size',
        'type': 'number',
        'description': 'Number of dedicated people needed to execute this initiative.',
    },
    'target_adoption_rate': {
        'label': 'Target Adoption Rate',
        'type': 'percentage',
        'description': 'Expected share of target users or customers who will adopt this.',
    },
    'expected_annual_return': {
        'label': 'Expected Annual Return',
        'type': 'currency',
        'description': 'Estimated recurring financial return generated annually by this initiative.',
    },
    'annual_operational_cost': {
        'label': 'Annual Operational Cost',
        'type': 'currency',
        'description': 'Ongoing annual cost to operate and maintain this initiative.',
    },
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
            if key in inputs or key in _OUTPUT_FIELDS or key in SCENARIO_OUTPUT_FIELDS or key.startswith('_'):
                continue
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                inputs[key] = val
    return inputs


def _extract_assumption_levers(baseline):
    """Parse assumptions text for numeric candidate levers."""
    assumptions = baseline.get('assumptions') if isinstance(baseline, dict) else None
    if not isinstance(assumptions, list):
        return []

    levers = []
    seen_keys = set()

    currency_re = re.compile(r'\$\s*([\d,]+(?:\.\d+)?)\s*([KkMmBb]?)', re.I)
    pct_re = re.compile(r'([\d,]+(?:\.\d+)?)\s*(?:%|percent)', re.I)
    dur_re = re.compile(r'([\d,]+(?:\.\d+)?)\s*(?:months?|weeks?)', re.I)
    count_re = re.compile(r'([\d,]+(?:\.\d+)?)\s*(?:FTEs?|engineers?|developers?|people|members?|users?|customers?|licenses?|seats?|units?)', re.I)

    for entry in assumptions:
        if not isinstance(entry, str):
            continue
        text = entry.strip()
        value = None
        lever_type = 'number'

        matched = currency_re.search(text)
        if matched:
            value = float(matched.group(1).replace(',', ''))
            suffix = matched.group(2).upper()
            if suffix == 'K':
                value *= 1e3
            elif suffix == 'M':
                value *= 1e6
            elif suffix == 'B':
                value *= 1e9
            lever_type = 'currency'

        if value is None:
            matched = pct_re.search(text)
            if matched:
                value = float(matched.group(1).replace(',', ''))
                lever_type = 'percentage'

        if value is None:
            matched = dur_re.search(text)
            if matched:
                value = float(matched.group(1).replace(',', ''))
                lever_type = 'months'

        if value is None:
            matched = count_re.search(text)
            if matched:
                value = float(matched.group(1).replace(',', ''))
                lever_type = 'number'

        if value is None or not (0 < value < 1e12):
            continue

        key = 'assump_' + re.sub(r'[^a-z0-9]+', '_', text.lower())[:35].strip('_')
        if key in seen_keys:
            continue
        seen_keys.add(key)

        label = (text[:55] + '...') if len(text) > 55 else text.rstrip('.,;:')
        bounds = _lever_bounds(value, lever_type)
        levers.append({
            'id': key,
            'key': key,
            'label': label,
            'type': lever_type,
            'value': round(float(value), 6),
            'current': round(float(value), 6),
            'min': bounds['min'],
            'max': bounds['max'],
            'step': bounds['step'],
            'description': text,
            'source': 'observed',
            'readonly': False,
            'display_multiplier': 1,
        })

    return levers[:8]


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
    normalized_changes = {}

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
        normalized_changes[key.lower()] = pct_change

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

    adoption_shift = next((v for k, v in normalized_changes.items() if 'adoption' in k), 0.0)
    training_shift = next((v for k, v in normalized_changes.items() if 'training' in k), 0.0)
    timeline_shift = next((v for k, v in normalized_changes.items() if any(p in k for p in ('timeline', 'month', 'duration', 'period'))), 0.0)
    budget_shift = next((v for k, v in normalized_changes.items() if any(p in k for p in ('budget', 'invest'))), 0.0)

    if adoption_shift:
        financial_factor += adoption_shift * 0.18
        components['market_position'] = max(0.0, min(100.0, components['market_position'] + adoption_shift * 10.0))
    if training_shift:
        financial_factor += training_shift * 0.08
        components['execution_readiness'] = max(0.0, min(100.0, components['execution_readiness'] + training_shift * 8.0))
    if timeline_shift < 0:
        financial_factor += timeline_shift * 0.12
        components['execution_readiness'] = max(0.0, min(100.0, components['execution_readiness'] + timeline_shift * 10.0))
        components['operational_efficiency'] = max(0.0, min(100.0, components['operational_efficiency'] + timeline_shift * 6.0))
    elif timeline_shift > 0:
        financial_factor += timeline_shift * 0.05
    if budget_shift > 0 and abs(timeline_shift) < 0.05:
        financial_factor -= budget_shift * 0.08

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
        'executive_summary',
        'executive_narrative',
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

        baseline_inputs, lever_catalog = _build_scenario_lever_catalog(baseline, baseline_inputs)
        thread_data['baseline_inputs'] = baseline_inputs
        thread_data['lever_catalog'] = lever_catalog
        all_data[thread_id] = thread_data
        _save_scenarios(user_id, all_data)

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
                model_selection=model_selection,
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
            'lever_catalog': lever_catalog,
            'output_metrics': sorted(SCENARIO_OUTPUT_FIELDS),
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
        preflight_answers = payload.get('preflight_answers') if isinstance(payload.get('preflight_answers'), dict) else {}
        scenario_id = str(payload.get('scenario_id') or '').strip() or None
        scorecard_id = str(payload.get('scorecard_id') or '').strip() or None

        all_data, thread_data, baseline, _baseline_inputs, session, _strategy_objective = _resolve_thread_baseline(user_id, thread_id)
        scenarios = thread_data.get('scenarios') if isinstance(thread_data.get('scenarios'), dict) else {}
        adopted_id = thread_data.get('adopted_scenario_id')
        adopted_scenario = None

        current_scorecard = None

        # First-class resolution: explicit scorecard_id from CTA click.
        if scorecard_id:
            kind, _container, _key, carrier = _find_scorecard_carrier(user_id, thread_id, scorecard_id)
            if kind and isinstance(carrier, dict):
                result_blob = carrier.get('result') if isinstance(carrier.get('result'), dict) else None
                if isinstance(result_blob, dict):
                    current_scorecard = result_blob

        # Fallbacks: baseline / scenario / adopted scenario / session result.
        if not isinstance(current_scorecard, dict):
            current_scorecard = baseline if isinstance(baseline, dict) else None

        if (
            not isinstance(current_scorecard, dict)
            and scenario_id
            and scenario_id in scenarios
            and isinstance((scenarios.get(scenario_id) or {}).get('result'), dict)
        ):
            adopted_scenario = scenarios.get(scenario_id)
            current_scorecard = adopted_scenario.get('result')
        elif (
            not isinstance(current_scorecard, dict)
            and adopted_id
            and adopted_id in scenarios
            and isinstance((scenarios.get(adopted_id) or {}).get('result'), dict)
        ):
            adopted_scenario = scenarios.get(adopted_id)
            current_scorecard = adopted_scenario.get('result')
        if current_scorecard is None and isinstance(session, dict) and isinstance(session.get('result'), dict):
            current_scorecard = session.get('result')
        # Fallback: thread_id might be a scorecard analysis_id rather than a session_id.
        # Scan all sessions to find one whose result.analysis_id matches.
        if not isinstance(current_scorecard, dict):
            all_sessions = load_user_sessions(user_id) or {}
            for _key, _candidate in all_sessions.items():
                if not isinstance(_candidate, dict):
                    continue
                _result = _candidate.get('result')
                if not isinstance(_result, dict):
                    continue
                _aid = str(_result.get('analysis_id') or _result.get('id') or '').strip()
                if _aid and _aid == str(thread_id):
                    current_scorecard = _result
                    _canonical_td = all_data.get(_key)
                    if isinstance(_canonical_td, dict):
                        thread_data = _canonical_td
                        scenarios = thread_data.get('scenarios') if isinstance(thread_data.get('scenarios'), dict) else {}
                        adopted_id = thread_data.get('adopted_scenario_id')
                    break
        if not isinstance(current_scorecard, dict):
            return jsonify({'error': 'No scorecard context found for this thread.'}), 404

        # If a committed plan already exists for THIS idea, don't silently
        # overwrite it. Unless the caller explicitly forces a regenerate
        # (force=true), signal the frontend so it can offer "open the existing
        # plan" vs. "generate a new one". Done before the LLM call to save cost.
        force_new = bool(payload.get('force') or payload.get('regenerate'))
        if commit and not force_new:
            existing_idea_id, _existing_idea_name = _wbs_idea_identity(current_scorecard, fallback_id=scorecard_id)
            existing_plan = _existing_committed_plan(thread_data, existing_idea_id)
            if existing_plan:
                return jsonify({
                    'plan_exists': True,
                    'thread_id': thread_id,
                    'scorecard_id': existing_idea_id or None,
                    'scorecard_name': (
                        existing_plan.get('scorecard_name')
                        or existing_plan.get('idea_name')
                        or _existing_idea_name
                        or ''
                    ),
                    'plan_name': existing_plan.get('name') or '',
                    'task_count': len(existing_plan.get('tasks') or []),
                }), 200

        if not preflight_answers:
            has_exec_summary = bool(str(current_scorecard.get('executive_summary') or '').strip())
            score_value = int(current_scorecard.get('jaspen_score') or 0)
            if not has_exec_summary and score_value == 0:
                return jsonify({
                    'needs_preflight': True,
                    'questions': [
                        {'id': 'team', 'label': 'Who are the primary team members or owners of this project? (e.g., names, roles, or departments)'},
                        {'id': 'timeline', 'label': 'What is your target completion timeline or hard deadline?'},
                        {'id': 'functions', 'label': 'Which business functions or systems are most directly affected?'},
                        {'id': 'constraints', 'label': 'Are there any budget caps, compliance requirements, or technical constraints we should account for?'},
                    ],
                }), 200

        if preflight_answers:
            preflight_context = '\n'.join([
                f"- {key}: {value}"
                for key, value in preflight_answers.items()
                if str(value or '').strip()
            ])
            if preflight_context:
                instruction = (
                    f"Project Planning Context (from pre-flight):\n{preflight_context}\n\n"
                    f"{instruction or ''}"
                ).strip()

        # Pull conversation history from the session so the AI can build a specific plan
        raw_chat = None
        if isinstance(session, dict):
            raw_chat = session.get('chat_history')
            if not isinstance(raw_chat, list):
                result_blob = session.get('result')
                raw_chat = result_blob.get('chat_history') if isinstance(result_blob, dict) else None
        if not isinstance(raw_chat, list):
            raw_chat = []
        # Keep the last 20 turns and trim to text-only for the prompt
        chat_turns = []
        for msg in raw_chat[-20:]:
            role = str(msg.get('role') or msg.get('sender') or '').strip().lower()
            text = str(msg.get('content') or msg.get('text') or msg.get('message') or '').strip()
            if text and role in ('user', 'assistant', 'jaspen'):
                label = 'User' if role == 'user' else 'Jaspen'
                chat_turns.append(f"{label}: {text[:400]}")

        # Ensure initiative name is available for WBS task naming
        session_name = str(session.get('name') or '').strip() if isinstance(session, dict) else ''
        wbs_scorecard = dict(current_scorecard) if isinstance(current_scorecard, dict) else {}
        if not wbs_scorecard.get('project_name') and session_name:
            wbs_scorecard['project_name'] = session_name

        client = get_llm_client()
        raw_wbs = _generate_ai_wbs_suggestion(
            client,
            model_selection['llm_model'],
            scorecard=wbs_scorecard,
            instruction=instruction,
            scenario_payload=adopted_scenario,
            model_selection=model_selection,
            strategy_objective=_strategy_objective,
            chat_history=chat_turns,
        )
        materialized = _materialize_ai_wbs(raw_wbs)
        normalized_wbs = _normalize_project_wbs({'project_wbs': materialized}, existing=None)
        normalized_wbs['ai_generated'] = True
        normalized_wbs['ai_generated_at'] = datetime.utcnow().isoformat()
        normalized_wbs['ai_summary'] = str(raw_wbs.get('summary') or '').strip()
        if scenario_id:
            normalized_wbs['source_scenario_id'] = scenario_id
        # Stamp the originating idea's id + name so this plan knows which idea it
        # belongs to (header naming + Session Artifacts registration). Built from
        # the resolved scorecard, falling back to the explicit CTA scorecard_id.
        _stamp_wbs_identity(normalized_wbs, current_scorecard, fallback_id=scorecard_id)
        canonical_scorecard_id = str(normalized_wbs.get('scorecard_id') or scorecard_id or '').strip() or None

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
            # Key the plan under the canonical idea id so it's always registered
            # to the originating idea (never just the thread-level mirror).
            _store_thread_wbs(thread_data, canonical_scorecard_id, normalized_wbs)
            all_data[thread_id] = thread_data
            _save_scenarios(user_id, all_data)
            # Register the plan as a Session Artifact on the originating idea so
            # it shows up in the artifacts list even though it was built from the
            # workspace CTA / trade-off table rather than the chat tool.
            _register_execution_plan_artifact(user_id, thread_id, normalized_wbs)
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

        # Pre-compute the scenario result so it's never saved with result=null.
        # This prevents data loss if the user navigates away before applyScenario
        # is called, and ensures savedScenarios always have results on restore.
        computed_result = None
        if deltas:
            all_data = _load_scenarios(user_id)
            td = all_data.get(thread_id, {})
            stored_baseline = td.get('baseline') or baseline
            stored_inputs = td.get('baseline_inputs') or (
                _extract_baseline_inputs(stored_baseline) if isinstance(stored_baseline, dict) else {}
            )
            if isinstance(stored_baseline, dict) and stored_inputs:
                computed_result = _compute_scenario_scorecard(stored_baseline, deltas, stored_inputs)

        try:
            created = _create_scenario_record(
                user_id,
                thread_id,
                deltas=deltas,
                label=label,
                baseline=baseline,
                plan_key=plan_key,
                result=computed_result,
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
            'result': computed_result,
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
            # Re-compute result immediately so it's never null on disk.
            baseline = td.get('baseline')
            baseline_inputs = td.get('baseline_inputs') or {}
            if isinstance(baseline, dict) and baseline_inputs:
                result = _compute_scenario_scorecard(baseline, data['deltas'], baseline_inputs)
                result['analysis_id'] = scenario_id
                result['scenario_id'] = scenario_id
                result['thread_id'] = thread_id
                result['label'] = scenario.get('label', 'Scenario')
                scenario['result'] = result
            else:
                scenario['result'] = None  # no baseline to compute against

        scenario['updated_at'] = datetime.utcnow().isoformat()
        _save_scenarios(user_id, all_data)
        if 'label' in data:
            try:
                _rename_snapshot_in_session(user_id, thread_id, scenario_id, scenario['label'])
            except Exception as rename_error:
                current_app.logger.warning("[update_scenario] snapshot label sync failed: %s", rename_error)
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
        snapshot_meta = None
        try:
            snapshot_meta = _delete_snapshot_from_session(user_id, thread_id, scenario_id)
        except ValueError as delete_error:
            return jsonify({'error': str(delete_error)}), 400
        except Exception as delete_error:
            current_app.logger.warning("[delete_scenario] snapshot delete sync failed: %s", delete_error)
        return jsonify({
            'success': True,
            'deleted_scenario_id': scenario_id,
            'selected_scorecard_id': (snapshot_meta or {}).get('selected_scorecard_id'),
            'scorecard_snapshots': (snapshot_meta or {}).get('scorecard_snapshots'),
        }), 200

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

        data = request.get_json() or {}
        thread_id = data.get('thread_id') or request.args.get('thread_id')

        all_data = _load_scenarios(user_id)
        resolved_thread_id = None
        td = None
        scenario = None
        if thread_id:
            candidate = all_data.get(thread_id, {})
            if scenario_id not in candidate.get('scenarios', {}):
                return jsonify({'error': 'Scenario not found'}), 404
            resolved_thread_id = thread_id
            td = candidate
            scenario = candidate.get('scenarios', {}).get(scenario_id)
        else:
            for tid, candidate in all_data.items():
                if scenario_id in candidate.get('scenarios', {}):
                    resolved_thread_id = tid
                    td = candidate
                    scenario = candidate.get('scenarios', {}).get(scenario_id)
                    break
            if not resolved_thread_id or not isinstance(scenario, dict):
                return jsonify({'error': 'Scenario not found in any thread'}), 404

        baseline = td.get('baseline') if isinstance(td.get('baseline'), dict) else None
        if not baseline:
            return jsonify({'error': 'No baseline stored for this thread.'}), 400
        baseline_inputs = td.get('baseline_inputs') if isinstance(td.get('baseline_inputs'), dict) else {}
        result = scenario.get('result') if isinstance(scenario.get('result'), dict) else None
        if not result:
            result = _compute_scenario_scorecard(baseline, scenario.get('deltas') or {}, baseline_inputs)
            result['analysis_id'] = scenario_id
            result['scenario_id'] = scenario_id
            result['thread_id'] = resolved_thread_id
            result['label'] = scenario.get('label') or 'Scenario'
            scenario['result'] = result

        td['adopted_scenario_id'] = scenario_id
        scenario['updated_at'] = datetime.utcnow().isoformat()

        _save_scenarios(user_id, all_data)
        snapshot_meta = _persist_scenario_snapshot_to_session(
            user_id,
            resolved_thread_id,
            scenario,
            result,
            select=True,
        )
        _audit_strategy_event(
            'scenario.adopted',
            user_id=user_id,
            details={
                'thread_id': resolved_thread_id,
                'scenario_id': scenario_id,
            },
        )
        return jsonify({
            'success': True,
            'adopted_scenario_id': scenario_id,
            'selected_scorecard_id': (snapshot_meta or {}).get('selected_scorecard_id'),
            'snapshot': (snapshot_meta or {}).get('snapshot'),
            'scorecard_snapshots': (snapshot_meta or {}).get('scorecard_snapshots'),
        }), 200

    except Exception as e:
        current_app.logger.error("[adopt_scenario] %s", e)
        return jsonify({'error': str(e)}), 500


# ============================================================
# WBS ROUTES
# ============================================================

# ------------------------------------------------------------------
# Per-idea execution plans
# ------------------------------------------------------------------
# Each idea (scorecard) gets its OWN execution plan so plans stand on their
# own — building or editing one idea's plan never touches another's. Plans are
# stored under td['wbs_by_scorecard'][scorecard_id]; td['project_wbs'] is kept
# as a mirror of the last-touched plan for back-compat with readers that don't
# pass an id and for threads created before per-idea plans existed.

def _resolve_thread_wbs(td, scorecard_id=None):
    """Return the plan for a specific idea when one exists. Falls back to the
    legacy thread-level project_wbs only for threads that have no per-idea
    store yet — never leaks one idea's plan to another once plans are split."""
    if not isinstance(td, dict):
        return None
    by_card = td.get('wbs_by_scorecard') if isinstance(td.get('wbs_by_scorecard'), dict) else {}
    key = str(scorecard_id or '').strip()
    if key:
        if key in by_card:
            return by_card.get(key)
        if by_card:
            # Per-idea store exists but this idea has no plan yet → genuinely
            # empty. Do NOT fall through to another idea's project_wbs.
            return None
    return td.get('project_wbs')


def _existing_committed_plan(td, scorecard_id):
    """Return the already-committed plan for this idea if one exists with at
    least one task, else None. Used to gate 'create a plan' triggers so we
    don't silently overwrite an existing plan — the caller offers the user a
    choice (open the existing plan vs. generate a new one) instead."""
    plan = _resolve_thread_wbs(td, scorecard_id)
    if isinstance(plan, dict) and isinstance(plan.get('tasks'), list) and len(plan['tasks']) > 0:
        return plan
    return None


def _store_thread_wbs(td, scorecard_id, normalized_wbs):
    """Persist a plan as the given idea's plan and mirror it to project_wbs as
    the thread's 'active' plan."""
    if not isinstance(td, dict):
        return
    key = str(scorecard_id or '').strip()
    if key:
        by_card = td.get('wbs_by_scorecard')
        if not isinstance(by_card, dict):
            by_card = {}
        by_card[key] = normalized_wbs
        td['wbs_by_scorecard'] = by_card
        # Whatever plan was just written becomes the active one for chat edits.
        td['active_execution_scorecard_id'] = key
    td['project_wbs'] = normalized_wbs


_GENERIC_WBS_NAMES = {
    '', 'execution wbs', 'execution plan', 'ai generated project plan',
    'ai generated program plan',
}
_GENERIC_IDEA_NAMES = {
    '', 'untitled idea', 'jaspen analysis', 'jaspen intake', 'execution wbs',
    'ai generated project plan',
}


def _wbs_idea_identity(scorecard, fallback_id=None):
    """Return (canonical_id, display_name) for the idea a plan belongs to,
    pulled from the resolved scorecard. Mirrors the frontend's name-picking
    so the plan carries the same identity the scorecard shows."""
    sc = scorecard if isinstance(scorecard, dict) else {}
    idea_id = str(sc.get('id') or sc.get('analysis_id') or fallback_id or '').strip()
    overrides = sc.get('display_overrides') if isinstance(sc.get('display_overrides'), dict) else {}
    name = ''
    for cand in (
        overrides.get('title'), sc.get('name'), sc.get('project_name'),
        sc.get('label'), sc.get('initiative_name'),
    ):
        value = str(cand or '').strip()
        if value and value.lower() not in _GENERIC_IDEA_NAMES:
            name = value
            break
    return idea_id, name


def _plan_content_text(plan):
    """Flatten a plan's generated CONTENT (task names/descriptions + AI summary)
    into lowercase searchable text. Deliberately excludes the plan's own `name`
    field, which may have been mis-stamped — we only trust the generated body,
    which the WBS generator seeds with the originating idea's name."""
    if not isinstance(plan, dict):
        return ''
    parts = []
    for task in (plan.get('tasks') or []):
        if isinstance(task, dict):
            parts.append(str(task.get('name') or task.get('title') or ''))
            parts.append(str(task.get('description') or ''))
    parts.append(str(plan.get('ai_summary') or ''))
    return ' \n '.join(parts).lower()


def _infer_plan_origin(plan, candidates):
    """Best-effort recovery of which idea a legacy/unstamped plan was built from
    by matching candidate idea names against the plan's generated content. The
    WBS generator writes the idea name into task titles (e.g. "Kickoff ... for
    <Idea Name>"), so a verbatim name hit is a reliable origin signal. Returns
    (idea_id, idea_name) for the longest matching name, or (None, '') when no
    candidate name is found — we'd rather stay generic than guess wrong."""
    text = _plan_content_text(plan)
    if not text.strip():
        return None, ''
    best_id, best_name, best_len = None, '', 0
    for sc in (candidates or []):
        cid, name = _wbs_idea_identity(sc)
        candidate_name = str(name or '').strip()
        if len(candidate_name) >= 4 and candidate_name.lower() in text and len(candidate_name) > best_len:
            best_id, best_name, best_len = cid, candidate_name, len(candidate_name)
    return best_id, best_name


def _stamp_wbs_identity(normalized_wbs, scorecard, fallback_id=None):
    """Stamp the originating idea's id + name onto a plan so every plan — no
    matter where it was built — knows which idea it belongs to and can show
    that idea's name in its header and in the Session Artifacts list."""
    if not isinstance(normalized_wbs, dict):
        return normalized_wbs
    idea_id, idea_name = _wbs_idea_identity(scorecard, fallback_id)
    if idea_id:
        normalized_wbs['scorecard_id'] = idea_id
    if idea_name:
        normalized_wbs['scorecard_name'] = idea_name
        normalized_wbs['idea_name'] = idea_name
        current_name = str(normalized_wbs.get('name') or '').strip()
        if current_name.lower() in _GENERIC_WBS_NAMES:
            normalized_wbs['name'] = f'{idea_name} — Execution Plan'
    return normalized_wbs


def _register_execution_plan_artifact(user_id, thread_id, normalized_wbs):
    """Append (or replace) an execution_plan artifact in the originating
    session's chat_history so the plan appears in that idea's Session Artifacts
    list regardless of where it was built (chat tool, workspace CTA, or the
    trade-off table). Replaces any prior plan artifact for the SAME idea so we
    don't stack duplicates when a plan is regenerated."""
    try:
        sessions = load_user_sessions(user_id) or {}
        session_key, session = _resolve_session_entry(sessions, thread_id)
        if not isinstance(session, dict):
            return False
        raw = session.get('chat_history')
        if not isinstance(raw, list):
            result_blob = session.get('result')
            raw = (
                result_blob.get('chat_history')
                if isinstance(result_blob, dict) and isinstance(result_blob.get('chat_history'), list)
                else []
            )
        sid = str(normalized_wbs.get('scorecard_id') or '').strip()
        idea_name = str(normalized_wbs.get('scorecard_name') or normalized_wbs.get('idea_name') or '').strip()
        task_count = len(normalized_wbs.get('tasks') or [])
        now_iso = datetime.utcnow().isoformat()

        def _plan_signature(plan):
            """A content fingerprint so plans built across id churn (the same
            task list re-stamped with a different scorecard_id) are recognized as
            the SAME plan and don't stack as duplicate artifacts."""
            try:
                names = [
                    str((t or {}).get('title') or (t or {}).get('name') or '').strip().lower()
                    for t in (plan.get('tasks') or [])
                    if isinstance(t, dict)
                ]
                names = [n for n in names if n]
                return tuple(names[:12])
            except Exception:
                return tuple()

        new_sig = _plan_signature(normalized_wbs)

        kept = []
        for msg in raw:
            if isinstance(msg, dict):
                art = msg.get('artifact') if isinstance(msg.get('artifact'), dict) else None
                if art and str(art.get('type') or '') == 'execution_plan':
                    art_data = art.get('data') or {}
                    art_sid = str(art_data.get('scorecard_id') or '').strip()
                    if sid and art_sid == sid:
                        continue  # drop the stale plan for this same idea
                    # Same content under a different (churned) id is still a dup.
                    if new_sig and _plan_signature(art_data) == new_sig:
                        continue
            kept.append(msg)

        label = idea_name or 'this idea'
        plural = '' if task_count == 1 else 's'
        kept.append({
            'role': 'assistant',
            'content': (
                f'Execution plan ready for "{label}" — {task_count} task{plural}. '
                'Open the Execution view to review the list, board, and timeline.'
            ),
            'text': f'Execution plan ready for "{label}" — {task_count} task{plural}.',
            'artifact': {'type': 'execution_plan', 'data': normalized_wbs},
            'timestamp': now_iso,
        })
        session['chat_history'] = kept
        if isinstance(session.get('result'), dict):
            session['result']['chat_history'] = kept
        session['timestamp'] = now_iso
        sessions[session_key or thread_id] = session
        return save_user_sessions(user_id, sessions)
    except Exception:
        current_app.logger.exception("[_register_execution_plan_artifact] failed")
        return False


@strategy_bp.route('/threads/<thread_id>/wbs', methods=['GET'])
@jwt_required()
def get_thread_wbs(thread_id):
    try:
        user_id = get_jwt_identity()
        _, plan_key, access_err = _require_tool_access(user_id, 'wbs_read', access='read')
        if access_err:
            return access_err

        scorecard_id = str(request.args.get('scorecard_id') or '').strip() or None
        all_data = _load_scenarios(user_id)
        td = all_data.get(thread_id, {}) if isinstance(all_data, dict) else {}
        project_wbs = _resolve_thread_wbs(td, scorecard_id)

        # Remember which idea's plan is currently open so the chat agent's WBS
        # mutation tools (which don't receive view context) edit THIS plan.
        if scorecard_id and isinstance(td, dict) and td.get('active_execution_scorecard_id') != scorecard_id:
            td['active_execution_scorecard_id'] = scorecard_id
            all_data[thread_id] = td
            try:
                _save_scenarios(user_id, all_data)
            except Exception:
                pass

        # Backfill / correct identity on legacy or mis-stamped plans so the
        # header + Session Artifacts name the idea the plan was ACTUALLY built
        # from. We never guess from "active_execution_scorecard_id" (that points
        # at the last-touched plan, which may be a different idea) — instead we
        # match candidate idea names against the plan's generated content, which
        # the WBS generator seeds with the originating idea's name.
        if isinstance(project_wbs, dict) and (project_wbs.get('tasks') or []):
            # Enumerate this thread's ideas (baseline + snapshots + scenarios).
            candidates = []
            try:
                from .ai_agent import _collect_session_scorecards
                sessions = load_user_sessions(user_id) or {}
                _skey, _session = _resolve_session_entry(sessions, thread_id)
                candidates.extend(_collect_session_scorecards(_session))
            except Exception:
                candidates = []
            try:
                for _scen in (td.get('scenarios') or {}).values():
                    if isinstance(_scen, dict) and isinstance(_scen.get('result'), dict):
                        candidates.append(_scen['result'])
            except Exception:
                pass

            inferred_id, inferred_name = _infer_plan_origin(project_wbs, candidates)
            current_sc_name = str(project_wbs.get('scorecard_name') or '').strip()
            current_name = str(project_wbs.get('name') or '').strip()
            # Apply when we positively recovered an origin AND it differs from
            # what's currently stamped (covers both unstamped legacy plans and
            # plans previously stamped with the wrong idea).
            if inferred_name and inferred_name.lower() != current_sc_name.lower():
                project_wbs['scorecard_name'] = inferred_name
                project_wbs['idea_name'] = inferred_name
                if inferred_id:
                    project_wbs['scorecard_id'] = inferred_id
                # Reset the display name when it's generic or an auto-generated
                # "<idea> — Execution Plan" label (possibly from a bad stamp).
                if (
                    current_name.lower() in _GENERIC_WBS_NAMES
                    or current_name.endswith('— Execution Plan')
                    or current_name.endswith('- Execution Plan')
                ):
                    project_wbs['name'] = f'{inferred_name} — Execution Plan'
                try:
                    key = str(inferred_id or project_wbs.get('scorecard_id') or '').strip() or None
                    # Drop any stale per-idea entries that point at THIS plan
                    # object under a different (wrong) key before re-keying.
                    by_card = td.get('wbs_by_scorecard') if isinstance(td.get('wbs_by_scorecard'), dict) else {}
                    for _k in [k for k, v in by_card.items() if v is project_wbs and k != key]:
                        by_card.pop(_k, None)
                    td['wbs_by_scorecard'] = by_card
                    _store_thread_wbs(td, key, project_wbs)
                    all_data[thread_id] = td
                    _save_scenarios(user_id, all_data)
                    _register_execution_plan_artifact(user_id, thread_id, project_wbs)
                except Exception:
                    current_app.logger.exception("[get_thread_wbs] identity backfill persist failed")

        # Orphan-cleanup: prune execution_plan artifacts whose idea id no longer
        # has a stored plan in wbs_by_scorecard. Earlier identity-backfill churn
        # (re-keying a plan from id A→B→C) left behind artifacts pointing at
        # abandoned ids — they show up as phantom duplicates in Session Artifacts.
        try:
            by_card = td.get('wbs_by_scorecard') if isinstance(td.get('wbs_by_scorecard'), dict) else {}
            if by_card:
                valid_ids = {str(k).strip() for k in by_card.keys() if str(k).strip()}
                sessions2 = load_user_sessions(user_id) or {}
                skey2, session2 = _resolve_session_entry(sessions2, thread_id)
                hist = session2.get('chat_history') if isinstance(session2, dict) else None
                if isinstance(hist, list):
                    cleaned = []
                    removed = False
                    for msg in hist:
                        drop = False
                        if isinstance(msg, dict):
                            art = msg.get('artifact') if isinstance(msg.get('artifact'), dict) else None
                            if art and str(art.get('type') or '') == 'execution_plan':
                                art_sid = str((art.get('data') or {}).get('scorecard_id') or '').strip()
                                if art_sid and art_sid not in valid_ids:
                                    drop = True
                                    removed = True
                        if not drop:
                            cleaned.append(msg)
                    if removed:
                        session2['chat_history'] = cleaned
                        if isinstance(session2.get('result'), dict):
                            session2['result']['chat_history'] = cleaned
                        sessions2[skey2 or thread_id] = session2
                        save_user_sessions(user_id, sessions2)
        except Exception:
            current_app.logger.exception("[get_thread_wbs] orphan artifact cleanup failed")

        # When the caller didn't scope by ?scorecard_id (legacy __execution__
        # route), surface the idea this stored plan belongs to so the workspace
        # header can still name it instead of falling back to a bare label.
        resolved_scorecard_id = scorecard_id or (
            str(project_wbs.get('scorecard_id')).strip()
            if isinstance(project_wbs, dict) and project_wbs.get('scorecard_id')
            else None
        )
        return jsonify({
            'thread_id': thread_id,
            'scorecard_id': resolved_scorecard_id,
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
        scorecard_id = str(payload.get('scorecard_id') or request.args.get('scorecard_id') or '').strip() or None

        all_data = _load_scenarios(user_id)
        if thread_id not in all_data:
            all_data[thread_id] = _thread_entry()
        td = all_data[thread_id]

        resolved_existing = _resolve_thread_wbs(td, scorecard_id)
        existing_wbs = resolved_existing if isinstance(resolved_existing, dict) else None
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
        _store_thread_wbs(td, scorecard_id, normalized_wbs)
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
# WORKSPACE CHAT  (per-artifact sidebar conversation persistence)
# ============================================================
# The Workspace sidebar chat is scoped to a single artifact (a scorecard, or
# the trade-off / execution sentinels). We persist each artifact's conversation
# server-side under the thread record so it survives a hard refresh and is
# available on any device — not just the browser that created it.

def _sanitize_workspace_chat(raw, max_messages=200):
    """Coerce an incoming chat array into a compact, storable shape.

    Each entry is {role: 'user'|'ai', text: str} plus an optional small
    `execPlan` summary card. We cap history length and field sizes so a long
    conversation can't bloat the thread record."""
    if not isinstance(raw, list):
        return []
    out = []
    for m in raw[-max_messages:]:
        if not isinstance(m, dict):
            continue
        role = 'user' if m.get('role') == 'user' else 'ai'
        text = str(m.get('text') or '')[:20000]
        entry = {'role': role, 'text': text}
        ep = m.get('execPlan')
        if isinstance(ep, dict):
            tasks = ep.get('tasks') if isinstance(ep.get('tasks'), list) else []
            try:
                total = int(ep.get('total') or 0)
            except (TypeError, ValueError):
                total = 0
            entry['execPlan'] = {
                'label': str(ep.get('label') or '')[:200],
                'total': total,
                'tasks': [
                    {'title': str((t or {}).get('title') or (t or {}).get('name') or '')[:300]}
                    for t in tasks[:6] if isinstance(t, dict)
                ],
            }
        out.append(entry)
    return out


_EXECUTION_SENTINEL = '__execution__'


def _canonical_workspace_artifact_id(td, artifact_id):
    """Collapse the bare execution sentinel and its idea-scoped variants onto a
    single canonical key so the same execution plan shares ONE chat regardless of
    which route (``__execution__`` vs ``__execution__::<id>``) the user arrived by.

    Returns a tuple ``(canonical_id, legacy_ids)`` where ``legacy_ids`` are the
    other keys whose chat history should be migrated/merged onto the canonical
    key (the bare sentinel chiefly)."""
    raw = str(artifact_id or '')
    if not raw.startswith(_EXECUTION_SENTINEL):
        return raw, []

    # Pull an explicit idea id off the route variant if present.
    explicit_id = ''
    for sep in ('::', '?idea=', '&idea='):
        if sep in raw:
            explicit_id = raw.split(sep, 1)[1]
            break
    explicit_id = (explicit_id or '').split('&')[0].split('?')[0].strip()

    canonical_idea = explicit_id
    if not canonical_idea and isinstance(td, dict):
        canonical_idea = str(td.get('active_execution_scorecard_id') or '').strip()
    if not canonical_idea and isinstance(td, dict):
        pw = td.get('project_wbs')
        if isinstance(pw, dict):
            canonical_idea = str(pw.get('scorecard_id') or '').strip()

    if canonical_idea:
        canonical_id = '{}::{}'.format(_EXECUTION_SENTINEL, canonical_idea)
    else:
        canonical_id = _EXECUTION_SENTINEL

    # Every other execution-flavored key we might want to fold in.
    legacy_ids = [_EXECUTION_SENTINEL]
    if canonical_idea:
        legacy_ids.append('{}::{}'.format(_EXECUTION_SENTINEL, canonical_idea))
    if raw not in legacy_ids:
        legacy_ids.append(raw)
    legacy_ids = [k for k in legacy_ids if k != canonical_id]
    return canonical_id, legacy_ids


@strategy_bp.route('/threads/<thread_id>/workspace-chat/<artifact_id>', methods=['GET'])
@jwt_required()
def get_workspace_chat(thread_id, artifact_id):
    try:
        user_id = get_jwt_identity()
        all_data = _load_scenarios(user_id)
        td = all_data.get(thread_id, {}) if isinstance(all_data, dict) else {}
        chats = td.get('workspace_chats') if isinstance(td, dict) else None
        messages = []
        if isinstance(chats, dict):
            canonical_id, legacy_ids = _canonical_workspace_artifact_id(td, artifact_id)
            raw = chats.get(canonical_id)
            if isinstance(raw, list) and raw:
                messages = raw
            else:
                # No canonical chat yet — adopt the richest legacy chat (e.g. the
                # bare ``__execution__`` history created before idea-scoping) and
                # migrate it onto the canonical key so future reads/writes align.
                best = None
                for k in legacy_ids:
                    cand = chats.get(k)
                    if isinstance(cand, list) and len(cand) > (len(best) if best else 0):
                        best = cand
                if best:
                    messages = best
                    if canonical_id != _EXECUTION_SENTINEL:
                        try:
                            chats[canonical_id] = best
                            for k in legacy_ids:
                                if k in chats and k != canonical_id:
                                    chats.pop(k, None)
                            td['workspace_chats'] = chats
                            all_data[thread_id] = td
                            _save_scenarios(user_id, all_data)
                        except Exception:
                            pass
        return jsonify({
            'thread_id': thread_id,
            'artifact_id': artifact_id,
            'messages': messages,
        }), 200
    except Exception as e:
        current_app.logger.error("[get_workspace_chat] %s", e)
        return jsonify({'error': str(e)}), 500


@strategy_bp.route('/threads/<thread_id>/workspace-chat/<artifact_id>', methods=['PUT', 'PATCH'])
@jwt_required()
def upsert_workspace_chat(thread_id, artifact_id):
    try:
        user_id = get_jwt_identity()
        payload = request.get_json() or {}
        messages = _sanitize_workspace_chat(payload.get('messages'))

        all_data = _load_scenarios(user_id)
        if thread_id not in all_data:
            all_data[thread_id] = _thread_entry()
        td = all_data[thread_id]

        chats = td.get('workspace_chats')
        if not isinstance(chats, dict):
            chats = {}
        canonical_id, legacy_ids = _canonical_workspace_artifact_id(td, artifact_id)
        chats[canonical_id] = messages
        # Drop any stale legacy keys so we never split the same plan's chat again.
        if canonical_id != _EXECUTION_SENTINEL:
            for k in legacy_ids:
                if k in chats and k != canonical_id:
                    chats.pop(k, None)
        td['workspace_chats'] = chats
        all_data[thread_id] = td
        _save_scenarios(user_id, all_data)

        return jsonify({
            'success': True,
            'thread_id': thread_id,
            'artifact_id': artifact_id,
            'messages': messages,
        }), 200
    except Exception as e:
        current_app.logger.error("[upsert_workspace_chat] %s", e)
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
        lever_catalog = td.get('lever_catalog') if isinstance(td.get('lever_catalog'), list) else []
        if snapshot_state:
            baseline = snapshot_state['baseline']
        elif baseline is None and session_result:
            baseline = session_result
        if not isinstance(scenarios_dict, dict):
            scenarios_dict = {}
        if not isinstance(baseline_inputs, dict):
            baseline_inputs = {}
        if isinstance(baseline, dict):
            baseline_inputs, generated_catalog = _build_scenario_lever_catalog(baseline, baseline_inputs)
            # Regenerate if stored catalog is missing any standard levers (not just when completely empty)
            stored_keys = {row.get('key') for row in lever_catalog if isinstance(row, dict)}
            std_keys = set(_STANDARD_SCENARIO_LEVERS.keys())
            if not lever_catalog or not std_keys.issubset(stored_keys):
                lever_catalog = generated_catalog
            td['baseline_inputs'] = baseline_inputs
            td['lever_catalog'] = lever_catalog
            all_data[thread_id] = td
            _save_scenarios(user_id, all_data)

        # Sorted scenario list
        scenarios_list = sorted(scenarios_dict.values(),
                                key=lambda s: s.get('created_at', ''), reverse=True)[:scn_limit]

        # Current scorecard prefers the explicitly selected snapshot, then adopted scenario, then baseline.
        current_scorecard = baseline
        if snapshot_state and isinstance(snapshot_state.get('selected_snapshot'), dict):
            current_scorecard = snapshot_state['selected_snapshot']
        elif adopted_id and adopted_id in scenarios_dict:
            current_scorecard = scenarios_dict[adopted_id].get('result') or baseline

        scenario_levers = [dict(row) for row in lever_catalog]

        # Merge scenarios saved via create_as_version into the snapshot list so
        # all scorecard versions survive a hard reload. Each scenario record
        # carries its full scored payload in `result`.
        merged_snapshots = list(snapshot_state['snapshots']) if snapshot_state else []
        _existing_snap_ids = {str(s.get('id') or s.get('analysis_id') or '') for s in merged_snapshots}
        for _scn in scenarios_list:
            if not isinstance(_scn, dict):
                continue
            _scn_result = _scn.get('result') if isinstance(_scn.get('result'), dict) else None
            if not _scn_result:
                continue
            _scn_id = str(
                _scn_result.get('id')
                or _scn_result.get('analysis_id')
                or _scn.get('scenario_id')
                or ''
            ).strip()
            if not _scn_id or _scn_id in _existing_snap_ids:
                continue
            _snap = _normalize_scorecard_payload(_scn_result)
            _snap['id'] = _scn_id
            _snap['analysis_id'] = _snap.get('analysis_id') or _scn_id
            _snap['label'] = _snap.get('label') or _scn.get('label') or 'Version'
            _snap['isBaseline'] = False
            _snap['createdAt'] = _snap.get('createdAt') or _scn.get('created_at') or _scn_result.get('timestamp')
            # Pass through any Workspace (Beta) cosmetic overrides so the canvas
            # editor and chat-inline renderer see the same edited view.
            if isinstance(_scn_result.get('display_overrides'), dict):
                _snap['display_overrides'] = _scn_result['display_overrides']
            merged_snapshots.append(_snap)
            _existing_snap_ids.add(_scn_id)

        # Also merge scorecard artifacts saved in chat_history (assistant
        # artifact entries). This rescues legacy/new threads where a scorecard
        # exists inline but has not been mirrored into scenarios yet.
        chat_history = session.get('chat_history') if isinstance(session, dict) and isinstance(session.get('chat_history'), list) else []
        for _msg in chat_history:
            if not isinstance(_msg, dict):
                continue
            _artifact = _msg.get('artifact') if isinstance(_msg.get('artifact'), dict) else None
            if not isinstance(_artifact, dict):
                continue
            if str(_artifact.get('type') or '').strip() != 'scorecard':
                continue
            _data = _artifact.get('data') if isinstance(_artifact.get('data'), dict) else None
            if not _data:
                continue
            _aid = str(
                _data.get('id')
                or _data.get('analysis_id')
                or _data.get('analysisId')
                or ''
            ).strip()
            if not _aid or _aid in _existing_snap_ids:
                continue
            _snap = _normalize_scorecard_payload(_data)
            _snap['id'] = _aid
            _snap['analysis_id'] = _snap.get('analysis_id') or _aid
            _snap['isBaseline'] = bool(_snap.get('isBaseline'))
            _snap['createdAt'] = _snap.get('createdAt') or _msg.get('timestamp') or _data.get('timestamp')
            if isinstance(_data.get('display_overrides'), dict):
                _snap['display_overrides'] = _data['display_overrides']
            merged_snapshots.append(_snap)
            _existing_snap_ids.add(_aid)

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
            'scorecard_snapshots': merged_snapshots,
            'selected_scorecard_id': snapshot_state['selected_id'] if snapshot_state else None,
            'scenarios': scenarios_list,
            'scenario_levers': scenario_levers,
            'lever_catalog': lever_catalog,
            'output_metrics': sorted(SCENARIO_OUTPUT_FIELDS),
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


@strategy_bp.route('/threads/<thread_id>/scorecard-snapshots/<snapshot_id>', methods=['PATCH'])
@jwt_required()
def update_scorecard_snapshot(thread_id, snapshot_id):
    try:
        user_id = get_jwt_identity()
        payload = request.get_json() or {}
        next_label = str(payload.get('label') or '').strip()
        set_active = bool(payload.get('active'))
        expected_selected_scorecard_id = str(payload.get('expected_selected_scorecard_id') or '').strip() or None
        expected_snapshot_id = str(payload.get('expected_snapshot_id') or snapshot_id or '').strip() or None
        expected_snapshot_revision = str(
            payload.get('expected_snapshot_revision')
            or payload.get('expected_snapshot_created_at')
            or ''
        ).strip() or None

        snapshot_meta = None
        if next_label:
            snapshot_meta = _rename_snapshot_in_session(
                user_id,
                thread_id,
                snapshot_id,
                next_label,
                expected_selected_scorecard_id=expected_selected_scorecard_id,
                expected_snapshot_id=expected_snapshot_id,
                expected_snapshot_revision=expected_snapshot_revision,
            )
            if not snapshot_meta:
                return jsonify({'error': 'Snapshot not found'}), 404

            all_data = _load_scenarios(user_id)
            td = all_data.get(thread_id, {})
            scenarios = td.get('scenarios') if isinstance(td.get('scenarios'), dict) else {}
            scenario = scenarios.get(snapshot_id)
            if isinstance(scenario, dict):
                scenario['label'] = next_label
                if isinstance(scenario.get('result'), dict):
                    scenario['result']['label'] = next_label
                scenario['updated_at'] = datetime.utcnow().isoformat()
                _save_scenarios(user_id, all_data)

        if set_active:
            active_meta = _set_selected_snapshot_in_session(
                user_id,
                thread_id,
                snapshot_id,
                expected_selected_scorecard_id=expected_selected_scorecard_id,
                expected_snapshot_id=expected_snapshot_id,
                expected_snapshot_revision=expected_snapshot_revision,
            )
            if not active_meta:
                return jsonify({'error': 'Snapshot not found'}), 404
            snapshot_meta = {
                **(snapshot_meta or {}),
                **active_meta,
            }

        if not snapshot_meta:
            return jsonify({'error': 'No changes requested'}), 400

        return jsonify({
            'success': True,
            'snapshot': snapshot_meta.get('snapshot'),
            'scorecard_snapshots': snapshot_meta.get('scorecard_snapshots'),
            'selected_scorecard_id': snapshot_meta.get('selected_scorecard_id'),
        }), 200
    except ScorecardConflictError as conflict:
        payload = conflict.payload if isinstance(conflict.payload, dict) else {}
        return jsonify(payload or {'error': str(conflict), 'code': 'scorecard_conflict'}), 409
    except Exception as e:
        current_app.logger.error("[update_scorecard_snapshot] %s", e)
        return jsonify({'error': str(e)}), 500


# ── Workspace (Beta) ──────────────────────────────────────────────────────────
# Cosmetic edits applied via the new Workspace canvas editor. These overrides
# never touch the AI's analytical fields (scores, dimensions, risks); they only
# decorate cosmetic copy and styling on top of the stored snapshot.
_ALLOWED_OVERRIDE_KEYS = {
    'title',
    'subtitle',
    'executive_summary',
    'accent_color',
    'theme',
    'narrative',
    # Trade-off "park / un-park": when False, this scorecard is excluded from
    # hero-strip math, the quadrant, and the ranking pills in the Trade-off
    # view. It still renders in the chat — purely a presentation flag.
    'tradeoff_included',
    # Qualitative narrative the user can hand-edit. These don't feed the numeric
    # score (only dimensions do), so they're manual-or-AI editable, not locked.
    'top_risks',           # list[str]
    'recommended_scenario',  # str
}


def _coerce_override_value(key, value):
    """Best-effort sanitization. Returns the cleaned value, or None to delete."""
    if value is None:
        return None  # caller treats None as "remove this key"
    if key in {'title', 'subtitle', 'executive_summary', 'narrative', 'theme',
               'recommended_scenario'}:
        s = str(value).strip()
        return s if s else None
    if key == 'top_risks':
        # Accept a list of risks (strings or {risk/label} dicts) or a single
        # newline-delimited string. Normalize to a clean list[str]; empty → remove.
        items = []
        if isinstance(value, str):
            items = value.split('\n')
        elif isinstance(value, (list, tuple)):
            for v in value:
                if isinstance(v, dict):
                    items.append(v.get('risk') or v.get('label') or '')
                else:
                    items.append(v)
        cleaned = [str(x).strip() for x in items if str(x).strip()]
        return cleaned if cleaned else None
    if key == 'accent_color':
        s = str(value).strip()
        # accept '#rrggbb', '#rgb', or named subset; reject anything else
        if not s:
            return None
        if s.startswith('#') and len(s) in (4, 7):
            return s
        return None
    if key == 'tradeoff_included':
        # Coerce truthy/falsy strings and numbers. Default to True if ambiguous.
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            v = value.strip().lower()
            if v in ('false', '0', 'no', 'off', 'excluded', 'parked'):
                return False
            if v in ('true', '1', 'yes', 'on', 'included'):
                return True
        return True
    return value


def _find_scorecard_carrier(user_id, thread_id, scorecard_id):
    """Return (kind, container, key, carrier) so the caller can read/write
    display_overrides on the right storage cell.

    kind = 'baseline' → container is the full sessions dict, key=session_key,
                        carrier = the session dict (carrier['result'] holds it)
    kind = 'scenario' → container is the full scenarios all_data dict,
                        key=scenario_id, carrier = the scenario dict
                        (carrier['result'] holds the scorecard)
    """
    sessions = load_user_sessions(user_id) or {}
    _key, session = _resolve_session_entry(sessions, thread_id)
    sid = str(scorecard_id or '').strip()

    # Baseline match: session.result has matching analysis_id OR scorecard_id == thread_id
    if isinstance(session, dict) and isinstance(session.get('result'), dict):
        res = session['result']
        baseline_ids = {
            str(res.get('analysis_id') or '').strip(),
            str(res.get('id') or '').strip(),
            str(thread_id or '').strip(),
        }
        if sid and sid in baseline_ids:
            return ('baseline', sessions, _key or thread_id, session)

    # Variation match: scenario with matching scenario_id OR result.id/analysis_id
    all_data = _load_scenarios(user_id)
    td = all_data.get(thread_id, {})
    scenarios = td.get('scenarios') if isinstance(td.get('scenarios'), dict) else {}
    for scn_id, scn in scenarios.items():
        if not isinstance(scn, dict):
            continue
        result_blob = scn.get('result') if isinstance(scn.get('result'), dict) else {}
        candidate_ids = {
            str(scn_id),
            str(scn.get('scenario_id') or ''),
            str(result_blob.get('id') or ''),
            str(result_blob.get('analysis_id') or ''),
        }
        if sid in candidate_ids:
            return ('scenario', all_data, scn_id, scn)

    # Fallback: chat_history assistant artifact entries can hold scorecards
    # that were rendered inline before scenario persistence.
    if isinstance(session, dict):
        chat_history = session.get('chat_history')
        if isinstance(chat_history, list):
            for msg in reversed(chat_history):
                if not isinstance(msg, dict):
                    continue
                artifact = msg.get('artifact') if isinstance(msg.get('artifact'), dict) else None
                if not isinstance(artifact, dict) or str(artifact.get('type') or '').strip() != 'scorecard':
                    continue
                data = artifact.get('data') if isinstance(artifact.get('data'), dict) else None
                if not isinstance(data, dict):
                    continue
                candidate_ids = {
                    str(data.get('id') or '').strip(),
                    str(data.get('analysis_id') or '').strip(),
                    str(data.get('analysisId') or '').strip(),
                }
                if sid and sid in candidate_ids:
                    return ('chat_artifact', sessions, _key or thread_id, {'result': data})

    return (None, None, None, None)


def apply_scorecard_edit_in_place(user_id, thread_id, scorecard_id, mutate_fn):
    """Locate the LIVE scorecard for (thread_id, scorecard_id) using the same
    carrier resolution as the workspace fetch / overrides endpoints, apply
    ``mutate_fn`` to produce the new full card dict, persist it to whichever
    store actually holds it (session baseline / scenario / chat artifact), and
    return the updated card dict.

    This is the single source of truth for editing the OPEN idea in place. It
    intentionally reuses ``_find_scorecard_carrier`` so a card the workspace can
    render is always a card we can edit — the weaker in-memory lookup in
    ai_agent could only see baseline/snapshot cards and missed scenario-store
    and chat-artifact cards entirely.

    mutate_fn(current_card: dict) -> dict   # returns the FULL merged card
    Returns the persisted card dict, or None when the scorecard can't be located
    or the mutation produced nothing usable.
    """
    kind, container, key, carrier = _find_scorecard_carrier(user_id, thread_id, scorecard_id)
    if not kind or not isinstance(carrier, dict):
        return None
    result_blob = carrier.get('result') if isinstance(carrier.get('result'), dict) else None
    if not isinstance(result_blob, dict):
        return None

    try:
        updated = mutate_fn(dict(result_blob))
    except Exception as exc:  # pragma: no cover - defensive
        current_app.logger.error("[apply_scorecard_edit_in_place] mutate_fn failed: %s", exc)
        return None
    if not isinstance(updated, dict) or not updated:
        return None

    now = datetime.utcnow().isoformat()
    card_id = str(updated.get('id') or updated.get('analysis_id') or scorecard_id or thread_id)
    updated.setdefault('id', card_id)
    updated['updated_at'] = now

    # Mutate the live object in place so any other holder of this reference
    # (and the carrier) sees the change.
    result_blob.clear()
    result_blob.update(updated)

    if kind == 'baseline':
        # container is the sessions dict; carrier is the session, result_blob is
        # session['result']. Ground the open idea so chat re-grounds correctly.
        result_blob['selected_scorecard_id'] = card_id
        container[key]['result'] = result_blob
        container[key]['timestamp'] = now
        save_user_sessions(user_id, container)
    elif kind == 'chat_artifact':
        # carrier['result'] IS the live artifact data dict (already mutated
        # above). Persist the owning session so the edit survives refresh.
        session_entry = container.get(key) if isinstance(container, dict) else None
        if isinstance(session_entry, dict):
            session_entry['timestamp'] = now
            container[key] = session_entry
            save_user_sessions(user_id, container)
    else:
        # container is the scenarios all_data dict; carrier is the scenario.
        carrier['result'] = result_blob
        carrier['updated_at'] = now
        _save_scenarios(user_id, container)

    return result_blob


@strategy_bp.route('/threads/<thread_id>/scorecards/<scorecard_id>', methods=['GET'])
@jwt_required()
def get_scorecard_for_workspace(thread_id, scorecard_id):
    """Lightweight single-artifact fetch used by the Workspace canvas.
    Returns the full scorecard payload + cosmetic display_overrides in one
    round-trip. Doesn't pull the rest of the bundle (messages, scenarios list,
    etc.) so the workspace loads fast and can't be blocked by an unrelated
    bundle hiccup."""
    try:
        user_id = get_jwt_identity()
        kind, _container, _key, carrier = _find_scorecard_carrier(user_id, thread_id, scorecard_id)
        if not kind or not isinstance(carrier, dict):
            return jsonify({'error': 'Scorecard not found', 'thread_id': thread_id, 'scorecard_id': scorecard_id}), 404

        result_blob = carrier.get('result') if isinstance(carrier.get('result'), dict) else None
        if not isinstance(result_blob, dict):
            return jsonify({'error': 'Scorecard payload missing'}), 404

        normalized = _normalize_scorecard_payload(result_blob)
        normalized['id'] = str(
            normalized.get('id')
            or normalized.get('analysis_id')
            or scorecard_id
        )
        normalized['isBaseline'] = (kind == 'baseline')
        overrides = result_blob.get('display_overrides') if isinstance(result_blob.get('display_overrides'), dict) else {}

        return jsonify({
            'scorecard': normalized,
            'display_overrides': overrides,
            'kind': kind,
        }), 200
    except Exception as e:
        current_app.logger.error("[get_scorecard_for_workspace] %s", e)
        return jsonify({'error': str(e)}), 500


@strategy_bp.route('/threads/<thread_id>/scorecards/<scorecard_id>/overrides', methods=['GET', 'PATCH'])
@jwt_required()
def scorecard_display_overrides(thread_id, scorecard_id):
    """Read or write cosmetic display_overrides for a single scorecard.

    GET    → returns the current overrides object (empty if none)
    PATCH  → merges the supplied keys into display_overrides. Passing `null`
             for a key removes it. The endpoint never touches analytical fields.
    """
    try:
        user_id = get_jwt_identity()
        kind, container, key, carrier = _find_scorecard_carrier(user_id, thread_id, scorecard_id)
        if not kind or not isinstance(carrier, dict):
            return jsonify({'error': 'Scorecard not found', 'thread_id': thread_id, 'scorecard_id': scorecard_id}), 404

        result_blob = carrier.get('result') if isinstance(carrier.get('result'), dict) else None
        if not isinstance(result_blob, dict):
            return jsonify({'error': 'Scorecard payload missing'}), 404

        current = result_blob.get('display_overrides') if isinstance(result_blob.get('display_overrides'), dict) else {}

        if request.method == 'GET':
            return jsonify({'display_overrides': current}), 200

        # PATCH
        payload = request.get_json(silent=True) or {}
        patch = payload.get('display_overrides') if isinstance(payload.get('display_overrides'), dict) else payload
        if not isinstance(patch, dict):
            return jsonify({'error': 'Body must be a JSON object'}), 400

        next_overrides = dict(current)
        for raw_key, raw_value in patch.items():
            if raw_key not in _ALLOWED_OVERRIDE_KEYS:
                # ignore unknown keys rather than 400'ing — keeps the API forward-compatible
                continue
            cleaned = _coerce_override_value(raw_key, raw_value)
            if cleaned is None or cleaned == '':
                next_overrides.pop(raw_key, None)
            else:
                next_overrides[raw_key] = cleaned

        result_blob['display_overrides'] = next_overrides
        result_blob['display_overrides_updated_at'] = datetime.utcnow().isoformat()

        if kind == 'baseline':
            # container is the sessions dict, key is the session_key
            container[key]['result'] = result_blob
            container[key]['timestamp'] = datetime.utcnow().isoformat()
            save_user_sessions(user_id, container)
        elif kind == 'chat_artifact':
            # Persist overrides back into the matching assistant artifact entry
            # in chat_history so workspace edits survive refresh even when this
            # scorecard has not been promoted to scenario storage yet.
            session_entry = container.get(key) if isinstance(container, dict) else None
            if isinstance(session_entry, dict):
                chat_history = session_entry.get('chat_history')
                if isinstance(chat_history, list):
                    target_id = str(scorecard_id or '').strip()
                    for msg in chat_history:
                        if not isinstance(msg, dict):
                            continue
                        artifact = msg.get('artifact') if isinstance(msg.get('artifact'), dict) else None
                        if not isinstance(artifact, dict) or str(artifact.get('type') or '').strip() != 'scorecard':
                            continue
                        data = artifact.get('data') if isinstance(artifact.get('data'), dict) else None
                        if not isinstance(data, dict):
                            continue
                        ids = {
                            str(data.get('id') or '').strip(),
                            str(data.get('analysis_id') or '').strip(),
                            str(data.get('analysisId') or '').strip(),
                        }
                        if target_id and target_id in ids:
                            data['display_overrides'] = next_overrides
                            data['display_overrides_updated_at'] = result_blob['display_overrides_updated_at']
                            artifact['data'] = data
                            msg['artifact'] = artifact
                            break
                    session_entry['chat_history'] = chat_history
                    result_blob_session = session_entry.get('result')
                    if isinstance(result_blob_session, dict):
                        result_blob_session['chat_history'] = chat_history
                    session_entry['timestamp'] = datetime.utcnow().isoformat()
                    container[key] = session_entry
                    save_user_sessions(user_id, container)
        else:
            # container is the scenarios all_data dict
            carrier['result'] = result_blob
            carrier['updated_at'] = datetime.utcnow().isoformat()
            _save_scenarios(user_id, container)

        return jsonify({
            'success': True,
            'display_overrides': next_overrides,
            'scorecard_id': scorecard_id,
            'thread_id': thread_id,
            'kind': kind,
        }), 200

    except Exception as e:
        current_app.logger.error("[scorecard_display_overrides] %s", e)
        return jsonify({'error': str(e)}), 500


@strategy_bp.route('/threads/<thread_id>/scorecard-patch', methods=['PATCH'])
@jwt_required()
def patch_thread_scorecard(thread_id):
    user_id = get_jwt_identity()
    payload = request.get_json(silent=True) or {}
    patchable_fields = {
        'executive_summary', 'executive_narrative',
        'top_risks', 'risks', 'recommendations',
        'assumptions', 'key_insights',
        'component_rationale', 'decision_framework',
        'financial_impact', 'investment_analysis',
        'npv_irr_analysis', 'valuation',
    }
    patch = {key: value for key, value in payload.items() if key in patchable_fields}
    if 'risks' in patch and 'top_risks' not in patch:
        patch['top_risks'] = patch['risks']
    patch.pop('risks', None)
    if not patch:
        return jsonify({'error': 'No patchable fields provided'}), 400

    sessions = load_user_sessions(user_id) or {}
    resolved_thread_id, session = _resolve_session_entry(sessions, thread_id)
    if not isinstance(session, dict):
        return jsonify({'error': 'Thread not found'}), 404

    session_result = session.get('result') if isinstance(session.get('result'), dict) else {}
    snapshot_state = _scorecard_snapshot_state(session_result, resolved_thread_id)
    expected_selected_scorecard_id = str(payload.get('expected_selected_scorecard_id') or '').strip() or None
    expected_snapshot_id = str(
        payload.get('expected_snapshot_id')
        or payload.get('selected_scorecard_id')
        or expected_selected_scorecard_id
        or ''
    ).strip() or None
    expected_snapshot_revision = str(
        payload.get('expected_snapshot_revision')
        or payload.get('expected_snapshot_created_at')
        or ''
    ).strip() or None
    try:
        _assert_scorecard_write_fresh(
            snapshot_state,
            resolved_thread_id,
            expected_selected_scorecard_id=expected_selected_scorecard_id,
            expected_snapshot_id=expected_snapshot_id,
            expected_snapshot_revision=expected_snapshot_revision,
        )
    except ScorecardConflictError as conflict:
        payload = conflict.payload if isinstance(conflict.payload, dict) else {}
        return jsonify(payload or {'error': str(conflict), 'code': 'scorecard_conflict'}), 409
    base_scorecard = (
        payload.get('scorecard')
        if isinstance(payload.get('scorecard'), dict)
        else snapshot_state['selected_snapshot']
    )
    base_scorecard = _normalize_scorecard_payload(base_scorecard)
    if not isinstance(base_scorecard, dict) or not base_scorecard:
        return jsonify({'error': 'No scorecard context is available for this thread'}), 400

    updated_scorecard = _merge_scorecard_patch(base_scorecard, patch)
    current_selected = snapshot_state['selected_snapshot'] or snapshot_state['baseline']
    current_selected_id = str(
        payload.get('selected_scorecard_id')
        or current_selected.get('id')
        or snapshot_state['selected_id']
        or resolved_thread_id
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

    next_result = {
        **session_result,
        '_baseline_scorecard': session_result.get('_baseline_scorecard') or snapshot_state['baseline'],
        'scorecard_snapshots': next_snapshots,
        'selected_scorecard_id': edited_id,
    }
    session['analysis_result'] = next_result
    session['result'] = next_result
    session['timestamp'] = datetime.utcnow().isoformat()
    sessions[resolved_thread_id] = session
    save_user_sessions(user_id, sessions)
    return jsonify({
        'success': True,
        'updated_scorecard': edited_snapshot,
        'scorecard_snapshots': next_snapshots,
        'selected_scorecard_id': edited_id,
    }), 200



@strategy_bp.route('/threads/<thread_id>/scorecard-snapshots/<snapshot_id>', methods=['DELETE'])
@jwt_required()
def delete_scorecard_snapshot(thread_id, snapshot_id):
    try:
        user_id = get_jwt_identity()
        expected_selected_scorecard_id = str(request.args.get('expected_selected_scorecard_id') or '').strip() or None
        expected_snapshot_id = str(request.args.get('expected_snapshot_id') or snapshot_id or '').strip() or None
        expected_snapshot_revision = str(
            request.args.get('expected_snapshot_revision')
            or request.args.get('expected_snapshot_created_at')
            or ''
        ).strip() or None
        snapshot_meta = _delete_snapshot_from_session(
            user_id,
            thread_id,
            snapshot_id,
            expected_selected_scorecard_id=expected_selected_scorecard_id,
            expected_snapshot_id=expected_snapshot_id,
            expected_snapshot_revision=expected_snapshot_revision,
        )
        if not snapshot_meta:
            return jsonify({'error': 'Snapshot not found'}), 404

        all_data = _load_scenarios(user_id)
        td = all_data.get(thread_id, {})
        scenarios = td.get('scenarios') if isinstance(td.get('scenarios'), dict) else {}
        if snapshot_id in scenarios:
            del scenarios[snapshot_id]
            if td.get('adopted_scenario_id') == snapshot_id:
                td['adopted_scenario_id'] = None
            _save_scenarios(user_id, all_data)

        return jsonify({
            'success': True,
            'deleted_snapshot_id': snapshot_meta.get('deleted_snapshot_id'),
            'scorecard_snapshots': snapshot_meta.get('scorecard_snapshots'),
            'selected_scorecard_id': snapshot_meta.get('selected_scorecard_id'),
        }), 200
    except ScorecardConflictError as conflict:
        payload = conflict.payload if isinstance(conflict.payload, dict) else {}
        return jsonify(payload or {'error': str(conflict), 'code': 'scorecard_conflict'}), 409
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error("[delete_scorecard_snapshot] %s", e)
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
        all_data = _load_scenarios(user_id)
        resolved_thread_id, session_key, session = _resolve_strategy_thread_state(sessions, all_data, thread_id)
        if not resolved_thread_id:
            return jsonify({'error': 'Thread not found'}), 404

        thread_data = all_data.get(resolved_thread_id) if isinstance(all_data, dict) else None
        thread_data = thread_data if isinstance(thread_data, dict) else None
        if not isinstance(session, dict) and not isinstance(thread_data, dict):
            return jsonify({'error': 'Thread not found'}), 404
        if not isinstance(session, dict):
            existing_baseline = thread_data.get('baseline') if isinstance(thread_data, dict) else None
            scenarios = thread_data.get('scenarios') if isinstance(thread_data, dict) and isinstance(thread_data.get('scenarios'), dict) else {}
            adopted_scenario_id = thread_data.get('adopted_scenario_id') if isinstance(thread_data, dict) else None
            adopted_scenario = scenarios.get(adopted_scenario_id) if adopted_scenario_id and isinstance(scenarios.get(adopted_scenario_id), dict) else None
            current_result = (
                adopted_scenario.get('result') if isinstance(adopted_scenario, dict) and isinstance(adopted_scenario.get('result'), dict)
                else existing_baseline if isinstance(existing_baseline, dict)
                else None
            )
            existing_name = None
            if isinstance(existing_baseline, dict):
                existing_name = (
                    existing_baseline.get('project_name')
                    or existing_baseline.get('name')
                    or existing_baseline.get('title')
                )
            now_iso = datetime.utcnow().isoformat()
            session = {
                'session_id': resolved_thread_id,
                'name': str(existing_name or next_name or 'Jaspen Analysis').strip(),
                'document_type': 'strategy',
                'created': now_iso,
                'timestamp': now_iso,
                'status': 'completed' if isinstance(thread_data, dict) and (thread_data.get('baseline') or thread_data.get('scenarios')) else 'in_progress',
                'chat_history': [],
                'result': dict(current_result) if isinstance(current_result, dict) else None,
                'analysis_history': (
                    [{'analysis_id': str(current_result.get('analysis_id') or resolved_thread_id), 'result': dict(current_result)}]
                    if isinstance(current_result, dict)
                    else []
                ),
            }
            session_key = resolved_thread_id

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

        sessions[session_key or resolved_thread_id] = session
        save_user_sessions(user_id, sessions)

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

            all_data[resolved_thread_id] = thread_data
            _save_scenarios(user_id, all_data)

        return jsonify({
            'success': True,
            'thread': {
                'id': resolved_thread_id,
                'session_id': resolved_thread_id,
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

        view_context = payload.get('view_context') if isinstance(payload.get('view_context'), dict) else {}
        if not view_context:
            view_context = {}
            for key in ('current_view', 'active_tab', 'active_scorecard_id', 'active_scenario_id', 'wbs_summary'):
                if key in payload:
                    view_context[key] = payload.get(key)
        if not isinstance(view_context, dict):
            view_context = {}
        view_context = {k: v for k, v in view_context.items() if k in {'current_view', 'active_tab', 'active_scorecard_id', 'active_scenario_id', 'wbs_summary'}}

        view_context_lines = []
        current_view = str(view_context.get('current_view') or '').strip()
        if current_view:
            view_context_lines.append(f"- Current view: {current_view}")
        active_tab = str(view_context.get('active_tab') or '').strip()
        if active_tab:
            view_context_lines.append(f"- Active tab: {active_tab}")
        active_scorecard_id = str(view_context.get('active_scorecard_id') or '').strip()
        if active_scorecard_id:
            view_context_lines.append(f"- Active scorecard ID: {active_scorecard_id}")
        active_scenario_id = str(view_context.get('active_scenario_id') or '').strip()
        if active_scenario_id:
            view_context_lines.append(f"- Active scenario ID: {active_scenario_id}")
        wbs_summary = view_context.get('wbs_summary') if isinstance(view_context.get('wbs_summary'), dict) else {}
        total_tasks = wbs_summary.get('total_tasks')
        by_status = wbs_summary.get('by_status') if isinstance(wbs_summary.get('by_status'), dict) else {}
        if total_tasks is not None or by_status:
            status_tokens = []
            for status_key in ('todo', 'in_progress', 'blocked', 'done'):
                if status_key in by_status:
                    status_tokens.append(f"{status_key}:{by_status.get(status_key)}")
            if total_tasks is not None and status_tokens:
                view_context_lines.append(f"- Execution summary: {total_tasks} tasks ({', '.join(status_tokens)})")
            elif total_tasks is not None:
                view_context_lines.append(f"- Execution summary: {total_tasks} tasks")
            elif status_tokens:
                view_context_lines.append(f"- Execution summary by status: {', '.join(status_tokens)}")
        view_context_text = "\n".join(view_context_lines) if view_context_lines else "- Not provided."

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
            'investment_analysis': base_scorecard.get('investment_analysis'),
            'npv_irr_analysis': base_scorecard.get('npv_irr_analysis'),
            'valuation': base_scorecard.get('valuation'),
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

Current workspace view context:
{view_context_text}

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
    "assumptions": ["<optional updated assumption list>"],
    "financial_impact": {{
      "<metric_key>": "<optional rewritten wording>"
    }},
    "investment_analysis": {{
      "<metric_key>": "<optional rewritten wording>"
    }},
    "npv_irr_analysis": {{
      "<metric_key>": "<optional rewritten wording>"
    }},
    "valuation": {{
      "<metric_key>": "<optional rewritten wording>"
    }}
  }},
  "updated_sections": ["<section keys you changed>"]
}}

Rules:
- If the user is only asking a question and not asking to rewrite or reword the scorecard, set updated_scorecard to null and updated_sections to [].
- Never change numeric scores, category scores, or financial values in the scorecard.
- Only rewrite wording or organization for text sections.
- Preserve the original meaning unless the user explicitly asks to change the substance.
- Use the workspace view context to focus your answer on what the user is currently looking at.
- If you update a list section, return the full replacement list for that section.
- If you update an object section, return the full replacement object for that section.
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

        _persist_scorecard_assistant_turn(session, session_result, instruction, reply)

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
            selected_scorecard_id = edited_id
        else:
            session['result'] = session_result

        session['timestamp'] = datetime.utcnow().isoformat()
        sessions[session_key or thread_id] = session
        persisted = save_user_sessions(user_id, sessions)
        if not persisted:
            current_app.logger.error(
                "[scorecard_assistant] save_user_sessions failed for user=%s thread=%s",
                user_id, thread_id,
            )

        # Persist the user/assistant exchange into the session chat_history
        chat_history = session.get('chat_history')
        if not isinstance(chat_history, list):
            result_blob = session.get('result')
            chat_history = (
                result_blob.get('chat_history')
                if isinstance(result_blob, dict) and isinstance(result_blob.get('chat_history'), list)
                else []
            )
        now_iso = datetime.utcnow().isoformat()
        chat_history = list(chat_history)
        chat_history.append({'role': 'user', 'content': instruction, 'text': instruction, 'timestamp': now_iso})
        chat_history.append({'role': 'assistant', 'content': reply, 'text': reply, 'timestamp': now_iso})
        session['chat_history'] = chat_history
        if isinstance(session.get('result'), dict):
            session['result']['chat_history'] = chat_history
        session['timestamp'] = now_iso
        sessions[session_key or thread_id] = session
        persisted = save_user_sessions(user_id, sessions)
        if not persisted:
            current_app.logger.error(
                "[scorecard_assistant] save_user_sessions failed for user=%s thread=%s",
                user_id, thread_id,
            )

        return jsonify({
            'success': True,
            'reply': reply,
            'updated_scorecard': updated_scorecard,
            'updated_sections': updated_sections,
            'selected_scorecard_id': selected_scorecard_id,
            'persisted': persisted,
        }), 200

    except Exception as e:
        current_app.logger.error("[scorecard_assistant] %s", e)
        return jsonify({'error': str(e)}), 500


# ============================================================
# EXECUTION ASSISTANT  (execution plan sidebar)
# ============================================================

@strategy_bp.route('/threads/<thread_id>/execution-assistant', methods=['POST'])
@jwt_required()
@limiter.limit("20 per minute")
def execution_assistant(thread_id):
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

        # Load session + WBS
        sessions = load_user_sessions(user_id) or {}
        session_key, session = _resolve_session_entry(sessions, thread_id)
        if not isinstance(session, dict):
            return jsonify({'error': 'Thread not found'}), 404

        all_data = _load_scenarios(user_id)
        td = all_data.get(thread_id, {}) if isinstance(all_data, dict) else {}
        project_wbs = td.get('project_wbs') if isinstance(td, dict) else None
        tasks = project_wbs.get('tasks') if isinstance(project_wbs, dict) else []
        if not isinstance(tasks, list):
            tasks = []

        # Build compact task list for context
        task_lines = []
        for t in tasks:
            tid_str = str(t.get('id') or '')
            title = str(t.get('title') or '')
            phase = str(t.get('phase') or '')
            status = str(t.get('status') or 'todo')
            owner = str(t.get('owner') or '')
            due = str(t.get('due_date') or '')
            line = f"  - id={tid_str} | {title} | phase={phase} | status={status}"
            if owner:
                line += f" | owner={owner}"
            if due:
                line += f" | due={due}"
            task_lines.append(line)
        task_block = "\n".join(task_lines) if task_lines else "  (no tasks yet)"

        # Full conversation history from this session
        full_history = _load_thread_conversation(user_id, thread_id)
        history_lines = []
        for item in full_history[-30:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get('role') or '').strip()
            role_label = 'User' if 'user' in role.lower() else 'Jaspen'
            content = str(item.get('content') or item.get('text') or '').strip()
            if content:
                history_lines.append(f"{role_label}: {content[:500]}")
        history_block = "\n".join(history_lines) if history_lines else "(no prior conversation)"

        # Project identity
        project_name = str(
            session.get('name') or
            (session.get('result') or {}).get('project_name') or
            'this project'
        ).strip()

        system_prompt = (
            "You are the Jaspen execution plan assistant. "
            "You help users manage tasks in their execution plan. "
            "You have full context of the project from intake through scorecard, scenarios, and execution. "
            "Return valid JSON only."
        )

        editor_prompt = f"""You are reviewing the execution plan for: {project_name}

Full conversation history (intake → scorecard → scenarios → execution):
{history_block}

User request:
{instruction}

Current execution plan tasks:
{task_block}

You can modify the plan by returning uiActions. Each action has a "type" and "payload".

Supported action types:
- WBS_ADD_TASK: add a new task. payload fields: title (required), phase, status (todo/in_progress/done/blocked), owner, due_date (YYYY-MM-DD), description, priority (low/medium/high), estimated_days, depends_on (array of task IDs)
- WBS_UPDATE_TASK: update an existing task. payload fields: id (required, must match an existing task id), plus any fields to change
- WBS_REMOVE_TASK: remove a task. payload fields: id (required)
- WBS_ADD_DEPENDENCY: add a dependency. payload fields: task_id (the task that depends), depends_on (the task it depends on)

Rules:
- Use exact task IDs from the task list above when referencing existing tasks
- Only return uiActions when the user explicitly asks to modify the plan
- If the user is asking a question, return a helpful reply with empty uiActions
- Use the full conversation history to give context-aware answers (not generic responses)
- Keep the reply concise and professional

Return one valid JSON object only:
{{
  "reply": "<short, direct response to the user>",
  "uiActions": [
    {{"type": "<action_type>", "payload": {{...}}}}
  ]
}}

If no plan changes are needed, return "uiActions": [].
""".strip()

        api_key = (
            current_app.config.get('ANTHROPIC_API_KEY')
            or os.environ.get('ANTHROPIC_API_KEY')
        )
        if not api_key:
            return jsonify({'error': 'AI service unavailable'}), 503
        client = anthropic.Anthropic(api_key=api_key)
        model_id = model_selection.get('llm_model') or 'claude-haiku-4-5-20251001'

        try:
            response = client.messages.create(
                model=model_id,
                max_tokens=1500,
                system=system_prompt,
                messages=[{"role": "user", "content": editor_prompt}],
            )
            raw = response.content[0].text if response.content else '{}'
        except Exception as llm_err:
            current_app.logger.error("[execution_assistant] LLM error: %s", llm_err)
            return jsonify({'error': 'AI service unavailable'}), 503

        # Parse JSON response
        result = {}
        try:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r'^```[a-zA-Z]*\n?', '', cleaned)
                cleaned = re.sub(r'\n?```$', '', cleaned)
            result = json.loads(cleaned)
        except Exception:
            result = {'reply': raw, 'uiActions': []}

        reply = str(result.get('reply') or '').strip() or 'Done.'
        ui_actions = result.get('uiActions') or result.get('actions') or []
        if not isinstance(ui_actions, list):
            ui_actions = []

        # Persist the turn to conversation history
        try:
            _persist_scorecard_assistant_turn(session, session.get('result') or {}, instruction, reply)
            sessions[session_key] = session
            save_user_sessions(user_id, sessions)
        except Exception as persist_err:
            current_app.logger.warning("[execution_assistant] persist failed: %s", persist_err)

        return jsonify({
            'success': True,
            'reply': reply,
            'uiActions': ui_actions,
        }), 200

    except Exception as e:
        current_app.logger.error("[execution_assistant] %s", e)
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
