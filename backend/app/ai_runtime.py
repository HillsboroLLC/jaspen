"""Shared execution boundary for customer-visible text generation.

Provider selection, failover, provider-cost telemetry, projected charging, and
single-result settlement meet here. Legacy callers can adopt this boundary
without activating the router or the 3,600-credit policy: both default to
shadow mode.
"""

from __future__ import annotations

from flask import current_app

from . import db
from .ai_audit import persist_operation, projected_charge_for_usage
from .ai_governance import credit_policy_mode


class AIOperationPaymentRequired(RuntimeError):
    def __init__(self, payload):
        super().__init__('Thinking Power exhausted')
        self.payload = dict(payload or {})


def execute_customer_text_operation(
    user,
    *,
    messages,
    system_prompt,
    operation_type,
    model_type='orbit',
    legacy_model=None,
    strategy_objective='balanced',
    max_tokens=900,
    temperature=0.2,
    thread_id=None,
    customer_visible=True,
):
    """Execute one visible result and settle it once.

    Shadow mode records the proposed 3,600-credit charge but preserves the
    caller's prior zero-charge behavior. Active mode reserves and settles via
    the same ledger used by chat and scorecard operations.
    """
    from .routes.ai_agent import (
        _charge_for_usage,
        _generate_routed_chat_reply,
        _release_reserved_credits,
        _reserve_preflight_credits,
        _settle_reserved_credits,
    )

    selection = {
        'model_type': str(model_type or 'orbit'),
        'llm_model': str(
            legacy_model
            or current_app.config.get('ANTHROPIC_MODEL')
            or 'claude-sonnet-4-6'
        ),
    }
    policy_active = credit_policy_mode(current_app.config) == 'active'
    should_charge = bool(policy_active and customer_visible)
    reserved = 0
    if should_charge:
        reservation = _reserve_preflight_credits(
            user,
            selection['model_type'],
            token_hint=max(800, int(max_tokens or 900) * 2),
        )
        if not reservation.get('ok'):
            raise AIOperationPaymentRequired(reservation.get('payload'))
        reserved = int(reservation.get('reserved') or 0)
        db.session.commit()

    try:
        reply, usage = _generate_routed_chat_reply(
            messages,
            selection,
            system_prompt=system_prompt,
            strategy_objective=strategy_objective,
            operation_type=operation_type,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except Exception as exc:
        if reserved:
            _release_reserved_credits(user, reserved)
        persist_operation(
            user,
            usage={},
            charged_credits=0,
            operation_type=operation_type,
            thread_id=thread_id,
            success=False,
            error_code=type(exc).__name__,
            customer_visible=customer_visible,
        )
        db.session.commit()
        raise

    projected_credits, provider_cost = projected_charge_for_usage(usage)
    if should_charge:
        actual_credits = _charge_for_usage(usage, selection['model_type'], user)
        settlement = _settle_reserved_credits(
            user,
            reserved_credits=reserved,
            actual_credits=actual_credits,
        )
        charged = int(settlement.get('charged') or 0)
        if not settlement.get('ok'):
            persist_operation(
                user,
                usage=usage,
                charged_credits=charged,
                operation_type=operation_type,
                thread_id=thread_id,
                success=False,
                error_code='thinking_power_exhausted',
                customer_visible=customer_visible,
            )
            db.session.commit()
            raise AIOperationPaymentRequired(settlement.get('payload'))
    else:
        charged = 0

    operation = persist_operation(
        user,
        usage=usage,
        charged_credits=charged,
        operation_type=operation_type,
        thread_id=thread_id,
        success=True,
        customer_visible=customer_visible,
    )
    if operation is not None:
        metadata = dict(operation.metadata_json or {})
        metadata.update({
            'shadow_projected_credits': int(projected_credits),
            'successful_provider_cost_usd': float(provider_cost or 0),
            'legacy_charge_preserved': not should_charge,
            'internal_cost_absorbed': not customer_visible,
        })
        operation.metadata_json = metadata
    db.session.commit()
    return reply, usage, {
        'charged_credits': charged,
        'projected_credits': int(projected_credits),
        'provider_cost_usd': float(provider_cost or 0),
        'policy_mode': 'active' if policy_active else 'shadow',
        'customer_visible': bool(customer_visible),
    }
