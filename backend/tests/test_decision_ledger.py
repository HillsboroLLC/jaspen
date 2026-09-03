"""The challenge ledger — acceptance tests.

docs/DECISION_IMPACT_REPORT_SPEC.md §4 and §10. Written against the claims the
ledger is supposed to license: that Jaspen challenged something, that it
validated something, and that a retry did not make either look larger.

The ledger is the thing that lifts the attribution cap, so the tests that
matter most are the ones proving it CANNOT be inflated: by a retry, by a
cosmetic edit, by a backfill, or by a blank field being mistaken for an
uncertainty someone made explicit.
"""

import pathlib

import pytest

from app.decision_ledger import (
    cap_qualifying_event_count,
    counts_by_type,
    record_generated_plan,
    record_scoring_pass,
    targets_with_event,
    thread_events,
)
from app.models_challenge_event import (
    ACTOR_JASPEN,
    CAP_QUALIFYING_TYPES,
    EVENT_ASSUMPTION_LEFT_OPEN,
    EVENT_ASSUMPTION_RESOLVED,
    EVENT_DEPENDENCY_SURFACED,
    EVENT_EVIDENCE_REQUESTED,
    EVENT_EXPOSURE_QUANTIFIED,
    EVENT_TYPES,
    TARGET_CRITERION,
    ChallengeEvent,
)

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def _dims(**criteria):
    """dimensions payload: key -> (score, confidence, ask)."""
    return {
        key: {
            'label': key.title(),
            'score': spec[0],
            'raw_score': spec[0],
            'confidence': spec[1],
            'what_would_improve': spec[2],
        }
        for key, spec in criteria.items()
    }


def _payload(dimensions, weights=None, run='run-1'):
    """`run` is the evaluation_id: a NEW scoring pass gets a new one, a retry
    of the same pass carries the one already persisted."""
    return {
        'id': 'card-1',
        'evaluation_id': run,
        'dimensions': dimensions,
        'scoring_weights': weights or {key: 1.0 for key in dimensions},
    }


def _pass(db, user, previous, new, scorecard_id='card-1'):
    events = record_scoring_pass(
        user_id=user.id,
        thread_id='t-ledger',
        scorecard_id=scorecard_id,
        previous_payload=previous,
        new_payload=new,
    )
    db.session.commit()
    return events


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------

def test_at27_every_event_type_has_a_real_emitter():
    """AT-27 A type with no call site is removed, never left aspirational."""
    emitters = (BACKEND / 'app' / 'decision_ledger.py').read_text()
    for event_type in EVENT_TYPES:
        constant = f'EVENT_{event_type.upper()}'
        assert constant in emitters, f'{event_type} has no emitter'


def test_at27b_the_taxonomy_did_not_grow_to_fit_what_is_easy_to_log():
    """AT-27b Five types, and no type invented because a system action was
    convenient to record. The three absentees are absent because no call site
    can establish who authored the thing (spec §4.5)."""
    assert set(EVENT_TYPES) == {
        EVENT_EVIDENCE_REQUESTED,
        EVENT_ASSUMPTION_RESOLVED,
        EVENT_ASSUMPTION_LEFT_OPEN,
        EVENT_EXPOSURE_QUANTIFIED,
        EVENT_DEPENDENCY_SURFACED,
    }
    for absent in ('criterion_added', 'alternative_introduced', 'weighting_challenged'):
        assert absent not in EVENT_TYPES


# ---------------------------------------------------------------------------
# Emission from a real scoring pass
# ---------------------------------------------------------------------------

def test_an_unsupported_criterion_with_an_ask_records_evidence_requested(db, test_user):
    _pass(db, test_user, None, _payload(_dims(
        cost=(80, 'assumed', 'Share the FY25 spend export.'),
        risk=(70, 'high', None),
    )))

    events = thread_events(test_user.id, 't-ledger')
    requested = [e for e in events if e.type == EVENT_EVIDENCE_REQUESTED]
    assert [e.target_id for e in requested] == ['cost']
    assert requested[0].target_kind == TARGET_CRITERION
    assert requested[0].actor == ACTOR_JASPEN
    assert requested[0].user_visible is True
    # The trigger records the STATE, so the row is checkable rather than asserted.
    assert requested[0].trigger['grade'] == 'assumed'
    assert requested[0].trigger['resolution_ask_recorded'] is True


def test_an_unsupported_criterion_without_an_ask_is_not_a_challenge(db, test_user):
    """A blank field is not a challenge. Jaspen has to have said something.

    The criterion's exposure is still quantified — that is a separate, real
    finding — but nothing here claims Jaspen asked for evidence.
    """
    _pass(db, test_user, None, _payload(_dims(cost=(80, 'assumed', None))))
    types = {e.type for e in thread_events(test_user.id, 't-ledger')}
    assert EVENT_EVIDENCE_REQUESTED not in types
    assert EVENT_ASSUMPTION_LEFT_OPEN not in types


def test_a_grade_rising_to_evidenced_records_assumption_resolved(db, test_user):
    first = _payload(_dims(cost=(80, 'assumed', 'Share the spend export.')))
    _pass(db, test_user, None, first)
    _pass(db, test_user, first, _payload(_dims(cost=(80, 'high', None)), run='run-2'))

    resolved = [e for e in thread_events(test_user.id, 't-ledger')
                if e.type == EVENT_ASSUMPTION_RESOLVED]
    assert [e.target_id for e in resolved] == ['cost']
    assert resolved[0].trigger == {'grade': 'high', 'previous_grade': 'assumed'}


def test_a_criterion_that_arrives_evidenced_was_not_resolved_by_us(db, test_user):
    """Nothing to resolve: it never stood on an assumption in this thread."""
    _pass(db, test_user, None, _payload(_dims(cost=(80, 'high', None))))
    assert targets_with_event(test_user.id, 't-ledger', EVENT_ASSUMPTION_RESOLVED) == set()


def test_at61_assumption_left_open_means_jaspen_said_so_again(db, test_user):
    """AT-61 The requirement that it is an uncertainty made explicit, not a
    field that happened to stay blank.

    It can only be reached by a criterion Jaspen ALREADY challenged, which was
    re-scored, and which Jaspen flagged again. A criterion nobody ever asked
    about cannot arrive here however empty it is.
    """
    first = _payload(_dims(cost=(80, 'assumed', 'Share the spend export.')), run='run-1')
    _pass(db, test_user, None, first)
    _pass(db, test_user, first, _payload(_dims(
        cost=(80, 'assumed', 'Still need the spend export.'),
    ), run='run-2'))

    left_open = targets_with_event(test_user.id, 't-ledger', EVENT_ASSUMPTION_LEFT_OPEN)
    assert left_open == {'cost'}

    # A criterion seen once, never challenged, never reaches it.
    assert 'risk' not in left_open


def test_material_exposure_is_recorded_and_trivial_exposure_is_not(db, test_user):
    """Below the materiality line the arithmetic is real; the finding is not
    worth claiming."""
    _pass(db, test_user, None, _payload(
        _dims(
            cost=(100, 'assumed', 'Share the export.'),   # capped 45, big swing
            speed=(46, 'assumed', 'Share the export.'),   # capped 45, ~1pt swing
        ),
        weights={'cost': 0.5, 'speed': 0.5},
    ))
    quantified = targets_with_event(test_user.id, 't-ledger', EVENT_EXPOSURE_QUANTIFIED)
    assert 'cost' in quantified
    assert 'speed' not in quantified


# ---------------------------------------------------------------------------
# Idempotence — a retry is not more thinking
# ---------------------------------------------------------------------------

def test_at28_a_repeated_scoring_pass_adds_no_events(db, test_user):
    """AT-28 The requirement that a retry cannot inflate the record.

    The same run arriving again — same evaluation_id — must add nothing at all,
    including no "still unresolved" finding, because nothing was re-examined.
    """
    payload = _payload(_dims(cost=(100, 'assumed', 'Share the export.')), run='run-1')
    _pass(db, test_user, None, payload)
    before = ChallengeEvent.query.filter_by(user_id=test_user.id).count()
    assert before > 0

    for _ in range(4):
        _pass(db, test_user, payload, payload)      # the retry: same run id

    assert ChallengeEvent.query.filter_by(user_id=test_user.id).count() == before


def test_at28b_the_database_refuses_a_duplicate_even_if_the_code_does_not(db, test_user):
    """AT-28b Idempotence is a constraint, not a convention."""
    from sqlalchemy.exc import IntegrityError

    _pass(db, test_user, None, _payload(_dims(cost=(80, 'assumed', 'Share it.'))))
    original = ChallengeEvent.query.filter_by(user_id=test_user.id).first()

    db.session.add(ChallengeEvent(
        user_id=original.user_id, thread_id=original.thread_id, epoch=original.epoch,
        seq=99, type=original.type, origin=original.origin, actor=original.actor,
        trigger={}, dedupe_key=original.dedupe_key,
    ))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_at30_seq_is_monotonic_within_a_thread(db, test_user):
    """AT-30"""
    first = _payload(_dims(cost=(90, 'assumed', 'Share it.'), risk=(90, 'low', 'Get data.')))
    _pass(db, test_user, None, first)
    _pass(db, test_user, first, _payload(_dims(
        cost=(90, 'high', None), risk=(90, 'low', 'Still need data.'),
    ), run='run-2'))

    seqs = [e.seq for e in thread_events(test_user.id, 't-ledger')]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)


def test_at29_nothing_updates_or_deletes_an_event():
    """AT-29 Append-only, checked against the source rather than trusted."""
    ledger = (BACKEND / 'app' / 'decision_ledger.py').read_text()
    for forbidden in ('db.session.delete', '.delete()', '.update('):
        assert forbidden not in ledger


# ---------------------------------------------------------------------------
# What must NOT produce ledger entries
# ---------------------------------------------------------------------------

def test_at62_only_a_real_scoring_pass_may_write_events(db, test_user):
    """AT-62 Renames, in-place prose edits, display overrides and backfills all
    reach upsert_scorecard. None of them is analysis."""
    import inspect as _inspect
    from app.scorecards import upsert_scorecard

    assert _inspect.signature(upsert_scorecard).parameters['analysis_pass'].default is False

    upsert_scorecard(
        user_id=test_user.id, thread_id='t-ledger',
        payload=_payload(_dims(cost=(80, 'assumed', 'Share the export.'))),
    )
    db.session.commit()
    assert ChallengeEvent.query.filter_by(user_id=test_user.id).count() == 0


def test_at62b_the_scoring_flag_is_set_only_at_genuine_analysis_call_sites():
    """AT-62b Ten call sites reach upsert_scorecard; three are analysis."""
    strategy = (BACKEND / 'app' / 'routes' / 'strategy.py').read_text()
    agent = (BACKEND / 'app' / 'routes' / 'ai_agent.py').read_text()
    scorecards = (BACKEND / 'app' / 'scorecards.py').read_text()

    assert strategy.count('analysis_pass=True') == 2      # /analyze, /score-batch
    assert agent.count('analysis_pass=True') == 2         # generate_scorecard, rescore
    # Backfill and tombstone paths must never opt in.
    assert 'analysis_pass=True' not in scorecards


def test_at63_a_user_edited_plan_does_not_surface_dependencies():
    """AT-63 A dependency the user typed into their own plan is theirs.

    Only the two AI generation paths call the recorder; the plan-editing routes
    do not, and that is the whole control.
    """
    strategy = (BACKEND / 'app' / 'routes' / 'strategy.py').read_text()
    agent = (BACKEND / 'app' / 'routes' / 'ai_agent.py').read_text()
    assert strategy.count('record_generated_plan(') == 1
    assert agent.count('record_generated_plan(') == 1


def test_a_generated_plan_records_its_dependencies(db, test_user):
    record_generated_plan(
        user_id=test_user.id,
        thread_id='t-ledger',
        plan={'tasks': [
            {'id': 'task-2', 'title': 'Sign vendor', 'depends_on': ['task-1']},
            {'id': 'task-1', 'title': 'Validate spend', 'depends_on': []},
        ]},
    )
    db.session.commit()

    surfaced = targets_with_event(test_user.id, 't-ledger', EVENT_DEPENDENCY_SURFACED)
    assert surfaced == {'task-1->task-2'}


def test_regenerating_the_same_plan_adds_nothing(db, test_user):
    plan = {'tasks': [{'id': 'b', 'title': 'B', 'depends_on': ['a']}]}
    for _ in range(3):
        record_generated_plan(user_id=test_user.id, thread_id='t-ledger', plan=plan)
        db.session.commit()
    assert ChallengeEvent.query.filter_by(user_id=test_user.id).count() == 1


# ---------------------------------------------------------------------------
# The attribution cap
# ---------------------------------------------------------------------------

def test_at64_the_cap_counts_only_observable_qualifying_events(db, test_user):
    """AT-64 Invisible work did not challenge anyone."""
    _pass(db, test_user, None, _payload(_dims(cost=(90, 'assumed', 'Share it.'))))
    assert cap_qualifying_event_count(test_user.id, 't-ledger') >= 1

    for hidden in ChallengeEvent.query.filter_by(user_id=test_user.id).all():
        hidden.user_visible = False
    db.session.commit()
    assert cap_qualifying_event_count(test_user.id, 't-ledger') == 0


def test_at64b_the_cap_set_is_declared_separately_from_the_taxonomy():
    """AT-64b So a bookkeeping type can enter the ledger without entering the
    count."""
    from app import models_challenge_event as mod

    assert 'CAP_QUALIFYING_TYPES' in dir(mod)
    assert CAP_QUALIFYING_TYPES <= set(EVENT_TYPES)


def test_counts_by_type_reports_only_visible_events(db, test_user):
    _pass(db, test_user, None, _payload(_dims(
        cost=(90, 'assumed', 'Share it.'), risk=(90, 'low', 'Get data.'),
    )))
    counts = counts_by_type(test_user.id, 't-ledger')
    assert counts.get(EVENT_EVIDENCE_REQUESTED) == 2


# ---------------------------------------------------------------------------
# Identity across the lifecycle
# ---------------------------------------------------------------------------

def test_at65_events_on_one_criterion_connect_across_passes(db, test_user):
    """AT-65 A challenge and its later resolution are the same criterion, not
    two unrelated counts."""
    first = _payload(_dims(cost=(80, 'assumed', 'Share the spend export.')))
    _pass(db, test_user, None, first)
    _pass(db, test_user, first, _payload(_dims(cost=(80, 'high', None)), run='run-2'))

    by_target = {}
    for event in thread_events(test_user.id, 't-ledger'):
        by_target.setdefault(event.target_id, []).append(event.type)

    assert EVENT_EVIDENCE_REQUESTED in by_target['cost']
    assert EVENT_ASSUMPTION_RESOLVED in by_target['cost']


def test_at66_no_model_output_becomes_a_ledger_fact():
    """AT-66 A model may author the challenge's wording; it may not author the
    fact. No emitter reaches a model client, and no event stores prose."""
    ledger = (BACKEND / 'app' / 'decision_ledger.py').read_text().lower()
    code = '\n'.join(l for l in ledger.splitlines() if not l.strip().startswith('#'))
    for token in ('anthropic', 'openai', 'genai', 'gemini', 'call_llm', 'client'):
        assert token not in code

    # The ask's WORDING is never persisted — only the fact that one exists.
    assert "'resolution_ask_recorded': True" in (
        BACKEND / 'app' / 'decision_ledger.py'
    ).read_text()
