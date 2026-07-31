from types import SimpleNamespace

from app.evaluation_telemetry import (
    attachment_metrics,
    build_evaluation_usage_report,
    ensure_session_evaluation_id,
    evaluation_id_for_new_scorecard,
)
from app.models import Scorecard, UsageEvent
from app.routes.sessions import load_user_sessions, save_user_sessions
from app.scorecards import (
    COMPARISON_SESSION_LIMIT_MESSAGE,
    collect_peer_scorecards,
    upsert_scorecard,
)


def _card(card_id, name):
    return {
        'id': card_id,
        'analysis_id': card_id,
        'project_name': name,
        'jaspen_score': 70,
        'dimensions': {},
    }


def _session(user_id, thread_id):
    return {
        'session_id': thread_id,
        'user_id': str(user_id),
        'name': thread_id,
        'status': 'in_progress',
        'chat_history': [],
        'result': {},
        'scorecard_queue': [],
    }


def _mock_batch(monkeypatch, call_sizes):
    from app.routes import ai_agent, strategy

    monkeypatch.setattr(strategy, 'get_llm_client', lambda: object())
    monkeypatch.setattr(
        strategy,
        '_generate_batch_scorecards',
        lambda _client, ideas, **_kwargs: (
            call_sizes.append(len(ideas))
            or ([_card(f'generated-{index}', item['name']) for index, item in enumerate(ideas)], {}, {
                'provider': 'anthropic', 'model': 'claude-test',
                'input_tokens': len(ideas) * 10, 'output_tokens': len(ideas) * 5,
            })
        ),
    )
    monkeypatch.setattr(
        ai_agent,
        '_reserve_preflight_credits',
        lambda *args, **kwargs: {'ok': True, 'reserved': 90, 'remaining': 1000},
    )
    monkeypatch.setattr(ai_agent, '_charge_for_usage', lambda *args, **kwargs: 30)
    monkeypatch.setattr(
        ai_agent,
        '_settle_reserved_credits',
        lambda *args, **kwargs: {'ok': True, 'charged': 30, 'remaining': 970, 'payload': None},
    )


def test_full_session_rejects_project_31_before_provider_call(
    client, db, test_user, auth_headers, monkeypatch
):
    thread_id = 'full-comparison-session'
    assert save_user_sessions(test_user.id, {thread_id: _session(test_user.id, thread_id)})
    for index in range(30):
        upsert_scorecard(
            user_id=test_user.id,
            thread_id=thread_id,
            payload=_card(f'card-{index}', f'Project {index}'),
        )
    db.session.commit()
    provider_calls = []
    _mock_batch(monkeypatch, provider_calls)

    response = client.post(
        f'/api/v1/strategy/threads/{thread_id}/score-batch',
        headers=auth_headers,
        json={'ideas': [{'name': 'Project 31'}]},
    )

    assert response.status_code == 409
    assert response.get_json()['error'] == COMPARISON_SESSION_LIMIT_MESSAGE
    assert provider_calls == []
    assert Scorecard.query.filter_by(user_id=str(test_user.id), thread_id=thread_id).count() == 30


def test_crossing_batch_only_generates_retainable_project_and_all_30_reload(
    client, db, test_user, auth_headers, monkeypatch
):
    thread_id = 'crossing-comparison-session'
    assert save_user_sessions(test_user.id, {thread_id: _session(test_user.id, thread_id)})
    for index in range(29):
        upsert_scorecard(
            user_id=test_user.id,
            thread_id=thread_id,
            payload=_card(f'existing-{index}', f'Existing {index}'),
        )
    db.session.commit()
    provider_calls = []
    _mock_batch(monkeypatch, provider_calls)

    response = client.post(
        f'/api/v1/strategy/threads/{thread_id}/score-batch',
        headers=auth_headers,
        json={'ideas': [{'name': 'Thirty'}, {'name': 'Thirty one'}, {'name': 'Thirty two'}]},
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert provider_calls == [1]
    assert payload['persisted_project_count'] == 1
    assert payload['not_persisted_project_names'] == ['Thirty one', 'Thirty two']
    assert payload['reason'] == 'comparison_session_limit_reached'
    assert len(collect_peer_scorecards(test_user.id, thread_id)) == 30

    reloaded = load_user_sessions(test_user.id)[thread_id]
    assert len(collect_peer_scorecards(test_user.id, thread_id, legacy_session=reloaded)) == 30


def test_second_session_continues_without_account_level_cap(
    client, db, test_user, auth_headers, monkeypatch
):
    first_thread = 'first-full-session'
    second_thread = 'second-session'
    sessions = {
        first_thread: _session(test_user.id, first_thread),
        second_thread: _session(test_user.id, second_thread),
    }
    assert save_user_sessions(test_user.id, sessions)
    for index in range(30):
        upsert_scorecard(
            user_id=test_user.id,
            thread_id=first_thread,
            payload=_card(f'first-{index}', f'First {index}'),
        )
    db.session.commit()
    provider_calls = []
    _mock_batch(monkeypatch, provider_calls)

    response = client.post(
        f'/api/v1/strategy/threads/{second_thread}/score-batch',
        headers=auth_headers,
        json={'ideas': [{'name': 'Continued project'}]},
    )

    assert response.status_code == 200
    assert provider_calls == [1]
    assert len(collect_peer_scorecards(test_user.id, first_thread)) == 30
    assert len(collect_peer_scorecards(test_user.id, second_thread)) == 1


def test_direct_analyze_checks_session_capacity_before_provider_generation(
    client, db, test_user, auth_headers, monkeypatch
):
    from app.routes import strategy

    thread_id = 'full-direct-analysis-session'
    assert save_user_sessions(test_user.id, {thread_id: _session(test_user.id, thread_id)})
    for index in range(30):
        upsert_scorecard(
            user_id=test_user.id,
            thread_id=thread_id,
            payload=_card(f'direct-{index}', f'Direct {index}'),
        )
    db.session.commit()
    provider_calls = []
    monkeypatch.setattr(strategy, 'get_llm_client', lambda: object())
    monkeypatch.setattr(
        strategy,
        '_generate_jaspen_scorecard',
        lambda *_args, **_kwargs: provider_calls.append(True),
    )

    response = client.post(
        '/api/v1/strategy/analyze',
        headers=auth_headers,
        json={'thread_id': thread_id, 'description': 'Project 31'},
    )

    assert response.status_code == 409
    assert response.get_json()['error'] == COMPARISON_SESSION_LIMIT_MESSAGE
    assert provider_calls == []


def test_direct_analyze_binds_scorecard_and_usage_to_framing_evaluation(
    client, db, test_user, auth_headers, monkeypatch
):
    from app.routes import ai_agent, strategy

    thread_id = 'direct-analysis-telemetry'
    session = _session(test_user.id, thread_id)
    evaluation_id = ensure_session_evaluation_id(session, user_id=test_user.id)
    assert save_user_sessions(test_user.id, {thread_id: session})
    monkeypatch.setattr(strategy, 'get_llm_client', lambda: object())
    monkeypatch.setattr(
        strategy,
        '_generate_jaspen_scorecard',
        lambda *_args, **_kwargs: ({
            'name': 'Telemetry project',
            'jaspen_score': 76,
            'dimensions': {},
        }, {
            'provider': 'anthropic', 'model': 'claude-test', 'model_type': 'pluto',
            'input_tokens': 120, 'output_tokens': 60,
        }),
    )
    monkeypatch.setattr(ai_agent, 'extract_and_update_user_memory', lambda *_args, **_kwargs: None)

    response = client.post(
        '/api/v1/strategy/analyze',
        headers=auth_headers,
        json={'thread_id': thread_id, 'description': 'Evaluate the telemetry project'},
    )

    assert response.status_code == 200
    scorecard = Scorecard.query.filter_by(user_id=str(test_user.id), thread_id=thread_id).one()
    event = UsageEvent.query.filter_by(thread_id=thread_id, operation_type='scorecard_generation').one()
    assert scorecard.evaluation_id == evaluation_id
    assert event.evaluation_id == evaluation_id
    assert event.scorecard_id == scorecard.id
    assert event.input_tokens == 120
    assert event.output_tokens == 60
    assert event.success is True


def test_chat_usage_records_evaluation_plan_attachment_and_one_failover_event(app, db, test_user):
    from app.routes.ai_agent import _record_usage

    session = _session(test_user.id, 'telemetry-chat')
    evaluation_id = ensure_session_evaluation_id(session, user_id=test_user.id)
    attachments = [{'name': 'brief.docx', 'text_content': 'a' * 40}]
    actions = [{'result': {'ok': True, 'tool': 'set_scoring_rubric'}}]
    _record_usage(
        session,
        {
            'provider': 'anthropic', 'model': 'claude-test', 'model_type': 'pluto',
            'input_tokens': 100, 'output_tokens': 50,
            'failover': {'attempted': ['route-a'], 'final': 'route-b'},
        },
        12,
        actions=actions,
        attachments=attachments,
    )
    db.session.commit()

    events = UsageEvent.query.filter_by(thread_id='telemetry-chat').all()
    assert len(events) == 1
    event = events[0]
    assert event.evaluation_id == evaluation_id
    assert event.plan_key == 'free'
    assert event.operation_type == 'rubric_refinement'
    assert event.attachment_count == 1
    assert event.extracted_attachment_tokens == 10
    assert event.is_failover is True
    assert event.success is True


def test_failed_chat_event_is_grouped_without_thinking_power_debit(app, db, test_user):
    from app.routes.ai_agent import _record_failed_chat_usage

    session = _session(test_user.id, 'failed-chat')
    evaluation_id = ensure_session_evaluation_id(session, user_id=test_user.id)
    _record_failed_chat_usage(session, RuntimeError('provider unavailable'))

    event = UsageEvent.query.filter_by(thread_id='failed-chat').one()
    assert event.evaluation_id == evaluation_id
    assert event.success is False
    assert event.error_code == 'RuntimeError'
    assert event.settled_credits == 0


def test_scorecard_revision_preserves_evaluation_id(db, test_user):
    thread_id = 'revision-evaluation'
    first = upsert_scorecard(
        user_id=test_user.id,
        thread_id=thread_id,
        payload=_card('stable-card', 'Original'),
        evaluation_id='22222222-2222-4222-8222-222222222222',
    )
    db.session.commit()
    revised = upsert_scorecard(
        user_id=test_user.id,
        thread_id=thread_id,
        payload=_card('stable-card', 'Revised'),
    )
    db.session.commit()

    assert revised.id == first.id
    assert revised.evaluation_id == '22222222-2222-4222-8222-222222222222'
    assert revised.to_peer_dict()['evaluation_id'] == revised.evaluation_id


def test_new_project_gets_new_evaluation_while_review_reuses_scorecard_id(db, test_user):
    session = _session(test_user.id, 'evaluation-lifecycle')
    first_evaluation_id = ensure_session_evaluation_id(session, user_id=test_user.id)
    upsert_scorecard(
        user_id=test_user.id,
        thread_id='evaluation-lifecycle',
        payload=_card('first-project', 'First project'),
        evaluation_id=first_evaluation_id,
    )
    db.session.commit()
    session['active_evaluation_scorecard_id'] = 'first-project'

    reviewed_id = ensure_session_evaluation_id(
        session,
        user_id=test_user.id,
        scorecard_id='first-project',
    )
    second_evaluation_id = evaluation_id_for_new_scorecard(session, user_id=test_user.id)

    assert reviewed_id == first_evaluation_id
    assert second_evaluation_id != first_evaluation_id


def test_attachment_metrics_use_explicit_volume_then_text_estimate():
    assert attachment_metrics([
        {'extracted_tokens': 8, 'text_content': 'ignored'},
        {'text_content': 'a' * 20},
        {'kind': 'image'},
    ]) == (3, 13)


def test_evaluation_report_calculates_ranges_models_attachments_and_plans():
    events = [
        SimpleNamespace(evaluation_id='a', settled_credits=10, credits_charged=10, model='m1', plan_key='free', attachment_count=0, success=True),
        SimpleNamespace(evaluation_id='b', settled_credits=30, credits_charged=30, model='m1', plan_key='starter', attachment_count=1, success=True),
        SimpleNamespace(evaluation_id='c', settled_credits=50, credits_charged=50, model='m2', plan_key='starter', attachment_count=0, success=True),
        SimpleNamespace(evaluation_id=None, settled_credits=999, credits_charged=999, model='legacy', plan_key=None, attachment_count=0, success=True),
    ]

    report = build_evaluation_usage_report(events)

    assert report['evaluations'] == 3
    assert report['average_credits'] == 30
    assert report['median_credits'] == 30
    assert report['credit_ranges']['efficient_p10_p25'][0] < report['credit_ranges']['typical_p25_p75'][1]
    assert report['by_model']['m1']['evaluations'] == 2
    assert report['by_plan']['starter']['evaluations'] == 2
    assert report['by_attachment_usage']['with_attachments']['evaluations'] == 1
    assert report['historical_events_without_evaluation_id_excluded'] == 1
