from datetime import datetime, timedelta

import pytest

from app.billing_config import (
    apply_plan_to_user,
    consume_credits,
    effective_plan_key,
    get_usage_meter_state,
    release_consumed_credits,
    reset_user_monthly_credits,
)
from app.founder_entitlements import (
    advantage_credit_balance,
    advantage_limits_active,
    grant_advantage_offer,
    has_advantage_entitlement,
    reverse_advantage_credits,
)
from app.models import AccountEntitlement, PersistentCreditGrant, Scorecard, StripeWebhookEvent, UsageEvent, UserSession
from app.routes.sessions import save_user_sessions
from app.scorecards import backfill_legacy_scorecards, collect_peer_scorecards, scorecard_limit_for, upsert_scorecard


def _card(card_id, name, score=70, rubric_key='value'):
    return {
        'id': card_id,
        'analysis_id': card_id,
        'project_name': name,
        'name': name,
        'jaspen_score': score,
        'dimensions': {
            rubric_key: {'label': rubric_key.title(), 'score': score, 'confidence': 'medium'},
        },
        'rubric': {'criteria': [{'key': rubric_key, 'label': rubric_key.title(), 'weight': 1.0}]},
        'createdAt': datetime.utcnow().isoformat(),
    }


def _session_payload(user_id, thread_id, cards):
    first = dict(cards[0])
    first['_baseline_scorecard'] = dict(cards[0], isBaseline=True)
    first['scorecard_snapshots'] = [dict(card, isBaseline=False) for card in cards[1:]]
    first['selected_scorecard_id'] = cards[0]['id']
    return {
        'session_id': thread_id,
        'user_id': str(user_id),
        'name': 'Portfolio',
        'status': 'completed',
        'result': first,
        'analysis_history': [{
            'id': cards[0]['id'],
            'analysis_id': cards[0]['id'],
            'result': first,
        }],
    }


def test_advantage_grant_is_idempotent_and_independent_of_plan(app, db, test_user):
    apply_plan_to_user(test_user, 'free', app.config, reset_credits=True)
    _, first_grant, created = grant_advantage_offer(
        test_user,
        300_000_000,
        payment_reference='pi_advantage_1',
    )
    _, second_grant, created_again = grant_advantage_offer(
        test_user,
        300_000_000,
        payment_reference='pi_advantage_1',
    )
    db.session.commit()

    assert created is True
    assert created_again is False
    assert first_grant.id == second_grant.id
    assert AccountEntitlement.query.count() == 1
    assert PersistentCreditGrant.query.count() == 1
    assert has_advantage_entitlement(test_user)
    assert advantage_credit_balance(test_user) == 300_000_000
    assert test_user.subscription_plan == 'free'


def test_advantage_is_standalone_billing_with_individual_output_access(
    client, app, db, test_user, auth_headers
):
    apply_plan_to_user(test_user, 'free', app.config, reset_credits=True)
    grant_advantage_offer(test_user, 300_000_000, payment_reference='pi_advantage_access')
    db.session.commit()

    response = client.get('/api/v1/billing/status', headers=auth_headers)
    payload = response.get_json()

    assert response.status_code == 200
    assert test_user.subscription_plan == 'free'
    assert payload['plan_key'] == 'free'
    assert payload['effective_plan_key'] == 'essential'
    assert payload['has_jaspen_advantage'] is True
    assert payload['access_restricted'] is False
    assert effective_plan_key(test_user, app.config) == 'essential'


def test_advantage_refund_revokes_standalone_output_access(app, db, test_user):
    apply_plan_to_user(test_user, 'free', app.config, reset_credits=True)
    grant_advantage_offer(test_user, 300_000_000, payment_reference='pi_advantage_refund')
    db.session.commit()

    reversed_amount = reverse_advantage_credits(
        test_user,
        reason='refund',
        external_reference='re_test',
    )
    db.session.commit()

    assert reversed_amount == 300_000_000
    assert advantage_credit_balance(test_user) == 0
    assert has_advantage_entitlement(test_user) is False
    assert effective_plan_key(test_user, app.config) == 'free'


def test_duplicate_advantage_checkout_webhook_does_not_duplicate_grant(
    client, app, db, test_user, monkeypatch
):
    from app.routes import billing

    app.config['STRIPE_WEBHOOK_SECRET'] = 'whsec_founder_test'
    test_user.stripe_customer_id = 'cus_advantage'
    db.session.commit()
    session = {
        'id': 'cs_advantage',
        'payment_intent': 'pi_advantage',
        'customer': 'cus_advantage',
        'metadata': {
            'user_id': str(test_user.id),
            'checkout_type': billing.JASPEN_ADVANTAGE_CHECKOUT_TYPE,
            'tokens': '300000000',
            'campaign_id': 'advantage_pmo',
        },
    }
    event = {
        'id': 'evt_advantage_checkout',
        'type': 'checkout.session.completed',
        'data': {'object': session},
    }
    monkeypatch.setattr(billing.stripe.Webhook, 'construct_event', lambda *_args: event)

    first = client.post('/api/v1/billing/webhook', data=b'{}', headers={'Stripe-Signature': 'test'})
    second = client.post('/api/v1/billing/webhook', data=b'{}', headers={'Stripe-Signature': 'test'})

    assert first.status_code == 200
    assert second.status_code == 200
    assert PersistentCreditGrant.query.filter_by(user_id=str(test_user.id)).count() == 1
    assert AccountEntitlement.query.filter_by(user_id=str(test_user.id)).count() == 1
    assert StripeWebhookEvent.query.filter_by(stripe_event_id='evt_advantage_checkout', processed=True).count() == 1
    assert test_user.subscription_plan == 'free'


def test_advantage_checkout_uses_one_time_price_without_subscription(
    client, app, auth_headers, monkeypatch
):
    from app.routes import billing

    app.config['STRIPE_JASPEN_ADVANTAGE_PRICE_ID'] = 'price_advantage_999'
    app.config['JASPEN_ADVANTAGE_CREDIT_TOKENS'] = 300_000_000
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return {'id': 'cs_advantage', 'url': 'https://checkout.stripe.test/advantage'}

    monkeypatch.setattr(billing, '_ensure_customer_for_user', lambda _user: 'cus_advantage')
    monkeypatch.setattr(billing.stripe.checkout.Session, 'create', fake_create)
    response = client.post(
        '/api/v1/billing/create-jaspen-advantage-checkout',
        headers=auth_headers,
        json={'campaign_id': 'advantage_pmo', 'return_path': '/limited-time/project-prioritization'},
    )

    assert response.status_code == 200
    assert response.get_json()['url'] == 'https://checkout.stripe.test/advantage'
    assert captured['mode'] == 'payment'
    assert captured['line_items'] == [{'price': 'price_advantage_999', 'quantity': 1}]
    assert captured['metadata']['checkout_type'] == billing.JASPEN_ADVANTAGE_CHECKOUT_TYPE
    assert captured['metadata']['tokens'] == '300000000'
    assert 'subscription_data' not in captured


def test_founder_credits_survive_renewal_downgrade_and_reset(app, db, test_user):
    apply_plan_to_user(test_user, 'essential', app.config, reset_credits=True)
    grant_advantage_offer(test_user, 300_000_000, payment_reference='pi_advantage_reset')
    db.session.commit()

    test_user.credits_reset_at = datetime.utcnow() - timedelta(days=35)
    reset_user_monthly_credits(test_user, app.config, force=True)
    apply_plan_to_user(test_user, 'free', app.config, reset_credits=True)
    state = get_usage_meter_state(test_user, app.config)
    db.session.commit()

    assert has_advantage_entitlement(test_user)
    assert advantage_credit_balance(test_user) == 300_000_000
    assert state['remaining'] == 300_300_000
    assert state['founder_credits'] == 300_000_000


def test_monthly_credits_are_consumed_before_founder_credits(app, db, test_user):
    apply_plan_to_user(test_user, 'essential', app.config, reset_credits=True)
    grant_advantage_offer(test_user, 1_000, payment_reference='pi_advantage_order')
    db.session.commit()

    ok, remaining = consume_credits(test_user, 7_000_100)
    db.session.commit()

    assert ok is True
    assert remaining == 900
    assert advantage_credit_balance(test_user) == 900


def test_reservation_release_restores_only_the_current_debit_sources(app, db, test_user):
    apply_plan_to_user(test_user, 'essential', app.config, reset_credits=True)
    grant_advantage_offer(test_user, 1_000, payment_reference='pi_advantage_release')
    db.session.commit()

    consume_credits(test_user, 7_000_100)
    assert advantage_credit_balance(test_user) == 900
    release_consumed_credits(test_user, 50)
    state = get_usage_meter_state(test_user, app.config)
    db.session.commit()

    assert advantage_credit_balance(test_user) == 950
    assert state['monthly_remaining'] == 0
    assert state['remaining'] == 950


def test_founder_limits_end_automatically_at_zero_balance(app, db, test_user):
    apply_plan_to_user(test_user, 'essential', app.config, reset_credits=True)
    grant_advantage_offer(test_user, 10, payment_reference='pi_advantage_limits')
    db.session.commit()
    assert advantage_limits_active(test_user) is True

    consume_credits(test_user, 7_000_010)
    db.session.commit()
    assert advantage_credit_balance(test_user) == 0
    assert advantage_limits_active(test_user) is False
    assert has_advantage_entitlement(test_user) is True


def test_founder_balance_remains_usable_after_upgrade_to_shared_team_pool(app, db, test_user):
    from app.orgs import ensure_default_organization_for_user

    ensure_default_organization_for_user(test_user)
    apply_plan_to_user(test_user, 'team', app.config, reset_credits=True)
    grant_advantage_offer(test_user, 1_000, payment_reference='pi_advantage_team')
    db.session.commit()

    ok, remaining = consume_credits(test_user, 29_000_100)
    db.session.commit()

    assert ok is True
    assert remaining == 900
    assert advantage_credit_balance(test_user) == 900
    reset_user_monthly_credits(test_user, app.config, force=True)
    assert advantage_credit_balance(test_user) == 900
    assert get_usage_meter_state(test_user, app.config)['remaining'] == 29_000_900


def test_peer_collection_merges_native_and_legacy_without_baseline(db, test_user):
    thread_id = 'peer-thread'
    legacy = _card('legacy-1', 'Legacy')
    native = _card('native-1', 'Native', rubric_key='risk')
    upsert_scorecard(user_id=test_user.id, thread_id=thread_id, payload=native)
    db.session.commit()

    peers = collect_peer_scorecards(
        test_user.id,
        thread_id,
        legacy_session=_session_payload(test_user.id, thread_id, [legacy]),
    )

    assert {item['id'] for item in peers} == {'legacy-1', 'native-1'}
    assert all(item['isBaseline'] is False for item in peers)
    assert all('delta_vs_baseline' not in item for item in peers)


def test_backfill_preserves_long_legacy_scorecard_ids_idempotently(db, test_user):
    thread_id = 'legacy-edited-thread'
    legacy_id = '7bd32f48-e851-4ed9-87f2-682687e7d6cc__edited'
    legacy = _card(legacy_id, 'Edited legacy scorecard')
    session = _session_payload(test_user.id, thread_id, [legacy])

    created = backfill_legacy_scorecards(
        user_id=test_user.id,
        thread_id=thread_id,
        legacy_session=session,
    )
    db.session.commit()
    created_again = backfill_legacy_scorecards(
        user_id=test_user.id,
        thread_id=thread_id,
        legacy_session=session,
    )

    assert Scorecard.__table__.c.id.type.length == 255
    assert UsageEvent.__table__.c.scorecard_id.type.length == 255
    assert created == 1
    assert created_again == 0
    assert Scorecard.query.get(legacy_id).data['id'] == legacy_id


def test_deleting_first_middle_and_last_scorecard_keeps_session(
    client, db, test_user, auth_headers
):
    thread_id = 'delete-peers'
    cards = [_card('first', 'First'), _card('middle', 'Middle'), _card('last', 'Last')]
    assert save_user_sessions(test_user.id, {thread_id: _session_payload(test_user.id, thread_id, cards)})
    for card in cards:
        upsert_scorecard(user_id=test_user.id, thread_id=thread_id, payload=card)
    db.session.commit()

    for card_id in ('first', 'middle', 'last'):
        response = client.delete(
            f'/api/v1/strategy/scores/{thread_id}/{card_id}',
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert UserSession.query.filter_by(user_id=str(test_user.id), session_id=thread_id).first() is not None

    assert Scorecard.query.filter_by(user_id=str(test_user.id), thread_id=thread_id, archived_at=None).count() == 0


def test_explicit_session_delete_is_separate_and_archives_peers(
    client, db, test_user, auth_headers
):
    thread_id = 'delete-session'
    card = _card('session-card', 'Session Card')
    assert save_user_sessions(test_user.id, {thread_id: _session_payload(test_user.id, thread_id, [card])})
    upsert_scorecard(user_id=test_user.id, thread_id=thread_id, payload=card)
    db.session.commit()

    response = client.delete(f'/api/v1/sessions/{thread_id}', headers=auth_headers)
    assert response.status_code == 200
    row = UserSession.query.filter_by(user_id=str(test_user.id), session_id=thread_id).first()
    scorecard = Scorecard.query.get('session-card')
    assert row.archived_at is not None
    assert scorecard.archived_at is not None


def test_bundle_and_exports_return_all_peer_scorecards_without_baseline_fields(
    client, db, test_user, auth_headers
):
    from app.routes.export import _scorecard_variants_for_export

    thread_id = 'complete-peers'
    cards = [_card(f'card-{index}', f'Project {index}', score=60 + index) for index in range(12)]
    assert save_user_sessions(test_user.id, {thread_id: _session_payload(test_user.id, thread_id, cards[:1])})
    for card in cards:
        upsert_scorecard(user_id=test_user.id, thread_id=thread_id, payload=card)
    db.session.commit()

    response = client.get(f'/api/v1/strategy/threads/{thread_id}/bundle', headers=auth_headers)
    assert response.status_code == 200
    bundle = response.get_json()
    assert len(bundle['peer_scorecards']) == 12
    assert len(bundle['scorecard_snapshots']) == 12

    variants = _scorecard_variants_for_export(
        _session_payload(test_user.id, thread_id, cards[:1]),
        thread_id,
        user_id=test_user.id,
    )
    assert len(variants) == 12
    assert all(item['is_baseline'] is False for item in variants)
    assert all('delta_vs_baseline' not in item for item in variants)


def test_export_collection_does_not_truncate_portfolios_above_twelve(db, test_user):
    from app.routes.export import _scorecard_variants_for_export

    thread_id = 'fourteen-export-peers'
    cards = [_card(f'export-{index}', f'Export Project {index}') for index in range(14)]
    session = _session_payload(test_user.id, thread_id, cards[:1])
    assert save_user_sessions(test_user.id, {thread_id: session})
    for card in cards:
        upsert_scorecard(user_id=test_user.id, thread_id=thread_id, payload=card)
    db.session.commit()

    variants = _scorecard_variants_for_export(session, thread_id, user_id=test_user.id)

    assert len(variants) == 14
    assert {variant['id'] for variant in variants} == {card['id'] for card in cards}


def test_portfolio_limits_gate_creation_but_not_retention(db, test_user):
    assert scorecard_limit_for(test_user, 'free') == 30
    assert scorecard_limit_for(test_user, 'business') == 30
    grant_advantage_offer(test_user, 1, payment_reference='pi_advantage_capacity')
    db.session.commit()
    assert scorecard_limit_for(test_user, 'free') == 30


def _empty_portfolio_session(user_id, thread_id):
    return {
        'session_id': thread_id,
        'user_id': str(user_id),
        'name': 'Batch portfolio',
        'status': 'in_progress',
        'result': {},
        'scorecard_queue': [],
        'chat_history': [],
    }


def _mock_batch_accounting(monkeypatch):
    from app.routes import ai_agent, strategy

    monkeypatch.setattr(strategy, 'get_llm_client', lambda: object())
    monkeypatch.setattr(
        ai_agent,
        '_reserve_preflight_credits',
        lambda *args, **kwargs: {'ok': True, 'reserved': 100, 'remaining': 200},
    )
    monkeypatch.setattr(ai_agent, '_charge_for_usage', lambda *args, **kwargs: 10)
    monkeypatch.setattr(
        ai_agent,
        '_settle_reserved_credits',
        lambda *args, **kwargs: {'ok': True, 'charged': 10, 'remaining': 290, 'payload': None},
    )


@pytest.mark.parametrize('requested', [29, 30, 31])
def test_batch_generation_respects_free_portfolio_boundary_without_silent_discard(
    requested, client, db, test_user, auth_headers, monkeypatch
):
    from app.routes import strategy

    thread_id = f'batch-{requested}'
    assert save_user_sessions(test_user.id, {thread_id: _empty_portfolio_session(test_user.id, thread_id)})
    ideas = [{'name': f'Project {index}', 'description': 'Evaluate it'} for index in range(requested)]
    generated_sizes = []

    def fake_generate(_client, generated_ideas, **_kwargs):
        generated_sizes.append(len(generated_ideas))
        return ([_card(f'tmp-{i}', item['name']) for i, item in enumerate(generated_ideas)], {}, {
            'provider': 'anthropic', 'model': 'claude-test', 'input_tokens': 50,
            'output_tokens': 50, 'total_tokens': 100,
        })

    _mock_batch_accounting(monkeypatch)
    monkeypatch.setattr(strategy, '_generate_batch_scorecards', fake_generate)

    response = client.post(
        f'/api/v1/strategy/threads/{thread_id}/score-batch',
        headers=auth_headers,
        json={'ideas': ideas},
    )
    payload = response.get_json()
    expected = min(requested, 30)

    assert response.status_code == 200
    assert generated_sizes == [expected]
    assert payload['requested_project_count'] == requested
    assert payload['generated_project_count'] == expected
    assert payload['persisted_project_count'] == expected
    assert len(payload['not_persisted_project_names']) == requested - expected
    assert Scorecard.query.filter_by(user_id=str(test_user.id), thread_id=thread_id).count() == expected
    usage_events = UsageEvent.query.filter_by(thread_id=thread_id, operation_type='score_batch').all()
    assert len(usage_events) == expected
    assert sum(event.reserved_credits for event in usage_events) == 100
    assert sum(event.settled_credits for event in usage_events) == 10
    assert len({event.evaluation_id for event in usage_events}) == expected
    assert all(event.raw_provider_cost_usd is not None for event in usage_events)
    if requested > 30:
        assert payload['reason'] == 'comparison_session_limit_reached'
        assert 'existing scorecards remain saved and accessible' in payload['message'].lower()


def test_batch_reports_partial_model_failure(
    client, db, test_user, auth_headers, monkeypatch
):
    from app.routes import strategy

    thread_id = 'batch-model-partial'
    assert save_user_sessions(test_user.id, {thread_id: _empty_portfolio_session(test_user.id, thread_id)})
    ideas = [{'name': name} for name in ('One', 'Two', 'Three')]
    _mock_batch_accounting(monkeypatch)
    monkeypatch.setattr(
        strategy,
        '_generate_batch_scorecards',
        lambda *_args, **_kwargs: ([_card('one', 'One'), None, _card('three', 'Three')], {}, {}),
    )

    response = client.post(
        f'/api/v1/strategy/threads/{thread_id}/score-batch',
        headers=auth_headers,
        json={'ideas': ideas},
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['generated_project_count'] == 2
    assert payload['persisted_project_count'] == 2
    assert payload['not_persisted_project_names'] == ['Two']
    assert payload['reason'] == 'partial_model_failure'


def test_batch_reports_partial_persistence_failure(
    client, db, test_user, auth_headers, monkeypatch
):
    from app.routes import strategy

    thread_id = 'batch-persist-partial'
    assert save_user_sessions(test_user.id, {thread_id: _empty_portfolio_session(test_user.id, thread_id)})
    ideas = [{'name': name} for name in ('Keep', 'Fail')]
    _mock_batch_accounting(monkeypatch)
    monkeypatch.setattr(
        strategy,
        '_generate_batch_scorecards',
        lambda *_args, **_kwargs: ([_card('keep', 'Keep'), _card('fail', 'Fail')], {}, {}),
    )
    real_upsert = strategy.upsert_scorecard

    def selective_upsert(**kwargs):
        if kwargs['payload'].get('project_name') == 'Fail':
            raise RuntimeError('simulated persistence failure')
        return real_upsert(**kwargs)

    monkeypatch.setattr(strategy, 'upsert_scorecard', selective_upsert)
    response = client.post(
        f'/api/v1/strategy/threads/{thread_id}/score-batch',
        headers=auth_headers,
        json={'ideas': ideas},
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload['generated_project_count'] == 2
    assert payload['persisted_project_count'] == 1
    assert payload['not_persisted_project_names'] == ['Fail']
    assert payload['reason'] == 'partial_persistence_failure'


def test_execution_plan_generation_is_metered(
    client, db, test_user, auth_headers, monkeypatch
):
    from app.routes import strategy

    thread_id = 'metered-execution-plan'
    scorecard = _card('wbs-card', 'WBS Project')
    scorecard['executive_summary'] = 'A grounded project ready for planning.'
    assert save_user_sessions(test_user.id, {thread_id: _session_payload(test_user.id, thread_id, [scorecard])})
    upsert_scorecard(
        user_id=test_user.id,
        thread_id=thread_id,
        payload=scorecard,
        evaluation_id='11111111-1111-4111-8111-111111111111',
    )
    db.session.commit()
    _mock_batch_accounting(monkeypatch)
    monkeypatch.setattr(strategy, 'get_llm_client', lambda: object())
    monkeypatch.setattr(
        strategy,
        '_generate_ai_wbs_suggestion',
        lambda *_args, **_kwargs: ({
            'name': 'Execution plan',
            'summary': 'Metered plan',
            'phases': [{'name': 'Delivery', 'tasks': [{
                'id': 'task-1', 'title': 'Deliver WBS Project', 'estimated_days': 3,
                'priority': 'high', 'dependencies': [],
            }]}],
        }, {
            'provider': 'anthropic', 'model': 'claude-test',
            'input_tokens': 80, 'output_tokens': 120, 'total_tokens': 200,
        }, True, None),
    )

    response = client.post(
        f'/api/v1/strategy/threads/{thread_id}/ai-wbs',
        headers=auth_headers,
        json={'commit': False, 'scorecard_id': 'wbs-card'},
    )

    assert response.status_code == 200
    event = UsageEvent.query.filter_by(thread_id=thread_id, operation_type='execution_plan').one()
    assert event.endpoint == '/threads/<id>/ai-wbs'
    assert event.reserved_credits == 100
    assert event.settled_credits == 10
    assert event.input_tokens == 80
    assert event.output_tokens == 120
    assert event.evaluation_id == '11111111-1111-4111-8111-111111111111'
