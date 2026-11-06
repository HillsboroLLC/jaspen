"""Canonical append-only task changes and commitment signals."""

from datetime import datetime


TRACKED_TASK_FIELDS = ('due_date', 'start_date', 'status', 'owner', 'owner_email', 'title')
TASK_CHANGE_SOURCES = frozenset({
    'generation', 'person', 'ai_tool', 'schedule_shift', 'jira', 'smartsheet',
    'regeneration',
})
COMMITMENT_BASES = frozenset({'pm_sync', 'person_set', 'person_confirmed', 'user_stated'})


def _clean(value):
    if isinstance(value, str):
        return value.strip() or None
    return value


def _stamp(value=None):
    return value or datetime.utcnow().isoformat()


def commit_task(task, *, basis, ref=None, at=None):
    if basis not in COMMITMENT_BASES:
        raise ValueError('invalid task commitment basis')
    if isinstance(task.get('commitment'), dict):
        return task['commitment']
    task['commitment'] = {
        'due_date': _clean(task.get('due_date')),
        'committed_at': _stamp(at),
        'basis': basis,
        'ref': ref,
    }
    return task['commitment']


def confirm_task_commitment(task, *, user_quote, actor_user_id=None, at=None):
    quote = str(user_quote or '').strip()
    if not quote:
        raise ValueError('a verified user quote is required')
    return commit_task(task, basis='person_confirmed', ref=quote, at=at)


def commit_task_from_stated_date(task, *, signal_id, due_date, at=None):
    """Commit a date that a verified customer decision signal established."""
    signal_ref = str(signal_id or '').strip()
    stated_due_date = _clean(due_date)
    if not signal_ref:
        raise ValueError('a decision signal id is required')
    if not stated_due_date:
        raise ValueError('a customer-stated due date is required')
    if isinstance(task.get('commitment'), dict):
        return task['commitment']
    task['commitment'] = {
        'due_date': stated_due_date,
        'committed_at': _stamp(at),
        'basis': 'user_stated',
        'ref': signal_ref,
    }
    return task['commitment']


def record_task_changes(
    task, prior=None, *, source, actor_user_id=None, at=None,
    commit_on_person_change=False,
):
    if source not in TASK_CHANGE_SOURCES:
        raise ValueError('invalid task history source')
    prior = prior if isinstance(prior, dict) else {}
    at = _stamp(at)
    history = list(prior.get('history') or task.get('history') or [])
    changed = []
    for field in TRACKED_TASK_FIELDS:
        before = _clean(prior.get(field))
        after = _clean(task.get(field))
        if before == after:
            continue
        history.append({
            'field': field,
            'from': before,
            'to': after,
            'at': at,
            'actor_user_id': str(actor_user_id) if actor_user_id else None,
            'source': source,
        })
        changed.append(field)
    task['history'] = history
    if isinstance(prior.get('commitment'), dict):
        task['commitment'] = dict(prior['commitment'])
    else:
        task.setdefault('commitment', None)

    if commit_on_person_change and {'due_date', 'owner', 'owner_email'}.intersection(changed):
        commit_task(task, basis='person_set', at=at)
    if task.get('commitment') and 'due_date' in changed:
        commitment = dict(task['commitment'])
        commitment['rescheduled_to'] = _clean(task.get('due_date'))
        commitment['rescheduled_at'] = at
        task['commitment'] = commitment
    return task


def mark_task_pm_synced(task, *, connector_id, external_ref=None, at=None):
    basis_ref = external_ref or connector_id
    return commit_task(task, basis='pm_sync', ref=basis_ref, at=at)
