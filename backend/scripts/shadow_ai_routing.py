#!/usr/bin/env python3
"""Deterministic shadow validation for routing and the 3,600-credit policy."""

import json
from decimal import Decimal

from app.ai_governance import credits_for_provider_cost, routing_decision, shadow_comparison
from app.billing_config import DEFAULT_CREDIT_PACKS, DEFAULT_PLAN_CATALOG, provider_cost_usd


CASES = [
    ('acknowledgement', 'conversation', 'Thanks', 'pluto', 'claude-haiku-4-5', 200, 40),
    ('general_advice', 'conversation', 'Help me think through the options and trade-offs.', 'orbit', 'claude-sonnet-4-6', 1200, 350),
    ('scorecard', 'scorecard_generation', 'Evaluate this migration before we commit.', 'orbit', 'claude-sonnet-4-6', 9000, 2600),
    ('batch', 'score_batch', 'Compare five investment alternatives.', 'orbit', 'claude-sonnet-4-6', 16000, 5000),
    ('scenario', 'scenario_generation', 'Model the downside and assumptions.', 'orbit', 'claude-sonnet-4-6', 5000, 1200),
    ('report', 'report_generation', 'Create the executive decision report.', 'orbit', 'claude-sonnet-4-6', 6000, 1800),
    ('connector', 'connector_idea_generation', 'Find grounded initiatives in this data.', 'orbit', 'claude-sonnet-4-6', 5000, 1400),
    (
        'exceptional',
        'scenario_generation',
        'Board acquisition investment with regulatory and security trade-offs, conflicting assumptions, uncertain downside, and irreversible commitment.',
        'orbit',
        'claude-sonnet-4-6',
        18000,
        5000,
    ),
]


def _margin(price, public_credits):
    provider_capacity = Decimal(public_credits) / Decimal('3600')
    return ((Decimal(str(price)) - provider_capacity) / Decimal(str(price))) * 100


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
        'subsidized_categories': ['free', 'test', 'admin', 'fully_comped'],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
