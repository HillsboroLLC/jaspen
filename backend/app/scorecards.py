"""Canonical standalone peer-scorecard persistence and legacy compatibility."""

from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import current_app

from . import db, org_access
from .models import Scorecard, User, UserSession
from .session_access import can_read_session


COMPARISON_SESSION_PROJECT_LIMIT = 30
COMPARISON_SESSION_LIMIT_MESSAGE = (
    'This comparison session supports up to 30 projects. Start a new session to continue '
    'evaluating additional projects. Your existing scorecards remain saved and accessible.'
)
SCORECARD_VIEW_LIMITS = {
    plan_key: COMPARISON_SESSION_PROJECT_LIMIT
    for plan_key in ('free', 'starter', 'essential', 'team', 'business', 'enterprise_custom')
}
FOUNDER_VIEW_LIMIT = COMPARISON_SESSION_PROJECT_LIMIT


def _score_value(payload):
    for key in ('jaspen_score', 'overall_score', 'score'):
        try:
            value = Decimal(str(payload.get(key)))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if value.is_finite():
            return value
    return None


def _project_name(payload):
    return str(
        payload.get('project_name')
        or payload.get('name')
        or payload.get('title')
        or 'Untitled scorecard'
    ).strip() or 'Untitled scorecard'


def upsert_scorecard(
    *,
    user_id,
    thread_id,
    payload,
    organization_id=None,
    session_id=None,
    evaluation_id=None,
    source='native',
    analysis_pass=False,
):
    """Persist one scorecard.

    `analysis_pass` says this write is a genuine analytical scoring pass rather
    than a rename, an in-place prose edit, a display override, or a backfill.
    Only a scoring pass may produce challenge-ledger entries.

    It defaults to False on purpose. Ten call sites reach this function and
    only three of them are analysis; a default of True would quietly turn
    every backfill and every cosmetic edit into evidence of intellectual work,
    which is precisely the inflation the ledger exists to avoid. A caller that
    forgets to pass it under-reports, which is the safe direction.
    """
    if not isinstance(payload, dict):
        raise ValueError('scorecard payload must be an object')
    scorecard_id = str(payload.get('id') or payload.get('analysis_id') or '').strip()
    if not scorecard_id:
        raise ValueError('scorecard payload requires a stable id')
    row = Scorecard.query.filter_by(id=scorecard_id, user_id=str(user_id)).first()
    # The previously persisted payload, read BEFORE anything overwrites it.
    # Without this snapshot there is no "before" to compare a grade against.
    previous = dict(row.data) if row is not None and isinstance(row.data, dict) else {}
    if row is None:
        row = Scorecard(id=scorecard_id, user_id=str(user_id))
        db.session.add(row)
    row.organization_id = organization_id
    row.thread_id = str(thread_id)
    row.session_id = str(session_id or thread_id)
    if evaluation_id:
        row.evaluation_id = str(evaluation_id)
    elif not row.evaluation_id:
        row.evaluation_id = str(payload.get('evaluation_id') or '').strip() or None
    row.project_name = _project_name(payload)
    row.rubric = payload.get('scoring_rubric') or payload.get('rubric') or {}
    row.evidence = payload.get('evidence') or payload.get('evidence_items') or []
    row.score = _score_value(payload)
    row.assumptions = payload.get('assumptions') or []
    row.recommendation = payload.get('recommendation') or payload.get('recommendations')
    row.execution_plan_ref = payload.get('execution_plan_ref')
    if 'decision_fingerprint' in payload:
        row.decision_fingerprint = str(payload.get('decision_fingerprint') or '').strip() or None
    if 'decision_state_reusable' in payload:
        row.decision_state_reusable = bool(payload.get('decision_state_reusable') is True)
    reuse = payload.get('reuse_provenance') if isinstance(payload.get('reuse_provenance'), dict) else {}
    if reuse or 'reused_source_scorecard_id' in payload:
        row.reused_from_scorecard_id = str(
            reuse.get('source_scorecard_id') or payload.get('reused_source_scorecard_id') or ''
        ).strip() or None
        row.reuse_root_scorecard_id = str(
            reuse.get('root_scorecard_id') or row.reused_from_scorecard_id or ''
        ).strip() or None
    normalized = dict(payload)
    normalized['id'] = scorecard_id
    normalized['analysis_id'] = scorecard_id
    normalized['thread_id'] = str(thread_id)
    normalized['project_name'] = row.project_name
    normalized['evaluation_id'] = row.evaluation_id
    normalized['isBaseline'] = False
    normalized['is_baseline'] = False
    normalized.pop('delta_vs_baseline', None)
    row.data = normalized
    row.search_metadata = {
        'project_name': row.project_name,
        'thread_id': str(thread_id),
        'rubric_keys': [
            str(item.get('key') or item.get('id') or item.get('label') or '').strip()
            for item in ((row.rubric or {}).get('criteria') or [])
            if isinstance(item, dict)
        ],
    }
    row.source = source
    row.archived_at = None

    # Emitted here because this is the only point holding BOTH the dimensions
    # that were persisted and the ones replacing them — `previous` is captured
    # above, before row.data is overwritten. A grade transition is invisible
    # anywhere else.
    #
    # Never allowed to break a save: a decision the user is waiting on outranks
    # a ledger row, and an absent event only ever costs Jaspen credit.
    if analysis_pass:
        try:
            from .decision_ledger import record_scoring_pass
            record_scoring_pass(
                user_id=user_id,
                thread_id=thread_id,
                scorecard_id=scorecard_id,
                previous_payload=previous,
                new_payload=normalized,
                organization_id=organization_id,
            )
        except Exception:  # noqa: BLE001 — see above
            current_app.logger.warning(
                'decision_ledger: could not record scoring pass for %s', scorecard_id,
                exc_info=True,
            )
    return row


def list_scorecard_rows(user_id, *, thread_id=None, include_archived=False):
    query = Scorecard.query.filter_by(user_id=str(user_id))
    if thread_id is not None:
        query = query.filter_by(thread_id=str(thread_id))
    if not include_archived:
        query = query.filter(Scorecard.archived_at.is_(None))
    rows = query.order_by(Scorecard.created_at.asc(), Scorecard.id.asc()).all()
    # Scorecards this user scored inside an organization they have since left.
    return org_access.gate_rows(rows, user_id, path='list_scorecards', resource_type='scorecard')


def _source_session_for_scorecard(row):
    session_id = str(row.session_id or row.thread_id or '').strip()
    if not session_id:
        return None
    query = UserSession.query.filter_by(session_id=session_id)
    if row.organization_id:
        query = query.filter_by(organization_id=str(row.organization_id))
    else:
        query = query.filter_by(user_id=str(row.user_id))
    return query.order_by(UserSession.created_at.asc(), UserSession.id.asc()).first()


def _can_reuse_scorecard(row, actor):
    if actor is None:
        return False
    source_session = _source_session_for_scorecard(row)
    if source_session is None:
        # Legacy personal scorecards may predate durable UserSession rows. They
        # remain reusable by their owner, never by a teammate, and never once
        # the owner has left the organization that holds them.
        return str(row.user_id) == str(actor.id) and org_access.allow(
            row.organization_id, actor.id,
            path='scorecard_reuse', resource_type='scorecard', resource_id=row.id,
        )
    return can_read_session(source_session, actor)


def find_scorecard_by_fingerprint(user_id, fingerprint, *, organization_id=None):
    """Find a reusable canonical judgment within its declared custody ring."""
    fingerprint = str(fingerprint or "").strip()
    if not fingerprint:
        return None
    actor = User.query.get(str(user_id))
    filters = {
        'decision_fingerprint': fingerprint,
        'decision_state_reusable': True,
        'archived_at': None,
    }
    if organization_id:
        query = Scorecard.query.filter_by(organization_id=str(organization_id), **filters)
    else:
        query = Scorecard.query.filter_by(user_id=str(user_id), **filters)
    # The exact indexed predicate keeps this bounded without imposing an
    # arbitrary result cap that could hide an older accessible source behind
    # many private cards with the same state.
    for row in query.order_by(Scorecard.updated_at.desc()).all():
        if _can_reuse_scorecard(row, actor):
            return row
    return None


def reuse_provenance(source_row):
    """Immutable source metadata for a newly persisted reused scorecard."""
    root_id = str(source_row.reuse_root_scorecard_id or source_row.id)
    root = Scorecard.query.filter_by(id=root_id).first() or source_row
    author = User.query.get(str(root.user_id))
    return {
        'source_scorecard_id': str(source_row.id),
        'root_scorecard_id': str(root.id),
        'source_session_id': str(root.session_id or root.thread_id or ''),
        'source_user_id': str(root.user_id),
        'source_user_name': str(getattr(author, 'name', '') or '').strip() or None,
        'source_created_at': root.created_at.isoformat() if root.created_at else None,
        'reused_at': datetime.utcnow().isoformat(),
    }


def _legacy_scorecards(session, thread_data, thread_id):
    candidates = []
    session = session if isinstance(session, dict) else {}
    result = session.get('result') if isinstance(session.get('result'), dict) else None
    if result:
        baseline = result.get('_baseline_scorecard') if isinstance(result.get('_baseline_scorecard'), dict) else result
        candidates.append(baseline)
        for item in result.get('scorecard_snapshots') or []:
            if isinstance(item, dict):
                candidates.append(item)
    thread_data = thread_data if isinstance(thread_data, dict) else {}
    if not candidates and isinstance(thread_data.get('baseline'), dict):
        candidates.append(thread_data['baseline'])
    scenarios = thread_data.get('scenarios') if isinstance(thread_data.get('scenarios'), dict) else {}
    for scenario_id, scenario in scenarios.items():
        if not isinstance(scenario, dict) or not isinstance(scenario.get('result'), dict):
            continue
        payload = dict(scenario['result'])
        payload.setdefault('id', str(scenario_id))
        payload.setdefault('analysis_id', str(scenario_id))
        payload.setdefault('project_name', scenario.get('label'))
        candidates.append(payload)
    peers = []
    seen = set()
    for index, item in enumerate(candidates):
        if not isinstance(item, dict):
            continue
        payload = dict(item)
        item_id = str(payload.get('id') or payload.get('analysis_id') or (thread_id if index == 0 else '')).strip()
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        payload['id'] = item_id
        payload['analysis_id'] = item_id
        payload['thread_id'] = str(thread_id)
        payload['project_name'] = _project_name(payload)
        payload['isBaseline'] = False
        payload['is_baseline'] = False
        payload.pop('delta_vs_baseline', None)
        peers.append(payload)
    return peers


def collect_peer_scorecards(user_id, thread_id, *, legacy_session=None, legacy_thread_data=None):
    """Return native peers plus non-duplicated legacy fallback, honoring tombstones."""
    rows = list_scorecard_rows(user_id, thread_id=thread_id, include_archived=True)
    archived_ids = {row.id for row in rows if row.archived_at is not None}
    peers = [row.to_peer_dict() for row in rows if row.archived_at is None]
    seen = {str(item.get('id')) for item in peers}
    for payload in _legacy_scorecards(legacy_session, legacy_thread_data, thread_id):
        item_id = str(payload.get('id'))
        if item_id in seen or item_id in archived_ids:
            continue
        peers.append(payload)
        seen.add(item_id)
    return peers


def backfill_legacy_scorecards(
    *,
    user_id,
    thread_id,
    legacy_session=None,
    legacy_thread_data=None,
    organization_id=None,
):
    created = 0
    for payload in _legacy_scorecards(legacy_session, legacy_thread_data, thread_id):
        if Scorecard.query.filter_by(id=str(payload['id']), user_id=str(user_id)).first():
            continue
        upsert_scorecard(
            user_id=user_id,
            thread_id=thread_id,
            payload=payload,
            organization_id=organization_id,
            source='legacy_backfill',
        )
        created += 1
    return created


def archive_scorecard(user_id, scorecard_id, *, legacy_payload=None, thread_id=None):
    row = Scorecard.query.filter_by(id=str(scorecard_id), user_id=str(user_id)).first()
    if row is None and isinstance(legacy_payload, dict) and thread_id:
        row = upsert_scorecard(
            user_id=user_id,
            thread_id=thread_id,
            payload=legacy_payload,
            source='legacy_tombstone',
        )
    if row is None:
        return False
    row.archived_at = datetime.utcnow()
    return True


def archive_thread_scorecards(user_id, thread_id):
    now = datetime.utcnow()
    rows = Scorecard.query.filter_by(
        user_id=str(user_id),
        thread_id=str(thread_id),
        archived_at=None,
    ).all()
    for row in rows:
        row.archived_at = now
    return len(rows)


def delete_thread_scorecards(user_id, thread_id):
    return Scorecard.query.filter_by(
        user_id=str(user_id),
        thread_id=str(thread_id),
    ).delete(synchronize_session=False)


def scorecard_limit_for(user, plan_key):
    from .founder_entitlements import has_founder_entitlement
    if has_founder_entitlement(user):
        return FOUNDER_VIEW_LIMIT
    return SCORECARD_VIEW_LIMITS.get(str(plan_key or 'free'), SCORECARD_VIEW_LIMITS['free'])


def scorecard_capacity(user, thread_id, plan_key):
    limit = scorecard_limit_for(user, plan_key)
    current = Scorecard.query.filter_by(
        user_id=str(user.id),
        thread_id=str(thread_id),
        archived_at=None,
    ).count()
    return {'limit': limit, 'current': current, 'available': max(0, limit - current)}
