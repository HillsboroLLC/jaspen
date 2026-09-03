"""Decision Impact Report — the acceptance tests from the spec.

docs/DECISION_IMPACT_REPORT_SPEC.md §10. Test IDs in the docstrings map to the
spec so a reader can check coverage against the contract rather than against
the implementation.

The report's whole value is that someone who does not trust us can recompute
it, so these are written against the claims: what the baseline preserves, what
may move a verdict, and what the report must refuse to say.
"""

import copy
import pathlib

import pytest

from app.decision_impact import (
    BASIS_DETERMINISTIC,
    BASIS_PROPOSED_UNCONFIRMED,
    BASIS_USER_CONFIRMED,
    MATERIALITY_PP,
    MEASURES,
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
    derive_baseline_measures,
    evaluate_impact,
    evidence_backed_pct_from_grades,
    get_baseline,
    rederive_baseline_measures,
    seal_baseline,
    verify_baseline_integrity,
)
from app.models_decision_baseline import (
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
    """A complete measure set. Anything not overridden sits still."""
    base = {
        'A1': _m(2), 'A2': _m(5), 'A3': _m(5), 'A4': _m(1), 'A5': _m(0), 'A6': _m(3),
        'B1': _m(40), 'B2': _m(60), 'B3': _m({'high': 0, 'medium': 1, 'low': 2, 'assumed': 2}),
        'B4': _m(None, reason='phase 2'), 'B5': _m(None, reason='phase 2'), 'B6': _m(0),
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
    for card in (cards or []):
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
    assert set(measures) == set(MEASURES)
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
    before = _measure_set(A1=_m(3), A2=_m(6), A3=_m(6), A4=_m(5), A5=_m(3), B1=_m(74), B6=_m(5))
    after = _measure_set(A1=_m(3), A2=_m(6), A3=_m(6), A4=_m(5), A5=_m(3), B1=_m(77), B6=_m(5))

    impact = evaluate_impact(before, after, user_visible_events=12)
    assert impact['verdict'] == VERDICT_NONE
    assert impact['moved'] == []
    assert impact['routes_satisfied'] == []


def test_at32_golden_same_recommendation_stronger_basis():
    """AT-32 Example A: nothing structural moves, verdict is material on the
    verification route alone."""
    before = _measure_set(
        A1=_m(2), A2=_m(5), A3=_m(5), A4=_m(1), A5=_m(0),
        B1=_m(38), B3=_m({'high': 0, 'medium': 1, 'low': 2, 'assumed': 2}), B6=_m(0),
    )
    after = _measure_set(
        A1=_m(2), A2=_m(5), A3=_m(5), A4=_m(3), A5=_m(2),
        B1=_m(71), B3=_m({'high': 2, 'medium': 2, 'low': 1, 'assumed': 0}), B6=_m(4),
    )

    impact = evaluate_impact(before, after, user_visible_events=9)
    assert impact['verdict'] == VERDICT_MATERIAL
    assert 'verification' in impact['routes_satisfied']

    moved = {m['id'] for m in impact['moved']}
    assert {'B1', 'B3', 'B6'}.issubset(moved)
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
    _seed_thread(db, test_user, rubric=rubric, cards=[
        _card('Option A', 82, {'cost': 'high', 'risk': 'medium'}),
        _card('Option B', 68, {'cost': 'low', 'risk': 'assumed'}),
    ])
    capture_or_update_draft(test_user, 'thread-impact', structure=_structure())
    seal_baseline(test_user, 'thread-impact')

    report = build_impact_report(test_user, 'thread-impact')

    assert report['schema_version'] == 1
    assert report['baseline']['sealed_by'] == SEALED_BY_USER
    assert report['baseline']['submission_ref']['turn_count'] >= 1
    assert 'submission_payload' not in report['baseline']
    assert report['current']['leading_option'] == 'Option A'
    assert report['narrative']['generated_by'] == 'template'
    assert report['narrative']['model_id'] is None
    # Phase 1 has no ledger, and says so rather than implying no activity.
    assert report['activity']['available'] is False
    assert report['impact']['attribution_cap_applied'] in (True, False)
    assert report['impact']['verdict'] != VERDICT_MATERIAL  # the cap, in Phase 1
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
