"""Persistence helpers for versioned AI routing and cost telemetry."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from flask import current_app

from . import db
from .ai_governance import (
    CREDIT_POLICY_VERSION,
    ROUTER_VERSION,
    credit_policy_mode,
    credits_for_provider_cost,
    is_subsidized_usage,
    router_mode,
)
from .billing_config import provider_cost_usd, to_public_plan
from .models import AIOperation, AIProviderAttempt


def new_operation_id():
    return str(uuid.uuid4())


def attach_governance(usage, *, decision, legacy_routes=None, operation_type=None):
    payload = dict(usage) if isinstance(usage, dict) else {}
    operation_id = str(payload.get('operation_id') or new_operation_id())
    payload['operation_id'] = operation_id
    payload['operation_type'] = str(operation_type or payload.get('operation_type') or 'ai_operation')
    payload['governance'] = {
        'router_mode': router_mode(current_app.config),
        'router_version': ROUTER_VERSION,
        'policy_mode': credit_policy_mode(current_app.config),
        'policy_version': CREDIT_POLICY_VERSION,
        'route_class': (decision or {}).get('route_class'),
        'routing_reasons': list((decision or {}).get('routing_reasons') or []),
        'selected_provider': (decision or {}).get('selected_provider'),
        'selected_model': (decision or {}).get('selected_model'),
        'escalated': bool((decision or {}).get('escalated')),
        'legacy_routes': list(legacy_routes or []),
    }
    return payload


def projected_charge_for_usage(usage):
    usage = usage if isinstance(usage, dict) else {}
    cost = _successful_provider_cost(usage)
    return credits_for_provider_cost(cost, internal=True), cost


def _successful_provider_cost(usage):
    usage = usage if isinstance(usage, dict) else {}
    components = [
        item for item in (usage.get('component_usages') or []) if isinstance(item, dict)
    ]
    if components:
        return sum(
            provider_cost_usd(item.get('model'), item.get('input_tokens'), item.get('output_tokens'))
            for item in components
        )
    return provider_cost_usd(
        usage.get('model'),
        usage.get('input_tokens'),
        usage.get('output_tokens'),
    )


def _is_test_user(user):
    email = str(getattr(user, 'email', '') or '').strip().lower()
    return bool(
        current_app.config.get('TESTING')
        or email.endswith('@jaspen.local')
        or email.endswith('@example.com')
    )


def persist_operation(
    user,
    *,
    usage,
    charged_credits,
    operation_type=None,
    thread_id=None,
    success=True,
    error_code=None,
    is_comped=False,
    customer_visible=True,
):
    """Queue an idempotent operation/attempt audit record in the current DB txn."""
    if user is None:
        return None
    usage = usage if isinstance(usage, dict) else {}
    operation_id = str(usage.get('operation_id') or new_operation_id())
    existing = AIOperation.query.get(operation_id)
    if existing is not None:
        return existing

    governance = usage.get('governance') if isinstance(usage.get('governance'), dict) else {}
    failover = usage.get('failover') if isinstance(usage.get('failover'), dict) else {}
    failed_attempts = [item for item in (failover.get('attempted_providers') or []) if isinstance(item, dict)]
    successful_cost = _successful_provider_cost(usage) if success else 0.0
    projected = credits_for_provider_cost(successful_cost, internal=True) if success else 0
    plan_key = to_public_plan(getattr(user, 'subscription_plan', None))
    subsidized = is_subsidized_usage(
        plan_key=plan_key,
        is_test=_is_test_user(user),
        is_admin=bool(getattr(user, 'unlimited_analysis', False)),
        is_comped=bool(is_comped),
    )
    legacy_routes = governance.get('legacy_routes') if isinstance(governance.get('legacy_routes'), list) else []
    legacy_first = legacy_routes[0] if legacy_routes and isinstance(legacy_routes[0], dict) else {}

    operation = AIOperation(
        id=operation_id,
        user_id=str(user.id),
        organization_id=getattr(user, 'active_organization_id', None),
        thread_id=str(thread_id or '').strip() or None,
        operation_type=str(operation_type or usage.get('operation_type') or 'ai_operation'),
        status='succeeded' if success else 'failed',
        customer_visible=bool(customer_visible),
        subsidized=subsidized,
        router_mode=str(governance.get('router_mode') or router_mode(current_app.config)),
        router_version=str(governance.get('router_version') or ROUTER_VERSION),
        route_class=str(governance.get('route_class') or '').strip() or None,
        routing_reasons=list(governance.get('routing_reasons') or []),
        legacy_provider=legacy_first.get('provider'),
        legacy_model=legacy_first.get('model'),
        selected_provider=governance.get('selected_provider'),
        selected_model=governance.get('selected_model'),
        final_provider=str(usage.get('provider') or '').strip() or None,
        final_model=str(usage.get('model') or '').strip() or None,
        escalated=bool(governance.get('escalated') or failed_attempts),
        policy_mode=str(governance.get('policy_mode') or credit_policy_mode(current_app.config)),
        policy_version=str(governance.get('policy_version') or CREDIT_POLICY_VERSION),
        successful_provider_cost_usd=Decimal(str(successful_cost or 0)),
        total_provider_cost_usd=Decimal(str(successful_cost or 0)),
        projected_credits=int(projected),
        charged_credits=int(charged_credits or 0),
        settled_at=datetime.utcnow(),
        error_code=str(error_code or '').strip() or None,
        metadata_json={
            'failed_attempt_costs_absorbed': True,
            'failed_attempt_cost_known': False,
            'customer_charged_once': bool(customer_visible),
            'internal_operation': not bool(customer_visible),
        },
    )
    db.session.add(operation)

    sequence = 1
    for item in failed_attempts:
        db.session.add(AIProviderAttempt(
            operation_id=operation_id,
            sequence=sequence,
            provider=str(item.get('provider') or 'unknown'),
            model=str(item.get('model') or '').strip() or None,
            outcome=str(item.get('outcome') or 'failed'),
            status_code=item.get('status_code'),
            duration_ms=item.get('duration_ms'),
            input_tokens=0,
            output_tokens=0,
            raw_provider_cost_usd=None,
            customer_billable=False,
            error_code=str(item.get('outcome') or '').strip() or None,
            metadata_json={'provider_cost_unknown': True},
        ))
        sequence += 1

    if success:
        components = [
            item for item in (usage.get('component_usages') or []) if isinstance(item, dict)
        ] or [usage]
        for index, component in enumerate(components):
            component_cost = provider_cost_usd(
                component.get('model'),
                component.get('input_tokens'),
                component.get('output_tokens'),
            )
            db.session.add(AIProviderAttempt(
                operation_id=operation_id,
                sequence=sequence,
                provider=str(component.get('provider') or 'unknown'),
                model=str(component.get('model') or '').strip() or None,
                outcome='succeeded',
                input_tokens=int(component.get('input_tokens') or 0),
                output_tokens=int(component.get('output_tokens') or 0),
                raw_provider_cost_usd=Decimal(str(component_cost or 0)),
                customer_billable=bool(customer_visible and index == len(components) - 1),
                metadata_json={
                    'customer_visible_result': bool(customer_visible),
                    'component_index': index,
                    'settled_once_at_operation': True,
                },
            ))
            sequence += 1
    return operation
