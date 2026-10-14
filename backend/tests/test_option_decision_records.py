from sqlalchemy.orm.attributes import flag_modified

from app.decision_records import (
    append_lesson,
    append_outcome,
    create_or_refresh_record,
    current_option_decision,
    current_option_decisions,
    find_execution_plan_decision,
    option_decision_history,
    record_execution_plan_decision,
    record_option_decision,
)
from app.models_decision_record import DecisionRecord, OptionDecision
from app.decision_retrieval import summarize
from app.memory_context import build_memory_item, render_memory_prompt
from tests.test_decision_record_pipeline import _seed_scored_project
from tests.test_session_org_ownership import _headers, team_setup


BASE = '/api/v1/decision-records'


def _portfolio_record(db, team_setup, thread_id='portfolio-decisions'):
    org, owner = team_setup['org'], team_setup['owner']
    _seed_scored_project(db, org, owner, session_id=thread_id, name='Bid portfolio')
    record, _ = create_or_refresh_record(owner, thread_id)
    payload = dict(record.record)
    payload['decision_kit'] = 'rfp_bid'
    payload['scorecards'] = [
        {
            'id': 'card-a', 'option_key': 'option-a', 'name': 'Adams County',
            'recommendation': {'verdict_key': 'advance_with_conditions', 'label': 'Bid with conditions'},
        },
        {
            'id': 'card-b', 'option_key': 'option-b', 'name': 'Denver Water',
            'recommendation': {'verdict_key': 'advance', 'label': 'Bid'},
        },
    ]
    record.record = payload
    record.decision_type = 'rfp_bid'
    flag_modified(record, 'record')
    db.session.commit()
    return owner, record


def test_two_options_keep_independent_current_decisions_and_session_summary(db, team_setup):
    owner, record = _portfolio_record(db, team_setup)
    a, _ = record_option_decision(
        record, 'option-a', 'Bid with conditions — Adams County.',
        decided_by_user_id=owner.id, source='manual', option_name='Adams County',
        rationale='Proceed only if surety clears.',
    )
    b, _ = record_option_decision(
        record, 'option-b', 'Moving forward with Denver Water — execution plan built.',
        decided_by_user_id=owner.id, source='build_execution_plan', option_name='Denver Water',
    )

    assert a.id != b.id
    assert current_option_decision(record, 'option-a').final_decision == 'Bid with conditions — Adams County.'
    assert current_option_decision(record, 'option-a').rationale == 'Proceed only if surety clears.'
    assert current_option_decision(record, 'option-b').source == 'build_execution_plan'
    assert {item['option_key'] for item in DecisionRecord.query.get(record.id).record['option_decisions']} == {
        'option-a', 'option-b',
    }
    summary = summarize(record)
    assert summary['human_decision']['recorded'] is True
    assert {
        item['option_key'] for item in summary['human_decision']['option_decisions']
    } == {'option-a', 'option-b'}
    memory = build_memory_item(record)
    assert {item['option_key'] for item in memory['option_decisions']} == {
        'option-a', 'option-b',
    }
    prompt = render_memory_prompt({'items': [memory]})
    assert 'Current decisions by option (the bid/no-bid portfolio)' in prompt
    assert 'Adams County: Bid with conditions — Adams County.' in prompt
    assert 'Denver Water: Moving forward with Denver Water — execution plan built.' in prompt


def test_superseding_one_option_keeps_history_and_other_option_unchanged(db, team_setup):
    owner, record = _portfolio_record(db, team_setup)
    first, _ = record_option_decision(
        record, 'option-a', 'Bid with conditions.', decided_by_user_id=owner.id,
        source='manual', option_name='Adams County', rationale='Pending bond review.',
    )
    other, _ = record_option_decision(
        record, 'option-b', 'Bid.', decided_by_user_id=owner.id,
        source='manual', option_name='Denver Water',
    )
    replacement, created = record_option_decision(
        record, 'option-a', 'No-Bid.', decided_by_user_id=owner.id,
        source='manual', option_name='Adams County', rationale='Surety declined.',
    )

    assert created is True
    assert replacement.supersedes_id == first.id
    assert OptionDecision.query.get(first.id).superseded_at is not None
    assert [item.final_decision for item in option_decision_history(record, 'option-a')] == [
        'No-Bid.', 'Bid with conditions.',
    ]
    assert current_option_decision(record, 'option-b').id == other.id


def test_scorecard_view_only_exposes_its_own_decision(client, app, db, team_setup):
    owner, record = _portfolio_record(db, team_setup)
    record_option_decision(
        record, 'option-a', 'Bid with conditions — Adams County.',
        decided_by_user_id=owner.id, source='manual', option_name='Adams County',
    )

    a = client.get(
        f'{BASE}?thread_id={record.thread_id}&option_key=option-a&limit=1',
        headers=_headers(app, owner),
    ).get_json()['records'][0]
    b = client.get(
        f'{BASE}?thread_id={record.thread_id}&option_key=option-b&limit=1',
        headers=_headers(app, owner),
    ).get_json()['records'][0]

    assert a['final_decision'] == 'Bid with conditions — Adams County.'
    assert a['current_state'] == 'current'
    assert b['final_decision'] is None
    assert b['current_state'] == 'unknown'
    assert b['option_decision'] is None


def test_building_option_b_leaves_option_a_and_rebuild_uses_b_decision(db, team_setup):
    owner, record = _portfolio_record(db, team_setup)
    a, _ = record_option_decision(
        record, 'option-a', 'Bid with conditions — Adams County.',
        decided_by_user_id=owner.id, source='manual', option_name='Adams County',
        rationale='Proceed only if surety clears.',
    )
    decision_kit = {
        'verdict_vocabulary': {
            'advance': 'Bid', 'advance_with_conditions': 'Bid with conditions', 'decline': 'No-Bid',
        }
    }
    b = record_execution_plan_decision(
        owner, record.thread_id,
        {
            'id': 'card-b', 'option_key': 'option-b', 'project_name': 'Denver Water',
            'recommendation': {'verdict_key': 'advance', 'label': 'Bid'},
        },
        decision_kit=decision_kit,
    )

    assert current_option_decision(record, 'option-a').id == a.id
    assert current_option_decision(record, 'option-a').rationale == 'Proceed only if surety clears.'
    assert find_execution_plan_decision(owner, record.thread_id, 'option-b', decision_kit=decision_kit).id == b.id
    assert find_execution_plan_decision(owner, record.thread_id, 'option-a', decision_kit=decision_kit) is None


def test_outcomes_and_lessons_attach_to_the_option_decision(db, team_setup):
    owner, record = _portfolio_record(db, team_setup)
    a, _ = record_option_decision(
        record, 'option-a', 'Bid.', decided_by_user_id=owner.id,
        source='manual', option_name='Adams County',
    )
    b, _ = record_option_decision(
        record, 'option-b', 'No-Bid.', decided_by_user_id=owner.id,
        source='manual', option_name='Denver Water',
    )
    append_outcome(a, 'Awarded the contract.', {'status': 'achieved'}, actor=owner)
    append_lesson(a, 'Early surety confirmation mattered.', actor=owner)

    assert len(OptionDecision.query.get(a.id).outcomes) == 1
    assert len(OptionDecision.query.get(a.id).lessons_learned) == 1
    assert OptionDecision.query.get(b.id).outcomes == []
    assert OptionDecision.query.get(b.id).lessons_learned == []
