"""Inactive Phase 7 subscription-change, schedule, and proration commands.

No route, webhook, scheduler, worker, or provider integration imports this
module. Every function uses the caller's transaction and never commits.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError

from .billing_allocations import (
    RecurringAllocationError,
    _claim_registry,
    _complete_registry_if_claimed,
    allocate_recurring_credits,
)
from .billing_entitlements import add_calendar_months, append_entitlement_transition, monthly_period_bounds
from .billing_ledger import append_entry, lock_billing_account
from .billing_outbox import BillingOutboxInvariantError, DomainEventConflictError, record_domain_event
from .models import (
    BillingSubscription,
    CreditLedgerEntry,
    CreditLot,
    EntitlementDefinition,
    EntitlementInstance,
    FinancialLine,
    FinancialTransaction,
    IdempotencyRegistry,
    PlanChangeEvent,
    ScheduledPlanChange,
    UpgradeCreditAllocation,
)
from .models_billing_phase6 import RecurringCreditAllocation


SCHEDULE_NAMESPACE = "plan_change_schedule"
TRANSITION_NAMESPACE = "plan_change_transition"
UPGRADE_NAMESPACE = "upgrade_proration"
ENTITLEMENT_NAMESPACE = "phase7_entitlement_transition"
ACTIVE_SCHEDULE_STATES = ("pending", "awaiting_renewal_payment")


class PlanChangeError(ValueError):
    pass


class PlanChangeConflictError(PlanChangeError):
    pass


class PlanChangeRetryError(PlanChangeError):
    pass


def _utc(value, field):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PlanChangeError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _stored_utc(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _whole_seconds(delta):
    """Floor a timedelta to deterministic whole seconds without float conversion."""
    return delta.days * 86400 + delta.seconds


def _text(value, field, maximum):
    if not isinstance(value, str) or not value.strip():
        raise PlanChangeError(f"{field} must be a nonempty string")
    value = value.strip()
    if len(value) > maximum:
        raise PlanChangeError(f"{field} is too long")
    return value


def _deliveries(value):
    if not isinstance(value, (list, tuple)) or not value:
        raise PlanChangeError("at least one delivery obligation is required")
    return value


def _fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def _event(session, envelope, obligations):
    try:
        return record_domain_event(session, envelope, _deliveries(obligations))
    except DomainEventConflictError as exc:
        raise PlanChangeConflictError(str(exc)) from exc
    except BillingOutboxInvariantError as exc:
        raise PlanChangeError(str(exc)) from exc


def _claim(session, namespace, key, fingerprint, occurred_at):
    try:
        return _claim_registry(session, namespace, key, fingerprint, occurred_at)
    except DBAPIError:
        # Preserve PostgreSQL serialization/deadlock SQLSTATEs so callers can
        # apply the transaction retry policy required by D14.
        raise
    except Exception as exc:
        name = type(exc).__name__
        if "Conflict" in name:
            raise PlanChangeConflictError(str(exc)) from exc
        if "Retry" in name:
            raise PlanChangeRetryError(str(exc)) from exc
        raise PlanChangeError(str(exc)) from exc


def _definition_amount(definition):
    policy = definition.funding_policy_json
    if not isinstance(policy, dict):
        raise PlanChangeError("entitlement funding policy must be an object")
    amount = policy.get("credit_amount")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise PlanChangeError("entitlement credit amount must be a nonnegative integer")
    return amount


def _lock_subscription(session, account_id, subscription_id):
    lock_billing_account(session, account_id)
    subscription = session.execute(
        select(BillingSubscription)
        .where(BillingSubscription.id == subscription_id)
        .with_for_update()
    ).scalar_one_or_none()
    if subscription is None or subscription.billing_account_id != account_id:
        raise PlanChangeError("subscription does not belong to the billing account")
    return subscription


def _active_schedule(session, subscription_id):
    return session.execute(
        select(ScheduledPlanChange)
        .where(
            ScheduledPlanChange.subscription_id == subscription_id,
            ScheduledPlanChange.state.in_(ACTIVE_SCHEDULE_STATES),
        )
        .order_by(ScheduledPlanChange.created_at, ScheduledPlanChange.id)
        .with_for_update()
    ).scalar_one_or_none()


def schedule_plan_change(
    session, *, billing_account_id, subscription_id, client_command_id,
    kind, target_entitlement_definition_id, requested_at, effective_at,
    compatible_supersede, actor_type, actor_id, delivery_obligations,
):
    """Schedule a downgrade/cancellation with one-active-record precedence."""
    account_id = _text(billing_account_id, "billing_account_id", 36)
    subscription_id = _text(subscription_id, "subscription_id", 36)
    command_id = _text(client_command_id, "client_command_id", 255)
    actor_type = _text(actor_type, "actor_type", 32)
    actor_id = _text(actor_id, "actor_id", 255)
    requested_at = _utc(requested_at, "requested_at")
    effective_at = _utc(effective_at, "effective_at")
    if requested_at > effective_at:
        raise PlanChangeError("requested_at cannot follow the scheduled effective time")
    obligations = _deliveries(delivery_obligations)
    if kind not in {"downgrade", "cancellation"}:
        raise PlanChangeError("kind must be downgrade or cancellation")
    if kind == "downgrade":
        target_id = _text(target_entitlement_definition_id, "target_entitlement_definition_id", 36)
    elif target_entitlement_definition_id is not None:
        raise PlanChangeError("cancellation cannot name a target definition")
    else:
        target_id = None

    subscription = _lock_subscription(session, account_id, subscription_id)
    if subscription.state in {"cancelled", "expired"}:
        raise PlanChangeError("terminal subscription cannot accept a schedule")
    rule = "period_end" if kind == "cancellation" else {
        "month": "next_monthly_renewal", "year": "next_annual_renewal",
    }.get(subscription.interval)
    if rule is None:
        raise PlanChangeError("custom subscription schedule is outside Phase 7")
    if effective_at != _stored_utc(subscription.term_ends_at):
        raise PlanChangeError("scheduled change must use the current paid term end")
    if target_id:
        target = session.get(EntitlementDefinition, target_id)
        current = session.get(EntitlementDefinition, subscription.current_entitlement_definition_id)
        if target is None or target.approved_at is None:
            raise PlanChangeError("target entitlement definition must be approved")
        if current is None or _definition_amount(target) >= _definition_amount(current):
            raise PlanChangeError("scheduled downgrade target must have a lower recurring amount")

    key = f"schedule:{subscription.id}:{command_id}"
    fingerprint = _fingerprint({
        "account": account_id, "subscription": subscription.id, "kind": kind,
        "target": target_id, "rule": rule, "requested_at": requested_at.isoformat(),
        "effective_at": effective_at.isoformat(),
    })
    registry, inserted = _claim(session, SCHEDULE_NAMESPACE, key, fingerprint, requested_at)
    if not inserted:
        existing = session.execute(
            select(ScheduledPlanChange).where(ScheduledPlanChange.idempotency_registry_id == registry.id)
        ).scalar_one_or_none()
        if registry.state != "completed" or existing is None:
            raise PlanChangeRetryError("schedule command is already in progress")
        event, _messages, _state = _event(session, {
            "billing_account_id": account_id,
            "event_key": f"plan_change_scheduled:{existing.id}",
            "event_type": "plan_change_scheduled", "aggregate_type": "scheduled_plan_change",
            "aggregate_id": existing.id, "occurred_at": _stored_utc(registry.claimed_at),
            "reference_ids": [existing.id, subscription.id] + ([target_id] if target_id else []),
        }, obligations)
        if event.id != existing.domain_event_id:
            raise PlanChangeConflictError("schedule replay is bound to another event")
        return existing, "duplicate"

    active = _active_schedule(session, subscription.id)
    if active is not None and not (kind == "cancellation" or compatible_supersede is True):
        raise PlanChangeConflictError("an active schedule exists and compatible supersession was not confirmed")
    change_id = str(uuid.uuid4())
    domain_event, _messages, state = _event(session, {
        "billing_account_id": account_id, "event_key": f"plan_change_scheduled:{change_id}",
        "event_type": "plan_change_scheduled", "aggregate_type": "scheduled_plan_change",
        "aggregate_id": change_id, "occurred_at": requested_at,
        "reference_ids": [change_id, subscription.id] + ([target_id] if target_id else []),
    }, obligations)
    if state != "inserted":
        raise PlanChangeConflictError("new schedule reused an existing domain event")
    if active is not None:
        _transition_schedule(
            session, change=active, to_state="superseded", transition="superseded_by_command",
            effective_at=requested_at, actor_type=actor_type, actor_id=actor_id,
            evidence={"superseding_change_id": change_id}, delivery_obligations=obligations,
        )
    change = ScheduledPlanChange(
        id=change_id, billing_account_id=account_id, subscription_id=subscription.id,
        target_entitlement_definition_id=target_id, kind=kind, effective_rule=rule,
        effective_at=effective_at, state="pending", command_key=key,
        request_fingerprint=fingerprint, idempotency_registry_id=registry.id,
        domain_event_id=domain_event.id, supersedes_change_id=active.id if active else None,
    )
    session.add(change)
    session.flush()
    if kind == "cancellation":
        subscription.state = "cancel_at_period_end"
    _complete_registry_if_claimed(
        session, registry, completed_at=requested_at,
        result_type="scheduled_plan_change", result_id=change.id,
    )
    session.flush()
    return change, "inserted"


def _transition_schedule(
    session, *, change, to_state, transition, effective_at, actor_type, actor_id,
    evidence, delivery_obligations,
):
    allowed = {
        "pending": {"awaiting_renewal_payment", "applied", "superseded", "cancelled", "blocked_terminal_failure"},
        "awaiting_renewal_payment": {"applied", "superseded", "cancelled", "blocked_terminal_failure"},
    }
    if to_state not in allowed.get(change.state, set()):
        raise PlanChangeError(f"invalid schedule transition: {change.state} -> {to_state}")
    occurred_at = _utc(effective_at, "effective_at")
    key = f"plan-change-transition:{change.id}:{to_state}"
    fingerprint = _fingerprint({
        "change": change.id, "from": change.state, "to": to_state,
        "transition": transition, "effective_at": occurred_at.isoformat(), "evidence": evidence,
    })
    registry, inserted = _claim(session, TRANSITION_NAMESPACE, key, fingerprint, occurred_at)
    event_type = (
        "plan_change_applied" if to_state == "applied" else
        "plan_change_scheduled" if to_state == "awaiting_renewal_payment" else
        "plan_change_superseded"
    )
    domain_event, _messages, event_state = _event(session, {
        "billing_account_id": change.billing_account_id,
        "event_key": f"{event_type}:{change.id}:{to_state}",
        "event_type": event_type, "aggregate_type": "scheduled_plan_change",
        "aggregate_id": change.id, "occurred_at": occurred_at,
        "reference_ids": [change.id, change.subscription_id],
    }, delivery_obligations)
    if not inserted:
        existing = session.execute(
            select(PlanChangeEvent).where(PlanChangeEvent.idempotency_registry_id == registry.id)
        ).scalar_one_or_none()
        if registry.state == "completed" and existing is not None and existing.domain_event_id == domain_event.id:
            return existing, "duplicate"
        raise PlanChangeRetryError("schedule transition is already in progress")
    if event_state != "inserted":
        raise PlanChangeConflictError("new schedule transition reused an existing domain event")
    item = PlanChangeEvent(
        id=str(uuid.uuid4()), scheduled_change_id=change.id, from_state=change.state,
        to_state=to_state, transition=transition, effective_at=occurred_at,
        actor_type=actor_type, actor_id=actor_id, evidence_json=evidence,
        idempotency_registry_id=registry.id, domain_event_id=domain_event.id,
    )
    session.add(item)
    session.flush()
    session.refresh(change)
    if change.state != to_state:
        change.state = to_state
        change.last_event_id = item.id
        session.flush()
    _complete_registry_if_claimed(
        session, registry, completed_at=occurred_at,
        result_type="plan_change_event", result_id=item.id,
    )
    session.flush()
    return item, "inserted"


def _revalidate_transition_replay(session, change, delivery_obligations):
    """Revalidate D12 delivery facts for a completed schedule transition."""
    item = session.get(PlanChangeEvent, change.last_event_id)
    if item is None or item.scheduled_change_id != change.id or item.to_state != change.state:
        raise PlanChangeConflictError("schedule projection lacks its transition evidence")
    event_type = (
        "plan_change_applied" if item.to_state == "applied" else
        "plan_change_scheduled" if item.to_state == "awaiting_renewal_payment" else
        "plan_change_superseded"
    )
    domain_event, _messages, _state = _event(session, {
        "billing_account_id": change.billing_account_id,
        "event_key": f"{event_type}:{change.id}:{item.to_state}",
        "event_type": event_type, "aggregate_type": "scheduled_plan_change",
        "aggregate_id": change.id, "occurred_at": _stored_utc(item.effective_at),
        "reference_ids": [change.id, change.subscription_id],
    }, delivery_obligations)
    if domain_event.id != item.domain_event_id:
        raise PlanChangeConflictError("schedule replay is bound to another event")
    return item, "duplicate"


def _entitlement_transition(
    session, instance, to_state, transition, occurred_at, actor_type, actor_id, source_id,
):
    key = f"phase7-entitlement:{instance.id}:{to_state}:{source_id}"
    fingerprint = _fingerprint({"instance": instance.id, "from": instance.state, "to": to_state, "source": source_id})
    registry, inserted = _claim(session, ENTITLEMENT_NAMESPACE, key, fingerprint, occurred_at)
    if not inserted:
        if registry.state == "completed" and registry.result_type == "entitlement_event":
            return registry.result_id
        raise PlanChangeRetryError("entitlement transition is already in progress")
    event = append_entitlement_transition(
        session, instance_id=instance.id, next_state=to_state, transition=transition,
        effective_at=occurred_at, actor_type=actor_type, actor_id=actor_id,
        source_type="phase7_plan_change", source_id=source_id, idempotency=registry,
        evidence_json={"phase7_source_id": source_id},
    )
    session.flush()
    session.refresh(instance)
    if instance.state != to_state:
        # ORM-created unit schemas do not install migration triggers. Keep the
        # service projection identical to the PostgreSQL AFTER INSERT trigger.
        instance.state = to_state
        instance.last_event_id = event.id
        session.flush()
    _complete_registry_if_claimed(
        session, registry, completed_at=occurred_at,
        result_type="entitlement_event", result_id=event.id,
    )
    return event.id


def apply_paid_upgrade(
    session, *, billing_account_id, subscription_id, prior_entitlement_instance_id,
    target_entitlement_instance_id, financial_line_id, paid_at, period_index,
    actor_type, actor_id, delivery_obligations,
):
    """Apply one paid-to-higher-paid upgrade and its floored proration atomically."""
    account_id = _text(billing_account_id, "billing_account_id", 36)
    subscription_id = _text(subscription_id, "subscription_id", 36)
    prior_id = _text(prior_entitlement_instance_id, "prior_entitlement_instance_id", 36)
    target_id = _text(target_entitlement_instance_id, "target_entitlement_instance_id", 36)
    line_id = _text(financial_line_id, "financial_line_id", 36)
    actor_type = _text(actor_type, "actor_type", 32)
    actor_id = _text(actor_id, "actor_id", 255)
    paid_at = _utc(paid_at, "paid_at")
    obligations = _deliveries(delivery_obligations)
    if isinstance(period_index, bool) or not isinstance(period_index, int) or period_index < 0:
        raise PlanChangeError("period_index must be a nonnegative integer")
    subscription = _lock_subscription(session, account_id, subscription_id)
    if subscription.state not in {"active", "past_due"}:
        raise PlanChangeError("paid upgrade requires a nonterminal paid subscription")
    instances = session.execute(
        select(EntitlementInstance)
        .where(EntitlementInstance.id.in_([prior_id, target_id]))
        .order_by(EntitlementInstance.id)
        .with_for_update()
    ).scalars().all()
    by_id = {item.id: item for item in instances}
    prior, target = by_id.get(prior_id), by_id.get(target_id)
    if prior is None or target is None:
        raise PlanChangeError("upgrade entitlement evidence is missing")
    if any(item.billing_account_id != account_id or item.subscription_id != subscription.id for item in (prior, target)):
        raise PlanChangeError("upgrade entitlements do not match subscription ownership")
    initial_shape = (
        prior.state == "active" and target.state == "proposed"
        and subscription.current_entitlement_definition_id == prior.entitlement_definition_id
    )
    replay_shape = (
        prior.state == "expired" and target.state == "active"
        and subscription.current_entitlement_definition_id == target.entitlement_definition_id
    )
    if not (initial_shape or replay_shape):
        raise PlanChangeError("upgrade entitlement states do not match a new command or replay")
    old_definition = session.get(EntitlementDefinition, prior.entitlement_definition_id)
    new_definition = session.get(EntitlementDefinition, target.entitlement_definition_id)
    if not old_definition or not new_definition or new_definition.approved_at is None:
        raise PlanChangeError("upgrade definitions must exist and target must be approved")
    old_amount, new_amount = _definition_amount(old_definition), _definition_amount(new_definition)
    if new_amount <= old_amount:
        raise PlanChangeError("paid upgrade target must have a higher recurring amount")
    period_start, period_end = monthly_period_bounds(_stored_utc(subscription.anchor_at), period_index)
    if not (period_start <= paid_at <= period_end):
        raise PlanChangeError("upgrade payment is outside the current credit period")
    line = session.execute(select(FinancialLine).where(FinancialLine.id == line_id).with_for_update()).scalar_one_or_none()
    financial = session.get(FinancialTransaction, line.financial_transaction_id) if line else None
    if (
        line is None or financial is None or financial.kind != "payment"
        or financial.billing_account_id != account_id or financial.principal_minor <= 0
        or line.line_kind != "subscription" or line.principal_minor <= 0
        or line.subscription_id != subscription.id or line.entitlement_instance_id != target.id
        or _stored_utc(financial.effective_at) != paid_at
    ):
        raise PlanChangeError("upgrade requires matching positive paid-line evidence")
    seconds_total = _whole_seconds(period_end - period_start)
    seconds_remaining = max(0, _whole_seconds(period_end - paid_at))
    amount = ((new_amount - old_amount) * seconds_remaining) // seconds_total
    key = f"upgrade:{subscription.id}:{line.id}:{paid_at.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    fingerprint = _fingerprint({
        "account": account_id, "subscription": subscription.id, "prior": prior.id,
        "target": target.id, "line": line.id, "paid_at": paid_at.isoformat(),
        "period_start": period_start.isoformat(), "period_end": period_end.isoformat(),
        "old_amount": old_amount, "new_amount": new_amount, "amount": amount,
    })
    registry, inserted = _claim(session, UPGRADE_NAMESPACE, key, fingerprint, paid_at)
    if not inserted:
        allocation = session.execute(
            select(UpgradeCreditAllocation).where(UpgradeCreditAllocation.idempotency_registry_id == registry.id)
        ).scalar_one_or_none()
        if registry.state != "completed" or allocation is None:
            raise PlanChangeRetryError("upgrade is already in progress")
        event, _messages, _state = _event(session, {
            "billing_account_id": account_id, "event_key": f"plan_change_applied:upgrade:{allocation.id}",
            "event_type": "plan_change_applied", "aggregate_type": "upgrade_credit_allocation",
            "aggregate_id": allocation.id, "occurred_at": _stored_utc(registry.claimed_at),
            "reference_ids": [allocation.id, subscription.id, prior.id, target.id, line.id],
        }, obligations)
        if event.id != allocation.domain_event_id:
            raise PlanChangeConflictError("upgrade replay is bound to another domain event")
        return allocation, session.get(CreditLot, allocation.funded_lot_id), "duplicate"

    active = _active_schedule(session, subscription.id)
    allocation_id = str(uuid.uuid4())
    domain_event, _messages, state = _event(session, {
        "billing_account_id": account_id, "event_key": f"plan_change_applied:upgrade:{allocation_id}",
        "event_type": "plan_change_applied", "aggregate_type": "upgrade_credit_allocation",
        "aggregate_id": allocation_id, "occurred_at": paid_at,
        "reference_ids": [allocation_id, subscription.id, prior.id, target.id, line.id],
    }, obligations)
    if state != "inserted":
        raise PlanChangeConflictError("new upgrade reused an existing domain event")
    if active is not None:
        _transition_schedule(
            session, change=active, to_state="superseded", transition="superseded_by_paid_upgrade",
            effective_at=paid_at, actor_type=actor_type, actor_id=actor_id,
            evidence={"upgrade_allocation_id": allocation_id}, delivery_obligations=obligations,
        )
    _entitlement_transition(session, prior, "expired", "paid_upgrade_replaced", paid_at, actor_type, actor_id, allocation_id)
    session.refresh(prior)
    _entitlement_transition(session, target, "scheduled", "paid_upgrade_approved", paid_at, actor_type, actor_id, allocation_id)
    session.refresh(target)
    _entitlement_transition(session, target, "active", "paid_upgrade_activated", paid_at, actor_type, actor_id, allocation_id)
    subscription.current_entitlement_definition_id = target.entitlement_definition_id
    subscription.state = "active"
    lot = entry = None
    lot_id = str(uuid.uuid4()) if amount else None
    entry_id = str(uuid.uuid4()) if amount else None
    allocation = UpgradeCreditAllocation(
        id=allocation_id, billing_account_id=account_id, subscription_id=subscription.id,
        prior_entitlement_instance_id=prior.id, target_entitlement_instance_id=target.id,
        financial_line_id=line.id, idempotency_registry_id=registry.id,
        domain_event_id=domain_event.id, funded_lot_id=lot_id,
        grant_entry_id=entry_id, allocation_key=key,
        request_fingerprint=fingerprint, old_period_amount=old_amount,
        new_period_amount=new_amount, period_starts_at=period_start,
        period_ends_at=period_end, paid_at=paid_at, credit_amount=amount,
    )
    session.add(allocation)
    session.flush()
    if amount:
        lot = CreditLot(
            id=lot_id, billing_account_id=account_id,
            source_type="subscription_recurring", source_id=allocation_id,
            original_amount=amount, available_at=paid_at, expires_at=period_end,
            origin_evidence_json={"upgrade_credit_allocation_id": allocation_id, "financial_line_id": line.id},
        )
        session.add(lot)
        session.flush()
        entry = CreditLedgerEntry(
            id=entry_id, billing_account_id=account_id, lot_id=lot.id,
            entry_type="grant", available_delta=amount, held_delta=0,
            idempotency_registry_id=registry.id,
            effective_at=paid_at, actor_type=actor_type, actor_id=actor_id,
            reason_code="upgrade_proration", evidence_json={"upgrade_credit_allocation_id": allocation_id},
        )
        append_entry(session, entry)
    _complete_registry_if_claimed(
        session, registry, completed_at=paid_at,
        result_type="upgrade_credit_allocation", result_id=allocation.id,
    )
    session.flush()
    return allocation, lot, "inserted"


def activate_free_to_paid(
    session, *, billing_account_id, subscription_id, free_entitlement_instance_id,
    target_entitlement_instance_id, financial_line_id, paid_at, actor_type, actor_id,
    change_delivery_obligations, funding_delivery_obligations,
):
    """Activate a first paid subscription and fund its full opening period."""
    account_id = _text(billing_account_id, "billing_account_id", 36)
    subscription_id = _text(subscription_id, "subscription_id", 36)
    free_id = _text(free_entitlement_instance_id, "free_entitlement_instance_id", 36)
    target_id = _text(target_entitlement_instance_id, "target_entitlement_instance_id", 36)
    line_id = _text(financial_line_id, "financial_line_id", 36)
    actor_type = _text(actor_type, "actor_type", 32)
    actor_id = _text(actor_id, "actor_id", 255)
    paid_at = _utc(paid_at, "paid_at")
    change_obligations = _deliveries(change_delivery_obligations)
    funding_obligations = _deliveries(funding_delivery_obligations)
    subscription = _lock_subscription(session, account_id, subscription_id)
    if subscription.state not in {"proposed", "incomplete"}:
        raise PlanChangeError("free-to-paid activation requires a not-yet-active subscription")
    if (
        _stored_utc(subscription.anchor_at) != paid_at
        or _stored_utc(subscription.term_starts_at) != paid_at
    ):
        raise PlanChangeError("first paid subscription must use the successful activation anchor")
    instances = session.execute(
        select(EntitlementInstance)
        .where(EntitlementInstance.id.in_([free_id, target_id]))
        .order_by(EntitlementInstance.id)
        .with_for_update()
    ).scalars().all()
    by_id = {item.id: item for item in instances}
    free, target = by_id.get(free_id), by_id.get(target_id)
    if (
        free is None or target is None or free.billing_account_id != account_id
        or free.source_type != "free" or free.state != "active"
        or target.billing_account_id != account_id or target.subscription_id != subscription.id
        or target.source_type != "subscription" or target.state != "proposed"
        or target.entitlement_definition_id != subscription.current_entitlement_definition_id
    ):
        raise PlanChangeError("free-to-paid entitlement evidence does not match")
    line = session.execute(select(FinancialLine).where(FinancialLine.id == line_id).with_for_update()).scalar_one_or_none()
    financial = session.get(FinancialTransaction, line.financial_transaction_id) if line else None
    if (
        line is None or financial is None or financial.kind != "payment"
        or financial.billing_account_id != account_id or financial.principal_minor <= 0
        or _stored_utc(financial.effective_at) != paid_at or line.line_kind != "subscription"
        or line.principal_minor <= 0 or line.subscription_id != subscription.id
        or line.entitlement_instance_id != target.id
    ):
        raise PlanChangeError("free-to-paid activation requires matching paid-line evidence")
    key = f"upgrade:{subscription.id}:{line.id}:{paid_at.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    fingerprint = _fingerprint({
        "account": account_id, "subscription": subscription.id, "free": free.id,
        "target": target.id, "line": line.id, "paid_at": paid_at.isoformat(),
        "mode": "free_to_paid_full_period",
    })
    registry, inserted = _claim(session, UPGRADE_NAMESPACE, key, fingerprint, paid_at)
    if not inserted:
        if registry.state != "completed" or registry.result_type != "domain_event":
            raise PlanChangeRetryError("free-to-paid activation is already in progress")
        event, _messages, _state = _event(session, {
            "billing_account_id": account_id,
            "event_key": f"plan_change_applied:activation:{subscription.id}:{line.id}",
            "event_type": "plan_change_applied", "aggregate_type": "billing_subscription",
            "aggregate_id": subscription.id, "occurred_at": _stored_utc(registry.claimed_at),
            "reference_ids": [subscription.id, free.id, target.id, line.id],
        }, change_obligations)
        if event.id != registry.result_id:
            raise PlanChangeConflictError("activation replay is bound to another event")
        allocation = session.execute(
            select(RecurringCreditAllocation)
            .where(RecurringCreditAllocation.entitlement_instance_id == target.id)
        ).scalar_one()
        return allocation, "duplicate"
    domain_event, _messages, state = _event(session, {
        "billing_account_id": account_id,
        "event_key": f"plan_change_applied:activation:{subscription.id}:{line.id}",
        "event_type": "plan_change_applied", "aggregate_type": "billing_subscription",
        "aggregate_id": subscription.id, "occurred_at": paid_at,
        "reference_ids": [subscription.id, free.id, target.id, line.id],
    }, change_obligations)
    if state != "inserted":
        raise PlanChangeConflictError("new activation reused an existing domain event")
    _entitlement_transition(session, free, "expired", "free_replaced_by_paid", paid_at, actor_type, actor_id, domain_event.id)
    _entitlement_transition(session, target, "scheduled", "first_paid_approved", paid_at, actor_type, actor_id, domain_event.id)
    session.refresh(target)
    _entitlement_transition(session, target, "active", "first_paid_activation", paid_at, actor_type, actor_id, domain_event.id)
    subscription.state = "active"
    session.flush()
    try:
        allocation, _period, _lot, _state = allocate_recurring_credits(
            session, billing_account_id=account_id, entitlement_instance_id=target.id,
            period_index=0, opened_at=paid_at, delivery_obligations=funding_obligations,
            financial_line_id=line.id, actor_type=actor_type, actor_id=actor_id,
        )
    except RecurringAllocationError as exc:
        raise PlanChangeError(str(exc)) from exc
    _complete_registry_if_claimed(
        session, registry, completed_at=paid_at,
        result_type="domain_event", result_id=domain_event.id,
    )
    session.flush()
    return allocation, "inserted"


def apply_scheduled_change(
    session, *, scheduled_change_id, target_entitlement_instance_id,
    financial_line_id, period_index, applied_at, actor_type, actor_id,
    change_delivery_obligations, funding_delivery_obligations,
):
    """Apply a paid downgrade at renewal or a cancellation at paid term end."""
    change_id = _text(scheduled_change_id, "scheduled_change_id", 36)
    applied_at = _utc(applied_at, "applied_at")
    actor_type = _text(actor_type, "actor_type", 32)
    actor_id = _text(actor_id, "actor_id", 255)
    change_obligations = _deliveries(change_delivery_obligations)
    lock_row = session.execute(
        select(ScheduledPlanChange).where(ScheduledPlanChange.id == change_id).with_for_update()
    ).scalar_one_or_none()
    if lock_row is None:
        raise PlanChangeError("scheduled change does not exist")
    subscription = _lock_subscription(session, lock_row.billing_account_id, lock_row.subscription_id)
    change = session.execute(
        select(ScheduledPlanChange).where(ScheduledPlanChange.id == change_id).with_for_update()
    ).scalar_one()
    if change.state == "applied":
        event, state = _revalidate_transition_replay(
            session, change, change_obligations,
        )
        allocation_id = (event.evidence_json or {}).get(
            "recurring_credit_allocation_id",
        )
        return change, session.get(RecurringCreditAllocation, allocation_id), state
    if change.state not in ACTIVE_SCHEDULE_STATES:
        raise PlanChangeError("scheduled change is not active")
    if applied_at < _stored_utc(change.effective_at):
        raise PlanChangeError("scheduled change cannot apply before its effective time")
    current = session.execute(
        select(EntitlementInstance)
        .where(
            EntitlementInstance.subscription_id == subscription.id,
            EntitlementInstance.state == "active",
            EntitlementInstance.entitlement_definition_id == subscription.current_entitlement_definition_id,
        ).with_for_update()
    ).scalar_one()
    allocation = None
    if change.kind == "downgrade":
        target_id = _text(target_entitlement_instance_id, "target_entitlement_instance_id", 36)
        line_id = _text(financial_line_id, "financial_line_id", 36)
        target = session.execute(
            select(EntitlementInstance).where(EntitlementInstance.id == target_id).with_for_update()
        ).scalar_one_or_none()
        if (
            target is None or target.billing_account_id != change.billing_account_id
            or target.subscription_id != subscription.id or target.state != "scheduled"
            or target.entitlement_definition_id != change.target_entitlement_definition_id
        ):
            raise PlanChangeError("scheduled downgrade target evidence does not match")
        _entitlement_transition(session, current, "expired", "scheduled_downgrade_replaced", applied_at, actor_type, actor_id, change.id)
        _entitlement_transition(session, target, "active", "scheduled_downgrade_activated", applied_at, actor_type, actor_id, change.id)
        subscription.current_entitlement_definition_id = target.entitlement_definition_id
        subscription.state = "active"
        subscription.term_starts_at = applied_at
        subscription.term_ends_at = add_calendar_months(
            applied_at, 1 if subscription.interval == "month" else 12,
        )
        session.flush()
        try:
            allocation, _period, _lot, _state = allocate_recurring_credits(
                session, billing_account_id=change.billing_account_id,
                entitlement_instance_id=target.id, period_index=period_index,
                opened_at=applied_at, delivery_obligations=_deliveries(funding_delivery_obligations),
                financial_line_id=line_id, actor_type=actor_type, actor_id=actor_id,
            )
        except RecurringAllocationError as exc:
            raise PlanChangeError(str(exc)) from exc
    else:
        if target_entitlement_instance_id is not None or financial_line_id is not None:
            raise PlanChangeError("cancellation cannot use target or payment evidence")
        _entitlement_transition(session, current, "expired", "cancellation_term_ended", applied_at, actor_type, actor_id, change.id)
        subscription.state = "cancelled"
    event, state = _transition_schedule(
        session, change=change, to_state="applied", transition=f"{change.kind}_applied",
        effective_at=applied_at, actor_type=actor_type, actor_id=actor_id,
        evidence={"recurring_credit_allocation_id": allocation.id if allocation else None},
        delivery_obligations=change_obligations,
    )
    return change, allocation, state


def mark_scheduled_renewal_unpaid(
    session, *, scheduled_change_id, observed_at, actor_type, actor_id,
    delivery_obligations,
):
    """Retain the current entitlement and mark a due downgrade awaiting payment."""
    change = session.execute(
        select(ScheduledPlanChange)
        .where(ScheduledPlanChange.id == scheduled_change_id)
        .with_for_update()
    ).scalar_one_or_none()
    if change is None or change.kind != "downgrade":
        raise PlanChangeError("downgrade schedule does not exist")
    _lock_subscription(session, change.billing_account_id, change.subscription_id)
    if change.state == "awaiting_renewal_payment":
        _event, state = _revalidate_transition_replay(
            session, change, delivery_obligations,
        )
        return change, state
    event, state = _transition_schedule(
        session, change=change, to_state="awaiting_renewal_payment",
        transition="renewal_payment_not_succeeded", effective_at=observed_at,
        actor_type=actor_type, actor_id=actor_id, evidence={"credits_granted": False},
        delivery_obligations=delivery_obligations,
    )
    return change, state


def resume_cancellation(
    session, *, scheduled_change_id, resumed_at, actor_type, actor_id,
    delivery_obligations,
):
    """Cancel a pending period-end cancellation without moving its anchor."""
    change_id = _text(scheduled_change_id, "scheduled_change_id", 36)
    resumed_at = _utc(resumed_at, "resumed_at")
    actor_type = _text(actor_type, "actor_type", 32)
    actor_id = _text(actor_id, "actor_id", 255)
    obligations = _deliveries(delivery_obligations)
    change = session.execute(
        select(ScheduledPlanChange)
        .where(ScheduledPlanChange.id == change_id)
        .with_for_update()
    ).scalar_one_or_none()
    if change is None or change.kind != "cancellation":
        raise PlanChangeError("pending cancellation does not exist")
    subscription = _lock_subscription(
        session, change.billing_account_id, change.subscription_id,
    )
    session.refresh(change)
    if change.state == "cancelled":
        _event, state = _revalidate_transition_replay(
            session, change, obligations,
        )
        return change, state
    if change.state != "pending":
        raise PlanChangeError("cancellation is not pending")
    if resumed_at >= _stored_utc(change.effective_at):
        raise PlanChangeError("cancellation can only be resumed before period end")
    if subscription.state != "cancel_at_period_end":
        raise PlanChangeError("subscription is not pending cancellation")
    _event_row, state = _transition_schedule(
        session, change=change, to_state="cancelled",
        transition="cancellation_resumed", effective_at=resumed_at,
        actor_type=actor_type, actor_id=actor_id,
        evidence={"anchor_unchanged": True},
        delivery_obligations=obligations,
    )
    subscription.state = "active"
    session.flush()
    return change, state
