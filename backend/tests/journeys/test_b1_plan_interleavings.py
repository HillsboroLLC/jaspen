from app.models import AIOperation, UserSession
from app.scorecards import upsert_scorecard
from app.scenarios_store import load_scenarios_data
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

    scripted_plan_provider(_ai_plan(), hook)
    status = _status(
        client, auth_headers, tid, _build(client, auth_headers, tid).get_json()['job_id'],
    )
    assert status['status'] == 'done'
    td = load_scenarios_data(test_user.id)[tid]
    assert set(td['wbs_by_scorecard']) == {'planner-card', 'other-card'}
    assert strategy._resolve_thread_wbs(td, 'planner-card')['tasks']
    assert strategy._resolve_thread_wbs(td, 'other-card')['tasks'][0]['title'] == 'Option B work'


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
    real_save = strategy._save_project_scenarios

    def fail_plan_save(*args, **kwargs):
        if kwargs.get('updater') is not None:
            raise RuntimeError('injected storage failure')
        return real_save(*args, **kwargs)

    monkeypatch.setattr(strategy, '_save_project_scenarios', fail_plan_save)
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
