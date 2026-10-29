from app.models import AIOperation, UserSession
from app.models_pm_sync import PmSyncBinding, PmSyncLink
from app.scorecards import upsert_scorecard
import copy
from unittest.mock import patch

import pytest
from flask_jwt_extended import create_access_token

from app.scenarios_store import load_scenarios_data, save_project_scenarios_data
from app.session_access import RevisionConflict
from app.routes.sessions import load_user_sessions, save_user_sessions
from tests.test_decision_flow_stabilization import mock_accounting, modules, seed_thread
from tests.test_plan_build_jobs import CARD, _ai_plan


CONFLICT = "This project has newer changes. Reload to get the latest version. Your changes weren't saved."


def _seed(test_user, db, tid, cards=None):
    cards = cards or [CARD]
    seed_thread(test_user, tid, cards)
    for card in cards:
        upsert_scorecard(user_id=test_user.id, thread_id=tid, payload=card)
    db.session.commit()


def _build(client, headers, tid, scorecard_id='planner-card'):
    return client.post(
        f'/api/v1/strategy/threads/{tid}/ai-wbs', headers=headers,
        json={'commit': True, 'background': True, 'scorecard_id': scorecard_id},
    )


def _status(client, headers, tid, job_id):
    return client.get(
        f'/api/v1/strategy/threads/{tid}/ai-wbs/jobs/{job_id}', headers=headers,
    ).get_json()


def test_customer_reopens_a_project_with_two_scorecards_and_its_plan(
    client, db, test_user, auth_headers, monkeypatch,
    inline_plan_jobs, scripted_plan_provider,
):
    tid = 'journey-project-lifecycle'
    other = {**CARD, 'id': 'other-card', 'project_name': 'Other proposal'}
    _seed(test_user, db, tid, [CARD, other])
    mock_accounting(monkeypatch)
    assert client.post(
        f'/api/v1/ai-agent/threads/{tid}/messages', headers=auth_headers,
        json={'messages': [{'role': 'user', 'content': 'Compare both options.'}]},
    ).status_code == 200
    scripted_plan_provider(_ai_plan())
    status = _status(
        client, auth_headers, tid, _build(client, auth_headers, tid).get_json()['job_id'],
    )
    assert status['status'] == 'done'
    reopened = client.get(
        f'/api/v1/strategy/threads/{tid}/bundle', headers=auth_headers,
    )
    assert reopened.status_code == 200, reopened.get_json()
    bundle = reopened.get_json()
    assert len(bundle['scorecard_snapshots']) >= 2
    plan = client.get(
        f'/api/v1/strategy/threads/{tid}/wbs?scorecard_id=planner-card',
        headers=auth_headers,
    ).get_json()['project_wbs']
    assert 10 <= len(plan['tasks']) <= 18
    assert 4 <= len(plan['phases']) <= 6
    assert all(task.get('lineage') for task in plan['tasks'])


def test_customer_builds_a_plan_while_working_in_another_project(
    client, db, test_user, auth_headers, monkeypatch,
    inline_plan_jobs, scripted_plan_provider,
):
    strategy, _ = modules()
    _seed(test_user, db, 'journey-a')
    mock_accounting(monkeypatch)

    def hook():
        assert client.post(
            '/api/v1/strategy/threads/journey-b/scenarios', headers=auth_headers,
            json={'label': 'B scenario'},
        ).status_code == 201
        assert client.post(
            '/api/v1/strategy/threads/journey-c/scenarios', headers=auth_headers,
            json={'label': 'C scenario'},
        ).status_code == 201

    scripted_plan_provider(_ai_plan(), hook)
    started = _build(client, auth_headers, 'journey-a')
    status = _status(client, auth_headers, 'journey-a', started.get_json()['job_id'])
    assert status['status'] == 'done'
    stored = load_scenarios_data(test_user.id)
    assert strategy._resolve_thread_wbs(stored['journey-a'], 'planner-card')
    assert stored['journey-b']['scenarios']
    assert stored['journey-c']['scenarios']


def test_customer_builds_a_plan_while_adding_an_unrelated_same_project_scenario(
    client, db, test_user, auth_headers, monkeypatch,
    inline_plan_jobs, scripted_plan_provider,
):
    strategy, _ = modules()
    tid = 'journey-same-project'
    _seed(test_user, db, tid)
    mock_accounting(monkeypatch)

    def hook():
        assert client.post(
            f'/api/v1/strategy/threads/{tid}/scenarios', headers=auth_headers,
            json={'label': 'Mid-build scenario'},
        ).status_code == 201

    scripted_plan_provider(_ai_plan(), hook)
    started = _build(client, auth_headers, tid)
    status = _status(client, auth_headers, tid, started.get_json()['job_id'])
    assert status['status'] == 'done'
    stored = load_scenarios_data(test_user.id)[tid]
    assert strategy._resolve_thread_wbs(stored, 'planner-card')
    assert any(s['label'] == 'Mid-build scenario' for s in stored['scenarios'].values())


def test_customer_plan_edit_wins_over_a_build_for_the_same_option(
    client, db, test_user, auth_headers, monkeypatch,
    inline_plan_jobs, scripted_plan_provider,
):
    strategy, _ = modules()
    tid = 'journey-same-plan-conflict'
    _seed(test_user, db, tid)
    mock_accounting(monkeypatch)
    user_plan = {
        'scorecard_id': 'planner-card',
        'tasks': [{'id': 'user-task', 'title': 'Keep my edit', 'status': 'todo'}],
    }

    def hook():
        response = client.patch(
            f'/api/v1/strategy/threads/{tid}/wbs', headers=auth_headers,
            json={'scorecard_id': 'planner-card', 'project_wbs': user_plan},
        )
        assert response.status_code == 200, response.get_json()

    scripted_plan_provider(_ai_plan(), hook)
    started = _build(client, auth_headers, tid)
    status = _status(client, auth_headers, tid, started.get_json()['job_id'])
    assert status['status'] == 'failed'
    assert status['result_status'] == 409
    assert status['result']['code'] == 'revision_conflict'
    assert status['result']['error'] == CONFLICT
    stored = strategy._resolve_thread_wbs(load_scenarios_data(test_user.id)[tid], 'planner-card')
    assert stored['tasks'][0]['title'] == 'Keep my edit'
    operation = AIOperation.query.filter_by(
        thread_id=tid, operation_type='execution_plan',
    ).one()
    assert operation.charged_credits == 0
def test_customer_keeps_plans_for_two_options_and_their_lineage(
    client, db, test_user, auth_headers, monkeypatch,
    inline_plan_jobs, scripted_plan_provider,
):
    strategy, _ = modules()
    tid = 'journey-two-options'
    other = {**CARD, 'id': 'other-card', 'project_name': 'Other proposal'}
    _seed(test_user, db, tid, [CARD, other])
    mock_accounting(monkeypatch)
    option_b = {
        'scorecard_id': 'other-card',
        'tasks': [{'id': 'b-task', 'title': 'Option B work', 'status': 'todo',
                   'lineage': [{'type': 'risk', 'ref': 'risk-1'}]}],
    }

    def hook():
        response = client.patch(
            f'/api/v1/strategy/threads/{tid}/wbs', headers=auth_headers,
            json={'scorecard_id': 'other-card', 'project_wbs': option_b},
        )
        assert response.status_code == 200, response.get_json()
        sessions = load_user_sessions(test_user.id)
        result = sessions[tid]['result']
        result['scorecard_snapshots'] = [
            {**card, 'jaspen_score': 73} if card.get('id') == 'other-card' else card
            for card in result.get('scorecard_snapshots') or []
        ]
        result['selected_scorecard_id'] = 'other-card'
        sessions[tid]['result'] = result
        assert save_user_sessions(test_user.id, sessions)

    scripted_plan_provider(_ai_plan(), hook)
    status = _status(
        client, auth_headers, tid, _build(client, auth_headers, tid).get_json()['job_id'],
    )
    assert status['status'] == 'done'
    td = load_scenarios_data(test_user.id)[tid]
    assert set(td['wbs_by_scorecard']) == {'planner-card', 'other-card'}
    assert strategy._resolve_thread_wbs(td, 'planner-card')['tasks']
    assert strategy._resolve_thread_wbs(td, 'other-card')['tasks'][0]['title'] == 'Option B work'
    session = load_user_sessions(test_user.id)[tid]
    assert session['result']['selected_scorecard_id'] == 'other-card'
    rescored = next(card for card in session['result']['scorecard_snapshots'] if card['id'] == 'other-card')
    assert rescored['jaspen_score'] == 73


def test_customer_next_save_after_own_plan_build_uses_returned_revision(
    client, db, test_user, auth_headers, monkeypatch,
    inline_plan_jobs, scripted_plan_provider,
):
    tid = 'journey-next-save'
    _seed(test_user, db, tid)
    mock_accounting(monkeypatch)
    scripted_plan_provider(_ai_plan())
    status = _status(
        client, auth_headers, tid, _build(client, auth_headers, tid).get_json()['job_id'],
    )
    revision = status['result']['revision']
    response = client.post(
        f'/api/v1/strategy/threads/{tid}/scenarios', headers=auth_headers,
        json={'label': 'After build', 'base_revision': revision},
    )
    assert response.status_code == 201, response.get_json()
    assert response.get_json()['revision'] == revision + 1


def test_plan_storage_failure_keeps_no_partial_plan_and_reverses_once(
    client, db, test_user, auth_headers, monkeypatch,
    inline_plan_jobs, scripted_plan_provider,
):
    strategy, _ = modules()
    tid = 'journey-storage-failure'
    _seed(test_user, db, tid)
    mock_accounting(monkeypatch)
    scripted_plan_provider(_ai_plan())
    def fail_plan_save(*args, **kwargs):
        raise RuntimeError('injected storage failure')

    monkeypatch.setattr(strategy, '_persist_generated_plan', fail_plan_save)
    status = _status(
        client, auth_headers, tid, _build(client, auth_headers, tid).get_json()['job_id'],
    )
    assert status['status'] == 'failed'
    assert status['result_status'] == 500
    assert strategy._resolve_thread_wbs(
        load_scenarios_data(test_user.id).get(tid, {}), 'planner-card',
    ) is None
    operation = AIOperation.query.filter_by(
        thread_id=tid, operation_type='execution_plan',
    ).one()
    assert operation.charged_credits == 0


def test_chat_turn_does_not_conflict_with_plan_edit(client, db, test_user, auth_headers):
    tid = 'journey-chat-plan-edit'
    _seed(test_user, db, tid)
    created = client.patch(
        f'/api/v1/strategy/threads/{tid}/wbs', headers=auth_headers,
        json={'scorecard_id': 'planner-card', 'project_wbs': {
            'scorecard_id': 'planner-card',
            'tasks': [{'id': 'one', 'title': 'Before chat', 'status': 'todo'}],
        }},
    )
    assert created.status_code == 200, created.get_json()
    loaded_plan = created.get_json()['project_wbs']
    chatted = client.post(
        f'/api/v1/ai-agent/threads/{tid}/messages', headers=auth_headers,
        json={'messages': [{'role': 'user', 'content': 'One more thought'}]},
    )
    assert chatted.status_code == 200, chatted.get_json()
    loaded_plan['tasks'][0]['title'] = 'After chat'
    saved = client.patch(
        f'/api/v1/strategy/threads/{tid}/wbs', headers=auth_headers,
        json={'scorecard_id': 'planner-card', 'project_wbs': loaded_plan},
    )
    assert saved.status_code == 200, saved.get_json()
    assert saved.get_json()['project_wbs']['tasks'][0]['title'] == 'After chat'


def test_two_tabs_conflict_only_on_the_same_plan_or_scenario(
    client, db, test_user, auth_headers,
):
    tid = 'journey-object-conflicts'
    _seed(test_user, db, tid)
    initial = client.patch(
        f'/api/v1/strategy/threads/{tid}/wbs', headers=auth_headers,
        json={'scorecard_id': 'planner-card', 'project_wbs': {
            'scorecard_id': 'planner-card',
            'tasks': [{'id': 'one', 'title': 'Original', 'status': 'todo'}],
        }},
    ).get_json()['project_wbs']
    first = copy.deepcopy(initial)
    second = copy.deepcopy(initial)
    first['tasks'][0]['title'] = 'First tab'
    second['tasks'][0]['title'] = 'Second tab'
    assert client.patch(
        f'/api/v1/strategy/threads/{tid}/wbs', headers=auth_headers,
        json={'scorecard_id': 'planner-card', 'project_wbs': first},
    ).status_code == 200
    conflict = client.patch(
        f'/api/v1/strategy/threads/{tid}/wbs', headers=auth_headers,
        json={'scorecard_id': 'planner-card', 'project_wbs': second},
    )
    assert conflict.status_code == 409
    assert conflict.get_json()['error'] == CONFLICT
    stored = load_scenarios_data(test_user.id)[tid]
    assert stored['wbs_by_scorecard']['planner-card']['tasks'][0]['title'] == 'First tab'

    other = client.patch(
        f'/api/v1/strategy/threads/{tid}/wbs', headers=auth_headers,
        json={'scorecard_id': 'other-card', 'project_wbs': {
            'scorecard_id': 'other-card',
            'tasks': [{'id': 'two', 'title': 'Other option', 'status': 'todo'}],
        }},
    )
    assert other.status_code == 200, other.get_json()

    created_a = client.post(
        f'/api/v1/strategy/threads/{tid}/scenarios', headers=auth_headers,
        json={'label': 'Scenario A'},
    ).get_json()
    created_b = client.post(
        f'/api/v1/strategy/threads/{tid}/scenarios', headers=auth_headers,
        json={'label': 'Scenario B'},
    ).get_json()
    sid_a, basis_a = created_a['scenario_id'], created_a['updated_at']
    sid_b, basis_b = created_b['scenario_id'], created_b['updated_at']
    assert client.patch(
        f'/api/v1/strategy/scenarios/{sid_a}?thread_id={tid}', headers=auth_headers,
        json={'label': 'A first tab', 'expected_updated_at': basis_a},
    ).status_code == 200
    stale = client.patch(
        f'/api/v1/strategy/scenarios/{sid_a}?thread_id={tid}', headers=auth_headers,
        json={'label': 'A second tab', 'expected_updated_at': basis_a},
    )
    assert stale.status_code == 409
    assert client.patch(
        f'/api/v1/strategy/scenarios/{sid_b}?thread_id={tid}', headers=auth_headers,
        json={'label': 'B first tab', 'expected_updated_at': basis_b},
    ).status_code == 200


def test_generated_plan_guard_allows_one_same_option_build(db, test_user):
    strategy, _ = modules()
    tid = 'journey-two-builds'
    _seed(test_user, db, tid)
    guard = None
    first = {'scorecard_id': 'planner-card', 'updated_at': 'one', 'tasks': []}
    second = {'scorecard_id': 'planner-card', 'updated_at': 'two', 'tasks': []}
    strategy._persist_generated_plan(test_user.id, tid, 'planner-card', first, guard)
    with pytest.raises(RevisionConflict):
        strategy._persist_generated_plan(test_user.id, tid, 'planner-card', second, guard)


def test_legacy_plan_moves_only_when_its_option_is_resolvable():
    strategy, _ = modules()
    legacy = {'scorecard_id': 'old-card', 'tasks': [{'id': 'old'}]}
    td = {'project_wbs': legacy}
    new = {'scorecard_id': 'new-card', 'tasks': [{'id': 'new'}]}
    strategy._store_thread_wbs(td, 'new-card', new)
    assert td['wbs_by_scorecard']['old-card'] is legacy
    assert td['wbs_by_scorecard']['new-card'] is new
    assert td['project_wbs'] is new
    assert td['active_execution_scorecard_id'] == 'new-card'

    unresolved = {'tasks': [{'id': 'legacy'}]}
    td2 = {'project_wbs': unresolved}
    strategy._store_thread_wbs(td2, 'new-card', new)
    assert td2['project_wbs'] is unresolved
    assert td2['wbs_by_scorecard'] == {'new-card': new}


def test_project_rename_updates_session_baseline_and_scenarios_atomically(
    client, db, test_user, auth_headers,
):
    tid = 'journey-rename-atomic'
    _seed(test_user, db, tid)
    save_project_scenarios_data(test_user.id, tid, {
        'baseline': {**CARD, 'project_name': 'Old name'},
        'scenarios': {
            'scenario-1': {
                'scenario_id': 'scenario-1', 'updated_at': 'basis',
                'result': {**CARD, 'project_name': 'Old name'},
            },
        },
    })
    row = UserSession.query.filter_by(session_id=tid).one()
    response = client.patch(
        f'/api/v1/strategy/threads/{tid}', headers=auth_headers,
        json={'name': 'New name', 'base_revision': row.revision},
    )
    assert response.status_code == 200, response.get_json()
    db.session.expire_all()
    row = UserSession.query.filter_by(session_id=tid).one()
    assert row.payload['name'] == 'New name'
    assert row.scenarios_json['baseline']['project_name'] == 'New name'
    assert row.scenarios_json['scenarios']['scenario-1']['result']['project_name'] == 'New name'


def test_project_rename_lost_cas_rolls_back_both_halves(
    client, db, test_user, auth_headers, monkeypatch,
):
    import app.scenarios_store as scenarios_store

    tid = 'journey-rename-race'
    _seed(test_user, db, tid)
    save_project_scenarios_data(test_user.id, tid, {
        'baseline': {**CARD, 'project_name': 'Old name'},
        'scenarios': {},
    })
    row = UserSession.query.filter_by(session_id=tid).one()
    monkeypatch.setattr(scenarios_store, '_compare_and_swap', lambda *_args, **_kwargs: 0)

    response = client.patch(
        f'/api/v1/strategy/threads/{tid}', headers=auth_headers,
        json={'name': 'Unsaved name', 'base_revision': row.revision},
    )

    assert response.status_code == 409
    assert response.get_json()['error'] == CONFLICT
    db.session.expire_all()
    row = UserSession.query.filter_by(session_id=tid).one()
    assert row.payload['name'] != 'Unsaved name'
    assert row.scenarios_json['baseline']['project_name'] == 'Old name'


def test_older_plan_and_scenario_without_timestamps_save_twice(
    client, db, test_user, auth_headers,
):
    tid = 'journey-older-object-bases'
    _seed(test_user, db, tid)
    save_project_scenarios_data(test_user.id, tid, {
        'wbs_by_scorecard': {
            'planner-card': {
                'scorecard_id': 'planner-card',
                'tasks': [{'id': 'one', 'title': 'Old plan'}],
            },
        },
        'scenarios': {
            'older-scenario': {
                'scenario_id': 'older-scenario',
                'label': 'Old scenario',
                'deltas': {},
            },
        },
    })

    first_plan = client.patch(
        f'/api/v1/strategy/threads/{tid}/wbs', headers=auth_headers,
        json={'scorecard_id': 'planner-card', 'project_wbs': {
            'scorecard_id': 'planner-card',
            'tasks': [{'id': 'one', 'title': 'First plan edit'}],
        }},
    )
    assert first_plan.status_code == 200, first_plan.get_json()
    second_body = first_plan.get_json()['project_wbs']
    second_body['tasks'][0]['title'] = 'Second plan edit'
    assert client.patch(
        f'/api/v1/strategy/threads/{tid}/wbs', headers=auth_headers,
        json={'scorecard_id': 'planner-card', 'project_wbs': second_body},
    ).status_code == 200

    first_scenario = client.patch(
        f'/api/v1/strategy/scenarios/older-scenario?thread_id={tid}',
        headers=auth_headers,
        json={'label': 'First scenario edit'},
    )
    assert first_scenario.status_code == 200, first_scenario.get_json()
    assert client.patch(
        f'/api/v1/strategy/scenarios/older-scenario?thread_id={tid}',
        headers=auth_headers,
        json={
            'label': 'Second scenario edit',
            'expected_updated_at': first_scenario.get_json()['updated_at'],
        },
    ).status_code == 200


def test_score_delete_rolls_back_session_when_scenario_save_fails(
    client, db, test_user, auth_headers, monkeypatch,
):
    strategy, _ = modules()
    tid = 'journey-delete-atomic'
    _seed(test_user, db, tid)
    save_project_scenarios_data(test_user.id, tid, {
        'scenarios': {
            'planner-card': {
                'scenario_id': 'planner-card', 'updated_at': 'basis',
                'result': CARD,
            },
        },
    })
    monkeypatch.setattr(
        strategy, 'save_session_and_project_scenarios_data',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError('injected')),
    )
    response = client.delete(
        f'/api/v1/strategy/scores/{tid}/planner-card', headers=auth_headers,
    )
    assert response.status_code == 500
    db.session.expire_all()
    row = UserSession.query.filter_by(session_id=tid).one()
    assert row.payload.get('result')
    assert 'planner-card' in row.scenarios_json['scenarios']


def test_organization_collaborator_stale_plan_write_is_refused(
    app, client, db,
):
    from tests.test_session_org_ownership import (
        _add_member, _mk_org, _mk_user, _seed_project,
    )

    owner = _mk_user(db, 'b1-owner@example.test')
    collaborator = _mk_user(db, 'b1-collaborator@example.test')
    org = _mk_org(db, owner, name='B1 Org')
    _add_member(db, org, collaborator)
    tid = 'journey-org-stale-plan'
    _seed_project(db, org, owner, session_id=tid)
    with app.app_context():
        owner_headers = {'Authorization': f'Bearer {create_access_token(identity=str(owner.id))}'}
        collaborator_headers = {
            'Authorization': f'Bearer {create_access_token(identity=str(collaborator.id))}',
        }

    created = client.patch(
        f'/api/v1/strategy/threads/{tid}/wbs', headers=owner_headers,
        json={'scorecard_id': 'planner-card', 'project_wbs': {
            'scorecard_id': 'planner-card',
            'tasks': [{'id': 'one', 'title': 'Original'}],
        }},
    ).get_json()['project_wbs']
    owner_edit = copy.deepcopy(created)
    collaborator_edit = copy.deepcopy(created)
    owner_edit['tasks'][0]['title'] = 'Owner wins'
    collaborator_edit['tasks'][0]['title'] = 'Stale collaborator'
    assert client.patch(
        f'/api/v1/strategy/threads/{tid}/wbs', headers=owner_headers,
        json={'scorecard_id': 'planner-card', 'project_wbs': owner_edit},
    ).status_code == 200
    refused = client.patch(
        f'/api/v1/strategy/threads/{tid}/wbs', headers=collaborator_headers,
        json={'scorecard_id': 'planner-card', 'project_wbs': collaborator_edit},
    )
    assert refused.status_code == 409
    assert refused.get_json()['error'] == CONFLICT
    stored = load_scenarios_data(owner.id)[tid]
    assert stored['wbs_by_scorecard']['planner-card']['tasks'][0]['title'] == 'Owner wins'


def test_journey_9_jira_binding_stays_with_built_plan_after_edit(
    client, db, test_user, auth_headers, monkeypatch,
    inline_plan_jobs, scripted_plan_provider,
):
    tid = 'journey-9-jira-after-build'
    _seed(test_user, db, tid)
    mock_accounting(monkeypatch)
    scripted_plan_provider(_ai_plan())
    status = _status(
        client, auth_headers, tid, _build(client, auth_headers, tid).get_json()['job_id'],
    )
    assert status['status'] == 'done', status
    plan = status['result']['project_wbs']

    binding = PmSyncBinding(
        user_id=test_user.id,
        thread_id=tid,
        plan_key='planner-card',
        connector_id='jira_sync',
        external_container_id='JST',
        external_container_url='https://example.atlassian.net/browse/JST',
        mode='push_only',
        conflict_policy='manual_review',
        policy_set_by_user_id=test_user.id,
        field_policy_overrides={},
        config={'task_issue_type': 'Task', 'group_under_epics': False},
        user_map={},
    )
    db.session.add(binding)
    db.session.commit()
    calls = []

    def request(_config, method, path, payload=None, timeout=30):
        calls.append((method, path, payload))
        if path == '/rest/api/3/issue/bulk':
            updates = (payload or {}).get('issueUpdates') or []
            return {
                'issues': [{'key': f'JST-{index + 1}'} for index in range(len(updates))],
                'errors': [],
            }, {}
        if path == '/rest/api/3/issueLink':
            return {'id': 'link-1'}, {}
        return {}, {}

    with patch(
        'app.pm_sync.service.jira_adapter.assert_connected',
        return_value={'base_url': 'https://example.atlassian.net'},
    ), patch(
        'app.pm_sync.service.jira_adapter.request', side_effect=request,
    ), patch(
        'app.pm_sync.service.jira_adapter.set_identity',
    ), patch(
        'app.pm_sync.service.jira_adapter.recover_issue', return_value=None,
    ):
        first_sync = client.post(
            f'/api/v1/connectors/threads/{tid}/jira/sync',
            headers=auth_headers,
            json={'plan_key': 'planner-card'},
        )
        assert first_sync.status_code == 200, first_sync.get_json()

        plan['tasks'][0]['title'] = 'Edited after first Jira sync'
        edit = client.patch(
            f'/api/v1/strategy/threads/{tid}/wbs',
            headers=auth_headers,
            json={'scorecard_id': 'planner-card', 'project_wbs': plan},
        )
        assert edit.status_code == 200, edit.get_json()
        second_sync = client.post(
            f'/api/v1/connectors/threads/{tid}/jira/sync',
            headers=auth_headers,
            json={'plan_key': 'planner-card'},
        )
        assert second_sync.status_code == 200, second_sync.get_json()

    assert PmSyncBinding.query.filter_by(
        user_id=test_user.id, thread_id=tid, plan_key='planner-card',
    ).one().id == binding.id
    assert PmSyncLink.query.filter_by(
        binding_id=binding.id, entity_type='task',
    ).count() == len(plan['tasks'])
    assert sum(1 for _method, path, _payload in calls if path == '/rest/api/3/issue/bulk') == 1
