"""Inactive Phase 6 free and subscription recurring-credit allocation commands.

No live route, webhook, scheduler, or worker imports this module. Callers own
the transaction. The commands bind an approved entitlement definition and,
for subscriptions, an immutable paid financial line to one expiring Phase 3
lot without committing or contacting a provider.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .billing_entitlements import (
    EntitlementInvariantError,
    fund_credit_period,
    monthly_period_bounds,
    new_credit_period,
    validate_definition_payloads,
)
from .billing_ledger import append_entry, lock_billing_account
from .billing_outbox import (
    BillingOutboxInvariantError,
    DomainEventConflictError,
    record_domain_event,
)
from .models import (
    BillingSubscription,
    CreditLedgerEntry,
    CreditLot,
    CreditPeriod,
    EntitlementDefinition,
    EntitlementInstance,
    FinancialLine,
    FinancialTransaction,
    IdempotencyRegistry,
)
from .models_billing_phase6 import RecurringCreditAllocation


ALLOCATION_NAMESPACE = "recurring_credit_allocation"
EXPIRATION_NAMESPACE = "recurring_credit_expiration"


class RecurringAllocationError(ValueError):
    """Raised when recurring funding violates the approved Phase 6 contract."""


class RecurringAllocationConflictError(RecurringAllocationError):
    """Raised when a canonical allocation key is reused for different facts."""


class RecurringAllocationRetryError(RecurringAllocationError):
    """Raised when the transaction must be retried after a concurrent write."""


def _utc(value, field):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise RecurringAllocationError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _stored_utc(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _text(value, field, maximum):
    if not isinstance(value, str) or not value.strip():
        raise RecurringAllocationError(f"{field} must be a nonempty string")
    value = value.strip()
    if len(value) > maximum:
        raise RecurringAllocationError(f"{field} is too long")
    return value


def _timestamp_key(value):
    return _utc(value, "period_start").strftime("%Y-%m-%dT%H:%M:%SZ")


def _fingerprint(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _required_deliveries(delivery_obligations):
    if not isinstance(delivery_obligations, (list, tuple)) or not delivery_obligations:
        raise RecurringAllocationError(
            "at least one delivery obligation is required for the Phase 6 event"
        )
    return delivery_obligations


def _record_event(session, *, event, delivery_obligations):
    try:
        return record_domain_event(session, event, delivery_obligations)
    except DomainEventConflictError as exc:
        raise RecurringAllocationConflictError(str(exc)) from exc
    except BillingOutboxInvariantError as exc:
        raise RecurringAllocationError(str(exc)) from exc


def _funded_event(account_id, allocation_id, period, definition_id, line_id, occurred_at):
    references = [allocation_id, period.id, definition_id]
    if line_id:
        references.append(line_id)
    return {
        "billing_account_id": account_id,
        "event_key": f"credit_period_funded:{period.id}",
        "event_type": "credit_period_funded",
        "aggregate_type": "credit_period",
        "aggregate_id": period.id,
        "occurred_at": _stored_utc(occurred_at),
        "reference_ids": references,
    }


def _expired_event(account_id, allocation_id, period, occurred_at):
    return {
        "billing_account_id": account_id,
        "event_key": f"credits_expired:{period.id}",
        "event_type": "credits_expired",
        "aggregate_type": "credit_period",
        "aggregate_id": period.id,
        "occurred_at": _stored_utc(occurred_at),
        "reference_ids": [allocation_id, period.id, period.funded_lot_id],
    }


def _allocation_key(account_id, subscription, definition, kind, period_index, starts_at):
    start = _timestamp_key(starts_at)
    if kind == "free":
        return f"period:free:{account_id}:{start}"
    if kind == "annual_monthly":
        return f"period:annual:{subscription.id}:{period_index}:{start}"
    plan_version = f"{definition.key}@{definition.version}"
    return f"period:subscription:{subscription.id}:{start}:{plan_version}"


def _claim_registry(session, namespace, key, fingerprint, claimed_at):
    values = {
        "id": str(uuid.uuid4()),
        "namespace": namespace,
        "key": key,
        "request_fingerprint": fingerprint,
        "state": "claimed",
        "claimed_at": claimed_at,
    }
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        statement = postgresql_insert(IdempotencyRegistry).values(**values)
    elif dialect == "sqlite":
        statement = sqlite_insert(IdempotencyRegistry).values(**values)
    else:
        raise RecurringAllocationError(f"unsupported database dialect: {dialect}")
    inserted_id = session.execute(
        statement.on_conflict_do_nothing(
            index_elements=[IdempotencyRegistry.namespace, IdempotencyRegistry.key],
        ).returning(IdempotencyRegistry.id)
    ).scalar_one_or_none()
    if inserted_id is not None:
        return session.get(IdempotencyRegistry, inserted_id), True
    registry = session.execute(
        select(IdempotencyRegistry)
        .where(
            IdempotencyRegistry.namespace == namespace,
            IdempotencyRegistry.key == key,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if registry is None:
        raise RecurringAllocationRetryError(
            "idempotency identity raced under the current snapshot; retry the transaction"
        )
    if registry.request_fingerprint != fingerprint:
        raise RecurringAllocationConflictError(
            "recurring allocation identity was reused with different facts"
        )
    return registry, False


def _complete_registry_if_claimed(
    session, registry, *, completed_at, result_type, result_id,
):
    """Complete a claim once without rewriting a trigger-completed result."""
    session.execute(
        update(IdempotencyRegistry)
        .where(
            IdempotencyRegistry.id == registry.id,
            IdempotencyRegistry.state == "claimed",
        )
        .values(
            state="completed",
            completed_at=completed_at,
            result_type=result_type,
            result_id=result_id,
            last_error_code=None,
        )
        .execution_options(synchronize_session=False)
    )
    session.refresh(registry)
    if (
        registry.state != "completed"
        or registry.result_type != result_type
        or registry.result_id != result_id
    ):
        raise RecurringAllocationConflictError(
            "idempotency completion does not match the recurring result"
        )


def _validated_definition(session, instance, period_start, expected_kind):
    definition = session.execute(
        select(EntitlementDefinition)
        .where(EntitlementDefinition.id == instance.entitlement_definition_id)
    ).scalar_one()
    validate_definition_payloads(
        definition.capability_json, definition.funding_policy_json,
    )
    if definition.approved_at is None or not definition.approval_evidence_reference:
        raise RecurringAllocationError("entitlement definition is not approved")
    effective_at = _stored_utc(definition.effective_at) if definition.effective_at else None
    retired_at = _stored_utc(definition.retired_at) if definition.retired_at else None
    if effective_at is None or effective_at > period_start:
        raise RecurringAllocationError("entitlement definition is not effective for the period")
    if retired_at is not None and retired_at <= period_start:
        raise RecurringAllocationError("entitlement definition is retired for the period")
    if definition.funding_policy_json["period_kind"] != expected_kind:
        raise RecurringAllocationError("entitlement funding kind does not match the period")
    amount = definition.funding_policy_json["credit_amount"]
    if amount <= 0:
        raise RecurringAllocationError("recurring credit amount must be positive")
    return definition, amount


def _validated_paid_line(
    session, *, line_id, account, instance, subscription, kind,
    period_start, period_end, opened_at,
):
    if line_id is None:
        raise RecurringAllocationError("subscription allocation requires a paid financial line")
    row = session.execute(
        select(FinancialLine, FinancialTransaction)
        .join(
            FinancialTransaction,
            FinancialTransaction.id == FinancialLine.financial_transaction_id,
        )
        .where(FinancialLine.id == line_id)
    ).one_or_none()
    if row is None:
        raise RecurringAllocationError("paid financial line does not exist")
    line, transaction = row
    effective_at = _stored_utc(transaction.effective_at)
    if (
        transaction.billing_account_id != account.id
        or transaction.kind != "payment"
        or transaction.currency != account.currency
        or transaction.principal_minor <= 0
        or line.line_kind != "subscription"
        or line.principal_minor <= 0
        or line.currency != account.currency
        or line.subscription_id != subscription.id
        or line.entitlement_instance_id != instance.id
        or effective_at > opened_at
    ):
        raise RecurringAllocationError(
            "financial line is not paid subscription evidence for this account and entitlement"
        )
    term_start = _stored_utc(subscription.term_starts_at)
    if kind == "monthly_subscription" and not (period_start <= effective_at < period_end):
        raise RecurringAllocationError("monthly allocation requires payment in that period")
    if kind == "annual_monthly" and not (term_start <= effective_at < _stored_utc(subscription.term_ends_at)):
        raise RecurringAllocationError("annual allocation requires payment for the current term")
    return line


def allocate_recurring_credits(
    session, *, billing_account_id, entitlement_instance_id, period_index,
    opened_at, delivery_obligations, financial_line_id=None, actor_type, actor_id,
):
    """Atomically create and fund one open free or subscription credit period."""
    billing_account_id = _text(billing_account_id, "billing_account_id", 36)
    entitlement_instance_id = _text(
        entitlement_instance_id, "entitlement_instance_id", 36,
    )
    actor_type = _text(actor_type, "actor_type", 40)
    actor_id = _text(actor_id, "actor_id", 255)
    delivery_obligations = _required_deliveries(delivery_obligations)
    if isinstance(period_index, bool) or not isinstance(period_index, int) or period_index < 0:
        raise RecurringAllocationError("period_index must be a nonnegative integer")
    opened_at = _utc(opened_at, "opened_at")

    try:
        account = lock_billing_account(session, billing_account_id)
    except Exception as exc:
        raise RecurringAllocationError(str(exc)) from exc
    instance = session.execute(
        select(EntitlementInstance)
        .where(EntitlementInstance.id == entitlement_instance_id)
        .with_for_update()
    ).scalar_one_or_none()
    if instance is None or instance.billing_account_id != account.id:
        raise RecurringAllocationError("entitlement does not belong to the billing account")
    if instance.state != "active":
        raise RecurringAllocationError("recurring allocation requires an active entitlement")

    subscription = None
    if instance.source_type == "free":
        kind = "free"
        anchor_at = _stored_utc(account.account_anchor_at)
        if financial_line_id is not None:
            raise RecurringAllocationError("free allocation cannot use financial evidence")
    elif instance.source_type == "subscription" and instance.subscription_id:
        subscription = session.execute(
            select(BillingSubscription)
            .where(BillingSubscription.id == instance.subscription_id)
            .with_for_update()
        ).scalar_one()
        if subscription.billing_account_id != account.id:
            raise RecurringAllocationError("subscription does not belong to the billing account")
        kind = {
            "month": "monthly_subscription",
            "year": "annual_monthly",
        }.get(subscription.interval)
        if kind is None:
            raise RecurringAllocationError("custom subscription allocation is not Phase 6")
        if subscription.current_entitlement_definition_id != instance.entitlement_definition_id:
            raise RecurringAllocationError("subscription and entitlement definitions differ")
        anchor_at = _stored_utc(subscription.anchor_at)
    else:
        raise RecurringAllocationError("entitlement source is outside Phase 6")

    period_start, period_end = monthly_period_bounds(anchor_at, period_index)
    if not (period_start <= opened_at < period_end):
        raise RecurringAllocationError("credit period is not open at the requested time")
    instance_start = _stored_utc(instance.starts_at)
    instance_end = _stored_utc(instance.ends_at) if instance.ends_at else None
    if instance_start > period_start or (instance_end is not None and instance_end < period_end):
        raise RecurringAllocationError("credit period exceeds the entitlement interval")

    definition, amount = _validated_definition(session, instance, period_start, kind)
    if subscription is not None:
        if (
            period_start < _stored_utc(subscription.term_starts_at)
            or period_end > _stored_utc(subscription.term_ends_at)
        ):
            raise RecurringAllocationError("credit period exceeds the paid subscription term")
        line = _validated_paid_line(
            session,
            line_id=financial_line_id,
            account=account,
            instance=instance,
            subscription=subscription,
            kind=kind,
            period_start=period_start,
            period_end=period_end,
            opened_at=opened_at,
        )
        financial_line_id = line.id

    key = _allocation_key(
        account.id, subscription, definition, kind, period_index, period_start,
    )
    fingerprint = _fingerprint({
        "billing_account_id": account.id,
        "entitlement_instance_id": instance.id,
        "entitlement_definition_id": definition.id,
        "subscription_id": subscription.id if subscription else None,
        "financial_line_id": financial_line_id,
        "period_kind": kind,
        "period_index": period_index,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "credit_amount": amount,
    })
    registry, inserted = _claim_registry(
        session, ALLOCATION_NAMESPACE, key, fingerprint, opened_at,
    )
    if not inserted:
        allocation = session.execute(
            select(RecurringCreditAllocation)
            .where(RecurringCreditAllocation.idempotency_registry_id == registry.id)
        ).scalar_one_or_none()
        if registry.state == "completed" and allocation is not None:
            period = session.get(CreditPeriod, allocation.credit_period_id)
            lot = session.get(CreditLot, period.funded_lot_id)
            event, _messages, _state = _record_event(
                session,
                event=_funded_event(
                    account.id, allocation.id, period,
                    allocation.entitlement_definition_id,
                    allocation.financial_line_id, registry.claimed_at,
                ),
                delivery_obligations=delivery_obligations,
            )
            if event.id != allocation.domain_event_id:
                raise RecurringAllocationConflictError(
                    "recurring allocation is bound to another domain event"
                )
            return allocation, period, lot, "duplicate"
        raise RecurringAllocationRetryError("recurring allocation is already in progress")

    period = new_credit_period(
        billing_account_id=account.id,
        entitlement_instance_id=instance.id,
        subscription_id=subscription.id if subscription else None,
        kind=kind,
        period_index=period_index,
        anchor_at=anchor_at,
        planned_allocation_amount=amount,
    )
    session.add(period)
    session.flush()
    allocation_id = str(uuid.uuid4())
    domain_event, _messages, event_state = _record_event(
        session,
        event=_funded_event(
            account.id, allocation_id, period, definition.id,
            financial_line_id, registry.claimed_at,
        ),
        delivery_obligations=delivery_obligations,
    )
    if event_state != "inserted":
        raise RecurringAllocationConflictError(
            "new recurring allocation reused an existing domain event"
        )
    allocation = RecurringCreditAllocation(
        id=allocation_id,
        billing_account_id=account.id,
        credit_period_id=period.id,
        entitlement_instance_id=instance.id,
        entitlement_definition_id=definition.id,
        subscription_id=subscription.id if subscription else None,
        financial_line_id=financial_line_id,
        idempotency_registry_id=registry.id,
        domain_event_id=domain_event.id,
        allocation_key=key,
        request_fingerprint=fingerprint,
        period_kind=kind,
        period_index=period_index,
        period_starts_at=period_start,
        period_ends_at=period_end,
        credit_amount=amount,
    )
    session.add(allocation)
    session.flush()
    try:
        lot = fund_credit_period(
            session,
            period.id,
            registry,
            actor_type=actor_type,
            actor_id=actor_id,
            evidence_json={
                "recurring_credit_allocation_id": allocation.id,
                "financial_line_id": financial_line_id,
            },
        )
    except EntitlementInvariantError as exc:
        raise RecurringAllocationError(str(exc)) from exc
    _complete_registry_if_claimed(
        session, registry, completed_at=opened_at,
        result_type="credit_period", result_id=period.id,
    )
    session.flush()
    return allocation, period, lot, "inserted"


def expire_recurring_credits(
    session, *, credit_period_id, expired_at, delivery_obligations,
    actor_type, actor_id,
):
    """Expire the unspent value of one ended Phase 6 period without rollover."""
    credit_period_id = _text(credit_period_id, "credit_period_id", 36)
    actor_type = _text(actor_type, "actor_type", 40)
    actor_id = _text(actor_id, "actor_id", 255)
    delivery_obligations = _required_deliveries(delivery_obligations)
    expired_at = _utc(expired_at, "expired_at")
    account_id = session.execute(
        select(CreditPeriod.billing_account_id)
        .where(CreditPeriod.id == credit_period_id)
    ).scalar_one_or_none()
    if account_id is None:
        raise RecurringAllocationError("credit period does not exist")
    lock_billing_account(session, account_id)
    period = session.execute(
        select(CreditPeriod)
        .where(CreditPeriod.id == credit_period_id)
        .with_for_update()
    ).scalar_one()
    allocation = session.execute(
        select(RecurringCreditAllocation)
        .where(RecurringCreditAllocation.credit_period_id == period.id)
        .with_for_update()
    ).scalar_one_or_none()
    if allocation is None:
        raise RecurringAllocationError("credit period is not a Phase 6 allocation")
    if expired_at < _stored_utc(period.ends_at):
        raise RecurringAllocationError("credit period has not ended")

    fingerprint = _fingerprint({
        "credit_period_id": period.id,
        "lot_id": period.funded_lot_id,
        "period_end": _stored_utc(period.ends_at).isoformat(),
    })
    registry, inserted = _claim_registry(
        session, EXPIRATION_NAMESPACE, allocation.allocation_key,
        fingerprint, expired_at,
    )
    if not inserted:
        if registry.state == "completed" and registry.result_id == period.id:
            _record_event(
                session,
                event=_expired_event(
                    period.billing_account_id, allocation.id, period,
                    registry.claimed_at,
                ),
                delivery_obligations=delivery_obligations,
            )
            return period, "duplicate"
        raise RecurringAllocationRetryError("recurring expiration is already in progress")
    if period.state == "expired":
        raise RecurringAllocationConflictError("period was expired by another identity")
    if period.state != "funded" or not period.funded_lot_id:
        raise RecurringAllocationError("only a funded recurring period can expire")

    available, held = session.execute(
        select(
            func.coalesce(func.sum(CreditLedgerEntry.available_delta), 0),
            func.coalesce(func.sum(CreditLedgerEntry.held_delta), 0),
        ).where(CreditLedgerEntry.lot_id == period.funded_lot_id)
    ).one()
    available = int(available or 0)
    held = int(held or 0)
    entries = session.execute(
        select(CreditLedgerEntry)
        .where(CreditLedgerEntry.lot_id == period.funded_lot_id)
        .order_by(CreditLedgerEntry.created_at, CreditLedgerEntry.id)
    ).scalars().all()
    consumed_by_source = {}
    for entry in entries:
        if entry.related_entry_id and entry.held_delta < 0:
            consumed_by_source[entry.related_entry_id] = (
                consumed_by_source.get(entry.related_entry_id, 0)
                - int(entry.held_delta)
            )
    held_sources = []
    for entry in entries:
        if entry.entry_type not in {"reservation", "dispute_hold"}:
            continue
        remaining = int(entry.held_delta) - consumed_by_source.get(entry.id, 0)
        if remaining > 0:
            held_sources.append((entry, remaining))
    if sum(amount for _entry, amount in held_sources) != held:
        raise RecurringAllocationError("held recurring provenance does not reconcile")

    domain_event, _messages, event_state = _record_event(
        session,
        event=_expired_event(
            period.billing_account_id, allocation.id, period,
            registry.claimed_at,
        ),
        delivery_obligations=delivery_obligations,
    )
    if event_state != "inserted":
        raise RecurringAllocationConflictError(
            "new recurring expiration reused an existing domain event"
        )
    expiration_parts = held_sources
    if available and not expiration_parts:
        expiration_parts = [(None, 0)]
    for part_index, (source_entry, held_amount) in enumerate(expiration_parts):
        entry_registry = registry
        if part_index:
            child_key = f"{allocation.allocation_key}:held:{source_entry.id}"
            child_fingerprint = _fingerprint({
                "credit_period_id": period.id,
                "lot_id": period.funded_lot_id,
                "period_end": _stored_utc(period.ends_at).isoformat(),
                "related_entry_id": source_entry.id,
                "held_amount": held_amount,
            })
            entry_registry, child_inserted = _claim_registry(
                session, EXPIRATION_NAMESPACE, child_key,
                child_fingerprint, expired_at,
            )
            if not child_inserted:
                raise RecurringAllocationRetryError(
                    "held recurring expiration is already in progress"
                )
        append_entry(session, CreditLedgerEntry(
            id=str(uuid.uuid4()),
            billing_account_id=period.billing_account_id,
            lot_id=period.funded_lot_id,
            entry_type="expiration",
            available_delta=-available if part_index == 0 else 0,
            held_delta=-held_amount,
            related_entry_id=source_entry.id if source_entry else None,
            idempotency_registry_id=entry_registry.id,
            effective_at=period.ends_at,
            actor_type=actor_type,
            actor_id=actor_id,
            reason_code="recurring_period_expired",
            evidence_json={
                "recurring_credit_allocation_id": allocation.id,
                "held_source_entry_id": source_entry.id if source_entry else None,
            },
        ))
        if entry_registry is not registry:
            _complete_registry_if_claimed(
                session, entry_registry, completed_at=expired_at,
                result_type="credit_period", result_id=period.id,
            )
    period.state = "expired"
    _complete_registry_if_claimed(
        session, registry, completed_at=expired_at,
        result_type="credit_period", result_id=period.id,
    )
    if domain_event.aggregate_id != period.id:
        raise RecurringAllocationConflictError(
            "recurring expiration event aggregate does not match the period"
        )
    session.flush()
    return period, "expired"
