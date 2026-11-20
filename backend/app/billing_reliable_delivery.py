"""Inactive Phase 17 reliable-delivery integration for Phase 12 AI billing.

This module is deliberately disconnected from routes, provider clients, jobs,
and deployment configuration.  It is the worker-facing boundary required by
the Phase 17 activation gate: provider evidence is appended, a successful
response is saved before settlement, settlement can be replayed by a recovery
sweep, and a customer can recover the saved response independently of billing.

The Phase 3 ledger remains the only balance authority.  Phase 12 remains the
only authority for authorization, lease renewal, call usage, settlement,
absorption, and expiration.  ``AIOperation.result_json`` remains the existing
durable result store; this module adds a versioned envelope rather than a
second response or operation store.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from sqlalchemy import and_, func, or_, select

from .billing_ai_operations import (
    AIBillingError,
    AIBillingIsolationError,
    AIBillingStateError,
    _clock,
    expire_ai_operation,
    renew_ai_operation_reservation,
    settle_delivered_operation,
)
from .models import AIOperation, AIProviderAttempt, OrganizationMember
from .models_billing_phase12 import (
    AIAbsorbedUsage,
    AIBillingOperation,
    AIProviderCallUsage,
)


DELIVERY_SCHEMA = "jaspen.reliable-delivery.v1"
DELIVERY_KEY = "reliable_delivery"


class ReliableDeliveryError(AIBillingError):
    pass


class ReliableDeliveryConflictError(ReliableDeliveryError):
    pass


class ReliableDeliveryTimingError(ReliableDeliveryError):
    pass


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError) as exc:
        raise ReliableDeliveryError("the persisted response must be JSON serializable") from exc


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _bound_rows(session, operation_id, *, lock_operation=False):
    query = select(AIOperation).where(AIOperation.id == operation_id)
    if lock_operation:
        query = query.with_for_update()
    operation = session.execute(query).scalar_one_or_none()
    billing = session.get(AIBillingOperation, operation_id)
    if operation is None or billing is None:
        raise AIBillingStateError("the operation is not bound to Phase 12 billing")
    if (
        operation.organization_id != billing.organization_id
        or operation.user_id != billing.actor_user_id
        or operation.billing_account_id != billing.billing_account_id
    ):
        raise AIBillingIsolationError("the operation's durable ownership bindings disagree")
    return operation, billing


def _authorize_identity(session, operation, billing, *, organization_id, actor_user_id,
                        require_active_member=False):
    if organization_id != billing.organization_id or actor_user_id != billing.actor_user_id:
        raise AIBillingIsolationError("the response belongs to another organization or member")
    if require_active_member:
        active = session.execute(select(OrganizationMember.id).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == actor_user_id,
            OrganizationMember.status == "active",
        )).first()
        if active is None:
            raise AIBillingIsolationError("the operation member is no longer active in the organization")
    if operation.organization_id != organization_id or operation.user_id != actor_user_id:
        raise AIBillingIsolationError("the operation's customer identity changed")


def _envelope(operation):
    result = operation.result_json if isinstance(operation.result_json, dict) else {}
    value = result.get(DELIVERY_KEY)
    return value if isinstance(value, dict) and value.get("schema") == DELIVERY_SCHEMA else None


def _write_envelope(operation, envelope):
    result = dict(operation.result_json) if isinstance(operation.result_json, dict) else {}
    result[DELIVERY_KEY] = envelope
    operation.result_json = result


def _call_for_attempt(session, operation_id, attempt_number):
    calls = session.execute(select(AIProviderCallUsage).where(
        AIProviderCallUsage.operation_id == operation_id,
        AIProviderCallUsage.attempt_number == attempt_number,
    ).order_by(AIProviderCallUsage.call_index)).scalars().all()
    if not calls or calls[-1].outcome != "succeeded":
        raise ReliableDeliveryError("the delivered attempt must end in a recorded successful provider call")
    return calls


def _operational_attempt_for_call(session, operation_id, call_id):
    attempts = session.execute(select(AIProviderAttempt).where(
        AIProviderAttempt.operation_id == operation_id,
    ).order_by(AIProviderAttempt.sequence)).scalars().all()
    for attempt in attempts:
        metadata = attempt.metadata_json if isinstance(attempt.metadata_json, dict) else {}
        if metadata.get("phase12_call_usage_id") == call_id:
            return attempt
    return None


def assert_delivery_timing(session, *, operation_id, provider_timeout_seconds, heartbeat_interval_seconds):
    """Fail closed unless a healthy worker can renew before the lease lapses."""
    _operation, billing = _bound_rows(session, operation_id)
    provider_timeout_seconds = int(provider_timeout_seconds)
    heartbeat_interval_seconds = int(heartbeat_interval_seconds)
    if provider_timeout_seconds <= 0 or heartbeat_interval_seconds <= 0:
        raise ReliableDeliveryTimingError("provider timeout and heartbeat interval must be positive")
    if int(billing.lease_seconds) <= provider_timeout_seconds + heartbeat_interval_seconds:
        raise ReliableDeliveryTimingError(
            "reservation_lease_seconds must exceed provider timeout plus heartbeat interval"
        )
    return {
        "lease_seconds": int(billing.lease_seconds),
        "provider_timeout_seconds": provider_timeout_seconds,
        "heartbeat_interval_seconds": heartbeat_interval_seconds,
    }


def heartbeat_reliable_delivery(session, *, operation_id, organization_id, actor_user_id,
                                provider_timeout_seconds, heartbeat_interval_seconds):
    """Worker heartbeat entry point; it has no request/client dependency."""
    operation, billing = _bound_rows(session, operation_id)
    _authorize_identity(
        session, operation, billing, organization_id=organization_id, actor_user_id=actor_user_id,
    )
    assert_delivery_timing(
        session, operation_id=operation_id, provider_timeout_seconds=provider_timeout_seconds,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
    )
    return renew_ai_operation_reservation(session, operation_id=operation_id)


def append_provider_attempt(session, *, operation_id, organization_id, actor_user_id,
                            provider_call_usage_id, duration_ms=None, status_code=None,
                            operational_metadata=None):
    """Append operational evidence linked to immutable Phase 12 call evidence.

    Replaying the same call is a no-op.  Existing attempts are never updated or
    deleted, including when the legacy audit helper is retried.
    """
    operation, billing = _bound_rows(session, operation_id, lock_operation=True)
    _authorize_identity(
        session, operation, billing, organization_id=organization_id, actor_user_id=actor_user_id,
    )
    call = session.get(AIProviderCallUsage, provider_call_usage_id)
    if call is None or call.operation_id != operation_id:
        raise AIBillingIsolationError("provider call evidence belongs to another operation")
    facts = {
        "call_id": call.id,
        "duration_ms": duration_ms,
        "status_code": status_code,
        "metadata": operational_metadata or {},
    }
    fingerprint = _digest(facts)
    existing = _operational_attempt_for_call(session, operation_id, call.id)
    if existing is not None:
        metadata = existing.metadata_json if isinstance(existing.metadata_json, dict) else {}
        if metadata.get("phase17_fingerprint") != fingerprint:
            raise ReliableDeliveryConflictError("provider attempt replay changed its operational facts")
        return existing, True
    sequence = int(session.execute(select(func.coalesce(func.max(AIProviderAttempt.sequence), 0)).where(
        AIProviderAttempt.operation_id == operation_id,
    )).scalar_one()) + 1
    metadata = dict(operational_metadata or {})
    metadata.update({
        "phase12_call_usage_id": call.id,
        "provider_request_id": call.provider_request_id,
        "phase17_fingerprint": fingerprint,
        "append_only": True,
    })
    row = AIProviderAttempt(
        operation_id=operation_id,
        sequence=sequence,
        provider=call.provider,
        model=call.model,
        outcome=call.outcome,
        status_code=status_code,
        duration_ms=duration_ms,
        input_tokens=int(call.input_tokens or 0),
        output_tokens=int(call.output_tokens or 0),
        raw_provider_cost_usd=call.provider_reported_cost_usd or call.computed_cost_usd,
        customer_billable=False,
        error_code=call.error_category,
        metadata_json=metadata,
    )
    session.add(row)
    session.flush()
    return row, False


def persist_successful_response(session, *, operation_id, organization_id, actor_user_id,
                                delivered_attempt_number, response_json):
    """Durably save a successful response before (and independently of) settlement."""
    operation, billing = _bound_rows(session, operation_id, lock_operation=True)
    _authorize_identity(
        session, operation, billing, organization_id=organization_id, actor_user_id=actor_user_id,
    )
    delivered_attempt_number = int(delivered_attempt_number)
    if billing.state not in ("authorized", "expired") or (
        billing.state == "expired" and billing.delivery_status != "unsettled"
    ):
        raise AIBillingStateError("a response must be persisted before financial finalization")
    calls = _call_for_attempt(session, operation_id, delivered_attempt_number)
    if _operational_attempt_for_call(session, operation_id, calls[-1].id) is None:
        raise ReliableDeliveryError("operational provider-attempt evidence must be appended before persistence")
    response_digest = _digest(response_json)
    existing = _envelope(operation)
    if existing is not None:
        if (
            existing.get("response_sha256") != response_digest
            or int(existing.get("delivered_attempt_number") or 0) != delivered_attempt_number
        ):
            raise ReliableDeliveryConflictError("the persisted response cannot be replaced")
        return dict(existing), True
    envelope = {
        "schema": DELIVERY_SCHEMA,
        "operation_id": operation_id,
        "organization_id": organization_id,
        "actor_user_id": actor_user_id,
        "delivered_attempt_number": delivered_attempt_number,
        "provider_request_id": calls[-1].provider_request_id,
        "response_sha256": response_digest,
        "response": response_json,
        "persisted_at": _clock(session).isoformat(),
        "settlement": None,
    }
    _write_envelope(operation, envelope)
    session.flush()
    return dict(envelope), False


def recover_persisted_response(session, *, operation_id, organization_id, actor_user_id):
    """Return the saved response even when settlement or the client connection failed."""
    operation, billing = _bound_rows(session, operation_id)
    _authorize_identity(
        session, operation, billing, organization_id=organization_id, actor_user_id=actor_user_id,
        require_active_member=True,
    )
    envelope = _envelope(operation)
    if envelope is None:
        raise AIBillingStateError("the operation has no persisted response")
    if envelope.get("response_sha256") != _digest(envelope.get("response")):
        raise ReliableDeliveryConflictError("the persisted response failed its integrity check")
    return envelope.get("response")


def settle_persisted_response(session, *, operation_id, organization_id, actor_user_id):
    """Idempotently settle the saved response; safe for any recovery worker to replay."""
    operation, billing = _bound_rows(session, operation_id)
    _authorize_identity(
        session, operation, billing, organization_id=organization_id, actor_user_id=actor_user_id,
    )
    envelope = _envelope(operation)
    if envelope is None:
        raise AIBillingStateError("settlement requires a persisted response")
    result = settle_delivered_operation(
        session,
        operation_id=operation_id,
        delivered_attempt_number=int(envelope["delivered_attempt_number"]),
    )
    operation = session.get(AIOperation, operation_id)
    updated = dict(_envelope(operation) or envelope)
    recorded = {
        "state": result.state,
        "delivery_status": result.delivery_status,
        "charged_credits": result.charged_credits,
        "absorbed_credits": result.absorbed_credits,
    }
    prior = updated.get("settlement")
    if prior is not None and prior != recorded:
        raise ReliableDeliveryConflictError("the recorded settlement outcome changed")
    updated["settlement"] = recorded
    _write_envelope(operation, updated)
    operation.status = "succeeded"
    session.flush()
    return result


def provider_cost_reconciliation(session, *, operation_id):
    """Prove every Phase 12 call is either charged/delivering or absorbed."""
    _operation, billing = _bound_rows(session, operation_id)
    calls = session.execute(select(AIProviderCallUsage).where(
        AIProviderCallUsage.operation_id == operation_id,
    )).scalars().all()
    absorbed_ids = set()
    for row in session.execute(select(AIAbsorbedUsage).where(
        AIAbsorbedUsage.operation_id == operation_id,
    )).scalars():
        absorbed_ids.update(row.provider_call_ids_json or [])
    delivering_ids = {
        call.id for call in calls
        if billing.delivery_status == "delivered" and call.attempt_number == billing.delivered_attempt_number
    }
    unaccounted = sorted(call.id for call in calls if call.id not in absorbed_ids | delivering_ids)
    uncertain_charged = bool(
        int(billing.charged_credits or 0) > 0
        and any(call.usage_label != "reported" for call in calls if call.id in delivering_ids)
    )
    return {
        "operation_id": operation_id,
        "recorded_calls": len(calls),
        "delivering_call_ids": sorted(delivering_ids),
        "absorbed_call_ids": sorted(absorbed_ids),
        "unaccounted_call_ids": unaccounted,
        "uncertain_usage_charged": uncertain_charged,
        "reconciled": not unaccounted and not uncertain_charged,
    }


def _recovery_page(session, *, after, limit, lapsed_before=None, saved_results_only=False):
    query = select(AIBillingOperation).join(
        AIOperation,
        AIOperation.id == AIBillingOperation.operation_id,
    )
    if lapsed_before is None:
        query = query.where(or_(
            AIBillingOperation.state == "authorized",
            and_(
                AIBillingOperation.state == "expired",
                AIBillingOperation.delivery_status == "unsettled",
            ),
        ))
    else:
        query = query.where(
            AIBillingOperation.state == "authorized",
            AIBillingOperation.expires_at <= lapsed_before,
        )
    if saved_results_only:
        # Most live, unanswered operations have no result at all.  Filtering
        # them here avoids starvation while the keyset loop still skips any
        # legacy result that is not a reliable-delivery envelope.
        query = query.where(AIOperation.result_json.is_not(None))
    if after is not None:
        expires_at, operation_id = after
        query = query.where(or_(
            AIBillingOperation.expires_at > expires_at,
            and_(
                AIBillingOperation.expires_at == expires_at,
                AIBillingOperation.operation_id > operation_id,
            ),
        ))
    return session.execute(query.order_by(
        AIBillingOperation.expires_at,
        AIBillingOperation.operation_id,
    ).limit(limit)).scalars().all()


def _blocked_candidate(operation_id, exc):
    return {"operation_id": operation_id, "reason": str(exc)}


def recover_reliable_deliveries(session, *, limit=100):
    """Settle saved responses first, then expire only still-unanswered lapsed leases.

    The sweep is deterministic and idempotent.  It records no guessed customer
    identity: every row must pass its durable operation/billing bindings.
    """
    limit = max(1, min(int(limit), 1000))
    settled = []
    expired = []
    blocked = []
    envelope_operations = set()
    after = None
    attempted = 0
    while attempted < limit:
        candidates = _recovery_page(
            session,
            after=after,
            limit=min(limit, 100),
            saved_results_only=True,
        )
        if not candidates:
            break
        for billing in candidates:
            after = (billing.expires_at, billing.operation_id)
            try:
                with session.begin_nested():
                    operation, checked = _bound_rows(session, billing.operation_id)
                    if _envelope(operation) is None:
                        continue
                    envelope_operations.add(billing.operation_id)
                    result = settle_persisted_response(
                        session,
                        operation_id=billing.operation_id,
                        organization_id=checked.organization_id,
                        actor_user_id=checked.actor_user_id,
                    )
                    settled.append({"operation_id": billing.operation_id, **asdict(result)})
            except AIBillingError as exc:
                envelope_operations.add(billing.operation_id)
                blocked.append(_blocked_candidate(billing.operation_id, exc))
            attempted += 1
            if attempted >= limit:
                break

    now = _clock(session)
    after = None
    attempted = 0
    while attempted < limit:
        lapsed = _recovery_page(
            session,
            after=after,
            limit=min(limit, 100),
            lapsed_before=now,
        )
        if not lapsed:
            break
        for billing in lapsed:
            after = (billing.expires_at, billing.operation_id)
            if billing.operation_id in envelope_operations:
                continue
            try:
                with session.begin_nested():
                    operation, _checked = _bound_rows(session, billing.operation_id)
                    if _envelope(operation) is not None:
                        envelope_operations.add(billing.operation_id)
                        continue
                    result = expire_ai_operation(session, operation_id=billing.operation_id)
                    expired.append({"operation_id": billing.operation_id, **asdict(result)})
            except AIBillingError as exc:
                blocked.append(_blocked_candidate(billing.operation_id, exc))
            attempted += 1
            if attempted >= limit:
                break
    return {"settled": settled, "expired": expired, "blocked": blocked}
