from decimal import Decimal

import pytest

from app.ai_audit import attach_governance, persist_operation
from app.ai_governance import (
    CREDIT_POLICY_VERSION,
    CREDITS_PER_PROVIDER_DOLLAR,
    ROUTE_EXCEPTIONAL,
    ROUTE_ROUTINE,
    ROUTE_STRUCTURED,
    ROUTER_VERSION,
    classify_request,
    credits_for_provider_cost,
    routing_decision,
)
from app.models import AIOperation, AIProviderAttempt
from app.ai_runtime import execute_customer_text_operation


def test_3600_policy_uses_internal_ledger_precision_and_ceiling():
    assert CREDITS_PER_PROVIDER_DOLLAR == Decimal('3600')
    assert credits_for_provider_cost('0.01', internal=False) == 36
    assert credits_for_provider_cost('0.000001', internal=True) == 4
    assert credits_for_provider_cost(0, internal=True) == 0


@pytest.mark.parametrize(
    ('price', 'credits'),
    [
        (25, 1_000),
        (139, 7_000),
        (449, 29_000),
        (999, 80_000),
        (999, 300_000),
        (10, 3_000),
        (25, 8_000),
        (50, 18_000),
    ],
)
def test_paid_catalog_has_at_least_90_percent_direct_ai_cost_margin(price, credits):
    provider_cost_capacity = Decimal(credits) / CREDITS_PER_PROVIDER_DOLLAR
    margin = (Decimal(price) - provider_cost_capacity) / Decimal(price)
    assert margin >= Decimal('0.90')


def test_router_classifies_by_work_shape_not_customer_plan():
    text = 'Evaluate this enterprise migration, including security assumptions and downside scenarios.'
    free = routing_decision(operation_type='scorecard_generation', text=text)
    enterprise = routing_decision(operation_type='scorecard_generation', text=text)
    assert free == enterprise
    assert free['route_class'] == ROUTE_STRUCTURED
    assert free['routes'][0]['provider'] == 'anthropic'
    assert all(route['provider'] in {'anthropic', 'gemini'} for route in free['routes'])


def test_short_turn_routes_to_haiku_then_gemini_flash():
    decision = routing_decision(operation_type='conversation', text='Thanks')
    assert decision['route_class'] == ROUTE_ROUTINE
    assert [item['provider'] for item in decision['routes']] == ['anthropic', 'gemini']
    assert 'haiku' in decision['routes'][0]['model']
    assert 'flash' in decision['routes'][1]['model']


def test_exceptional_route_is_reserved_for_multiple_depth_signals():
    route_class, reasons = classify_request(
        operation_type='scenario_generation',
        text=(
            'Board acquisition investment with regulatory and security trade-offs, '
            'conflicting assumptions, uncertain downside, and an irreversible commitment.'
        ),
        attachment_count=3,
        alternatives_count=4,
    )
    assert route_class == ROUTE_EXCEPTIONAL
    assert any(reason.startswith('depth_score:') for reason in reasons)


def test_operation_audit_records_failover_cost_as_jaspen_cost_and_charges_once(app, db, test_user):
    with app.app_context():
        decision = routing_decision(operation_type='scorecard_generation', text='Enterprise migration')
        usage = attach_governance(
            {
                'provider': 'gemini',
                'model': 'gemini-2.5-pro',
                'input_tokens': 1000,
                'output_tokens': 500,
                'failover': {
                    'attempted_providers': [{
                        'provider': 'anthropic',
                        'model': 'claude-sonnet-4-6',
                        'outcome': 'timeout',
                        'duration_ms': 1200,
                    }],
                },
            },
            decision=decision,
            legacy_routes=[{'provider': 'anthropic', 'model': 'claude-sonnet-4-6'}],
            operation_type='scorecard_generation',
        )
        operation = persist_operation(
            test_user,
            usage=usage,
            charged_credits=1234,
            operation_type='scorecard_generation',
            success=True,
        )
        db.session.commit()

        stored = AIOperation.query.get(operation.id)
        attempts = AIProviderAttempt.query.filter_by(operation_id=operation.id).order_by(
            AIProviderAttempt.sequence.asc()
        ).all()
        assert stored.router_version == ROUTER_VERSION
        assert stored.policy_version == CREDIT_POLICY_VERSION
        assert stored.subsidized is True
        assert stored.charged_credits == 1234
        assert stored.metadata_json['customer_charged_once'] is True
        assert len(attempts) == 2
        assert attempts[0].outcome == 'timeout'
        assert attempts[0].customer_billable is False
        assert attempts[0].raw_provider_cost_usd is None
        assert attempts[1].outcome == 'succeeded'
        assert attempts[1].customer_billable is True


def test_shared_runtime_shadow_records_projection_without_changing_balance(
    app, db, test_user, monkeypatch
):
    from app.routes import ai_agent

    monkeypatch.setitem(app.config, 'JASPEN_CREDIT_POLICY_MODE', 'shadow')
    starting_balance = test_user.credits_remaining
    monkeypatch.setattr(
        ai_agent,
        '_generate_routed_chat_reply',
        lambda *_args, **_kwargs: (
            'governed result',
            attach_governance(
                {
                    'provider': 'anthropic',
                    'model': 'claude-sonnet-4-6',
                    'input_tokens': 1000,
                    'output_tokens': 200,
                },
                decision=routing_decision(operation_type='report_generation', text='report'),
                legacy_routes=[{'provider': 'anthropic', 'model': 'claude-sonnet-4-6'}],
                operation_type='report_generation',
            ),
        ),
    )

    _reply, _usage, settlement = execute_customer_text_operation(
        test_user,
        messages=[{'role': 'user', 'content': 'report'}],
        system_prompt='Return a report.',
        operation_type='report_generation',
    )

    operation = AIOperation.query.order_by(AIOperation.created_at.desc()).first()
    assert settlement['charged_credits'] == 0
    assert settlement['projected_credits'] > 0
    assert test_user.credits_remaining == starting_balance
    assert operation.charged_credits == 0
    assert operation.projected_credits == settlement['projected_credits']
    assert operation.metadata_json['legacy_charge_preserved'] is True


def test_shared_runtime_active_settles_exactly_once_for_success(
    app, db, test_user, monkeypatch
):
    from app.routes import ai_agent

    monkeypatch.setitem(app.config, 'JASPEN_CREDIT_POLICY_MODE', 'active')
    calls = {'reserve': 0, 'settle': 0}

    def reserve(*_args, **_kwargs):
        calls['reserve'] += 1
        return {'ok': True, 'reserved': 50_000}

    def settle(*_args, **kwargs):
        calls['settle'] += 1
        return {'ok': True, 'charged': kwargs['actual_credits'], 'remaining': 250_000}

    monkeypatch.setattr(ai_agent, '_reserve_preflight_credits', reserve)
    monkeypatch.setattr(ai_agent, '_settle_reserved_credits', settle)
    monkeypatch.setattr(ai_agent, '_charge_for_usage', lambda *_args, **_kwargs: 12_345)
    monkeypatch.setattr(
        ai_agent,
        '_generate_routed_chat_reply',
        lambda *_args, **_kwargs: (
            'visible result',
            attach_governance(
                {
                    'provider': 'gemini',
                    'model': 'gemini-2.5-pro',
                    'input_tokens': 900,
                    'output_tokens': 300,
                },
                decision=routing_decision(operation_type='data_insights', text='analyze data'),
                legacy_routes=[{'provider': 'anthropic', 'model': 'claude-sonnet-4-6'}],
                operation_type='data_insights',
            ),
        ),
    )

    _reply, _usage, settlement = execute_customer_text_operation(
        test_user,
        messages=[{'role': 'user', 'content': 'analyze data'}],
        system_prompt='Return analysis.',
        operation_type='data_insights',
    )

    assert calls == {'reserve': 1, 'settle': 1}
    assert settlement['charged_credits'] == 12_345
    operation = AIOperation.query.order_by(AIOperation.created_at.desc()).first()
    assert operation.charged_credits == 12_345
    assert AIProviderAttempt.query.filter_by(
        operation_id=operation.id,
        customer_billable=True,
    ).count() == 1


def test_active_automatic_router_does_not_let_plan_cap_model_capability(
    app, db, test_user, monkeypatch
):
    from app.routes import ai_agent

    # Isolate the behavior under test from the current public catalog, where
    # all three legacy labels happen to be available on every plan.
    monkeypatch.setattr(ai_agent, 'get_allowed_model_types', lambda *_args: ['pluto'])

    monkeypatch.setitem(app.config, 'JASPEN_AI_ROUTER_MODE', 'shadow')
    _selection, shadow_error = ai_agent._resolve_model_selection(
        test_user, requested_model_type='titan'
    )
    assert shadow_error['code'] == 'model_type_not_allowed'

    monkeypatch.setitem(app.config, 'JASPEN_AI_ROUTER_MODE', 'active')
    selection, active_error = ai_agent._resolve_model_selection(
        test_user, requested_model_type='titan'
    )
    assert active_error is None
    assert selection['model_type'] == 'titan'


def test_multi_call_batch_sums_provider_cost_but_has_one_settlement(
    app, db, test_user
):
    decision = routing_decision(operation_type='score_batch', text='Compare ten options')
    components = [
        {'provider': 'anthropic', 'model': 'claude-sonnet-4-6', 'input_tokens': 1000, 'output_tokens': 100},
        {'provider': 'anthropic', 'model': 'claude-sonnet-4-6', 'input_tokens': 1200, 'output_tokens': 200},
    ]
    usage = attach_governance(
        {
            'provider': 'anthropic',
            'model': 'claude-sonnet-4-6',
            'input_tokens': 2200,
            'output_tokens': 300,
            'component_usages': components,
        },
        decision=decision,
        legacy_routes=[{'provider': 'anthropic', 'model': 'claude-sonnet-4-6'}],
        operation_type='score_batch',
    )
    operation = persist_operation(
        test_user,
        usage=usage,
        charged_credits=20_000,
        operation_type='score_batch',
    )
    db.session.commit()

    attempts = AIProviderAttempt.query.filter_by(operation_id=operation.id).all()
    assert len(attempts) == 2
    assert sum(1 for attempt in attempts if attempt.customer_billable) == 1
    assert operation.successful_provider_cost_usd == sum(
        attempt.raw_provider_cost_usd for attempt in attempts
    )
    assert operation.charged_credits == 20_000
