# backend/app/decision_impact.py
#
# The Decision Impact Report — what changed about a decision between the moment
# it was submitted and the moment the analysis closed.
# Specification: docs/DECISION_IMPACT_REPORT_SPEC.md. This module implements
# Phase 1 of §12: the deterministic skeleton. No challenge ledger, no model.
#
# THE ONE RULE THIS MODULE EXISTS TO KEEP
#
# Every number here is counted by code from persisted structures. Nothing in
# this file asks a model anything, and nothing a model said reaches a measure,
# a delta, or a verdict. That is what lets the report be handed to someone who
# does not trust us: they can recompute it.
#
# WHAT PHASE 1 CAN AND CANNOT SAY (be honest about this when reading output)
#
#   The attribution cap (spec §5.4) holds the verdict at `limited` until the
#   challenge ledger exists, because without recorded analytical work we cannot
#   distinguish "Jaspen improved this decision" from "the user typed more".
#   Phase 1 therefore underclaims by construction. That is the intended
#   behaviour, not a gap to work around.
#
#   Measures that need per-criterion identity across the intake/close boundary
#   (B4, B5) are reported `not_applicable` with a reason. They arrive with the
#   ledger. They are not silently scored as zero.
#
# SHAPE IS THE CALLER'S JOB. Like decision_report.py, this returns content, not
# layout. The workspace panel, and later the email and deck, render subsets of
# one structure so they cannot drift apart.

import hashlib
import json
from datetime import datetime

from flask import current_app

from . import db
from .decision_confidence import EVIDENCE_FACTOR
from .intake_readiness import _active_readiness_version, _compute_readiness
from .models_decision_baseline import (
    BASIS_DETERMINISTIC,
    BASIS_PROPOSED_UNCONFIRMED,
    BASIS_USER_CONFIRMED,
    CAPTURE_CONTEMPORANEOUS,
    CAPTURE_RECONSTRUCTED,
    IMPACT_METHODOLOGY_VERSION,
    PREDICATE_ELIGIBLE_BASES,
    RECONSTRUCTED_LATE_SEAL,
    RECONSTRUCTED_NO_CAPTURE,
    SEALED_BY_ANALYSIS,
    SEALED_BY_USER,
    DecisionBaseline,
    SealedBaselineError,
)

IMPACT_SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Thresholds (spec §5.1)
#
# These are conventions, not discoveries. They are published in every report so
# a reader can recompute the verdict by hand, and changing one bumps the
# methodology version. MATERIALITY_PP in particular is a reasoned starting
# value awaiting calibration against real usage (spec §11 Q2) — treat it as
# provisional until there is a cohort to check it against.
# ---------------------------------------------------------------------------
MATERIALITY_PP = 10
STRONG_PP = 20
STRONG_ASSUMPTIONS_VALIDATED = 3
MATERIALITY_COUNT = 1

THRESHOLDS = {
    'MATERIALITY_PP': MATERIALITY_PP,
    'STRONG_PP': STRONG_PP,
    'STRONG_ASSUMPTIONS_VALIDATED': STRONG_ASSUMPTIONS_VALIDATED,
    'MATERIALITY_COUNT': MATERIALITY_COUNT,
}

VERDICT_MATERIAL = 'material'
VERDICT_LIMITED = 'limited'
VERDICT_NONE = 'no_material_change'

# The fourth state, and not a degree of the other three (spec §5.6). It says
# the comparison could not be made, rather than that it was made and found
# little. A reconstructed baseline reaches this and stops here: it can never
# be promoted by measures, however far they moved.
VERDICT_UNVERIFIED = 'unverified_baseline'

FAMILY_STRUCTURE = 'A'
FAMILY_VERIFICATION = 'B'

# ---------------------------------------------------------------------------
# Two classes of measure, and the distinction is not cosmetic (spec §2.5)
#
#   state         a property the decision genuinely HAS, at intake and at
#                 close. Comparable across the two, because both readings
#                 describe the same kind of thing.
#   intervention  something Jaspen DID, or caused to become explicit, during
#                 the analysis. It has no Before.
#
# "Before Jaspen, Jaspen had resolved zero assumptions" is definitionally true
# and says nothing about the decision the user brought. Presenting it as a
# 0 → 3 delta would dress a tautology up as a measured improvement, and it
# would be the most flattering number on the page. Interventions are reported
# as counts of work done, never as movement.
# ---------------------------------------------------------------------------
CLASS_STATE = 'state'
CLASS_INTERVENTION = 'intervention'

KIND_COUNT = 'count'
KIND_PCT = 'pct'
KIND_GRADES = 'grades'

# Route 1 refuses to fire on peripheral growth alone: a decision whose
# alternatives, criteria and dependencies are all unchanged has not been
# structurally reshaped, however many risks were added (spec §5.3).
ROUTE_1_QUALIFYING = ('A1', 'A2', 'A5')

# ---------------------------------------------------------------------------
# The measure registry (spec §2)
#
# `label` is what a reader sees. `direction` is declared once here so no caller
# can decide at read time which way a measure ought to point.
# ---------------------------------------------------------------------------
MEASURES = {
    'A1': {'label': 'Alternatives evaluated',        'family': FAMILY_STRUCTURE,    'kind': KIND_COUNT,  'direction': 'up',   'class': CLASS_STATE},
    'A2': {'label': 'Decision criteria defined',     'family': FAMILY_STRUCTURE,    'kind': KIND_COUNT,  'direction': 'up',   'class': CLASS_STATE},
    'A3': {'label': 'Criteria explicitly weighted',  'family': FAMILY_STRUCTURE,    'kind': KIND_COUNT,  'direction': 'up',   'class': CLASS_STATE},
    'A4': {'label': 'Risks documented',              'family': FAMILY_STRUCTURE,    'kind': KIND_COUNT,  'direction': 'up',   'class': CLASS_STATE},
    'A5': {'label': 'Execution dependencies',        'family': FAMILY_STRUCTURE,    'kind': KIND_COUNT,  'direction': 'up',   'class': CLASS_STATE},
    'A6': {'label': 'Readiness categories addressed','family': FAMILY_STRUCTURE,    'kind': KIND_COUNT,  'direction': 'up',   'class': CLASS_STATE},
    'B1': {'label': 'Evidence-backed share',         'family': FAMILY_VERIFICATION, 'kind': KIND_PCT,    'direction': 'up',   'class': CLASS_STATE},
    'B2': {'label': 'Assumption-dependent share',    'family': FAMILY_VERIFICATION, 'kind': KIND_PCT,    'direction': 'down', 'class': CLASS_STATE},
    'B3': {'label': 'Criteria evidence grades',      'family': FAMILY_VERIFICATION, 'kind': KIND_GRADES, 'direction': 'up',   'class': CLASS_STATE},
    # Interventions. Counts of work Jaspen did, never deltas.
    'B4': {'label': 'Assumptions validated',         'family': FAMILY_VERIFICATION, 'kind': KIND_COUNT,  'direction': 'up',   'class': CLASS_INTERVENTION},
    'B5': {'label': 'Uncertainties made explicit',   'family': FAMILY_VERIFICATION, 'kind': KIND_COUNT,  'direction': 'up',   'class': CLASS_INTERVENTION},
    'B6': {'label': 'Exposures quantified',          'family': FAMILY_VERIFICATION, 'kind': KIND_COUNT,  'direction': 'up',   'class': CLASS_INTERVENTION},
}

STATE_MEASURES = tuple(k for k, v in MEASURES.items() if v['class'] == CLASS_STATE)
INTERVENTION_MEASURES = tuple(k for k, v in MEASURES.items() if v['class'] == CLASS_INTERVENTION)

# What each intervention must reach to count as substantive, and what it must
# reach to carry a verification route on its own. `None` for strong means the
# intervention can contribute alongside others but never satisfies a route by
# itself: labelling one uncertainty is real work and is not, alone, a material
# change to a decision.
INTERVENTION_THRESHOLDS = {
    'B4': {'qualifying': 1, 'strong': STRONG_ASSUMPTIONS_VALIDATED},
    'B5': {'qualifying': 1, 'strong': None},
    'B6': {'qualifying': 1, 'strong': None},
}

# B4, B5 and B6 are LEDGER MEASURES: they count decision elements carrying a
# recorded challenge or validation event, not stocks read off a scorecard.
#
# That is what makes them honest. "Assumptions validated" was previously
# unmeasurable because a free-text assumption at intake and a rubric criterion
# at close share no identity — the ledger supplies it by keying every event to
# a stable criterion key, so a criterion challenged in one pass and resolved
# three passes later is recognisably the same criterion.
#
# Their baseline value is a deterministic 0, and not by convention: before
# Jaspen ran, Jaspen had resolved nothing, labelled nothing, and quantified
# nothing. That is true by definition rather than assumed.
LEDGER_MEASURES = {
    'B4': 'assumption_resolved',
    'B5': 'assumption_left_open',
    'B6': 'exposure_quantified',
}

# How a user's own statement about a criterion at intake maps to an evidence
# grade, so baseline B1 can be computed with the SAME arithmetic as closing B1
# (spec §2.4: identical definitions, different provenance).
#
# The backed case maps to `high` — the most generous reading available —
# deliberately. Every judgment call about the baseline either widens or narrows
# the delta we later claim, so ambiguity resolves in the BASELINE's favour. A
# stingier reading here would manufacture improvement.
BASELINE_GRADE_BACKED = 'high'
BASELINE_GRADE_UNBACKED = 'assumed'


# ---------------------------------------------------------------------------
# Canonical serialization and hashing (spec §3.4)
# ---------------------------------------------------------------------------

def canonical_json(payload):
    """Sorted keys, no whitespace, UTF-8 — the form the hashes are taken over."""
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def content_digest(payload):
    return 'sha256:' + hashlib.sha256(canonical_json(payload).encode('utf-8')).hexdigest()


def combined_digest(submission_payload, measures):
    return 'sha256:' + hashlib.sha256(
        (canonical_json(submission_payload) + canonical_json(measures)).encode('utf-8')
    ).hexdigest()


# ---------------------------------------------------------------------------
# Measure helpers
# ---------------------------------------------------------------------------

def _measure(value, basis, reason=None):
    entry = {'value': value, 'basis': basis}
    if reason:
        entry['reason'] = reason
    return entry


def _not_measurable(reason, basis=BASIS_DETERMINISTIC):
    return _measure(None, basis, reason)


def _int_or_zero(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def evidence_backed_pct_from_grades(graded_weights):
    """Weighted share of decision weight standing on evidence, 0-100.

    `graded_weights` is [(grade, weight), ...]. This is deliberately the same
    arithmetic as decision_confidence.evidence_ratio() — the same
    EVIDENCE_FACTOR table over the same normalized weights — expressed over
    grades alone so it can also be applied at intake, where no criterion has a
    score yet and criterion_entries() would therefore reject every row.
    Equivalence with evidence_ratio() is held by test, not by comment.
    """
    usable = [(g, float(w)) for g, w in graded_weights if w is not None and float(w) > 0]
    total = sum(w for _, w in usable)
    if not usable or total <= 0:
        return None
    backed = sum((w / total) * EVIDENCE_FACTOR.get(g, 0.0) for g, w in usable)
    return int(round(max(0.0, min(1.0, backed)) * 100))


def _grade_histogram(grades):
    histogram = {'high': 0, 'medium': 0, 'low': 0, 'assumed': 0}
    for grade in grades:
        if grade in histogram:
            histogram[grade] += 1
    return histogram


# ---------------------------------------------------------------------------
# Link 1 — capturing the raw submission (spec §3.1.1)
# ---------------------------------------------------------------------------

def build_submission_payload(session, structure=None):
    """The raw material the user supplied, verbatim.

    Verbatim means verbatim: message text is copied, not clipped, summarized or
    normalized. `_summarize_conversation` in decision_records.py does the
    opposite job for the opposite reason — a record wants a digest, a baseline
    wants the thing itself.

    Attachment BYTES are not copied here. The reference is: name, media type,
    size and whatever hash the upload recorded. That keeps the chain resolving
    to a specific artifact rather than to a description of one, without this
    table becoming a second copy of the user's files.
    """
    session = session if isinstance(session, dict) else {}
    history = session.get('chat_history')
    history = history if isinstance(history, list) else []

    turns = []
    attachments = []
    for index, message in enumerate(history):
        if not isinstance(message, dict):
            continue
        role = str(message.get('role') or '').lower()
        if role not in ('user', 'human'):
            continue
        content = message.get('content')
        if not isinstance(content, str):
            content = str(message.get('text') or message.get('message') or '')
        turn_attachments = message.get('attachments')
        turn_attachments = turn_attachments if isinstance(turn_attachments, list) else []
        for attachment in turn_attachments:
            if not isinstance(attachment, dict):
                continue
            attachments.append({
                'turn_index': index,
                'name': attachment.get('name') or attachment.get('filename'),
                'media_type': attachment.get('type') or attachment.get('media_type'),
                'kind': attachment.get('kind'),
                'size_bytes': attachment.get('size') or attachment.get('size_bytes'),
                'content_hash': attachment.get('content_hash') or attachment.get('hash'),
                'locator': attachment.get('url') or attachment.get('path') or attachment.get('id'),
            })
        turns.append({
            'index': index,
            'role': role,
            'content': content,
            'timestamp': message.get('timestamp') or message.get('createdAt'),
        })

    return {
        'turns': turns,
        'attachments': attachments,
        'strategy_objective': session.get('strategy_objective'),
        'session_name': session.get('name'),
        # What the user confirmed in the correction window. Empty until they do.
        'structure': structure if isinstance(structure, dict) else {},
        'captured_at': datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Link 2 — deriving baseline measures from the submission (spec §3.7)
# ---------------------------------------------------------------------------

def derive_baseline_measures(submission_payload, *, readiness_spec=None):
    """Measure the sealed submission.

    Two provenances, and the difference matters enough to be carried on every
    measure rather than inferred:

      deterministic    counted by code from the submission itself. In Phase 1
                       that is A6 alone — the readiness engine is the only
                       thing that reads free prose reliably. Counting
                       "alternatives" out of paragraphs with keyword rules
                       would be guesswork wearing a number's clothes.
      user_confirmed   the user told us, in the correction window, and stood
                       behind it.

    Everything the user did not confirm is reported with a reason instead of a
    value. A confident zero we did not earn is worse than an admitted blank:
    zeros move the predicate, blanks do not.
    """
    submission = submission_payload if isinstance(submission_payload, dict) else {}
    structure = submission.get('structure') if isinstance(submission.get('structure'), dict) else {}
    confirmed = bool(structure.get('confirmed'))

    # A6 — deterministic, straight from the readiness engine over the turns as
    # submitted. Same engine the sidebar runs, so the two can never disagree.
    chat_history = [
        {'role': turn.get('role'), 'content': turn.get('content')}
        for turn in (submission.get('turns') or [])
        if isinstance(turn, dict)
    ]
    readiness = _compute_readiness(
        chat_history,
        strategy_objective=submission.get('strategy_objective') or 'balanced',
        spec=readiness_spec,
    )
    addressed = sum(
        1 for category in (readiness.get('categories') or [])
        if isinstance(category, dict) and category.get('completed')
    )

    measures = {'A6': _measure(addressed, BASIS_DETERMINISTIC)}

    basis = BASIS_USER_CONFIRMED if confirmed else BASIS_PROPOSED_UNCONFIRMED
    unconfirmed_reason = None if confirmed else 'not confirmed at intake'

    def _listed(key):
        value = structure.get(key)
        return value if isinstance(value, list) else []

    criteria = [c for c in _listed('criteria') if isinstance(c, dict)]

    if structure:
        measures['A1'] = _measure(len(_listed('alternatives')), basis, unconfirmed_reason)
        measures['A2'] = _measure(len(criteria), basis, unconfirmed_reason)
        measures['A3'] = _measure(
            sum(1 for c in criteria if c.get('weight') is not None), basis, unconfirmed_reason,
        )
        measures['A4'] = _measure(len(_listed('risks')), basis, unconfirmed_reason)
        measures['A5'] = _measure(len(_listed('dependencies')), basis, unconfirmed_reason)

        if criteria:
            graded = [
                (
                    BASELINE_GRADE_BACKED if c.get('backed_by_source') else BASELINE_GRADE_UNBACKED,
                    # An unweighted criterion counts equally. Equal weighting is
                    # a stated convention, not a measurement: it is what the
                    # user implied by naming criteria without ranking them.
                    c.get('weight') if c.get('weight') is not None else 1.0,
                )
                for c in criteria
            ]
            backed_pct = evidence_backed_pct_from_grades(graded)
            measures['B1'] = _measure(backed_pct, basis, unconfirmed_reason)
            measures['B2'] = _measure(
                None if backed_pct is None else 100 - backed_pct, basis, unconfirmed_reason,
            )
            measures['B3'] = _measure(
                _grade_histogram([g for g, _ in graded]), basis, unconfirmed_reason,
            )

    # Intervention measures are deliberately ABSENT from the baseline rather
    # than recorded as zero. A zero here would be true and useless: it says
    # Jaspen had not acted before Jaspen acted, which is not a property of the
    # decision the user brought and must never render as the Before half of a
    # delta (spec §2.5).
    for measure_id in STATE_MEASURES:
        if measure_id not in measures:
            measures[measure_id] = _not_measurable('not established at intake')

    return measures


# ---------------------------------------------------------------------------
# Baseline lifecycle (spec §3.2 – §3.5)
# ---------------------------------------------------------------------------

def _thread_sources(user_id, thread_id):
    # decision_records owns the only reader over the two thread stores. Calling
    # it rather than re-implementing the lookup keeps the baseline and the
    # Decision Record reading the same conversation.
    from .decision_records import _load_thread_sources
    return _load_thread_sources(user_id, thread_id)


def get_baseline(user_id, thread_id, epoch=1):
    return (
        DecisionBaseline.query
        .filter_by(user_id=str(user_id), thread_id=str(thread_id), epoch=int(epoch))
        .first()
    )


def analysis_has_started(user_id, thread_id, session=None, thread_data=None):
    """Has this thread produced any scored analysis yet?

    Two things hang off this answer, so it has to be right in both directions.
    It closes the correction window — a baseline must never absorb material the
    user added after seeing what the analysis produced, which is the one edit
    that could manufacture a delta. And it decides capture provenance: a seal
    landing after this is true did not capture a before state.

    `user_id` and `thread_id` are REQUIRED, and passing them is the whole point.
    _collect_peer_scorecards falls back to the legacy session/scenario stores
    when they are absent, and misses the `scorecards` table entirely — so the
    parameterless form answers False for a fully analyzed thread, holding the
    correction window open long after it should have shut.
    """
    from .decision_records import _collect_peer_scorecards
    if session is None and thread_data is None:
        session, thread_data = _thread_sources(user_id, thread_id)
    return bool(_collect_peer_scorecards(
        session or {}, thread_data or {}, user_id=user_id, thread_id=thread_id,
    ))


def capture_or_update_draft(user, thread_id, structure=None, epoch=1):
    """Create or revise the UNSEALED draft baseline for a thread.

    Idempotent: called on every visit to the correction window. Raises once the
    baseline is sealed, or once analysis has produced output.
    """
    session, thread_data = _thread_sources(user.id, thread_id)
    if session is None and not thread_data:
        raise LookupError(f'No conversation found for thread {thread_id}')

    existing = get_baseline(user.id, thread_id, epoch)
    if existing and existing.is_sealed:
        raise SealedBaselineError(
            f'baseline for thread {thread_id} was sealed at {existing.sealed_at}'
        )
    if analysis_has_started(user.id, thread_id, session, thread_data):
        raise SealedBaselineError(
            'analysis has already produced output for this thread; '
            'the baseline can no longer be revised'
        )

    # Carry forward anything already confirmed so a caller passing no structure
    # is a no-op refresh rather than a silent erasure.
    if structure is None and existing:
        prior = existing.submission_payload if isinstance(existing.submission_payload, dict) else {}
        structure = prior.get('structure')

    submission_payload = build_submission_payload(session, structure)
    measures = derive_baseline_measures(submission_payload)

    if existing:
        existing.submission_payload = submission_payload
        existing.measures = measures
        existing.updated_at = datetime.utcnow()
        db.session.commit()
        return existing

    baseline = DecisionBaseline(
        user_id=user.id,
        organization_id=getattr(user, 'active_organization_id', None),
        thread_id=str(thread_id),
        epoch=int(epoch),
        submission_payload=submission_payload,
        measures=measures,
        readiness_spec_version=_active_readiness_version(),
        methodology_version=IMPACT_METHODOLOGY_VERSION,
    )
    db.session.add(baseline)
    db.session.commit()
    return baseline


def seal_baseline(user, thread_id, sealed_by=SEALED_BY_USER, epoch=1):
    """Freeze the baseline. Idempotent: sealing a sealed baseline returns it.

    A thread that reached analysis without a draft still gets a baseline — an
    absent baseline would mean no report at all, and the user ignoring an
    optional panel is not a reason to withhold their evidence chain. It seals
    `auto_on_analysis`, and every measure the correction window would have
    supplied stays `proposed_unconfirmed`, which the predicate ignores.
    """
    baseline = get_baseline(user.id, thread_id, epoch)
    if baseline and baseline.is_sealed:
        return baseline

    session, thread_data = _thread_sources(user.id, thread_id)
    if session is None and not thread_data:
        raise LookupError(f'No conversation found for thread {thread_id}')

    # Capture provenance is decided HERE, from the thread's own state, and is
    # never accepted from a caller. A seal that lands after analysis has
    # already produced output did not capture a before state, whatever the
    # caller believed it was doing.
    started = analysis_has_started(user.id, thread_id, session, thread_data)
    if not started:
        capture, capture_reason = CAPTURE_CONTEMPORANEOUS, None
    elif baseline is not None:
        # A draft exists, and the correction window refuses writes once
        # analysis starts — so this payload IS pre-analysis content. The seal
        # is what arrived late. Recorded distinctly because it is the case a
        # verified-reconstruction path could one day rescue; treated no
        # differently until that path exists.
        capture, capture_reason = CAPTURE_RECONSTRUCTED, RECONSTRUCTED_LATE_SEAL
    else:
        capture, capture_reason = CAPTURE_RECONSTRUCTED, RECONSTRUCTED_NO_CAPTURE

    if baseline is None:
        # Nothing was captured in time, so this payload is the thread AS IT NOW
        # STANDS — including every turn the user made during and after
        # analysis. It is recorded for transparency and marked reconstructed.
        # It is not a before state and nothing may render it as one.
        submission_payload = build_submission_payload(session, None)
        baseline = DecisionBaseline(
            user_id=user.id,
            organization_id=getattr(user, 'active_organization_id', None),
            thread_id=str(thread_id),
            epoch=int(epoch),
            submission_payload=submission_payload,
            measures=derive_baseline_measures(submission_payload),
            readiness_spec_version=_active_readiness_version(),
            methodology_version=IMPACT_METHODOLOGY_VERSION,
        )
        db.session.add(baseline)

    baseline.submission_hash = content_digest(baseline.submission_payload)
    baseline.measures_hash = content_digest(baseline.measures)
    baseline.content_hash = combined_digest(baseline.submission_payload, baseline.measures)
    baseline.sealed_at = datetime.utcnow()
    baseline.sealed_by = sealed_by if sealed_by in (SEALED_BY_USER, SEALED_BY_ANALYSIS) else SEALED_BY_ANALYSIS
    baseline.capture = capture
    baseline.capture_reason = capture_reason
    db.session.commit()
    return baseline


# The agent reaches scoring through _execute_mutation_tool. These are the tool
# names that begin an analysis; everything else it can do (patching prose,
# renaming, editing a plan) happens after one has already run.
SCORING_ENTRY_TOOLS = frozenset({'generate_scorecard', 'queue_scorecards'})


def seal_baseline_on_analysis_start(user, thread_id):
    """Freeze the baseline at the moment analysis begins (spec §3.4).

    Called from every entry point that can start scoring a thread. Idempotent,
    so the entry points need no knowledge of each other and a thread that
    reaches two of them seals once, at the first.

    BEST EFFORT, DELIBERATELY. This must never be the reason an analysis fails.
    A decision the user is waiting on matters more than a baseline row, and the
    report already refuses to generate without a sealed baseline — so a failure
    here costs a report, never an analysis. It is logged rather than raised.

    The counterpart guard does the real work regardless of this hook: the
    correction window rejects every write once the thread has scored output, so
    a baseline cannot absorb post-analysis material even if this never runs.
    """
    if not user or not thread_id:
        return None
    try:
        return seal_baseline(user, thread_id, sealed_by=SEALED_BY_ANALYSIS)
    except Exception:  # noqa: BLE001 — see BEST EFFORT above
        try:
            db.session.rollback()
        except Exception:  # noqa: BLE001
            pass
        current_app.logger.warning(
            'decision_impact: could not seal baseline at analysis start for thread %s',
            thread_id, exc_info=True,
        )
        return None


def verify_baseline_integrity(baseline):
    """Re-check the seal. A tampered baseline produces no report at all.

    Returning a report from a baseline whose hash no longer matches would be
    the worst available outcome: a document that looks like evidence and is not.
    """
    if not baseline or not baseline.is_sealed:
        return True, None
    if content_digest(baseline.submission_payload) != baseline.submission_hash:
        return False, 'submission_payload does not match submission_hash'
    if content_digest(baseline.measures) != baseline.measures_hash:
        return False, 'measures do not match measures_hash'
    if combined_digest(baseline.submission_payload, baseline.measures) != baseline.content_hash:
        return False, 'baseline does not match content_hash'
    return True, None


def rederive_baseline_measures(baseline):
    """Re-run the measurement engine over the sealed submission (spec §3.7, AT-18).

    The property this exists to prove: link 2 is reproducible from link 1. If
    this stops matching a sealed row, the engine changed without a methodology
    bump, and every report generated since is suspect.
    """
    return derive_baseline_measures(baseline.submission_payload)


# ---------------------------------------------------------------------------
# The closing state (spec §2.2, §2.3)
# ---------------------------------------------------------------------------

def _leading_card(cards):
    """The option the recommendation rests on.

    The verification measures describe one option's evidentiary basis, and the
    one worth describing is the option currently leading — that is the claim a
    reader is being asked to act on. Ties break on name so the choice is
    deterministic rather than dependent on dict ordering.
    """
    scored = [c for c in cards if isinstance(c.get('jaspen_score'), (int, float))]
    if not scored:
        return cards[0] if cards else None
    return sorted(scored, key=lambda c: (-c['jaspen_score'], str(c.get('name') or '')))[0]


def current_measures(user_id, thread_id):
    """Measure the decision as it now stands."""
    from .decision_records import _collect_peer_scorecards

    session, thread_data = _thread_sources(user_id, thread_id)
    session = session if isinstance(session, dict) else {}
    cards = _collect_peer_scorecards(session, thread_data, user_id=user_id, thread_id=thread_id)

    rubric = session.get('scoring_rubric') if isinstance(session.get('scoring_rubric'), dict) else {}
    criteria = [c for c in (rubric.get('criteria') or []) if isinstance(c, dict)]

    risks, dependencies = set(), set()
    for card in cards:
        for risk in (card.get('top_risks') or []):
            text = risk.get('risk') if isinstance(risk, dict) else risk
            if str(text or '').strip():
                risks.add(str(text).strip())
    wbs = thread_data.get('project_wbs') if isinstance(thread_data, dict) else None
    for item in (wbs if isinstance(wbs, list) else (wbs or {}).get('tasks', []) if isinstance(wbs, dict) else []):
        if isinstance(item, dict):
            for dependency in (item.get('dependencies') or []):
                if str(dependency or '').strip():
                    dependencies.add(str(dependency).strip())

    chat_history = session.get('chat_history') if isinstance(session.get('chat_history'), list) else []
    readiness = _compute_readiness(
        chat_history, strategy_objective=session.get('strategy_objective') or 'balanced',
    )
    addressed = sum(
        1 for category in (readiness.get('categories') or [])
        if isinstance(category, dict) and category.get('completed')
    )

    measures = {
        'A1': _measure(len(cards), BASIS_DETERMINISTIC),
        'A2': _measure(len(criteria), BASIS_DETERMINISTIC),
        'A3': _measure(
            sum(1 for c in criteria if c.get('weight') is not None), BASIS_DETERMINISTIC,
        ),
        'A4': _measure(len(risks), BASIS_DETERMINISTIC),
        'A5': _measure(len(dependencies), BASIS_DETERMINISTIC),
        'A6': _measure(addressed, BASIS_DETERMINISTIC),
    }

    leader = _leading_card(cards)
    dimensions = (leader or {}).get('dimensions') or {}
    weights = {
        str(c.get('key')): c.get('weight')
        for c in criteria if c.get('key') and c.get('weight') is not None
    }
    graded = [
        (
            str((dim or {}).get('confidence') or 'assumed').lower(),
            weights.get(key, 1.0),
        )
        for key, dim in dimensions.items() if isinstance(dim, dict)
    ]
    if graded:
        backed_pct = evidence_backed_pct_from_grades(graded)
        measures['B1'] = _measure(backed_pct, BASIS_DETERMINISTIC)
        measures['B2'] = _measure(
            None if backed_pct is None else 100 - backed_pct, BASIS_DETERMINISTIC,
        )
        measures['B3'] = _measure(_grade_histogram([g for g, _ in graded]), BASIS_DETERMINISTIC)
    else:
        for measure_id in ('B1', 'B2', 'B3'):
            measures[measure_id] = _not_measurable('no scored criteria in the closing analysis')

    # Ledger measures: distinct decision elements carrying the event, never a
    # row count. "How many criteria were resolved", not "how many times we said
    # so" — a re-score that re-states a finding must not read as more work.
    from .decision_ledger import targets_with_event
    for measure_id, event_type in LEDGER_MEASURES.items():
        measures[measure_id] = _measure(
            len(targets_with_event(user_id, thread_id, event_type)), BASIS_DETERMINISTIC,
        )

    return measures, {'leading_option': (leader or {}).get('name'), 'option_count': len(cards)}


# ---------------------------------------------------------------------------
# The impact predicate (spec §5)
# ---------------------------------------------------------------------------

def _eligible(entry):
    return (
        isinstance(entry, dict)
        and entry.get('value') is not None
        and entry.get('basis') in PREDICATE_ELIGIBLE_BASES
    )


def _movement(measure_id, before, after):
    """Has this measure moved beyond materiality? Returns a record or None."""
    spec = MEASURES[measure_id]
    kind = spec['kind']

    if kind == KIND_COUNT:
        delta = _int_or_zero(after['value']) - _int_or_zero(before['value'])
        if delta >= MATERIALITY_COUNT:
            strong = (
                measure_id == 'B4'
                and _int_or_zero(after['value']) >= STRONG_ASSUMPTIONS_VALIDATED
            )
            return {
                'id': measure_id, 'label': spec['label'], 'family': spec['family'],
                'from': before['value'], 'to': after['value'], 'delta': delta,
                'threshold': 'STRONG_ASSUMPTIONS_VALIDATED' if strong else 'MATERIALITY_COUNT',
                'strong': strong,
            }
        return None

    if kind == KIND_PCT:
        # B2 is B1's complement and is never thresholded on its own; counting
        # both would let one movement satisfy the predicate twice (spec §5.2).
        if measure_id == 'B2':
            return None
        delta = _int_or_zero(after['value']) - _int_or_zero(before['value'])
        if delta >= MATERIALITY_PP:
            strong = delta >= STRONG_PP
            return {
                'id': measure_id, 'label': spec['label'], 'family': spec['family'],
                'from': before['value'], 'to': after['value'], 'delta': delta,
                'threshold': 'STRONG_PP' if strong else 'MATERIALITY_PP',
                'strong': strong,
            }
        return None

    if kind == KIND_GRADES:
        # Without per-criterion identity across the intake boundary, band
        # improvement can only be read in aggregate: more criteria standing at
        # high or medium than before. The per-criterion transition test arrives
        # with the ledger, and will be strictly stronger than this one.
        before_top = _int_or_zero(before['value'].get('high')) + _int_or_zero(before['value'].get('medium'))
        after_top = _int_or_zero(after['value'].get('high')) + _int_or_zero(after['value'].get('medium'))
        if after_top - before_top >= MATERIALITY_COUNT:
            return {
                'id': measure_id, 'label': spec['label'], 'family': spec['family'],
                'from': before['value'], 'to': after['value'],
                'delta': after_top - before_top,
                'threshold': 'MATERIALITY_COUNT', 'strong': False,
            }
        return None

    return None


def _user_visible_event_count(user_id, thread_id, epoch=1):
    """Recorded analytical work that may lift the attribution cap (spec §5.4).

    Only events the user could actually observe, and only types that represent
    analysis rather than bookkeeping. The cap now lifts on its own for a thread
    where Jaspen genuinely challenged something, and keeps binding for one
    where it did not — which is the behaviour Phase 1 could only approximate by
    binding always.
    """
    from .decision_ledger import cap_qualifying_event_count
    return cap_qualifying_event_count(user_id, thread_id, epoch)


WITHHELD_REASONS = {
    RECONSTRUCTED_NO_CAPTURE: (
        'No baseline was captured before this decision was analyzed, so there is '
        'no recorded starting point to compare against. What the thread contains '
        'now includes everything said during and after the analysis.'
    ),
    RECONSTRUCTED_LATE_SEAL: (
        'A baseline was captured before analysis but was not sealed until after '
        'analysis had begun, so it cannot be verified as the state that preceded '
        'the analysis.'
    ),
}


def evaluate_impact(baseline_measures, closing_measures, *,
                    user_visible_events=0,
                    capture=CAPTURE_CONTEMPORANEOUS,
                    capture_reason=None):
    """The verdict, and everything needed to recompute it by hand (spec §5).

    A RECONSTRUCTED baseline stops before any of this arithmetic (spec §5.6).
    Not because the numbers would be unflattering, but because they would be
    meaningless and would look exactly like the meaningful ones: a
    reconstructed baseline is read from the thread as it stands after analysis,
    so its "before" already contains the after. Comparing them would produce a
    tidy, entirely fictional delta.

    So no movements are computed and none are reported. Emitting them as a
    "retrospective, caveat applies" section would leave a figure on the page
    that a reader — or a later renderer, or an export — could lift out of its
    caveat. The state at reconstruction is still published in the report; what
    is withheld is the comparison, because there is nothing honest to compare.
    """
    if capture != CAPTURE_CONTEMPORANEOUS:
        return {
            'verdict': VERDICT_UNVERIFIED,
            'verified_comparison': False,
            'capture': capture,
            'capture_reason': capture_reason,
            'withheld_reason': WITHHELD_REASONS.get(
                capture_reason,
                'This baseline was not captured before analysis began.',
            ),
            'routes_satisfied': [],
            'moved': [],
            'unmoved': [],
            'interventions': [],
            'not_applicable': [],
            'excluded_unconfirmed': [],
            'attribution_cap_applied': False,
            'user_visible_events': user_visible_events,
            'thresholds': dict(THRESHOLDS),
            'methodology_version': IMPACT_METHODOLOGY_VERSION,
        }

    moved, unmoved, not_applicable, excluded_unconfirmed = [], [], [], []

    # State measures only. Interventions are handled below and never enter
    # moved/unmoved, because there is no Before for them to have moved from.
    for measure_id in STATE_MEASURES:
        spec = MEASURES[measure_id]
        before = baseline_measures.get(measure_id) or _not_measurable('absent from baseline')
        after = closing_measures.get(measure_id) or _not_measurable('absent from closing state')

        if before.get('value') is None or after.get('value') is None:
            reason = before.get('reason') or after.get('reason') or 'not measurable'
            not_applicable.append({'id': measure_id, 'label': spec['label'], 'reason': reason})
            continue
        if before.get('basis') == BASIS_PROPOSED_UNCONFIRMED:
            excluded_unconfirmed.append({
                'id': measure_id, 'label': spec['label'],
                'reason': 'baseline value never confirmed',
            })
            continue
        if not _eligible(before) or not _eligible(after):
            not_applicable.append({
                'id': measure_id, 'label': spec['label'], 'reason': 'ineligible basis',
            })
            continue

        movement = _movement(measure_id, before, after)
        if movement:
            moved.append(movement)
        else:
            unmoved.append({
                'id': measure_id, 'label': spec['label'],
                'from': before['value'], 'to': after['value'],
            })

    # Interventions: reported as work done, with a threshold each. They can
    # carry the verification route, but never as a delta.
    interventions = []
    for measure_id in INTERVENTION_MEASURES:
        entry = closing_measures.get(measure_id) or {}
        value = _int_or_zero(entry.get('value'))
        limits = INTERVENTION_THRESHOLDS[measure_id]
        strong_at = limits['strong']
        interventions.append({
            'id': measure_id,
            'label': MEASURES[measure_id]['label'],
            'family': MEASURES[measure_id]['family'],
            'count': value,
            'qualifying': value >= limits['qualifying'],
            'strong': bool(strong_at is not None and value >= strong_at),
            'threshold': limits['qualifying'],
            'strong_threshold': strong_at,
        })

    moved_ids = {m['id'] for m in moved}
    family_a = [m for m in moved if m['family'] == FAMILY_STRUCTURE]
    family_b = [m for m in moved if m['family'] == FAMILY_VERIFICATION]
    qualifying_interventions = [i for i in interventions if i['qualifying']]

    # Verification signals of both kinds, counted once each. An intervention
    # counts once however many passes restated it, because the count behind it
    # is already distinct criteria rather than ledger rows.
    verification_signals = len(family_b) + len(qualifying_interventions)
    strong_verification = (
        any(m['strong'] for m in family_b)
        or any(i['strong'] for i in interventions)
    )

    # The multi-signal route needs at least one measured STATE change. Without
    # that clause a single stuck criterion satisfies it on its own — one
    # uncertainty labelled plus its exposure quantified is two signals about
    # the same unresolved thing, and calling that a material change to the
    # decision would be the breadth version of the repetition inflation the
    # distinct-intervention count already rules out.
    #
    # Verification-only impact still reaches Material on its own merits: three
    # assumptions validated (B4 strong) carries the route with no state change
    # at all, which is the "same recommendation, stronger basis" case.
    multi_signal = verification_signals >= 2 and bool(family_b)

    routes = []
    if len(family_a) >= 2 and moved_ids.intersection(ROUTE_1_QUALIFYING):
        routes.append('structural')
    if strong_verification or multi_signal:
        routes.append('verification')

    if routes:
        verdict = VERDICT_MATERIAL
    elif moved or qualifying_interventions:
        verdict = VERDICT_LIMITED
    else:
        verdict = VERDICT_NONE

    # The attribution cap (spec §5.4). Growth with no recorded, user-visible
    # analytical work behind it may simply be a user who typed more. We will
    # not call that Jaspen's impact, and we say so in the report rather than
    # applying it quietly.
    cap_applied = False
    if verdict == VERDICT_MATERIAL and user_visible_events <= 0:
        verdict = VERDICT_LIMITED
        cap_applied = True

    return {
        'verdict': verdict,
        # The comparison was made against a baseline captured in time. This is
        # the flag any future eligibility question keys off; it is a fact about
        # the evidence, not a commercial term.
        'verified_comparison': True,
        'capture': capture,
        'capture_reason': capture_reason,
        'withheld_reason': None,
        'routes_satisfied': routes,
        'moved': moved,
        'unmoved': unmoved,
        # Reported separately from moved/unmoved throughout, so no renderer can
        # accidentally present work Jaspen did as a property of the decision
        # that changed.
        'interventions': interventions,
        'not_applicable': not_applicable,
        'excluded_unconfirmed': excluded_unconfirmed,
        'attribution_cap_applied': cap_applied,
        'user_visible_events': user_visible_events,
        'thresholds': dict(THRESHOLDS),
        'methodology_version': IMPACT_METHODOLOGY_VERSION,
    }


# ---------------------------------------------------------------------------
# "What changed" — the deterministic template (spec §8)
# ---------------------------------------------------------------------------

VERDICT_OPENING = {
    VERDICT_MATERIAL: 'The decision record changed materially between submission and close.',
    VERDICT_LIMITED: 'The decision record changed between submission and close, within limits.',
    VERDICT_NONE: 'The decision closed in substantially the state it was submitted.',
    VERDICT_UNVERIFIED: 'This decision has no verified starting point, so no before-and-after '
                        'comparison can be made for it.',
}


def compose_narrative(impact, context):
    """Prose assembled from computed values only.

    Phase 1 renders the template. Phase 3 may hand the same deltas to a model,
    under the containment rules in spec §8 — and this template stays as the
    fallback, because the evidence layer must never depend on a model being
    reachable.
    """
    sentences = [VERDICT_OPENING[impact['verdict']]]

    # An unverified baseline gets the reason and nothing else. Anything further
    # would be prose about a comparison that was not made.
    if impact['verdict'] == VERDICT_UNVERIFIED:
        sentences.append(impact['withheld_reason'])
        sentences.append(
            'The current state of the decision is shown below and is accurate; '
            'what is missing is the record of what preceded it.'
        )
        return ' '.join(sentences)

    if impact['moved']:
        for movement in impact['moved'][:4]:
            if MEASURES[movement['id']]['kind'] == KIND_PCT:
                sentences.append(
                    f"{movement['label']} moved from {movement['from']}% to {movement['to']}%."
                )
            elif MEASURES[movement['id']]['kind'] == KIND_GRADES:
                sentences.append(
                    f"{movement['delta']} more criteria now stand at high or medium evidence."
                )
            else:
                sentences.append(
                    f"{movement['label']} went from {movement['from']} to {movement['to']}."
                )

    for intervention in impact.get('interventions', []):
        if intervention['qualifying']:
            sentences.append(
                f"Jaspen recorded {intervention['count']} "
                f"{intervention['label'].lower()}."
            )

    unmoved_labels = [entry['label'].lower() for entry in impact['unmoved'][:3]]
    if unmoved_labels:
        sentences.append('Unchanged: ' + ', '.join(unmoved_labels) + '.')

    if impact['attribution_cap_applied']:
        sentences.append(
            'No challenge or validation activity was recorded for this decision, so the '
            'change above is reported without attributing it to Jaspen.'
        )

    if impact['excluded_unconfirmed']:
        sentences.append(
            f"{len(impact['excluded_unconfirmed'])} measures were left out because their "
            'intake values were never confirmed.'
        )

    if context.get('leading_option'):
        sentences.append(f"The leading option is {context['leading_option']}.")

    return ' '.join(sentences)


# ---------------------------------------------------------------------------
# Assembly (spec §6)
# ---------------------------------------------------------------------------

PROVENANCE_NOTE = (
    'This report describes the state of the decision record, not the quality of '
    'the decision or its likely outcome. Before and After are two states of one '
    'decision, not a worse state and a better one. Every figure is counted by '
    'code from what was persisted; none was authored by a model.'
)

RECONSTRUCTED_NOTE = (
    'This decision has no baseline captured before analysis began. The state '
    'shown under Before was assembled afterwards, includes what was said during '
    'and after the analysis, and is not a record of what was originally '
    'submitted. No before-and-after comparison is made for this decision.'
)


def build_impact_report(user, thread_id, epoch=1):
    """The full report. Raises LookupError with no sealed baseline."""
    baseline = get_baseline(user.id, thread_id, epoch)
    if baseline is None or not baseline.is_sealed:
        raise LookupError(
            f'no sealed baseline for thread {thread_id}; the decision has no recorded '
            'starting point to compare against'
        )

    intact, problem = verify_baseline_integrity(baseline)
    if not intact:
        raise ValueError(f'baseline integrity check failed: {problem}')

    from .decision_ledger import counts_by_type, thread_events

    baseline_measures = baseline.measures if isinstance(baseline.measures, dict) else {}
    closing_measures, context = current_measures(user.id, thread_id)
    all_events = thread_events(user.id, thread_id, epoch)
    visible_events = [event for event in all_events if event.user_visible]
    impact = evaluate_impact(
        baseline_measures,
        closing_measures,
        user_visible_events=_user_visible_event_count(user.id, thread_id, epoch),
        capture=baseline.capture,
        capture_reason=baseline.capture_reason,
    )

    # The narrative is composed last and from the finished impact block, so it
    # can only ever describe what the rest of the report already established.
    from .decision_narrative import compose as compose_what_changed
    narrative_text, generated_by, model_id = compose_what_changed(
        impact, context, template=compose_narrative(impact, context),
    )

    return {
        'schema_version': IMPACT_SCHEMA_VERSION,
        'methodology_version': IMPACT_METHODOLOGY_VERSION,
        'thread_id': str(thread_id),
        'epoch': int(epoch),
        'generated_at': datetime.utcnow().isoformat(),
        'baseline': {
            'sealed_at': baseline.sealed_at.isoformat(),
            'sealed_by': baseline.sealed_by,
            # Whether this is a before state at all. Renderers key their
            # heading off this: a reconstructed baseline may never be labelled
            # "what Jaspen received" without qualification (spec §7.4).
            'capture': baseline.capture,
            'capture_reason': baseline.capture_reason,
            'verified_comparison': baseline.is_contemporaneous,
            'submission_hash': baseline.submission_hash,
            'measures_hash': baseline.measures_hash,
            'content_hash': baseline.content_hash,
            'readiness_spec_version': baseline.readiness_spec_version,
            'measures': baseline_measures,
            'submission_ref': baseline.submission_ref(),
        },
        'activity': {
            'counts_by_type': counts_by_type(user.id, thread_id, epoch),
            # User-visible events only. One that nobody could observe did not
            # challenge anyone, and listing it would pad the section that is
            # supposed to be the evidence of intervention.
            'events': [event.to_dict() for event in visible_events],
            'suppressed_non_visible': len(all_events) - len(visible_events),
            'available': True,
            'reason': None,
        },
        'current': {
            'measured_at': datetime.utcnow().isoformat(),
            'measures': closing_measures,
            'leading_option': context.get('leading_option'),
        },
        'impact': impact,
        'narrative': {
            'what_changed': narrative_text,
            'generated_by': generated_by,
            'grounded_in': {
                'measures': (
                    [m['id'] for m in impact['moved']]
                    + [i['id'] for i in impact['interventions'] if i['qualifying']]
                ),
                'events': [event.id for event in visible_events],
            },
            'model_id': model_id,
            'generated_at': datetime.utcnow().isoformat(),
        },
        'measure_catalog': {
            measure_id: {
                'label': spec['label'], 'family': spec['family'],
                'kind': spec['kind'], 'class': spec['class'],
            }
            for measure_id, spec in MEASURES.items()
        },
        'provenance_note': PROVENANCE_NOTE,
        'reconstruction_note': (
            None if baseline.is_contemporaneous else RECONSTRUCTED_NOTE
        ),
    }
