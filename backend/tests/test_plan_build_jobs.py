"""Background execution-plan builds: a job id at once, and always a plan."""
import json
from datetime import datetime, timedelta

from app.models import AIOperation
from app.scorecards import upsert_scorecard

from tests.test_decision_flow_stabilization import mock_accounting, modules, seed_thread

CARD = {
    'id': 'planner-card', 'project_name': 'Proposal', 'jaspen_score': 61,
    'recommendations': [{'id': 'rec-1', 'text': 'Resolve the compliance response'}],
    'top_risks': [{'id': 'risk-1', 'risk': 'Key staff are committed elsewhere'}],
}


def _seed(test_user, db, tid, card=CARD):
    seed_thread(test_user, tid, [card])
    upsert_scorecard(user_id=test_user.id, thread_id=tid, payload=card)
    db.session.commit()


def _run_jobs_inline(monkeypatch):
    strategy, _ = modules()
    monkeypatch.setattr(strategy, '_start_plan_build_job', strategy._run_plan_build_job)


def _ai_plan(task_count=12):
    lineage = [
        {'type': 'recommendation', 'ref': 'rec-1'},
        {'type': 'risk', 'ref': 'risk-1'},
        {'type': 'decision_commitment', 'ref': 'successful_plan_build'},
    ]
    phases = [{'name': f'Phase {p + 1}', 'tasks': []} for p in range(4)]
    for index in range(task_count):
        phases[index % 4]['tasks'].append({
            'id': f'task-{index + 1}', 'title': f'Proposal compliance step {index + 1}',
            'estimated_days': 2, 'lineage': lineage,
        })
    return {'summary': 'AI plan', 'phases': phases}


def _provider(monkeypatch, replies):
    strategy, _ = modules()
    calls = []

    def provider(messages, **_kwargs):
        calls.append(messages[0]['content'])
        reply = replies[min(len(calls), len(replies)) - 1]
        if isinstance(reply, Exception):
            raise reply
        return reply, {'provider': 'anthropic', 'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15}

    monkeypatch.setattr(strategy, '_strategy_generate_reply', provider)
    return calls


def _start(client, auth_headers, tid, **extra):
    return client.post(
        f'/api/v1/strategy/threads/{tid}/ai-wbs', headers=auth_headers,
        json={'commit': True, 'background': True, 'scorecard_id': 'planner-card', **extra},
    )


def _status(client, auth_headers, tid, job_id):
    return client.get(f'/api/v1/strategy/threads/{tid}/ai-wbs/jobs/{job_id}', headers=auth_headers)


def test_background_build_returns_job_and_finishes_with_saved_ai_plan(client, db, test_user, auth_headers, monkeypatch):
    strategy, _ = modules()
    tid = 'plan-job-ai'
    _seed(test_user, db, tid)
    mock_accounting(monkeypatch)
    _run_jobs_inline(monkeypatch)
    _provider(monkeypatch, [json.dumps(_ai_plan())])

    started = _start(client, auth_headers, tid)
    assert started.status_code == 202, started.get_json()
    job_id = started.get_json()['job_id']

    status = _status(client, auth_headers, tid, job_id).get_json()
    assert status['status'] == 'done'
    assert status['result_status'] == 200
    plan = status['result']['project_wbs']
    assert plan['generation_status'] == 'ai_generated'
    assert status['result']['decision_recorded'] is True
    stored = strategy._resolve_thread_wbs(strategy._load_scenarios(test_user.id)[tid], 'planner-card')
    assert len(stored['tasks']) == 12


def test_ai_failure_then_success_on_retry_gives_the_ai_plan(client, db, test_user, auth_headers, monkeypatch):
    tid = 'plan-job-retry'
    _seed(test_user, db, tid)
    mock_accounting(monkeypatch)
    _run_jobs_inline(monkeypatch)
    calls = _provider(monkeypatch, ['{"phases":[', '{"phases":[', json.dumps(_ai_plan())])

    job_id = _start(client, auth_headers, tid).get_json()['job_id']
    status = _status(client, auth_headers, tid, job_id).get_json()

    assert len(calls) == 3
    assert status['status'] == 'done'
    assert status['result']['project_wbs']['generation_status'] == 'ai_generated'


def test_all_ai_attempts_fail_gives_a_free_starter_plan_with_full_lineage(client, db, test_user, auth_headers, monkeypatch):
    from app.decision_lineage import STARTER_PLAN_LABEL
    from app.models_decision_record import OptionDecision
    strategy, _ = modules()
    tid = 'plan-job-starter'
    _seed(test_user, db, tid)
    mock_accounting(monkeypatch)
    _run_jobs_inline(monkeypatch)
    calls = _provider(monkeypatch, [RuntimeError('provider unavailable')])
    credits_before = test_user.credits_remaining

    job_id = _start(client, auth_headers, tid).get_json()['job_id']
    status = _status(client, auth_headers, tid, job_id).get_json()

    assert len(calls) == 3
    assert status['status'] == 'done'
    plan = status['result']['project_wbs']
    assert plan['generation_status'] == 'starter_plan'
    assert plan['ai_generated'] is False
    assert plan['starter_plan_note'].startswith(STARTER_PLAN_LABEL)
    assert 'It has 3 tasks' in plan['starter_plan_note']
    lineage = {(link['type'], link['ref']) for task in plan['tasks'] for link in task['lineage']}
    assert lineage == {
        ('recommendation', 'rec-1'), ('risk', 'risk-1'),
        ('decision_commitment', 'successful_plan_build'),
    }
    assert all(len(task['lineage']) == 1 for task in plan['tasks'])
    stored = strategy._resolve_thread_wbs(strategy._load_scenarios(test_user.id)[tid], 'planner-card')
    assert stored['generation_status'] == 'starter_plan'
    assert stored['starter_plan_note'] == plan['starter_plan_note']
    operation = AIOperation.query.filter_by(thread_id=tid, operation_type='execution_plan').one()
    assert operation.charged_credits == 0
    assert test_user.credits_remaining == credits_before
    # A plan exists, so the decision is recorded after it was saved.
    from app.models_decision_record import DecisionRecord
    record = DecisionRecord.query.filter_by(thread_id=tid).one()
    assert OptionDecision.query.filter_by(decision_record_id=record.id).count() == 1


def test_interrupted_job_resumes_on_the_next_status_check(client, db, test_user, auth_headers, monkeypatch):
    from app.models_plan_jobs import PlanBuildJob
    tid = 'plan-job-resume'
    _seed(test_user, db, tid)
    mock_accounting(monkeypatch)
    _provider(monkeypatch, [json.dumps(_ai_plan())])
    stale = datetime.utcnow() - timedelta(minutes=10)
    job = PlanBuildJob(
        user_id=str(test_user.id), thread_id=tid, heartbeat_at=stale,
        request_json={'commit': True, 'background': True, 'scorecard_id': 'planner-card'},
    )
    db.session.add(job)
    db.session.commit()

    strategy, _ = modules()
    started = []
    monkeypatch.setattr(strategy, '_start_plan_build_job', started.append)
    assert _status(client, auth_headers, tid, job.id).get_json()['status'] == 'running'
    assert _status(client, auth_headers, tid, job.id).get_json()['status'] == 'running'
    assert started == [job.id]  # restarted once, not by every status check

    strategy._run_plan_build_job(job.id)
    status = _status(client, auth_headers, tid, job.id).get_json()
    assert status['status'] == 'done'
    assert db.session.get(PlanBuildJob, job.id).run_count == 2


def test_resumed_job_reuses_a_finished_ai_result_instead_of_charging_again(client, db, test_user, auth_headers, monkeypatch):
    tid = 'plan-job-replay'
    _seed(test_user, db, tid)
    mock_accounting(monkeypatch)
    _run_jobs_inline(monkeypatch)
    calls = _provider(monkeypatch, [json.dumps(_ai_plan())])
    strategy, _ = modules()

    job_id = _start(client, auth_headers, tid).get_json()['job_id']
    strategy._run_plan_build_job(job_id)  # a second run of the same job

    assert len(calls) == 1
    assert AIOperation.query.filter_by(thread_id=tid, operation_type='execution_plan').count() == 1


def test_a_user_with_no_connectors_still_gets_a_plan(client, db, test_user, auth_headers, monkeypatch):
    from app.models_pm_sync import PmSyncBinding
    tid = 'plan-job-no-connectors'
    _seed(test_user, db, tid)
    mock_accounting(monkeypatch)
    _run_jobs_inline(monkeypatch)
    _provider(monkeypatch, [json.dumps(_ai_plan())])
    assert PmSyncBinding.query.filter_by(user_id=test_user.id).count() == 0

    job_id = _start(client, auth_headers, tid).get_json()['job_id']
    status = _status(client, auth_headers, tid, job_id).get_json()

    assert status['status'] == 'done'
    assert len(status['result']['project_wbs']['tasks']) == 12


def test_override_still_needs_confirmation_before_a_job_starts(client, db, test_user, auth_headers, monkeypatch):
    from app.models_plan_jobs import PlanBuildJob
    tid = 'plan-job-override'
    card = {**CARD, 'recommendation': {'verdict_key': 'decline', 'label': 'No-Bid'}}
    _seed(test_user, db, tid, card)
    mock_accounting(monkeypatch)
    _run_jobs_inline(monkeypatch)

    blocked = _start(client, auth_headers, tid)

    assert blocked.status_code == 409
    assert blocked.get_json()['code'] == 'recorded_advancing_decision_required'
    assert PlanBuildJob.query.filter_by(thread_id=tid).count() == 0


def test_status_of_another_users_job_is_not_found(client, db, test_user, auth_headers):
    from app.models_plan_jobs import PlanBuildJob
    job = PlanBuildJob(user_id='someone-else', thread_id='t', request_json={})
    db.session.add(job)
    db.session.commit()
    assert _status(client, auth_headers, 't', job.id).status_code == 404


def test_chat_tool_plan_falls_back_to_a_starter_plan(app, db, test_user, monkeypatch):
    strategy, agent = modules()
    tid = 'plan-tool-starter'
    _seed(test_user, db, tid)
    mock_accounting(monkeypatch)
    monkeypatch.setattr(agent, 'get_llm_client', lambda: object(), raising=False)
    _provider(monkeypatch, [RuntimeError('provider unavailable')])
    result = agent._execute_mutation_tool(
        'generate_execution_plan', {'scorecard_id': 'planner-card', 'decision_acknowledged': True},
        user=test_user, user_id=test_user.id, thread_id=tid,
    )
    assert result['ok'] is True, result
    assert result['project_wbs']['generation_status'] == 'starter_plan'
    assert 'starter plan' in result['confirmation']


def test_chat_tool_plan_saves_over_unrelated_project_change(app, db, test_user, monkeypatch):
    strategy, agent = modules()
    tid = 'plan-tool-unrelated'
    _seed(test_user, db, tid)
    mock_accounting(monkeypatch)
    monkeypatch.setattr(agent, 'get_llm_client', lambda: object(), raising=False)
    _provider(monkeypatch, [json.dumps(_ai_plan())])
    real_persist = strategy._persist_generated_plan

    def persist_after_unrelated(user_id, thread_id, scorecard_id, plan, guard):
        strategy._save_project_scenarios(
            user_id,
            {thread_id: {**strategy._load_scenarios(user_id).get(thread_id, {}), 'unrelated': True}},
            thread_id,
        )
        return real_persist(user_id, thread_id, scorecard_id, plan, guard)

    monkeypatch.setattr(strategy, '_persist_generated_plan', persist_after_unrelated)
    result = agent._execute_mutation_tool(
        'generate_execution_plan', {'scorecard_id': 'planner-card', 'decision_acknowledged': True},
        user=test_user, user_id=test_user.id, thread_id=tid,
    )
    assert result['ok'] is True, result
    stored = strategy._load_scenarios(test_user.id)[tid]
    assert stored['unrelated'] is True
    assert strategy._resolve_thread_wbs(stored, 'planner-card')


def test_chat_tool_plan_same_option_conflict_reverses_once(app, db, test_user, monkeypatch):
    strategy, agent = modules()
    tid = 'plan-tool-conflict'
    _seed(test_user, db, tid)
    mock_accounting(monkeypatch)
    monkeypatch.setattr(
        agent,
        '_settle_reserved_credits',
        lambda *a, **k: {'ok': True, 'charged': 9},
    )
    monkeypatch.setattr(agent, 'get_llm_client', lambda: object(), raising=False)
    _provider(monkeypatch, [json.dumps(_ai_plan())])
    real_persist = strategy._persist_generated_plan
    reversals = []
    monkeypatch.setattr(
        agent, 'reverse_customer_operation_charge',
        lambda *_args, **kwargs: reversals.append(kwargs.get('error_code')),
    )

    def competing_plan_first(user_id, thread_id, scorecard_id, plan, guard):
        competitor = {
            'scorecard_id': scorecard_id, 'updated_at': 'competitor',
            'tasks': [{'id': 'kept', 'title': 'Keep me'}],
        }
        real_persist(user_id, thread_id, scorecard_id, competitor, guard)
        return real_persist(user_id, thread_id, scorecard_id, plan, guard)

    monkeypatch.setattr(strategy, '_persist_generated_plan', competing_plan_first)
    result = agent._execute_mutation_tool(
        'generate_execution_plan', {'scorecard_id': 'planner-card', 'decision_acknowledged': True},
        user=test_user, user_id=test_user.id, thread_id=tid,
    )
    assert result['ok'] is False
    assert result['code'] == 'revision_conflict'
    assert len(reversals) == 1
    stored = strategy._resolve_thread_wbs(
        strategy._load_scenarios(test_user.id)[tid], 'planner-card',
    )
    assert stored['tasks'][0]['title'] == 'Keep me'


def test_starter_plan_traces_every_source_into_ordered_phases():
    from app.decision_lineage import STARTER_PLAN_LABEL, build_starter_plan, validate_plan_lineage
    sources = [
        {'type': 'decision_commitment', 'ref': 'd1', 'label': 'Moving forward with Denver.', 'required': True},
        {'type': 'gate', 'ref': 'surety', 'label': 'Surety / bond confirmation', 'required': True},
        {'type': 'condition', 'ref': 'c1', 'label': 'Bond issued before award', 'required': True},
        {'type': 'weak_criterion', 'ref': 'delivery', 'label': 'Delivery capacity', 'required': True},
        {'type': 'risk', 'ref': 'r1', 'label': 'Crew availability in March', 'required': True},
        {'type': 'recommendation', 'ref': 'rec1', 'label': 'Line up a backup subcontractor', 'required': True},
    ]
    plan = build_starter_plan(sources)
    assert [phase['name'] for phase in plan['phases']] == [
        'Commit and confirm', 'Close the evidence gaps', 'Reduce the risks', 'Carry out the recommendations',
    ]
    titles = [task['title'] for phase in plan['phases'] for task in phase['tasks']]
    assert titles == [
        'Confirm owners and kick off the work',
        'Resolve the required check: Surety / bond confirmation',
        'Meet the condition: Bond issued before award',
        'Strengthen the evidence for Delivery capacity',
        'Mitigate the risk: Crew availability in March',
        'Line up a backup subcontractor',
    ]
    validated, result = validate_plan_lineage(plan, sources)
    assert validated is not None and result['missing_sources'] == []
    assert plan['summary'].startswith(STARTER_PLAN_LABEL) and 'It has 6 tasks' in plan['summary']
