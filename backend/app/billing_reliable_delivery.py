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

from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy import exc as sa_exc

from .billing_ai_operations import (
    AIBillingConflictError,
    AIBillingError,
    AIBillingIsolationError,
    AIBillingIsolationLevelError,
    AIBillingRetryError,
    AIBillingStateError,
    ReservationLapsedError,
    RunawayLimitError,
    _clock,
    _require_read_committed,
    check_provider_call,
    expire_ai_operation,
    record_provider_call,
    record_undelivered_operation,
    release_without_billable_usage,
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


# ---------------------------------------------------------------------------
# Worker-facing commands (I3). Every one checks the durable identity binding;
# the worker module calls Phase 12 only through these.
# ---------------------------------------------------------------------------

def _checked(session, operation_id, organization_id, actor_user_id, *, require_active_member=False):
    operation, billing = _bound_rows(session, operation_id)
    _authorize_identity(
        session, operation, billing, organization_id=organization_id, actor_user_id=actor_user_id,
        require_active_member=require_active_member,
    )
    return operation, billing


def delivery_billing_state(session, *, operation_id, organization_id, actor_user_id):
    """The Phase 12 facts the worker decides on (identity-checked; no write)."""
    operation, billing = _checked(session, operation_id, organization_id, actor_user_id)
    return {
        "state": billing.state,
        "delivery_status": billing.delivery_status,
        "expires_at": billing.expires_at,
        "lease_seconds": int(billing.lease_seconds),
        "persisted": _envelope(operation) is not None,
    }


def check_delivery_call(session, *, operation_id, organization_id, actor_user_id, **call):
    """Phase 12's pure pre-call check, for the operation's own identity."""
    _checked(session, operation_id, organization_id, actor_user_id)
    return check_provider_call(session, operation_id=operation_id, **call)


def record_delivery_call(session, *, operation_id, organization_id, actor_user_id, duration_ms=None,
                         status_code=None, operational_metadata=None, **call):
    """Record one provider call (Phase 12) and append its operational attempt (Phase 17) together."""
    _checked(session, operation_id, organization_id, actor_user_id)
    usage, _state = record_provider_call(session, operation_id=operation_id, **call)
    attempt, _replay = append_provider_attempt(
        session, operation_id=operation_id, organization_id=organization_id, actor_user_id=actor_user_id,
        provider_call_usage_id=usage.id, duration_ms=duration_ms, status_code=status_code,
        operational_metadata=operational_metadata,
    )
    return usage, attempt


def close_delivery_undelivered(session, *, operation_id, organization_id, actor_user_id):
    """No usable response reached the customer: Phase 12 releases and absorbs (never a charge)."""
    operation, _billing = _checked(session, operation_id, organization_id, actor_user_id)
    if _envelope(operation) is not None:
        raise AIBillingStateError("a persisted response is delivered; settle it instead")
    return record_undelivered_operation(session, operation_id=operation_id)


def close_delivery_without_usage(session, *, operation_id, organization_id, actor_user_id):
    """No provider-billable usage happened: Phase 12 releases the exact reservation."""
    operation, _billing = _checked(session, operation_id, organization_id, actor_user_id)
    if _envelope(operation) is not None:
        raise AIBillingStateError("a persisted response is delivered; settle it instead")
    return release_without_billable_usage(session, operation_id=operation_id)


def delivery_view(session, *, operation_id, organization_id, actor_user_id):
    """Customer read: the saved response (integrity-checked) and outcome, for an active member only."""
    operation, billing = _checked(session, operation_id, organization_id, actor_user_id,
                                  require_active_member=True)
    envelope = _envelope(operation)
    response = None
    if envelope is not None:
        if envelope.get("response_sha256") != _digest(envelope.get("response")):
            raise ReliableDeliveryConflictError("the persisted response failed its integrity check")
        response = envelope.get("response")
    return {
        "response": response,
        "persisted": envelope is not None,
        "settlement": None if envelope is None else envelope.get("settlement"),
        "billing_state": billing.state,
        "delivery_status": billing.delivery_status,
        "charged_credits": None if billing.delivery_status is None else int(billing.charged_credits or 0),
        "absorbed_credits": None if billing.delivery_status is None else int(billing.absorbed_credits or 0),
    }


def closed_or_lapsed_filter(operation_id_column, *, at):
    """A filter on ``operation_id_column``: the operation's reservation is closed or its lease lapsed."""
    return select(AIBillingOperation.operation_id).where(
        AIBillingOperation.operation_id == operation_id_column,
        or_(AIBillingOperation.state != "authorized", AIBillingOperation.expires_at <= at),
    ).exists()


# ---------------------------------------------------------------------------
# Bounded recovery sweep
# ---------------------------------------------------------------------------

# Errors that say the sweep itself cannot run correctly. They are never
# reported as a per-row block (O1): the sweep stops and the caller alerts.
SYSTEMIC_ERRORS = (AIBillingIsolationLevelError,)
# Row-level database refusals (a guard or constraint on one row) are isolated
# by the row's savepoint and reported as blocked, so one row never stops
# recovery of every other row (O2). Any other database error (a lost
# connection, for example) is systemic and propagates.
ROW_DATABASE_ERRORS = (sa_exc.IntegrityError, sa_exc.DataError)
# Lock contention with a live worker: retry the row on a later sweep.
TRANSIENT_PGCODES = {"40001", "40P01", "55P03"}


class RecoverySystemicError(ReliableDeliveryError):
    """The sweep stopped because the error is not about one row."""


def _row_error(exc):
    """The blocked reason for a row-level failure, or None when the error is systemic."""
    if isinstance(exc, SYSTEMIC_ERRORS):
        return None
    if isinstance(exc, AIBillingError):
        return str(exc)
    if isinstance(exc, ROW_DATABASE_ERRORS):
        return f"database refused the row: {type(exc.orig).__name__ if exc.orig is not None else type(exc).__name__}"
    if isinstance(exc, sa_exc.OperationalError) and getattr(exc.orig, "pgcode", None) in TRANSIENT_PGCODES:
        return "lock contention; retried by a later sweep"
    if isinstance(exc, (KeyError, TypeError, ValueError)):
        # Malformed data in this row (for example a non-integer delivered attempt in a saved envelope).
        # A genuine code defect also lands here, as every row blocked: the CLI then exits 3 and alerts.
        return f"malformed row data: {type(exc).__name__}"
    return None


def _cursor_key(billing):
    return (billing.expires_at, billing.operation_id)


def encode_cursor(key):
    if key is None:
        return None
    expires_at, operation_id = key
    return {"expires_at": expires_at.isoformat(), "operation_id": operation_id}


def decode_cursor(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value["expires_at"]), str(value["operation_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ReliableDeliveryError("the recovery cursor is malformed") from exc


def _recovery_page(session, *, after, limit, lapsed_before=None, saved_results_only=False, until=None):
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
    if until is not None:
        expires_at, operation_id = until
        query = query.where(or_(
            AIBillingOperation.expires_at < expires_at,
            and_(
                AIBillingOperation.expires_at == expires_at,
                AIBillingOperation.operation_id <= operation_id,
            ),
        ))
    return session.execute(query.order_by(
        AIBillingOperation.expires_at,
        AIBillingOperation.operation_id,
    ).limit(limit)).scalars().all()


def _blocked_candidate(operation_id, reason):
    return {"operation_id": operation_id, "reason": reason}


def _sweep_pass(session, *, cursor, limit, scan_limit, page, act, on_blocked):
    """Walk candidates from ``cursor`` (wrapping once), act on at most ``limit``, scan at most ``scan_limit``.

    Returns the cursor to resume from (None after a full cycle). Each action runs
    in its own savepoint: a row-level failure is rolled back and reported, and a
    systemic failure stops the pass.
    """
    attempted = scanned = 0
    segments = [(cursor, None)] if cursor is None else [(cursor, None), (None, cursor)]
    for start, until in segments:
        after = start
        while True:
            candidates = page(after=after, limit=min(scan_limit - scanned, 100), until=until)
            if not candidates:
                break
            for billing in candidates:
                key = _cursor_key(billing)
                after = key
                scanned += 1
                try:
                    with session.begin_nested():
                        acted = act(billing)
                except Exception as exc:  # classified below; systemic errors re-raise
                    reason = _row_error(exc)
                    if reason is None:
                        if isinstance(exc, AIBillingError):
                            raise RecoverySystemicError(str(exc)) from exc
                        raise
                    on_blocked(billing, reason)
                    acted = True
                if acted:
                    attempted += 1
                if attempted >= limit or scanned >= scan_limit:
                    return key
    return None


def recover_reliable_deliveries(session, *, limit=100, scan_limit=1000, cursors=None):
    """Settle saved responses first, then expire only still-unanswered lapsed leases.

    The sweep is deterministic, idempotent and bounded: each pass acts on at most
    ``limit`` rows and scans at most ``scan_limit``, resuming from ``cursors``
    (the previous report's ``cursors``) and wrapping around, so rows ahead of a
    candidate (finished, in-flight, legacy or permanently blocked) never starve
    it. It records no guessed customer identity: every row must pass its durable
    operation/billing bindings. A systemic error stops the sweep (O1/O2).
    """
    _require_read_committed(session)
    limit = max(1, min(int(limit), 1000))
    scan_limit = max(limit, min(int(scan_limit), 10_000))
    cursors = cursors or {}
    settled = []
    expired = []
    blocked = []
    envelope_operations = set()

    def on_blocked(billing, reason):
        envelope_operations.add(billing.operation_id)
        blocked.append(_blocked_candidate(billing.operation_id, reason))

    def settle_row(billing):
        operation, checked = _bound_rows(session, billing.operation_id)
        if _envelope(operation) is None:
            return False
        envelope_operations.add(billing.operation_id)
        result = settle_persisted_response(
            session,
            operation_id=billing.operation_id,
            organization_id=checked.organization_id,
            actor_user_id=checked.actor_user_id,
        )
        settled.append({"operation_id": billing.operation_id, **asdict(result)})
        return True

    def settle_page(*, after, limit, until):
        return _recovery_page(session, after=after, limit=limit, until=until, saved_results_only=True)

    settle_cursor = _sweep_pass(
        session, cursor=decode_cursor(cursors.get("settle")), limit=limit, scan_limit=scan_limit,
        page=settle_page, act=settle_row, on_blocked=on_blocked,
    )

    now = _clock(session)

    def expire_row(billing):
        if billing.operation_id in envelope_operations:
            return False
        operation, _checked_row = _bound_rows(session, billing.operation_id)
        if _envelope(operation) is not None:
            envelope_operations.add(billing.operation_id)
            return False
        result = expire_ai_operation(session, operation_id=billing.operation_id)
        expired.append({"operation_id": billing.operation_id, **asdict(result)})
        return True

    def expire_page(*, after, limit, until):
        return _recovery_page(session, after=after, limit=limit, until=until, lapsed_before=now)

    expire_cursor = _sweep_pass(
        session, cursor=decode_cursor(cursors.get("expire")), limit=limit, scan_limit=scan_limit,
        page=expire_page, act=expire_row, on_blocked=on_blocked,
    )
    return {
        "settled": settled,
        "expired": expired,
        "blocked": blocked,
        "cursors": {"settle": encode_cursor(settle_cursor), "expire": encode_cursor(expire_cursor)},
    }
