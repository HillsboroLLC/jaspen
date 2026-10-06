"""Targeted regressions for decision-flow trust boundaries; no live providers."""
import json
import sys
import pytest
from flask import current_app
from app.models import AIOperation, AIProviderAttempt
from app.scorecards import upsert_scorecard
from app.ai_runtime import execute_customer_operation


def modules():
    return sys.modules['app.routes.strategy'], sys.modules['app.routes.ai_agent']


def test_execution_planner_worker_has_context(app, monkeypatch):
    strategy, _ = modules()
    def provider(*args, **kwargs):
        assert current_app._get_current_object() is app
        assert kwargs['operation_type'] == 'execution_plan'
        return json.dumps({'tasks': [{'id': '1', 'title': 'Proposal response', 'lineage': [{'type': 'recommendation', 'ref': 'r1'}]}]}), {'provider': 'anthropic', 'input_tokens': 10, 'output_tokens': 10}
    monkeypatch.setattr(strategy, '_strategy_generate_reply', provider)
    plan, usage, success, error = strategy._generate_ai_wbs_suggestion(None, 'model', scorecard={'project_name': 'Proposal'}, instruction='', model_selection={'llm_model': 'model'}, return_usage=True, lineage_sources=[{'type': 'recommendation', 'ref': 'r1', 'label': 'Prepare proposal', 'required': True}])
    assert success and error is None
    assert len(plan['tasks']) == 1 and usage['output_tokens'] == 10
    assert plan['tasks'][0]['lineage'][0]['ref'] == 'r1'


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
    strategy, _ = modules()
    tid = 'planner-route-success'
    card = {'id': 'planner-card', 'project_name': 'Proposal', 'jaspen_score': 61, 'recommendations': [{'id': 'rec-1', 'text': 'Resolve the compliance response'}]}
    seed_thread(test_user, tid, [card])
    upsert_scorecard(user_id=test_user.id, thread_id=tid, payload=card)
    db.session.commit()
    mock_accounting(monkeypatch)
    monkeypatch.setattr(
        strategy,
        '_strategy_generate_reply',
        lambda *args, **kwargs: (
            json.dumps({'tasks': [{'id': '1', 'title': 'Resolve the Proposal compliance response', 'estimated_days': 1, 'lineage': [{'type': 'recommendation', 'ref': 'rec-1'}]}]}),
            {'provider': 'anthropic', 'model': 'claude-test', 'input_tokens': 12, 'output_tokens': 15, 'total_tokens': 27},
        ),
    )
    response = client.post(f'/api/v1/strategy/threads/{tid}/ai-wbs', headers=auth_headers, json={'commit': True, 'scorecard_id': 'planner-card'})
    assert response.status_code == 200, response.get_json()
    plan = response.get_json()['project_wbs']
    assert plan['ai_generated'] is True
    assert plan['generation_status'] == 'ai_generated'
    row = AIOperation.query.filter_by(thread_id=tid, operation_type='execution_plan').one()
    assert row.status == 'succeeded'
    stored = strategy._load_scenarios(test_user.id)[tid]
    assert strategy._resolve_thread_wbs(stored, 'planner-card')['generation_status'] == 'ai_generated'


@pytest.mark.parametrize('has_existing_plan', [False, True])
def test_execution_provider_failure_cannot_create_or_overwrite_plan(client, db, test_user, auth_headers, monkeypatch, has_existing_plan):
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
    response = client.post(f'/api/v1/strategy/threads/{tid}/ai-wbs', headers=auth_headers, json={'commit': True, 'force': True, 'scorecard_id': 'planner-card'})

    assert response.status_code == 503, response.get_json()
    assert response.get_json() == {
        'success': False,
        'code': 'execution_plan_generation_failed',
        'error': 'AI execution-plan generation failed. Your existing plan was not changed.',
        'retryable': True,
        'generation_status': 'failed',
        'provider_error': 'RuntimeError',
        'source_item_count': 0,
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


def test_queue_to_route_completes_seven_and_agent_can_compare(client, db, test_user, auth_headers, monkeypatch):
    strategy, agent = modules()
    tid = 'seven-route'
    seed_thread(test_user, tid)
    mock_accounting(monkeypatch)
    queued = agent._execute_mutation_tool('queue_scorecards', {'ideas': [{'name': f'Option {i}'} for i in range(7)]}, user=test_user, user_id=test_user.id, thread_id=tid)
    assert queued['queued_count'] == 7
    def provider(messages, **kwargs):
        return json.dumps({'dimensions': {'strategic_alignment': {'score': 70, 'confidence': 'medium', 'rationale': 'fit'}}}), {'provider': 'anthropic', 'model': 'test', 'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}
    monkeypatch.setattr(strategy, '_strategy_generate_reply', provider)
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
