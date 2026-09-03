"""Decision Impact Report — the acceptance tests from the spec.

docs/DECISION_IMPACT_REPORT_SPEC.md §10. Test IDs in the docstrings map to the
spec so a reader can check coverage against the contract rather than against
the implementation.

The report's whole value is that someone who does not trust us can recompute
it, so these are written against the claims: what the baseline preserves, what
may move a verdict, and what the report must refuse to say.
"""

import ast
import copy
import pathlib

import pytest

from app.decision_impact import (
    BASIS_DETERMINISTIC,
    BASIS_PROPOSED_UNCONFIRMED,
    BASIS_USER_CONFIRMED,
    MATERIALITY_PP,
    MEASURES,
    STATE_MEASURES,
    STRONG_PP,
    THRESHOLDS,
    VERDICT_LIMITED,
    VERDICT_MATERIAL,
    VERDICT_NONE,
    build_impact_report,
    build_submission_payload,
    canonical_json,
    capture_or_update_draft,
    content_digest,
    current_measures,
    derive_baseline_measures,
    evaluate_impact,
    evidence_backed_pct_from_grades,
    get_baseline,
    rederive_baseline_measures,
    seal_baseline,
    seal_baseline_on_analysis_start,
    VERDICT_UNVERIFIED,
    verify_baseline_integrity,
)
from app.models_decision_baseline import (
    CAPTURE_CONTEMPORANEOUS,
    CAPTURE_RECONSTRUCTED,
    RECONSTRUCTED_LATE_SEAL,
    RECONSTRUCTED_NO_CAPTURE,
    SEALED_BY_ANALYSIS,
    SEALED_BY_USER,
    DecisionBaseline,
    SealedBaselineError,
)

BACKEND = pathlib.Path(__file__).resolve().parents[1]
IMPACT_MODULES = (
    BACKEND / 'app' / 'decision_impact.py',
    BACKEND / 'app' / 'models_decision_baseline.py',
    BACKEND / 'app' / 'routes' / 'decision_impact.py',
)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _m(value, basis=BASIS_DETERMINISTIC, reason=None):
    entry = {'value': value, 'basis': basis}
    if reason:
        entry['reason'] = reason
    return entry


def _measure_set(**overrides):
    """A complete measure set. Anything not overridden sits still.

    Interventions default to zero work recorded: a fixture should have to ask
    for Jaspen to have done something.
    """
    base = {
        'A1': _m(2), 'A2': _m(5), 'A3': _m(5), 'A4': _m(1), 'A5': _m(0), 'A6': _m(3),
        'B1': _m(40), 'B2': _m(60), 'B3': _m({'high': 0, 'medium': 1, 'low': 2, 'assumed': 2}),
        'B4': _m(0), 'B5': _m(0), 'B6': _m(0),
    }
    base.update(overrides)
    return base


def _structure(**overrides):
    structure = {
        'alternatives': ['Option A', 'Option B'],
        'criteria': [
            {'key': 'c1', 'label': 'Cost', 'backed_by_source': True, 'quantified': True, 'weight': None},
            {'key': 'c2', 'label': 'Risk', 'backed_by_source': False, 'quantified': False, 'weight': None},
        ],
        'assumptions': ['Demand holds'],
        'risks': ['Vendor lock-in'],
        'dependencies': [],
        'sources': ['FY25 spend export'],
        'confirmed': True,
    }
    structure.update(overrides)
    return structure


def _session(chat=('We are choosing between two vendors to cut spend by 15% by Q3.',)):
    return {
        'session_id': 'thread-impact',
        'name': 'Vendor consolidation',
        'strategy_objective': 'cost',
        'chat_history': [{'role': 'user', 'content': text} for text in chat],
    }


def _seed_thread(db, user, thread_id='thread-impact', chat=None, rubric=None, cards=None):
    from app.models import Scorecard, UserSession

    payload = _session(chat=chat or ('We are choosing between two vendors to cut spend by 15% by Q3.',))
    payload['session_id'] = thread_id
    if rubric:
        payload['scoring_rubric'] = rubric

    db.session.add(UserSession(
        user_id=user.id,
        session_id=thread_id,
        name='Vendor consolidation',
        created_by_user_id=user.id,
        payload=payload,
        scenarios_json={},
    ))
    db.session.commit()
    if cards:
        _add_cards(db, user, thread_id, cards)


def _add_cards(db, user, thread_id, cards):
    """Analysis output arriving on a thread."""
    from app.models import Scorecard

    for card in cards:
        db.session.add(Scorecard(
            id=card['id'],
            user_id=user.id,
            thread_id=thread_id,
            evaluation_id=card['id'],
            project_name=card['name'],
            score=card['score'],
            assumptions=[],
            evidence=[],
            data=card['data'],
        ))
    db.session.commit()


# ---------------------------------------------------------------------------
# Measurement — determinism, identity, nulls, provenance
# ---------------------------------------------------------------------------

def test_at20_measures_are_deterministic():
    """AT-20 Two runs over identical inputs produce identical measure sets."""
    submission = build_submission_payload(_session(), _structure())
    assert derive_baseline_measures(submission) == derive_baseline_measures(submission)
    assert canonical_json(derive_baseline_measures(submission)) == canonical_json(
        derive_baseline_measures(copy.deepcopy(submission))
    )


def test_at21_and_25c_no_model_client_in_the_measure_or_sealing_path():
    """AT-21 / AT-25c No model client is reachable from measurement or sealing."""
    forbidden = ('anthropic', 'openai', 'genai', 'gemini', 'litellm', 'call_llm')
    for path in IMPACT_MODULES:
        source = path.read_text().lower()
        # Strip comments: these modules discuss models at length in prose, and
        # the rule is about imports and calls, not about what may be explained.
        code = '\n'.join(
            line for line in source.splitlines() if not line.strip().startswith('#')
        )
        for token in forbidden:
            assert token not in code, f'{path.name} reaches a model client via {token!r}'


def test_at22_renaming_a_criterion_produces_no_movement():
    """AT-22 Identity is the stable key, never the label."""
    before = derive_baseline_measures(build_submission_payload(_session(), _structure()))
    renamed = _structure(criteria=[
        {'key': 'c1', 'label': 'Total cost of ownership', 'backed_by_source': True, 'quantified': True, 'weight': None},
        {'key': 'c2', 'label': 'Delivery risk', 'backed_by_source': False, 'quantified': False, 'weight': None},
    ])
    after = derive_baseline_measures(build_submission_payload(_session(), renamed))
    assert before == after

    impact = evaluate_impact(before, after, user_visible_events=5)
    assert impact['moved'] == []
    assert impact['verdict'] == VERDICT_NONE


def test_at23_null_measures_are_excluded_and_named():
    """AT-23 A null measure sits in not_applicable, never in the predicate."""
    before = _measure_set(A5=_m(None, reason='no implementation phase in scope'))
    after = _measure_set(A5=_m(4))
    impact = evaluate_impact(before, after, user_visible_events=5)

    assert 'A5' not in {m['id'] for m in impact['moved']}
    assert 'A5' not in {m['id'] for m in impact['unmoved']}
    entry = next(e for e in impact['not_applicable'] if e['id'] == 'A5')
    assert entry['reason'] == 'no implementation phase in scope'


def test_at25_b2_never_satisfies_a_movement_test():
    """AT-25 B2 is B1's complement; counting it would double-count."""
    before = _measure_set(B1=_m(40), B2=_m(60))
    after = _measure_set(B1=_m(75), B2=_m(25))
    impact = evaluate_impact(before, after, user_visible_events=5)

    moved = {m['id'] for m in impact['moved']}
    assert 'B1' in moved
    assert 'B2' not in moved
    assert 'B2' in {m['id'] for m in impact['unmoved']}


def test_at25b_every_baseline_measure_carries_a_basis():
    """AT-25b A measure without a basis is a write error, not a default."""
    measures = derive_baseline_measures(build_submission_payload(_session(), _structure()))
    # State measures only: an intervention has no Before (spec §2.5).
    assert set(measures) == set(STATE_MEASURES)
    for measure_id, entry in measures.items():
        assert entry['basis'] in (
            BASIS_DETERMINISTIC, BASIS_USER_CONFIRMED, BASIS_PROPOSED_UNCONFIRMED,
        ), measure_id


def test_baseline_evidence_share_uses_the_same_arithmetic_as_the_closing_measure():
    """Baseline B1 and closing B1 must be one measure, not two that resemble
    each other (spec §2.4). Held by test because a comment cannot hold it."""
    from app.decision_confidence import criterion_entries, evidence_ratio

    dimensions = {
        'cost': {'label': 'Cost', 'score': 80, 'confidence': 'high'},
        'risk': {'label': 'Risk', 'score': 60, 'confidence': 'assumed'},
        'speed': {'label': 'Speed', 'score': 70, 'confidence': 'medium'},
    }
    weights = {'cost': 0.5, 'risk': 0.3, 'speed': 0.2}

    from_engine = evidence_ratio(criterion_entries(dimensions, weights))
    from_grades = evidence_backed_pct_from_grades([
        ('high', 0.5), ('assumed', 0.3), ('medium', 0.2),
    ])
    assert from_grades == from_engine


def test_unconfirmed_intake_yields_proposed_unconfirmed_measures():
    """A user who skips the correction window gets blanks, not invented zeros."""
    submission = build_submission_payload(_session(), _structure(confirmed=False))
    measures = derive_baseline_measures(submission)

    assert measures['A1']['basis'] == BASIS_PROPOSED_UNCONFIRMED
    # A6 is read off the readiness engine, so it stands on its own regardless.
    assert measures['A6']['basis'] == BASIS_DETERMINISTIC


def test_no_structure_means_no_invented_counts():
    submission = build_submission_payload(_session(), None)
    measures = derive_baseline_measures(submission)

    assert measures['A1']['value'] is None
    assert measures['A1']['reason'] == 'not established at intake'
    assert measures['A6']['value'] is not None


# ---------------------------------------------------------------------------
# The predicate
# ---------------------------------------------------------------------------

def test_at31_golden_no_material_change():
    """AT-31 A well-prepared intake with minor movement returns no material
    change. This test guards spec §1.6 and may not be weakened."""
    before = _measure_set(A1=_m(3), A2=_m(6), A3=_m(6), A4=_m(5), A5=_m(3), B1=_m(74))
    after = _measure_set(A1=_m(3), A2=_m(6), A3=_m(6), A4=_m(5), A5=_m(3), B1=_m(77))

    impact = evaluate_impact(before, after, user_visible_events=12)
    assert impact['verdict'] == VERDICT_NONE
    assert impact['moved'] == []
    assert impact['routes_satisfied'] == []


def test_at32_golden_same_recommendation_stronger_basis():
    """AT-32 Example A: nothing structural moves, verdict is material on the
    verification route alone."""
    before = _measure_set(
        A1=_m(2), A2=_m(5), A3=_m(5), A4=_m(1), A5=_m(0),
        B1=_m(38), B3=_m({'high': 0, 'medium': 1, 'low': 2, 'assumed': 2}),
    )
    after = _measure_set(
        A1=_m(2), A2=_m(5), A3=_m(5), A4=_m(3), A5=_m(2),
        B1=_m(71), B3=_m({'high': 2, 'medium': 2, 'low': 1, 'assumed': 0}),
        B4=_m(3), B6=_m(4),
    )

    impact = evaluate_impact(before, after, user_visible_events=9)
    assert impact['verdict'] == VERDICT_MATERIAL
    assert 'verification' in impact['routes_satisfied']

    moved = {m['id'] for m in impact['moved']}
    assert {'B1', 'B3'}.issubset(moved)
    # Interventions carry their own section and never appear as movement.
    assert not {'B4', 'B5', 'B6'} & moved
    assert not {'B4', 'B5', 'B6'} & {m['id'] for m in impact['unmoved']}
    quantified = next(i for i in impact['interventions'] if i['id'] == 'B6')
    assert quantified['count'] == 4 and quantified['qualifying'] is True
    # The alternatives and criteria did not move, and the report says so.
    assert {'A1', 'A2', 'A3'}.issubset({m['id'] for m in impact['unmoved']})


def test_at33_route_one_needs_a_qualifying_structural_measure():
    """AT-33 Peripheral growth alone is not structural reshaping."""
    before = _measure_set(A4=_m(1), A6=_m(2))
    after = _measure_set(A4=_m(4), A6=_m(5))

    impact = evaluate_impact(before, after, user_visible_events=9)
    assert 'structural' not in impact['routes_satisfied']
    assert impact['verdict'] == VERDICT_LIMITED


def test_at33b_route_one_fires_with_a_qualifying_measure():
    before = _measure_set(A1=_m(2), A2=_m(0), A5=_m(0), B1=_m(44))
    after = _measure_set(A1=_m(3), A2=_m(6), A5=_m(3), B1=_m(52))

    impact = evaluate_impact(before, after, user_visible_events=9)
    assert 'structural' in impact['routes_satisfied']
    assert impact['verdict'] == VERDICT_MATERIAL
    # +8pp points the right way but is below materiality, and is reported as
    # unmoved rather than rounded into the win.
    assert 'B1' in {m['id'] for m in impact['unmoved']}


@pytest.mark.parametrize('delta,moves,strong', [
    (MATERIALITY_PP - 1, False, False),
    (MATERIALITY_PP, True, False),
    (STRONG_PP - 1, True, False),
    (STRONG_PP, True, True),
])
def test_at34_percentage_thresholds_are_exact_at_the_boundary(delta, moves, strong):
    """AT-34 +9 does not move, +10 does, +19 is not strong, +20 is."""
    impact = evaluate_impact(
        _measure_set(B1=_m(40)), _measure_set(B1=_m(40 + delta)), user_visible_events=9,
    )
    entry = next((m for m in impact['moved'] if m['id'] == 'B1'), None)
    assert (entry is not None) is moves
    if entry:
        assert entry['strong'] is strong


def test_at35_attribution_cap_holds_the_verdict_at_limited():
    """AT-35 With no user-visible analytical work recorded, we do not claim
    the change as Jaspen's."""
    before = _measure_set(A1=_m(2), A2=_m(2), A5=_m(0), B1=_m(30))
    after = _measure_set(A1=_m(4), A2=_m(8), A5=_m(4), B1=_m(80))

    uncapped = evaluate_impact(before, after, user_visible_events=1)
    assert uncapped['verdict'] == VERDICT_MATERIAL
    assert uncapped['attribution_cap_applied'] is False

    capped = evaluate_impact(before, after, user_visible_events=0)
    assert capped['verdict'] == VERDICT_LIMITED
    assert capped['attribution_cap_applied'] is True
    # The routes are still reported: the cap changes the claim, not the facts.
    assert capped['routes_satisfied']


def test_at36_all_three_verdicts_are_reachable():
    """AT-36"""
    verdicts = {
        evaluate_impact(_measure_set(), _measure_set(), user_visible_events=9)['verdict'],
        evaluate_impact(
            _measure_set(A4=_m(1)), _measure_set(A4=_m(3)), user_visible_events=9,
        )['verdict'],
        evaluate_impact(
            _measure_set(B1=_m(30)), _measure_set(B1=_m(80)), user_visible_events=9,
        )['verdict'],
    }
    assert verdicts == {VERDICT_NONE, VERDICT_LIMITED, VERDICT_MATERIAL}


def test_at37_the_verdict_is_recomputable_by_hand():
    """AT-37 Everything needed to check the arithmetic is published."""
    impact = evaluate_impact(
        _measure_set(B1=_m(38)), _measure_set(B1=_m(71)), user_visible_events=9,
    )
    assert impact['thresholds'] == THRESHOLDS
    for movement in impact['moved']:
        assert {'id', 'from', 'to', 'delta', 'threshold'}.issubset(movement)
        assert movement['threshold'] in THRESHOLDS


def test_at38_unconfirmed_baseline_measures_cannot_move():
    """AT-38 Movement is measured against a baseline the user stood behind."""
    before = _measure_set(A1=_m(1, BASIS_PROPOSED_UNCONFIRMED))
    after = _measure_set(A1=_m(6))

    impact = evaluate_impact(before, after, user_visible_events=9)
    assert 'A1' not in {m['id'] for m in impact['moved']}
    entry = next(e for e in impact['excluded_unconfirmed'] if e['id'] == 'A1')
    assert entry['reason'] == 'baseline value never confirmed'


# ---------------------------------------------------------------------------
# Baseline integrity — the immutability contract
# ---------------------------------------------------------------------------

def test_at10_the_record_assembler_cannot_author_a_baseline(db, test_user):
    """AT-10 Only capture_baseline writes a baseline. Enforced by test."""
    source = (BACKEND / 'app' / 'decision_records.py').read_text()
    assert 'DecisionBaseline' not in source
    assert 'decision_baselines' not in source

    _seed_thread(db, test_user)
    from app.decision_records import create_or_refresh_record

    create_or_refresh_record(test_user, 'thread-impact')
    assert DecisionBaseline.query.filter_by(user_id=test_user.id).count() == 0


def test_at11_refreshing_the_decision_record_leaves_the_baseline_untouched(db, test_user):
    """AT-11 The hazard this table exists to avoid."""
    _seed_thread(db, test_user)
    capture_or_update_draft(test_user, 'thread-impact', structure=_structure())
    sealed = seal_baseline(test_user, 'thread-impact')
    before_hash, before_measures = sealed.content_hash, copy.deepcopy(sealed.measures)

    from app.decision_records import create_or_refresh_record
    create_or_refresh_record(test_user, 'thread-impact')
    create_or_refresh_record(test_user, 'thread-impact')

    after = get_baseline(test_user.id, 'thread-impact')
    assert after.content_hash == before_hash
    assert after.measures == before_measures


def test_at12_a_tampered_baseline_produces_no_report(db, test_user):
    """AT-12 No report at all beats a report that looks like evidence."""
    _seed_thread(db, test_user)
    capture_or_update_draft(test_user, 'thread-impact', structure=_structure())
    baseline = seal_baseline(test_user, 'thread-impact')

    tampered = copy.deepcopy(baseline.measures)
    tampered['A1'] = {'value': 99, 'basis': BASIS_USER_CONFIRMED}
    # Bypass the ORM guard the way a stray script would: write the column
    # directly. The hash is the backstop for exactly this.
    DecisionBaseline.query.filter_by(id=baseline.id).update(
        {'measures': tampered}, synchronize_session=False,
    )
    db.session.commit()
    db.session.expire_all()

    intact, problem = verify_baseline_integrity(get_baseline(test_user.id, 'thread-impact'))
    assert intact is False
    assert 'measures_hash' in problem

    with pytest.raises(ValueError, match='integrity'):
        build_impact_report(test_user, 'thread-impact')


def test_at13_a_sealed_baseline_refuses_mutation(db, test_user):
    """AT-13 Enforced at the ORM, so every path is covered."""
    _seed_thread(db, test_user)
    capture_or_update_draft(test_user, 'thread-impact', structure=_structure())
    baseline = seal_baseline(test_user, 'thread-impact')

    baseline.measures = {'A1': {'value': 99, 'basis': BASIS_USER_CONFIRMED}}
    with pytest.raises(SealedBaselineError):
        db.session.commit()
    db.session.rollback()


def test_at14_corrections_before_sealing_are_accepted(db, test_user):
    """AT-14 The correction window, doing its job."""
    _seed_thread(db, test_user)
    draft = capture_or_update_draft(test_user, 'thread-impact', structure=_structure())
    assert draft.measures['A1']['value'] == 2

    widened = capture_or_update_draft(
        test_user, 'thread-impact',
        structure=_structure(alternatives=['Option A', 'Option B', 'Option C']),
    )
    assert widened.measures['A1']['value'] == 3
    assert widened.is_sealed is False


def test_at15_corrections_after_sealing_are_rejected(db, test_user):
    """AT-15"""
    _seed_thread(db, test_user)
    capture_or_update_draft(test_user, 'thread-impact', structure=_structure())
    seal_baseline(test_user, 'thread-impact')

    with pytest.raises(SealedBaselineError):
        capture_or_update_draft(test_user, 'thread-impact', structure=_structure())


def test_at16_seal_records_who_sealed_it(db, test_user):
    """AT-16"""
    _seed_thread(db, test_user, thread_id='t-user')
    capture_or_update_draft(test_user, 't-user', structure=_structure())
    assert seal_baseline(test_user, 't-user').sealed_by == SEALED_BY_USER

    _seed_thread(db, test_user, thread_id='t-auto')
    auto = seal_baseline(test_user, 't-auto', sealed_by=SEALED_BY_ANALYSIS)
    assert auto.sealed_by == SEALED_BY_ANALYSIS
    # Nothing was confirmed, so nothing the window would have supplied counts.
    assert auto.measures['A1']['basis'] == BASIS_PROPOSED_UNCONFIRMED or \
        auto.measures['A1']['value'] is None


def test_at16b_sealing_is_idempotent(db, test_user):
    _seed_thread(db, test_user)
    capture_or_update_draft(test_user, 'thread-impact', structure=_structure())
    first = seal_baseline(test_user, 'thread-impact')
    sealed_at = first.sealed_at
    assert seal_baseline(test_user, 'thread-impact').sealed_at == sealed_at


def test_at17_a_baseline_exists_without_a_decision_record(db, test_user):
    """AT-17 The lifecycle reason this is its own table."""
    _seed_thread(db, test_user)
    from app.models_decision_record import DecisionRecord

    baseline = capture_or_update_draft(test_user, 'thread-impact', structure=_structure())
    assert baseline is not None
    assert DecisionRecord.query.filter_by(user_id=test_user.id).count() == 0

    from app.decision_records import create_or_refresh_record
    record, _ = create_or_refresh_record(test_user, 'thread-impact')
    assert record.thread_id == baseline.thread_id


def test_at18_link_two_is_rederivable_from_link_one(db, test_user):
    """AT-18 The property that makes the baseline self-verifying.

    A divergence here means the measurement engine changed without a
    methodology bump, and every report generated since is suspect.
    """
    _seed_thread(db, test_user)
    capture_or_update_draft(test_user, 'thread-impact', structure=_structure())
    baseline = seal_baseline(test_user, 'thread-impact')

    rederived = rederive_baseline_measures(baseline)
    deterministic = {
        measure_id: entry for measure_id, entry in baseline.measures.items()
        if entry['basis'] == BASIS_DETERMINISTIC
    }
    for measure_id, entry in deterministic.items():
        assert rederived[measure_id] == entry, measure_id
    assert rederived == baseline.measures


def test_at18b_the_submission_round_trips_verbatim(db, test_user):
    """AT-18b No normalization, no clipping, no reordering."""
    long_text = 'We are choosing between two vendors. ' + ('Detail. ' * 500)
    _seed_thread(db, test_user, chat=(long_text, 'Second turn with specifics: 15% by Q3.'))

    baseline = capture_or_update_draft(test_user, 'thread-impact', structure=_structure())
    turns = baseline.submission_payload['turns']

    assert [t['content'] for t in turns] == [long_text, 'Second turn with specifics: 15% by Q3.']
    assert turns[0]['content'] == long_text  # not clipped
    assert [t['index'] for t in turns] == sorted(t['index'] for t in turns)


def test_at18c_an_attachment_resolves_even_without_its_bytes():
    """AT-18c The chain resolves to a specific artifact, not a description."""
    session = _session()
    session['chat_history'][0]['attachments'] = [{
        'name': 'FY25-spend.xlsx',
        'type': 'application/vnd.ms-excel',
        'size': 88213,
        'content_hash': 'sha256:abc123',
        'url': 's3://uploads/fy25-spend.xlsx',
    }]
    submission = build_submission_payload(session, _structure())

    attachment = submission['attachments'][0]
    assert attachment['content_hash'] == 'sha256:abc123'
    assert attachment['locator'] == 's3://uploads/fy25-spend.xlsx'


def test_at19_raw_submission_does_not_travel_with_a_derived_export(db, test_user):
    """AT-19 Custody: the raw submission is Ring 1 and stays there."""
    _seed_thread(db, test_user)
    baseline = capture_or_update_draft(test_user, 'thread-impact', structure=_structure())

    exported = baseline.to_dict()
    assert 'submission_payload' not in exported
    assert exported['submission_ref']['baseline_id'] == baseline.id
    assert 'submission_payload' in baseline.to_dict(include_submission=True)


def test_hashes_identify_which_half_diverged(db, test_user):
    _seed_thread(db, test_user)
    capture_or_update_draft(test_user, 'thread-impact', structure=_structure())
    baseline = seal_baseline(test_user, 'thread-impact')

    assert baseline.submission_hash == content_digest(baseline.submission_payload)
    assert baseline.measures_hash == content_digest(baseline.measures)
    assert baseline.content_hash not in (baseline.submission_hash, baseline.measures_hash)


# ---------------------------------------------------------------------------
# Assembly and scope
# ---------------------------------------------------------------------------

def _card(name, score, grades):
    return {
        'id': name.lower().replace(' ', '-'),
        'name': name,
        'score': score,
        'data': {
            'project_name': name,
            'jaspen_score': score,
            'score_category': 'Good',
            'dimensions': {
                key: {'label': key.title(), 'score': 70, 'confidence': grade}
                for key, grade in grades.items()
            },
            'top_risks': ['Delivery ownership is not confirmed.'],
            'assumptions': [],
        },
    }


def test_the_report_carries_the_whole_contract(db, test_user):
    rubric = {'criteria': [
        {'key': 'cost', 'label': 'Cost', 'weight': 0.6},
        {'key': 'risk', 'label': 'Risk', 'weight': 0.4},
    ]}
    _seed_thread(db, test_user, rubric=rubric)
    capture_or_update_draft(test_user, 'thread-impact', structure=_structure())
    seal_baseline(test_user, 'thread-impact')
    _add_cards(db, test_user, 'thread-impact', [
        _card('Option A', 82, {'cost': 'high', 'risk': 'medium'}),
        _card('Option B', 68, {'cost': 'low', 'risk': 'assumed'}),
    ])

    report = build_impact_report(test_user, 'thread-impact')

    assert report['schema_version'] == 1
    assert report['baseline']['sealed_by'] == SEALED_BY_USER
    assert report['baseline']['capture'] == CAPTURE_CONTEMPORANEOUS
    assert report['reconstruction_note'] is None
    assert report['baseline']['submission_ref']['turn_count'] >= 1
    assert 'submission_payload' not in report['baseline']
    assert report['current']['leading_option'] == 'Option A'
    assert report['narrative']['generated_by'] == 'template'
    assert report['narrative']['model_id'] is None
    assert report['activity']['available'] is True
    # These cards were written straight to the table, bypassing the scoring
    # path, so no analytical work was recorded and the cap still binds.
    assert report['activity']['counts_by_type'] == {}
    assert report['impact']['verdict'] != VERDICT_MATERIAL
    assert 'not the quality of the decision' in report['provenance_note']


def test_a_report_needs_a_sealed_baseline(db, test_user):
    _seed_thread(db, test_user)
    capture_or_update_draft(test_user, 'thread-impact', structure=_structure())
    with pytest.raises(LookupError, match='no sealed baseline'):
        build_impact_report(test_user, 'thread-impact')


def test_the_narrative_states_only_computed_facts():
    impact = evaluate_impact(
        _measure_set(B1=_m(38)), _measure_set(B1=_m(71)), user_visible_events=0,
    )
    from app.decision_impact import compose_narrative

    narrative = compose_narrative(impact, {'leading_option': 'Option A'})
    assert '38%' in narrative and '71%' in narrative
    # The cap is disclosed in the prose, not applied quietly.
    assert 'without attributing it to Jaspen' in narrative


def test_at40_no_refund_or_guarantee_mechanics_on_this_branch():
    """AT-40 The evidence layer ships before any commercial language does."""
    forbidden = ('refund', 'guarantee', 'entitlement', 'stripe', 'billing')
    for path in IMPACT_MODULES:
        code = '\n'.join(
            line for line in path.read_text().lower().splitlines()
            if not line.strip().startswith('#')
        )
        for token in forbidden:
            assert token not in code, f'{path.name} references {token!r}'


# ---------------------------------------------------------------------------
# Sealing at the start of analysis (spec §3.4)
# ---------------------------------------------------------------------------

def _functions_calling(path, name):
    """Enclosing function names for every call to `name` in a module.

    Parsed rather than grepped so the wiring test asserts where the hook is
    called, not merely that the string appears somewhere in the file.
    """
    tree = ast.parse(path.read_text())
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id == name
            ):
                found.add(node.name)
    return found


def test_every_scoring_entry_point_seals_the_baseline():
    """The evidence chain has to be true in lifecycle, not just in content:
    the seal belongs at the start of analysis, not whenever a report is read.

    Four entry points can begin scoring a thread. Three are strategy routes;
    the whole conversational path funnels through one agent chokepoint, which
    is why it costs a single call rather than a hook per tool.
    """
    strategy = _functions_calling(
        BACKEND / 'app' / 'routes' / 'strategy.py', 'seal_baseline_on_analysis_start',
    )
    assert strategy == {'analyze_project', 'score_next_queued', 'score_batch_queued'}

    agent = _functions_calling(
        BACKEND / 'app' / 'routes' / 'ai_agent.py', 'seal_baseline_on_analysis_start',
    )
    assert agent == {'_execute_mutation_tool'}


def test_the_agent_hook_only_fires_on_tools_that_begin_scoring():
    from app.decision_impact import SCORING_ENTRY_TOOLS

    assert SCORING_ENTRY_TOOLS == {'generate_scorecard', 'queue_scorecards'}
    # Editing prose or renaming a thread happens after an analysis has run and
    # must not be treated as one beginning.
    assert 'patch_scorecard' not in SCORING_ENTRY_TOOLS
    assert 'rename_thread' not in SCORING_ENTRY_TOOLS


def test_analysis_start_seals_an_untouched_thread(db, test_user):
    _seed_thread(db, test_user)

    baseline = seal_baseline_on_analysis_start(test_user, 'thread-impact')
    assert baseline.is_sealed is True
    assert baseline.sealed_by == SEALED_BY_ANALYSIS
    assert baseline.content_hash


def test_analysis_start_does_not_overwrite_a_user_confirmed_seal(db, test_user):
    """A user who confirmed their baseline keeps that provenance on the record."""
    _seed_thread(db, test_user)
    capture_or_update_draft(test_user, 'thread-impact', structure=_structure())
    confirmed = seal_baseline(test_user, 'thread-impact')

    again = seal_baseline_on_analysis_start(test_user, 'thread-impact')
    assert again.sealed_by == SEALED_BY_USER
    assert again.sealed_at == confirmed.sealed_at


def test_analysis_start_seals_only_once_across_entry_points(db, test_user):
    """Entry points need no knowledge of each other."""
    _seed_thread(db, test_user)
    first = seal_baseline_on_analysis_start(test_user, 'thread-impact')
    second = seal_baseline_on_analysis_start(test_user, 'thread-impact')
    assert first.id == second.id
    assert first.sealed_at == second.sealed_at
    assert DecisionBaseline.query.filter_by(user_id=test_user.id).count() == 1


def test_a_failed_seal_never_breaks_the_analysis(db, test_user, monkeypatch):
    """Best effort, and it has to be actually best effort.

    A decision the user is waiting on matters more than a baseline row. The
    cost of a failure here is a report, never an analysis.
    """
    import app.decision_impact as impact

    def _explode(*_args, **_kwargs):
        raise RuntimeError('database is on fire')

    monkeypatch.setattr(impact, 'seal_baseline', _explode)
    _seed_thread(db, test_user)

    assert impact.seal_baseline_on_analysis_start(test_user, 'thread-impact') is None


def test_the_hook_ignores_a_missing_thread_or_user(db, test_user):
    assert seal_baseline_on_analysis_start(test_user, None) is None
    assert seal_baseline_on_analysis_start(None, 'thread-impact') is None


# ---------------------------------------------------------------------------
# Capture provenance — contemporaneous versus reconstructed (spec §3.8, §5.6)
# ---------------------------------------------------------------------------

def test_at50_a_baseline_sealed_before_analysis_is_contemporaneous(db, test_user):
    """AT-50"""
    _seed_thread(db, test_user)
    capture_or_update_draft(test_user, 'thread-impact', structure=_structure())
    baseline = seal_baseline(test_user, 'thread-impact')

    assert baseline.capture == CAPTURE_CONTEMPORANEOUS
    assert baseline.capture_reason is None
    assert baseline.is_contemporaneous is True


def test_at51_a_thread_analyzed_before_any_capture_is_reconstructed(db, test_user):
    """AT-51 The pre-feature thread, and the thread nobody captured."""
    _seed_thread(db, test_user, cards=[_card('Option A', 80, {'cost': 'high'})])

    baseline = seal_baseline(test_user, 'thread-impact', sealed_by=SEALED_BY_ANALYSIS)
    assert baseline.capture == CAPTURE_RECONSTRUCTED
    assert baseline.capture_reason == RECONSTRUCTED_NO_CAPTURE
    assert baseline.is_contemporaneous is False


def test_at52_a_draft_sealed_late_is_reconstructed_with_its_own_reason(db, test_user):
    """AT-52 The hook failed, analysis ran anyway, the seal arrived after.

    The draft's CONTENT is provably pre-analysis — the correction window
    refuses writes once analysis starts. The lifecycle claim is what failed, so
    it is recorded under its own reason rather than being flattened into the
    pre-feature case. It is still not contemporaneous.
    """
    _seed_thread(db, test_user)
    capture_or_update_draft(test_user, 'thread-impact', structure=_structure())
    _add_cards(db, test_user, 'thread-impact', [_card('Option A', 80, {'cost': 'high'})])

    baseline = seal_baseline(test_user, 'thread-impact', sealed_by=SEALED_BY_ANALYSIS)
    assert baseline.capture == CAPTURE_RECONSTRUCTED
    assert baseline.capture_reason == RECONSTRUCTED_LATE_SEAL
    assert baseline.is_contemporaneous is False


def test_at53_a_failed_hook_cannot_be_laundered_by_the_later_lazy_seal(db, test_user):
    """AT-53 The whole point of this distinction.

    The hook fails, analysis proceeds (correctly — it must never be blocked by
    a baseline), and the report route later seals the thread. That later seal
    must not produce something indistinguishable from a baseline captured in
    time.
    """
    import app.decision_impact as impact

    _seed_thread(db, test_user)
    capture_or_update_draft(test_user, 'thread-impact', structure=_structure())

    original = impact.seal_baseline
    try:
        impact.seal_baseline = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('down'))
        assert impact.seal_baseline_on_analysis_start(test_user, 'thread-impact') is None
    finally:
        impact.seal_baseline = original

    _add_cards(db, test_user, 'thread-impact', [_card('Option A', 80, {'cost': 'high'})])
    late = seal_baseline(test_user, 'thread-impact', sealed_by=SEALED_BY_ANALYSIS)

    assert late.capture == CAPTURE_RECONSTRUCTED
    assert late.is_contemporaneous is False


def test_at54_capture_is_decided_by_the_thread_not_by_the_caller(db, test_user):
    """AT-54 No argument, no override, no way to assert it from outside."""
    import inspect as _inspect

    signature = _inspect.signature(seal_baseline)
    assert 'capture' not in signature.parameters
    assert 'capture_reason' not in signature.parameters

    _seed_thread(db, test_user, cards=[_card('Option A', 80, {'cost': 'high'})])
    # Even the most confident caller gets the truth.
    baseline = seal_baseline(test_user, 'thread-impact', sealed_by=SEALED_BY_USER)
    assert baseline.capture == CAPTURE_RECONSTRUCTED


def test_at55_a_reconstructed_baseline_yields_no_verdict(db, test_user):
    """AT-55 Not material, not limited, not "no material change" — no comparison."""
    impact = evaluate_impact(
        _measure_set(A1=_m(1), A2=_m(1), A5=_m(0), B1=_m(10)),
        _measure_set(A1=_m(9), A2=_m(9), A5=_m(9), B1=_m(95)),
        user_visible_events=50,
        capture=CAPTURE_RECONSTRUCTED,
        capture_reason=RECONSTRUCTED_NO_CAPTURE,
    )

    assert impact['verdict'] == VERDICT_UNVERIFIED
    assert impact['verified_comparison'] is False
    assert impact['routes_satisfied'] == []
    assert impact['withheld_reason']


def test_at56_no_movements_are_published_for_a_reconstructed_baseline():
    """AT-56 A figure on the page can be lifted out of its caveat, so there is
    no figure. The comparison is withheld, not annotated."""
    impact = evaluate_impact(
        _measure_set(B1=_m(10)), _measure_set(B1=_m(95)),
        user_visible_events=50,
        capture=CAPTURE_RECONSTRUCTED,
        capture_reason=RECONSTRUCTED_LATE_SEAL,
    )
    assert impact['moved'] == []
    assert impact['unmoved'] == []
    assert impact['not_applicable'] == []
    assert impact['excluded_unconfirmed'] == []


def test_at57_verified_comparison_is_the_eligibility_primitive():
    """AT-57 One boolean any later gate keys off, stated as a fact about the
    evidence rather than as a commercial term."""
    verified = evaluate_impact(_measure_set(), _measure_set(), user_visible_events=1)
    assert verified['verified_comparison'] is True

    for reason in (RECONSTRUCTED_NO_CAPTURE, RECONSTRUCTED_LATE_SEAL):
        withheld = evaluate_impact(
            _measure_set(), _measure_set(), user_visible_events=1,
            capture=CAPTURE_RECONSTRUCTED, capture_reason=reason,
        )
        assert withheld['verified_comparison'] is False


def test_at58_the_report_qualifies_a_reconstructed_baseline(db, test_user):
    """AT-58 It may never be presented as "what Jaspen received"."""
    _seed_thread(db, test_user, cards=[_card('Option A', 80, {'cost': 'high'})])
    seal_baseline(test_user, 'thread-impact', sealed_by=SEALED_BY_ANALYSIS)

    report = build_impact_report(test_user, 'thread-impact')

    assert report['baseline']['capture'] == CAPTURE_RECONSTRUCTED
    assert report['baseline']['verified_comparison'] is False
    assert report['impact']['verdict'] == VERDICT_UNVERIFIED
    assert report['reconstruction_note']
    assert 'not a record of what was originally submitted' in report['reconstruction_note']


def test_at59_the_narrative_makes_no_comparison_claim_when_withheld(db, test_user):
    """AT-59"""
    from app.decision_impact import compose_narrative

    impact = evaluate_impact(
        _measure_set(B1=_m(10)), _measure_set(B1=_m(95)),
        user_visible_events=50,
        capture=CAPTURE_RECONSTRUCTED, capture_reason=RECONSTRUCTED_NO_CAPTURE,
    )
    narrative = compose_narrative(impact, {'leading_option': 'Option A'})

    assert 'no verified starting point' in narrative
    # No figures, because no comparison was made.
    assert '95' not in narrative and '10' not in narrative


def test_at60_analysis_output_closes_the_correction_window(db, test_user):
    """AT-60 The scorecards table counts as analysis output.

    Detecting it requires user_id and thread_id: without them the peer
    collector falls back to the legacy session stores and answers False for a
    fully analyzed thread, holding the window open long after it should shut.
    """
    _seed_thread(db, test_user)
    capture_or_update_draft(test_user, 'thread-impact', structure=_structure())
    _add_cards(db, test_user, 'thread-impact', [_card('Option A', 80, {'cost': 'high'})])

    from app.decision_impact import analysis_has_started
    assert analysis_has_started(test_user.id, 'thread-impact') is True

    with pytest.raises(SealedBaselineError):
        capture_or_update_draft(test_user, 'thread-impact', structure=_structure())


# ---------------------------------------------------------------------------
# Phase 2 — what the ledger makes measurable (spec §4, §2.3)
# ---------------------------------------------------------------------------

def _score_through_the_real_path(db, user, thread_id, dimensions, *, run, weights=None):
    """Persist a scorecard the way an analytical pass does.

    Deliberately routed through upsert_scorecard rather than the ledger API:
    the claim under test is that real scoring produces events, not that the
    recorder works when called directly.
    """
    from app.scorecards import upsert_scorecard

    upsert_scorecard(
        user_id=user.id,
        thread_id=thread_id,
        payload={
            'id': 'card-a',
            'project_name': 'Option A',
            'evaluation_id': run,
            'jaspen_score': 78,
            'dimensions': dimensions,
            'scoring_weights': weights or {key: 1.0 for key in dimensions},
        },
        evaluation_id=run,
        analysis_pass=True,
    )
    db.session.commit()


def _dim(score, confidence, ask=None):
    return {
        'label': 'Cost', 'score': score, 'raw_score': score,
        'confidence': confidence, 'what_would_improve': ask,
    }


def test_at67_b4_and_b5_are_measurable_without_inference(db, test_user):
    """AT-67 The measures Phase 1 had to report as unavailable.

    They were unmeasurable because a free-text assumption at intake and a
    rubric criterion at close share no identity. The ledger supplies it: both
    now count DISTINCT criteria carrying a recorded event, with no cross-
    boundary matching and nothing inferred from prose.
    """
    rubric = {'criteria': [
        {'key': 'cost', 'label': 'Cost', 'weight': 0.5},
        {'key': 'risk', 'label': 'Risk', 'weight': 0.5},
    ]}
    _seed_thread(db, test_user, rubric=rubric)
    capture_or_update_draft(test_user, 'thread-impact', structure=_structure())
    seal_baseline(test_user, 'thread-impact')

    _score_through_the_real_path(db, test_user, 'thread-impact', {
        'cost': _dim(80, 'assumed', 'Share the FY25 spend export.'),
        'risk': _dim(70, 'low', 'Provide the vendor SLA history.'),
    }, run='run-1', weights={'cost': 0.5, 'risk': 0.5})

    _score_through_the_real_path(db, test_user, 'thread-impact', {
        'cost': _dim(80, 'high', None),
        'risk': _dim(70, 'low', 'Still need the vendor SLA history.'),
    }, run='run-2', weights={'cost': 0.5, 'risk': 0.5})

    measures, _ = current_measures(test_user.id, 'thread-impact')

    assert measures['B4']['value'] == 1        # cost: assumed -> high
    assert measures['B4']['basis'] == BASIS_DETERMINISTIC
    assert measures['B5']['value'] == 1        # risk: challenged, still open
    assert measures['B4']['reason'] is None if 'reason' in measures['B4'] else True

    # And they are ABSENT from the baseline rather than recorded as zero.
    # "Before Jaspen, Jaspen had resolved nothing" is a tautology, not a
    # property of the decision the user brought (spec §2.5).
    baseline = get_baseline(test_user.id, 'thread-impact')
    assert 'B4' not in baseline.measures
    assert 'B5' not in baseline.measures
    assert 'B6' not in baseline.measures


def test_at68_recorded_work_lifts_the_attribution_cap(db, test_user):
    """AT-68 The cap was never meant to bind forever — only until we could
    tell Jaspen's work from the user's."""
    rubric = {'criteria': [{'key': 'cost', 'label': 'Cost', 'weight': 1.0}]}
    _seed_thread(db, test_user, rubric=rubric)
    capture_or_update_draft(test_user, 'thread-impact', structure=_structure())
    seal_baseline(test_user, 'thread-impact')

    _score_through_the_real_path(
        db, test_user, 'thread-impact',
        {'cost': _dim(100, 'assumed', 'Share the FY25 spend export.')},
        run='run-1',
    )

    report = build_impact_report(test_user, 'thread-impact')
    assert report['activity']['counts_by_type']
    assert report['impact']['user_visible_events'] > 0
    assert report['impact']['attribution_cap_applied'] is False


def test_at69_the_cap_still_binds_when_nothing_was_recorded(db, test_user):
    """AT-69 The other half of AT-68: growth with no recorded analytical work
    is still not claimed."""
    impact = evaluate_impact(
        _measure_set(A1=_m(1), A2=_m(1), A5=_m(0)),
        _measure_set(A1=_m(5), A2=_m(8), A5=_m(4)),
        user_visible_events=0,
    )
    assert impact['attribution_cap_applied'] is True
    assert impact['verdict'] == VERDICT_LIMITED


def test_at70_the_report_lists_only_observable_events(db, test_user):
    """AT-70"""
    from app.models_challenge_event import ChallengeEvent

    rubric = {'criteria': [{'key': 'cost', 'label': 'Cost', 'weight': 1.0}]}
    _seed_thread(db, test_user, rubric=rubric)
    capture_or_update_draft(test_user, 'thread-impact', structure=_structure())
    seal_baseline(test_user, 'thread-impact')
    _score_through_the_real_path(
        db, test_user, 'thread-impact',
        {'cost': _dim(100, 'assumed', 'Share the export.')}, run='run-1',
    )

    hidden = ChallengeEvent.query.filter_by(user_id=test_user.id).first()
    hidden.user_visible = False
    db.session.commit()

    report = build_impact_report(test_user, 'thread-impact')
    assert report['activity']['suppressed_non_visible'] == 1
    assert all(event['user_visible'] for event in report['activity']['events'])
