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


def subsidy_classification(user, *, explicit=None, customer_visible=True):
    """Return the auditable reason Jaspen, rather than revenue, funds usage."""
    requested = str(explicit or '').strip().lower()
    allowed = {
        'free', 'test', 'admin', 'promotional', 'fully_comped',
        'internal', 'public_intake',
    }
    if requested:
        if requested not in allowed:
            raise ValueError(f'Unsupported subsidy classification: {requested}')
        return requested
    if not customer_visible:
        return 'internal'
    if user is None:
        return 'public_intake'
    if _is_test_user(user):
        return 'test'
    from .admin_policy import is_global_admin
    if is_global_admin(user, app_config=current_app.config):
        return 'admin'
    plan_key = to_public_plan(getattr(user, 'subscription_plan', None))
    if plan_key == 'free':
        return 'free'
    from .models import Payment, PersistentCreditGrant
    comped_payment = Payment.query.filter_by(user_id=str(user.id), is_comped=True).first()
    if comped_payment is not None:
        return 'fully_comped'
    promotional_grant = PersistentCreditGrant.query.filter(
        PersistentCreditGrant.user_id == str(user.id),
        PersistentCreditGrant.status == 'active',
        PersistentCreditGrant.remaining_amount > 0,
        PersistentCreditGrant.source == '300k_limited_time',
    ).first()
    if promotional_grant is not None:
        return 'promotional'
    return None


def _attempt_cost(item):
    raw = item.get('raw_provider_cost_usd')
    if raw is not None:
        try:
            return float(raw), False
        except (TypeError, ValueError):
            pass
    input_tokens = max(0, int(item.get('input_tokens') or 0))
    output_tokens = max(0, int(item.get('output_tokens') or 0))
    return provider_cost_usd(item.get('model'), input_tokens, output_tokens), True


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
    subsidy_reason=None,
    customer_visible=True,
    idempotency_key=None,
    request_fingerprint=None,
    result_json=None,
):
    """Queue an idempotent operation/attempt audit record in the current DB txn."""
    usage = usage if isinstance(usage, dict) else {}
    operation_id = str(usage.get('operation_id') or new_operation_id())
    existing = AIOperation.query.get(operation_id)
    if existing is None and idempotency_key:
        existing = AIOperation.query.filter_by(idempotency_key=str(idempotency_key)).first()

    governance = usage.get('governance') if isinstance(usage.get('governance'), dict) else {}
    failover = usage.get('failover') if isinstance(usage.get('failover'), dict) else {}
    failed_attempts = [item for item in (failover.get('attempted_providers') or []) if isinstance(item, dict)]
    successful_cost = _successful_provider_cost(usage) if success else 0.0
    failed_costs = [_attempt_cost(item) for item in failed_attempts]
    failed_cost = sum(item[0] for item in failed_costs)
    total_cost = successful_cost + failed_cost
    projected = credits_for_provider_cost(successful_cost, internal=True) if success else 0
    classification = subsidy_classification(
        user,
        explicit=('fully_comped' if is_comped else subsidy_reason),
        customer_visible=customer_visible,
    )
    subsidized = bool(classification)
    legacy_routes = governance.get('legacy_routes') if isinstance(governance.get('legacy_routes'), list) else []
    legacy_first = legacy_routes[0] if legacy_routes and isinstance(legacy_routes[0], dict) else {}

    operation = existing or AIOperation(id=operation_id)
    operation.user_id = str(user.id) if user is not None else None
    operation.organization_id = getattr(user, 'active_organization_id', None) if user is not None else None
    operation.thread_id = str(thread_id or '').strip() or None
    operation.operation_type = str(operation_type or usage.get('operation_type') or 'ai_operation')
    operation.idempotency_key = str(idempotency_key or operation.idempotency_key or '').strip() or None
    operation.request_fingerprint = str(request_fingerprint or operation.request_fingerprint or '').strip() or None
    operation.status = 'succeeded' if success else 'failed'
    operation.customer_visible = bool(customer_visible)
    operation.subsidized = subsidized
    operation.subsidy_classification = classification
    operation.router_mode = str(governance.get('router_mode') or router_mode(current_app.config))
    operation.router_version = str(governance.get('router_version') or ROUTER_VERSION)
    operation.route_class = str(governance.get('route_class') or '').strip() or None
    operation.routing_reasons = list(governance.get('routing_reasons') or [])
    operation.legacy_provider = legacy_first.get('provider')
    operation.legacy_model = legacy_first.get('model')
    operation.selected_provider = governance.get('selected_provider')
    operation.selected_model = governance.get('selected_model')
    operation.final_provider = str(usage.get('provider') or '').strip() or None
    operation.final_model = str(usage.get('model') or '').strip() or None
    operation.escalated = bool(governance.get('escalated') or failed_attempts)
    operation.policy_mode = str(governance.get('policy_mode') or credit_policy_mode(current_app.config))
    operation.policy_version = str(governance.get('policy_version') or CREDIT_POLICY_VERSION)
    operation.successful_provider_cost_usd = Decimal(str(successful_cost or 0))
    operation.total_provider_cost_usd = Decimal(str(total_cost or 0))
    operation.projected_credits = int(projected)
    operation.charged_credits = int(charged_credits or 0)
    operation.settled_at = datetime.utcnow()
    operation.error_code = str(error_code or '').strip() or None
    operation.result_json = result_json
    operation.metadata_json = {
        'failed_attempt_costs_absorbed': True,
        'failed_attempt_cost_known': bool(failed_attempts) and not any(estimated for _cost, estimated in failed_costs),
        'failed_attempt_cost_estimated': any(estimated for _cost, estimated in failed_costs),
        'failed_attempt_provider_cost_usd': float(failed_cost or 0),
        'customer_charged_once': bool(customer_visible),
        'internal_operation': not bool(customer_visible),
        'subsidy_classification': classification,
    }
    if existing is None:
        db.session.add(operation)
    else:
        AIProviderAttempt.query.filter_by(operation_id=operation.id).delete(synchronize_session=False)
    operation_id = operation.id

    sequence = 1
    for item, (attempt_cost, cost_estimated) in zip(failed_attempts, failed_costs):
        db.session.add(AIProviderAttempt(
            operation_id=operation_id,
            sequence=sequence,
            provider=str(item.get('provider') or 'unknown'),
            model=str(item.get('model') or '').strip() or None,
            outcome=str(item.get('outcome') or 'failed'),
            status_code=item.get('status_code'),
            duration_ms=item.get('duration_ms'),
            input_tokens=int(item.get('input_tokens') or 0),
            output_tokens=int(item.get('output_tokens') or 0),
            raw_provider_cost_usd=Decimal(str(attempt_cost or 0)),
            customer_billable=False,
            error_code=str(item.get('outcome') or '').strip() or None,
            metadata_json={
                'provider_cost_estimated': bool(cost_estimated),
                'estimate_method': item.get('estimate_method') if cost_estimated else None,
            },
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
