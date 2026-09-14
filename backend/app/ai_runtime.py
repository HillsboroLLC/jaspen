"""Central execution boundary for every Jaspen AI operation."""

from __future__ import annotations

import hashlib
import json
import uuid

from flask import current_app, has_request_context, request
from sqlalchemy.exc import IntegrityError

from . import db
from .ai_audit import persist_operation, projected_charge_for_usage, subsidy_classification
from .ai_governance import CREDIT_POLICY_VERSION, ROUTER_VERSION, credit_policy_mode, router_mode
from .models import AIOperation


class AIOperationPaymentRequired(RuntimeError):
    def __init__(self, payload):
        super().__init__('Thinking Power exhausted')
        self.payload = dict(payload or {})


class AIOperationIdempotencyConflict(RuntimeError):
    pass


class AIOperationInProgress(RuntimeError):
    pass


def _request_idempotency_key(explicit=None):
    # ``False`` deliberately disables request-header idempotency. This is used
    # by anonymous, non-billable intake so replay support does not require
    # retaining visitor response content in the durable AI-operation ledger.
    if explicit is False:
        return None
    value = str(explicit or '').strip()
    if not value and has_request_context():
        value = str(request.headers.get('X-Jaspen-Idempotency-Key') or '').strip()
    if not value:
        return None
    if len(value) > 200:
        raise AIOperationIdempotencyConflict('Idempotency key is too long.')
    return value


def _fingerprint(*, user, operation_type, request_payload):
    canonical = json.dumps(
        {
            'user_id': str(getattr(user, 'id', '') or ''),
            'operation_type': str(operation_type or ''),
            'request': request_payload,
        },
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _claim_operation(user, *, operation_type, thread_id, customer_visible,
                     subsidy_reason, idempotency_key, request_fingerprint):
    if not idempotency_key:
        return None, None
    existing = AIOperation.query.filter_by(idempotency_key=idempotency_key).first()
    if existing is not None:
        if existing.request_fingerprint != request_fingerprint:
            raise AIOperationIdempotencyConflict(
                'This idempotency key was already used for a different AI request.'
            )
        if existing.status == 'succeeded' and isinstance(existing.result_json, dict):
            return existing, dict(existing.result_json)
        if existing.status == 'started':
            raise AIOperationInProgress('The same AI request is already in progress.')
        existing.status = 'started'
        existing.error_code = None
        existing.result_json = None
        existing.settled_at = None
        db.session.commit()
        return existing, None

    classification = subsidy_classification(
        user, explicit=subsidy_reason, customer_visible=customer_visible,
    )
    operation = AIOperation(
        id=str(uuid.uuid4()),
        user_id=str(user.id) if user is not None else None,
        organization_id=getattr(user, 'active_organization_id', None) if user is not None else None,
        thread_id=str(thread_id or '').strip() or None,
        operation_type=str(operation_type or 'ai_operation'),
        idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint,
        status='started',
        customer_visible=bool(customer_visible),
        subsidized=bool(classification),
        subsidy_classification=classification,
        router_mode=router_mode(current_app.config),
        router_version=ROUTER_VERSION,
        policy_mode=credit_policy_mode(current_app.config),
        policy_version=CREDIT_POLICY_VERSION,
        projected_credits=0,
        charged_credits=0,
        metadata_json={'idempotency_protected': True},
    )
    db.session.add(operation)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _claim_operation(
            user,
            operation_type=operation_type,
            thread_id=thread_id,
            customer_visible=customer_visible,
            subsidy_reason=subsidy_reason,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
        )
    return operation, None


def execute_customer_operation(user, *, generate, operation_type, request_payload,
                               model_type='orbit', max_tokens=900, thread_id=None,
                               customer_visible=True, subsidy_reason=None,
                               idempotency_key=None):
    """Execute an arbitrary AI generator and settle its visible result once."""
    from .routes.ai_agent import (
        _charge_for_usage,
        _release_reserved_credits,
        _reserve_preflight_credits,
        _settle_reserved_credits,
    )

    raw_key = _request_idempotency_key(idempotency_key)
    # One HTTP action can legitimately contain several governed components
    # (for example, a scorecard tool call plus the surrounding assistant turn).
    # Namespace the client key by customer and operation so components do not
    # collide and one customer's key can never block another customer.
    key = (
        hashlib.sha256(
            f"{getattr(user, 'id', '')}:{operation_type}:{raw_key}".encode('utf-8')
        ).hexdigest()
        if raw_key
        else None
    )
    fingerprint = _fingerprint(
        user=user, operation_type=operation_type, request_payload=request_payload,
    )
    claimed, cached = _claim_operation(
        user,
        operation_type=operation_type,
        thread_id=thread_id,
        customer_visible=customer_visible,
        subsidy_reason=subsidy_reason,
        idempotency_key=key,
        request_fingerprint=fingerprint,
    )
    if cached is not None:
        settlement = dict(cached.get('settlement') or {})
        settlement['idempotent_replay'] = True
        return cached.get('value'), dict(cached.get('usage') or {}), settlement

    policy_mode = credit_policy_mode(current_app.config)
    policy_active = policy_mode == 'active'
    # Shadow/off preserve today's settlement behavior. `_charge_for_usage`
    # chooses the legacy amount unless the new policy is active.
    should_charge = bool(customer_visible and user is not None)
    reserved = 0
    if should_charge:
        reservation = _reserve_preflight_credits(
            user,
            str(model_type or 'orbit'),
            token_hint=max(800, int(max_tokens or 900) * 2),
        )
        if not reservation.get('ok'):
            if claimed is not None:
                claimed.status = 'failed'
                claimed.error_code = 'thinking_power_exhausted'
                db.session.commit()
            raise AIOperationPaymentRequired(reservation.get('payload'))
        reserved = int(reservation.get('reserved') or 0)
        db.session.commit()

    try:
        value, usage = generate()
    except Exception as exc:
        if reserved:
            _release_reserved_credits(user, reserved)
        failed_usage = dict(getattr(exc, 'jaspen_usage', {}) or {})
        if claimed is not None:
            failed_usage['operation_id'] = claimed.id
        persist_operation(
            user,
            usage=failed_usage,
            charged_credits=0,
            operation_type=operation_type,
            thread_id=thread_id,
            success=False,
            error_code=type(exc).__name__,
            subsidy_reason=subsidy_reason,
            customer_visible=customer_visible,
            idempotency_key=key,
            request_fingerprint=fingerprint,
        )
        db.session.commit()
        raise

    usage = dict(usage or {})
    if claimed is not None:
        usage['operation_id'] = claimed.id
    projected_credits, successful_cost = projected_charge_for_usage(usage)
    if should_charge:
        actual_credits = _charge_for_usage(usage, str(model_type or 'orbit'), user)
        credit_settlement = _settle_reserved_credits(
            user, reserved_credits=reserved, actual_credits=actual_credits,
        )
        charged = int(credit_settlement.get('charged') or 0)
        if not credit_settlement.get('ok'):
            persist_operation(
                user,
                usage=usage,
                charged_credits=charged,
                operation_type=operation_type,
                thread_id=thread_id,
                success=False,
                error_code='thinking_power_exhausted',
                subsidy_reason=subsidy_reason,
                customer_visible=customer_visible,
                idempotency_key=key,
                request_fingerprint=fingerprint,
            )
            db.session.commit()
            raise AIOperationPaymentRequired(credit_settlement.get('payload'))
    else:
        charged = 0
        credit_settlement = {'remaining': getattr(user, 'credits_remaining', None)}

    settlement = {
        'charged_credits': charged,
        'reserved_credits': int(reserved or 0),
        'projected_credits': int(projected_credits),
        'provider_cost_usd': float(successful_cost or 0),
        'policy_mode': policy_mode,
        'remaining': credit_settlement.get('remaining'),
        'customer_visible': bool(customer_visible),
        'idempotent_replay': False,
    }
    result_json = {'value': value, 'usage': usage, 'settlement': settlement}
    operation = persist_operation(
        user,
        usage=usage,
        charged_credits=charged,
        operation_type=operation_type,
        thread_id=thread_id,
        success=True,
        subsidy_reason=subsidy_reason,
        customer_visible=customer_visible,
        idempotency_key=key,
        request_fingerprint=fingerprint,
        result_json=result_json if key else None,
    )
    if operation is not None:
        metadata = dict(operation.metadata_json or {})
        metadata.update({
            'shadow_projected_credits': int(projected_credits),
            'successful_provider_cost_usd': float(successful_cost or 0),
            'legacy_charge_preserved': bool(should_charge and not policy_active),
            'internal_cost_absorbed': not customer_visible,
            'idempotency_protected': bool(key),
        })
        operation.metadata_json = metadata
    db.session.commit()
    return value, usage, settlement


def execute_customer_text_operation(user, *, messages, system_prompt, operation_type,
                                    model_type='orbit', legacy_model=None,
                                    strategy_objective='balanced', max_tokens=900,
                                    temperature=0.2, thread_id=None,
                                    customer_visible=True, subsidy_reason=None,
                                    idempotency_key=None, routing_signals=None):
    """Execute one routed text result through the shared operation boundary."""
    from .routes.ai_agent import _generate_routed_chat_reply

    selection = {
        'model_type': str(model_type or 'orbit'),
        'llm_model': str(
            legacy_model or current_app.config.get('ANTHROPIC_MODEL') or 'claude-sonnet-4-6'
        ),
    }
    signals = dict(routing_signals or {})

    def generate():
        return _generate_routed_chat_reply(
            messages,
            selection,
            system_prompt=system_prompt,
            strategy_objective=strategy_objective,
            operation_type=operation_type,
            max_tokens=max_tokens,
            temperature=temperature,
            routing_signals=signals,
        )

    return execute_customer_operation(
        user,
        generate=generate,
        operation_type=operation_type,
        request_payload={
            'messages': messages,
            'system_prompt': system_prompt,
            'strategy_objective': strategy_objective,
            'max_tokens': max_tokens,
            'temperature': temperature,
            'routing_signals': signals,
        },
        model_type=selection['model_type'],
        max_tokens=max_tokens,
        thread_id=thread_id,
        customer_visible=customer_visible,
        subsidy_reason=subsidy_reason,
        idempotency_key=idempotency_key,
    )


def execute_system_text_operation(**kwargs):
    """Run a non-customer operation with full audit and no customer charge."""
    reason = kwargs.pop('subsidy_reason', 'internal')
    return execute_customer_text_operation(
        None, customer_visible=False, subsidy_reason=reason, **kwargs,
    )
