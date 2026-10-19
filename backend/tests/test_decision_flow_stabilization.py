"""Targeted regressions for decision-flow trust boundaries; no live providers."""
import json
import sys
import types
import pytest
from flask import current_app
from app.models import AIOperation, AIProviderAttempt, Scorecard, UsageEvent
from app.scorecards import upsert_scorecard
from app.ai_runtime import execute_customer_operation


def modules():
    return sys.modules['app.routes.strategy'], sys.modules['app.routes.ai_agent']


def _lineage_tasks(count, *, ref='r1', start=1):
    return [
        {
            'id': f'task-{index}',
            'title': f'Proposal delivery task {index}',
            'lineage': [{'type': 'recommendation', 'ref': ref}],
        }
        for index in range(start, start + count)
    ]


def _phased_lineage_plan(*, task_count=18, phase_count=6, ref='r1'):
    tasks_per_phase = task_count // phase_count
    remainder = task_count % phase_count
    phases = []
    task_number = 1
    prior_id = None
    for phase_index in range(phase_count):
        phase_tasks = []
        count = tasks_per_phase + (1 if phase_index < remainder else 0)
        for _ in range(count):
            task_id = f'task-{task_number}'
            phase_tasks.append({
                'id': task_id,
                'title': f'Proposal delivery task {task_number}',
                'description': f'Complete proposal work item {task_number}.',
                'priority': 'high' if task_number <= 3 else 'medium',
                'estimated_days': (task_number % 5) + 1,
                'suggested_role': 'Proposal Lead',
                'function': 'Operations',
                'activity_type': 'delivery',
                'dependencies': [prior_id] if prior_id else [],
                'risk_area': 'Proposal readiness',
                'lineage': [{'type': 'recommendation', 'ref': ref}],
            })
            prior_id = task_id
            task_number += 1
        phases.append({'name': f'Phase {phase_index + 1}', 'tasks': phase_tasks})
    return {'name': 'Proposal execution plan', 'summary': 'Deliver the proposal.', 'phases': phases}


def test_execution_planner_worker_has_context(app, monkeypatch):
    strategy, _ = modules()
    def provider(*args, **kwargs):
        assert current_app._get_current_object() is app
        assert kwargs['operation_type'] == 'execution_plan'
        return json.dumps({'tasks': _lineage_tasks(10)}), {'provider': 'anthropic', 'input_tokens': 10, 'output_tokens': 10}
    monkeypatch.setattr(strategy, '_strategy_generate_reply', provider)
    plan, usage, success, error = strategy._generate_ai_wbs_suggestion(None, 'model', scorecard={'project_name': 'Proposal'}, instruction='', model_selection={'llm_model': 'model'}, return_usage=True, lineage_sources=[{'type': 'recommendation', 'ref': 'r1', 'label': 'Prepare proposal', 'required': True}])
    assert success and error is None
    assert len(plan['tasks']) == 10 and usage['output_tokens'] == 10
    assert plan['tasks'][0]['lineage'][0]['ref'] == 'r1'


def test_execution_plan_canonicalizes_duplicate_lineage_and_junk_dependencies(app, monkeypatch):
    strategy, _ = modules()
    response = {"tasks": [
        {"id": "task", "title": "First", "lineage": [
            {"type": "recommendation", "ref": "r1"},
            {"type": "recommendation", "ref": "r1"},
        ], "dependencies": ["missing", "task"]},
        {"id": "task", "title": "Second", "lineage": [
            {"type": "recommendation", "ref": "r1"},
        ], "dependencies": ["task", "missing"]},
    ] + _lineage_tasks(8, start=3)}
    monkeypatch.setattr(strategy, '_strategy_generate_reply', lambda *a, **k: (json.dumps(response), {}))
    sources = [{"type": "recommendation", "ref": "r1", "label": "Prepare", "required": True}]
    plan, _, success, error = strategy._generate_ai_wbs_suggestion(
        None, 'model', scorecard={'project_name': 'Proposal'}, instruction='',
        model_selection={'llm_model': 'model'}, return_usage=True, lineage_sources=sources,
    )
    assert success and error is None
    assert [task['id'] for task in plan['tasks'][:2]] == ['task', 'task-2']
    assert len(plan['tasks'][0]['lineage']) == 1
    assert plan['tasks'][0]['dependencies'] == []
    assert plan['tasks'][1]['dependencies'] == ['task']


def test_execution_plan_retries_once_when_lineage_validation_leaves_too_few_tasks(app, monkeypatch):
    strategy, _ = modules()
    prompts = []
    responses = [
        {'tasks': _lineage_tasks(6)},
        {'tasks': _lineage_tasks(12)},
    ]

    def provider(messages, **_kwargs):
        prompts.append(messages[0]['content'])
        return json.dumps(responses[len(prompts) - 1]), {
            'provider': 'anthropic', 'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15,
        }

    monkeypatch.setattr(strategy, '_strategy_generate_reply', provider)
    plan, usage, success, error = strategy._generate_ai_wbs_suggestion(
        None, 'model', scorecard={'project_name': 'Proposal'}, instruction='',
        model_selection={'llm_model': 'model'}, return_usage=True,
        lineage_sources=[{'type': 'recommendation', 'ref': 'r1', 'label': 'Prepare', 'required': True}],
    )

    assert success and error is None
    assert len(prompts) == 2
    assert 'valid tasks after lineage validation: 6; minimum required: 10' in prompts[1]
    assert 'Do not add generic padding' in prompts[1]
    assert len(plan['tasks']) == 12
    assert usage['input_tokens'] == 20
    assert usage['output_tokens'] == 10
    assert usage['total_tokens'] == 30
    assert len(usage['component_usages']) == 2
    first_attempt, second_attempt = usage['component_usages']
    assert first_attempt['attempt'] == 1
    assert first_attempt['duration_ms'] >= 0
    assert first_attempt['lineage_valid_task_count'] == 6
    assert first_attempt['lineage_dropped_tasks'] == []
    assert first_attempt['outcome'] == 'insufficient_valid_tasks'
    assert second_attempt['attempt'] == 2
    assert second_attempt['lineage_valid_task_count'] == 12
    assert second_attempt['outcome'] == 'accepted'


def test_execution_plan_repairs_only_missing_lineage_coverage(app, monkeypatch):
    strategy, _ = modules()
    calls = []
    initial = _phased_lineage_plan(task_count=16, phase_count=4, ref='r1')
    repair = {'tasks': [{
        'id': 'repair-commercial-risk',
        'title': 'Resolve Proposal contract commercial risk',
        'description': 'Close the contract commercial risk before approval.',
        'priority': 'high',
        'estimated_days': 3,
        'suggested_role': 'Commercial Lead',
        'function': 'Legal',
        'activity_type': 'risk_management',
        'dependencies': [],
        'risk_area': 'Contract commercial risk',
        'phase': 'Phase 4',
        'lineage': [{'type': 'weak_criterion', 'ref': 'contract_commercial_risk'}],
    }]}

    def provider(messages, **kwargs):
        calls.append((messages[0]['content'], kwargs['max_tokens']))
        response = initial if len(calls) == 1 else repair
        return json.dumps(response), {
            'provider': 'anthropic', 'stop_reason': 'end_turn',
            'input_tokens': 10, 'output_tokens': 20, 'total_tokens': 30,
        }

    clock_values = iter([0, 0, 0, 42, 42, 42, 43])
    monkeypatch.setattr(strategy, 'time', types.SimpleNamespace(monotonic=lambda: next(clock_values)))
    monkeypatch.setattr(strategy, '_strategy_generate_reply', provider)
    plan, usage, success, error = strategy._generate_ai_wbs_suggestion(
        None, 'model', scorecard={'project_name': 'Proposal'}, instruction='',
        model_selection={'llm_model': 'model'}, return_usage=True,
        lineage_sources=[
            {'type': 'recommendation', 'ref': 'r1', 'label': 'Prepare', 'required': True},
            {'type': 'weak_criterion', 'ref': 'contract_commercial_risk', 'label': 'Commercial risk', 'required': True},
        ],
    )

    assert success and error is None
    assert [max_tokens for _prompt, max_tokens in calls] == [8000, 600]
    assert 'return at most 2 tasks' in calls[1][0]
    assert 'Do not repeat or regenerate the existing plan' in calls[1][0]
    assert len(plan['tasks']) == 17
    assert len(plan['phases']) == 4
    assert plan['lineage_validation']['missing_sources'] == []
    assert [item['outcome'] for item in usage['component_usages']] == [
        'coverage_repair_required', 'repair_accepted',
    ]
    assert usage['component_usages'][1]['attempt_type'] == 'coverage_repair'


def test_execution_plan_retries_truncated_json_with_compact_descriptions(app, monkeypatch):
    strategy, _ = modules()
    prompts = []
    max_tokens = []
    complete = _phased_lineage_plan()

    def provider(messages, **kwargs):
        prompts.append(messages[0]['content'])
        max_tokens.append(kwargs['max_tokens'])
        if len(prompts) == 1:
            return '{"name":"Proposal plan","phases":[{"name":"Phase 1","tasks":[', {
                'provider': 'anthropic', 'stop_reason': 'max_tokens',
                'input_tokens': 10, 'output_tokens': 8000, 'total_tokens': 8010,
            }
        return json.dumps(complete), {
            'provider': 'anthropic', 'stop_reason': 'end_turn',
            'input_tokens': 12, 'output_tokens': 4000, 'total_tokens': 4012,
        }

    monkeypatch.setattr(strategy, '_strategy_generate_reply', provider)
    plan, usage, success, error = strategy._generate_ai_wbs_suggestion(
        None, 'model', scorecard={'project_name': 'Proposal'}, instruction='',
        model_selection={'llm_model': 'model'}, return_usage=True,
        lineage_sources=[{'type': 'recommendation', 'ref': 'r1', 'label': 'Prepare', 'required': True}],
    )

    assert success and error is None
    assert max_tokens == [8000, 8000]
    assert len(prompts) == 2
    assert 'output-token limit' in prompts[1]
    assert 'one concise sentence' in prompts[1]
    assert 'Do not return fewer tasks' in prompts[1]
    assert len(plan['tasks']) == 18
    assert len(plan['phases']) == 6
    assert usage['stop_reason'] == 'end_turn'
    assert [item['stop_reason'] for item in usage['component_usages']] == ['max_tokens', 'end_turn']
    assert [item['outcome'] for item in usage['component_usages']] == ['truncated_json', 'accepted']
    assert all(item['duration_ms'] >= 0 for item in usage['component_usages'])


def test_execution_plan_malformed_twice_returns_clean_failure(app, monkeypatch):
    strategy, _ = modules()
    prompts = []

    def provider(messages, **_kwargs):
        prompts.append(messages[0]['content'])
        return '{"phases":[', {
            'provider': 'anthropic', 'stop_reason': 'end_turn',
            'input_tokens': 2, 'output_tokens': 3, 'total_tokens': 5,
        }

    monkeypatch.setattr(strategy, '_strategy_generate_reply', provider)
    plan, usage, success, error = strategy._generate_ai_wbs_suggestion(
        None, 'model', scorecard={'project_name': 'Proposal'}, instruction='',
        model_selection={'llm_model': 'model'}, return_usage=True,
        lineage_sources=[{'type': 'recommendation', 'ref': 'r1', 'label': 'Prepare', 'required': True}],
    )

    assert len(prompts) == 2
    assert 'not valid JSON' in prompts[1]
    assert plan is None and not success
    assert error == 'invalid_wbs_response'
    assert usage['total_tokens'] == 10


def test_execution_plan_18_tasks_six_phases_materializes_intact(app, monkeypatch):
    strategy, _ = modules()
    response = _phased_lineage_plan()
    monkeypatch.setattr(
        strategy,
        '_strategy_generate_reply',
        lambda *args, **kwargs: (json.dumps(response), {'provider': 'test', 'stop_reason': 'end_turn'}),
    )
    plan, _, success, error = strategy._generate_ai_wbs_suggestion(
        None, 'model', scorecard={'project_name': 'Proposal'}, instruction='',
        model_selection={'llm_model': 'model'}, return_usage=True,
        lineage_sources=[{'type': 'recommendation', 'ref': 'r1', 'label': 'Prepare', 'required': True}],
    )
    assert success and error is None
    assert len(plan['tasks']) == 18
    assert len(plan['phases']) == 6

    materialized = strategy._materialize_ai_wbs(plan, start_date='2026-10-20')
    assert len(materialized['tasks']) == 18
    assert len(materialized['phases']) == 6
    assert [len(phase['task_ids']) for phase in materialized['phases']] == [3, 3, 3, 3, 3, 3]
    assert materialized['tasks'][-1]['depends_on'] == [materialized['tasks'][-2]['id']]


def test_execution_plan_logs_lineage_validation_details(app, monkeypatch, caplog):
    strategy, _ = modules()
    response = {"tasks": [{"id": "task", "title": "Unlinked", "lineage": [
        {"type": "recommendation", "ref": "junk"},
    ]}]}
    monkeypatch.setattr(strategy, '_strategy_generate_reply', lambda *a, **k: (json.dumps(response), {}))
    sources = [{"type": "recommendation", "ref": "required", "label": "Required", "required": True}]
    plan, _, success, error = strategy._generate_ai_wbs_suggestion(
        None, 'model', scorecard={'project_name': 'Proposal'}, instruction='',
        model_selection={'llm_model': 'model'}, return_usage=True, lineage_sources=sources,
    )
    assert plan is None and not success and error == 'ValueError'
    assert 'invalid_plan_lineage' in caplog.text
    assert 'missing_sources' in caplog.text


def test_failed_execution_generation_is_degraded_and_does_not_charge(app, db, test_user, monkeypatch):
    strategy, _ = modules()
    monkeypatch.setattr(strategy, '_strategy_generate_reply', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('provider failed')))
    def generate():
        plan, usage, success, error = strategy._generate_ai_wbs_suggestion(None, 'model', scorecard={'project_name': 'Proposal'}, instruction='', model_selection={'llm_model': 'model'}, return_usage=True)
        assert plan is None and not success and error == 'RuntimeError'
        return plan, {'degraded': True, 'generation_failed': True, 'error_code': error}
    from app.billing_config import reset_user_monthly_credits
    reset_user_monthly_credits(test_user, app.config)
    initial = test_user.credits_remaining
    kwargs = dict(generate=generate, operation_type='execution_plan', request_payload={}, idempotency_key='failed-plan', thread_id='test-thread')
    plan, _, settlement = execute_customer_operation(test_user, **kwargs)
    row = AIOperation.query.filter_by(operation_type='execution_plan').one()
    assert plan is None
    assert row.status == 'degraded' and row.metadata_json['generation_failed']
    assert row.error_code == 'RuntimeError'
    assert not AIProviderAttempt.query.filter_by(operation_id=row.id, outcome='succeeded').count()
    assert settlement['charged_credits'] == 0 and test_user.credits_remaining == initial
    replayed_plan, _, replay = execute_customer_operation(test_user, **kwargs)
    assert replayed_plan is None and replay['idempotent_replay']


def test_agent_reads_seven_canonical_cards_and_current_rescore(app, db, test_user):
    _, agent = modules()
    for i in range(7):
        upsert_scorecard(user_id=test_user.id, thread_id='seven', payload={'id': f'card-{i}', 'project_name': f'Option {i}', 'jaspen_score': 30+i})
    upsert_scorecard(user_id=test_user.id, thread_id='other', payload={'id': 'other', 'jaspen_score': 99})
    upsert_scorecard(user_id=test_user.id, thread_id='seven', payload={'id': 'card-3', 'project_name': 'Option 3', 'jaspen_score': 72})
    db.session.commit()
    session = {'result': {'id': 'card-3', 'jaspen_score': 59}}
    cards = agent._collect_session_scorecards(session, user_id=test_user.id, thread_id='seven')
    assert len(cards) == 7
    assert next(c for c in cards if c['id'] == 'card-3')['jaspen_score'] == 72
    prompt = agent._scorecard_content_prompt_suffix(session, {}, user_id=test_user.id, thread_id='seven')
    for i in range(7):
        assert f'Option {i}' in prompt
    assert 'other' not in {c['id'] for c in cards}


def test_queue_keeps_seven_and_never_leaks_continuation(app, db, test_user, monkeypatch):
    _, agent = modules()
    monkeypatch.setattr(agent, 'load_user_sessions', lambda uid: {'seven': {'session_id': 'seven'}})
    saved = []
    monkeypatch.setattr(agent, 'save_user_sessions', lambda uid, sessions: saved.append(sessions) or True)
    result = agent._execute_mutation_tool('queue_scorecards', {'ideas': [{'name': f'Option {i}'} for i in range(7)]}, user=test_user, user_id=test_user.id, thread_id='seven')
    assert result['ok'], result
    assert len(result['queue']) == 7 and result['overflow_count'] == 0
    visible = agent._mutation_result_summary('queue_scorecards', result)['confirmation']
    assert 'continue' not in visible.lower() and 'tell the user' not in visible.lower()
    assert len(saved[-1]['seven']['scorecard_queue']) == 7
    assert "Jaspen's standard criteria" in result['confirmation']
    assert 'your rubric' not in result['confirmation']


def test_short_score_action_routes_as_structured(app):
    _, agent = modules()
    from app.ai_governance import routing_decision, ROUTE_ROUTINE
    signals = agent._conversation_routing_signals('Score all 7 now', [], session={})
    decision = routing_decision(text='Score all 7 now', **signals)
    assert decision['route_class'] != ROUTE_ROUTINE


def test_short_action_survives_provider_failure(app, monkeypatch):
    _, agent = modules()
    monkeypatch.setattr(agent, '_resolve_governed_routes', lambda *a, **k: ([{'provider': 'anthropic', 'model': 'first'}, {'provider': 'anthropic', 'model': 'second'}], {}))
    calls = []
    def generate(message, history, readiness, selection, **kwargs):
        calls.append((message, selection['llm_model'], kwargs['allow_failover']))
        if len(calls) == 1:
            raise ValueError('invalid_response')
        return 'Scoring all seven.', {'provider': 'anthropic', 'model': 'second'}, [{'tool': 'queue_scorecards'}], [], None
    monkeypatch.setattr(agent, '_generate_assistant_reply_anthropic', generate)
    result = agent._generate_assistant_reply('Score all 7 now', [], {}, {'llm_model': 'first'}, session={})
    assert [c[0] for c in calls] == ['Score all 7 now'] * 2
    assert result[2][0]['tool'] == 'queue_scorecards'
    assert result[1]['failover']['attempted_providers'][0]['outcome'] == 'invalid_response'


def test_exhausted_action_raises_instead_of_successful_heuristic(app, monkeypatch):
    _, agent = modules()
    monkeypatch.setattr(agent, '_resolve_governed_routes', lambda *a, **k: ([{'provider': 'anthropic', 'model': 'first'}], {}))
    monkeypatch.setattr(agent, '_generate_assistant_reply_anthropic', lambda *a, **k: (_ for _ in ()).throw(ValueError('invalid_response')))
    with pytest.raises(agent.ConversationProviderUnavailable) as error:
        agent._generate_assistant_reply('Score all 7 now', [], {}, {'llm_model': 'first'}, session={})
    assert error.value.jaspen_usage['failover']['attempted_providers']


def test_streaming_short_action_fails_over_without_losing_request(app, monkeypatch):
    _, agent = modules()
    monkeypatch.setattr(agent, '_resolve_governed_routes', lambda *a, **k: ([{'provider': 'anthropic', 'model': 'first'}, {'provider': 'anthropic', 'model': 'second'}], {}))
    calls = []
    def stream(message, history, readiness, selection, **kwargs):
        calls.append(message)
        if len(calls) == 1:
            raise ValueError('invalid_response')
        kwargs['state'].update(reply='Scoring seven.', usage={'provider': 'anthropic', 'model': 'second'}, actions=[{'tool': 'queue_scorecards'}])
        yield {'type': 'delta', 'text': 'Scoring seven.'}
    monkeypatch.setattr(agent, '_stream_assistant_reply_events_anthropic', stream)
    state = {}
    events = list(agent._stream_assistant_reply_events('Score all 7 now', [], {}, {'llm_model': 'first'}, session={}, state=state))
    assert calls == ['Score all 7 now'] * 2
    assert events == [{'type': 'delta', 'text': 'Scoring seven.'}]
    assert state['actions'][0]['tool'] == 'queue_scorecards'
    assert state['usage']['failover']['attempted_providers'][0]['outcome'] == 'invalid_response'


def test_model_unavailable_404_uses_next_route(app):
    _, agent = modules()
    error = RuntimeError('model unavailable')
    error.status_code = 404
    assert agent._classify_provider_error(error) == {'retryable': True, 'reason': 'model_unavailable', 'status_code': 404}


def seed_thread(user, thread_id, cards=None):
    from app.routes.sessions import save_user_sessions
    cards = cards or []
    result = {**cards[0], '_baseline_scorecard': cards[0], 'scorecard_snapshots': cards} if cards else {}
    assert save_user_sessions(user.id, {thread_id: {'session_id': thread_id, 'user_id': user.id, 'name': 'Validation', 'status': 'completed' if cards else 'in_progress', 'result': result, 'chat_history': [], 'scorecard_queue': []}})


def mock_accounting(monkeypatch):
    strategy, agent = modules()
    monkeypatch.setattr(strategy, 'get_llm_client', lambda: object())
    monkeypatch.setattr(agent, '_reserve_preflight_credits', lambda *a, **k: {'ok': True, 'reserved': 0})
    monkeypatch.setattr(agent, '_settle_reserved_credits', lambda *a, **k: {'ok': True, 'charged': 0})


def seed_rfp_thread(user, thread_id, *, decision_kit='rfp_bid', queue=None):
    from app.decision_kits import get_decision_kit
    from app.routes.sessions import save_user_sessions

    kit = get_decision_kit(decision_kit)
    assert save_user_sessions(user.id, {thread_id: {
        'session_id': thread_id,
        'user_id': user.id,
        'name': 'RFP validation',
        'status': 'in_progress',
        'decision_kit': decision_kit,
        'decision_kit_version': 1,
        'decision_kit_family': 'rfp',
        'scoring_rubric': {
            'criteria': list(kit.get('starter_rubric') or []),
            'source': 'decision_kit',
            'approved_by_user_at': '2026-10-06T00:00:00Z',
        },
        'chat_history': [{'role': 'user', 'content': 'Use the stated proposal facts to score this RFP.'}],
        'scorecard_queue': list(queue or []),
    }})


def test_real_single_rfp_generate_scorecard_tool_path_normalizes_aliases(app, db, test_user, monkeypatch):
    strategy, agent = modules()
    tid = 'live-single-rfp-alias'
    seed_rfp_thread(test_user, tid)
    mock_accounting(monkeypatch)
    monkeypatch.setattr(strategy, '_generate_jaspen_scorecard', lambda *a, **k: ({
        'jaspen_score': 62,
        'score_category': 'Good',
        'dimensions': {'financial_attractiveness': {'score': 62, 'confidence': 'medium'}},
        'gates': [],
    }, {'provider': 'test', 'model': 'test', 'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}))

    result = agent._execute_mutation_tool(
        'generate_scorecard',
        {
            'name': 'Aurora RFP',
            'idea_description': 'Score Aurora for a bid response.',
            'attributes': {
                'proposal_due_date': {'value': '11/14/2026', 'source': 'user'},
                'contract_value': {'value': '$60M', 'source': 'user'},
                'made_up_rank': {'value': 4, 'source': 'user'},
            },
        },
        user=test_user,
        user_id=test_user.id,
        thread_id=tid,
    )

    assert result['ok'] is True, result
    card = result['scorecard']
    assert card['attributes']['submission_due']['value'] == '2026-11-14'
    assert card['attributes']['contract_value']['value'] == 60_000_000
    assert 'made_up_rank' not in card['attributes']
    assert card['rejected_attributes'][0]['field'] == 'made_up_rank'
    assert card['rejected_attributes'][0]['reason'] == "Evidence could not be grounded in the user's words"
    assert card['context_notes'] == []


def test_rfp_queue_persists_explicit_submission_dates_omitted_by_provider(app, db, test_user):
    _, agent = modules()
    from app.routes.sessions import load_user_sessions, save_user_sessions

    tid = 'rfp-queue-date-capture'
    seed_rfp_thread(test_user, tid)
    sessions = load_user_sessions(test_user.id)
    sessions[tid]['chat_history'] = [{
        'role': 'user',
        'content': (
            'Denver Water: Contract value $12M. Submission due November 20, 2026. Surety confirmed. '
            'Adams County: Contract value $10M. Submission due November 21, 2026. '
            'The bond is still pending surety review.'
        ),
    }]
    assert save_user_sessions(test_user.id, sessions)

    result = agent._execute_mutation_tool(
        'queue_scorecards',
        {'ideas': [
            {
                'name': 'Denver Water',
                'attributes': {'contract_value': {
                    'value': '$12M', 'source': 'user', 'evidence': 'Contract value $12M',
                }},
            },
            {
                'name': 'Adams County',
                'attributes': {'contract_value': {
                    'value': '$10M', 'source': 'user', 'evidence': 'Contract value $10M',
                }},
            },
        ]},
        user=test_user, user_id=test_user.id, thread_id=tid,
    )

    assert result['ok'] is True, result
    assert [item['attributes']['submission_due']['value'] for item in result['queue']] == [
        '2026-11-20', '2026-11-21',
    ]
    assert [item['attributes']['surety_status']['value'] for item in result['queue']] == [
        'confirmed', 'pending',
    ]
    durable = load_user_sessions(test_user.id)[tid]
    assert [item['attributes']['submission_due']['value'] for item in durable['scorecard_queue']] == [
        '2026-11-20', '2026-11-21',
    ]
    assert durable['scorecard_queue'][1]['attributes']['surety_status']['value'] == 'pending'


def test_unlabeled_contract_amount_is_grounded_without_cross_field_guessing(app):
    from app.decision_facts import ground_user_evidence, normalize_fact_entry
    from app.decision_kits import get_decision_kit
    from app.decision_metrics import calculate_metrics

    kit = get_decision_kit('rfp_bid')
    sentence = "Bid 1: Adams County road resurfacing, $4.2M, our margin ~11%."
    evidence = ground_user_evidence('contract_value', '$4.2M', '$4.2M', sentence, kit=kit)
    assert evidence == sentence
    _, contract = normalize_fact_entry(
        'contract_value', {'value': '$4.2M', 'source': 'user', 'evidence': evidence}, kit=kit,
    )
    metrics = calculate_metrics({
        'contract_value': contract,
        'win_probability': {'value': 40, 'source': 'user', 'evidence': 'win probability 40%'},
        'margin_pct': {'value': 11, 'source': 'user', 'evidence': 'margin 11%'},
    }, kit['metrics'])
    assert metrics['expected_value']['value'] == 184_800
    assert ground_user_evidence(
        'build_out_cost', '$320,000', '$320,000',
        'Monthly lease is now $320,000.', kit=kit,
    ) is None


def test_surety_approved_alias_normalizes_and_grounds_as_confirmed(app):
    from app.decision_facts import ground_user_evidence, normalize_fact_entry
    from app.decision_kits import get_decision_kit

    kit = get_decision_kit('rfp_bid')
    sentence = 'Surety bonding is approved for all three.'
    key, entry = normalize_fact_entry(
        'surety_status', {'value': 'approved', 'source': 'user', 'evidence': sentence}, kit=kit,
    )
    assert key == 'surety_status' and entry['value'] == 'confirmed'
    assert ground_user_evidence(
        'surety_status', 'confirmed', sentence, sentence, kit=kit,
    ) == sentence


@pytest.mark.parametrize(('excerpt', 'expected'), [
    ('has declined', 'declined'),
    ("hasn't declined", None),
    ('has not declined', None),
    ("didn't decline", None),
    ('no longer pending', None),
    ("hasn't declined; the request is still pending", 'pending'),
    ('approved the bond', 'confirmed'),
])
def test_enum_value_from_user_excerpt_ignores_negated_phrases(app, excerpt, expected):
    from app.decision_facts import _enum_value_from_user_excerpt
    from app.decision_kits import get_decision_kit

    surety_status = next(
        field for field in get_decision_kit('rfp_bid')['fields']
        if field['key'] == 'surety_status'
    )

    assert _enum_value_from_user_excerpt(excerpt, surety_status) == expected


def test_exact_user_excerpt_overrides_reworded_enum_and_text_values(app):
    from app.decision_facts import ground_user_evidence, normalize_fact_entry
    from app.decision_kits import get_decision_kit

    kit = get_decision_kit('rfp_bid')
    cases = [
        (
            'surety_status', 'declined',
            'Our surety has declined to provide the required performance bond for this job.',
            'declined',
        ),
        (
            'surety_status', 'declined - surety will not issue required performance bond',
            'Our surety has declined to provide the required performance bond for this job.',
            'declined',
        ),
        ('surety_status', 'pending', "We haven't decided on surety yet.", 'pending'),
        (
            'past_project_experience', '3 similar water main jobs in last 2 years',
            'We have done three similar water main jobs in the last two years.',
            'We have done three similar water main jobs in the last two years.',
        ),
        ('client', 'City of Aurora', 'The client is the City of Aurora.', 'The client is the City of Aurora.'),
    ]

    for key, provider_value, quote, expected in cases:
        assert ground_user_evidence(
            key, provider_value, quote, quote, kit=kit,
        ) == quote
        normalized_key, entry = normalize_fact_entry(
            key,
            {'value': provider_value, 'source': 'user', 'evidence': quote},
            kit=kit,
        )
        assert entry['value'] == expected
        assert ground_user_evidence(
            normalized_key, entry['value'], quote, quote, kit=kit,
        ) == quote


def test_exact_money_excerpt_with_reworded_value_becomes_context_note(app, db, test_user):
    _, agent = modules()
    from app.routes.sessions import load_user_sessions, save_user_sessions

    tid = 'reworded-money-context-note'
    seed_rfp_thread(test_user, tid)
    quote = 'Pursuit cost is $80,000.'
    sessions = load_user_sessions(test_user.id)
    sessions[tid]['chat_history'] = [{'role': 'user', 'content': quote}]
    assert save_user_sessions(test_user.id, sessions)

    result = agent._execute_mutation_tool(
        'set_option_attributes', {'option': 'Aurora', 'fields': [{
            'key': 'pursuit_cost', 'value': '$800,000', 'source': 'user',
            'evidence': quote,
        }]},
        user=test_user, user_id=test_user.id, thread_id=tid, user_message=quote,
    )

    assert result['ok'], result
    assert 'pursuit_cost' not in result['option_attributes']
    session = load_user_sessions(test_user.id)[tid]
    note = next(iter(session['option_context_notes_by_key'].values()))[0]
    assert note['value'] == quote
    assert note['evidence'] == quote
    assert note['affects'] == ['financial_attractiveness']
    assert result['rejected_fields'] == []


def test_pending_surety_correction_saves_and_rescores_existing_card(
    app, db, test_user, monkeypatch,
):
    strategy, agent = modules()
    from app.decision_kits import get_decision_kit
    from app.routes.sessions import load_user_sessions, save_user_sessions

    tid = 'pending-surety-correction'
    seed_rfp_thread(test_user, tid)
    initial_quote = (
        'Our surety has declined to provide the required performance bond for this job.'
    )
    sessions = load_user_sessions(test_user.id)
    sessions[tid]['chat_history'] = [{'role': 'user', 'content': initial_quote}]
    kit = get_decision_kit('rfp_bid')
    sessions[tid]['scoring_rubric']['criteria'].extend({
        'key': item['key'], 'label': item['label'], 'weight': 0,
        'gate': True, 'gate_rule': item['rule'],
    } for item in kit['gate_suggestions'])
    assert save_user_sessions(test_user.id, sessions)
    mock_accounting(monkeypatch)

    def scorer(*_args, **kwargs):
        status = kwargs['attributes']['surety_status']['value']
        label = 'No-Bid' if status == 'declined' else 'Depends on confirming surety / bond confirmation'
        gate_status = 'fail' if status == 'declined' else 'unknown'
        return ({
            'jaspen_score': 52,
            'score_category': 'Mixed',
            'dimensions': {'delivery_capability_capacity': {
                'score': 52, 'confidence': 'medium',
            }},
            'gates': [{
                'key': 'surety_confirmation', 'label': 'Surety / bond confirmation',
                'status': gate_status, 'confidence': 'medium', 'source': 'conversation',
                'evidence': [kwargs['attributes']['surety_status']['evidence']],
                'basis': f'Surety status is {status}.',
            }],
            'recommendation': {'label': label},
        }, {'provider': 'test', 'input_tokens': 1, 'output_tokens': 1})

    monkeypatch.setattr(strategy, '_generate_jaspen_scorecard', scorer)
    saved_decline = agent._execute_mutation_tool(
        'set_option_attributes', {'option': 'Aurora RFP', 'fields': [{
            'key': 'surety_status',
            'value': 'declined - surety will not issue required performance bond',
            'source': 'user', 'evidence': initial_quote,
        }]},
        user=test_user, user_id=test_user.id, thread_id=tid, user_message=initial_quote,
    )
    first = agent._execute_mutation_tool(
        'generate_scorecard', {'name': 'Aurora RFP', 'idea_description': 'Score the RFP.'},
        user=test_user, user_id=test_user.id, thread_id=tid,
    )

    assert saved_decline['ok'], saved_decline
    assert saved_decline['option_attributes']['surety_status']['value'] == 'declined'
    assert first['ok'] and first['scorecard']['recommendation']['label'] == 'No-Bid'

    correction = (
        'Correction: our surety has not declined; its decision is still pending. Re-score with that.'
    )
    sessions = load_user_sessions(test_user.id)
    sessions[tid]['chat_history'].append({'role': 'user', 'content': correction})
    assert save_user_sessions(test_user.id, sessions)
    changed = agent._execute_mutation_tool(
        'set_option_attributes', {
            'option': 'Aurora RFP', 'scorecard_id': first['scorecard']['id'],
            'fields': [{
                'key': 'surety_status', 'value': 'not declined - awaiting surety decision',
                'source': 'user', 'evidence': correction,
            }],
        },
        user=test_user, user_id=test_user.id, thread_id=tid, user_message=correction,
    )
    rescored = agent._execute_mutation_tool(
        'generate_scorecard', {
            'name': 'Aurora RFP', 'idea_description': 'Re-score with corrected surety status.',
            'rescore_scorecard_id': first['scorecard']['id'],
        },
        user=test_user, user_id=test_user.id, thread_id=tid,
    )

    assert changed['ok'], changed
    assert changed['option_attributes']['surety_status']['value'] == 'pending'
    assert rescored['ok'] and rescored['rescored'], rescored
    assert rescored['updated_scorecard']['recommendation']['label'].startswith(
        'Depends on confirming'
    )


def test_full_corpus_fallback_rejects_evidence_naming_another_option(app):
    from app.decision_facts import ground_option_user_evidence
    from app.decision_kits import get_decision_kit

    corpus = 'Bid 1: Adams. Bid 2: Boulder. Bid 3 surety is pending.'
    assert ground_option_user_evidence(
        'surety_status', 'pending', 'Bid 3 surety is pending.',
        'Bid 1: Adams.', corpus, kit=get_decision_kit('rfp_bid'),
        current_option_names=['Bid 1', 'Adams'],
        other_option_names=['Bid 2', 'Boulder', 'Bid 3', 'Denver'],
    ) is None
    assert ground_option_user_evidence(
        'surety_status', 'pending', 'Bid 3 surety is pending.',
        'Bid 3: Denver.', corpus, kit=get_decision_kit('rfp_bid'),
        current_option_names=['Bid 3', 'Denver'],
        other_option_names=['Bid 1', 'Adams', 'Bid 2', 'Boulder'],
    ) == 'Bid 3 surety is pending.'


def test_live_rfp_prompt_queues_unlabeled_values_and_shared_surety_for_every_option(
    app, db, test_user,
):
    _, agent = modules()
    from app.decision_kits import get_decision_kit
    from app.decision_processing import normalize_gates
    from app.routes.sessions import load_user_sessions, save_user_sessions

    tid = 'rfp-unlabeled-shared-evidence'
    seed_rfp_thread(test_user, tid)
    prompt = (
        "We're a regional civil contractor deciding which of three municipal RFPs to bid. "
        "Bid 1: Adams County road resurfacing, $4.2M, due in 5 weeks, our margin ~11%, we've done similar work. "
        "Bid 2: Boulder stormwater upgrade, $6.8M, due in 3 weeks, margin ~14%, new client, needs a specialty sub. "
        "Bid 3: Denver bike lane package, $2.1M, due in 7 weeks, margin ~9%, low risk. "
        "Surety bonding is approved for all three. Score all three now."
    )
    sessions = load_user_sessions(test_user.id)
    sessions[tid]['chat_history'] = [{'role': 'user', 'content': prompt}]
    assert save_user_sessions(test_user.id, sessions)
    options = [
        ('Adams County Road Resurfacing', '$4.2M'),
        ('Boulder Stormwater Upgrade', '$6.8M'),
        ('Denver Bike Lane Package', '$2.1M'),
    ]
    shared = 'Surety bonding is approved for all three.'
    result = agent._execute_mutation_tool(
        'queue_scorecards', {'ideas': [{
            'name': name,
            'description': name,
            'fields': [
                {'key': 'contract_value', 'value': amount, 'source': 'user', 'evidence': amount},
                {'key': 'surety_status', 'value': 'confirmed', 'source': 'user', 'evidence': shared},
            ],
        } for name, amount in options]},
        user=test_user, user_id=test_user.id, thread_id=tid,
    )

    assert result['ok'], result
    kit = get_decision_kit('rfp_bid')
    rubric = {
        'approval_status': 'approved',
        'approved_by_user_at': '2026-10-11T00:00:00Z',
        'criteria': [
            {**gate, 'gate': True, 'gate_rule': gate.get('rule')}
            for gate in kit['gate_suggestions']
        ],
    }
    assert [item['attributes']['contract_value']['value'] for item in result['queue']] == [
        4_200_000, 6_800_000, 2_100_000,
    ]
    for item in result['queue']:
        attributes = item['attributes']
        assert attributes['surety_status']['value'] == 'confirmed'
        assert attributes['surety_status']['evidence'] == shared
        gates = {
            gate['key']: gate['status']
            for gate in normalize_gates([], rubric, prompt, attributes=attributes)
        }
        assert gates['capacity_available'] == 'pass'
        assert gates['surety_confirmation'] == 'pass'


def test_model_title_expansion_keeps_code_owned_option_identity_and_facts(app, db, test_user, monkeypatch):
    strategy, agent = modules()
    tid = 'stable-option-identity'
    seed_rfp_thread(test_user, tid)
    mock_accounting(monkeypatch)

    captured = agent._execute_mutation_tool(
        'set_option_attributes',
        {
            'option': 'Boulder Pearl Street',
            'fields': [{
                'key': 'contract_value', 'value': '$14M',
                'source': 'document', 'evidence': 'Contract value $14M',
            }],
        },
        user=test_user, user_id=test_user.id, thread_id=tid,
    )
    assert captured['ok'], captured
    original_key = captured['option_key']
    monkeypatch.setattr(strategy, '_generate_jaspen_scorecard', lambda *a, **k: ({
        'jaspen_score': 64,
        'score_category': 'Good',
        'dimensions': {'financial_attractiveness': {'score': 64, 'confidence': 'medium'}},
        'gates': [],
    }, {'provider': 'test', 'model': 'test', 'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}))

    scored = agent._execute_mutation_tool(
        'generate_scorecard',
        {
            'name': 'Boulder Pearl Street Second Location',
            'idea_description': 'Score the Boulder Pearl Street option.',
        },
        user=test_user, user_id=test_user.id, thread_id=tid,
    )

    assert scored['ok'], scored
    assert scored['scorecard']['option_key'] == original_key
    assert scored['scorecard']['attributes']['contract_value']['value'] == 14_000_000
    session = agent.load_user_sessions(test_user.id)[tid]
    assert session['option_aliases']['boulder pearl street'] == original_key
    assert session['option_aliases']['boulder pearl street second location'] == original_key


def test_scored_option_cannot_be_reused_as_a_differently_named_new_option(
    app, db, test_user, monkeypatch,
):
    """A stale pending registry entry must not let option B take over option A."""
    strategy, agent = modules()
    from app.routes.sessions import load_user_sessions, save_user_sessions

    tid = 'sequential-then-new-option'
    seed_thread(test_user, tid)
    sessions = load_user_sessions(test_user.id)
    sessions[tid]['scoring_rubric'] = {
        'approval_status': 'approved',
        'approved_by_user_at': '2026-10-10T10:00:00Z',
        'criteria': [
            {'key': 'financial_value', 'label': 'Financial value', 'weight': 0.6},
            {'key': 'location_fit', 'label': 'Location fit', 'weight': 0.4},
        ],
    }
    sessions[tid]['chat_history'] = [{
        'role': 'user',
        'content': (
            'Coffee Kiosk at Union Station has build-out cost $85,000 '
            'and monthly lease $7,200.'
        ),
    }]
    assert save_user_sessions(test_user.id, sessions)
    mock_accounting(monkeypatch)

    provider_calls = []

    def scorer(*args, **kwargs):
        attributes = kwargs.get('attributes') or {}
        provider_calls.append({
            key: entry.get('value') for key, entry in attributes.items()
            if isinstance(entry, dict)
        })
        return ({
            'jaspen_score': 60,
            'score_category': 'Good',
            'dimensions': {
                'financial_value': {'score': 60, 'confidence': 'high'},
                'location_fit': {'score': 60, 'confidence': 'high'},
            },
            'gates': [],
        }, {
            'provider': 'test', 'model': 'test',
            'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2,
        })

    monkeypatch.setattr(strategy, '_generate_jaspen_scorecard', scorer)
    union_attributes = {
        'build_out_cost': {
            'value': '$85,000', 'source': 'user',
            'evidence': 'build-out cost $85,000',
        },
        'monthly_lease': {
            'value': '$7,200', 'source': 'user',
            'evidence': 'monthly lease $7,200',
        },
    }
    first = agent._execute_mutation_tool(
        'generate_scorecard', {
            'name': 'Coffee Kiosk at Union Station',
            'idea_description': 'Score the Union Station kiosk.',
            'attributes': union_attributes,
        },
        user=test_user, user_id=test_user.id, thread_id=tid,
    )
    assert first['ok'], first
    union_card = first['scorecard']

    # Reproduce the live session shape: the scorecard is durable, while its
    # sole registry entry is still marked pending. The old title-expansion
    # shortcut treated the next name as another alias for this option.
    sessions = load_user_sessions(test_user.id)
    union_key = union_card['option_key']
    sessions[tid]['option_registry'][union_key]['status'] = 'pending'
    sessions[tid]['chat_history'].append({
        'role': 'user',
        'content': (
            'Coffee Kiosk at Airport Terminal B has build-out cost $140,000 '
            'and monthly lease $12,500.'
        ),
    })
    assert save_user_sessions(test_user.id, sessions)

    airport = agent._execute_mutation_tool(
        'generate_scorecard', {
            'name': 'Coffee Kiosk at Airport Terminal B',
            'idea_description': 'Score the Airport Terminal B kiosk.',
            'attributes': {
                'build_out_cost': {
                    'value': '$140,000', 'source': 'user',
                    'evidence': 'build-out cost $140,000',
                },
                'monthly_lease': {
                    'value': '$12,500', 'source': 'user',
                    'evidence': 'monthly lease $12,500',
                },
            },
        },
        user=test_user, user_id=test_user.id, thread_id=tid,
    )

    assert airport['ok'], airport
    airport_card = airport['scorecard']
    assert airport_card['option_key'] != union_key
    assert airport_card['attributes']['build_out_cost']['value'] == 140_000
    assert airport_card['attributes']['monthly_lease']['value'] == 12_500
    assert airport_card['decision_fingerprint'] != union_card['decision_fingerprint']
    assert airport_card['meta']['reused_source_scorecard_id'] is None

    # The first option remains independently reusable after the second is added.
    union_again = agent._execute_mutation_tool(
        'generate_scorecard', {
            'name': 'Coffee Kiosk at Union Station',
            'idea_description': 'Score the Union Station kiosk.',
            'attributes': union_attributes,
        },
        user=test_user, user_id=test_user.id, thread_id=tid,
    )
    assert union_again['ok'], union_again
    assert union_again['scorecard']['option_key'] == union_key
    assert union_again['scorecard']['decision_fingerprint'] == union_card['decision_fingerprint']
    assert union_again['scorecard']['meta']['reused_source_scorecard_id'] == union_card['id']
    assert provider_calls == [
        {'build_out_cost': 85_000, 'monthly_lease': 7_200},
        {'build_out_cost': 140_000, 'monthly_lease': 12_500},
    ]


def test_single_option_then_batch_reuses_a_without_reusing_it_for_b(
    app, client, db, test_user, auth_headers, monkeypatch,
):
    strategy, agent = modules()
    from app.routes.sessions import load_user_sessions, save_user_sessions

    tid = 'single-then-batch-option-identity'
    seed_thread(test_user, tid)
    sessions = load_user_sessions(test_user.id)
    sessions[tid]['scoring_rubric'] = {
        'approval_status': 'approved',
        'approved_by_user_at': '2026-10-10T10:00:00Z',
        'criteria': [
            {'key': 'financial_value', 'label': 'Financial value', 'weight': 0.6},
            {'key': 'location_fit', 'label': 'Location fit', 'weight': 0.4},
        ],
    }
    sessions[tid]['chat_history'] = [{
        'role': 'user',
        'content': (
            'Option A: Coffee Kiosk at Union Station. Build-out cost $85,000. '
            'Monthly lease $7,200. '
            'Option B: Coffee Kiosk at Airport Terminal B. Build-out cost $140,000. '
            'Monthly lease $12,500.'
        ),
    }]
    assert save_user_sessions(test_user.id, sessions)
    mock_accounting(monkeypatch)
    provider_names = []

    def scorer(*args, **kwargs):
        provider_names.append(kwargs.get('option_name'))
        return ({
            'jaspen_score': 60,
            'score_category': 'Good',
            'dimensions': {
                'financial_value': {'score': 60, 'confidence': 'high'},
                'location_fit': {'score': 60, 'confidence': 'high'},
            },
            'gates': [],
        }, {
            'provider': 'test', 'model': 'test',
            'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2,
        })

    monkeypatch.setattr(strategy, '_generate_jaspen_scorecard', scorer)
    union_attributes = {
        'build_out_cost': {
            'value': '$85,000', 'source': 'user',
            'evidence': 'Build-out cost $85,000.',
        },
        'monthly_lease': {
            'value': '$7,200', 'source': 'user',
            'evidence': 'Monthly lease $7,200.',
        },
    }
    first = agent._execute_mutation_tool(
        'generate_scorecard', {
            'name': 'Coffee Kiosk at Union Station',
            'idea_description': 'Score the Union Station kiosk.',
            'attributes': union_attributes,
        },
        user=test_user, user_id=test_user.id, thread_id=tid,
    )
    assert first['ok'], first

    queued = agent._execute_mutation_tool(
        'queue_scorecards', {'ideas': [
            {
                'name': 'Coffee Kiosk at Union Station',
                'description': 'Score the Union Station kiosk.',
                'attributes': union_attributes,
            },
            {
                'name': 'Coffee Kiosk at Airport Terminal B',
                'description': 'Score the Airport Terminal B kiosk.',
                'attributes': {
                    'build_out_cost': {
                        'value': '$140,000', 'source': 'user',
                        'evidence': 'Build-out cost $140,000.',
                    },
                    'monthly_lease': {
                        'value': '$12,500', 'source': 'user',
                        'evidence': 'Monthly lease $12,500.',
                    },
                },
            },
        ]},
        user=test_user, user_id=test_user.id, thread_id=tid,
    )
    assert queued['ok'], queued
    queued_by_name = {item['name']: item for item in queued['queue']}
    assert queued_by_name['Coffee Kiosk at Union Station']['option_key'] == first['scorecard']['option_key']
    assert queued_by_name['Coffee Kiosk at Airport Terminal B']['option_key'] != first['scorecard']['option_key']

    response = client.post(
        f'/api/v1/strategy/threads/{tid}/score-batch', headers=auth_headers, json={},
    )
    assert response.status_code == 200, response.get_json()
    assert response.get_json()['count'] == 2

    rows = Scorecard.query.filter_by(thread_id=tid).all()
    cards = [dict(row.data or {}) for row in rows]
    airport = next(card for card in cards if card.get('project_name') == 'Coffee Kiosk at Airport Terminal B')
    union_batch = next(
        card for card in cards
        if card.get('project_name') == 'Coffee Kiosk at Union Station'
        and card.get('id') != first['scorecard']['id']
    )
    assert airport['option_key'] != first['scorecard']['option_key']
    assert airport['attributes']['build_out_cost']['value'] == 140_000
    assert airport['decision_fingerprint'] != first['scorecard']['decision_fingerprint']
    assert not (
        airport.get('reused_source_scorecard_id')
        or (airport.get('meta') or {}).get('reused_source_scorecard_id')
    )
    assert (
        union_batch.get('reused_source_scorecard_id')
        or (union_batch.get('meta') or {}).get('reused_source_scorecard_id')
    ) == first['scorecard']['id']
    assert union_batch['decision_fingerprint'] == first['scorecard']['decision_fingerprint']
    assert provider_names == [
        'Coffee Kiosk at Union Station',
        'Coffee Kiosk at Airport Terminal B',
    ]


def test_approved_rubric_cannot_be_downgraded_or_replaced_by_agent(app, db, test_user):
    _, agent = modules()
    tid = 'immutable-approved-rubric'
    seed_rfp_thread(test_user, tid)
    before = agent.load_user_sessions(test_user.id)[tid]['scoring_rubric']

    result = agent._execute_mutation_tool(
        'set_scoring_rubric',
        {'criteria': [
            {'label': 'Agent replacement one', 'weight': 60},
            {'label': 'Agent replacement two', 'weight': 40},
        ]},
        user=test_user, user_id=test_user.id, thread_id=tid,
        user_message='Help me continue this analysis.',
    )

    assert result['ok'] and result['approved_rubric_preserved'] is True
    session = agent.load_user_sessions(test_user.id)[tid]
    assert session['scoring_rubric'] == before
    assert session['rubric_proposal']['approval_status'] == 'proposed'
    assert session['rubric_proposal']['criteria'] != before['criteria']


def test_material_fact_update_uses_option_key_history_and_forces_holistic_rescore(app, db, test_user, monkeypatch):
    strategy, agent = modules()
    from app.routes.sessions import load_user_sessions, save_user_sessions
    tid = 'material-fact-rescore'
    seed_thread(test_user, tid)
    sessions = load_user_sessions(test_user.id)
    sessions[tid]['scoring_rubric'] = {
        'approval_status': 'approved',
        'approved_by_user_at': '2026-10-09T10:00:00Z',
        'criteria': [
            {'key': 'financial_value', 'label': 'Financial value', 'weight': 0.6},
            {'key': 'delivery_confidence', 'label': 'Delivery confidence', 'weight': 0.4},
        ],
    }
    sessions[tid]['chat_history'] = [
        {'role': 'user', 'content': 'Boulder build-out is $240,000 and the lease term is 5 years.'},
    ]
    assert save_user_sessions(test_user.id, sessions)
    mock_accounting(monkeypatch)
    judged_values = []

    def scorer(*args, **kwargs):
        value = kwargs['attributes']['build_out_cost']['value']
        judged_values.append(value)
        score = 55 if value == 240_000 else 48
        return ({'jaspen_score': score, 'score_category': 'Mixed', 'dimensions': {
            'financial_value': {'score': score, 'confidence': 'medium'},
            'delivery_confidence': {'score': score, 'confidence': 'medium'},
        }, 'gates': []}, {'provider': 'test', 'input_tokens': 1, 'output_tokens': 1})

    monkeypatch.setattr(strategy, '_generate_jaspen_scorecard', scorer)
    first_fact = agent._execute_mutation_tool(
        'set_option_attributes',
        {'option': 'Boulder', 'fields': [
            {
                'key': 'build_out_cost', 'value': '$240,000', 'source': 'user',
                'evidence': 'Boulder build-out is $240,000 and the lease term is 5 years.',
            },
            {
                'key': 'lease_term_years', 'value': '5', 'source': 'user',
                'evidence': 'Boulder build-out is $240,000 and the lease term is 5 years.',
            },
        ]},
        user=test_user, user_id=test_user.id, thread_id=tid,
    )
    first = agent._execute_mutation_tool(
        'generate_scorecard', {'name': 'Boulder', 'idea_description': 'Evaluate Boulder.'},
        user=test_user, user_id=test_user.id, thread_id=tid,
    )
    assert first_fact['ok'] and first['ok']
    card_id = first['scorecard']['id']
    option_key = first['scorecard']['option_key']
    first_fingerprint = first['scorecard']['decision_fingerprint']
    update_message = "The contractor's final bid came in, and the build-out is now $320,000."
    sessions = load_user_sessions(test_user.id)
    sessions[tid]['chat_history'].append({'role': 'user', 'content': update_message})
    agent._apply_rfp_decision_context(sessions[tid], update_message)
    assert sessions[tid].get('decision_kit') is None
    assert sessions[tid].get('decision_kit_family') is None
    assert sessions[tid].get('decision_kit_change_pending') is None
    assert save_user_sessions(test_user.id, sessions)

    changed = agent._execute_mutation_tool(
        'set_option_attributes',
        {'option': 'Boulder', 'scorecard_id': card_id, 'fields': [{
            'key': 'build_out_cost', 'value': '$320,000', 'source': 'user',
            'evidence': 'the build-out is now $320,000',
        }]},
        user=test_user, user_id=test_user.id, thread_id=tid, user_message=update_message,
    )
    rescored = agent._execute_mutation_tool(
        'generate_scorecard', {
            'name': 'Boulder', 'idea_description': 'Re-evaluate Boulder holistically.',
            'rescore_scorecard_id': card_id,
        },
        user=test_user, user_id=test_user.id, thread_id=tid,
    )

    assert changed['ok'] and rescored['ok'] and rescored['rescored']
    assert rescored['scorecard_id'] == card_id
    assert rescored['updated_scorecard']['option_key'] == option_key
    assert rescored['updated_scorecard']['attributes']['build_out_cost']['value'] == 320_000
    assert rescored['updated_scorecard']['attributes']['lease_term_years']['value'] == '5'
    assert rescored['updated_scorecard']['decision_fingerprint'] != first_fingerprint
    assert rescored['updated_scorecard']['decision_state']['facts']['build_out_cost']['value'] == 320_000
    assert rescored['updated_scorecard']['decision_state']['facts']['lease_term_years']['value'] == '5'
    assert rescored['updated_scorecard']['decision_state_reusable'] is True
    persisted = Scorecard.query.filter_by(id=card_id, thread_id=tid).one()
    assert persisted.data['attributes']['lease_term_years']['value'] == '5'
    assert persisted.data['decision_state']['facts']['build_out_cost']['value'] == 320_000
    assert persisted.data['decision_state']['facts']['lease_term_years']['value'] == '5'
    assert persisted.data['decision_state_reusable'] is True
    repeated = agent._execute_mutation_tool(
        'generate_scorecard', {
            'name': 'Boulder', 'idea_description': 'Re-evaluate Boulder holistically.',
        },
        user=test_user, user_id=test_user.id, thread_id=tid,
    )
    assert repeated['ok']
    assert repeated['scorecard']['meta']['reused_source_scorecard_id'] == card_id
    assert repeated['scorecard']['decision_fingerprint'] == rescored['updated_scorecard']['decision_fingerprint']
    assert repeated['scorecard']['decision_state_reusable'] is True
    assert judged_values == [240_000, 320_000]
    session = load_user_sessions(test_user.id)[tid]
    history = session['option_attribute_history_by_key'][option_key]
    assert history[-1]['previous']['value'] == 240_000
    assert history[-1]['previous']['evidence'] == 'Boulder build-out is $240,000 and the lease term is 5 years.'


@pytest.mark.parametrize('message', [
    "The contractor's final bid came in at $320,000.",
    'The vendor sent a revised proposal for the build-out.',
    'We need to compare the supplier proposal with the original estimate.',
])
def test_incidental_rfp_language_cannot_switch_an_established_general_decision(app, message):
    _, agent = modules()
    facts = {
        'build_out_cost': {'value': 240000, 'source': 'user'},
        'lease_term_years': {'value': '5', 'source': 'user'},
    }
    session = {
        'active_evaluation_scorecard_id': 'card-1',
        'decision_kit': None,
        'decision_kit_version': None,
        'option_attributes_by_key': {'boulder': facts.copy()},
    }

    agent._apply_rfp_decision_context(session, message)

    assert session.get('decision_kit') is None
    assert session.get('decision_kit_version') is None
    assert session.get('decision_kit_family') is None
    assert session.get('decision_kit_source') is None
    assert session.get('decision_kit_change_pending') is None
    assert session['option_attributes_by_key']['boulder'] == facts


def test_explicit_kit_change_on_established_decision_requires_confirmation_and_preserves_facts(app):
    _, agent = modules()
    facts = {
        'build_out_cost': {'value': 320000, 'source': 'user'},
        'lease_term_years': {'value': '5', 'source': 'user'},
    }
    session = {
        'active_evaluation_scorecard_id': 'card-1',
        'decision_kit': None,
        'decision_kit_version': None,
        'option_attributes_by_key': {'boulder': facts.copy()},
    }

    agent._apply_rfp_decision_context(
        session, 'Change this decision to the RFP vendor selection Decision Kit.',
        judgment={
            'kit': 'rfp_vendor_selection', 'confidence': 'high',
            'evidence_quote': 'vendor selection',
        },
    )

    assert session.get('decision_kit') is None
    assert session['decision_kit_change_pending']['target'] == 'rfp_vendor_selection'
    assert agent._decision_kit_change_question_needed(session) is True
    assert session['option_attributes_by_key']['boulder'] == facts

    agent._apply_rfp_decision_context(session, 'Confirm the Decision Kit change.')

    assert session['decision_kit'] == 'rfp_vendor_selection'
    assert session['decision_kit_source'] == 'user_confirmed'
    assert session['decision_kit_rescore_required'] is True
    assert session['decision_kit_preserve_existing_facts'] is True
    assert session.get('decision_kit_change_pending') is None
    assert session['option_attributes_by_key']['boulder'] == facts


def test_proposed_rubric_is_visible_with_weights_before_approval(app, db, test_user):
    _, agent = modules()
    tid = 'visible-proposed-rubric'
    seed_thread(test_user, tid)
    session = agent.load_user_sessions(test_user.id)[tid]
    result, _ = agent._execute_local_tool(
        'set_scoring_rubric', {'criteria': [
            {'label': 'Financial Value', 'weight': 60},
            {'label': 'Delivery Confidence', 'weight': 40},
        ], 'criteria_source': 'jaspen'},
        readiness={}, user=test_user, user_id=test_user.id, thread_id=tid,
        user_turn_count=1, mutations_this_turn=0,
        user_message='Help me evaluate this option.', session=session,
    )
    action = {'tool': 'set_scoring_rubric', 'result': result}
    reply = agent._finalize_agent_reply(
        'Please review the proposed rubric.', '', [],
        user_id=test_user.id, thread_id=tid, executed_actions=[action],
    )
    reply = agent._sanitize_assistant_numeric_claims(
        reply + '\n' + result['confirmation'], user_message='Help me evaluate this option.',
        session=session, user_id=test_user.id, thread_id=tid, actions=[action],
    )
    agent._apply_rubric_action_to_session(session, [action])

    assert result['rubric']['approval_status'] == 'proposed'
    assert 'Financial Value weight 60%' in reply
    assert 'Delivery Confidence weight 40%' in reply
    assert session['scoring_rubric']['presented_at']


def test_decision_kit_starter_rubric_is_persisted_and_rendered_before_provider_runs(app, db, test_user, monkeypatch):
    _, agent = modules()
    from app.routes.sessions import load_user_sessions, save_user_sessions
    tid = 'kit-rubric-before-provider'
    seed_thread(test_user, tid)
    sessions = load_user_sessions(test_user.id)
    sessions[tid].update({
        'decision_kit': 'rfp_bid', 'decision_kit_version': 1,
        'decision_kit_family': 'rfp',
    })
    assert save_user_sessions(test_user.id, sessions)
    session = load_user_sessions(test_user.id)[tid]
    monkeypatch.setattr(
        agent, '_resolve_governed_routes',
        lambda *a, **k: pytest.fail('provider routing must not run before the rubric is shown'),
    )

    reply, usage, actions, _, _ = agent._generate_assistant_reply(
        'Show me the rubric for this RFP.', [], {}, {'llm_model': 'test'},
        session=session, user=test_user, user_id=test_user.id, thread_id=tid,
    )

    assert usage['provider'] == 'deterministic' and actions == []
    assert 'Win probability & competitive position: weight 20%' in reply
    assert 'Contract & commercial risk: weight 10%' in reply
    durable = load_user_sessions(test_user.id)[tid]['scoring_rubric']
    assert durable['approval_status'] == 'proposed'
    assert durable['presented_at']
    assert len(durable['criteria']) == 9
    assert {item['key'] for item in durable['criteria'] if item.get('gate')} == {
        'submission_deadline', 'capacity_available', 'surety_confirmation',
    }
    assert 'Surety / bond confirmation: required gate' in reply


def test_suggested_rfp_kit_requires_selection_then_first_approval_allows_scoring(app, db, test_user, monkeypatch):
    _, agent = modules()
    from app.routes.sessions import load_user_sessions, save_user_sessions

    tid = 'inferred-rfp-one-approval'
    seed_thread(test_user, tid)
    sessions = load_user_sessions(test_user.id)
    session = sessions[tid]
    first_message = (
        'We need to decide whether to bid on three public contracts. '
        'Propose a scoring rubric for me to approve.'
    )
    agent._apply_rfp_decision_context(session, first_message, judgment={
        'kit': 'rfp_bid',
        'confidence': 'high',
        'evidence_quote': 'decide whether to bid',
    })

    assert session.get('decision_kit') is None
    assert session['decision_kit_suggestion']['kit'] == 'rfp_bid'
    assert agent._ensure_decision_kit_starter_rubric(
        session, user_message=first_message,
    ) is False

    # The user accepts the one-click suggestion in the composer. Only that
    # explicit action activates the kit and makes its starter rubric eligible.
    session.update({
        'decision_kit': 'rfp_bid',
        'decision_kit_version': 1,
        'decision_kit_family': 'rfp',
        'decision_kit_source': 'user',
        'decision_kit_family_locked': True,
    })
    session.pop('decision_kit_suggestion', None)
    assert agent._ensure_decision_kit_starter_rubric(
        session, user_message=first_message,
    ) is True
    assert session['decision_kit'] == 'rfp_bid'
    proposed = session['scoring_rubric']
    assert proposed['approval_status'] == 'proposed'
    assert 'presented_at' not in proposed
    assert len(proposed['criteria']) == 9
    assert {item['key'] for item in proposed['criteria'] if item.get('gate')} == {
        'submission_deadline', 'capacity_available', 'surety_confirmation',
    }
    sessions[tid] = session
    assert save_user_sessions(test_user.id, sessions)
    monkeypatch.setattr(
        agent, '_resolve_governed_routes',
        lambda *a, **k: pytest.fail('provider must not author or present the kit rubric'),
    )

    reply, usage, actions, _, _ = agent._generate_assistant_reply(
        first_message, [], {}, {'llm_model': 'test'},
        session=session, user=test_user, user_id=test_user.id, thread_id=tid,
    )

    assert usage['provider'] == 'deterministic' and actions == []
    assert 'Win probability & competitive position: weight 20%' in reply
    assert 'Surety / bond confirmation: required gate' in reply
    displayed = load_user_sessions(test_user.id)[tid]['scoring_rubric']
    assert displayed['presented_at']
    assert displayed['created_at'] == proposed['created_at']

    approval = 'Approved. Score all three bids with it now.'
    result = agent._execute_mutation_tool(
        'approve_presented_rubric',
        {'user_request_quote': 'Approved'},
        user=test_user, user_id=test_user.id, thread_id=tid,
        user_message=approval,
    )
    assert result['ok'] is True
    session['scoring_rubric'] = result['rubric']
    approved = load_user_sessions(test_user.id)[tid]['scoring_rubric']
    assert approved['approval_status'] == 'approved'
    assert approved['criteria'] == displayed['criteria']
    assert agent._guard_mutation_tool(
        'queue_scorecards', user_turn_count=2, mutations_this_turn=0,
        user_message=approval, user_request_quote='Score all three bids with it now',
        session=session,
    ) is None
    assert session['scoring_intent'] == {'status': 'requested', 'source': 'user'}


def test_rfp_proposal_acknowledges_supplied_facts_without_calling_them_weights(app, db, test_user, monkeypatch):
    _, agent = modules()
    from app.routes.sessions import load_user_sessions, save_user_sessions

    tid = 'rfp-rubric-context'
    seed_thread(test_user, tid)
    sessions = load_user_sessions(test_user.id)
    sessions[tid].update({
        'decision_kit': 'rfp_bid', 'decision_kit_version': 1,
        'decision_kit_family': 'rfp',
    })
    message = (
        'Denver Water: contract value $2,400,000, win probability 35%, expected margin 18%, '
        'pursuit cost $45,000, submission due November 20, 2026, and surety confirmed. '
        'Propose a scoring rubric for me to approve before you score.'
    )
    assert agent._ensure_decision_kit_starter_rubric(
        sessions[tid], user_message=message,
    ) is True
    assert save_user_sessions(test_user.id, sessions)
    session = load_user_sessions(test_user.id)[tid]
    monkeypatch.setattr(
        agent, '_resolve_governed_routes',
        lambda *a, **k: pytest.fail('provider must not replace the saved proposal'),
    )

    reply, usage, actions, _, _ = agent._generate_assistant_reply(
        message, [], {}, {'llm_model': 'test'},
        session=session, user=test_user, user_id=test_user.id, thread_id=tid,
    )

    assert usage['provider'] == 'deterministic' and actions == []
    assert 'You already supplied decision inputs for' in reply
    assert 'Contract value' in reply and 'Win probability' in reply
    assert 'Expected margin' in reply and 'Pursuit cost' in reply
    assert 'Those are evidence values, not criterion weights.' in reply
    assert 'Win probability & competitive position: weight 20%' in reply
    assert 'Win probability & competitive position: 20%' not in reply


def test_kit_session_always_gets_proposed_starter_rubric():
    _, agent = modules()
    session = {'decision_kit': 'rfp_bid', 'decision_kit_version': 1}
    message = (
        'Use our criteria: customer relationship, team capacity, and expected margin. '
        'Suggest weights for those criteria.'
    )

    assert agent._ensure_decision_kit_starter_rubric(session, user_message=message) is True
    assert session['scoring_rubric']['approval_status'] == 'proposed'
    assert session['scoring_rubric']['source'] == 'jaspen_proposed'


def test_score_now_uses_proposed_kit_rubric_without_approval_stop(app, db, test_user, monkeypatch):
    _, agent = modules()
    from app.routes.sessions import load_user_sessions, save_user_sessions

    tid = 'score-now-standard-kit-rubric'
    seed_thread(test_user, tid)
    sessions = load_user_sessions(test_user.id)
    session = sessions[tid]
    session.update({
        'decision_kit': 'rfp_bid', 'decision_kit_version': 1,
        'decision_kit_family': 'rfp',
    })
    message = 'Score all three bids now.'
    assert agent._ensure_decision_kit_starter_rubric(session, user_message=message) is True
    sessions[tid] = session
    assert save_user_sessions(test_user.id, sessions)

    assert agent._present_decision_kit_rubric(
        session, user_id=test_user.id, thread_id=tid, user_message=message,
    ) is None
    assert agent._guard_mutation_tool(
        'queue_scorecards', user_turn_count=1, mutations_this_turn=0,
        user_message=message, user_request_quote='Score all three bids now',
        session=session,
    ) is None
    assert session['scoring_rubric']['approval_status'] == 'proposed'
    assert session['scoring_rubric']['scoring_authorized_by'] == 'explicit_score_request'

    monkeypatch.setattr(agent, '_execute_mutation_tool', lambda *a, **k: {
        'ok': True,
        'confirmation': 'Queued all three bids for scoring.',
    })
    result, _ = agent._execute_local_tool(
        'queue_scorecards', {
            'ideas': [{'name': 'A'}, {'name': 'B'}, {'name': 'C'}],
            'user_request_quote': 'Score all three bids now',
        },
        readiness={}, user=test_user, user_id=test_user.id, thread_id=tid,
        user_turn_count=1, mutations_this_turn=0, user_message=message, session=session,
    )
    assert result['ok'] is True
    durable = load_user_sessions(test_user.id)[tid]
    assert durable['scoring_rubric']['approval_status'] == 'proposed'
    assert durable['scoring_rubric']['scoring_authorized_by'] == 'explicit_score_request'

    reply = agent._finalize_agent_reply(
        '', '', [], user_id=test_user.id, thread_id=tid,
        executed_actions=[{'tool': 'queue_scorecards', 'result': result}],
    )
    assert 'Queued all three bids for scoring.' in reply
    assert 'I’m weighing these on' in reply
    assert 'If something matters more to you, tell me and I’ll re-score.' in reply
    assert 'approve' not in reply.lower()
    durable = load_user_sessions(test_user.id)[tid]
    assert durable['scoring_rubric']['criteria_summary_presented_at']

    detail = agent._present_decision_kit_rubric(
        durable, user_id=test_user.id, thread_id=tid,
        user_message='Show me the rubric and weights.',
    )
    assert 'Here are the standard RFP response rubric criteria I used:' in detail
    assert 'Win probability & competitive position: weight 20%' in detail
    assert 'approve' not in detail.lower()


@pytest.mark.parametrize('score_request', [
    'Correction: delivery is June 1. Re-score with that.',
    'Rescore with that.',
    'Update the score.',
    'Score again.',
])
def test_authorized_proposed_rubric_allows_natural_rescore_requests(app, score_request):
    _, agent = modules()
    session = {
        'scoring_rubric': {
            'approval_status': 'proposed',
            'source': 'jaspen_proposed',
            'criteria': [
                {'key': 'value', 'label': 'Value', 'weight': 0.6},
                {'key': 'risk', 'label': 'Risk', 'weight': 0.4},
            ],
        },
    }

    assert agent._guard_mutation_tool(
        'generate_scorecard', user_turn_count=1, mutations_this_turn=0,
        user_message='Score it now.', user_request_quote='Score it now', session=session,
    ) is None
    assert session['scoring_rubric']['approval_status'] == 'proposed'
    assert session['scoring_rubric']['scoring_authorized_by'] == 'explicit_score_request'

    assert agent._guard_mutation_tool(
        'generate_scorecard', user_turn_count=2, mutations_this_turn=0,
        user_message=score_request, user_request_quote=score_request, session=session,
    ) is None
    assert session['scoring_rubric']['approval_status'] == 'proposed'
    assert 'approved_by_user_at' not in session['scoring_rubric']


def test_changed_rubric_after_authorized_score_shows_criteria_and_approve_action(app):
    _, agent = modules()
    session = {
        'scoring_rubric': {
            'approval_status': 'proposed',
            'source': 'jaspen_proposed',
            'criteria': [{'key': 'value', 'label': 'Value', 'weight': 1.0}],
        },
    }
    assert agent._guard_mutation_tool(
        'generate_scorecard', user_turn_count=1, mutations_this_turn=0,
        user_message='Score it now.', user_request_quote='Score it now', session=session,
    ) is None

    session['scoring_rubric'] = {
        'approval_status': 'proposed',
        'source': 'jaspen_proposed',
        'criteria': [
            {'key': 'value', 'label': 'Value', 'weight': 0.7},
            {'key': 'risk', 'label': 'Risk', 'weight': 0.3},
        ],
    }
    result = agent._guard_mutation_tool(
        'generate_scorecard', user_turn_count=2, mutations_this_turn=0,
        user_message='Re-score with that.', user_request_quote='Re-score with that',
        session=session,
    )

    assert result['code'] == 'rubric_approval_required'
    assert result['confirmation_required'] is True
    assert '- Value: weight 70%' in result['confirmation']
    assert '- Risk: weight 30%' in result['confirmation']
    assert result['actions'][0] == {
        'label': 'Approve rubric', 'value': 'Approve this rubric',
    }
    reply = agent._finalize_agent_reply(
        'Re-scoring now.', '', [], user_id='u', thread_id='t',
        executed_actions=[{'tool': 'generate_scorecard', 'result': result}],
    )
    assert reply == result['confirmation']


def test_plain_looks_good_approves_conversational_criteria_summary(app, db, test_user):
    _, agent = modules()
    from app.routes.sessions import load_user_sessions, save_user_sessions

    tid = 'approve-criteria-summary'
    seed_thread(test_user, tid)
    sessions = load_user_sessions(test_user.id)
    sessions[tid]['scoring_rubric'] = {
        'criteria': [
            {'key': 'price', 'label': 'Price', 'weight': 0.6},
            {'key': 'delivery', 'label': 'Delivery', 'weight': 0.4},
        ],
        'source': 'jaspen_proposed',
        'approval_status': 'proposed',
        'criteria_summary_presented_at': '2026-10-10T21:00:00Z',
    }
    assert save_user_sessions(test_user.id, sessions)
    session = load_user_sessions(test_user.id)[tid]

    result = agent._execute_mutation_tool(
        'approve_presented_rubric', {'user_request_quote': 'Looks good'},
        user=test_user, user_id=test_user.id, thread_id=tid,
        user_message='Looks good.',
    )
    assert result['ok'] is True
    assert load_user_sessions(test_user.id)[tid]['scoring_rubric']['approval_status'] == 'approved'


def test_plain_language_criteria_change_becomes_user_owned(app, db, test_user):
    _, agent = modules()
    from app.routes.sessions import load_user_sessions, save_user_sessions

    tid = 'plain-language-rubric-change'
    seed_thread(test_user, tid)
    sessions = load_user_sessions(test_user.id)
    sessions[tid]['scoring_rubric'] = {
        'criteria': [
            {'key': 'price', 'label': 'Price', 'weight': 0.5},
            {'key': 'delivery', 'label': 'Delivery', 'weight': 0.5},
        ],
        'source': 'jaspen_proposed',
        'approval_status': 'proposed',
        'criteria_summary_presented_at': '2026-10-10T21:00:00Z',
    }
    assert save_user_sessions(test_user.id, sessions)

    result = agent._execute_mutation_tool(
        'set_scoring_rubric', {'criteria': [
            {'label': 'Price', 'weight': 70},
            {'label': 'Delivery', 'weight': 30},
        ], 'criteria_source': 'user', 'user_request_quote': 'Price matters most'},
        user=test_user, user_id=test_user.id, thread_id=tid,
        user_message='Price matters most. Make it 70% and delivery 30%, then re-score.',
    )

    assert result['ok'] is True
    assert result['rubric']['approval_status'] == 'approved'
    assert result['rubric']['source'] == 'user'
    assert [item['weight'] for item in result['rubric']['criteria']] == [0.7, 0.3]
    durable = load_user_sessions(test_user.id)[tid]['scoring_rubric']
    assert durable['approval_status'] == 'approved'


def test_general_objective_rubric_is_persisted_and_rendered_in_full(app, db, test_user, monkeypatch):
    _, agent = modules()
    from app.routes.sessions import load_user_sessions
    tid = 'general-rubric-before-provider'
    seed_thread(test_user, tid)
    session = load_user_sessions(test_user.id)[tid]
    monkeypatch.setattr(
        agent, '_resolve_governed_routes',
        lambda *a, **k: pytest.fail('provider must not author the application rubric'),
    )

    reply, usage, actions, _, _ = agent._generate_assistant_reply(
        'Show me the scoring rubric and weights.', [], {}, {'llm_model': 'test'},
        session=session, user=test_user, user_id=test_user.id, thread_id=tid,
    )

    assert usage['provider'] == 'deterministic' and actions == []
    expected = [
        'Market opportunity: weight 18%', 'Financial viability: weight 20%',
        'Execution readiness: weight 18%', 'Strategic alignment: weight 16%',
        'Risk profile: weight 16%', 'Evidence quality: weight 12%',
    ]
    assert all(line in reply for line in expected)
    durable = load_user_sessions(test_user.id)[tid]['scoring_rubric']
    assert durable['approval_status'] == 'proposed'
    assert durable['presented_at']
    assert len(durable['criteria']) == 6
    assert not [item for item in durable['criteria'] if item.get('gate')]


def test_streaming_inferred_rfp_renders_all_starter_criteria_without_provider(app, db, test_user, monkeypatch):
    _, agent = modules()
    from app.routes.sessions import load_user_sessions, save_user_sessions
    tid = 'streaming-inferred-rfp-rubric'
    seed_thread(test_user, tid)
    sessions = load_user_sessions(test_user.id)
    sessions[tid].update({
        'decision_kit': 'rfp_vendor_selection', 'decision_kit_version': 1,
        'decision_kit_family': 'rfp', 'decision_kit_source': 'discovery_inference',
    })
    assert save_user_sessions(test_user.id, sessions)
    session = load_user_sessions(test_user.id)[tid]
    monkeypatch.setattr(
        agent, '_resolve_governed_routes',
        lambda *a, **k: pytest.fail('provider must not render the starter rubric'),
    )
    state = {}

    events = list(agent._stream_assistant_reply_events(
        'We received vendor proposals and need to select one. Show me the rubric.', [], {},
        {'llm_model': 'test'}, session=session, state=state,
        user=test_user, user_id=test_user.id, thread_id=tid,
    ))

    reply = state['reply']
    assert events == [{'type': 'delta', 'text': reply}]
    expected = [
        'Functional / technical fit: weight 25%', 'Total cost of ownership: weight 20%',
        'Implementation risk & timeline: weight 20%', 'Vendor viability & references: weight 15%',
        'Integration & compliance: weight 10%', 'Commercial terms: weight 10%',
    ]
    assert all(line in reply for line in expected)
    durable = load_user_sessions(test_user.id)[tid]['scoring_rubric']
    assert durable['approval_status'] == 'proposed'
    assert len(durable['criteria']) == 7
    assert [item['key'] for item in durable['criteria'] if item.get('gate')] == ['proposal_complete']


def test_provider_cannot_add_unspoken_rubric_meaning(app, db, test_user):
    _, agent = modules()
    tid = 'rubric-description-grounding'
    seed_thread(test_user, tid)
    result = agent._execute_mutation_tool(
        'set_scoring_rubric', {'criteria': [
            {'label': 'Financial Value', 'weight': 60, 'description': 'Use a secret model rule.'},
            {'label': 'Delivery Confidence', 'weight': 40, 'description': 'Another secret rule.'},
        ], 'criteria_source': 'user', 'user_request_quote': 'Use Financial Value 60% and Delivery Confidence 40%'},
        user=test_user, user_id=test_user.id, thread_id=tid,
        user_message='Use Financial Value 60% and Delivery Confidence 40%. Score it now.',
    )
    assert result['ok'] and result['rubric']['approval_status'] == 'approved'
    assert all(item['description'] is None for item in result['rubric']['criteria'])


def test_plain_approval_is_not_phrase_matched_before_provider(app, db, test_user, monkeypatch):
    _, agent = modules()
    from app.routes.sessions import load_user_sessions, save_user_sessions

    tid = 'plain-rubric-approval-live-turn'
    seed_thread(test_user, tid)
    sessions = load_user_sessions(test_user.id)
    criteria = [
        {'key': 'fit', 'label': 'Strategic fit', 'weight': 0.6},
        {'key': 'risk', 'label': 'Delivery risk', 'weight': 0.4, 'is_risk': True},
    ]
    sessions[tid]['scoring_rubric'] = {
        'criteria': criteria,
        'source': 'jaspen_proposed',
        'created_at': '2026-10-09T10:00:00Z',
        'presented_at': '2026-10-09T10:00:00Z',
        'approval_status': 'proposed',
    }
    assert save_user_sessions(test_user.id, sessions)
    session = load_user_sessions(test_user.id)[tid]

    monkeypatch.setattr(agent, '_resolve_governed_routes', lambda *a, **k: ([{
        'provider': 'anthropic', 'model': 'test-model', 'model_key': 'test',
    }], {}))

    def provider(*args, **kwargs):
        active = kwargs['session']['scoring_rubric']
        durable = load_user_sessions(test_user.id)[tid]['scoring_rubric']
        assert active['approval_status'] == 'proposed'
        assert durable['approval_status'] == 'proposed'
        assert active['criteria'] == criteria == durable['criteria']
        return 'I will apply your approval.', {'provider': 'anthropic', 'model': 'test-model'}, [], [], None

    monkeypatch.setattr(agent, '_generate_assistant_reply_anthropic', provider)
    reply, _, _, _, _ = agent._generate_assistant_reply(
        'I approve this rubric as shown. Score it now.', [], {},
        {'llm_model': 'test-model'}, session=session, user=test_user,
        user_id=test_user.id, thread_id=tid,
    )

    unchanged = load_user_sessions(test_user.id)[tid]['scoring_rubric']
    assert reply == 'I will apply your approval.'
    assert unchanged['criteria'] == criteria
    assert unchanged['source'] == 'jaspen_proposed'
    assert unchanged['approval_status'] == 'proposed'
    assert 'approved_by_user_at' not in unchanged


def test_common_canonical_fact_update_survives_active_decision_kit(app, db, test_user):
    _, agent = modules()
    from app.routes.sessions import load_user_sessions, save_user_sessions

    tid = 'common-fact-update-with-kit'
    seed_rfp_thread(test_user, tid, decision_kit='rfp_vendor_selection')
    sessions = load_user_sessions(test_user.id)
    sessions[tid]['chat_history'] = [{
        'role': 'user', 'content': 'Build-out is now $320,000.',
    }]
    assert save_user_sessions(test_user.id, sessions)

    result = agent._execute_mutation_tool(
        'set_option_attributes', {'option': 'RegionalERP', 'fields': [{
            'key': 'build_out_cost', 'value': '$320,000', 'source': 'user',
            'evidence': 'Build-out is now $320,000.',
        }]},
        user=test_user, user_id=test_user.id, thread_id=tid,
        user_message='Build-out is now $320,000.',
    )

    assert result['ok'], result
    assert result['rejected_fields'] == []
    assert result['option_attributes']['build_out_cost']['value'] == 320000
    stored = load_user_sessions(test_user.id)[tid]
    values = list(stored['option_attributes_by_key'].values())
    assert values[0]['build_out_cost']['value'] == 320000


def test_foreign_view_scorecard_id_saves_facts_and_allows_first_score(
    app, db, test_user, monkeypatch,
):
    strategy, agent = modules()
    from app.routes.sessions import load_user_sessions, save_user_sessions

    tid = 'foreign-view-scorecard-first-score'
    seed_thread(test_user, tid)
    sessions = load_user_sessions(test_user.id)
    sessions[tid]['active_evaluation_scorecard_id'] = 'scorecard-from-another-session'
    sessions[tid]['chat_history'] = [{
        'role': 'user', 'content': 'Option B costs $320,000.',
    }]
    assert save_user_sessions(test_user.id, sessions)

    facts = agent._execute_mutation_tool(
        'set_option_attributes', {'option': 'Option B', 'fields': [{
            'key': 'build_out_cost', 'value': '$320,000', 'source': 'user',
            'evidence': 'Option B costs $320,000.',
        }]},
        user=test_user, user_id=test_user.id, thread_id=tid,
        user_message='Option B costs $320,000.',
        view_context={'active_scorecard_id': 'scorecard-from-another-session'},
    )

    assert facts['ok'], facts
    stored = load_user_sessions(test_user.id)[tid]
    assert stored.get('active_evaluation_scorecard_id') is None
    assert list(stored['option_attributes_by_key'].values())[0]['build_out_cost']['value'] == 320000

    stale_explicit_target = agent._execute_mutation_tool(
        'set_option_attributes', {
            'option': 'Option B',
            'scorecard_id': 'scorecard-from-another-session',
            'fields': [{
                'key': 'build_out_cost', 'value': '$320,000', 'source': 'user',
                'evidence': 'Option B costs $320,000.',
            }],
        },
        user=test_user, user_id=test_user.id, thread_id=tid,
        user_message='Option B costs $320,000.',
    )
    assert stale_explicit_target['ok'], stale_explicit_target

    mock_accounting(monkeypatch)
    monkeypatch.setattr(strategy, '_generate_jaspen_scorecard', lambda *a, **k: ({
        'jaspen_score': 61,
        'score_category': 'Good',
        'dimensions': {'financial_viability': {'score': 61, 'confidence': 'medium'}},
        'gates': [],
    }, {'provider': 'test', 'input_tokens': 1, 'output_tokens': 1}))
    scored = agent._execute_mutation_tool(
        'generate_scorecard', {'name': 'Option B', 'idea_description': 'Score Option B.'},
        user=test_user, user_id=test_user.id, thread_id=tid,
    )

    assert scored['ok'], scored
    missing_explicit_target = agent._execute_mutation_tool(
        'set_option_attributes', {
            'option': 'Option B',
            'scorecard_id': 'missing-from-this-session',
            'fields': [],
        },
        user=test_user, user_id=test_user.id, thread_id=tid,
    )
    assert missing_explicit_target['ok'] is False
    assert missing_explicit_target['code'] == 'scorecard_not_found'


def test_material_update_binds_provider_paraphrase_to_exact_user_evidence(app, db, test_user):
    _, agent = modules()
    from app.routes.sessions import load_user_sessions, save_user_sessions

    tid = 'paraphrased-material-update-evidence'
    seed_thread(test_user, tid)
    sessions = load_user_sessions(test_user.id)
    sessions[tid]['chat_history'] = [{
        'role': 'user', 'content': 'Build-out is now $320,000.',
    }]
    assert save_user_sessions(test_user.id, sessions)

    result = agent._execute_mutation_tool(
        'set_option_attributes', {'option': 'Boulder', 'fields': [{
            'key': 'build_out_cost', 'value': '$320,000', 'source': 'user',
            'evidence': 'Build-out cost: $320,000',
        }]},
        user=test_user, user_id=test_user.id, thread_id=tid,
        user_message='Build-out is now $320,000.',
    )

    assert result['ok'], result
    fact = result['option_attributes']['build_out_cost']
    assert fact['value'] == 320000
    assert fact['evidence'] == 'Build-out is now $320,000.'


def test_material_update_can_bind_user_evidence_when_provider_omits_quote(app, db, test_user):
    _, agent = modules()
    from app.routes.sessions import load_user_sessions, save_user_sessions

    tid = 'omitted-material-update-evidence'
    seed_thread(test_user, tid)
    sessions = load_user_sessions(test_user.id)
    sessions[tid]['chat_history'] = [{
        'role': 'user', 'content': 'Build-out is now $320,000.',
    }]
    assert save_user_sessions(test_user.id, sessions)

    result = agent._execute_mutation_tool(
        'set_option_attributes', {'option': 'Boulder', 'fields': [{
            'key': 'build_out_cost', 'value': '$320,000', 'source': 'user',
            'evidence': '',
        }]},
        user=test_user, user_id=test_user.id, thread_id=tid,
        user_message='Build-out is now $320,000.',
    )

    assert result['ok'], result
    assert result['option_attributes']['build_out_cost']['evidence'] == 'Build-out is now $320,000.'


def test_failed_fact_grounding_blocks_same_turn_rescore(app, db, test_user, monkeypatch, caplog):
    _, agent = modules()
    from app.routes.sessions import load_user_sessions, save_user_sessions

    tid = 'failed-fact-update-blocks-rescore'
    seed_thread(test_user, tid)
    sessions = load_user_sessions(test_user.id)
    sessions[tid]['chat_history'] = [{
        'role': 'user', 'content': 'Monthly lease is now $320,000.',
    }]
    assert save_user_sessions(test_user.id, sessions)
    session = load_user_sessions(test_user.id)[tid]

    with caplog.at_level('WARNING'):
        failed, count = agent._execute_local_tool(
            'set_option_attributes', {'option': 'Boulder', 'fields': [{
                'key': 'build_out_cost', 'value': '$320,000', 'source': 'user',
                'evidence': 'Build-out cost: $320,000',
            }]},
            readiness={}, user=test_user, user_id=test_user.id, thread_id=tid,
            user_turn_count=2, mutations_this_turn=0,
            user_message='Monthly lease is now $320,000.', session=session,
        )
    assert failed['ok'] is False
    assert count == 0
    assert failed['rejected_fields'][0]['reason'] == "Evidence could not be grounded in the user's words"
    assert any('Rejected 1 ungrounded fact(s)' in message for message in caplog.messages)

    monkeypatch.setattr(
        agent, '_execute_mutation_tool',
        lambda *a, **k: pytest.fail('scoring must not run after a failed fact update'),
    )
    blocked, _ = agent._execute_local_tool(
        'generate_scorecard', {'name': 'Boulder', 'idea_description': 'Re-score Boulder.'},
        readiness={}, user=test_user, user_id=test_user.id, thread_id=tid,
        user_turn_count=2, mutations_this_turn=count,
        user_message='Monthly lease is now $320,000.', session=session,
    )
    assert blocked['ok'] is False
    assert blocked['failure_state'] is True
    assert blocked['code'] == 'fact_update_required'
    assert blocked['action'] == {'type': 'retry', 'label': 'Retry'}
    assert 'did not re-score' in blocked['error']


def test_numeric_guard_allows_persisted_rubric_weights_but_rejects_model_math(app):
    _, agent = modules()
    session = {'scoring_rubric': {'approval_status': 'proposed', 'criteria': [
        {'key': 'value', 'label': 'Financial Value', 'weight': 0.6},
        {'key': 'delivery', 'label': 'Delivery Confidence', 'weight': 0.4},
    ]}}
    reply = agent._sanitize_assistant_numeric_claims(
        'Financial Value 60%. Delivery Confidence 40%. $42M leaves $48M of your $90M headroom.',
        user_message='', session=session, actions=[],
    )
    assert 'Financial Value 60%' in reply and 'Delivery Confidence 40%' in reply
    assert '$42M' not in reply and '$48M' not in reply and '$90M' not in reply


def test_first_turn_score_now_with_user_owned_rubric_scores_immediately(app, db, test_user, monkeypatch):
    strategy, agent = modules()
    tid = 'first-turn-score-now'
    seed_thread(test_user, tid)
    session = agent.load_user_sessions(test_user.id)[tid]
    message = 'Use Financial Value 60% and Delivery Confidence 40%. Score it now.'
    rubric_result, count = agent._execute_local_tool(
        'set_scoring_rubric', {'criteria': [
            {'label': 'Financial Value', 'weight': 60},
            {'label': 'Delivery Confidence', 'weight': 40},
        ], 'criteria_source': 'user', 'user_request_quote': 'Use Financial Value 60% and Delivery Confidence 40%'},
        readiness={}, user=test_user, user_id=test_user.id, thread_id=tid,
        user_turn_count=1, mutations_this_turn=0, user_message=message, session=session,
    )
    assert rubric_result['ok'] and rubric_result['rubric']['approval_status'] == 'approved'
    mock_accounting(monkeypatch)
    monkeypatch.setattr(strategy, '_generate_jaspen_scorecard', lambda *a, **k: ({
        'jaspen_score': 62, 'score_category': 'Good',
        'dimensions': {'financial_value': {'score': 62, 'confidence': 'assumed'}},
        'gates': [],
        'neutral_criteria': [{'key': 'delivery_confidence', 'label': 'Delivery Confidence', 'score': 45}],
    }, {'provider': 'test', 'input_tokens': 1, 'output_tokens': 1}))
    scored, _ = agent._execute_local_tool(
        'generate_scorecard', {
            'name': 'Boulder',
            'idea_description': 'Evaluate Boulder.',
            'user_request_quote': 'Score it now',
        },
        readiness={}, user=test_user, user_id=test_user.id, thread_id=tid,
        user_turn_count=1, mutations_this_turn=count, user_message=message, session=session,
    )
    assert scored['ok'], scored
    assert scored['scorecard']['jaspen_score'] == 62
    assert scored['neutral_criteria'] == scored['scorecard']['neutral_criteria']


def test_blocked_score_cannot_keep_success_narration(app):
    _, agent = modules()
    action = {'tool': 'generate_scorecard', 'result': {
        'ok': False, 'code': 'rubric_approval_required',
        'error': 'The proposed scoring rubric needs human approval before scoring.',
    }}
    reply = agent._finalize_agent_reply(
        'Now scoring your option.', '', [],
        user_id='u', thread_id='t', executed_actions=[action],
    )
    assert reply == 'Approve the proposed rubric to continue scoring, then try again.'
    assert 'needs human approval' not in reply.lower()
    assert 'now scoring' not in reply.lower()


def test_real_batch_rfp_scoring_keeps_valid_fields_when_one_is_invalid(client, db, test_user, auth_headers, monkeypatch):
    strategy, agent = modules()
    from app.decision_kits import get_decision_kit
    tid = 'live-batch-rfp-alias'
    queue = [
        {
            'name': 'Vendor A',
            'description': 'Vendor A proposal',
            'option_key': 'vendor-a',
            'attributes': {
                '5yr_tco': {'value': '$12.5M', 'source': 'document', 'evidence': '5yr TCO $12.5M'},
                'unknown_magic': {'value': 7, 'source': 'document', 'evidence': 'unknown magic 7'},
            },
        },
        {
            'name': 'Vendor B',
            'description': 'Vendor B proposal',
            'option_key': 'vendor-b',
            'attributes': {'proposal_price': {'value': '$10M', 'source': 'document', 'evidence': 'proposal price $10M'}},
        },
    ]
    seed_rfp_thread(test_user, tid, decision_kit='rfp_vendor_selection', queue=queue)
    mock_accounting(monkeypatch)
    criterion_keys = [item['key'] for item in get_decision_kit('rfp_vendor_selection')['starter_rubric']]
    def grounded_reply(messages, **_kwargs):
        prompt = messages[0]['content']
        quote = '5yr TCO $12.5M' if '5yr TCO $12.5M' in prompt else 'proposal price $10M'
        return json.dumps({
            'dimensions': {
                key: {'score': 65, 'confidence': 'medium', 'rationale': 'Supported.', 'evidence': [quote]}
                for key in criterion_keys
            },
            'gates': [],
        }), {'provider': 'test', 'model': 'test', 'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}
    monkeypatch.setattr(strategy, '_strategy_generate_reply', grounded_reply)

    response = client.post(f'/api/v1/strategy/threads/{tid}/score-batch', headers=auth_headers, json={})

    assert response.status_code == 200, response.get_json()
    assert response.get_json()['count'] == 2
    cards = agent._collect_session_scorecards(agent.load_user_sessions(test_user.id)[tid], user_id=test_user.id, thread_id=tid)
    vendor_a = next(card for card in cards if card['project_name'] == 'Vendor A')
    assert vendor_a['attributes']['tco']['value'] == 12_500_000
    assert 'unknown_magic' not in vendor_a['attributes']
    assert vendor_a['rejected_attributes'][0]['field'] == 'unknown_magic'


def test_single_and_batch_tool_paths_capture_equivalent_canonical_evidence(app, db, test_user):
    _, agent = modules()
    from app.routes.sessions import load_user_sessions, save_user_sessions
    single_tid = 'single-evidence-capture'
    batch_tid = 'batch-evidence-capture'
    seed_rfp_thread(test_user, single_tid)
    sessions = load_user_sessions(test_user.id)
    sessions[batch_tid] = {
        **sessions[single_tid],
        'session_id': batch_tid,
        'chat_history': [{'role': 'user', 'content': 'Option A: Contract value $14M.'}],
    }
    sessions[single_tid]['chat_history'] = [{'role': 'user', 'content': 'Option A: Contract value $14M.'}]
    assert save_user_sessions(test_user.id, sessions)
    field = {
        'key': 'contract_value', 'value': '$14M', 'source': 'user',
        'evidence': 'Contract value $14M.', 'source_id': 'message-1',
        'locator': {'message_index': 0},
    }
    single = agent._execute_mutation_tool(
        'set_option_attributes', {'option': 'Option A', 'fields': [field]},
        user=test_user, user_id=test_user.id, thread_id=single_tid,
    )
    batch = agent._execute_mutation_tool(
        'queue_scorecards', {'ideas': [{
            'name': 'Option A', 'description': 'Option A', 'fields': [field],
        }]},
        user=test_user, user_id=test_user.id, thread_id=batch_tid,
    )
    assert single['ok'] and batch['ok']
    single_fact = dict(single['option_attributes']['contract_value'])
    single_fact.pop('updated_at', None)
    batch_fact = batch['queue'][0]['attributes']['contract_value']
    assert batch_fact == single_fact
    assert batch_fact['evidence'] == 'Contract value $14M.'
    assert batch_fact['source'] == 'user'
    assert batch_fact['source_id'] == 'message-1'
    assert batch_fact['locator'] == {'message_index': 0}


@pytest.mark.parametrize(('raw_value', 'canonical_value'), [
    ('confirmed in writing', 'confirmed'),
    ('surety declined', 'declined'),
    ('still pending', 'pending'),
])
def test_ambiguous_bonding_field_uses_schema_value_to_reach_surety_gate(
    app, db, test_user, raw_value, canonical_value,
):
    _, agent = modules()
    from app.routes.sessions import load_user_sessions, save_user_sessions
    tid = f'surety-alias-{canonical_value}'
    seed_rfp_thread(test_user, tid)
    evidence = f'Option A: Bonding requirement is {raw_value}.'
    sessions = load_user_sessions(test_user.id)
    sessions[tid]['chat_history'] = [{'role': 'user', 'content': evidence}]
    assert save_user_sessions(test_user.id, sessions)

    queued = agent._execute_mutation_tool(
        'queue_scorecards', {'ideas': [{
            'name': 'Option A', 'description': 'Option A', 'fields': [{
                'key': 'bonding_requirement', 'value': raw_value,
                'source': 'user', 'evidence': evidence,
            }],
        }]},
        user=test_user, user_id=test_user.id, thread_id=tid,
    )

    assert queued['ok'], queued
    attributes = queued['queue'][0]['attributes']
    assert attributes['surety_status']['value'] == canonical_value
    assert 'capacity_draw' not in attributes


def test_numeric_bonding_requirement_remains_capacity_draw(app):
    from app.decision_facts import normalize_option_facts
    from app.decision_kits import get_decision_kit

    facts = normalize_option_facts({
        'bonding_requirement': {
            'value': '$5M', 'source': 'user', 'evidence': 'Bonding requirement is $5M.',
        },
    }, kit=get_decision_kit('rfp_bid'))
    assert facts['capacity_draw']['value'] == 5_000_000
    assert 'surety_status' not in facts


def test_material_update_migrates_legacy_alias_without_erasing_other_facts(app, db, test_user):
    _, agent = modules()
    from app.routes.sessions import load_user_sessions, save_user_sessions
    tid = 'legacy-alias-material-update'
    seed_rfp_thread(test_user, tid)
    sessions = load_user_sessions(test_user.id)
    session = sessions[tid]
    session['chat_history'] = [{'role': 'user', 'content': 'Build-out is now $320,000.'}]
    session['option_registry'] = {'stable-a': {
        'option_key': 'stable-a', 'display_name': 'Option A',
        'aliases': ['option a'], 'status': 'pending',
    }}
    session['option_aliases'] = {'option a': 'stable-a'}
    session['option_attributes_by_key'] = {'stable-a': {
        'buildout_cost': {'value': 240000, 'source': 'user', 'evidence': 'Buildout cost is $240,000.'},
        'contract_value': {'value': 14000000, 'source': 'user', 'evidence': 'Contract value $14M.'},
    }}
    assert save_user_sessions(test_user.id, sessions)

    result = agent._execute_mutation_tool(
        'set_option_attributes', {'option': 'Option A', 'fields': [{
            'key': 'build_out_cost', 'value': '$320,000', 'source': 'user',
            'evidence': 'Build-out is now $320,000.',
        }]},
        user=test_user, user_id=test_user.id, thread_id=tid,
    )

    assert result['ok'], result
    session = load_user_sessions(test_user.id)[tid]
    current = session['option_attributes_by_key']['stable-a']
    assert set(current) == {'build_out_cost', 'contract_value'}
    assert current['build_out_cost']['value'] == 320000
    history = session['option_attribute_history_by_key']['stable-a']
    assert [item['previous']['value'] for item in history] == [240000]


def test_scorecard_attribute_endpoint_uses_the_same_canonical_alias_migration(
    client, db, test_user, auth_headers,
):
    _, agent = modules()
    from app.routes.sessions import load_user_sessions, save_user_sessions
    tid = 'attribute-endpoint-alias-update'
    seed_rfp_thread(test_user, tid)
    sessions = load_user_sessions(test_user.id)
    session = sessions[tid]
    session['chat_history'] = [{'role': 'user', 'content': 'Build-out is now $320,000.'}]
    session['option_registry'] = {'stable-a': {
        'option_key': 'stable-a', 'display_name': 'Option A',
        'aliases': ['option a'], 'status': 'scored',
    }}
    session['option_aliases'] = {'option a': 'stable-a'}
    session['option_attributes_by_key'] = {'stable-a': {
        'buildout_cost': {'value': 240000, 'source': 'user', 'evidence': 'Buildout cost is $240,000.'},
        'contract_value': {'value': 14000000, 'source': 'user', 'evidence': 'Contract value $14M.'},
    }}
    assert save_user_sessions(test_user.id, sessions)
    upsert_scorecard(user_id=test_user.id, thread_id=tid, payload={
        'id': 'legacy-attribute-card', 'project_name': 'Option A',
        'option_key': 'stable-a', 'jaspen_score': 50,
        'attributes': session['option_attributes_by_key']['stable-a'],
    })
    db.session.commit()

    response = client.patch(
        f'/api/v1/strategy/threads/{tid}/scorecards/legacy-attribute-card/attributes',
        headers=auth_headers,
        json={'attributes': {'build_out_cost': {
            'value': '$320,000', 'source': 'user',
            'evidence': 'Build-out is now $320,000.',
        }}},
    )

    assert response.status_code == 200, response.get_json()
    attributes = response.get_json()['attributes']
    assert set(attributes) == {'build_out_cost', 'contract_value'}
    assert attributes['build_out_cost']['value'] == 320000
    durable = agent.load_user_sessions(test_user.id)[tid]
    assert set(durable['option_attributes_by_key']['stable-a']) == {
        'build_out_cost', 'contract_value',
    }


def test_successful_queue_reply_uses_only_deterministic_confirmation(app):
    _, agent = modules()
    action = {'tool': 'queue_scorecards', 'result': {
        'ok': True,
        'confirmation': 'Queued 3 options for scoring.',
    }}
    reply = agent._finalize_agent_reply(
        'Option A passes its surety gate and the cards are coming.', '', [],
        user_id='u', thread_id='t', executed_actions=[action],
    )
    assert reply == 'Queued 3 options for scoring.'


def test_blocked_queue_reply_requires_rubric_approval_instead_of_claiming_it_was_queued(app, test_user):
    _, agent = modules()
    session = {
        'scoring_rubric': {
            'approval_status': 'proposed',
            'criteria': [
                {'key': 'value', 'label': 'Value', 'weight': 0.6},
                {'key': 'risk', 'label': 'Risk', 'weight': 0.4},
            ],
        },
    }
    result, _ = agent._execute_local_tool(
        'queue_scorecards', {'ideas': [{'name': 'A'}, {'name': 'B'}]},
        readiness={}, user=test_user, user_id=test_user.id, thread_id='blocked-queue',
        user_turn_count=2, mutations_this_turn=0,
        user_message='Score all options now.', session=session,
    )
    assert result['ok'] is False
    assert result['code'] == 'rubric_approval_required'
    reply = agent._finalize_agent_reply(
        'Queued 2 ideas.', '', [], user_id=test_user.id, thread_id='blocked-queue',
        executed_actions=[{'tool': 'queue_scorecards', 'result': result}],
    )
    assert 'Approve this proposed scoring rubric to continue scoring:' in reply
    assert '- Value: weight 60%' in reply
    assert '- Risk: weight 40%' in reply
    assert result['actions'][0]['label'] == 'Approve rubric'


def test_active_decision_kit_adds_required_gates_to_a_custom_proposed_rubric(app, db, test_user):
    _, agent = modules()
    from app.routes.sessions import load_user_sessions, save_user_sessions
    tid = 'kit-gates-custom-rubric'
    seed_rfp_thread(test_user, tid)
    sessions = load_user_sessions(test_user.id)
    sessions[tid].pop('scoring_rubric', None)
    assert save_user_sessions(test_user.id, sessions)

    result = agent._execute_mutation_tool(
        'set_scoring_rubric', {'criteria': [
            {'label': 'Bondability', 'weight': 30},
            {'label': 'Financial value', 'weight': 70},
        ]},
        user=test_user, user_id=test_user.id, thread_id=tid,
        user_message='Propose a rubric for these bids.',
    )

    assert result['ok'] is True
    rubric = result['rubric']
    assert rubric['approval_status'] == 'proposed'
    gates = {item['key']: item for item in rubric['criteria'] if item.get('gate')}
    assert set(gates) == {'submission_deadline', 'capacity_available', 'surety_confirmation'}
    assert all(item['weight'] == 0 and item['source'] == 'decision_kit' for item in gates.values())
    weighted = [item for item in rubric['criteria'] if not item.get('gate')]
    assert sum(item['weight'] for item in weighted) == pytest.approx(1.0)


def test_custom_criterion_cannot_shadow_a_required_kit_gate(app):
    _, agent = modules()
    from app.decision_kits import get_decision_kit
    merged = agent._rubric_with_required_kit_gates([
        {'key': 'surety_confirmation', 'label': 'Bondability', 'weight': 0.3},
        {'key': 'financial_value', 'label': 'Financial value', 'weight': 0.7},
    ], get_decision_kit('rfp_bid'))
    surety = next(item for item in merged if item['key'] == 'surety_confirmation')
    assert surety['gate'] is True
    assert surety['weight'] == 0
    assert surety['source'] == 'decision_kit'
    assert sum(item['weight'] for item in merged if not item.get('gate')) == pytest.approx(1.0)


def test_rfp_queue_stops_when_canonical_fact_persistence_fails(app, db, test_user, monkeypatch):
    _, agent = modules()
    from app.routes.sessions import load_user_sessions, save_user_sessions
    tid = 'rfp-canonical-persist-failure'
    seed_rfp_thread(test_user, tid)
    sessions = load_user_sessions(test_user.id)
    sessions[tid]['chat_history'] = [{'role': 'user', 'content': 'Option A: Contract value $14M.'}]
    assert save_user_sessions(test_user.id, sessions)
    monkeypatch.setattr(agent, 'save_user_sessions', lambda *_args, **_kwargs: False)

    result = agent._execute_mutation_tool(
        'queue_scorecards',
        {'ideas': [{
            'name': 'Option A',
            'description': 'Option A',
            'fields': [{
                'key': 'contract_value', 'value': '$14M', 'source': 'user',
                'evidence': 'Contract value $14M.',
            }],
        }]},
        user=test_user, user_id=test_user.id, thread_id=tid,
    )

    assert result['ok'] is False
    assert result['code'] == 'canonical_fact_persist_failed'
    assert result['retryable'] is True
    assert result['action'] == {'type': 'retry', 'label': 'Retry'}


def test_rfp_single_score_with_no_canonical_facts_uses_neutral_values(app, db, test_user, monkeypatch):
    strategy, agent = modules()
    tid = 'rfp-no-raw-prose-fallback'
    seed_rfp_thread(test_user, tid)
    mock_accounting(monkeypatch)
    monkeypatch.setattr(strategy, '_generate_jaspen_scorecard', lambda *a, **k: ({
        'jaspen_score': 45,
        'score_category': 'Fair',
        'dimensions': {},
        'gates': [],
        'neutral_criteria': [
            {'key': 'delivery_capability_capacity', 'label': 'Delivery capability & capacity', 'score': 45},
        ],
    }, {'provider': 'test', 'input_tokens': 1, 'output_tokens': 1}))

    result = agent._execute_mutation_tool(
        'generate_scorecard',
        {'name': 'Option A', 'idea_description': 'Contract value and margin are somewhere in this prose.'},
        user=test_user, user_id=test_user.id, thread_id=tid,
    )

    assert result['ok'] is True
    assert result['scorecard']['jaspen_score'] == 45
    assert result['neutral_criteria'][0]['label'] == 'Delivery capability & capacity'


def test_empty_batch_is_failed_retryable_preserves_queue_and_charges_zero(client, db, test_user, auth_headers, monkeypatch):
    strategy, agent = modules()
    tid = 'live-empty-batch'
    queue = [{'name': 'Aurora RFP', 'description': 'Aurora RFP', 'option_key': 'aurora'}]
    seed_rfp_thread(test_user, tid, queue=queue)
    mock_accounting(monkeypatch)
    initial_credits = test_user.credits_remaining
    monkeypatch.setattr(strategy, '_generate_batch_scorecards', lambda *a, **k: (
        [None], {}, {'provider': 'test', 'model': 'test', 'input_tokens': 2, 'output_tokens': 2, 'total_tokens': 4}
    ))

    response = client.post(f'/api/v1/strategy/threads/{tid}/score-batch', headers=auth_headers, json={})

    payload = response.get_json()
    assert response.status_code == 503, payload
    assert payload['failure_state'] is True and payload['retryable'] is True
    assert payload['action'] == {'type': 'retry', 'label': 'Retry'}
    assert payload['persisted_project_count'] == 0
    assert payload['credits']['charged'] == 0
    assert agent.load_user_sessions(test_user.id)[tid]['scorecard_queue'][0]['name'] == 'Aurora RFP'
    row = AIOperation.query.filter_by(thread_id=tid, operation_type='score_batch').one()
    assert row.status == 'failed' and row.charged_credits == 0
    assert test_user.credits_remaining == initial_credits


def test_score_next_targets_each_option_and_keeps_only_failure_for_retry(
    client, test_user, auth_headers, monkeypatch
):
    _, agent = modules()
    tid = 'independent-score-next-queue'
    queue = [
        {'name': 'Option A', 'description': 'First option'},
        {'name': 'Option B', 'description': 'Second option'},
        {'name': 'Option C', 'description': 'Third option'},
    ]
    seed_rfp_thread(test_user, tid, queue=queue)

    failed = {'Option B'}

    def score_one(_tool, tool_input, **_kwargs):
        name = tool_input['name']
        if name in failed:
            return {'ok': False, 'error': 'Provider unavailable.'}
        scorecard = {'id': f'card-{name}', 'project_name': name, 'jaspen_score': 60}
        return {
            'ok': True,
            'scorecard': scorecard,
            'artifact': {'type': 'scorecard', 'data': scorecard},
        }

    monkeypatch.setattr(agent, '_execute_mutation_tool', score_one)

    first = client.post(
        f'/api/v1/strategy/threads/{tid}/score-next',
        headers=auth_headers,
        json={'name': 'Option A'},
    )
    second = client.post(
        f'/api/v1/strategy/threads/{tid}/score-next',
        headers=auth_headers,
        json={'name': 'Option B'},
    )
    third = client.post(
        f'/api/v1/strategy/threads/{tid}/score-next',
        headers=auth_headers,
        json={'name': 'Option C'},
    )

    assert first.status_code == second.status_code == third.status_code == 200
    assert first.get_json()['ok'] is True
    failure = second.get_json()
    assert failure['ok'] is False
    assert failure['failure_state'] is True
    assert failure['action'] == {'type': 'retry', 'label': 'Retry'}
    assert third.get_json()['ok'] is True

    stored = agent.load_user_sessions(test_user.id)[tid]
    assert [item['name'] for item in stored['scorecard_queue']] == ['Option B']
    artifacts = [
        item.get('artifact', {}).get('data', {}).get('project_name')
        for item in stored['chat_history']
        if isinstance(item.get('artifact'), dict)
    ]
    assert artifacts == ['Option A', 'Option C']
    failure_messages = [
        item for item in stored['chat_history'] if item.get('score_queue_error')
    ]
    assert failure_messages[-1]['failed_option_name'] == 'Option B'
    assert failure_messages[-1]['action'] == {'type': 'retry', 'label': 'Retry'}

    failed.clear()
    retry = client.post(
        f'/api/v1/strategy/threads/{tid}/score-next',
        headers=auth_headers,
        json={'name': 'Option B'},
    )
    assert retry.status_code == 200
    assert retry.get_json()['ok'] is True
    assert agent.load_user_sessions(test_user.id)[tid]['scorecard_queue'] == []


def test_score_next_accepts_explicitly_authorized_proposed_rubric(
    client, test_user, auth_headers, monkeypatch,
):
    _, agent = modules()
    from app.routes.sessions import load_user_sessions, save_user_sessions

    tid = 'score-next-proposed-rubric'
    seed_rfp_thread(test_user, tid, queue=[{
        'name': 'Denver Water', 'description': 'Denver Water', 'option_key': 'denver-water',
    }])
    sessions = load_user_sessions(test_user.id)
    rubric = sessions[tid]['scoring_rubric']
    rubric.pop('approved_by_user_at', None)
    rubric.update({
        'approval_status': 'proposed',
        'source': 'jaspen_proposed',
        'scoring_authorized_by': 'explicit_score_request',
    })
    assert save_user_sessions(test_user.id, sessions)
    monkeypatch.setattr(agent, '_execute_mutation_tool', lambda *a, **k: {
        'ok': True,
        'scorecard': {'id': 'card-denver', 'project_name': 'Denver Water', 'jaspen_score': 60},
        'artifact': {
            'type': 'scorecard',
            'data': {'id': 'card-denver', 'project_name': 'Denver Water', 'jaspen_score': 60},
        },
    })

    response = client.post(
        f'/api/v1/strategy/threads/{tid}/score-next',
        headers=auth_headers,
        json={'name': 'Denver Water'},
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()['ok'] is True


def test_score_fresh_bypasses_reuse_for_only_the_selected_option(
    client, db, test_user, auth_headers, monkeypatch,
):
    strategy, agent = modules()
    from app import decision_fingerprint

    tid = 'score-fresh-selected-option'
    option_a = {
        'id': 'card-a', 'analysis_id': 'card-a', 'project_name': 'Option A',
        'name': 'Option A', 'option_key': 'option-a', 'jaspen_score': 41,
        'decision_fingerprint': 'same-state', 'attributes': {},
    }
    option_b = {
        'id': 'card-b', 'analysis_id': 'card-b', 'project_name': 'Option B',
        'name': 'Option B', 'option_key': 'option-b', 'jaspen_score': 52,
        'decision_fingerprint': 'same-state', 'attributes': {},
    }
    seed_thread(test_user, tid, [option_a, option_b])
    upsert_scorecard(user_id=test_user.id, thread_id=tid, payload=option_a)
    upsert_scorecard(user_id=test_user.id, thread_id=tid, payload=option_b)
    db.session.commit()
    mock_accounting(monkeypatch)
    monkeypatch.setattr(decision_fingerprint, 'scoring_fingerprint', lambda **_kwargs: 'same-state')
    generated = []

    def score_fresh(*_args, **_kwargs):
        generated.append(1)
        return ({
            'jaspen_score': 77,
            'score_category': 'Strong',
            'dimensions': {},
            'gates': [],
        }, {
            'provider': 'test', 'model': 'test',
            'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2,
        })

    monkeypatch.setattr(strategy, '_generate_jaspen_scorecard', score_fresh)

    response = client.post(
        f'/api/v1/strategy/threads/{tid}/score-next',
        headers=auth_headers,
        json={
            'scorecard_id': 'card-b',
            'option_key': 'option-b',
            'force_fresh': True,
        },
    )

    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    assert payload['ok'] is True, payload
    assert payload['fresh_scored'] is True
    assert payload['scorecard_id'] == 'card-b'
    assert payload['scorecard']['jaspen_score'] == 77
    assert generated == [1]
    by_id = {
        row.id: row.to_peer_dict()
        for row in Scorecard.query.filter_by(user_id=test_user.id, thread_id=tid).all()
    }
    assert by_id['card-a']['jaspen_score'] == 41
    assert by_id['card-b']['jaspen_score'] == 77
    stored = agent.load_user_sessions(test_user.id)[tid]
    assert stored['chat_history'] == []


def test_failed_single_scoring_turn_is_explicit_saved_retryable_and_zero_credit(client, db, test_user, auth_headers, monkeypatch):
    _, agent = modules()
    tid = 'live-failed-single-score'
    seed_rfp_thread(test_user, tid)
    initial_credits = test_user.credits_remaining
    monkeypatch.setattr(agent, '_reserve_preflight_credits', lambda *a, **k: {'ok': True, 'reserved': 0})
    monkeypatch.setattr(agent, '_settle_reserved_credits', lambda *a, **k: {
        'ok': True, 'charged': 0, 'remaining': initial_credits,
    })
    monkeypatch.setattr(agent, '_execute_mutation_tool', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('scorer crashed')))

    def failed_turn(*args, **kwargs):
        result, _ = agent._execute_local_tool(
            'generate_scorecard',
            {'name': 'Aurora RFP', 'idea_description': 'Score Aurora'},
            readiness={}, user=test_user, user_id=test_user.id, thread_id=tid,
            user_turn_count=2, mutations_this_turn=0,
        )
        action = {'tool': 'generate_scorecard', 'input': {}, 'result': result}
        return 'Your scorecard is coming.', {'provider': 'test', 'model': 'test', 'input_tokens': 3, 'output_tokens': 3, 'total_tokens': 6}, [action], [{'tool': 'generate_scorecard', 'success': False, 'code': result['code']}], None

    monkeypatch.setattr(agent, '_generate_assistant_reply', failed_turn)
    response = client.post('/api/v1/ai-agent/conversation/continue', headers=auth_headers, json={
        'thread_id': tid,
        'message': 'Score Aurora now.',
    })

    payload = response.get_json()
    assert response.status_code == 200, payload
    assert payload['failure_state'] is True and payload['success'] is False
    assert payload['action'] == {'type': 'retry', 'label': 'Retry'}
    assert payload['credits']['charged'] == 0
    assert payload['reply'] == "Jaspen couldn't complete scoring. Your request is saved. Try again."
    stored = agent.load_user_sessions(test_user.id)[tid]
    assert any(item.get('role') == 'user' and item.get('content') == 'Score Aurora now.' for item in stored['chat_history'])
    assert not any('scorecard is coming' in str(item.get('content') or '').lower() for item in stored['chat_history'])
    usage_row = UsageEvent.query.filter_by(thread_id=tid, operation_type='score_next').one()
    assert usage_row.success is False and usage_row.credits_charged == 0


def test_streaming_single_score_failure_suppresses_normal_looking_narration(app, test_user, monkeypatch):
    from types import SimpleNamespace

    _, agent = modules()
    failure = agent._scoring_tool_failure(
        "Jaspen couldn't complete scoring. Your request is saved. Try again.",
        code='scorecard_generation_failed',
    )

    class Stream:
        def __init__(self, message, events=()):
            self.message = message
            self.events = list(events)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def __iter__(self):
            return iter(self.events)
        def get_final_message(self):
            return self.message

    tool_message = SimpleNamespace(
        content=[SimpleNamespace(type='tool_use', name='generate_scorecard', id='score-1', input={'name': 'Aurora RFP', 'idea_description': 'Score Aurora'})],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    misleading_message = SimpleNamespace(
        content=[SimpleNamespace(type='text', text='Your scorecard is coming.')],
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    misleading_event = SimpleNamespace(
        type='content_block_delta',
        delta=SimpleNamespace(type='text_delta', text='Your scorecard is coming.'),
    )
    streams = [Stream(tool_message), Stream(misleading_message, [misleading_event])]

    monkeypatch.setattr(agent, '_anthropic_api_key', lambda: 'test-key')
    monkeypatch.setattr(agent, '_prepare_context_window', lambda *a, **k: ([{'role': 'user', 'content': 'Score Aurora'}], '', {}))
    monkeypatch.setattr(agent, '_build_agent_system_prompt', lambda **k: 'Test')
    monkeypatch.setattr(agent, '_wbs_content_prompt_suffix', lambda *a: '')
    monkeypatch.setattr(agent, '_anthropic_message_create', lambda *a, **k: (streams.pop(0), 'test-model'))
    monkeypatch.setattr(agent, '_execute_local_tool', lambda *a, **k: (failure, 0))

    state = {}
    events = list(agent._stream_assistant_reply_events_anthropic(
        'Score Aurora',
        [{'role': 'user', 'content': 'Score Aurora'}],
        {},
        {'llm_model': 'test-model'},
        user=test_user,
        user_id=test_user.id,
        thread_id='stream-failed-score',
        session={},
        state=state,
    ))

    assert not any(event.get('type') == 'delta' and 'coming' in event.get('text', '').lower() for event in events)
    assert state['reply'] == "Jaspen couldn't complete scoring. Your request is saved. Try again."
    assert state['actions'][0]['result']['failure_state'] is True


def test_live_general_scoring_creates_decision_record(client, db, test_user, monkeypatch):
    from app.models_decision_record import DecisionRecord

    strategy, agent = modules()
    tid = 'live-record-general'
    seed_thread(test_user, tid)
    mock_accounting(monkeypatch)
    monkeypatch.setattr(
        strategy,
        '_generate_jaspen_scorecard',
        lambda *a, **k: ({
            'jaspen_score': 64,
            'score_category': 'Good',
            'dimensions': {'fit': {'score': 64, 'confidence': 'medium'}},
        }, {'provider': 'test', 'input_tokens': 1, 'output_tokens': 1}),
    )

    result = agent._execute_mutation_tool(
        'generate_scorecard',
        {'name': 'General option', 'idea_description': 'Evaluate this general option'},
        user=test_user,
        user_id=test_user.id,
        thread_id=tid,
    )

    assert result['ok'] is True
    record = DecisionRecord.query.filter_by(thread_id=tid).one()
    assert record.status == 'recorded'
    assert record.record['decision_kit'] is None
    assert record.record['scorecards'][0]['id'] == result['scorecard']['id']
    assert record.record['scorecards'][0]['option_key'] == result['scorecard']['option_key']


def test_execution_route_persists_ai_generated_plan(client, db, test_user, auth_headers, monkeypatch):
    from app.models_decision_record import DecisionRecord, OptionDecision
    strategy, _ = modules()
    tid = 'planner-route-success'
    card = {'id': 'planner-card', 'project_name': 'Proposal', 'jaspen_score': 61, 'recommendations': [{'id': 'rec-1', 'text': 'Resolve the compliance response'}]}
    seed_thread(test_user, tid, [card])
    upsert_scorecard(user_id=test_user.id, thread_id=tid, payload=card)
    db.session.commit()
    mock_accounting(monkeypatch)
    monkeypatch.setattr(
        strategy,
        '_generate_ai_wbs_suggestion',
        lambda *args, **kwargs: (
            {'tasks': [{'id': '1', 'title': 'Resolve the Proposal compliance response', 'estimated_days': 1, 'lineage': [
                {'type': item['type'], 'ref': item['ref']} for item in kwargs.get('lineage_sources', []) if item.get('required')
            ]}]},
            {'provider': 'anthropic', 'model': 'claude-test', 'input_tokens': 12, 'output_tokens': 15, 'total_tokens': 27},
            True,
            None,
        ),
    )
    blocked = client.post(
        f'/api/v1/strategy/threads/{tid}/ai-wbs',
        headers=auth_headers,
        json={'commit': True, 'scorecard_id': 'planner-card'},
    )
    assert blocked.status_code == 409
    assert blocked.get_json()['code'] == 'recorded_advancing_decision_required'
    assert blocked.get_json()['option_name'] == 'Proposal'
    assert blocked.get_json()['action'] == 'record_decision'
    response = client.post(f'/api/v1/strategy/threads/{tid}/ai-wbs', headers=auth_headers, json={'commit': True, 'scorecard_id': 'planner-card', 'record_decision': {'acknowledged': True}})
    assert response.status_code == 200, response.get_json()
    plan = response.get_json()['project_wbs']
    assert plan['ai_generated'] is True
    assert plan['generation_status'] == 'ai_generated'
    row = AIOperation.query.filter_by(thread_id=tid, operation_type='execution_plan').one()
    assert row.status == 'succeeded'
    stored = strategy._load_scenarios(test_user.id)[tid]
    assert strategy._resolve_thread_wbs(stored, 'planner-card')['generation_status'] == 'ai_generated'
    decision = DecisionRecord.query.filter_by(thread_id=tid).one()
    assert decision.final_decision is None
    option_decision = OptionDecision.query.filter_by(
        decision_record_id=decision.id, superseded_at=None,
    ).one()
    assert OptionDecision.query.filter_by(decision_record_id=decision.id).count() == 1
    assert option_decision.option_key == 'scorecard:planner-card'
    assert option_decision.final_decision == 'Moving forward with Proposal — execution plan built.'
    assert option_decision.source == 'build_execution_plan'


@pytest.mark.parametrize('has_existing_plan', [False, True])
def test_execution_provider_failure_cannot_create_or_overwrite_plan(client, db, test_user, auth_headers, monkeypatch, has_existing_plan):
    from app.models_decision_record import DecisionRecord, OptionDecision
    strategy, _ = modules()
    tid = f"planner-route-failure-{'existing' if has_existing_plan else 'empty'}"
    card = {'id': 'planner-card', 'project_name': 'Proposal', 'jaspen_score': 61}
    seed_thread(test_user, tid, [card])
    upsert_scorecard(user_id=test_user.id, thread_id=tid, payload=card)
    stored = strategy._load_scenarios(test_user.id)
    stored.setdefault(tid, strategy._thread_entry())
    existing = {
        'name': 'Proposal execution plan',
        'scorecard_id': 'planner-card',
        'generation_status': 'ai_generated',
        'ai_generated': True,
        'tasks': [{'id': 'specific-task', 'title': 'Prepare the Proposal compliance matrix'}],
    }
    if has_existing_plan:
        strategy._store_thread_wbs(stored[tid], 'planner-card', existing)
    strategy._save_scenarios(test_user.id, stored)
    db.session.commit()
    mock_accounting(monkeypatch)
    monkeypatch.setattr(strategy, '_strategy_generate_reply', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('provider unavailable')))

    initial_credits = test_user.credits_remaining
    response = client.post(f'/api/v1/strategy/threads/{tid}/ai-wbs', headers=auth_headers, json={'commit': True, 'force': True, 'scorecard_id': 'planner-card', 'record_decision': {'acknowledged': True}})

    assert response.status_code == 503, response.get_json()
    assert response.get_json() == {
        'success': False,
        'code': 'execution_plan_generation_failed',
        'error': "Jaspen couldn't finish building this plan — try again. Your existing plan was not changed.",
        'retryable': True,
        'generation_status': 'failed',
        'provider_error': 'RuntimeError',
        'source_item_count': 1,
    }
    after = strategy._resolve_thread_wbs(strategy._load_scenarios(test_user.id)[tid], 'planner-card')
    if has_existing_plan:
        assert after == existing
        assert after['tasks'] == [{'id': 'specific-task', 'title': 'Prepare the Proposal compliance matrix'}]
    else:
        assert after is None
    row = AIOperation.query.filter_by(thread_id=tid, operation_type='execution_plan_refinement').one()
    assert row.status == 'degraded'
    assert row.metadata_json['generation_failed'] is True
    assert row.charged_credits == 0
    assert test_user.credits_remaining == initial_credits
    record = DecisionRecord.query.filter_by(thread_id=tid).one()
    decision = OptionDecision.query.filter_by(
        decision_record_id=record.id, option_key='scorecard:planner-card', superseded_at=None,
    ).one()
    assert decision.final_decision == 'Moving forward with Proposal.'
    assert 'plan built' not in decision.final_decision.lower()


def test_execution_plan_skips_repair_after_50_seconds_used(
    client, db, test_user, auth_headers, monkeypatch,
):
    strategy, _ = modules()
    tid = 'planner-route-repair-budget-expired'
    card = {
        'id': 'planner-card', 'project_name': 'Proposal', 'jaspen_score': 61,
        'recommendations': [{'id': 'r1', 'text': 'Prepare the response'}],
        'dimensions': {'contract_commercial_risk': {'score': 40}},
    }
    seed_thread(test_user, tid, [card])
    upsert_scorecard(user_id=test_user.id, thread_id=tid, payload=card)
    db.session.commit()
    mock_accounting(monkeypatch)
    calls = []

    def provider(*_args, **_kwargs):
        calls.append(True)
        return json.dumps(_phased_lineage_plan(task_count=16, phase_count=4, ref='r1')), {
            'provider': 'anthropic', 'stop_reason': 'end_turn',
            'input_tokens': 10, 'output_tokens': 20, 'total_tokens': 30,
        }

    clock_values = iter([0, 0, 0, 50, 50])
    monkeypatch.setattr(strategy, 'time', types.SimpleNamespace(monotonic=lambda: next(clock_values)))
    monkeypatch.setattr(strategy, '_strategy_generate_reply', provider)
    initial_credits = test_user.credits_remaining

    response = client.post(
        f'/api/v1/strategy/threads/{tid}/ai-wbs', headers=auth_headers,
        json={'commit': True, 'scorecard_id': 'planner-card', 'record_decision': {'acknowledged': True}},
    )

    assert response.status_code == 503
    assert response.get_json()['code'] == 'execution_plan_generation_failed'
    assert calls == [True]
    stored_thread = strategy._load_scenarios(test_user.id).get(tid)
    assert stored_thread is None or strategy._resolve_thread_wbs(stored_thread, 'planner-card') is None
    operation = AIOperation.query.filter_by(thread_id=tid, operation_type='execution_plan').one()
    assert operation.charged_credits == 0
    assert operation.metadata_json['plan_attempts'][0]['outcome'] == 'lineage_rejected'
    assert test_user.credits_remaining == initial_credits


def test_malformed_execution_plan_response_is_not_saved_and_records_stop_reason(
    client, db, test_user, auth_headers, monkeypatch,
):
    strategy, _ = modules()
    tid = 'planner-route-malformed-json'
    card = {'id': 'planner-card', 'project_name': 'Proposal', 'jaspen_score': 61,
            'recommendations': [{'id': 'rec-1', 'text': 'Prepare the response'}]}
    seed_thread(test_user, tid, [card])
    upsert_scorecard(user_id=test_user.id, thread_id=tid, payload=card)
    db.session.commit()
    mock_accounting(monkeypatch)
    monkeypatch.setattr(
        strategy,
        '_strategy_generate_reply',
        lambda *args, **kwargs: ('{"phases":[', {
            'provider': 'anthropic', 'model': 'claude-test', 'stop_reason': 'max_tokens',
            'input_tokens': 3, 'output_tokens': 8000, 'total_tokens': 8003,
        }),
    )

    response = client.post(
        f'/api/v1/strategy/threads/{tid}/ai-wbs', headers=auth_headers,
        json={'commit': True, 'force': True, 'scorecard_id': 'planner-card',
              'record_decision': {'acknowledged': True}},
    )

    assert response.status_code == 503
    assert response.get_json()['error'].startswith("Jaspen couldn't finish building this plan")
    assert response.get_json()['retryable'] is True
    stored_thread = strategy._load_scenarios(test_user.id).get(tid)
    assert stored_thread is None or strategy._resolve_thread_wbs(stored_thread, 'planner-card') is None
    event = UsageEvent.query.filter_by(thread_id=tid, operation_type='execution_plan_refinement').one()
    assert event.success is False
    assert event.metadata_json['stop_reason'] == 'max_tokens'
    assert event.metadata_json['stop_reasons'] == ['max_tokens', 'max_tokens']
    operation = AIOperation.query.filter_by(thread_id=tid, operation_type='execution_plan_refinement').one()
    assert operation.status == 'degraded'
    assert operation.metadata_json['stop_reason'] == 'max_tokens'
    assert operation.metadata_json['stop_reasons'] == ['max_tokens', 'max_tokens']
    assert len(operation.metadata_json['plan_attempts']) == 2
    assert [item['outcome'] for item in operation.metadata_json['plan_attempts']] == [
        'truncated_json', 'truncated_json',
    ]
    attempts = AIProviderAttempt.query.filter_by(operation_id=operation.id).order_by(
        AIProviderAttempt.sequence.asc()
    ).all()
    assert len(attempts) == 2
    assert all(item.duration_ms is not None for item in attempts)
    assert all(item.metadata_json['stop_reason'] == 'max_tokens' for item in attempts)


def test_queue_to_route_completes_seven_and_agent_can_compare(client, db, test_user, auth_headers, monkeypatch):
    strategy, agent = modules()
    tid = 'seven-route'
    seed_thread(test_user, tid)
    mock_accounting(monkeypatch)
    queued = agent._execute_mutation_tool('queue_scorecards', {'ideas': [{'name': f'Option {i}'} for i in range(7)]}, user=test_user, user_id=test_user.id, thread_id=tid)
    assert queued['queued_count'] == 7
    monkeypatch.setattr(strategy, '_generate_jaspen_scorecard', lambda *a, **k: ({
        'dimensions': {'strategic_alignment': {'score': 70, 'confidence': 'medium'}},
        'jaspen_score': 70,
        'score_category': 'Good',
        'gates': [],
    }, {'provider': 'anthropic', 'model': 'test', 'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}))
    response = client.post(f'/api/v1/strategy/threads/{tid}/score-batch', headers=auth_headers, json={})
    assert response.status_code == 200, response.get_json()
    assert response.get_json()['count'] == 7
    session = agent.load_user_sessions(test_user.id)[tid]
    assert not session.get('scorecard_queue')
    cards = agent._collect_session_scorecards(session, user_id=test_user.id, thread_id=tid)
    assert len(cards) == 7
    assert {card['project_name'] for card in cards} == {f'Option {i}' for i in range(7)}
    compared = agent._execute_mutation_tool('generate_tradeoff_comparison', {}, user=test_user, user_id=test_user.id, thread_id=tid)
    assert compared['ok'], compared
    assert compared['tradeoff']['included_count'] == 7


def test_rescore_replaces_canonical_card_in_place(app, db, test_user, monkeypatch):
    strategy, agent = modules()
    tid = 'rescore-current'
    card = {'id': 'city', 'project_name': 'Commerce City', 'jaspen_score': 59, 'top_risks': [{'risk': 'Old risk'}]}
    seed_thread(test_user, tid, [card])
    upsert_scorecard(user_id=test_user.id, thread_id=tid, payload=card)
    db.session.commit()
    mock_accounting(monkeypatch)
    monkeypatch.setattr(strategy, '_generate_jaspen_scorecard', lambda *a, **k: ({'jaspen_score': 61, 'project_name': 'Commerce City', 'top_risks': [{'risk': 'Current risk'}]}, {'provider': 'anthropic', 'input_tokens': 1, 'output_tokens': 1}))
    result = agent._execute_mutation_tool('generate_scorecard', {'rescore_scorecard_id': 'city', 'name': 'Commerce City', 'idea_description': 'New material facts'}, user=test_user, user_id=test_user.id, thread_id=tid)
    assert result['ok'] and result['rescored'], result
    cards = agent._collect_session_scorecards(agent.load_user_sessions(test_user.id)[tid], user_id=test_user.id, thread_id=tid)
    assert len(cards) == 1 and cards[0]['id'] == 'city'
    assert cards[0]['jaspen_score'] == 61
    assert cards[0]['top_risks'] == [{'risk': 'Current risk'}]


def test_rescore_identity_mismatch_cannot_overwrite_another_option(app, db, test_user, monkeypatch):
    strategy, agent = modules()
    tid = 'rescore-identity-guard'
    aurora = {'id': 'aurora', 'project_name': 'Aurora', 'name': 'Aurora', 'jaspen_score': 30}
    commerce = {'id': 'commerce', 'project_name': 'Commerce City', 'name': 'Commerce City', 'jaspen_score': 59}
    seed_thread(test_user, tid, [aurora, commerce])
    upsert_scorecard(user_id=test_user.id, thread_id=tid, payload=aurora)
    upsert_scorecard(user_id=test_user.id, thread_id=tid, payload=commerce)
    db.session.commit()

    provider_called = False
    def provider(*args, **kwargs):
        nonlocal provider_called
        provider_called = True
        return {'jaspen_score': 61}, {'provider': 'anthropic'}
    monkeypatch.setattr(strategy, '_generate_jaspen_scorecard', provider)

    result = agent._execute_mutation_tool(
        'generate_scorecard',
        {
            'rescore_scorecard_id': 'aurora',
            'name': 'Commerce City',
            'idea_description': 'Commerce City with new material facts',
        },
        user=test_user,
        user_id=test_user.id,
        thread_id=tid,
    )

    assert result['ok'] is False
    assert result['code'] == 'rescore_option_mismatch'
    assert provider_called is False
    cards = agent._collect_session_scorecards(
        agent.load_user_sessions(test_user.id)[tid],
        user_id=test_user.id,
        thread_id=tid,
    )
    assert len(cards) == 2
    by_id = {card['id']: card for card in cards}
    assert by_id['aurora']['jaspen_score'] == 30
    assert by_id['commerce']['jaspen_score'] == 59


def test_rescore_accepts_a_registered_alias_for_the_same_option(app, db, test_user, monkeypatch):
    strategy, agent = modules()
    from app.routes.sessions import load_user_sessions, save_user_sessions
    tid = 'rescore-same-option-alias'
    card = {
        'id': 'boulder', 'project_name': 'Boulder Pearl Street',
        'name': 'Boulder Pearl Street', 'option_key': 'stable-boulder',
        'jaspen_score': 52,
        'attributes': {'build_out_cost': {
            'value': 240000, 'source': 'user', 'evidence': 'Build-out is $240,000.',
        }},
    }
    seed_thread(test_user, tid, [card])
    sessions = load_user_sessions(test_user.id)
    sessions[tid]['option_registry'] = {'stable-boulder': {
        'option_key': 'stable-boulder', 'display_name': 'Boulder Pearl Street',
        'aliases': ['boulder pearl street', 'boulder pearl street second location'],
        'status': 'scored',
    }}
    sessions[tid]['option_aliases'] = {
        'boulder pearl street': 'stable-boulder',
        'boulder pearl street second location': 'stable-boulder',
    }
    sessions[tid]['option_attributes_by_key'] = {
        'stable-boulder': card['attributes'],
    }
    sessions[tid]['chat_history'] = [{
        'role': 'user', 'content': 'Build-out is now $320,000.',
    }]
    assert save_user_sessions(test_user.id, sessions)
    upsert_scorecard(user_id=test_user.id, thread_id=tid, payload=card)
    db.session.commit()
    mock_accounting(monkeypatch)
    monkeypatch.setattr(strategy, '_generate_jaspen_scorecard', lambda *a, **k: ({
        'jaspen_score': 48, 'score_category': 'Fair',
        'dimensions': {'financial_viability': {'score': 48, 'confidence': 'medium'}},
        'gates': [],
    }, {'provider': 'test', 'input_tokens': 1, 'output_tokens': 1}))

    changed = agent._execute_mutation_tool(
        'set_option_attributes', {
            'option': 'Boulder Pearl Street Second Location',
            'scorecard_id': 'boulder',
            'fields': [{
                'key': 'build_out_cost', 'value': '$320,000', 'source': 'user',
                'evidence': 'Build-out is now $320,000.',
            }],
        },
        user=test_user, user_id=test_user.id, thread_id=tid,
    )
    rescored = agent._execute_mutation_tool(
        'generate_scorecard', {
            'rescore_scorecard_id': 'boulder',
            'name': 'Boulder Pearl Street Second Location',
            'idea_description': 'Re-score after the material fact update.',
        },
        user=test_user, user_id=test_user.id, thread_id=tid,
    )

    assert changed['ok'], changed
    assert rescored['ok'] and rescored['rescored'], rescored
    assert rescored['updated_scorecard']['id'] == 'boulder'
    assert rescored['updated_scorecard']['option_key'] == 'stable-boulder'
    assert rescored['updated_scorecard']['attributes']['build_out_cost']['value'] == 320000


def test_failed_chat_audit_retains_provider_attempts(app, db, test_user):
    _, agent = modules()
    error = ValueError('invalid_response')
    error.jaspen_usage = {'failover': {'attempted_providers': [{'provider': 'anthropic', 'model': 'test', 'outcome': 'invalid_response'}]}}
    agent._record_failed_chat_usage({'user_id': test_user.id, 'session_id': 'failed-action'}, error)
    row = AIOperation.query.one()
    assert row.status == 'failed'
    assert AIProviderAttempt.query.filter_by(operation_id=row.id, outcome='invalid_response').count() == 1


def test_narration_failure_keeps_completed_action_but_marks_degraded(app, test_user, monkeypatch):
    from types import SimpleNamespace
    _, agent = modules()
    monkeypatch.setattr(agent, '_anthropic_api_key', lambda: 'test-key')
    monkeypatch.setattr(agent, '_prepare_context_window', lambda *a, **k: ([{'role': 'user', 'content': 'Score all 7 now'}], '', {}))
    monkeypatch.setattr(agent, '_build_agent_system_prompt', lambda **k: 'Test')
    monkeypatch.setattr(agent, '_wbs_content_prompt_suffix', lambda *a: '')
    monkeypatch.setattr(agent, '_maybe_capture_turn_undo_snapshot', lambda *a, **k: None)
    monkeypatch.setattr(agent, '_execute_local_tool', lambda *a, **k: ({'ok': True, 'tool': 'queue_scorecards', 'confirmation': 'Queued all seven.'}, 1))
    calls = []
    response = SimpleNamespace(content=[SimpleNamespace(type='tool_use', name='queue_scorecards', id='q', input={})], usage=SimpleNamespace(input_tokens=5, output_tokens=5))
    def provider(*a, **k):
        calls.append(k)
        if len(calls) > 1:
            raise RuntimeError('narration unavailable')
        return response, 'test-model'
    monkeypatch.setattr(agent, '_anthropic_message_create', provider)
    reply, usage, actions, mutations, _ = agent._generate_assistant_reply_anthropic('Score all 7 now', [{'role': 'user', 'content': 'Score all 7 now'}], {}, {'llm_model': 'test-model'}, user=test_user, user_id=test_user.id, thread_id='seven', session={}, allow_failover=True)
    assert len(calls) == 2 and len(actions) == 1
    assert mutations[0]['success']
    assert usage['degraded'] and usage['error_code'] == 'narration_failed'
    assert 'Queued all seven.' in reply


def test_chat_execution_plan_confirms_records_and_does_not_reprompt_for_regenerate(app, db, test_user, monkeypatch):
    from app.models_decision_record import DecisionRecord

    strategy, agent = modules()
    tid = 'chat-plan-universal-decision'
    card = {
        'id': 'chat-plan-card',
        'option_key': 'option-general',
        'project_name': 'General expansion',
        'jaspen_score': 68,
        'recommendation': {'verdict_key': 'advance_with_conditions', 'label': 'Proceed with conditions'},
        'recommendations': [{'id': 'rec-1', 'text': 'Validate staffing before launch'}],
    }
    seed_thread(test_user, tid, [card])
    upsert_scorecard(user_id=test_user.id, thread_id=tid, payload=card)
    db.session.commit()

    provider_calls = []
    monkeypatch.setattr(strategy, 'get_llm_client', lambda: object())

    def fake_plan(*args, **kwargs):
        provider_calls.append(kwargs)
        required = [item for item in kwargs.get('lineage_sources', []) if item.get('required')]
        return ({
            'tasks': [{
                'id': 'task-1',
                'title': 'Validate staffing for General expansion',
                'estimated_days': 2,
                'lineage': [{'type': item['type'], 'ref': item['ref']} for item in required],
            }],
        }, {'provider': 'test', 'input_tokens': 1, 'output_tokens': 1}, True, None)

    monkeypatch.setattr(strategy, '_generate_ai_wbs_suggestion', fake_plan)

    def fake_operation(_user, *, generate, **kwargs):
        generated, usage = generate()
        return generated, usage, {'charged_credits': 0, 'reserved_credits': 0}

    monkeypatch.setattr(agent, 'execute_customer_operation', fake_operation)

    confirmation = agent._execute_mutation_tool(
        'generate_execution_plan', {}, user=test_user, user_id=test_user.id, thread_id=tid,
    )
    assert confirmation['ok'] is True
    assert confirmation['confirmation_required'] is True
    assert confirmation['option_key'] == 'option-general'
    assert confirmation['confirmation'] == (
        "This records that you're moving forward with General expansion "
        '(Proceed with conditions) — go ahead?'
    )
    assert provider_calls == []
    assert DecisionRecord.query.filter_by(thread_id=tid).count() == 0

    built = agent._execute_mutation_tool(
        'generate_execution_plan',
        {'decision_acknowledged': True, 'option_key': 'option-general'},
        user=test_user, user_id=test_user.id, thread_id=tid,
    )
    assert built['ok'] is True
    assert built['decision_recorded'] is True
    assert built['project_wbs']['tasks'][0]['title'] == 'Validate staffing for General expansion'
    record = DecisionRecord.query.filter_by(thread_id=tid).one()
    assert record.final_decision is None
    from app.models_decision_record import OptionDecision
    option_decision = OptionDecision.query.filter_by(decision_record_id=record.id).one()
    assert option_decision.final_decision == 'Moving forward with General expansion.'
    assert option_decision.option_key == 'option-general'
    assert option_decision.source == 'build_execution_plan'

    regenerated = agent._execute_mutation_tool(
        'generate_execution_plan', {'regenerate': True},
        user=test_user, user_id=test_user.id, thread_id=tid,
    )
    assert regenerated['ok'] is True
    assert regenerated.get('confirmation_required') is not True
    assert len(provider_calls) == 2


def test_execution_assistant_persists_edits_before_returning_success(
    client, db, test_user, auth_headers, monkeypatch
):
    strategy, _ = modules()
    tid = 'plan-refinement-persist-first'
    seed_thread(test_user, tid)
    stored = strategy._load_scenarios(test_user.id)
    stored[tid] = strategy._thread_entry()
    stored[tid]['project_wbs'] = {
        'name': 'Launch plan',
        'tasks': [{'id': 'task-1', 'title': 'Old title', 'status': 'todo'}],
    }
    assert strategy._save_scenarios(test_user.id, stored)
    monkeypatch.setattr(
        strategy,
        'execute_customer_text_operation',
        lambda *a, **k: (
            json.dumps({
                'reply': 'Updated the task.',
                'uiActions': [{
                    'type': 'WBS_UPDATE_TASK',
                    'payload': {'id': 'task-1', 'title': 'Approved title'},
                }],
            }),
            {'provider': 'test'},
            {'charged_credits': 9, 'operation_id': 'op-refine'},
        ),
    )

    response = client.post(
        f'/api/v1/strategy/threads/{tid}/execution-assistant',
        headers=auth_headers,
        json={'instruction': 'Rename the first task to Approved title.'},
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()['appliedActions'] == 1
    assert response.get_json()['uiActions'] == []
    saved = strategy._load_scenarios(test_user.id)[tid]['project_wbs']
    assert saved['tasks'][0]['title'] == 'Approved title'


def test_execution_assistant_save_failure_reverses_charge_and_keeps_plan(
    client, db, test_user, auth_headers, monkeypatch
):
    strategy, _ = modules()
    tid = 'plan-refinement-save-failure'
    seed_thread(test_user, tid)
    original = {
        'name': 'Launch plan',
        'tasks': [{'id': 'task-1', 'title': 'Keep this title', 'status': 'todo'}],
    }
    stored = strategy._load_scenarios(test_user.id)
    stored[tid] = strategy._thread_entry()
    stored[tid]['project_wbs'] = original
    assert strategy._save_scenarios(test_user.id, stored)
    monkeypatch.setattr(
        strategy,
        'execute_customer_text_operation',
        lambda *a, **k: (
            json.dumps({
                'reply': 'Updated the task.',
                'uiActions': [{
                    'type': 'WBS_UPDATE_TASK',
                    'payload': {'id': 'task-1', 'title': 'Unsaved title'},
                }],
            }),
            {'provider': 'test'},
            {'charged_credits': 9, 'operation_id': 'op-refine-failed'},
        ),
    )
    reversed_settlements = []
    monkeypatch.setattr(
        strategy,
        'reverse_customer_operation_charge',
        lambda user, settlement, **kwargs: reversed_settlements.append((settlement, kwargs)) or 9,
    )
    monkeypatch.setattr(strategy, '_save_scenarios', lambda *a, **k: False)

    response = client.post(
        f'/api/v1/strategy/threads/{tid}/execution-assistant',
        headers=auth_headers,
        json={'instruction': 'Rename the first task.'},
    )

    assert response.status_code == 503
    assert response.get_json() == {
        'error': "Jaspen couldn't save that plan update — try again.",
        'retryable': True,
    }
    assert reversed_settlements == [(
        {'charged_credits': 9, 'operation_id': 'op-refine-failed'},
        {'error_code': 'plan_refinement_persistence_failed'},
    )]
    assert strategy._load_scenarios(test_user.id)[tid]['project_wbs']['tasks'][0]['title'] == 'Keep this title'
