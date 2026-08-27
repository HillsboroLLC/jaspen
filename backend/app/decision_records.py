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

import uuid
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
    'recommendation', 'confidence', 'execution_plan', 'attribution', 'source',
)
# NOT derived, deliberately: `human_decision` mirrors the human-owned
# final_decision column. Refreshing it from a re-derivation would reset a
# recorded human decision back to "none", which is the worst thing this
# module could do. It is reconciled FROM the column instead.


def _clip(text, limit=2000):
    text = str(text or '').strip()
    return text[:limit]


def _display_name_for(user_id):
    from .models import User
    user = User.query.get(str(user_id)) if user_id else None
    if user is None:
        return None
    return str(getattr(user, 'name', None) or getattr(user, 'email', None) or '').strip() or None


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
            # Name snapshot so authorship survives the FK being nulled when a
            # person leaves. The record stays attributable; only the live link
            # to a user row goes away.
            'created_by_name': _display_name_for(user_id),
            'last_refreshed_by_user_id': str(actor_user_id or user_id),
            'last_refreshed_at': datetime.utcnow().isoformat(),
        },
        'derived_at': datetime.utcnow().isoformat(),
        'source': {
            'thread_id': thread_id,
            # Visibility SNAPSHOT of the project this was derived from. A
            # Decision Record is durable and outlives its session, so once the
            # project is purged there is no live visibility signal left to
            # authorize against. Snapshotting it here keeps the fallback
            # principled instead of guessing -- see can_read_record().
            'visibility': str((session or {}).get('visibility') or 'private').strip().lower(),
            'shared_with_user_ids': [
                str(uid) for uid in ((session or {}).get('shared_with_user_ids') or [])
                if str(uid or '').strip()
            ],
        },
    }
    promoted = {
        'title': title,
        'decision_statement': decision_statement or None,
    }
    return payload, promoted


def can_read_record(record, user, membership=None):
    """May this user read this Decision Record?

    A record is a durable artifact DERIVED from a project, so it inherits that
    project's access rules rather than inventing its own. This is an adapter
    over the session chokepoint in app/session_access.py -- deliberately not a
    second authorization system.

    Two cases:

      * The project still exists -> defer entirely to can_read_session(), so
        record access and project access can never disagree.
      * The project has been purged (records outlive their sessions, which is
        the point of them) -> fall back to the visibility SNAPSHOT taken at
        derivation time, applying the same private/team/specific rules.

    Organization membership is required first in both cases, so a stale
    organization_id cannot leak a record to someone who has since been removed.
    """
    from .models import UserSession  # noqa: F401  (documents the relationship)
    from .orgs import active_membership_for_user
    from .session_access import can_read_session, canonical_row

    if record is None or user is None:
        return False

    uid = str(user.id)
    org_id = getattr(record, 'organization_id', None)

    # A record with no organization is personal-scope: attribution decides.
    if not org_id:
        return str(record.user_id or '') == uid

    if membership is None:
        membership = active_membership_for_user(org_id, uid)
    if membership is None:
        return False

    row = canonical_row(user, record.thread_id, include_archived=True)
    if row is not None:
        return can_read_session(row, user, membership=membership)

    # Project gone: use the snapshot.
    payload = record.record if isinstance(record.record, dict) else {}
    source = payload.get('source') if isinstance(payload.get('source'), dict) else {}
    visibility = str(source.get('visibility') or 'private').strip().lower()

    if str(record.user_id or '') == uid:
        return True
    if visibility == 'team':
        return True
    if visibility == 'specific':
        shared = source.get('shared_with_user_ids')
        shared = shared if isinstance(shared, list) else []
        return uid in {str(item or '').strip() for item in shared}
    return False


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


# ─────────────────────────────────────────────────────────────────────────────
# Outcomes and lessons (Phase 6)
#
# OUTCOME is what happened. LESSON is what the organization concluded from what
# happened. They are kept structurally separate on purpose: collapsing them
# into one "retrospective" blob loses the distinction between observation and
# judgement, and it is the judgement that is reusable across future decisions.
#
# Both are HUMAN-AUTHORED. Nothing derives them. A project completing is not a
# successful outcome, and a model's recommendation is not a lesson -- neither
# may ever be written here without a person submitting it.
#
# Both are APPEND-ONLY sequences, which the original implementation already got
# right. A later observation never overwrites an earlier one, so the record
# shows how understanding developed rather than only its latest state.
# ─────────────────────────────────────────────────────────────────────────────

OUTCOME_STATUSES = (
    'achieved', 'partially_achieved', 'not_achieved', 'too_early', 'abandoned',
)


def _entry_id(prefix):
    return f'{prefix}_{uuid.uuid4().hex[:12]}'


def _actor_name(actor):
    return str(getattr(actor, 'name', None) or getattr(actor, 'email', None) or '').strip() or None


def _evidence_refs(value):
    """Stable ids only. Never the source documents themselves."""
    if not isinstance(value, list):
        return []
    out = []
    for item in value[:24]:
        ref = str(item or '').strip()
        if ref:
            out.append(ref[:128])
    return out


def _metrics(value):
    """User-supplied measurements, kept as given. Nothing is computed here."""
    if not isinstance(value, list):
        return []
    out = []
    for item in value[:24]:
        if not isinstance(item, dict):
            continue
        label = str(item.get('label') or '').strip()
        if not label:
            continue
        out.append({
            'label': label[:120],
            'value': str(item.get('value') or '').strip()[:120] or None,
            'expected': str(item.get('expected') or '').strip()[:120] or None,
            'unit': str(item.get('unit') or '').strip()[:32] or None,
        })
    return out


def append_outcome(record, summary, extra=None, actor=None):
    """Record WHAT HAPPENED after a decision. Append-only.

    `objective_met` is captured only when the human states it. It is never
    inferred from execution completing, from a metric moving, or from the
    decision having been made at all.
    """
    extra = extra if isinstance(extra, dict) else {}

    status = str(extra.get('status') or '').strip().lower() or None
    if status and status not in OUTCOME_STATUSES:
        raise ValueError(f'status must be one of {OUTCOME_STATUSES}')

    objective_met = extra.get('objective_met')
    if objective_met is not None and not isinstance(objective_met, bool):
        objective_met = None

    entry = {
        'id': _entry_id('out'),
        'summary': _clip(summary, 4000),
        'status': status,
        'observed_result': _clip(extra.get('observed_result'), 4000) or None,
        'expected_result': _clip(extra.get('expected_result'), 4000) or None,
        'metrics': _metrics(extra.get('metrics')),
        'evidence_refs': _evidence_refs(extra.get('evidence_refs')),
        'objective_met': objective_met,
        'recorded_by_user_id': str(getattr(actor, 'id', '') or '') or None,
        # Name snapshot, so attribution survives the author leaving.
        'recorded_by_name': _actor_name(actor),
        'recorded_at': datetime.utcnow().isoformat(),
        'outcome_date': _clip(extra.get('outcome_date'), 64) or None,
    }
    # Fields the original implementation carried; kept for older readers.
    if 'went_with_recommendation' in extra:
        entry['went_with_recommendation'] = extra['went_with_recommendation']
    if 'sentiment' in extra:
        entry['sentiment'] = extra['sentiment']

    outcomes = list(record.outcomes or [])
    outcomes.append(entry)
    record.outcomes = outcomes
    flag_modified(record, 'outcomes')

    # Never regress a superseded/archived record, and never overwrite a status
    # that already says something stronger about lifecycle.
    if record.status in ('in_analysis', 'recorded', 'decided'):
        record.status = 'outcome_recorded'
    record.outcome_recorded_at = datetime.utcnow()
    record.updated_at = datetime.utcnow()
    db.session.commit()
    return record


def append_lesson(record, lesson, extra=None, actor=None):
    """Record WHAT THE ORGANIZATION LEARNED. Append-only.

    A lesson may be added long after the outcome, when more is known, and may
    optionally cite the outcome it came from.
    """
    extra = extra if isinstance(extra, dict) else {}

    outcome_id = str(extra.get('outcome_id') or '').strip() or None
    if outcome_id:
        known = {
            str(o.get('id')) for o in (record.outcomes or []) if isinstance(o, dict)
        }
        if outcome_id not in known:
            raise ValueError('outcome_id does not belong to this decision record')

    entry = {
        'id': _entry_id('les'),
        'lesson': _clip(lesson, 4000),
        'outcome_id': outcome_id,
        'evidence_refs': _evidence_refs(extra.get('evidence_refs')),
        'recorded_by_user_id': str(getattr(actor, 'id', '') or '') or None,
        'recorded_by_name': _actor_name(actor),
        'recorded_at': datetime.utcnow().isoformat(),
    }

    lessons = list(record.lessons_learned or [])
    lessons.append(entry)
    record.lessons_learned = lessons
    flag_modified(record, 'lessons_learned')
    record.updated_at = datetime.utcnow()
    db.session.commit()
    return record


def latest_outcome(record):
    """The most recent observation, or None. Earlier ones are still there."""
    outcomes = record.outcomes if isinstance(record.outcomes, list) else []
    entries = [o for o in outcomes if isinstance(o, dict)]
    return entries[-1] if entries else None


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


# ─────────────────────────────────────────────────────────────────────────────
# Supersession and current state (Phase 5)
#
# REFRESH IS NOT SUPERSESSION. The distinction is the whole point of this
# section, so it is worth stating plainly:
#
#   * REFRESH -- create_or_refresh_record() on the SAME thread. Re-scoring a
#     decision updates the one canonical record: the analysis improved, the
#     decision did not change. Human-owned fields are never touched. This
#     happens automatically, on every completed score.
#
#   * SUPERSESSION -- a DIFFERENT record, representing a NEW decision, is
#     explicitly declared to replace an earlier one. This never happens
#     automatically. A model producing a different recommendation is not an
#     organization changing its mind, and treating it as one would fabricate
#     institutional history. It requires a deliberate human action through
#     supersede_record().
# ─────────────────────────────────────────────────────────────────────────────

CURRENT = 'current'
SUPERSEDED = 'superseded'
UNKNOWN = 'unknown'

# How deep a supersession chain may be walked. Guards against a cycle that
# predates the cycle check, and against pathological chains.
MAX_CHAIN_DEPTH = 50


def successor_of(record):
    """The record that supersedes this one, if any.

    The reverse of `supersedes_id`, resolved by query rather than stored, so
    the two directions cannot disagree.
    """
    if record is None:
        return None
    return DecisionRecord.query.filter_by(supersedes_id=str(record.id)).first()


def current_state(record):
    """Is this record the organization's CURRENT position, or history?

    Three states, and the third one matters:

      * SUPERSEDED -- something explicitly replaced it. Definitive.
      * CURRENT    -- nothing replaced it AND a human recorded a decision on
                      it. Definitive: a person affirmed this is the
                      organization's position.
      * UNKNOWN    -- nothing replaced it and no human ever decided. This is
                      analysis that was recorded, not a decision that was
                      taken.

    That third state is why current-ness is not simply "has no successor".
    Every record that exists today has no successor and no human decision;
    calling them all "current" would assert an organizational position nobody
    ever took. Recency is likewise not evidence: a later analysis is not
    automatically a new decision.
    """
    if record is None:
        return UNKNOWN
    if successor_of(record) is not None:
        return SUPERSEDED
    if record.final_decision:
        return CURRENT
    return UNKNOWN


def _would_create_cycle(new_record, prior_record):
    """True if pointing new_record at prior_record closes a loop."""
    seen = {str(new_record.id)}
    cursor = prior_record
    depth = 0
    while cursor is not None and depth < MAX_CHAIN_DEPTH:
        cid = str(cursor.id)
        if cid in seen:
            return True
        seen.add(cid)
        cursor = (
            DecisionRecord.query.get(cursor.supersedes_id)
            if cursor.supersedes_id else None
        )
        depth += 1
    return False


def supersede_record(new_record, prior_record, actor):
    """Declare that `new_record` replaces `prior_record`.

    Never called automatically. Validates, in order:

      * both records readable by the actor (so supersession cannot be used to
        probe for records they cannot see);
      * write permission on the superseding record;
      * same organization -- cross-organization supersession is impossible,
        not merely discouraged;
      * not itself, and no cycle.

    The prior record is left completely intact: its narrative, evidence and
    human decision all remain readable. Supersession adds a pointer; it never
    deletes or rewrites history.
    """
    from .session_access import can_write_session, canonical_row

    if new_record is None or prior_record is None:
        raise LookupError('Decision record not found')

    if str(new_record.id) == str(prior_record.id):
        raise ValueError('A decision record cannot supersede itself')

    if not can_read_record(new_record, actor) or not can_read_record(prior_record, actor):
        # Deliberately LookupError, not a permission error: a caller must not
        # learn that an unreadable record exists by trying to supersede it.
        raise LookupError('Decision record not found')

    row = canonical_row(actor, new_record.thread_id, include_archived=True)
    if row is not None and not can_write_session(row, actor):
        raise PermissionError('Your role on this project is read-only')

    if str(new_record.organization_id or '') != str(prior_record.organization_id or ''):
        raise ValueError(
            'A decision record can only supersede one owned by the same organization'
        )

    if _would_create_cycle(new_record, prior_record):
        raise ValueError('That supersession would create a cycle')

    existing = successor_of(prior_record)
    if existing is not None and str(existing.id) != str(new_record.id):
        raise ValueError(
            'That decision has already been superseded by another record'
        )

    new_record.supersedes_id = str(prior_record.id)
    new_record.superseded_at = datetime.utcnow()
    new_record.updated_at = datetime.utcnow()
    db.session.commit()
    return new_record


def clear_supersession(record):
    """Undo a supersession link. History is restored, nothing is destroyed."""
    record.supersedes_id = None
    record.superseded_at = None
    record.updated_at = datetime.utcnow()
    db.session.commit()
    return record


def supersession_chain(record, actor, *, max_depth=MAX_CHAIN_DEPTH):
    """Relationship metadata for the chain around one record.

    Returns lightweight links -- ids, titles, timestamps, state -- never full
    payloads. Enough to explain "A was superseded by B, which was superseded
    by C" without loading three records' worth of narrative.

    A link the actor may not read is REDACTED rather than omitted: the chain
    stays honest about being incomplete without disclosing which record it is
    or what it said.
    """
    def _link(item):
        if item is None:
            return None
        if not can_read_record(item, actor):
            return {
                'accessible': False,
                'id': None,
                'title': None,
                'note': 'A related decision exists but is not visible to you',
            }
        return {
            'accessible': True,
            'id': item.id,
            'title': item.title,
            'status': item.status,
            'current_state': current_state(item),
            'human_decision_recorded': bool(item.final_decision),
            'created_at': item.created_at.isoformat() if item.created_at else None,
            'superseded_at': item.superseded_at.isoformat() if item.superseded_at else None,
        }

    predecessors = []
    cursor = DecisionRecord.query.get(record.supersedes_id) if record.supersedes_id else None
    seen = {str(record.id)}
    while cursor is not None and len(predecessors) < max_depth:
        if str(cursor.id) in seen:
            break
        seen.add(str(cursor.id))
        predecessors.append(_link(cursor))
        cursor = (
            DecisionRecord.query.get(cursor.supersedes_id)
            if cursor.supersedes_id else None
        )

    successors = []
    cursor = successor_of(record)
    while cursor is not None and len(successors) < max_depth:
        if str(cursor.id) in seen:
            break
        seen.add(str(cursor.id))
        successors.append(_link(cursor))
        cursor = successor_of(cursor)

    return {
        'record_id': record.id,
        'current_state': current_state(record),
        # Oldest first, so the chain reads forwards.
        'supersedes': list(reversed(predecessors)),
        'superseded_by': successors,
    }
