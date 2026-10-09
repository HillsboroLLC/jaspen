"""Targeted regressions for decision-flow trust boundaries; no live providers."""
import json
import sys
import pytest
from flask import current_app
from app.models import AIOperation, AIProviderAttempt, Scorecard, UsageEvent
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
    ]}
    monkeypatch.setattr(strategy, '_strategy_generate_reply', lambda *a, **k: (json.dumps(response), {}))
    sources = [{"type": "recommendation", "ref": "r1", "label": "Prepare", "required": True}]
    plan, _, success, error = strategy._generate_ai_wbs_suggestion(
        None, 'model', scorecard={'project_name': 'Proposal'}, instruction='',
        model_selection={'llm_model': 'model'}, return_usage=True, lineage_sources=sources,
    )
    assert success and error is None
    assert [task['id'] for task in plan['tasks']] == ['task', 'task-2']
    assert len(plan['tasks'][0]['lineage']) == 1
    assert plan['tasks'][0]['dependencies'] == []
    assert plan['tasks'][1]['dependencies'] == ['task']


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
        ]},
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
    assert 'Financial Value 60%' in reply
    assert 'Delivery Confidence 40%' in reply
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
        'Help me evaluate this RFP.', [], {}, {'llm_model': 'test'},
        session=session, user=test_user, user_id=test_user.id, thread_id=tid,
    )

    assert usage['provider'] == 'deterministic' and actions == []
    assert 'Win probability & competitive position: 20%' in reply
    assert 'Contract & commercial risk: 10%' in reply
    durable = load_user_sessions(test_user.id)[tid]['scoring_rubric']
    assert durable['approval_status'] == 'proposed'
    assert durable['presented_at']
    assert len(durable['criteria']) == 6


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
        'Market opportunity: 18%', 'Financial viability: 20%',
        'Execution readiness: 18%', 'Strategic alignment: 16%',
        'Risk profile: 16%', 'Evidence quality: 12%',
    ]
    assert all(line in reply for line in expected)
    durable = load_user_sessions(test_user.id)[tid]['scoring_rubric']
    assert durable['approval_status'] == 'proposed'
    assert durable['presented_at']
    assert len(durable['criteria']) == 6


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
        'We received vendor proposals and need to select one.', [], {},
        {'llm_model': 'test'}, session=session, state=state,
        user=test_user, user_id=test_user.id, thread_id=tid,
    ))

    reply = state['reply']
    assert events == [{'type': 'delta', 'text': reply}]
    expected = [
        'Functional / technical fit: 25%', 'Total cost of ownership: 20%',
        'Implementation risk & timeline: 20%', 'Vendor viability & references: 15%',
        'Integration & compliance: 10%', 'Commercial terms: 10%',
    ]
    assert all(line in reply for line in expected)
    durable = load_user_sessions(test_user.id)[tid]['scoring_rubric']
    assert durable['approval_status'] == 'proposed'
    assert len(durable['criteria']) == 6


def test_provider_cannot_add_unspoken_rubric_meaning(app, db, test_user):
    _, agent = modules()
    tid = 'rubric-description-grounding'
    seed_thread(test_user, tid)
    result = agent._execute_mutation_tool(
        'set_scoring_rubric', {'criteria': [
            {'label': 'Financial Value', 'weight': 60, 'description': 'Use a secret model rule.'},
            {'label': 'Delivery Confidence', 'weight': 40, 'description': 'Another secret rule.'},
        ]},
        user=test_user, user_id=test_user.id, thread_id=tid,
        user_message='Use Financial Value 60% and Delivery Confidence 40%. Score it now.',
    )
    assert result['ok'] and result['rubric']['approval_status'] == 'approved'
    assert all(item['description'] is None for item in result['rubric']['criteria'])


def test_plain_approval_persists_exact_presented_rubric_before_provider(app, db, test_user, monkeypatch):
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
        assert active['approval_status'] == 'approved'
        assert durable['approval_status'] == 'approved'
        assert active['criteria'] == criteria == durable['criteria']
        return 'Scoring started.', {'provider': 'anthropic', 'model': 'test-model'}, [], [], None

    monkeypatch.setattr(agent, '_generate_assistant_reply_anthropic', provider)
    reply, _, _, _, _ = agent._generate_assistant_reply(
        'I approve this rubric as shown. Score it now.', [], {},
        {'llm_model': 'test-model'}, session=session, user=test_user,
        user_id=test_user.id, thread_id=tid,
    )

    approved = load_user_sessions(test_user.id)[tid]['scoring_rubric']
    assert reply == 'Scoring started.'
    assert approved['criteria'] == criteria
    assert approved['source'] == 'user'
    assert approved['approval_status'] == 'approved'
    assert approved['approved_by_user_at']


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


def test_failed_fact_grounding_blocks_same_turn_rescore(app, db, test_user, monkeypatch):
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
        ]},
        readiness={}, user=test_user, user_id=test_user.id, thread_id=tid,
        user_turn_count=1, mutations_this_turn=0, user_message=message, session=session,
    )
    assert rubric_result['ok'] and rubric_result['rubric']['approval_status'] == 'approved'
    mock_accounting(monkeypatch)
    monkeypatch.setattr(strategy, '_generate_jaspen_scorecard', lambda *a, **k: ({
        'jaspen_score': 62, 'score_category': 'Good',
        'dimensions': {'financial_value': {'score': 62, 'confidence': 'assumed'}},
        'gates': [],
    }, {'provider': 'test', 'input_tokens': 1, 'output_tokens': 1}))
    scored, _ = agent._execute_local_tool(
        'generate_scorecard', {'name': 'Boulder', 'idea_description': 'Evaluate Boulder.'},
        readiness={}, user=test_user, user_id=test_user.id, thread_id=tid,
        user_turn_count=1, mutations_this_turn=count, user_message=message, session=session,
    )
    assert scored['ok'], scored
    assert scored['scorecard']['jaspen_score'] == 62


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


def test_rfp_single_score_cannot_fall_back_to_raw_prose_without_canonical_facts(app, db, test_user):
    _, agent = modules()
    tid = 'rfp-no-raw-prose-fallback'
    seed_rfp_thread(test_user, tid)

    result = agent._execute_mutation_tool(
        'generate_scorecard',
        {'name': 'Option A', 'idea_description': 'Contract value and margin are somewhere in this prose.'},
        user=test_user, user_id=test_user.id, thread_id=tid,
    )

    assert result['ok'] is False
    assert result['code'] == 'canonical_facts_required'
    assert result['retryable'] is True
    assert result['action'] == {'type': 'retry', 'label': 'Retry'}


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
