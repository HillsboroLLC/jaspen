# backend/app/decision_records.py
#
# Service layer for the canonical Decision Record (Constitution Art. 20-21;
# Framework §7.1). Assembles a permanent, human-readable record FROM the
# existing session + scenario stores without mutating either — the record is
# strictly additive infrastructure. See models_decision_record.py for schema
# and custody design.
#
# Lifecycle:  conversation → analysis (evidence/rubric/scorecards/
# recommendation/plan) → Decision Record (this module) → outcome tracking →
# lessons learned → [future: Library, pattern discovery, decision intelligence].

from datetime import datetime

from sqlalchemy.orm.attributes import flag_modified

from . import db
from .models_decision_record import (
    DecisionRecord,
    DECISION_RECORD_SCHEMA_VERSION,
    DECISION_RECORD_STATUSES,
    LIBRARY_CONSENT_LEVELS,
)

# Fields in `record` that are DERIVED from thread storage and safe to refresh.
# Human-owned fields (final_decision, outcomes, lessons_learned, consent) live
# on dedicated columns and are never touched by re-derivation.
_DERIVED_FIELDS = (
    'decision_statement', 'conversation_summary', 'evidence_summary',
    'objectives', 'rubric', 'alternatives', 'scorecards', 'scorecard_ids',
    'recommendation', 'confidence', 'execution_plan', 'attribution',
)
# NOT derived, deliberately: `human_decision` mirrors the human-owned
# final_decision column. Refreshing it from a re-derivation would reset a
# recorded human decision back to "none", which is the worst thing this
# module could do. It is reconciled FROM the column instead.


def _clip(text, limit=2000):
    text = str(text or '').strip()
    return text[:limit]


def canonical_context(actor, thread_id):
    """Resolve who OWNS this thread's record and who it is ATTRIBUTED to.

    Phases 1-2 made the organization the owner of a project and left user
    identity as attribution. A Decision Record is the durable artifact derived
    from that project, so it must follow the same rule, or two members
    completing the same decision would produce two competing records and a
    departure would orphan one of them.

    Returns ``(row, organization_id, attribution_user_id)``:

      * ``organization_id`` comes from the canonical session row, NOT from the
        actor's active organization -- otherwise a member whose active org has
        since changed would file the record under the wrong organization.
      * ``attribution_user_id`` is the project's creator, so a collaborator
        refreshing a record does not become its author.
    """
    from .models import User
    from .session_access import canonical_row

    if actor is None:
        return None, None, None

    row = canonical_row(actor, thread_id, include_archived=True)
    if row is None:
        # No resolvable project, so there is no organization to attribute the
        # record to. Return None rather than falling back to the actor's active
        # organization: guessing here would file a record under whichever
        # organization the member happened to be looking at. Assembly raises
        # LookupError immediately afterwards anyway.
        return None, None, str(actor.id)

    organization_id = row.organization_id
    attribution_user_id = str(row.created_by_user_id or row.user_id or actor.id)

    # The attributed user must still exist for the record's FK; fall back to
    # the actor rather than writing a dangling reference.
    if not User.query.get(attribution_user_id):
        attribution_user_id = str(actor.id)

    return row, organization_id, attribution_user_id


def _load_thread_sources(user_id, thread_id):
    """Read-only view over the two existing stores for one thread.

    `user_id` is the ATTRIBUTION identity (the project's creator), not
    necessarily the caller. Reading under a stable identity is what makes the
    assembled record identical no matter which member triggers a refresh --
    otherwise a collaborator would derive a record missing the owner's
    scorecards and scenario data.
    """
    # Local imports: routes modules import broadly at module load; deferring
    # avoids import cycles (same pattern strategy.py uses toward ai_agent).
    from .routes.sessions import load_user_sessions
    from .routes.strategy import _load_scenarios

    sessions = load_user_sessions(user_id) or {}
    session = None
    for key, value in (sessions.items() if isinstance(sessions, dict) else []):
        if not isinstance(value, dict):
            continue
        if str(value.get('session_id') or key) == str(thread_id) or str(key) == str(thread_id):
            session = value
            break

    all_scenarios = _load_scenarios(user_id) or {}
    thread_data = all_scenarios.get(thread_id)
    if not isinstance(thread_data, dict):
        thread_data = {}
    return session, thread_data


def _collect_peer_scorecards(session, thread_data, *, user_id=None, thread_id=None):
    """Every scored artifact for the thread as a FLAT PEER LIST.

    Deliberately erases the legacy baseline/variant hierarchy: the session's
    baseline result and each scenario-store result become equal entries. This
    is the peer-to-peer shape future capabilities consume (see
    docs/peer-scorecard-migration-audit.md for the legacy-model audit).
    """
    cards = []
    seen_ids = set()

    def _add(card):
        if not isinstance(card, dict):
            return
        if card.get('jaspen_score') is None and not card.get('dimensions'):
            return
        cid = str(card.get('analysis_id') or card.get('id') or '').strip()
        if cid and cid in seen_ids:
            return
        if cid:
            seen_ids.add(cid)
        dims = card.get('dimensions') if isinstance(card.get('dimensions'), dict) else {}
        # Cards persisted by the batch path don't carry data_confidence; derive
        # it with the engine's own function so the record and the UI can never
        # disagree (Art. 1/9: one implementation, displayed = computed).
        data_confidence = card.get('data_confidence')
        if data_confidence is None and dims:
            from .routes.strategy import _data_confidence_from_dimensions
            data_confidence = _data_confidence_from_dimensions(dims)
        cards.append({
            'id': cid or None,
            'name': str(card.get('project_name') or card.get('name') or card.get('label') or 'Option').strip(),
            'jaspen_score': card.get('jaspen_score'),
            'score_category': card.get('score_category'),
            'data_confidence': data_confidence,
            'dimensions': {
                key: {
                    'label': (dim or {}).get('label') or key,
                    'score': (dim or {}).get('score'),
                    'confidence': (dim or {}).get('confidence'),
                    'source': (dim or {}).get('source'),
                    'rationale': _clip((dim or {}).get('rationale'), 500),
                }
                for key, dim in dims.items() if isinstance(dim, dict)
            },
            'executive_summary': _clip(card.get('executive_summary')),
            'key_insights': card.get('key_insights') if isinstance(card.get('key_insights'), list) else [],
            'top_risks': card.get('top_risks') if isinstance(card.get('top_risks'), list) else [],
            'assumptions': card.get('assumptions') if isinstance(card.get('assumptions'), list) else [],
            'generated_at': card.get('timestamp') or card.get('createdAt'),
        })

    if user_id is not None and thread_id is not None:
        from .scorecards import collect_peer_scorecards
        for peer in collect_peer_scorecards(
            user_id,
            thread_id,
            legacy_session=session,
            legacy_thread_data=thread_data,
        ):
            _add(peer)
        return cards

    if isinstance(session, dict):
        result = session.get('result')
        if isinstance(result, dict):
            _add(result)
            for snap in (result.get('scorecard_snapshots') or []):
                _add(snap)

    scenarios = thread_data.get('scenarios')
    if isinstance(scenarios, dict):
        for scenario in scenarios.values():
            if isinstance(scenario, dict):
                _add(scenario.get('result'))

    return cards


def _summarize_conversation(session, max_turns=12):
    """Compact human-readable digest of the conversation (not a transcript)."""
    if not isinstance(session, dict):
        return ''
    history = session.get('chat_history')
    if not isinstance(history, list):
        return ''
    lines = []
    for msg in history[-max_turns:]:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get('role') or '').lower()
        content = str(msg.get('content') or msg.get('text') or '').strip()
        if not content or content.startswith('{'):
            continue
        speaker = 'User' if role in ('user', 'human') else 'Jaspen'
        lines.append(f'{speaker}: {_clip(content, 300)}')
    return '\n'.join(lines[-max_turns:])


def _summarize_evidence(cards):
    """Evidence summary derived from dimension confidence/source grades —
    honest by construction (Art. 11/12): reports what was graded, not prose."""
    counts = {'high': 0, 'medium': 0, 'low': 0, 'assumed': 0}
    sources = {}
    for card in cards:
        for dim in (card.get('dimensions') or {}).values():
            conf = str(dim.get('confidence') or '').lower()
            if conf in counts:
                counts[conf] += 1
            src = str(dim.get('source') or '').lower() or 'unspecified'
            sources[src] = sources.get(src, 0) + 1
    total = sum(counts.values())
    return {
        'dimension_confidence_counts': counts,
        'evidence_sources': sources,
        'graded_dimensions': total,
    }


def assemble_record_payload(user_id, thread_id, *, actor_user_id=None):
    """Derive the canonical Decision Record payload for a thread.

    `user_id` is the ATTRIBUTION identity -- the project's creator -- and is
    what the thread's sources and scorecards are read under, so the same
    evidence set is assembled no matter which member triggered the refresh.
    `actor_user_id` is whoever triggered it, recorded as a contributor.

    Returns (payload, promoted) where `promoted` carries values for the
    queryable columns. Raises LookupError when the thread has no analyzable
    content at all.
    """
    session, thread_data = _load_thread_sources(user_id, thread_id)
    if session is None and not thread_data:
        raise LookupError(f'No conversation or analysis found for thread {thread_id}')

    session = session if isinstance(session, dict) else {}
    cards = _collect_peer_scorecards(
        session,
        thread_data,
        user_id=user_id,
        thread_id=thread_id,
    )

    rubric = session.get('scoring_rubric') if isinstance(session.get('scoring_rubric'), dict) else None
    portfolio = session.get('portfolio_summary') if isinstance(session.get('portfolio_summary'), dict) else {}
    wbs = thread_data.get('project_wbs')
    objective = str(session.get('strategy_objective') or 'balanced')

    title = _clip(session.get('name') or f'Decision {thread_id}', 255) or 'Untitled decision'
    decision_statement = _clip(session.get('name'), 500)

    # Confidence: the honest aggregate — per-card data_confidence, never a
    # model-authored overall number (Art. 1: code does the math).
    confidences = [c.get('data_confidence') for c in cards if isinstance(c.get('data_confidence'), (int, float))]
    confidence = {
        'per_card': {c['name']: c.get('data_confidence') for c in cards},
        'mean': round(sum(confidences) / len(confidences), 1) if confidences else None,
    }

    payload = {
        'schema_version': DECISION_RECORD_SCHEMA_VERSION,
        'decision_statement': decision_statement,
        'decision_owner': str(user_id),
        'conversation_summary': _summarize_conversation(session),
        'evidence_summary': _summarize_evidence(cards),
        'objectives': {'strategy_objective': objective},
        'rubric': rubric,
        'alternatives': [c['name'] for c in cards],
        'scorecards': cards,                       # flat peer list, no baseline flag
        # Separately addressable evidence. The full cards stay above; this is
        # the stable-id index so a future retrieval layer can reference the
        # durable Scorecard rows without re-parsing the payload.
        'scorecard_ids': [c['id'] for c in cards if c.get('id')],

        # AI OUTPUT. Article 4: the human decides. This is the model's
        # recommendation and must never be read as the organization's
        # decision -- see `human_decision` below, which is the only place a
        # decision can live.
        'recommendation': _clip(portfolio.get('recommended_sequence'), 2000) or None,

        # HUMAN DECISION. Deliberately empty at derivation time: nothing in
        # the product currently captures a final human decision, so recording
        # one here would be an invention. `recorded: False` states that
        # absence explicitly rather than letting a reader infer that the
        # recommendation above was adopted. record_final_decision() is the only
        # writer, and it advances status to 'decided'.
        'human_decision': {
            'recorded': False,
            'decision': None,
            'decided_at': None,
            'decided_by_user_id': None,
        },

        'confidence': confidence,
        'execution_plan': wbs if isinstance(wbs, (dict, list)) else None,
        'attribution': {
            'created_by_user_id': str(user_id),
            'last_refreshed_by_user_id': str(actor_user_id or user_id),
            'last_refreshed_at': datetime.utcnow().isoformat(),
        },
        'derived_at': datetime.utcnow().isoformat(),
        'source': {'thread_id': thread_id},
    }
    promoted = {
        'title': title,
        'decision_statement': decision_statement or None,
    }
    return payload, promoted


def _find_existing_record(organization_id, attribution_user_id, thread_id):
    """The canonical record for this thread.

    Identity is (organization_id, thread_id) whenever the thread has an
    organization -- which, post-Phase-1, is every thread except a personal
    sentinel. Keying on (user_id, thread_id) as this used to would give each
    member of a team their own private record of the same decision, which is
    the exact fork Phase 1 removed at the session layer.

    The user-scoped lookup survives only as a fallback for a thread with no
    organization, and as a migration path: a record written under the old
    per-user identity is found and adopted rather than duplicated.
    """
    tid = str(thread_id)
    if organization_id:
        found = (
            DecisionRecord.query
            .filter_by(organization_id=str(organization_id), thread_id=tid)
            .order_by(DecisionRecord.created_at.asc())
            .first()
        )
        if found is not None:
            return found

    return (
        DecisionRecord.query
        .filter_by(user_id=str(attribution_user_id), thread_id=tid)
        .order_by(DecisionRecord.created_at.asc())
        .first()
    )


def create_or_refresh_record(user, thread_id):
    """One active record per thread. Creating twice refreshes the DERIVED
    analysis fields and never touches human-owned fields (final decision,
    outcomes, lessons, consent, advanced status)."""
    _row, organization_id, attribution_user_id = canonical_context(user, thread_id)
    attribution_user_id = attribution_user_id or str(user.id)

    payload, promoted = assemble_record_payload(
        attribution_user_id, thread_id, actor_user_id=user.id
    )

    existing = _find_existing_record(organization_id, attribution_user_id, thread_id)
    if existing:
        # Copy BEFORE mutating: mutating the loaded dict in place makes
        # SQLAlchemy's flush-time comparison see old == new and skip the
        # UPDATE entirely (the mutable-JSON trap). flag_modified is added as
        # belt-and-braces so the column is always written.
        record_json = {**(existing.record if isinstance(existing.record, dict) else {})}
        for field in _DERIVED_FIELDS:
            if field in payload:
                record_json[field] = payload[field]
        record_json['derived_at'] = payload['derived_at']
        record_json['schema_version'] = payload['schema_version']
        # Reconcile the human-decision block FROM the column, so a refresh can
        # neither invent a decision nor erase one that was recorded.
        record_json['human_decision'] = _human_decision_block(existing)
        existing.record = record_json
        flag_modified(existing, 'record')
        existing.title = promoted['title']
        if not existing.decision_statement:
            existing.decision_statement = promoted['decision_statement']
        # Only advance in_analysis → recorded; never regress a decided record.
        if existing.status == 'in_analysis' and payload.get('scorecards'):
            existing.status = 'recorded'
        existing.updated_at = datetime.utcnow()
        db.session.commit()
        return existing, False

    record = DecisionRecord(
        # ATTRIBUTION, not ownership: the project's creator, so a collaborator
        # completing the decision does not become its author.
        user_id=attribution_user_id,
        # OWNERSHIP: taken from the canonical session row rather than the
        # actor's active organization, which may since have changed.
        organization_id=organization_id,
        thread_id=str(thread_id),
        title=promoted['title'],
        decision_statement=promoted['decision_statement'],
        # 'recorded' means the analysis is captured. It is NOT 'decided':
        # advancing that far requires an actual human decision signal, which
        # only record_final_decision() supplies.
        status='recorded' if payload.get('scorecards') else 'in_analysis',
        record=payload,
    )
    db.session.add(record)
    db.session.commit()
    return record, True


def _human_decision_block(record):
    """The record's human-decision state, derived from its own columns."""
    decided = bool(record.final_decision)
    return {
        'recorded': decided,
        'decision': record.final_decision if decided else None,
        'decided_at': record.decided_at.isoformat() if decided and record.decided_at else None,
        'decided_by_user_id': (record.record or {}).get('human_decision', {}).get('decided_by_user_id')
        if isinstance(record.record, dict) else None,
    }


def record_final_decision(record, final_decision_text, decided_by_user_id=None):
    """Capture the FINAL HUMAN DECISION -- the only writer of that field.

    Article 4: the human decides. Nothing in the derivation path may call this;
    a model recommendation never becomes the organization's decision without a
    human signal passing through here.
    """
    record.final_decision = _clip(final_decision_text, 4000) or None
    if record.final_decision:
        record.status = 'decided'
        record.decided_at = datetime.utcnow()

    record_json = {**(record.record if isinstance(record.record, dict) else {})}
    block = _human_decision_block(record)
    if decided_by_user_id and record.final_decision:
        block['decided_by_user_id'] = str(decided_by_user_id)
    record_json['human_decision'] = block
    record.record = record_json
    flag_modified(record, 'record')

    record.updated_at = datetime.utcnow()
    db.session.commit()
    return record


def append_outcome(record, summary, extra=None):
    outcomes = list(record.outcomes or [])
    entry = {'summary': _clip(summary, 4000), 'recorded_at': datetime.utcnow().isoformat()}
    if isinstance(extra, dict):
        for key in ('went_with_recommendation', 'outcome_date', 'sentiment'):
            if key in extra:
                entry[key] = extra[key]
    outcomes.append(entry)
    record.outcomes = outcomes
    flag_modified(record, 'outcomes')
    record.status = 'outcome_recorded'
    record.outcome_recorded_at = datetime.utcnow()
    record.updated_at = datetime.utcnow()
    db.session.commit()
    return record


def append_lesson(record, lesson):
    lessons = list(record.lessons_learned or [])
    lessons.append({'lesson': _clip(lesson, 4000), 'recorded_at': datetime.utcnow().isoformat()})
    record.lessons_learned = lessons
    flag_modified(record, 'lessons_learned')
    record.updated_at = datetime.utcnow()
    db.session.commit()
    return record


def set_library_consent(record, level):
    """Ring 2 custody transition — an explicit, timestamped act (Art. 21)."""
    level = str(level or '').strip().lower()
    if level not in LIBRARY_CONSENT_LEVELS:
        raise ValueError(f'library consent must be one of {LIBRARY_CONSENT_LEVELS}')
    record.library_consent = level
    record.library_consented_at = datetime.utcnow() if level != 'none' else None
    record.updated_at = datetime.utcnow()
    db.session.commit()
    return record


def set_status(record, status):
    status = str(status or '').strip().lower()
    if status not in DECISION_RECORD_STATUSES:
        raise ValueError(f'status must be one of {DECISION_RECORD_STATUSES}')
    record.status = status
    record.updated_at = datetime.utcnow()
    db.session.commit()
    return record
