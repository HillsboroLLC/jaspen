#!/usr/bin/env python3
"""Deterministic shadow validation for routing and the 3,600-credit policy."""

import json
from decimal import Decimal

from app.ai_governance import credits_for_provider_cost, routing_decision, shadow_comparison
from app.billing_config import DEFAULT_CREDIT_PACKS, DEFAULT_PLAN_CATALOG, provider_cost_usd


CASES = [
    ('acknowledgement', 'conversation', 'Thanks', 'pluto', 'claude-haiku-4-5', 200, 40),
    ('general_advice', 'conversation', 'Help me think through the options and trade-offs.', 'orbit', 'claude-sonnet-5', 1200, 350),
    ('scorecard', 'scorecard_generation', 'Evaluate this migration before we commit.', 'orbit', 'claude-sonnet-5', 9000, 2600),
    ('batch', 'score_batch', 'Compare five investment alternatives.', 'orbit', 'claude-sonnet-5', 16000, 5000),
    ('scenario', 'scenario_generation', 'Model the downside and assumptions.', 'orbit', 'claude-sonnet-5', 5000, 1200),
    ('report', 'report_generation', 'Create the executive decision report.', 'orbit', 'claude-sonnet-5', 6000, 1800),
    ('connector', 'connector_idea_generation', 'Find grounded initiatives in this data.', 'orbit', 'claude-sonnet-5', 5000, 1400),
    (
        'exceptional',
        'scenario_generation',
        'Board acquisition investment with regulatory and security trade-offs, conflicting assumptions, uncertain downside, and irreversible commitment.',
        'orbit',
        'claude-sonnet-5',
        18000,
        5000,
    ),
]


def _margin(price, public_credits):
    provider_capacity = Decimal(public_credits) / Decimal('3600')
    return ((Decimal(str(price)) - provider_capacity) / Decimal(str(price))) * 100


def _operation_margin(*, public_credits, revenue_per_credit, all_in_provider_cost):
    revenue = Decimal(str(public_credits)) * Decimal(str(revenue_per_credit))
    if revenue <= 0:
        return None
    return ((revenue - Decimal(str(all_in_provider_cost))) / revenue) * 100


def main():
    routing = []
    for name, operation, text, legacy_type, legacy_model, input_tokens, output_tokens in CASES:
        kwargs = {}
        if name == 'exceptional':
            kwargs = {'attachment_count': 3, 'alternatives_count': 4}
        decision = routing_decision(operation_type=operation, text=text, **kwargs)
        comparison = shadow_comparison(
            legacy_routes=[{'provider': 'anthropic', 'model': legacy_model, 'model_type': legacy_type}],
            proposed_decision=decision,
        )
        chosen = decision['routes'][0]
        cost = provider_cost_usd(chosen['model'], input_tokens, output_tokens)
        routing.append({
            'case': name,
            'operation_type': operation,
            'route_class': decision['route_class'],
            'proposed_provider': chosen['provider'],
            'proposed_model': chosen['model'],
            'routing_reasons': decision['routing_reasons'],
            'legacy_model': legacy_model,
            'would_change': comparison['would_change'],
            'sample_provider_cost_usd': round(cost, 6),
            'sample_projected_public_credits': credits_for_provider_cost(cost, internal=False),
        })

    products = []
    for key, plan in DEFAULT_PLAN_CATALOG.items():
        credits = plan.get('monthly_credits')
        monthly = plan.get('monthly_price_usd')
        annual_monthly = plan.get('annual_monthly_price_usd')
        if not credits or not monthly:
            continue
        products.append({
            'product': f'{key}_monthly',
            'margin_percent': round(float(_margin(monthly, int(credits) / 1000)), 2),
        })
        if annual_monthly:
            products.append({
                'product': f'{key}_annual',
                'margin_percent': round(float(_margin(annual_monthly * 12, (int(credits) / 1000) * 12)), 2),
            })
    for key, pack in DEFAULT_CREDIT_PACKS.items():
        products.append({
            'product': key,
            'margin_percent': round(float(_margin(pack['price_usd'], int(pack['credits']) / 1000)), 2),
        })
    products.append({'product': 'limited_time_300k', 'margin_percent': round(float(_margin(999, 300000)), 2)})

    lowest_credit_price = min(
        Decimal(str(item['price_usd'])) / Decimal(int(item['credits']) / 1000)
        for item in DEFAULT_CREDIT_PACKS.values()
    )
    # Forced failover example: a Sonnet attempt consumes estimated work before
    # a Gemini Pro response succeeds. The customer is charged only for Gemini;
    # the Claude attempt remains Jaspen cost.
    failed_attempt_cost = Decimal(str(provider_cost_usd('claude-sonnet-5', 5000, 1000)))
    successful_cost = Decimal(str(provider_cost_usd('gemini-2.5-pro', 5000, 1000)))
    successful_public_credits = credits_for_provider_cost(successful_cost, internal=False)
    forced_failover_margin = _operation_margin(
        public_credits=successful_public_credits,
        revenue_per_credit=lowest_credit_price,
        all_in_provider_cost=failed_attempt_cost + successful_cost,
    )

    payload = {
        'routing_cases': routing,
        'route_distribution': {
            route_class: sum(1 for item in routing if item['route_class'] == route_class)
            for route_class in sorted({item['route_class'] for item in routing})
        },
        'changed_from_legacy': sum(1 for item in routing if item['would_change']),
        'paid_products': products,
        'minimum_direct_ai_cost_margin_percent': min(item['margin_percent'] for item in products),
        'all_paid_products_meet_90_percent_floor': all(item['margin_percent'] >= 90 for item in products),
        'forced_failover_example': {
            'failed_attempt_provider_cost_usd': float(failed_attempt_cost),
            'successful_provider_cost_usd': float(successful_cost),
            'customer_public_credits_charged_once': successful_public_credits,
            'lowest_catalog_revenue_per_credit_usd': float(lowest_credit_price),
            'all_in_margin_percent': round(float(forced_failover_margin), 2),
            'meets_90_percent_floor': bool(forced_failover_margin >= Decimal('90')),
        },
        'subsidized_categories': [
            'free', 'test', 'admin', 'promotional', 'fully_comped',
            'internal', 'public_intake',
        ],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
