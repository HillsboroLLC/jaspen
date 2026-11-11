"""Inactive Phase 4 entitlement and recurring-period policy.

This module is intentionally unreferenced by live routes, webhooks,
authentication, access gates, and jobs. It is the single future policy surface
for lifecycle transitions, UTC period arithmetic, and ledger-compatible period
funding after later phases authorize command integration.
"""

import calendar
import math
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from .billing_ledger import CreditLedgerInvariantError, append_entry, lock_billing_account
from .models import CreditLedgerEntry, CreditLot, IdempotencyRegistry
from .models_billing_phase4 import CreditPeriod, EntitlementEvent, EntitlementInstance


SUBSCRIPTION_TRANSITIONS = {
    "proposed": frozenset({"incomplete", "active", "cancelled"}),
    "incomplete": frozenset({"active", "cancelled", "expired"}),
    "active": frozenset({"past_due", "paused", "cancel_at_period_end", "cancelled", "expired"}),
    "past_due": frozenset({"active", "unpaid", "paused", "cancel_at_period_end", "cancelled", "expired"}),
    "unpaid": frozenset({"active", "cancelled", "expired"}),
    "paused": frozenset({"active", "cancel_at_period_end", "cancelled", "expired"}),
    "cancel_at_period_end": frozenset({"active", "past_due", "cancelled", "expired"}),
    "cancelled": frozenset(),
    "expired": frozenset(),
}

ENTITLEMENT_TRANSITIONS = {
    "proposed": frozenset({"scheduled", "cancelled"}),
    "scheduled": frozenset({"active", "superseded", "cancelled"}),
    "active": frozenset({"reducing", "expired"}),
    "reducing": frozenset({"expired", "superseded"}),
    "expired": frozenset(),
    "superseded": frozenset(),
    "cancelled": frozenset(),
}

CREDIT_PERIOD_TRANSITIONS = {
    "planned": frozenset({"funded", "unfunded", "expired"}),
    "unfunded": frozenset({"funded", "expired"}),
    "funded": frozenset({"expired"}),
    "expired": frozenset(),
}

PERIOD_SOURCE_TYPES = {
    "free": "free_recurring",
    "monthly_subscription": "subscription_recurring",
    "annual_monthly": "subscription_recurring",
    "enterprise": "enterprise_recurring",
}


class EntitlementInvariantError(ValueError):
    pass


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise EntitlementInvariantError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def add_calendar_months(anchor_at: datetime, months: int) -> datetime:
    """Advance a UTC anchor with deterministic month-end/leap-year clamping."""
    if months < 0:
        raise EntitlementInvariantError("calendar month offset cannot be negative")
    anchor = _utc(anchor_at)
    absolute = anchor.year * 12 + anchor.month - 1 + months
    year, zero_month = divmod(absolute, 12)
    month = zero_month + 1
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    return anchor.replace(year=year, month=month, day=day)


def monthly_period_bounds(anchor_at: datetime, period_index: int) -> tuple[datetime, datetime]:
    return add_calendar_months(anchor_at, period_index), add_calendar_months(anchor_at, period_index + 1)


def validate_definition_payloads(capability_json: dict, funding_policy_json: dict):
    """Validate the approved v1 finite-value contract without adding policy."""
    if not isinstance(capability_json, dict) or not isinstance(funding_policy_json, dict):
        raise EntitlementInvariantError("definition payloads must be JSON objects")
    if capability_json.get("schema_version") != 1:
        raise EntitlementInvariantError("capability schema_version must be 1")
    if not isinstance(capability_json.get("capabilities"), dict):
        raise EntitlementInvariantError("capabilities must be an explicit object")
    if funding_policy_json.get("schema_version") != 1:
        raise EntitlementInvariantError("funding schema_version must be 1")
    amount = funding_policy_json.get("credit_amount")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise EntitlementInvariantError("credit_amount must be an explicit nonnegative integer")
    if amount > 2**63 - 1:
        raise EntitlementInvariantError("credit_amount exceeds ledger precision")
    period_kind = funding_policy_json.get("period_kind")
    if period_kind not in {"none", "free", "monthly_subscription", "annual_monthly", "enterprise"}:
        raise EntitlementInvariantError("funding period_kind is invalid")

    def reject_unlimited(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise EntitlementInvariantError("definition values must be finite")
        if isinstance(value, dict):
            for key, child in value.items():
                if "unlimited" in str(key).lower() and child not in (False, 0, None):
                    raise EntitlementInvariantError("unlimited benefits are not permitted")
                reject_unlimited(child)
        elif isinstance(value, list):
            for child in value:
                reject_unlimited(child)

    reject_unlimited(capability_json)
    reject_unlimited(funding_policy_json)


def new_credit_period(
    *, billing_account_id: str, entitlement_instance_id: str,
    subscription_id: str | None, kind: str, period_index: int,
    anchor_at: datetime, planned_allocation_amount: int,
):
    """Construct a planned period from the sole calendar implementation."""
    if planned_allocation_amount <= 0:
        raise EntitlementInvariantError("planned allocation must be positive")
    starts_at, ends_at = monthly_period_bounds(anchor_at, period_index)
    return CreditPeriod(
        id=str(uuid.uuid4()), billing_account_id=billing_account_id,
        entitlement_instance_id=entitlement_instance_id,
        subscription_id=subscription_id, kind=kind, period_index=period_index,
        anchor_at=_utc(anchor_at), starts_at=starts_at, ends_at=ends_at,
        planned_allocation_amount=planned_allocation_amount, state="planned",
    )


def append_entitlement_transition(
    session, *, instance_id: str, next_state: str, transition: str,
    effective_at: datetime, actor_type: str, actor_id: str,
    source_type: str, source_id: str, idempotency: IdempotencyRegistry,
    evidence_json: dict,
):
    """Append the event that database triggers project onto the instance."""
    if idempotency.state == "completed":
        if idempotency.result_type == "entitlement_event" and idempotency.result_id:
            return session.get(EntitlementEvent, idempotency.result_id)
        raise EntitlementInvariantError("completed key refers to another result")
    if idempotency.state != "claimed":
        raise EntitlementInvariantError("transition requires a claimed idempotency key")
    account_id = session.execute(
        select(EntitlementInstance.billing_account_id)
        .where(EntitlementInstance.id == instance_id)
    ).scalar_one()
    lock_billing_account(session, account_id)
    instance = session.execute(
        select(EntitlementInstance)
        .where(EntitlementInstance.id == instance_id)
        .with_for_update()
    ).scalar_one()
    if next_state not in ENTITLEMENT_TRANSITIONS.get(instance.state, frozenset()):
        raise EntitlementInvariantError(f"invalid entitlement transition: {instance.state} -> {next_state}")
    event = EntitlementEvent(
        id=str(uuid.uuid4()), entitlement_instance_id=instance_id,
        transition=transition, from_state=instance.state, to_state=next_state,
        effective_at=_utc(effective_at), actor_type=actor_type, actor_id=actor_id,
        source_type=source_type, source_id=source_id,
        idempotency_registry_id=idempotency.id, evidence_json=evidence_json,
    )
    session.add(event)
    session.flush()
    return event


def mark_period_unfunded(session, period_id: str, idempotency: IdempotencyRegistry, error_code: str):
    account_id = session.execute(
        select(CreditPeriod.billing_account_id).where(CreditPeriod.id == period_id)
    ).scalar_one()
    lock_billing_account(session, account_id)
    period = session.execute(
        select(CreditPeriod).where(CreditPeriod.id == period_id).with_for_update()
    ).scalar_one()
    if "unfunded" not in CREDIT_PERIOD_TRANSITIONS[period.state]:
        raise EntitlementInvariantError("invalid credit period transition")
    if period.funding_idempotency_registry_id not in (None, idempotency.id):
        raise EntitlementInvariantError("period is bound to another funding identity")
    if idempotency.state != "claimed":
        raise EntitlementInvariantError("funding requires a claimed idempotency key")
    period.funding_idempotency_registry_id = idempotency.id
    period.state = "unfunded"
    idempotency.state = "failed_retryable"
    idempotency.last_error_code = error_code
    session.flush()
    return period


def fund_credit_period(
    session, period_id: str, idempotency: IdempotencyRegistry,
    *, actor_type: str, actor_id: str, evidence_json: dict,
):
    """Fund one disposable-test period through the sole Phase 3 ledger."""
    account_id = session.execute(
        select(CreditPeriod.billing_account_id).where(CreditPeriod.id == period_id)
    ).scalar_one()
    lock_billing_account(session, account_id)
    period = session.execute(
        select(CreditPeriod).where(CreditPeriod.id == period_id).with_for_update()
    ).scalar_one()
    if period.state == "funded":
        if period.funding_idempotency_registry_id == idempotency.id:
            return session.get(CreditLot, period.funded_lot_id)
        raise EntitlementInvariantError("period was already funded")
    if "funded" not in CREDIT_PERIOD_TRANSITIONS[period.state]:
        raise EntitlementInvariantError("invalid credit period transition")
    if period.funding_idempotency_registry_id not in (None, idempotency.id):
        raise EntitlementInvariantError("period is bound to another funding identity")
    if idempotency.state != "claimed":
        raise EntitlementInvariantError("funding requires a claimed idempotency key")

    lot = CreditLot(
        id=str(uuid.uuid4()), billing_account_id=period.billing_account_id,
        source_type=PERIOD_SOURCE_TYPES[period.kind], source_id=period.id,
        original_amount=period.planned_allocation_amount,
        available_at=period.starts_at, expires_at=period.ends_at,
        origin_evidence_json=evidence_json,
    )
    session.add(lot)
    session.flush()
    entry = CreditLedgerEntry(
        id=str(uuid.uuid4()), billing_account_id=period.billing_account_id,
        lot_id=lot.id, entry_type="grant",
        available_delta=period.planned_allocation_amount, held_delta=0,
        idempotency_registry_id=idempotency.id, effective_at=period.starts_at,
        actor_type=actor_type, actor_id=actor_id,
        reason_code="credit_period_funded", evidence_json=evidence_json,
    )
    try:
        append_entry(session, entry)
    except CreditLedgerInvariantError as exc:
        raise EntitlementInvariantError(str(exc)) from exc
    period.funding_idempotency_registry_id = idempotency.id
    period.funded_lot_id = lot.id
    period.state = "funded"
    session.flush()
    return lot
