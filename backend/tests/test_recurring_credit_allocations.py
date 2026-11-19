"""Phase 6 free and subscription recurring-credit allocation coverage."""

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import threading
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

import app.billing_allocations as billing_allocations_module
from app.billing_allocations import (
    RecurringAllocationConflictError,
    RecurringAllocationError,
    allocate_recurring_credits,
    expire_recurring_credits,
)
from app.billing_entitlements import add_calendar_months, append_entitlement_transition
from app.billing_ledger import append_entry, ordered_lot_balances
from app.models import (
    BillingAccount,
    BillingSubscription,
    CommunicationOutbox,
    CreditLedgerEntry,
    CreditLot,
    CreditPeriod,
    DomainEvent,
    EntitlementDefinition,
    EntitlementInstance,
    ExternalEventInbox,
    FinancialLine,
    FinancialTransaction,
    IdempotencyRegistry,
    Organization,
    RecurringCreditAllocation,
    User,
)


ANCHOR = datetime(2026, 1, 31, 15, 45, tzinfo=timezone.utc)
CAPABILITIES = {"schema_version": 1, "capabilities": {"analysis": True}}
FUNDED_DELIVERIES = ({
    "template_key": "test-credit-period-funded",
    "template_version": "test-v1",
    "channel": "test-channel",
    "locale": "en-US",
},)
EXPIRED_DELIVERIES = ({
    "template_key": "test-credits-expired",
    "template_version": "test-v1",
    "channel": "test-channel",
    "locale": "en-US",
},)


def _utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _free_foundation(db, test_user, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    organization = Organization(
        name=f"Phase 6 Free {suffix}", slug=f"phase-6-free-{suffix}",
        owner_user_id=test_user.id, plan_key="free",
    )
    db.session.add(organization)
    db.session.flush()
    account = BillingAccount(
        id=f"p6-account-{suffix}", organization_id=organization.id,
        currency="usd", account_anchor_at=ANCHOR,
    )
    definition = EntitlementDefinition(
        id=f"p6-definition-{suffix}", key="free", version=3,
        exclusivity_key="base-plan", capability_json=CAPABILITIES,
        funding_policy_json={
            "schema_version": 1, "period_kind": "free", "credit_amount": 120,
        },
        effective_at=ANCHOR, approved_at=ANCHOR,
        approval_evidence_reference="approval:phase6-free",
    )
    db.session.add_all([account, definition])
    db.session.flush()
    instance = EntitlementInstance(
        id=f"p6-instance-{suffix}", billing_account_id=account.id,
        entitlement_definition_id=definition.id, state="active",
        starts_at=ANCHOR, ends_at=add_calendar_months(ANCHOR, 12),
        source_type="free", source_id=f"free:{suffix}",
        approval_evidence_reference="approval:phase6-free",
    )
    db.session.add(instance)
    db.session.flush()
    return account, definition, instance


def _subscription_foundation(db, test_user, *, interval="year", suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    organization = Organization(
        name=f"Phase 6 Paid {suffix}", slug=f"phase-6-paid-{suffix}",
        owner_user_id=test_user.id, plan_key="free",
    )
    db.session.add(organization)
    db.session.flush()
    account = BillingAccount(
        id=f"p6-paid-account-{suffix}", organization_id=organization.id,
        currency="usd", account_anchor_at=ANCHOR,
    )
    period_kind = "annual_monthly" if interval == "year" else "monthly_subscription"
    definition = EntitlementDefinition(
        id=f"p6-paid-definition-{suffix}", key=f"pro-{suffix}", version=7,
        exclusivity_key="base-plan", capability_json=CAPABILITIES,
        funding_policy_json={
            "schema_version": 1, "period_kind": period_kind, "credit_amount": 500,
        },
        effective_at=ANCHOR, approved_at=ANCHOR,
        approval_evidence_reference="approval:phase6-paid",
    )
    db.session.add_all([account, definition])
    db.session.flush()
    subscription = BillingSubscription(
        id=f"p6-subscription-{suffix}", billing_account_id=account.id,
        processor="stripe", external_subscription_id=f"sub_{suffix}",
        interval=interval, anchor_at=ANCHOR, term_starts_at=ANCHOR,
        term_ends_at=add_calendar_months(ANCHOR, 12 if interval == "year" else 2),
        state="active", current_entitlement_definition_id=definition.id,
        origin_evidence_json={"inbox_event_id": f"p6-inbox-{suffix}"},
    )
    db.session.add(subscription)
    db.session.flush()
    instance = EntitlementInstance(
        id=f"p6-paid-instance-{suffix}", billing_account_id=account.id,
        entitlement_definition_id=definition.id, subscription_id=subscription.id,
        state="active", starts_at=ANCHOR, ends_at=subscription.term_ends_at,
        source_type="subscription", source_id=subscription.external_subscription_id,
        approval_evidence_reference="approval:phase6-paid",
    )
    inbox = ExternalEventInbox(
        id=f"p6-inbox-{suffix}", provider="stripe", event_id=f"evt_{suffix}",
        event_type="invoice.payment_succeeded", object_type="invoice",
        object_id=f"in_{suffix}", payload_digest="a" * 64,
        summary_json={"schema_version": 1}, livemode=False,
        provider_created_at=ANCHOR, received_at=ANCHOR,
        state="processed", processed_at=ANCHOR,
    )
    db.session.add_all([instance, inbox])
    db.session.flush()
    transaction = FinancialTransaction(
        id=f"p6-payment-{suffix}", billing_account_id=account.id,
        kind="payment", provider="stripe", object_type="invoice",
        object_id=f"in_{suffix}", external_version="paid-v1",
        effective_at=ANCHOR, currency="usd", principal_minor=10000,
        tax_minor=0, fee_minor=0, discount_minor=0, gross_minor=10000,
        inbox_event_id=inbox.id,
    )
    db.session.add(transaction)
    db.session.flush()
    line = FinancialLine(
        id=f"p6-line-{suffix}", financial_transaction_id=transaction.id,
        external_line_id=f"il_{suffix}", line_kind="subscription",
        source_type="stripe_price", source_id=f"price_{suffix}", quantity=1,
        currency="usd", principal_minor=10000, tax_minor=0, fee_minor=0,
        discount_minor=0, subscription_id=subscription.id,
        entitlement_instance_id=instance.id,
    )
    db.session.add(line)
    db.session.flush()
    return account, definition, instance, subscription, line


def _paid_subscription_line(db, account, instance, subscription, *, effective_at, suffix):
    inbox = ExternalEventInbox(
        id=f"p6-inbox-{suffix}", provider="stripe", event_id=f"evt_{suffix}",
        event_type="invoice.payment_succeeded", object_type="invoice",
        object_id=f"in_{suffix}", payload_digest="b" * 64,
        summary_json={"schema_version": 1}, livemode=False,
        provider_created_at=effective_at, received_at=effective_at,
        state="processed", processed_at=effective_at,
    )
    db.session.add(inbox)
    db.session.flush()
    transaction = FinancialTransaction(
        id=f"p6-payment-{suffix}", billing_account_id=account.id,
        kind="payment", provider="stripe", object_type="invoice",
        object_id=f"in_{suffix}", external_version="paid-v1",
        effective_at=effective_at, currency=account.currency, principal_minor=10000,
        tax_minor=0, fee_minor=0, discount_minor=0, gross_minor=10000,
        inbox_event_id=inbox.id,
    )
    db.session.add(transaction)
    db.session.flush()
    line = FinancialLine(
        id=f"p6-line-{suffix}", financial_transaction_id=transaction.id,
        external_line_id=f"il_{suffix}", line_kind="subscription",
        source_type="stripe_price", source_id=f"price_{suffix}", quantity=1,
        currency=account.currency, principal_minor=10000, tax_minor=0, fee_minor=0,
        discount_minor=0, subscription_id=subscription.id,
        entitlement_instance_id=instance.id,
    )
    db.session.add(line)
    db.session.flush()
    return line


def test_free_period_is_anchored_idempotent_expiring_and_nonrolling(db, test_user):
    account, _, instance = _free_foundation(db, test_user)
    allocation, period, lot, state = allocate_recurring_credits(
        db.session, billing_account_id=account.id,
        entitlement_instance_id=instance.id, period_index=0, opened_at=ANCHOR,
        delivery_obligations=FUNDED_DELIVERIES,
        actor_type="system", actor_id="phase-6",
    )
    db.session.commit()

    assert state == "inserted"
    assert allocation.allocation_key == (
        f"period:free:{account.id}:2026-01-31T15:45:00Z"
    )
    assert _utc(period.starts_at) == ANCHOR
    assert _utc(period.ends_at) == datetime(2026, 2, 28, 15, 45, tzinfo=timezone.utc)
    assert lot.original_amount == 120
    assert lot.source_type == "free_recurring"
    assert lot.source_id == period.id
    assert _utc(lot.expires_at) == _utc(period.ends_at)
    funded_event = db.session.get(DomainEvent, allocation.domain_event_id)
    assert funded_event.event_type == "credit_period_funded"
    assert funded_event.aggregate_id == period.id
    assert db.session.query(CommunicationOutbox).filter_by(
        domain_event_id=funded_event.id,
    ).count() == 1

    replay = allocate_recurring_credits(
        db.session, billing_account_id=account.id,
        entitlement_instance_id=instance.id, period_index=0, opened_at=ANCHOR,
        delivery_obligations=FUNDED_DELIVERIES,
        actor_type="system", actor_id="phase-6",
    )
    assert replay[2].id == lot.id
    assert replay[3] == "duplicate"
    assert db.session.query(CreditLot).filter_by(billing_account_id=account.id).count() == 1
    assert db.session.query(DomainEvent).filter_by(
        billing_account_id=account.id,
    ).count() == 1
    assert db.session.query(CommunicationOutbox).filter_by(
        billing_account_id=account.id,
    ).count() == 1

    changed_deliveries = ({**FUNDED_DELIVERIES[0], "locale": "fr-CA"},)
    with pytest.raises(RecurringAllocationConflictError):
        allocate_recurring_credits(
            db.session, billing_account_id=account.id,
            entitlement_instance_id=instance.id, period_index=0, opened_at=ANCHOR,
            delivery_obligations=changed_deliveries,
            actor_type="system", actor_id="phase-6",
        )
    db.session.rollback()

    expired, state = expire_recurring_credits(
        db.session, credit_period_id=period.id, expired_at=_utc(period.ends_at),
        delivery_obligations=EXPIRED_DELIVERIES,
        actor_type="system", actor_id="phase-6",
    )
    db.session.commit()
    assert state == "expired"
    assert expired.state == "expired"
    expired_event = db.session.query(DomainEvent).filter_by(
        billing_account_id=account.id, event_type="credits_expired",
    ).one()
    assert db.session.query(CommunicationOutbox).filter_by(
        domain_event_id=expired_event.id,
    ).count() == 1
    replayed_expiration = expire_recurring_credits(
        db.session, credit_period_id=period.id, expired_at=_utc(period.ends_at),
        delivery_obligations=EXPIRED_DELIVERIES,
        actor_type="system", actor_id="phase-6",
    )
    assert replayed_expiration[1] == "duplicate"
    with pytest.raises(RecurringAllocationConflictError):
        expire_recurring_credits(
            db.session, credit_period_id=period.id, expired_at=_utc(period.ends_at),
            delivery_obligations=({**EXPIRED_DELIVERIES[0], "locale": "fr-CA"},),
            actor_type="system", actor_id="phase-6",
        )
    db.session.rollback()
    assert [entry.entry_type for entry in db.session.query(CreditLedgerEntry).filter_by(
        lot_id=lot.id,
    ).order_by(CreditLedgerEntry.created_at, CreditLedgerEntry.id)] == [
        "grant", "expiration",
    ]
    assert ordered_lot_balances(db.session, account.id, _utc(period.ends_at)) == []


def test_allocation_rollback_is_atomic(db, test_user):
    account, _, instance = _free_foundation(db, test_user)
    allocation, period, lot, _ = allocate_recurring_credits(
        db.session, billing_account_id=account.id,
        entitlement_instance_id=instance.id, period_index=0, opened_at=ANCHOR,
        delivery_obligations=FUNDED_DELIVERIES,
        actor_type="system", actor_id="phase-6",
    )
    identifiers = allocation.id, period.id, lot.id, allocation.domain_event_id
    db.session.rollback()
    assert db.session.get(RecurringCreditAllocation, identifiers[0]) is None
    assert db.session.get(CreditPeriod, identifiers[1]) is None
    assert db.session.get(CreditLot, identifiers[2]) is None
    assert db.session.get(DomainEvent, identifiers[3]) is None
    assert db.session.query(CommunicationOutbox).count() == 0


def test_delivery_validation_failure_rolls_back_allocation_and_expiration(db, test_user):
    account, _, instance = _free_foundation(db, test_user)
    db.session.commit()
    with pytest.raises(RecurringAllocationError, match="at least one"):
        allocate_recurring_credits(
            db.session, billing_account_id=account.id,
            entitlement_instance_id=instance.id, period_index=0, opened_at=ANCHOR,
            delivery_obligations=(), actor_type="system", actor_id="phase-6",
        )
    db.session.rollback()
    assert db.session.query(RecurringCreditAllocation).filter_by(
        billing_account_id=account.id,
    ).count() == 0

    invalid_deliveries = ({**FUNDED_DELIVERIES[0], "channel": "bad:channel"},)
    with pytest.raises(RecurringAllocationError, match="separator"):
        allocate_recurring_credits(
            db.session, billing_account_id=account.id,
            entitlement_instance_id=instance.id, period_index=0, opened_at=ANCHOR,
            delivery_obligations=invalid_deliveries,
            actor_type="system", actor_id="phase-6",
        )
    db.session.rollback()
    assert db.session.query(CreditPeriod).filter_by(
        billing_account_id=account.id,
    ).count() == 0
    assert db.session.query(DomainEvent).filter_by(
        billing_account_id=account.id,
    ).count() == 0

    _, period, lot, _ = allocate_recurring_credits(
        db.session, billing_account_id=account.id,
        entitlement_instance_id=instance.id, period_index=0, opened_at=ANCHOR,
        delivery_obligations=FUNDED_DELIVERIES,
        actor_type="system", actor_id="phase-6",
    )
    db.session.commit()
    invalid_expiration = ({**EXPIRED_DELIVERIES[0], "template_version": "bad:v1"},)
    with pytest.raises(RecurringAllocationError, match="separator"):
        expire_recurring_credits(
            db.session, credit_period_id=period.id,
            expired_at=_utc(period.ends_at),
            delivery_obligations=invalid_expiration,
            actor_type="system", actor_id="phase-6",
        )
    db.session.rollback()
    assert db.session.get(CreditPeriod, period.id).state == "funded"
    assert db.session.query(CreditLedgerEntry).filter_by(
        lot_id=lot.id, entry_type="expiration",
    ).count() == 0
    assert db.session.query(DomainEvent).filter_by(
        billing_account_id=account.id, event_type="credits_expired",
    ).count() == 0


def test_outbox_persistence_failure_rolls_back_funding_and_expiration(
    db, test_user, monkeypatch,
):
    account, _, instance = _free_foundation(db, test_user)
    db.session.commit()
    original = billing_allocations_module.record_domain_event

    def fail_after_flush(*args, **kwargs):
        original(*args, **kwargs)
        raise sa.exc.IntegrityError(
            "test outbox persistence failure", {}, RuntimeError("injected"),
        )

    monkeypatch.setattr(
        billing_allocations_module, "record_domain_event", fail_after_flush,
    )
    with pytest.raises(sa.exc.IntegrityError, match="test outbox persistence failure"):
        allocate_recurring_credits(
            db.session, billing_account_id=account.id,
            entitlement_instance_id=instance.id, period_index=0, opened_at=ANCHOR,
            delivery_obligations=FUNDED_DELIVERIES,
            actor_type="system", actor_id="phase-6",
        )
    db.session.rollback()
    assert db.session.query(CreditPeriod).filter_by(
        billing_account_id=account.id,
    ).count() == 0
    assert db.session.query(DomainEvent).filter_by(
        billing_account_id=account.id,
    ).count() == 0

    monkeypatch.setattr(
        billing_allocations_module, "record_domain_event", original,
    )
    _, period, lot, _ = allocate_recurring_credits(
        db.session, billing_account_id=account.id,
        entitlement_instance_id=instance.id, period_index=0, opened_at=ANCHOR,
        delivery_obligations=FUNDED_DELIVERIES,
        actor_type="system", actor_id="phase-6",
    )
    db.session.commit()

    monkeypatch.setattr(
        billing_allocations_module, "record_domain_event", fail_after_flush,
    )
    with pytest.raises(sa.exc.IntegrityError, match="test outbox persistence failure"):
        expire_recurring_credits(
            db.session, credit_period_id=period.id,
            expired_at=_utc(period.ends_at),
            delivery_obligations=EXPIRED_DELIVERIES,
            actor_type="system", actor_id="phase-6",
        )
    db.session.rollback()
    assert db.session.get(CreditPeriod, period.id).state == "funded"
    assert db.session.query(CreditLedgerEntry).filter_by(
        lot_id=lot.id, entry_type="expiration",
    ).count() == 0
    assert db.session.query(DomainEvent).filter_by(
        billing_account_id=account.id, event_type="credits_expired",
    ).count() == 0


def test_period_end_expires_available_and_held_value(db, test_user):
    account, _, instance = _free_foundation(db, test_user)
    _, period, lot, _ = allocate_recurring_credits(
        db.session, billing_account_id=account.id,
        entitlement_instance_id=instance.id, period_index=0, opened_at=ANCHOR,
        delivery_obligations=FUNDED_DELIVERIES,
        actor_type="system", actor_id="phase-6",
    )
    hold_registry = IdempotencyRegistry(
        id=str(uuid.uuid4()), namespace="phase6_test_hold", key=lot.id,
        request_fingerprint="c" * 64, state="completed", claimed_at=ANCHOR,
        completed_at=ANCHOR, result_type="credit_lot", result_id=lot.id,
    )
    db.session.add(hold_registry)
    db.session.flush()
    hold = append_entry(db.session, CreditLedgerEntry(
        id=str(uuid.uuid4()), billing_account_id=account.id, lot_id=lot.id,
        entry_type="dispute_hold", available_delta=-20, held_delta=20,
        idempotency_registry_id=hold_registry.id, effective_at=ANCHOR,
        actor_type="test", actor_id="phase-6", reason_code="test_hold",
        evidence_json={"test": "phase6-expiration"},
    ))
    second_registry = IdempotencyRegistry(
        id=str(uuid.uuid4()), namespace="phase6_test_hold", key=f"{lot.id}:2",
        request_fingerprint="d" * 64, state="completed", claimed_at=ANCHOR,
        completed_at=ANCHOR, result_type="credit_lot", result_id=lot.id,
    )
    db.session.add(second_registry)
    db.session.flush()
    second_hold = append_entry(db.session, CreditLedgerEntry(
        id=str(uuid.uuid4()), billing_account_id=account.id, lot_id=lot.id,
        entry_type="dispute_hold", available_delta=-10, held_delta=10,
        idempotency_registry_id=second_registry.id, effective_at=ANCHOR,
        actor_type="test", actor_id="phase-6", reason_code="test_hold",
        evidence_json={"test": "phase6-expiration-second"},
    ))
    db.session.commit()

    expired, state = expire_recurring_credits(
        db.session, credit_period_id=period.id, expired_at=_utc(period.ends_at),
        delivery_obligations=EXPIRED_DELIVERIES,
        actor_type="system", actor_id="phase-6",
    )
    db.session.commit()
    expirations = db.session.query(CreditLedgerEntry).filter_by(
        lot_id=lot.id, entry_type="expiration",
    ).order_by(CreditLedgerEntry.created_at, CreditLedgerEntry.id).all()
    assert state == "expired"
    assert expired.state == "expired"
    assert sum(entry.available_delta for entry in expirations) == -90
    assert sum(entry.held_delta for entry in expirations) == -30
    assert {entry.related_entry_id for entry in expirations} == {
        hold.id, second_hold.id,
    }


def test_annual_payment_opens_monthly_periods_without_future_value(db, test_user):
    account, _, instance, _, line = _subscription_foundation(db, test_user)
    first = allocate_recurring_credits(
        db.session, billing_account_id=account.id,
        entitlement_instance_id=instance.id, period_index=0, opened_at=ANCHOR,
        delivery_obligations=FUNDED_DELIVERIES,
        financial_line_id=line.id, actor_type="financial_event", actor_id=line.id,
    )
    db.session.commit()
    assert first[0].period_kind == "annual_monthly"
    assert _utc(first[2].available_at) == ANCHOR
    assert first[2].original_amount == 500

    with pytest.raises(RecurringAllocationError, match="not open"):
        allocate_recurring_credits(
            db.session, billing_account_id=account.id,
            entitlement_instance_id=instance.id, period_index=1,
            opened_at=ANCHOR, financial_line_id=line.id,
            delivery_obligations=FUNDED_DELIVERIES,
            actor_type="financial_event", actor_id=line.id,
        )
    db.session.rollback()

    second_start = datetime(2026, 2, 28, 15, 45, tzinfo=timezone.utc)
    second = allocate_recurring_credits(
        db.session, billing_account_id=account.id,
        entitlement_instance_id=instance.id, period_index=1,
        opened_at=second_start, financial_line_id=line.id,
        delivery_obligations=FUNDED_DELIVERIES,
        actor_type="financial_event", actor_id=line.id,
    )
    db.session.commit()
    assert second[0].allocation_key == (
        f"period:annual:{first[1].subscription_id}:1:2026-02-28T15:45:00Z"
    )
    assert _utc(second[2].available_at) == second_start
    assert db.session.query(CreditLot).filter_by(billing_account_id=account.id).count() == 2


def test_monthly_subscription_requires_payment_in_each_period(db, test_user):
    account, definition, instance, subscription, first_line = _subscription_foundation(
        db, test_user, interval="month",
    )
    first = allocate_recurring_credits(
        db.session, billing_account_id=account.id,
        entitlement_instance_id=instance.id, period_index=0, opened_at=ANCHOR,
        financial_line_id=first_line.id,
        delivery_obligations=FUNDED_DELIVERIES,
        actor_type="financial_event", actor_id=first_line.id,
    )
    db.session.commit()
    assert first[0].period_kind == "monthly_subscription"
    assert first[0].allocation_key.endswith(f":{definition.key}@{definition.version}")

    second_start = add_calendar_months(ANCHOR, 1)
    with pytest.raises(RecurringAllocationError, match="payment in that period"):
        allocate_recurring_credits(
            db.session, billing_account_id=account.id,
            entitlement_instance_id=instance.id, period_index=1,
            opened_at=second_start, financial_line_id=first_line.id,
            delivery_obligations=FUNDED_DELIVERIES,
            actor_type="financial_event", actor_id=first_line.id,
        )
    db.session.rollback()

    second_line = _paid_subscription_line(
        db, account, instance, subscription,
        effective_at=second_start, suffix=uuid.uuid4().hex[:8],
    )
    second = allocate_recurring_credits(
        db.session, billing_account_id=account.id,
        entitlement_instance_id=instance.id, period_index=1,
        opened_at=second_start, financial_line_id=second_line.id,
        delivery_obligations=FUNDED_DELIVERIES,
        actor_type="financial_event", actor_id=second_line.id,
    )
    db.session.commit()
    assert second[0].financial_line_id == second_line.id
    assert second[2].original_amount == 500


def test_subscription_allocation_rejects_cross_account_and_wrong_line(db, test_user):
    account, _, instance, _, _ = _subscription_foundation(db, test_user)
    other = _subscription_foundation(db, test_user)
    with pytest.raises(RecurringAllocationError, match="not paid subscription evidence"):
        allocate_recurring_credits(
            db.session, billing_account_id=account.id,
            entitlement_instance_id=instance.id, period_index=0, opened_at=ANCHOR,
            financial_line_id=other[4].id,
            delivery_obligations=FUNDED_DELIVERIES,
            actor_type="financial_event", actor_id=other[4].id,
        )


def test_phase6_service_has_no_live_runtime_callers():
    app_dir = Path(__file__).resolve().parents[1] / "app"
    allowed = {
        "billing_allocations.py", "billing_enterprise_contracts.py", "billing_financial_effects.py", "billing_offers.py",
        "billing_plan_changes.py", "billing_seats.py", "models.py", "models_billing_phase6.py",
        "billing_migration.py",  # Phase 14 backfill is inactive and reuses the registry claim.
    }
    importers = []
    for path in app_dir.rglob("*.py"):
        if path.name not in allowed and (
            "billing_allocations" in path.read_text()
            or "models_billing_phase6" in path.read_text()
        ):
            importers.append(str(path.relative_to(app_dir)))
    assert importers == []


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)
@pytest.mark.parametrize("isolation_level", (
    "READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE",
))
def test_postgres_concurrent_free_period_allocation_converges(
    db, test_user, isolation_level,
):
    account, _, instance = _free_foundation(db, test_user)
    account_id = account.id
    instance_id = instance.id
    db.session.commit()
    engine = db.engine
    barrier = threading.Barrier(2)

    def allocate():
        connection = engine.connect().execution_options(
            isolation_level=isolation_level,
        )
        try:
            with Session(connection) as session:
                barrier.wait(timeout=10)
                try:
                    result = allocate_recurring_credits(
                        session,
                        billing_account_id=account_id,
                        entitlement_instance_id=instance_id,
                        period_index=0,
                        opened_at=ANCHOR,
                        delivery_obligations=FUNDED_DELIVERIES,
                        actor_type="system",
                        actor_id="phase-6",
                    )
                    session.commit()
                    return result[3]
                except sa.exc.DBAPIError as error:
                    session.rollback()
                    return getattr(error.orig, "sqlstate", None)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _index: allocate(), range(2)))
    assert "inserted" in outcomes
    if isolation_level == "READ COMMITTED":
        assert sorted(outcomes) == ["duplicate", "inserted"]
    else:
        assert outcomes.count("inserted") == 1
        assert set(outcomes) <= {"inserted", "duplicate", "40001"}
    db.session.expire_all()
    assert db.session.query(RecurringCreditAllocation).filter_by(
        billing_account_id=account_id,
    ).count() == 1
    assert db.session.query(CreditLot).filter_by(
        billing_account_id=account_id,
    ).count() == 1


def _migrated_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("local disposable PostgreSQL is not configured")
    engine = sa.create_engine(url, pool_size=6, max_overflow=2)
    with engine.connect() as connection:
        revision = connection.execute(sa.text(
            "SELECT version_num FROM alembic_version"
        )).scalar_one_or_none()
    if revision not in {"f5c8d3e0b2a1", "a7d9e2f4b6c8", "b8c2d4e6f8a1", "e1a3c5b7d9f2", "f2b4d6e8a0c3", "b4d6f8a0c2e5", "c8e0a2b4d6f1", "d2f4a6c8e0b3"}:
        engine.dispose()
        pytest.fail(
            "Phase 6 migrated-schema tests require the Phase 6 or Phase 7 Alembic head; "
            f"found {revision!r}"
        )
    return engine


def _seed_migrated_free(session, suffix):
    user = User(
        id=f"p6-user-{suffix}", email=f"p6-{suffix}@example.test",
        name="Phase 6 Test", password_hash="not-a-login-credential",
        subscription_plan="free", credits_remaining=0, seat_limit=1, max_seats=1,
    )
    session.add(user)
    session.flush()
    organization = Organization(
        id=f"p6-org-{suffix}", name=f"Phase 6 {suffix}",
        slug=f"phase-6-{suffix}", owner_user_id=user.id, plan_key="free",
    )
    session.add(organization)
    session.flush()
    account = BillingAccount(
        id=f"p6-account-{suffix}", organization_id=organization.id,
        status="active", currency="usd", account_anchor_at=ANCHOR,
    )
    definition = EntitlementDefinition(
        id=f"p6-definition-{suffix}", key=f"free-{suffix}", version=1,
        exclusivity_key="base-plan", capability_json=CAPABILITIES,
        funding_policy_json={
            "schema_version": 1, "period_kind": "free", "credit_amount": 120,
        },
        effective_at=ANCHOR, approved_at=ANCHOR,
        approval_evidence_reference="approval:phase6-migrated-test",
    )
    instance = EntitlementInstance(
        id=f"p6-instance-{suffix}", billing_account_id=account.id,
        entitlement_definition_id=definition.id, state="proposed",
        starts_at=ANCHOR, ends_at=add_calendar_months(ANCHOR, 12),
        source_type="free", source_id=f"free:{suffix}",
        approval_evidence_reference="approval:phase6-migrated-test",
    )
    session.add_all([account, definition])
    session.flush()
    session.add(instance)
    session.flush()
    for index, (next_state, transition) in enumerate((
        ("scheduled", "schedule"), ("active", "activate"),
    )):
        activation_registry = IdempotencyRegistry(
            id=f"p6-transition-{index}-{suffix}",
            namespace="phase6_migrated_activation",
            key=f"{transition}:{instance.id}",
            request_fingerprint=str(8 - index) * 64,
            state="claimed", claimed_at=ANCHOR,
        )
        session.add(activation_registry)
        session.flush()
        append_entitlement_transition(
            session, instance_id=instance.id, next_state=next_state,
            transition=transition, effective_at=ANCHOR,
            actor_type="test", actor_id="phase-6-migrated-test",
            source_type="test", source_id=f"phase6:{suffix}",
            idempotency=activation_registry,
            evidence_json={"test": "phase6-migrated-schema"},
        )
        session.expire(instance)
    session.commit()
    return account.id, instance.id


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)
def test_postgres_migrated_schema_funding_and_expiration_replay():
    engine = _migrated_engine()
    suffix = uuid.uuid4().hex[:8]
    try:
        with Session(engine, expire_on_commit=False) as session:
            account_id, instance_id = _seed_migrated_free(session, suffix)
            allocation, period, lot, state = allocate_recurring_credits(
                session, billing_account_id=account_id,
                entitlement_instance_id=instance_id, period_index=0,
                opened_at=ANCHOR, delivery_obligations=FUNDED_DELIVERIES,
                actor_type="system", actor_id="phase-6-migrated-test",
            )
            session.commit()
            registry_id = allocation.idempotency_registry_id
            completed_at = session.get(IdempotencyRegistry, registry_id).completed_at
            assert state == "inserted"

            replay = allocate_recurring_credits(
                session, billing_account_id=account_id,
                entitlement_instance_id=instance_id, period_index=0,
                opened_at=ANCHOR, delivery_obligations=FUNDED_DELIVERIES,
                actor_type="system", actor_id="phase-6-migrated-test",
            )
            session.commit()
            assert replay[3] == "duplicate"
            assert session.get(IdempotencyRegistry, registry_id).completed_at == completed_at

            expired, expiration_state = expire_recurring_credits(
                session, credit_period_id=period.id,
                expired_at=_utc(period.ends_at),
                delivery_obligations=EXPIRED_DELIVERIES,
                actor_type="system", actor_id="phase-6-migrated-test",
            )
            session.commit()
            assert expiration_state == "expired"
            assert expired.state == "expired"
            assert expire_recurring_credits(
                session, credit_period_id=period.id,
                expired_at=_utc(period.ends_at),
                delivery_obligations=EXPIRED_DELIVERIES,
                actor_type="system", actor_id="phase-6-migrated-test",
            )[1] == "duplicate"
            session.commit()
            assert session.query(CreditLot).filter_by(
                billing_account_id=account_id,
            ).count() == 1
            assert session.query(DomainEvent).filter_by(
                billing_account_id=account_id,
            ).count() == 2
            assert session.query(CommunicationOutbox).filter_by(
                billing_account_id=account_id,
            ).count() == 2
            assert ordered_lot_balances(
                session, account_id, _utc(period.ends_at),
            ) == []
    finally:
        engine.dispose()


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)
@pytest.mark.parametrize("isolation_level", (
    "READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE",
))
def test_postgres_migrated_concurrent_expiration_converges(isolation_level):
    engine = _migrated_engine()
    suffix = uuid.uuid4().hex[:8]
    try:
        with Session(engine, expire_on_commit=False) as seed:
            account_id, instance_id = _seed_migrated_free(seed, suffix)
            _allocation, period, lot, _state = allocate_recurring_credits(
                seed, billing_account_id=account_id,
                entitlement_instance_id=instance_id, period_index=0,
                opened_at=ANCHOR, delivery_obligations=FUNDED_DELIVERIES,
                actor_type="system", actor_id="phase-6-migrated-test",
            )
            seed.commit()
            period_id = period.id
            lot_id = lot.id
            period_end = _utc(period.ends_at)
        barrier = threading.Barrier(2)

        def expire():
            connection = engine.connect().execution_options(
                isolation_level=isolation_level,
            )
            try:
                with Session(connection) as session:
                    barrier.wait(timeout=10)
                    try:
                        outcome = expire_recurring_credits(
                            session, credit_period_id=period_id,
                            expired_at=period_end,
                            delivery_obligations=EXPIRED_DELIVERIES,
                            actor_type="system", actor_id="phase-6-migrated-test",
                        )[1]
                        session.commit()
                        return outcome
                    except sa.exc.DBAPIError as error:
                        session.rollback()
                        return getattr(error.orig, "sqlstate", None)
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _index: expire(), range(2)))
        assert outcomes.count("expired") == 1
        if isolation_level == "READ COMMITTED":
            assert sorted(outcomes) == ["duplicate", "expired"]
        else:
            assert set(outcomes) <= {"expired", "duplicate", "40001"}
        with Session(engine) as verify:
            assert verify.get(CreditPeriod, period_id).state == "expired"
            assert verify.query(CreditLedgerEntry).filter_by(
                lot_id=lot_id, entry_type="expiration",
            ).count() == 1
            assert verify.query(DomainEvent).filter_by(
                billing_account_id=account_id, event_type="credits_expired",
            ).count() == 1
    finally:
        engine.dispose()


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)
@pytest.mark.parametrize("isolation_level", (
    "READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE",
))
def test_postgres_migrated_expiration_races_held_allocation(isolation_level):
    engine = _migrated_engine()
    suffix = uuid.uuid4().hex[:8]
    try:
        with Session(engine, expire_on_commit=False) as seed:
            account_id, instance_id = _seed_migrated_free(seed, suffix)
            _allocation, period, lot, _state = allocate_recurring_credits(
                seed, billing_account_id=account_id,
                entitlement_instance_id=instance_id, period_index=0,
                opened_at=ANCHOR, delivery_obligations=FUNDED_DELIVERIES,
                actor_type="system", actor_id="phase-6-migrated-test",
            )
            seed.commit()
            period_id = period.id
            lot_id = lot.id
            period_end = _utc(period.ends_at)
        barrier = threading.Barrier(2)

        def expire():
            connection = engine.connect().execution_options(
                isolation_level=isolation_level,
            )
            try:
                with Session(connection) as session:
                    barrier.wait(timeout=10)
                    try:
                        outcome = expire_recurring_credits(
                            session, credit_period_id=period_id,
                            expired_at=period_end,
                            delivery_obligations=EXPIRED_DELIVERIES,
                            actor_type="system", actor_id="phase-6-migrated-test",
                        )[1]
                        session.commit()
                        return outcome
                    except sa.exc.DBAPIError as error:
                        session.rollback()
                        return getattr(error.orig, "sqlstate", None)
            finally:
                connection.close()

        def hold():
            connection = engine.connect().execution_options(
                isolation_level=isolation_level,
            )
            try:
                with Session(connection) as session:
                    registry = IdempotencyRegistry(
                        id=f"p6-race-hold-{suffix}", namespace="phase6_test_hold",
                        key=f"hold:{lot_id}", request_fingerprint="6" * 64,
                        state="claimed", claimed_at=ANCHOR,
                    )
                    session.add(registry)
                    session.flush()
                    barrier.wait(timeout=10)
                    try:
                        append_entry(session, CreditLedgerEntry(
                            id=f"p6-race-entry-{suffix}",
                            billing_account_id=account_id, lot_id=lot_id,
                            entry_type="dispute_hold", available_delta=-20,
                            held_delta=20, idempotency_registry_id=registry.id,
                            effective_at=ANCHOR, actor_type="test",
                            actor_id="phase-6-migrated-test",
                            reason_code="test_concurrent_hold",
                            evidence_json={"test": "phase6-held-race"},
                        ))
                        registry.state = "completed"
                        registry.completed_at = ANCHOR
                        registry.result_type = "credit_lot"
                        registry.result_id = lot_id
                        session.commit()
                        return "held"
                    except sa.exc.DBAPIError as error:
                        session.rollback()
                        return getattr(error.orig, "sqlstate", None)
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            expiration_future = pool.submit(expire)
            hold_future = pool.submit(hold)
            expiration_outcome = expiration_future.result()
            hold_outcome = hold_future.result()
        assert expiration_outcome in {"expired", "40001"}
        assert hold_outcome in {"held", "23514", "40001"}

        if expiration_outcome == "40001":
            with Session(engine) as retry:
                assert expire_recurring_credits(
                    retry, credit_period_id=period_id, expired_at=period_end,
                    delivery_obligations=EXPIRED_DELIVERIES,
                    actor_type="system", actor_id="phase-6-migrated-test",
                )[1] == "expired"
                retry.commit()

        with Session(engine) as verify:
            assert verify.get(CreditPeriod, period_id).state == "expired"
            totals = verify.execute(sa.select(
                sa.func.coalesce(sa.func.sum(CreditLedgerEntry.available_delta), 0),
                sa.func.coalesce(sa.func.sum(CreditLedgerEntry.held_delta), 0),
            ).where(CreditLedgerEntry.lot_id == lot_id)).one()
            assert tuple(map(int, totals)) == (0, 0)
            if hold_outcome == "held":
                assert verify.query(CreditLedgerEntry).filter_by(
                    lot_id=lot_id, entry_type="expiration",
                ).count() == 1
    finally:
        engine.dispose()
