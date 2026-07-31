"""Durable evaluation identity, attachment metrics, and usage reporting."""

from collections import defaultdict
from statistics import mean, median
import math
import uuid


def new_evaluation_id():
    return str(uuid.uuid4())


def _clean_id(value):
    value = str(value or '').strip()
    return value or None


def evaluation_id_for_scorecard(user_id, scorecard_id):
    scorecard_id = _clean_id(scorecard_id)
    if not scorecard_id:
        return None
    from .models import Scorecard
    row = Scorecard.query.filter_by(id=scorecard_id, user_id=str(user_id)).first()
    return _clean_id(getattr(row, 'evaluation_id', None)) if row else None


def ensure_session_evaluation_id(session, *, user_id=None, scorecard_id=None, force_new=False):
    """Return the active evaluation, preferring the selected durable scorecard."""
    if not isinstance(session, dict):
        return None
    selected_scorecard_id = _clean_id(scorecard_id)
    if not selected_scorecard_id:
        view_context = session.get('view_context') if isinstance(session.get('view_context'), dict) else {}
        selected_scorecard_id = _clean_id(view_context.get('active_scorecard_id'))
    if selected_scorecard_id and user_id:
        persisted = evaluation_id_for_scorecard(user_id, selected_scorecard_id)
        if persisted:
            session['active_evaluation_id'] = persisted
            session['active_evaluation_scorecard_id'] = selected_scorecard_id
            return persisted
    current = None if force_new else _clean_id(session.get('active_evaluation_id'))
    if not current:
        current = new_evaluation_id()
        session['active_evaluation_id'] = current
        session.pop('active_evaluation_scorecard_id', None)
    return current


def evaluation_id_for_new_scorecard(session, *, user_id):
    """Reuse an unbound framing ID; start a new ID after one project is bound."""
    current = ensure_session_evaluation_id(session, user_id=user_id)
    bound_scorecard_id = _clean_id(session.get('active_evaluation_scorecard_id'))
    if not bound_scorecard_id and current:
        from .models import Scorecard
        bound = Scorecard.query.filter_by(
            user_id=str(user_id),
            evaluation_id=current,
        ).first()
        bound_scorecard_id = _clean_id(getattr(bound, 'id', None)) if bound else None
    if bound_scorecard_id:
        current = ensure_session_evaluation_id(session, user_id=user_id, force_new=True)
    return current


def bind_scorecard_evaluation(session, scorecard, evaluation_id):
    evaluation_id = _clean_id(evaluation_id) or new_evaluation_id()
    scorecard.evaluation_id = evaluation_id
    if isinstance(scorecard.data, dict):
        scorecard.data['evaluation_id'] = evaluation_id
    if isinstance(session, dict):
        session['active_evaluation_id'] = evaluation_id
        session['active_evaluation_scorecard_id'] = str(scorecard.id)
    return evaluation_id


def attachment_metrics(attachments):
    items = attachments if isinstance(attachments, list) else []
    extracted_tokens = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        explicit = item.get('extracted_tokens') or item.get('extracted_token_count')
        if explicit is not None:
            try:
                extracted_tokens += max(0, int(explicit))
                continue
            except (TypeError, ValueError):
                pass
        text = str(item.get('text_content') or item.get('extracted_text') or '')
        if text:
            extracted_tokens += max(1, math.ceil(len(text) / 4))
    return len(items), extracted_tokens


def chat_operation_type(actions=None, *, attachment_count=0, regenerated=False):
    if regenerated:
        return 'chat_revision'
    successful_tools = []
    for action in actions if isinstance(actions, list) else []:
        if not isinstance(action, dict):
            continue
        result = action.get('result') if isinstance(action.get('result'), dict) else {}
        if result.get('ok'):
            successful_tools.append(str(result.get('tool') or '').strip())
    if 'set_scoring_rubric' in successful_tools:
        return 'rubric_refinement'
    if 'generate_tradeoff_comparison' in successful_tools:
        return 'recommendation_review'
    if attachment_count:
        return 'attachment_analysis'
    return 'framing_clarification'


def split_integer(total, count):
    count = max(1, int(count or 1))
    total = int(total or 0)
    base, remainder = divmod(total, count)
    return [base + (1 if index < remainder else 0) for index in range(count)]


def _percentile(values, percentile):
    values = sorted(float(value) for value in values)
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] + ((values[upper] - values[lower]) * (position - lower))


def build_evaluation_usage_report(events):
    """Aggregate durable usage events without requiring historical IDs."""
    grouped = defaultdict(list)
    for event in events:
        evaluation_id = _clean_id(getattr(event, 'evaluation_id', None))
        if evaluation_id:
            grouped[evaluation_id].append(event)

    evaluation_rows = []
    for evaluation_id, rows in grouped.items():
        credits = sum(int(getattr(row, 'settled_credits', 0) or getattr(row, 'credits_charged', 0) or 0) for row in rows)
        evaluation_rows.append({
            'evaluation_id': evaluation_id,
            'credits': credits,
            'model': next((getattr(row, 'model', None) for row in rows if getattr(row, 'model', None)), None),
            'plan': next((getattr(row, 'plan_key', None) for row in rows if getattr(row, 'plan_key', None)), None),
            'has_attachments': any(int(getattr(row, 'attachment_count', 0) or 0) > 0 for row in rows),
            'operations': len(rows),
            'failures': sum(1 for row in rows if not bool(getattr(row, 'success', True))),
        })

    credits = [row['credits'] for row in evaluation_rows]

    def summarize(rows):
        values = [row['credits'] for row in rows]
        return {
            'evaluations': len(rows),
            'average_credits': round(mean(values), 2) if values else None,
            'median_credits': round(median(values), 2) if values else None,
        }

    def summarize_by(key):
        buckets = defaultdict(list)
        for row in evaluation_rows:
            buckets[str(row.get(key) if row.get(key) is not None else 'unknown')].append(row)
        return {name: summarize(rows) for name, rows in sorted(buckets.items())}

    attachment_buckets = {
        'with_attachments': [row for row in evaluation_rows if row['has_attachments']],
        'without_attachments': [row for row in evaluation_rows if not row['has_attachments']],
    }

    return {
        **summarize(evaluation_rows),
        'credit_ranges': {
            'efficient_p10_p25': [_percentile(credits, 0.10), _percentile(credits, 0.25)],
            'typical_p25_p75': [_percentile(credits, 0.25), _percentile(credits, 0.75)],
            'heavy_p75_p95': [_percentile(credits, 0.75), _percentile(credits, 0.95)],
        },
        'by_model': summarize_by('model'),
        'by_plan': summarize_by('plan'),
        'by_attachment_usage': {
            name: summarize(rows) for name, rows in attachment_buckets.items()
        },
        'historical_events_without_evaluation_id_excluded': sum(
            1 for event in events if not _clean_id(getattr(event, 'evaluation_id', None))
        ),
    }
