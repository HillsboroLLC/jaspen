"""P2d: one-time, idempotent legacy plan identifier backfill.

Before P2b, opening a plan repaired legacy plans as a side effect. P2b made
reads read-only, so stored data can still hold plans under a stale option id,
plans missing from Session Artifacts, and orphan execution-plan artifacts.
This job corrects the stored data once, so every plan lookup (workspace,
export, email, chat plan tools, Jira) resolves the same plan by the option's
own id. Specification: P2B_ACCEPTANCE_DEPENDENCIES_2026-11-13.md section 1.

Rules (each one is the existing product rule, reused, never a new one):

* Re-key: ``strategy._resolve_option_plan``, P2b's read rule. A plan under a
  stale key (no current option's id) whose generated content names an option
  that has no plan of its own moves to that option's id. When several stale
  plans name it, the most recently updated moves; the others stay and are
  reported. A plan under a current option's id is never touched. Nothing is
  ever deleted from ``wbs_by_scorecard``.
* Identity: ``strategy._apply_inferred_plan_identity``, the identity rule of
  P2a's plan read, applied to moved plans.
* Artifacts: ``strategy._with_execution_plan_artifact`` registers a missing
  execution_plan artifact for a current option's plan; an execution_plan
  artifact is removed only when its id has no plan after the re-key (P2a's
  orphan rule). An artifact of an option that has a plan is never removed.
* Writes: one canonical project per transaction through
  ``save_session_and_project_scenarios_data`` with compare-and-swap on the
  row revision. A row that changed during the job is skipped and reported. No
  row is ever created.

Dry run is the default. ``write=True`` writes, and records a before-image of
every changed row first (JSON lines); ``rollback_legacy_plans`` restores a
before-image only while the row is still at the job's after-revision.
"""

import copy
import hashlib
import json
import os
from datetime import datetime

from sqlalchemy.orm.attributes import flag_modified

from . import db
from .models import User, UserSession
from .session_access import RevisionConflict, SessionAccessError, can_write_session

JOB_NAME = 'p2d_legacy_plan_backfill'


# ---------------------------------------------------------------------------
# Reading one project
# ---------------------------------------------------------------------------

def _by_card(td):
    value = td.get('wbs_by_scorecard') if isinstance(td, dict) else None
    return value if isinstance(value, dict) else {}


def _history(payload):
    """The session's chat history, where Session Artifacts live."""
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get('chat_history'), list):
        return payload['chat_history']
    result = payload.get('result')
    if isinstance(result, dict) and isinstance(result.get('chat_history'), list):
        return result['chat_history']
    return None


def _plan_artifact_id(message):
    art = message.get('artifact') if isinstance(message, dict) else None
    if not isinstance(art, dict) or str(art.get('type') or '') != 'execution_plan':
        return None
    data = art.get('data') if isinstance(art.get('data'), dict) else {}
    return str(data.get('scorecard_id') or '').strip()


def _project_candidates(row, writer_id, payload, td):
    """This project's options, the same set P2b's read matches a legacy plan
    against (``strategy._thread_plan_candidates``), taken from the canonical
    project itself: the session's own cards, the project's indexed
    scorecards, and the scenario results."""
    from .routes.ai_agent import _collect_session_scorecards
    from .scorecards import collect_peer_scorecards

    inline = _collect_session_scorecards(payload)
    legacy = {'result': {**inline[0], 'scorecard_snapshots': inline[1:]}} if inline else {}
    candidates = list(collect_peer_scorecards(
        writer_id, str(row.session_id), legacy_session=legacy, project_row=row,
    ))
    for scenario in ((td or {}).get('scenarios') or {}).values():
        if isinstance(scenario, dict) and isinstance(scenario.get('result'), dict):
            candidates.append(scenario['result'])
    return candidates


def _eligible_writer(row, user):
    """True when ``user`` may write ``row`` now, decided without touching
    organization-access recording: for organization work an active
    membership with an editing role comes first (a former member never
    qualifies through authorship), then the shared write rule."""
    from .orgs import active_membership_for_user, can_edit_projects, normalize_org_role
    from .session_access import is_personal_session_id

    if user is None:
        return False
    membership = None
    if row.organization_id and not is_personal_session_id(row.session_id):
        membership = active_membership_for_user(row.organization_id, str(user.id))
        if membership is None or not can_edit_projects(normalize_org_role(membership.role)):
            return False
    return can_write_session(row, user, membership=membership)


def _writer_for(row):
    """The member the job writes as, under the current access rules.

    Organization work: its creator, else the organization's owner, else the
    row's home contributor, whoever is an active member with an editing role
    now. Personal work: its owner, else its creator. None when nobody
    qualifies; the job never widens anyone's access.
    """
    if row.organization_id:
        from .models import Organization

        org = db.session.get(Organization, row.organization_id)
        candidates = [row.created_by_user_id, getattr(org, 'owner_user_id', None), row.user_id]
    else:
        candidates = [row.user_id, row.created_by_user_id]
    seen = set()
    for user_id in candidates:
        if not user_id or str(user_id) in seen:
            continue
        seen.add(str(user_id))
        user = db.session.get(User, str(user_id))
        if _eligible_writer(row, user):
            return user
    return None


def _bound_plan_keys(row):
    """Plan keys that a Jira or Smartsheet binding of this project uses.

    A binding belongs to the project's thread and its owning organization
    (personal work: no organization and the project's own member).
    """
    from .models_pm_sync import PmSyncBinding

    query = PmSyncBinding.query.filter(PmSyncBinding.thread_id == str(row.session_id))
    if row.organization_id:
        query = query.filter(PmSyncBinding.organization_id == str(row.organization_id))
    else:
        owners = [str(u) for u in (row.user_id, row.created_by_user_id) if u]
        query = query.filter(
            PmSyncBinding.organization_id.is_(None), PmSyncBinding.user_id.in_(owners),
        )
    return {str(binding.plan_key or '').strip() for binding in query.all()} - {''}


def _is_canonical(row):
    from .session_access import canonical_row

    owner = db.session.get(User, str(row.user_id)) if row.user_id else None
    if owner is None:
        return False
    canonical = canonical_row(owner, row.session_id, include_archived=True)
    return canonical is not None and canonical.id == row.id


def _plan_row(row):
    """Compute what the job would change for one row. Writes nothing.

    Returns a dict: ``status`` (``unchanged``, ``change``, ``skipped``),
    ``changes`` and ``reported`` (ambiguous cases) for the report, and, for a
    change, the new ``scenarios_json`` and chat history.
    """
    from .routes.strategy import (
        _apply_inferred_plan_identity,
        _infer_plan_origin,
        _resolve_option_plan,
        _wbs_idea_identity,
        _with_execution_plan_artifact,
    )

    entry = {
        'row_id': row.id,
        'session_id': str(row.session_id),
        'organization_id': row.organization_id,
        'revision': int(row.revision or 1),
        'changes': [],
        'reported': [],
    }
    td = row.scenarios_json if isinstance(row.scenarios_json, dict) else {}
    payload = row.payload if isinstance(row.payload, dict) else {}
    by_card = _by_card(td)
    history = _history(payload)
    if not by_card:
        if isinstance(td.get('project_wbs'), dict):
            entry['reported'].append({
                'case': 'thread_level_plan_only',
                'detail': 'The project has only a thread-level plan and no per-option plans; not re-keyed.',
            })
        entry['status'] = 'unchanged'
        return entry

    if not _is_canonical(row):
        entry['status'] = 'skipped'
        entry['reported'].append({'case': 'not_canonical_row'})
        return entry
    writer = _writer_for(row)
    if writer is None:
        entry['status'] = 'skipped'
        entry['reported'].append({'case': 'no_member_may_write'})
        return entry
    entry['writer_user_id'] = str(writer.id)

    candidates = _project_candidates(row, str(writer.id), payload, td)
    live_ids = []
    for card in candidates:
        if isinstance(card, dict):
            card_id = str(_wbs_idea_identity(card)[0] or '').strip()
            if card_id and card_id not in live_ids:
                live_ids.append(card_id)

    new_td = copy.deepcopy(td)
    new_by_card = _by_card(new_td)
    bound_keys = _bound_plan_keys(row)
    moved = {}  # stale key -> option id
    held = {}  # stale key -> option id, kept because a sync binding uses it
    for option_id in live_ids:
        if option_id in by_card:
            continue
        stored_key, plan = _resolve_option_plan(td, option_id, candidates)
        if not stored_key or stored_key == option_id or not isinstance(plan, dict):
            continue
        if stored_key in bound_keys or option_id in bound_keys:
            # A binding reads and writes this plan through its own key (or
            # through the thread-level fallback for an option id with no
            # plan). Moving it would repoint the binding silently.
            held[stored_key] = option_id
            continue
        moved_plan = copy.deepcopy(plan)
        inferred_id, inferred_name = _infer_plan_origin(moved_plan, candidates)
        _apply_inferred_plan_identity(moved_plan, inferred_id, inferred_name)
        moved_plan['scorecard_id'] = option_id
        new_by_card.pop(stored_key, None)
        new_by_card[option_id] = moved_plan
        moved[stored_key] = option_id
        if str(new_td.get('active_execution_scorecard_id') or '').strip() == stored_key:
            new_td['active_execution_scorecard_id'] = option_id
        if new_td.get('project_wbs') == plan:
            new_td['project_wbs'] = copy.deepcopy(moved_plan)
        entry['changes'].append({
            'change': 'rekey',
            'from_key': stored_key,
            'to_option_id': option_id,
            'plan_name': moved_plan.get('name'),
            'option_name': moved_plan.get('scorecard_name'),
        })

    # Stale plans that stay where they are, with the reason.
    for stored_key, plan in by_card.items():
        if stored_key in live_ids or stored_key in moved or not isinstance(plan, dict):
            continue
        if stored_key in held:
            entry['reported'].append({
                'case': 'stale_plan_has_sync_binding', 'key': stored_key,
                'names_option_id': held[stored_key],
                'bound_plan_keys': sorted(k for k in (stored_key, held[stored_key]) if k in bound_keys),
            })
            continue
        inferred_id, inferred_name = _infer_plan_origin(plan, candidates)
        inferred_id = str(inferred_id or '').strip()
        if not inferred_id:
            case = 'stale_plan_names_no_option'
        elif inferred_id in by_card:
            case = 'stale_plan_option_has_its_own_plan'
        else:
            case = 'stale_plan_older_duplicate'
        entry['reported'].append({
            'case': case, 'key': stored_key, 'names_option_id': inferred_id or None,
            'option_name': inferred_name or None, 'updated_at': plan.get('updated_at'),
        })

    if new_by_card:
        new_td['wbs_by_scorecard'] = new_by_card

    # Session Artifacts.
    new_history = copy.deepcopy(history) if isinstance(history, list) else None
    if new_history is not None:
        now_iso = datetime.utcnow().isoformat()
        valid = {str(key).strip() for key in new_by_card if str(key).strip()}
        registered = {
            _plan_artifact_id(message) for message in new_history if _plan_artifact_id(message)
        }
        for key, plan in new_by_card.items():
            # Only an option's own plan is registered: a stale plan the job
            # could not attribute stays out of Session Artifacts and is
            # reported instead.
            if key not in live_ids or key in registered:
                continue
            if not isinstance(plan, dict) or not (plan.get('tasks') or []):
                continue
            artifact_plan = copy.deepcopy(plan)
            artifact_plan['scorecard_id'] = key
            candidate = _with_execution_plan_artifact(new_history, artifact_plan, now_iso)
            dropped = [m for m in new_history if not any(m is k for k in candidate)]
            if any(_plan_artifact_id(m) in valid for m in dropped):
                # Never drop the artifact of an option that has a plan, even
                # when its task list matches: append only.
                new_history = new_history + [candidate[-1]]
                dropped = []
            else:
                new_history = candidate
            for message in dropped:
                entry['changes'].append({
                    'change': 'remove_orphan_artifact', 'option_id': _plan_artifact_id(message),
                })
            registered.add(key)
            entry['changes'].append({'change': 'register_artifact', 'option_id': key})
        kept = []
        for message in new_history:
            artifact_id = _plan_artifact_id(message)
            if artifact_id and artifact_id not in valid:
                entry['changes'].append({'change': 'remove_orphan_artifact', 'option_id': artifact_id})
                continue
            kept.append(message)
        new_history = kept

    scenarios_changed = new_td != td
    history_changed = new_history is not None and new_history != history
    if not scenarios_changed and not history_changed:
        entry['changes'] = []
        entry['status'] = 'unchanged'
        return entry
    entry['status'] = 'change'
    entry['_expected'] = _fingerprint(row)
    entry['_scenarios'] = new_td if scenarios_changed else None
    entry['_history'] = new_history if history_changed else None
    return entry


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def _job_payload(history):
    """The job's payload change: the new chat history, mirrored into the
    result blob the way _register_execution_plan_artifact keeps them."""
    def apply(payload):
        payload['chat_history'] = history
        if isinstance(payload.get('result'), dict):
            payload['result']['chat_history'] = copy.deepcopy(history)
        return payload
    return apply


def _restore_payload(before):
    """Put back exactly the chat history copies the before-image recorded."""
    def apply(payload):
        for holder, key in ((payload, 'chat_history'), (payload.get('result'), 'chat_history')):
            if not isinstance(holder, dict):
                continue
            field = 'chat_history' if holder is payload else 'result_chat_history'
            value = before.get(field)
            if value is None:
                holder.pop(key, None)
            else:
                holder[key] = copy.deepcopy(value)
        return payload
    return apply


def _chat_views(payload):
    payload = payload if isinstance(payload, dict) else {}
    result = payload.get('result') if isinstance(payload.get('result'), dict) else {}
    return payload.get('chat_history'), result.get('chat_history')


def _fingerprint(row):
    """What the job reads and writes on a row: its plan data and the two
    chat-history copies. Comments, visibility, activity and every other
    payload field are not part of it, and are never written by the job."""
    blob = json.dumps(
        [row.scenarios_json if isinstance(row.scenarios_json, dict) else {}, *_chat_views(row.payload)],
        sort_keys=True, default=str,
    )
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


def _lock_row(row_id, expected_revision):
    """Lock one project row for this transaction and read it fresh.

    PostgreSQL: SELECT ... FOR UPDATE. SQLite has no row locks, so a no-op
    compare-and-swap UPDATE takes the database write lock first; both hold
    until commit or rollback. Returns the fresh row, or None when the row is
    gone or no longer at ``expected_revision``.
    """
    db.session.rollback()
    table = UserSession.__table__
    if db.session.get_bind().dialect.name != 'postgresql':
        claimed = db.session.execute(
            table.update()
            .where(table.c.id == row_id, table.c.revision == int(expected_revision))
            .values(revision=table.c.revision, updated_at=table.c.updated_at)
        ).rowcount
        if claimed != 1:
            db.session.rollback()
            return None
    row = (
        UserSession.query.filter(UserSession.id == row_id)
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if row is None or int(row.revision or 1) != int(expected_revision):
        db.session.rollback()
        return None
    return row


def _write_row(row_id, writer_id, expected_revision, expected_fingerprint, scenarios,
               payload_change=None):
    """One project, one transaction, compare-and-swap on the row revision.

    The row is locked and re-read first. It must still be at the revision
    the job planned from, and its plan data and chat history must be what
    the job planned from (a write that skips the revision, like a team
    comment, may have landed since). Only the chat-history copies change on
    the freshly read payload, so a teammate's comment, visibility or activity
    change is kept. Raises RevisionConflict, with nothing written, otherwise.
    Returns ``(new_revision, after_fingerprint)``.
    """
    from .scenarios_store import ScenariosData, save_session_and_project_scenarios_data

    row = _lock_row(row_id, expected_revision)
    if row is None or (expected_fingerprint is not None and _fingerprint(row) != expected_fingerprint):
        db.session.rollback()
        raise RevisionConflict(expected_revision, None)
    sid = str(row.session_id)
    source = ScenariosData()
    source[sid] = copy.deepcopy(row.scenarios_json if isinstance(row.scenarios_json, dict) else {})
    source.remember(sid, row)
    if payload_change is not None:
        payload = copy.deepcopy(row.payload) if isinstance(row.payload, dict) else {}
        row.payload = payload_change(payload)
        flag_modified(row, 'payload')
    target = scenarios if scenarios is not None else copy.deepcopy(source[sid])
    new_revision = save_session_and_project_scenarios_data(
        writer_id, sid, source=source, base_revision=expected_revision,
        updater=lambda _current: copy.deepcopy(target),
    )
    written = db.session.get(UserSession, row_id)
    return int(new_revision), _fingerprint(written)


def _append(handle, record):
    handle.write(json.dumps(record, sort_keys=True, default=str) + '\n')
    handle.flush()
    os.fsync(handle.fileno())


def _public(entry):
    return {key: value for key, value in entry.items() if not key.startswith('_')}


def _rows(organization_id=None, session_ids=None):
    query = UserSession.query
    if organization_id:
        query = query.filter(UserSession.organization_id == str(organization_id))
    if session_ids:
        query = query.filter(UserSession.session_id.in_([str(s) for s in session_ids]))
    return [row.id for row in query.order_by(UserSession.id.asc()).all()]


def backfill_legacy_plans(*, write=False, organization_id=None, before_image_path=None,
                          session_ids=None):
    """Run the job. Dry run unless ``write``; returns the report.

    A write run needs ``before_image_path``, a file that does not exist yet.
    """
    if write:
        if not before_image_path:
            raise ValueError('A write run needs a before-image file path.')
        if os.path.exists(before_image_path):
            raise ValueError('The before-image file already exists; choose a new path.')

    report = {
        'job': JOB_NAME,
        'mode': 'write' if write else 'dry_run',
        'organization_id': organization_id,
        'started_at': datetime.utcnow().isoformat(),
        'before_image_path': before_image_path if write else None,
        'counts': {
            'rows_scanned': 0, 'rows_changed': 0, 'rows_unchanged': 0,
            'rows_skipped': 0, 'rows_conflicted': 0, 'rekeys': 0,
            'artifacts_registered': 0, 'orphan_artifacts_removed': 0,
            'cases_reported': 0,
        },
        'projects': [],
    }
    counts = report['counts']
    handle = open(before_image_path, 'x', encoding='utf-8') if write else None
    try:
        for row_id in _rows(organization_id, session_ids):
            db.session.rollback()
            row = db.session.get(UserSession, row_id)
            if row is None:
                continue
            counts['rows_scanned'] += 1
            entry = _plan_row(row)
            counts['cases_reported'] += len(entry['reported'])
            if entry['status'] == 'unchanged':
                counts['rows_unchanged'] += 1
                if entry['reported']:
                    report['projects'].append(_public(entry))
                continue
            if entry['status'] == 'skipped':
                counts['rows_skipped'] += 1
                report['projects'].append(_public(entry))
                continue
            kinds = [c['change'] for c in entry['changes']]
            if write:
                before = {
                    'type': 'before', 'job': JOB_NAME, 'row_id': row.id,
                    'session_id': str(row.session_id), 'organization_id': row.organization_id,
                    'revision': entry['revision'], 'after_revision': entry['revision'] + 1,
                    'writer_user_id': entry['writer_user_id'],
                    'scenarios_json': row.scenarios_json,
                    'chat_history': (row.payload or {}).get('chat_history'),
                    'result_chat_history': (((row.payload or {}).get('result') or {}).get('chat_history')
                                            if isinstance((row.payload or {}).get('result'), dict) else None),
                }
                _append(handle, before)
                try:
                    new_revision, after_fingerprint = _write_row(
                        before['row_id'], entry['writer_user_id'], entry['revision'],
                        entry['_expected'], entry['_scenarios'],
                        _job_payload(entry['_history']) if entry['_history'] is not None else None,
                    )
                except RevisionConflict:
                    db.session.rollback()
                    counts['rows_conflicted'] += 1
                    entry['status'] = 'skipped'
                    entry['reported'].append({'case': 'changed_during_job'})
                    counts['cases_reported'] += 1
                    _append(handle, {'type': 'not_written', 'row_id': before['row_id'],
                                     'reason': 'changed_during_job'})
                    report['projects'].append(_public(entry))
                    continue
                except SessionAccessError as exc:
                    db.session.rollback()
                    counts['rows_skipped'] += 1
                    entry['status'] = 'skipped'
                    entry['reported'].append({'case': 'write_refused', 'detail': type(exc).__name__})
                    counts['cases_reported'] += 1
                    _append(handle, {'type': 'not_written', 'row_id': before['row_id'],
                                     'reason': 'write_refused'})
                    report['projects'].append(_public(entry))
                    continue
                _append(handle, {'type': 'committed', 'row_id': before['row_id'],
                                 'after_revision': int(new_revision),
                                 'after_fingerprint': after_fingerprint})
                entry['status'] = 'written'
                entry['after_revision'] = int(new_revision)
            counts['rows_changed'] += 1
            counts['rekeys'] += kinds.count('rekey')
            counts['artifacts_registered'] += kinds.count('register_artifact')
            counts['orphan_artifacts_removed'] += kinds.count('remove_orphan_artifact')
            report['projects'].append(_public(entry))
    finally:
        db.session.rollback()
        if handle is not None:
            handle.close()
    report['finished_at'] = datetime.utcnow().isoformat()
    return report


def rollback_legacy_plans(before_image_path, *, write=False):
    """Restore before-images whose row is still at the job's after-revision.

    Rows edited since, and rows the job never committed, are reported for
    manual review and never overwritten. Dry run unless ``write``.
    """
    befores, committed, fingerprints = {}, {}, {}
    with open(before_image_path, encoding='utf-8') as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get('type') == 'before':
                befores[record['row_id']] = record
            elif record.get('type') == 'committed':
                committed[record['row_id']] = int(record['after_revision'])
                fingerprints[record['row_id']] = record.get('after_fingerprint')

    report = {
        'job': JOB_NAME, 'mode': 'rollback_write' if write else 'rollback_dry_run',
        'before_image_path': before_image_path,
        'restored': [], 'would_restore': [], 'edited_since': [], 'not_committed': [],
        'missing_rows': [], 'refused': [],
    }
    try:
        for row_id, before in befores.items():
            db.session.rollback()
            if row_id not in committed:
                report['not_committed'].append(row_id)
                continue
            row = db.session.get(UserSession, row_id)
            if row is None:
                report['missing_rows'].append(row_id)
                continue
            after = committed[row_id]
            changed_since = int(row.revision or 1) != after or (
                fingerprints.get(row_id) is not None and _fingerprint(row) != fingerprints[row_id]
            )
            if changed_since:
                report['edited_since'].append({'row_id': row_id, 'revision': int(row.revision or 1),
                                               'job_after_revision': after})
                continue
            if not write:
                report['would_restore'].append(row_id)
                continue
            writer = _writer_for(row)
            if writer is None:
                report['refused'].append({'row_id': row_id, 'reason': 'no_member_may_write'})
                continue
            try:
                _write_row(
                    row_id, str(writer.id), after, fingerprints.get(row_id),
                    before.get('scenarios_json') or {}, _restore_payload(before),
                )
            except RevisionConflict:
                db.session.rollback()
                report['edited_since'].append({'row_id': row_id, 'job_after_revision': after})
                continue
            except SessionAccessError as exc:
                db.session.rollback()
                report['refused'].append({'row_id': row_id, 'reason': type(exc).__name__})
                continue
            report['restored'].append(row_id)
    finally:
        db.session.rollback()
    return report
