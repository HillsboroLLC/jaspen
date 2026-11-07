from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm.attributes import flag_modified

from app import db as app_db
from app.decision_intelligence_backfill import backfill_decision_intelligence
from app.decision_records import (
    _with_first_scored_times,
    decision_signals_for,
    option_dispositions,
    record_decision_signal,
    record_option_decision,
    retract_decision_signal,
)
from app.models import Scorecard, UserSession
from app.models_decision_record import DecisionSignal, OptionDecision
from app.task_history import (
    commit_task_from_stated_date,
    confirm_task_commitment,
    mark_task_pm_synced,
)
from tests.test_option_decision_records import _portfolio_record
from tests.test_session_org_ownership import team_setup  # noqa: F401


def _set_cards(record, cards):
    payload = dict(record.record or {})
    payload['scorecards'] = cards
    record.record = payload
    flag_modified(record, 'record')
    app_db.session.commit()


def test_option_dispositions_are_per_option_and_reconcile(db, team_setup):
    owner, record = _portfolio_record(db, team_setup, thread_id='di-dispositions')
    cards = [
        {'id': 'card-a', 'option_key': 'option-a', 'name': 'A', 'first_scored_at': '2026-10-01T10:00:00'},
        {'id': 'card-b', 'option_key': 'option-b', 'name': 'B', 'first_scored_at': '2026-10-02T10:00:00'},
        {'id': 'card-c', 'option_key': 'option-c', 'name': 'C', 'first_scored_at': '2026-10-03T10:00:00'},
        {'id': 'card-d', 'option_key': 'option-d', 'name': 'D', 'first_scored_at': '2026-10-04T10:00:00'},
    ]
    _set_cards(record, cards)
    record_option_decision(
        record, 'option-a', 'Moving forward with A.', disposition='pursue',
        source='conversation', user_quote='We are doing A', option_name='A',
    )
    record_option_decision(
        record, 'option-b', 'Moving forward with B.', disposition='pursue',
        source='conversation', user_quote='And B', option_name='B',
    )
    record_option_decision(
        record, 'option-c', 'Deferred C.', disposition='still_evaluating',
        source='conversation', user_quote='Still evaluating C', option_name='C',
        capture_metadata={'deferred': True},
    )
    record_option_decision(
        record, 'option-d', 'Declined D.', disposition='not_pursue',
        source='conversation', user_quote='No on D', option_name='D',
    )

    result = option_dispositions(record)
    states = {row['option_key']: row['state'] for row in result['options']}
    assert states == {
        'option-a': 'pursued', 'option-b': 'pursued',
        'option-c': 'open', 'option-d': 'not_pursued',
    }
    assert result['reconciliation'] == {
        'pursued': 2, 'not_pursued': 1, 'open': 1, 'archived': 0,
        'scored_options': 4, 'reconciles': True,
    }
    assert next(row for row in result['options'] if row['option_key'] == 'option-c')['still_evaluating'] is True


def test_plan_after_still_evaluating_wins_and_archive_only_applies_to_open(db, team_setup):
    owner, record = _portfolio_record(db, team_setup, thread_id='di-plan-order')
    cards = [
        {'id': 'card-a', 'option_key': 'option-a', 'name': 'A'},
        {'id': 'card-b', 'option_key': 'option-b', 'name': 'B'},
    ]
    _set_cards(record, cards)
    record_option_decision(
        record, 'option-a', 'Deferred A.', disposition='still_evaluating',
        source='conversation', user_quote='Still looking', option_name='A',
    )
    record_option_decision(
        record, 'option-a', 'Moving forward with A — execution plan built.',
        disposition='pursue', source='plan_created', option_name='A',
    )
    row_a = Scorecard(id='card-a', user_id=owner.id, thread_id=record.thread_id,
                      project_name='A', data=cards[0], archived_at=datetime.utcnow())
    row_b = Scorecard(id='card-b', user_id=owner.id, thread_id=record.thread_id,
                      project_name='B', data=cards[1], archived_at=datetime.utcnow())
    app_db.session.add_all([row_a, row_b]); app_db.session.commit()

    result = option_dispositions(record, scorecard_rows=[row_a, row_b])
    states = {row['option_key']: row['state'] for row in result['options']}
    assert states == {'option-a': 'pursued', 'option-b': 'archived'}
    row_b.archived_at = None
    app_db.session.commit()
    restored = option_dispositions(record, scorecard_rows=[row_a, row_b])
    assert next(row for row in restored['options'] if row['option_key'] == 'option-b')['state'] == 'open'
    session = UserSession.query.filter_by(session_id=record.thread_id).first()
    session.archived_at = datetime.utcnow()
    app_db.session.commit()
    session_archived = option_dispositions(record, session=session, scorecard_rows=[row_a, row_b])
    assert next(row for row in session_archived['options'] if row['option_key'] == 'option-b')['state'] == 'archived'
    assert next(row for row in session_archived['options'] if row['option_key'] == 'option-a')['state'] == 'pursued'


def test_plan_snapshot_is_stored_once_and_regeneration_appends_history(app):
    from app.routes.strategy import _attach_decision_basis, _normalize_project_wbs
    card = {
        'id': 'score-1', 'option_key': 'opt-1', 'jaspen_score': 71,
        'score_category': 'Promising', 'decision_fingerprint': 'fp-1',
        'evidence_profile': {'evidence_backed_pct': 45, 'criteria': [
            {'key': 'cost', 'label': 'Cost', 'confidence': 'assumed', 'evidenced': False,
             'weight': 30, 'resolution': 'Verify quote'},
        ]},
        'gates': [{'key': 'legal', 'label': 'Legal', 'status': 'fail'}],
        'recommendation': {'verdict_key': 'advance_with_conditions'},
        'decision_state': {'methodology': {'version': '2'}},
    }
    plan = _normalize_project_wbs({'project_wbs': {'tasks': [{'id': 't1', 'title': 'Verify', 'due_date': '2026-11-10'}]}})
    first = _attach_decision_basis(plan, card)
    assert first == plan['decision_basis']
    assert first['evidence_backed_pct'] == 45
    assert first['unevidenced_criteria'][0]['resolution'] == 'Verify quote'

    regenerated = _normalize_project_wbs(
        {'project_wbs': {'tasks': [{'id': 't2', 'title': 'Verify again', 'due_date': '2026-11-12'}]}},
        existing=plan, change_source='regeneration',
    )
    _attach_decision_basis(regenerated, {**card, 'jaspen_score': 80}, existing=plan)
    assert regenerated['created_at'] == plan['created_at']
    assert regenerated['decision_basis']['jaspen_score'] == 71
    assert regenerated['decision_basis_history'][-1]['jaspen_score'] == 80
    assert regenerated['tasks'][0]['history'][-1]['source'] == 'regeneration'


def test_first_scored_time_survives_rescore_refresh_and_row_purge(db, test_user):
    session = UserSession(
        user_id=test_user.id, session_id='first-scored', name='First scored',
        payload={'session_id': 'first-scored', 'option_registry': {
            'opt-1': {'option_key': 'opt-1', 'display_name': 'Option'},
        }},
    )
    first = datetime(2026, 10, 1, 9, 0, 0)
    second = first + timedelta(days=2)
    app_db.session.add(session)
    app_db.session.add_all([
        Scorecard(id='rescore-1', user_id=test_user.id, thread_id='first-scored',
                  project_name='Option', data={'id': 'rescore-1', 'option_key': 'opt-1'}, created_at=first),
        Scorecard(id='rescore-2', user_id=test_user.id, thread_id='first-scored',
                  project_name='Option', data={'id': 'rescore-2', 'option_key': 'opt-1'}, created_at=second),
    ])
    app_db.session.commit()
    payload = {'source': {'thread_id': 'first-scored'}, 'scorecards': [
        {'id': 'rescore-1', 'option_key': 'opt-1', 'name': 'Option'},
        {'id': 'rescore-2', 'option_key': 'opt-1', 'name': 'Option'},
    ]}
    stamped = _with_first_scored_times(payload, session_row=session, record_created_at=second)
    assert {card['first_scored_at'] for card in stamped['scorecards']} == {first.isoformat()}
    assert session.payload['option_registry']['opt-1']['first_scored_at'] == first.isoformat()

    Scorecard.query.filter_by(thread_id='first-scored').delete()
    app_db.session.commit()
    after_purge = _with_first_scored_times(
        {'source': {'thread_id': 'first-scored'}, 'scorecards': []},
        existing_payload=stamped, session_row=session, record_created_at=second,
    )
    assert len(after_purge['scorecards']) == 2
    assert {card['first_scored_at'] for card in after_purge['scorecards']} == {first.isoformat()}


def test_task_history_commitments_and_reschedules_are_distinct(app):
    from app.routes.strategy import _normalize_project_wbs, _shift_wbs_dates
    generated = _normalize_project_wbs({'project_wbs': {'tasks': [
        {'id': 't1', 'title': 'Do it', 'owner': 'Alex', 'start_date': '2026-11-01', 'due_date': '2026-11-10'},
    ]}})
    task = generated['tasks'][0]
    assert task['commitment'] is None
    assert {entry['source'] for entry in task['history']} == {'generation'}

    uncommitted_shifted, _ = _shift_wbs_dates(generated, '2026-11-02', actor_user_id='person-1')
    assert uncommitted_shifted['tasks'][0]['commitment'] is None
    assert uncommitted_shifted['tasks'][0]['history'][-1]['source'] == 'schedule_shift'

    edited = _normalize_project_wbs(
        {'project_wbs': {'tasks': [{**task, 'due_date': '2026-11-12'}]}},
        existing=generated, change_source='person', actor_user_id='person-1',
        commit_on_person_change=True,
    )
    changed = edited['tasks'][0]
    assert changed['commitment']['due_date'] == '2026-11-12'
    assert changed['commitment']['basis'] == 'person_set'

    shifted, _ = _shift_wbs_dates(edited, '2026-11-15', actor_user_id='person-1')
    shifted_task = shifted['tasks'][0]
    assert shifted_task['commitment']['due_date'] == '2026-11-12'
    assert shifted_task['commitment']['rescheduled_to'] != '2026-11-12'
    assert shifted_task['history'][-1]['source'] == 'schedule_shift'


def test_task_dates_are_strict_without_rewriting_legacy_values(app):
    from app.routes.strategy import InvalidTaskDate, _normalize_project_wbs

    original = {'name': 'Plan', 'tasks': [{
        'id': 't1', 'title': 'Do it', 'status': 'todo',
        'start_date': 'legacy start', 'due_date': '2026-11-102026-11-13',
        'updated_at': '2026-11-01T10:00:00',
    }]}

    unchanged = _normalize_project_wbs(
        {'project_wbs': {**original, 'tasks': [{**original['tasks'][0], 'title': 'Renamed'}]}},
        existing=original, change_source='person', actor_user_id='person-1',
        commit_on_person_change=True,
    )
    assert unchanged['tasks'][0]['start_date'] == 'legacy start'
    assert unchanged['tasks'][0]['due_date'] == '2026-11-102026-11-13'
    assert unchanged['tasks'][0]['title'] == 'Renamed'

    for field, value in (
        ('start_date', '2026-02-30'),
        ('due_date', '2026-11-102026-11-13'),
        ('due_date', ' 2026-11-13 '),
    ):
        with pytest.raises(InvalidTaskDate) as raised:
            _normalize_project_wbs({'project_wbs': {'tasks': [{
                'id': 'new-task', 'title': 'New task', field: value,
            }]}})
        assert raised.value.task_id == 'new-task'
        assert raised.value.field == field

    cleared = _normalize_project_wbs(
        {'project_wbs': {
            **original,
            'start_date': '',
            'tasks': [{**original['tasks'][0], 'start_date': '', 'due_date': None}],
        }},
        existing={**original, 'start_date': '2026-11-01'}, change_source='person', actor_user_id='person-1',
        commit_on_person_change=True,
    )
    # Task dates can be cleared; the plan start is kept (it anchors the schedule).
    assert cleared['start_date'] == '2026-11-01'
    assert cleared['tasks'][0]['start_date'] is None
    assert cleared['tasks'][0]['due_date'] is None

    valid = _normalize_project_wbs(
        {'project_wbs': {**original, 'tasks': [{**original['tasks'][0], 'due_date': '2026-11-13'}]}},
        existing=original, change_source='person', actor_user_id='person-1',
        commit_on_person_change=True,
    )['tasks'][0]
    assert valid['due_date'] == '2026-11-13'
    assert valid['field_updated_at']['due_date']
    due_history = [entry for entry in valid['history'] if entry['field'] == 'due_date']
    assert due_history[-1]['to'] == '2026-11-13'

    synced = {'due_date': '2026-12-01'}
    mark_task_pm_synced(synced, connector_id='jira_sync', external_ref='JAS-1')
    assert synced['commitment']['basis'] == 'pm_sync'
    confirmed = {'due_date': '2026-12-02'}
    confirm_task_commitment(confirmed, user_quote='December second works')
    assert confirmed['commitment']['basis'] == 'person_confirmed'


def test_generated_decision_lineage_never_creates_commitments(app):
    from app.routes.strategy import _normalize_project_wbs
    plan = _normalize_project_wbs({'project_wbs': {'tasks': [{
        'id': 't1', 'title': 'Submit', 'due_date': '2026-11-20',
        'lineage': [{'type': 'decision_commitment', 'ref': 'deadline-1', 'label': 'Submission date'}],
    }, {
        'id': 't2', 'title': 'Prepare', 'due_date': '2026-11-18',
        'lineage': [{'type': 'decision_commitment', 'ref': 'decision-1', 'label': 'Proceed'}],
    }]}})
    assert all(task['commitment'] is None for task in plan['tasks'])


def test_customer_stated_date_has_an_explicit_commitment_writer(app):
    task = {'due_date': '2026-11-22', 'commitment': None}
    commitment = commit_task_from_stated_date(
        task, signal_id='signal-1', due_date='2026-11-20', at='2026-11-01T12:00:00',
    )
    assert commitment == {
        'due_date': '2026-11-20',
        'committed_at': '2026-11-01T12:00:00',
        'basis': 'user_stated',
        'ref': 'signal-1',
    }
    assert task['due_date'] == '2026-11-20'
    assert task['history'][-1] == {
        'field': 'due_date', 'from': '2026-11-22', 'to': '2026-11-20',
        'at': '2026-11-01T12:00:00', 'actor_user_id': None, 'source': 'person',
    }
    assert task['field_updated_at']['due_date'] == '2026-11-01T12:00:00'
    assert 'rescheduled_to' not in task['commitment']

    changed = commit_task_from_stated_date(
        task, signal_id='signal-2', due_date='2026-11-25', at='2026-11-02T12:00:00',
    )
    assert task['due_date'] == '2026-11-25'
    assert changed['due_date'] == '2026-11-20'
    assert changed['rescheduled_to'] == '2026-11-25'
    assert changed['rescheduled_at'] == '2026-11-02T12:00:00'
    assert changed['rescheduled_ref'] == 'signal-2'
    assert task['history'][-1]['from'] == '2026-11-20'
    assert task['history'][-1]['to'] == '2026-11-25'
    unchanged = {
        **task,
        'history': [dict(item) for item in task['history']],
        'commitment': dict(task['commitment']),
        'field_updated_at': dict(task['field_updated_at']),
    }
    commit_task_from_stated_date(
        task, signal_id='signal-3', due_date='2026-11-25', at='2026-11-03T12:00:00',
    )
    assert task == unchanged


def test_shared_task_history_writer_leaves_caller_field_times_alone(app):
    from app.task_history import record_task_changes

    # The plan editor and PM pull stamp field times themselves (description
    # included); the shared history writer must never overwrite them.
    prior = {'id': 't1', 'due_date': '2026-11-01', 'description': 'Old',
             'field_updated_at': {'description': '2026-10-01T00:00:00'}}
    task = {'id': 't1', 'due_date': '2026-11-05', 'description': 'New',
            'field_updated_at': {'description': '2026-11-02T00:00:00', 'due_date': '2026-11-02T00:00:00'},
            'updated_at': '2026-11-02T00:00:00'}
    record_task_changes(task, prior, source='person', at='2026-11-02T00:00:00')
    assert task['field_updated_at'] == {
        'description': '2026-11-02T00:00:00', 'due_date': '2026-11-02T00:00:00',
    }
    assert task['updated_at'] == '2026-11-02T00:00:00'
    assert task['history'][-1]['to'] == '2026-11-05'


def test_decision_signals_require_quotes_validate_and_deduplicate(db, team_setup):
    owner, record = _portfolio_record(db, team_setup, thread_id='di-signals')
    with pytest.raises(ValueError, match='user_quote'):
        record_decision_signal(record, kind='concern', content='Cost', source='conversation')
    with pytest.raises(ValueError, match='option_key'):
        record_decision_signal(
            record, kind='concern', content='Cost', source='conversation',
            option_key='missing', user_quote='Cost worries me',
        )
    first, created = record_decision_signal(
        record, kind='review_timing', content='Review next month', source='conversation',
        option_key='option-a', user_quote='Review it next month',
        structured={'review_by': '2026-12-01'}, actor_user_id=owner.id,
    )
    repeated, repeated_created = record_decision_signal(
        record, kind='review_timing', content='Review next month', source='conversation',
        option_key='option-a', user_quote='Review it next month',
        structured={'review_by': '2026-12-01'}, actor_user_id=owner.id,
    )
    assert created is True and repeated_created is False and repeated.id == first.id
    assert first.organization_id == record.organization_id
    assert first.attribution_user_id == record.user_id
    retract_decision_signal(first, actor_user_id=owner.id)
    assert decision_signals_for(record, 'option-a')[0].retracted_by == owner.id
    assert DecisionSignal.query.filter_by(decision_record_id=record.id).count() == 1


def test_backfill_maps_verdicts_creates_legacy_plan_and_is_idempotent(db, team_setup):
    owner, record = _portfolio_record(db, team_setup, thread_id='di-backfill')
    OptionDecision.query.delete()
    legacy = OptionDecision(
        decision_record_id=record.id, option_key='option-a', option_name='A',
        final_decision='unmapped customer wording', source='build_execution_plan',
        kit_verdict={'verdict_key': 'decline'}, decided_at=datetime.utcnow(),
    )
    unmapped = OptionDecision(
        decision_record_id=record.id, option_key='option-a', option_name='A',
        final_decision='customer-authored text', source='manual', decided_at=datetime.utcnow(),
    )
    app_db.session.add_all([legacy, unmapped])
    session = UserSession.query.filter_by(session_id=record.thread_id).first()
    session.scenarios_json = {'wbs_by_scorecard': {'card-b': {
        'scorecard_id': 'card-b', 'created_at': '2026-10-10T12:00:00',
        'tasks': [{'id': 't1', 'title': 'Execute'}],
    }}}
    flag_modified(session, 'scenarios_json')
    app_db.session.commit()

    first = backfill_decision_intelligence()
    second = backfill_decision_intelligence()
    assert first['option_decisions_mapped'] == 1
    assert first['option_decisions_unmapped'] == 1
    assert first['legacy_plan_decisions_created'] == 1
    assert first['legacy_plans_marked'] == 1
    assert second['legacy_plan_decisions_created'] == 0
    assert second['legacy_plans_marked'] == 0
    assert second['option_decisions_unmapped'] == 1
    assert legacy.source == 'build_execution_plan'
    assert OptionDecision.query.filter_by(source='legacy_plan', option_key='option-b').count() == 1
    assert second['report']['dispositions_by_source']['legacy_plan']['pursue'] == 1
    assert second['report']['dispositions_by_source']['build_execution_plan']['not_pursue'] == 1
    assert second['report']['records_with_first_scored_at'] == 1
    assert second['report']['plans_marked_created_before_snapshot'] == 1
