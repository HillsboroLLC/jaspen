# backend/app/decision_ledger.py
#
# Emitting and reading the challenge ledger (spec §4). Phase 2 of the Decision
# Impact Report.
#
# WHAT THIS MODULE IS ALLOWED TO RECORD
#
# Only deterministic state transitions observed at the moment they are written,
# and only ones that constitute analytical work. Every function here takes the
# actual before/after state as arguments; none of them reads a transcript, asks
# a model anything, or accepts a caller's assertion about what happened.
#
# The distinction that matters at the scoring call site: this module is NOT
# recording "a scorecard was saved". It is recording "criterion `cost` was
# found to rest on nothing, and an ask for the source was put in front of the
# user". The first is a persistence operation and must never reach the ledger;
# the second is the finding, and it is what the report is entitled to claim.
#
# UNDER-ATTRIBUTION IS THE DEFAULT
#
# Where the semantics of an event are ambiguous — most often "did Jaspen
# introduce this, or did the user?" — nothing is recorded. Three event types
# from the original taxonomy have no emitter for exactly this reason (§4.5 of
# the spec). A missing event costs Jaspen credit it earned. A wrong one claims
# the user's own thinking as Jaspen's, and there is no version of this product
# where that is the better error.

from datetime import datetime

from . import db
from .decision_confidence import (
    EVIDENCED_GRADES,
    MATERIAL_SWING_POINTS,
    criterion_entries,
)
from .models_challenge_event import (
    ACTOR_JASPEN,
    CAP_QUALIFYING_TYPES,
    EVENT_ASSUMPTION_LEFT_OPEN,
    EVENT_ASSUMPTION_RESOLVED,
    EVENT_DEPENDENCY_SURFACED,
    EVENT_EVIDENCE_REQUESTED,
    EVENT_EXPOSURE_QUANTIFIED,
    TARGET_CRITERION,
    TARGET_DEPENDENCY,
    ChallengeEvent,
)

ORIGIN_SCORING = 'scoring'
ORIGIN_EXECUTION_PLAN = 'execution_plan'


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def thread_events(user_id, thread_id, epoch=1):
    return (
        ChallengeEvent.query
        .filter_by(user_id=str(user_id), thread_id=str(thread_id), epoch=int(epoch))
        .order_by(ChallengeEvent.seq.asc(), ChallengeEvent.occurred_at.asc())
        .all()
    )


def existing_dedupe_keys(user_id, thread_id, epoch=1):
    rows = (
        db.session.query(ChallengeEvent.dedupe_key)
        .filter_by(user_id=str(user_id), thread_id=str(thread_id), epoch=int(epoch))
        .all()
    )
    return {row[0] for row in rows}


def targets_with_event(user_id, thread_id, event_type, epoch=1):
    """Distinct decision elements carrying an event of this type.

    Distinct, not a row count: the measures are "how many criteria were
    resolved", never "how many times we said so".
    """
    rows = (
        db.session.query(ChallengeEvent.target_id)
        .filter_by(
            user_id=str(user_id), thread_id=str(thread_id),
            epoch=int(epoch), type=event_type,
        )
        .all()
    )
    return {row[0] for row in rows if row[0]}


def cap_qualifying_event_count(user_id, thread_id, epoch=1):
    """Events that may lift the attribution cap (spec §5.4).

    Two filters, both load-bearing. `user_visible` — an intervention nobody
    could observe did not challenge anyone. `CAP_QUALIFYING_TYPES` — so that a
    future bookkeeping event can enter the ledger without entering this count.
    """
    return (
        ChallengeEvent.query
        .filter_by(user_id=str(user_id), thread_id=str(thread_id), epoch=int(epoch))
        .filter(ChallengeEvent.user_visible.is_(True))
        .filter(ChallengeEvent.type.in_(tuple(CAP_QUALIFYING_TYPES)))
        .count()
    )


def counts_by_type(user_id, thread_id, epoch=1):
    counts = {}
    for event in thread_events(user_id, thread_id, epoch):
        if event.user_visible:
            counts[event.type] = counts.get(event.type, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def _stage(user_id, thread_id, epoch, organization_id, drafts):
    """Stage new events, dropping any that already exist.

    Deduplicated twice over: against what is already stored, and within this
    batch. The unique constraint is the real guarantee — this just avoids
    provoking it. Nothing is committed here; the events flush with whatever
    write produced them, so a rolled-back scorecard takes its ledger entries
    with it.
    """
    if not drafts:
        return []

    seen = existing_dedupe_keys(user_id, thread_id, epoch)
    next_seq = (
        db.session.query(db.func.coalesce(db.func.max(ChallengeEvent.seq), 0))
        .filter_by(user_id=str(user_id), thread_id=str(thread_id), epoch=int(epoch))
        .scalar()
    ) or 0

    staged = []
    for draft in drafts:
        key = draft['dedupe_key']
        if key in seen:
            continue
        seen.add(key)
        next_seq += 1
        event = ChallengeEvent(
            user_id=str(user_id),
            organization_id=organization_id,
            thread_id=str(thread_id),
            epoch=int(epoch),
            seq=next_seq,
            occurred_at=datetime.utcnow(),
            actor=ACTOR_JASPEN,
            user_visible=True,
            **draft,
        )
        db.session.add(event)
        staged.append(event)
    return staged


def _grade(dimension):
    return str((dimension or {}).get('confidence') or '').strip().lower()


def _ask(dimension):
    return str((dimension or {}).get('what_would_improve') or '').strip()


def _label(dimension, key):
    return str((dimension or {}).get('label') or key)[:255]


def record_scoring_pass(
    *, user_id, thread_id, scorecard_id, previous_payload, new_payload,
    organization_id=None, epoch=1,
):
    """Ledger entries for one analytical scoring pass.

    Called from inside `upsert_scorecard`, which is the single chokepoint every
    scoring path funnels through and the only place holding BOTH the previously
    persisted dimensions and the ones about to replace them. That pairing is
    what makes a grade transition observable at all.

    Four findings come out of one pass:

      evidence_requested    a criterion rests on nothing (or nearly nothing) and
                            Jaspen put a specific ask in front of the user. The
                            grade is deterministic; the ask's wording is the
                            model's. The event records the STATE and the fact an
                            ask exists — never the wording as a claim.
      assumption_left_open  a criterion Jaspen already challenged has been
                            re-scored and is STILL unsupported, and Jaspen has
                            said so again. This is the difference the spec
                            insists on (§4.3): an uncertainty made explicit, not
                            a field that happened to stay blank. A criterion
                            nobody ever asked about cannot reach this state.
      assumption_resolved   a criterion that stood on an assumption now stands
                            on evidence. Requires a previous pass: a criterion
                            that arrived evidenced was never resolved by us.
      exposure_quantified   a criterion's uncertainty has been converted into a
                            number of score points, and enough of them to
                            matter. Below the materiality line the arithmetic is
                            real but the finding is not worth claiming.
    """
    previous = (previous_payload or {}).get('dimensions')
    previous = previous if isinstance(previous, dict) else {}
    new = (new_payload or {}).get('dimensions')
    new = new if isinstance(new, dict) else {}
    if not new:
        return []

    already_requested = targets_with_event(
        user_id, thread_id, EVENT_EVIDENCE_REQUESTED, epoch,
    )

    # Did a genuinely NEW analytical pass happen, or is this the same run
    # arriving twice? Each scoring run carries its own evaluation_id; a retry
    # of one carries the one already persisted.
    #
    # This gates `assumption_left_open` only. Without it, re-executing an
    # identical request would record "Jaspen re-examined this and it is still
    # unsupported" when Jaspen did no such thing — the retry inflation the
    # ledger exists to prevent, arriving through the back door. When either id
    # is missing the answer is "cannot tell", and the event is skipped: a
    # missing event costs Jaspen credit, a false one costs the report its
    # standing.
    previous_run = str((previous_payload or {}).get('evaluation_id') or '').strip()
    current_run = str((new_payload or {}).get('evaluation_id') or '').strip()
    is_new_pass = bool(previous_run and current_run and previous_run != current_run)

    drafts = []
    for key, dimension in new.items():
        if not isinstance(dimension, dict):
            continue
        grade = _grade(dimension)
        prior = previous.get(key) if isinstance(previous.get(key), dict) else None
        prior_grade = _grade(prior) if prior else None
        ask = _ask(dimension)
        evidenced = grade in EVIDENCED_GRADES
        label = _label(dimension, key)

        if not evidenced and ask:
            asked_before = key in already_requested
            if asked_before and not is_new_pass:
                # Already challenged, and nothing new has happened since.
                # Saying so a second time is not a second finding.
                continue
            event_type = EVENT_ASSUMPTION_LEFT_OPEN if asked_before else EVENT_EVIDENCE_REQUESTED
            drafts.append({
                'type': event_type,
                'target_kind': TARGET_CRITERION,
                'target_id': str(key),
                'target_label': label,
                'trigger': {
                    'grade': grade,
                    'previous_grade': prior_grade,
                    'resolution_ask_recorded': True,
                    'evaluation_id': current_run or None,
                },
                'origin': ORIGIN_SCORING,
                'derivation_id': str(scorecard_id),
                'dedupe_key': f'{event_type}:{key}',
            })

        if evidenced and prior_grade and prior_grade not in EVIDENCED_GRADES:
            drafts.append({
                'type': EVENT_ASSUMPTION_RESOLVED,
                'target_kind': TARGET_CRITERION,
                'target_id': str(key),
                'target_label': label,
                'trigger': {'grade': grade, 'previous_grade': prior_grade},
                'origin': ORIGIN_SCORING,
                'derivation_id': str(scorecard_id),
                'dedupe_key': f'{EVENT_ASSUMPTION_RESOLVED}:{key}',
            })

    weights = (new_payload or {}).get('scoring_weights')
    if not isinstance(weights, dict) or not weights:
        rubric = (new_payload or {}).get('rubric') or (new_payload or {}).get('scoring_rubric')
        criteria = (rubric or {}).get('criteria') if isinstance(rubric, dict) else None
        weights = {
            str(c.get('key')): c.get('weight')
            for c in (criteria or []) if isinstance(c, dict) and c.get('key')
        }
    for entry in criterion_entries(new, weights or {}):
        if entry['swing'] < MATERIAL_SWING_POINTS:
            continue
        drafts.append({
            'type': EVENT_EXPOSURE_QUANTIFIED,
            'target_kind': TARGET_CRITERION,
            'target_id': str(entry['key']),
            'target_label': str(entry['label'])[:255],
            'trigger': {
                'swing_points': entry['swing'],
                'weight': entry['weight'],
                'grade': entry['confidence'],
                'materiality_points': MATERIAL_SWING_POINTS,
            },
            'origin': ORIGIN_SCORING,
            'derivation_id': str(scorecard_id),
            'dedupe_key': f'{EVENT_EXPOSURE_QUANTIFIED}:{entry["key"]}',
        })

    return _stage(user_id, thread_id, epoch, organization_id, drafts)


def record_generated_plan(
    *, user_id, thread_id, plan, organization_id=None, epoch=1, derivation_id=None,
):
    """Ledger entries for execution dependencies Jaspen surfaced.

    Only ever called from the AI plan-generation path. A dependency the user
    typed into their own plan is theirs, and a user edit reaching this function
    would attribute their work to Jaspen — so the plan-editing routes do not
    call it, and this is deliberate rather than an omission.
    """
    tasks = []
    if isinstance(plan, dict):
        tasks = plan.get('tasks') if isinstance(plan.get('tasks'), list) else []
    elif isinstance(plan, list):
        tasks = plan

    drafts = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_id = str(task.get('id') or '').strip()
        title = str(task.get('title') or task.get('name') or '').strip()
        for raw in (task.get('depends_on') or task.get('dependencies') or []):
            dependency = str(raw or '').strip()
            if not dependency or not task_id:
                continue
            drafts.append({
                'type': EVENT_DEPENDENCY_SURFACED,
                'target_kind': TARGET_DEPENDENCY,
                'target_id': f'{dependency}->{task_id}'[:120],
                'target_label': title[:255] or task_id,
                'trigger': {'task_id': task_id, 'depends_on': dependency},
                'origin': ORIGIN_EXECUTION_PLAN,
                'derivation_id': str(derivation_id or task_id),
                'dedupe_key': f'{EVENT_DEPENDENCY_SURFACED}:{dependency}->{task_id}'[:200],
            })

    return _stage(user_id, thread_id, epoch, organization_id, drafts)
