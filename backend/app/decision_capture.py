"""Decision-intelligence capture helpers for the conversational agent.

This module builds FACTS, never wording. The agent composes every question the
customer sees; code only reports what is stored (dispositions, signals,
outcomes, plan progress) and verifies the provenance of what the customer
said. Nothing here parses customer text for meaning: the only text check is
whether a message is literally a choice-card answer the assistant offered.
"""

import json
from datetime import date

from .decision_records import (
    DISPOSITION_NOT_PURSUE,
    DISPOSITION_STILL_EVALUATING,
    _find_existing_record,
    can_read_record,
    canonical_context,
    decision_signals_for,
    execution_option_key,
    is_plan_decision_source,
    option_dispositions,
)
from .models_decision_record import OptionDecision

CHOICE_OPEN = '[[choice]]'
CHOICE_CLOSE = '[[/choice]]'
MEASURED_OUTCOME_STATUSES = frozenset({
    'achieved', 'partially_achieved', 'not_achieved', 'abandoned',
})
_CONTENT_LIMIT = 240


def parse_choice_block(text):
    """The choice card embedded in one assistant message, or None."""
    raw = str(text or '')
    start = raw.find(CHOICE_OPEN)
    if start < 0:
        return None
    end = raw.find(CHOICE_CLOSE, start)
    if end < 0:
        return None
    try:
        parsed = json.loads(raw[start + len(CHOICE_OPEN):end].strip())
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict) or not isinstance(parsed.get('options'), list):
        return None
    options = []
    for item in parsed['options']:
        if isinstance(item, str):
            item = {'label': item}
        if not isinstance(item, dict):
            continue
        label = str(item.get('label') or '').strip()
        if label:
            options.append({'label': label, 'exclusive': item.get('exclusive') is True})
    if not options:
        return None
    return {
        'question': str(parsed.get('question') or '').strip(),
        'options': options,
        'allow_multi': bool(parsed.get('allow_multi')),
    }


def _split_into_labels(message, labels):
    """Return the labels that compose `message` joined by ', ', else None."""
    ordered = sorted(set(labels), key=len, reverse=True)
    memo = {}

    def walk(index):
        if index == len(message):
            return []
        if index in memo:
            return memo[index]
        memo[index] = None
        for label in ordered:
            if not message.startswith(label, index):
                continue
            after = index + len(label)
            if after == len(message):
                memo[index] = [label]
                break
            if message.startswith(', ', after):
                rest = walk(after + 2)
                if rest is not None:
                    memo[index] = [label] + rest
                    break
        return memo[index]

    return walk(0)


def _entry_text(entry):
    content = entry.get('content') if isinstance(entry, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ''.join(
            str(part.get('text') or '') for part in content
            if isinstance(part, dict) and part.get('type') == 'text'
        )
    return ''


def choice_answer_context(chat_history, user_message):
    """Provenance of `user_message` when it is literally a choice-card answer.

    The card answer arrives as the user's own message (the selected labels,
    joined by ', '). This checks only that exact form against the card the
    assistant showed in the preceding message.
    """
    message = str(user_message or '').strip()
    if not message or not isinstance(chat_history, list):
        return None
    turns = list(chat_history)
    if turns and isinstance(turns[-1], dict) and turns[-1].get('role') == 'user' \
            and _entry_text(turns[-1]).strip() == message:
        turns = turns[:-1]
    # Artifact cards are stored as assistant entries with no text after the
    # reply; the card the user answered is on the last assistant text entry
    # since their previous message.
    previous = None
    for turn in reversed(turns):
        if not isinstance(turn, dict):
            continue
        if turn.get('role') == 'user':
            break
        if turn.get('role') == 'assistant' and not turn.get('artifact') and _entry_text(turn).strip():
            previous = turn
            break
    choice = parse_choice_block(_entry_text(previous)) if previous else None
    if not choice:
        return None
    labels = [item['label'] for item in choice['options']]
    selected = _split_into_labels(message, labels) if choice['allow_multi'] else (
        [message] if message in labels else None
    )
    if not selected:
        return None
    exclusive = {item['label'] for item in choice['options'] if item['exclusive']}
    return {
        'question': choice['question'][:500],
        'options': labels[:24],
        'selected': selected,
        'exclusive_selected': [label for label in selected if label in exclusive],
    }


def normalize_iso_date(value):
    """An ISO calendar date string, or None when the value is not one."""
    text = str(value or '').strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def find_thread_record(user, thread_id):
    """The thread's canonical Decision Record when this user may read it."""
    _row, organization_id, attribution_user_id = canonical_context(user, thread_id)
    record = _find_existing_record(organization_id, attribution_user_id or user.id, thread_id)
    if record is None or not can_read_record(record, user):
        return None
    return record


def _clip(value, limit=_CONTENT_LIMIT):
    text = str(value or '').strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def _latest_cards_by_option(record):
    payload = record.record if isinstance(record.record, dict) else {}
    latest = {}
    for card in payload.get('scorecards') or []:
        if isinstance(card, dict):
            key = execution_option_key(card)
            if key:
                latest[key] = card
    return latest


def _plan_progress(plans):
    tasks = [
        task for plan in plans
        for task in (plan.get('tasks') if isinstance(plan.get('tasks'), list) else [])
        if isinstance(task, dict)
    ]
    if not tasks:
        return {'status': 'none'}
    done = sum(1 for task in tasks if str(task.get('status') or '').strip().lower() == 'done')
    return {
        'status': 'complete' if done == len(tasks) else 'in_progress',
        'tasks_done': done,
        'tasks_total': len(tasks),
        'committed_tasks': sum(1 for task in tasks if isinstance(task.get('commitment'), dict)),
    }


def _signal_fact(signal):
    fact = {
        'signal_id': str(signal.id),
        'content': _clip(signal.content),
        'source': signal.source,
        'at': signal.occurred_at.isoformat() if signal.occurred_at else None,
    }
    if isinstance(signal.structured, dict) and signal.structured:
        fact['structured'] = signal.structured
    return fact


def _signals_by_kind(signals):
    grouped = {}
    for signal in signals:
        grouped.setdefault(signal.kind, []).append(signal)
    return {
        kind: {'count': len(items), 'latest': _signal_fact(items[-1])}
        for kind, items in grouped.items()
    }


def _review_dates(signals):
    out = []
    for signal in signals:
        if signal.kind not in {'success_measure', 'review_timing'}:
            continue
        structured = signal.structured if isinstance(signal.structured, dict) else {}
        review_by = normalize_iso_date(structured.get('review_by'))
        if review_by:
            out.append((review_by, signal))
    return out


def _outcome_state(outcomes):
    if not outcomes:
        return 'none'
    latest = outcomes[-1] if isinstance(outcomes[-1], dict) else {}
    status = str(latest.get('status') or '').strip().lower()
    if status in MEASURED_OUTCOME_STATUSES:
        return 'measured'
    if status == 'too_early':
        return 'awaiting_measurement'
    return 'recorded'


def decision_facts(user, thread_id, *, today=None, session_row=None):
    """Compact, code-built facts for one session's decision state, or None."""
    record = find_thread_record(user, thread_id)
    if record is None:
        return None
    today = (today or date.today()).isoformat()
    derived = option_dispositions(record, session=session_row)
    cards = _latest_cards_by_option(record)

    scenarios = None
    if session_row is not None:
        scenarios = getattr(session_row, 'scenarios_json', None)
    if scenarios is None:
        from .models import UserSession
        row = (
            UserSession.query.filter_by(session_id=str(record.thread_id))
            .order_by(UserSession.created_at.asc()).first()
        )
        scenarios = getattr(row, 'scenarios_json', None) if row is not None else None
    scenarios = scenarios if isinstance(scenarios, dict) else {}
    plans_by_card = scenarios.get('wbs_by_scorecard') if isinstance(scenarios.get('wbs_by_scorecard'), dict) else {}

    rows = (
        OptionDecision.query.filter_by(decision_record_id=str(record.id))
        .order_by(OptionDecision.decided_at.asc(), OptionDecision.created_at.asc()).all()
    )
    rows_by_option = {}
    for row in rows:
        rows_by_option.setdefault(str(row.option_key), []).append(row)

    signals = [signal for signal in decision_signals_for(record) if signal.retracted_at is None]
    signals_by_option = {}
    for signal in signals:
        signals_by_option.setdefault(signal.option_key, []).append(signal)

    options = []
    follow_up = []
    for option in derived['options']:
        key = option['option_key']
        card = cards.get(key) or {}
        history = rows_by_option.get(key, [])
        current = next((row for row in reversed(history) if row.superseded_at is None), None)
        outcomes = [item for row in history for item in (row.outcomes or []) if isinstance(item, dict)]
        lessons = [item for row in history for item in (row.lessons_learned or []) if isinstance(item, dict)]
        plans = [
            plan for plan_id, plan in plans_by_card.items()
            if str(plan_id) in set(option['plan_ids']) and isinstance(plan, dict)
        ]
        progress = _plan_progress(plans)
        option_signals = signals_by_option.get(key, [])
        disposition = {
            'state': option['state'],
            'still_evaluating': option['still_evaluating'],
            'source': option['state_source'],
            'since': option['state_since'],
        }
        if current is not None and current.user_quote:
            disposition['quote'] = _clip(current.user_quote)
        if current is not None and current.rationale:
            disposition['rationale'] = _clip(current.rationale)
        outcome_state = _outcome_state(outcomes)
        entry = {
            'option_key': key,
            'name': option['option_name'] or card.get('name'),
            'score': card.get('jaspen_score'),
            'band': card.get('score_category'),
            'disposition': disposition,
            'plan': progress,
            'signals': _signals_by_kind(option_signals),
            'success_measures': [
                {'signal_id': str(signal.id), 'content': _clip(signal.content),
                 'review_by': normalize_iso_date((signal.structured or {}).get('review_by'))}
                for signal in option_signals if signal.kind == 'success_measure'
            ],
            'outcome_state': outcome_state,
            'outcomes_count': len(outcomes),
            'lessons_count': len(lessons),
        }
        if outcomes:
            entry['latest_outcome'] = {
                'id': outcomes[-1].get('id'),
                'status': outcomes[-1].get('status'),
                'recorded_at': outcomes[-1].get('recorded_at'),
            }
        options.append(entry)

        measured = outcome_state == 'measured'
        due = sorted(review_by for review_by, _signal in _review_dates(option_signals) if review_by <= today)
        if due and not measured:
            follow_up.append({'kind': 'review_due', 'option_key': key, 'review_by': due[0]})
        if progress['status'] == 'complete' and not outcomes:
            follow_up.append({'kind': 'implementation_complete_without_outcome', 'option_key': key})
        # A plan built after the customer said not pursue or still evaluating:
        # the plan-created row supersedes their stated disposition.
        if current is not None and is_plan_decision_source(current.source) and current.supersedes_id:
            replaced = next((row for row in history if str(row.id) == str(current.supersedes_id)), None)
            if (
                replaced is not None
                and not is_plan_decision_source(replaced.source)
                and replaced.disposition in {DISPOSITION_NOT_PURSUE, DISPOSITION_STILL_EVALUATING}
            ):
                follow_up.append({
                    'kind': 'plan_conflicts_disposition',
                    'option_key': key,
                    'stated_disposition': replaced.disposition,
                    'stated_at': replaced.decided_at.isoformat() if replaced.decided_at else None,
                    'plan_decision_at': current.decided_at.isoformat() if current.decided_at else None,
                })

    decision_signals = signals_by_option.get(None, [])
    decision_outcomes = [item for item in (record.outcomes or []) if isinstance(item, dict)]
    decision_level = {
        'signals': _signals_by_kind(decision_signals),
        'outcome_state': _outcome_state(decision_outcomes),
        'outcomes_count': len(decision_outcomes),
        'lessons_count': len([item for item in (record.lessons_learned or []) if isinstance(item, dict)]),
    }
    decision_due = sorted(review_by for review_by, _signal in _review_dates(decision_signals) if review_by <= today)
    if decision_due and decision_level['outcome_state'] != 'measured':
        follow_up.append({'kind': 'review_due', 'option_key': None, 'review_by': decision_due[0]})

    return {
        'decision_record_id': str(record.id),
        'today': today,
        'options': options,
        'reconciliation': derived['reconciliation'],
        'decision_level': decision_level,
        'follow_up_facts': follow_up,
    }

