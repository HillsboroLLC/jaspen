"""Phase 7 upgrade, downgrade, cancellation, and schedule coverage."""

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import uuid

import pytest
import sqlalchemy as sa
from alembic.script import ScriptDirectory
from sqlalchemy.orm import Session

from app.billing_entitlements import add_calendar_months, append_entitlement_transition
from app.billing_allocations import _complete_registry_if_claimed
from app.billing_plan_changes import (
    PlanChangeConflictError,
    PlanChangeError,
    UPGRADE_NAMESPACE,
    _claim,
    _event,
    _fingerprint,
    _transition_schedule,
    activate_free_to_paid,
    apply_paid_upgrade,
    apply_scheduled_change,
    mark_scheduled_renewal_unpaid,
    resume_cancellation,
    schedule_plan_change,
)
from app.billing_inbox import claim_next_event, mark_processed
from app.models import (
    BillingSubscription,
    BillingAccount,
    CommunicationOutbox,
    CreditLedgerEntry,
    CreditLot,
    DomainEvent,
    EntitlementDefinition,
    EntitlementInstance,
    ExternalEventInbox,
    FinancialLine,
    FinancialTransaction,
    IdempotencyRegistry,
    Organization,
    PlanChangeEvent,
    RecurringCreditAllocation,
    ScheduledPlanChange,
    UpgradeCreditAllocation,
    User,
)
from test_recurring_credit_allocations import (
    ANCHOR, CAPABILITIES, _free_foundation, _migrated_engine,
    _subscription_foundation,
)


DELIVERIES = ({
    "template_key": "test-plan-change",
    "template_version": "test-v1",
    "channel": "test-channel",
    "locale": "en-US",
},)
FUNDING_DELIVERIES = ({
    "template_key": "test-period-funded",
    "template_version": "test-v1",
    "channel": "test-channel",
    "locale": "en-US",
},)
MIGRATIONS_DIR = str(Path(__file__).resolve().parents[1] / "migrations")


def _assert_phase7_model_schema(engine):
    script = ScriptDirectory(MIGRATIONS_DIR)
    assert script.get_heads() == ["a1f3c5e7b9d0"]  # I1 follows BI-1; BI-1 extends the Phase 17 guard, which extends Phase 14 without changing Phase 7.
    assert script.get_revision("a7d9e2f4b6c8").down_revision == "f5c8d3e0b2a1"
    inspector = sa.inspect(engine)
    for model in (ScheduledPlanChange, PlanChangeEvent, UpgradeCreditAllocation):
        table = model.__table__
        assert {column.name for column in table.columns} == {
            column["name"] for column in inspector.get_columns(table.name)
        }
        model_constraints = {
            constraint.name for constraint in table.constraints if constraint.name
        }
        database_constraints = {
            constraint["name"]
            for constraint in (
                inspector.get_check_constraints(table.name)
                + inspector.get_foreign_keys(table.name)
                + inspector.get_unique_constraints(table.name)
            )
            if constraint.get("name")
        }
        assert model_constraints - {table.primary_key.name} == database_constraints


def _utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _target(db, account, subscription, amount, *, state="proposed", starts_at=None, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    starts_at = starts_at or ANCHOR
    definition = EntitlementDefinition(
        id=f"p7-definition-{suffix}", key=f"p7-{amount}-{suffix}", version=1,
        exclusivity_key="base-plan", capability_json=CAPABILITIES,
        funding_policy_json={
            "schema_version": 1,
            "period_kind": "annual_monthly" if subscription.interval == "year" else "monthly_subscription",
            "credit_amount": amount,
        },
        effective_at=ANCHOR, approved_at=ANCHOR,
        approval_evidence_reference=f"approval:p7:{suffix}",
    )
    db.session.add(definition)
    db.session.flush()
    term_end = _utc(subscription.term_ends_at)
    ends_at = (
        add_calendar_months(starts_at, 12 if subscription.interval == "year" else 1)
        if starts_at >= term_end else term_end
    )
    instance = EntitlementInstance(
        id=f"p7-instance-{suffix}", billing_account_id=account.id,
        entitlement_definition_id=definition.id, subscription_id=subscription.id,
        state=state, starts_at=starts_at, ends_at=ends_at,
        source_type="subscription", source_id=f"{subscription.external_subscription_id}:p7:{suffix}",
        approval_evidence_reference=f"approval:p7:{suffix}",
    )
    db.session.add(instance)
    db.session.flush()
    return definition, instance


def _line(db, account, subscription, target, paid_at, suffix=None):
    suffix = suffix or uuid.uuid4().hex[:8]
    inbox = ExternalEventInbox(
        id=f"p7-inbox-{suffix}", provider="stripe", event_id=f"p7_evt_{suffix}",
        event_type="invoice.payment_succeeded", object_type="invoice",
        object_id=f"p7_in_{suffix}", payload_digest="d" * 64,
        summary_json={"schema_version": 1}, livemode=False,
        provider_created_at=paid_at, received_at=paid_at,
        state="processed", processed_at=paid_at,
    )
    db.session.add(inbox)
    db.session.flush()
    transaction = FinancialTransaction(
        id=f"p7-payment-{suffix}", billing_account_id=account.id,
        kind="payment", provider="stripe", object_type="invoice",
        object_id=f"p7_in_{suffix}", external_version="paid-v1",
        effective_at=paid_at, currency=account.currency, principal_minor=5000,
        tax_minor=0, fee_minor=0, discount_minor=0, gross_minor=5000,
        inbox_event_id=inbox.id,
    )
    db.session.add(transaction)
    db.session.flush()
    line = FinancialLine(
        id=f"p7-line-{suffix}", financial_transaction_id=transaction.id,
        external_line_id=f"p7_il_{suffix}", line_kind="subscription",
        source_type="stripe_price", source_id=f"price_{suffix}", quantity=1,
        currency=account.currency, principal_minor=5000, tax_minor=0, fee_minor=0,
        discount_minor=0, subscription_id=subscription.id,
        entitlement_instance_id=target.id,
    )
    db.session.add(line)
    db.session.flush()
    return line


def test_paid_upgrade_uses_integer_utc_floor_and_replays_once(db, test_user):
    account, _old_definition, prior, subscription, _old_line = _subscription_foundation(
        db, test_user, interval="month",
    )
    paid_at = datetime(2026, 2, 10, 15, 45, tzinfo=timezone.utc)
    new_definition, target = _target(db, account, subscription, 900, starts_at=paid_at)
    line = _line(db, account, subscription, target, paid_at)

    allocation, lot, state = apply_paid_upgrade(
        db.session, billing_account_id=account.id, subscription_id=subscription.id,
        prior_entitlement_instance_id=prior.id,
        target_entitlement_instance_id=target.id, financial_line_id=line.id,
        paid_at=paid_at, period_index=0, actor_type="system", actor_id="phase7-test",
        delivery_obligations=DELIVERIES,
    )
    db.session.commit()

    # Jan 31 -> Feb 28: 18 of 28 days remain; floor((900-500)*18/28).
    assert allocation.credit_amount == 257
    assert lot.original_amount == 257
    assert _utc(lot.expires_at) == datetime(2026, 2, 28, 15, 45, tzinfo=timezone.utc)
    assert _utc(subscription.anchor_at) == ANCHOR
    assert subscription.current_entitlement_definition_id == new_definition.id
    assert prior.state == "expired"
    assert target.state == "active"
    assert db.session.query(CreditLedgerEntry).filter_by(lot_id=lot.id).count() == 1
    assert db.session.query(CommunicationOutbox).filter_by(
        domain_event_id=allocation.domain_event_id,
    ).count() == 1

    replay = apply_paid_upgrade(
        db.session, billing_account_id=account.id, subscription_id=subscription.id,
        prior_entitlement_instance_id=prior.id,
        target_entitlement_instance_id=target.id, financial_line_id=line.id,
        paid_at=paid_at, period_index=0, actor_type="system", actor_id="phase7-test",
        delivery_obligations=DELIVERIES,
    )
    assert replay[0].id == allocation.id
    assert replay[2] == "duplicate"
    assert db.session.query(UpgradeCreditAllocation).filter_by(
        billing_account_id=account.id,
    ).count() == 1
    assert db.session.query(CreditLot).filter_by(id=lot.id).count() == 1


def test_paid_upgrade_zero_floor_records_evidence_without_a_lot(db, test_user):
    account, _old_definition, prior, subscription, _old_line = _subscription_foundation(
        db, test_user, interval="month",
    )
    paid_at = datetime(2026, 2, 28, 15, 45, tzinfo=timezone.utc)
    _new_definition, target = _target(db, account, subscription, 900, starts_at=paid_at)
    line = _line(db, account, subscription, target, paid_at)
    allocation, lot, state = apply_paid_upgrade(
        db.session, billing_account_id=account.id, subscription_id=subscription.id,
        prior_entitlement_instance_id=prior.id,
        target_entitlement_instance_id=target.id, financial_line_id=line.id,
        paid_at=paid_at, period_index=0, actor_type="system", actor_id="phase7-test",
        delivery_obligations=DELIVERIES,
    )
    db.session.commit()
    assert state == "inserted"
    assert allocation.credit_amount == 0
    assert allocation.funded_lot_id is None
    assert allocation.grant_entry_id is None
    assert lot is None


def test_paid_upgrade_supersedes_an_active_schedule(db, test_user):
    account, _old_definition, prior, subscription, _old_line = _subscription_foundation(
        db, test_user, interval="month",
    )
    effective = _utc(subscription.term_ends_at)
    lower, _lower_target = _target(
        db, account, subscription, 200, state="scheduled", starts_at=effective,
    )
    change, _ = schedule_plan_change(
        db.session, billing_account_id=account.id, subscription_id=subscription.id,
        client_command_id="lower-before-upgrade", kind="downgrade",
        target_entitlement_definition_id=lower.id, requested_at=ANCHOR,
        effective_at=effective, compatible_supersede=False, actor_type="user",
        actor_id="admin", delivery_obligations=DELIVERIES,
    )
    paid_at = datetime(2026, 2, 10, 15, 45, tzinfo=timezone.utc)
    _higher, target = _target(db, account, subscription, 900, starts_at=paid_at)
    line = _line(db, account, subscription, target, paid_at)
    allocation, _lot, state = apply_paid_upgrade(
        db.session, billing_account_id=account.id, subscription_id=subscription.id,
        prior_entitlement_instance_id=prior.id,
        target_entitlement_instance_id=target.id, financial_line_id=line.id,
        paid_at=paid_at, period_index=0, actor_type="system", actor_id="phase7-test",
        delivery_obligations=DELIVERIES,
    )
    db.session.commit()
    assert state == "inserted"
    assert allocation.credit_amount == 257
    assert change.state == "superseded"
    assert db.session.query(PlanChangeEvent).filter_by(
        scheduled_change_id=change.id, transition="superseded_by_paid_upgrade",
    ).count() == 1


def test_free_to_paid_opens_full_paid_period_without_proration(db, test_user):
    account, _free_definition, free = _free_foundation(db, test_user)
    paid_definition = EntitlementDefinition(
        id=f"p7-paid-{uuid.uuid4().hex[:8]}", key="p7-paid", version=1,
        exclusivity_key="base-plan", capability_json=CAPABILITIES,
        funding_policy_json={
            "schema_version": 1, "period_kind": "monthly_subscription",
            "credit_amount": 700,
        },
        effective_at=ANCHOR, approved_at=ANCHOR,
        approval_evidence_reference="approval:p7-paid",
    )
    subscription = BillingSubscription(
        id=f"p7-sub-{uuid.uuid4().hex[:8]}", billing_account_id=account.id,
        processor="stripe", external_subscription_id=f"sub_{uuid.uuid4().hex[:8]}",
        interval="month", anchor_at=ANCHOR, term_starts_at=ANCHOR,
        term_ends_at=add_calendar_months(ANCHOR, 1), state="proposed",
        current_entitlement_definition_id=paid_definition.id,
        origin_evidence_json={"test": "phase7-free-to-paid"},
    )
    db.session.add(paid_definition)
    db.session.flush()
    db.session.add(subscription)
    db.session.flush()
    target = EntitlementInstance(
        id=f"p7-paid-instance-{uuid.uuid4().hex[:8]}",
        billing_account_id=account.id, entitlement_definition_id=paid_definition.id,
        subscription_id=subscription.id, state="proposed", starts_at=ANCHOR,
        ends_at=subscription.term_ends_at, source_type="subscription",
        source_id=f"{subscription.external_subscription_id}:activation",
        approval_evidence_reference="approval:p7-paid",
    )
    db.session.add(target)
    db.session.flush()
    line = _line(db, account, subscription, target, ANCHOR)
    allocation, state = activate_free_to_paid(
        db.session, billing_account_id=account.id, subscription_id=subscription.id,
        free_entitlement_instance_id=free.id,
        target_entitlement_instance_id=target.id, financial_line_id=line.id,
        paid_at=ANCHOR, actor_type="system", actor_id="phase7-test",
        change_delivery_obligations=DELIVERIES,
        funding_delivery_obligations=FUNDING_DELIVERIES,
    )
    db.session.commit()
    lot = db.session.query(CreditLot).filter_by(
        billing_account_id=account.id, source_type="subscription_recurring",
    ).one()
    assert state == "inserted"
    assert allocation.credit_amount == 700
    assert lot.original_amount == 700
    assert free.state == "expired"
    assert target.state == "active"
    assert subscription.state == "active"


def test_failed_upgrade_preserves_existing_schedule_and_all_financial_state(db, test_user):
    account, _definition, prior, subscription, _line0 = _subscription_foundation(
        db, test_user, interval="month",
    )
    lower, _future = _target(
        db, account, subscription, 200, state="scheduled",
        starts_at=_utc(subscription.term_ends_at),
    )
    change, _ = schedule_plan_change(
        db.session, billing_account_id=account.id, subscription_id=subscription.id,
        client_command_id="lower-next-term", kind="downgrade",
        target_entitlement_definition_id=lower.id,
        requested_at=ANCHOR, effective_at=_utc(subscription.term_ends_at),
        compatible_supersede=False, actor_type="user", actor_id="admin",
        delivery_obligations=DELIVERIES,
    )
    db.session.commit()
    paid_at = datetime(2026, 2, 10, 15, 45, tzinfo=timezone.utc)
    _higher, target = _target(db, account, subscription, 900, starts_at=paid_at)
    bad_line = _line(db, account, subscription, target, paid_at)
    bad_line.principal_minor = 0
    db.session.flush()
    db.session.commit()

    with pytest.raises(PlanChangeError):
        apply_paid_upgrade(
            db.session, billing_account_id=account.id, subscription_id=subscription.id,
            prior_entitlement_instance_id=prior.id,
            target_entitlement_instance_id=target.id, financial_line_id=bad_line.id,
            paid_at=paid_at, period_index=0, actor_type="system", actor_id="phase7-test",
            delivery_obligations=DELIVERIES,
        )
    db.session.rollback()
    assert db.session.get(ScheduledPlanChange, change.id).state == "pending"
    assert db.session.get(EntitlementInstance, prior.id).state == "active"
    assert db.session.query(UpgradeCreditAllocation).filter_by(
        billing_account_id=account.id,
    ).count() == 0


def test_cancellation_supersedes_downgrade_and_history_is_retained(db, test_user):
    account, _definition, _prior, subscription, _line0 = _subscription_foundation(
        db, test_user, interval="month",
    )
    lower, _future = _target(
        db, account, subscription, 200, state="scheduled",
        starts_at=_utc(subscription.term_ends_at),
    )
    downgrade, _ = schedule_plan_change(
        db.session, billing_account_id=account.id, subscription_id=subscription.id,
        client_command_id="downgrade", kind="downgrade",
        target_entitlement_definition_id=lower.id, requested_at=ANCHOR,
        effective_at=_utc(subscription.term_ends_at), compatible_supersede=False,
        actor_type="user", actor_id="admin", delivery_obligations=DELIVERIES,
    )
    cancellation, _ = schedule_plan_change(
        db.session, billing_account_id=account.id, subscription_id=subscription.id,
        client_command_id="cancel", kind="cancellation",
        target_entitlement_definition_id=None,
        requested_at=ANCHOR, effective_at=_utc(subscription.term_ends_at),
        compatible_supersede=False, actor_type="user", actor_id="admin",
        delivery_obligations=DELIVERIES,
    )
    db.session.commit()
    assert downgrade.state == "superseded"
    assert cancellation.state == "pending"
    assert cancellation.supersedes_change_id == downgrade.id
    assert subscription.state == "cancel_at_period_end"
    assert db.session.query(ScheduledPlanChange).filter_by(
        billing_account_id=account.id,
    ).count() == 2
    assert db.session.query(PlanChangeEvent).filter_by(
        scheduled_change_id=downgrade.id, to_state="superseded",
    ).count() == 1

    anchor = _utc(subscription.anchor_at)
    resumed, resume_state = resume_cancellation(
        db.session, scheduled_change_id=cancellation.id,
        resumed_at=ANCHOR + timedelta(days=1), actor_type="user",
        actor_id="admin", delivery_obligations=DELIVERIES,
    )
    db.session.commit()
    assert resume_state == "inserted"
    assert resumed.state == "cancelled"
    assert subscription.state == "active"
    assert _utc(subscription.anchor_at) == anchor
    replay = resume_cancellation(
        db.session, scheduled_change_id=cancellation.id,
        resumed_at=ANCHOR + timedelta(days=1), actor_type="user",
        actor_id="admin", delivery_obligations=DELIVERIES,
    )
    assert replay[1] == "duplicate"
    with pytest.raises(PlanChangeConflictError):
        resume_cancellation(
            db.session, scheduled_change_id=cancellation.id,
            resumed_at=ANCHOR + timedelta(days=1), actor_type="user",
            actor_id="admin",
            delivery_obligations=({**DELIVERIES[0], "locale": "fr-CA"},),
        )
    db.session.rollback()


def test_downgrade_waits_for_payment_then_applies_and_funds(db, test_user):
    account, _definition, prior, subscription, _line0 = _subscription_foundation(
        db, test_user, interval="month",
    )
    effective = _utc(subscription.term_ends_at)
    lower, target = _target(
        db, account, subscription, 200, state="scheduled", starts_at=effective,
    )
    # The accepted Phase 6 fixture covers two monthly periods; make the target
    # and renewed subscription cover the new paid term.
    target.ends_at = add_calendar_months(effective, 1)
    change, _ = schedule_plan_change(
        db.session, billing_account_id=account.id, subscription_id=subscription.id,
        client_command_id="lower", kind="downgrade",
        target_entitlement_definition_id=lower.id, requested_at=ANCHOR,
        effective_at=effective, compatible_supersede=False,
        actor_type="user", actor_id="admin", delivery_obligations=DELIVERIES,
    )
    mark_scheduled_renewal_unpaid(
        db.session, scheduled_change_id=change.id, observed_at=effective,
        actor_type="system", actor_id="phase7-test", delivery_obligations=DELIVERIES,
    )
    db.session.commit()
    assert change.state == "awaiting_renewal_payment"
    assert prior.state == "active"
    assert subscription.current_entitlement_definition_id != lower.id
    line = _line(db, account, subscription, target, effective)
    applied, allocation, state = apply_scheduled_change(
        db.session, scheduled_change_id=change.id,
        target_entitlement_instance_id=target.id, financial_line_id=line.id,
        period_index=2, applied_at=effective, actor_type="system", actor_id="phase7-test",
        change_delivery_obligations=DELIVERIES,
        funding_delivery_obligations=FUNDING_DELIVERIES,
    )
    db.session.commit()
    assert state == "inserted"
    assert applied.state == "applied"
    assert allocation.credit_amount == 200
    assert subscription.current_entitlement_definition_id == lower.id
    assert prior.state == "expired"
    assert target.state == "active"


def test_cancellation_applies_at_paid_term_end_without_new_funding(db, test_user):
    account, _definition, prior, subscription, _line0 = _subscription_foundation(
        db, test_user, interval="month",
    )
    effective = _utc(subscription.term_ends_at)
    change, _ = schedule_plan_change(
        db.session, billing_account_id=account.id, subscription_id=subscription.id,
        client_command_id="cancel-at-end", kind="cancellation",
        target_entitlement_definition_id=None, requested_at=ANCHOR,
        effective_at=effective, compatible_supersede=False, actor_type="user",
        actor_id="admin", delivery_obligations=DELIVERIES,
    )
    applied, allocation, state = apply_scheduled_change(
        db.session, scheduled_change_id=change.id,
        target_entitlement_instance_id=None, financial_line_id=None,
        period_index=2, applied_at=effective, actor_type="system",
        actor_id="phase7-test", change_delivery_obligations=DELIVERIES,
        funding_delivery_obligations=(),
    )
    db.session.commit()
    assert state == "inserted"
    assert applied.state == "applied"
    assert allocation is None
    assert prior.state == "expired"
    assert subscription.state == "cancelled"
    assert db.session.query(RecurringCreditAllocation).filter_by(
        billing_account_id=account.id,
    ).count() == 0


def test_schedule_validation_failure_rolls_back_event_and_outbox(db, test_user):
    account, _definition, _prior, subscription, _line0 = _subscription_foundation(
        db, test_user, interval="month",
    )
    lower, _target_instance = _target(
        db, account, subscription, 200, state="scheduled",
        starts_at=_utc(subscription.term_ends_at),
    )
    before_events = db.session.query(DomainEvent).count()
    with pytest.raises(PlanChangeError):
        schedule_plan_change(
            db.session, billing_account_id=account.id, subscription_id=subscription.id,
            client_command_id="invalid", kind="downgrade",
            target_entitlement_definition_id=lower.id, requested_at=ANCHOR,
            effective_at=_utc(subscription.term_ends_at), compatible_supersede=False,
            actor_type="user", actor_id="admin", delivery_obligations=(),
        )
    db.session.rollback()
    assert db.session.query(ScheduledPlanChange).filter_by(
        billing_account_id=account.id,
    ).count() == 0
    assert db.session.query(DomainEvent).count() == before_events
    assert db.session.query(CommunicationOutbox).count() == 0


def test_second_unconfirmed_schedule_is_rejected(db, test_user):
    account, _definition, _prior, subscription, _line0 = _subscription_foundation(
        db, test_user, interval="month",
    )
    lower, _target_instance = _target(
        db, account, subscription, 200, state="scheduled",
        starts_at=_utc(subscription.term_ends_at),
    )
    schedule_plan_change(
        db.session, billing_account_id=account.id, subscription_id=subscription.id,
        client_command_id="one", kind="downgrade",
        target_entitlement_definition_id=lower.id, requested_at=ANCHOR,
        effective_at=_utc(subscription.term_ends_at), compatible_supersede=False,
        actor_type="user", actor_id="admin", delivery_obligations=DELIVERIES,
    )
    with pytest.raises(PlanChangeConflictError):
        schedule_plan_change(
            db.session, billing_account_id=account.id, subscription_id=subscription.id,
            client_command_id="two", kind="downgrade",
            target_entitlement_definition_id=lower.id, requested_at=ANCHOR,
            effective_at=_utc(subscription.term_ends_at), compatible_supersede=False,
            actor_type="user", actor_id="admin", delivery_obligations=DELIVERIES,
        )


def test_confirmed_compatible_schedule_supersedes_without_erasing_history(db, test_user):
    account, _definition, _prior, subscription, _line0 = _subscription_foundation(
        db, test_user, interval="month",
    )
    effective = _utc(subscription.term_ends_at)
    first_definition, _first_target = _target(
        db, account, subscription, 300, state="scheduled", starts_at=effective,
    )
    second_definition, _second_target = _target(
        db, account, subscription, 200, state="scheduled", starts_at=effective,
    )
    first, _ = schedule_plan_change(
        db.session, billing_account_id=account.id, subscription_id=subscription.id,
        client_command_id="compatible-one", kind="downgrade",
        target_entitlement_definition_id=first_definition.id, requested_at=ANCHOR,
        effective_at=effective, compatible_supersede=False, actor_type="user",
        actor_id="admin", delivery_obligations=DELIVERIES,
    )
    second, state = schedule_plan_change(
        db.session, billing_account_id=account.id, subscription_id=subscription.id,
        client_command_id="compatible-two", kind="downgrade",
        target_entitlement_definition_id=second_definition.id, requested_at=ANCHOR,
        effective_at=effective, compatible_supersede=True, actor_type="user",
        actor_id="admin", delivery_obligations=DELIVERIES,
    )
    db.session.commit()
    assert state == "inserted"
    assert first.state == "superseded"
    assert second.state == "pending"
    assert second.supersedes_change_id == first.id


def test_annual_downgrade_applies_only_at_paid_annual_renewal(db, test_user):
    account, _definition, prior, subscription, _line0 = _subscription_foundation(
        db, test_user, interval="year",
    )
    effective = _utc(subscription.term_ends_at)
    lower, target = _target(
        db, account, subscription, 200, state="scheduled", starts_at=effective,
    )
    change, _ = schedule_plan_change(
        db.session, billing_account_id=account.id, subscription_id=subscription.id,
        client_command_id="annual-lower", kind="downgrade",
        target_entitlement_definition_id=lower.id, requested_at=ANCHOR,
        effective_at=effective, compatible_supersede=False, actor_type="user",
        actor_id="admin", delivery_obligations=DELIVERIES,
    )
    line = _line(db, account, subscription, target, effective)
    applied, allocation, state = apply_scheduled_change(
        db.session, scheduled_change_id=change.id,
        target_entitlement_instance_id=target.id, financial_line_id=line.id,
        period_index=12, applied_at=effective, actor_type="system",
        actor_id="phase7-test", change_delivery_obligations=DELIVERIES,
        funding_delivery_obligations=FUNDING_DELIVERIES,
    )
    db.session.commit()
    assert state == "inserted"
    assert applied.state == "applied"
    assert allocation.period_kind == "annual_monthly"
    assert allocation.credit_amount == 200
    assert prior.state == "expired"
    assert target.state == "active"
    assert _utc(subscription.anchor_at) == ANCHOR


def _seed_migrated_paid_upgrade(
    session, suffix, *, old_amount=500, new_amount=900, paid_at=None,
):
    user = User(
        id=f"p7-user-{suffix}", email=f"p7-{suffix}@example.test",
        name="Phase 7 Test", password_hash="not-a-login-credential",
        subscription_plan="free", credits_remaining=0, seat_limit=1, max_seats=1,
    )
    organization = Organization(
        id=f"p7-org-{suffix}", name=f"Phase 7 {suffix}",
        slug=f"phase-7-{suffix}", owner_user_id=user.id, plan_key="free",
    )
    session.add(user)
    session.flush()
    session.add(organization)
    session.flush()
    account = BillingAccount(
        id=f"p7-account-{suffix}", organization_id=organization.id,
        status="active", currency="usd", account_anchor_at=ANCHOR,
    )
    old_definition = EntitlementDefinition(
        id=f"p7-old-definition-{suffix}", key=f"old-{suffix}", version=1,
        exclusivity_key="base-plan", capability_json=CAPABILITIES,
        funding_policy_json={
            "schema_version": 1, "period_kind": "monthly_subscription",
            "credit_amount": old_amount,
        },
        effective_at=ANCHOR, approved_at=ANCHOR,
        approval_evidence_reference="approval:p7-old",
    )
    new_definition = EntitlementDefinition(
        id=f"p7-new-definition-{suffix}", key=f"new-{suffix}", version=1,
        exclusivity_key="base-plan", capability_json=CAPABILITIES,
        funding_policy_json={
            "schema_version": 1, "period_kind": "monthly_subscription",
            "credit_amount": new_amount,
        },
        effective_at=ANCHOR, approved_at=ANCHOR,
        approval_evidence_reference="approval:p7-new",
    )
    session.add_all([account, old_definition, new_definition])
    session.flush()
    subscription = BillingSubscription(
        id=f"p7-subscription-{suffix}", billing_account_id=account.id,
        processor="stripe", external_subscription_id=f"p7_sub_{suffix}",
        interval="month", anchor_at=ANCHOR, term_starts_at=ANCHOR,
        term_ends_at=add_calendar_months(ANCHOR, 2), state="active",
        current_entitlement_definition_id=old_definition.id,
        origin_evidence_json={"test": "phase7-migrated"},
    )
    session.add(subscription)
    session.flush()
    prior = EntitlementInstance(
        id=f"p7-prior-{suffix}", billing_account_id=account.id,
        entitlement_definition_id=old_definition.id, subscription_id=subscription.id,
        state="proposed", starts_at=ANCHOR, ends_at=subscription.term_ends_at,
        source_type="subscription", source_id=f"p7_sub_{suffix}:old",
        approval_evidence_reference="approval:p7-old",
    )
    paid_at = paid_at or datetime(2026, 2, 10, 15, 45, tzinfo=timezone.utc)
    target = EntitlementInstance(
        id=f"p7-target-{suffix}", billing_account_id=account.id,
        entitlement_definition_id=new_definition.id, subscription_id=subscription.id,
        state="proposed", starts_at=paid_at, ends_at=subscription.term_ends_at,
        source_type="subscription", source_id=f"p7_sub_{suffix}:new",
        approval_evidence_reference="approval:p7-new",
    )
    session.add_all([prior, target])
    session.flush()
    for index, next_state in enumerate(("scheduled", "active")):
        registry = IdempotencyRegistry(
            id=f"p7-prior-transition-{index}-{suffix}", namespace="phase7_test_seed",
            key=f"p7-seed:{prior.id}:{next_state}", request_fingerprint=str(index + 1) * 64,
            state="claimed", claimed_at=ANCHOR,
        )
        session.add(registry)
        session.flush()
        append_entitlement_transition(
            session, instance_id=prior.id, next_state=next_state,
            transition=f"seed_{next_state}", effective_at=ANCHOR,
            actor_type="test", actor_id="phase7-test", source_type="test",
            source_id=f"phase7:{suffix}", idempotency=registry,
            evidence_json={"test": "phase7-migrated"},
        )
        session.expire(prior)
    inbox_now = datetime.now(timezone.utc)
    inbox = ExternalEventInbox(
        id=f"p7-inbox-{suffix}", provider="stripe", event_id=f"p7_evt_{suffix}",
        event_type="invoice.payment_succeeded", object_type="invoice",
        object_id=f"p7_invoice_{suffix}", payload_digest="e" * 64,
        summary_json={"schema_version": 1}, livemode=False,
        provider_created_at=paid_at, received_at=inbox_now,
        state="received",
    )
    session.add(inbox)
    session.flush()
    claimed = claim_next_event(session, now=inbox_now, lease_seconds=60)
    assert claimed.id == inbox.id
    mark_processed(
        session, inbox.id, claimed.attempt_count,
        now=inbox_now + timedelta(seconds=1),
    )
    transaction = FinancialTransaction(
        id=f"p7-payment-{suffix}", billing_account_id=account.id,
        kind="payment", provider="stripe", object_type="invoice",
        object_id=f"p7_invoice_{suffix}", external_version="paid-v1",
        effective_at=paid_at, currency="usd", principal_minor=5000,
        tax_minor=0, fee_minor=0, discount_minor=0, gross_minor=5000,
        inbox_event_id=inbox.id,
    )
    session.add(transaction)
    session.flush()
    line = FinancialLine(
        id=f"p7-line-{suffix}", financial_transaction_id=transaction.id,
        external_line_id=f"p7_il_{suffix}", line_kind="subscription",
        source_type="stripe_price", source_id=f"price_{suffix}", quantity=1,
        currency="usd", principal_minor=5000, tax_minor=0, fee_minor=0,
        discount_minor=0, subscription_id=subscription.id,
        entitlement_instance_id=target.id,
    )
    session.add(line)
    session.commit()
    return account.id, subscription.id, prior.id, target.id, line.id, paid_at


def _add_migrated_lower_schedule_target(session, account_id, subscription_id, suffix):
    subscription = session.get(BillingSubscription, subscription_id)
    effective = _utc(subscription.term_ends_at)
    definition = EntitlementDefinition(
        id=f"p7-lower-definition-{suffix}", key=f"lower-{suffix}", version=1,
        exclusivity_key="base-plan", capability_json=CAPABILITIES,
        funding_policy_json={
            "schema_version": 1, "period_kind": "monthly_subscription",
            "credit_amount": 200,
        },
        effective_at=ANCHOR, approved_at=ANCHOR,
        approval_evidence_reference="approval:p7-lower",
    )
    session.add(definition)
    session.flush()
    target = EntitlementInstance(
        id=f"p7-lower-instance-{suffix}", billing_account_id=account_id,
        entitlement_definition_id=definition.id, subscription_id=subscription_id,
        state="proposed", starts_at=effective, ends_at=add_calendar_months(effective, 1),
        source_type="subscription", source_id=f"{subscription.external_subscription_id}:lower:{suffix}",
        approval_evidence_reference="approval:p7-lower",
    )
    session.add(target)
    session.flush()
    registry = IdempotencyRegistry(
        id=f"p7-lower-transition-{suffix}", namespace="phase7_test_seed",
        key=f"p7-seed:{target.id}:scheduled", request_fingerprint="7" * 64,
        state="claimed", claimed_at=ANCHOR,
    )
    session.add(registry)
    session.flush()
    append_entitlement_transition(
        session, instance_id=target.id, next_state="scheduled",
        transition="seed_schedule", effective_at=effective,
        actor_type="test", actor_id="phase7-test", source_type="test",
        source_id=f"phase7-lower:{suffix}", idempotency=registry,
        evidence_json={"test": "phase7-migrated-schedule"},
    )
    session.commit()
    return definition.id, target.id, effective


def _add_migrated_paid_line(session, account_id, subscription_id, target_id, paid_at, suffix):
    now = datetime.now(timezone.utc)
    inbox = ExternalEventInbox(
        id=f"p7-renewal-inbox-{suffix}", provider="stripe",
        event_id=f"p7_renewal_evt_{suffix}", event_type="invoice.payment_succeeded",
        object_type="invoice", object_id=f"p7_renewal_invoice_{suffix}",
        payload_digest="f" * 64, summary_json={"schema_version": 1}, livemode=False,
        provider_created_at=paid_at, received_at=now, state="received",
    )
    session.add(inbox)
    session.flush()
    claimed = claim_next_event(session, now=now, lease_seconds=60)
    assert claimed.id == inbox.id
    mark_processed(session, inbox.id, claimed.attempt_count, now=now + timedelta(seconds=1))
    transaction = FinancialTransaction(
        id=f"p7-renewal-payment-{suffix}", billing_account_id=account_id,
        kind="payment", provider="stripe", object_type="invoice",
        object_id=f"p7_renewal_invoice_{suffix}", external_version="paid-v1",
        effective_at=paid_at, currency="usd", principal_minor=4000,
        tax_minor=0, fee_minor=0, discount_minor=0, gross_minor=4000,
        inbox_event_id=inbox.id,
    )
    session.add(transaction)
    session.flush()
    line = FinancialLine(
        id=f"p7-renewal-line-{suffix}", financial_transaction_id=transaction.id,
        external_line_id=f"p7_renewal_il_{suffix}", line_kind="subscription",
        source_type="stripe_price", source_id=f"lower_price_{suffix}", quantity=1,
        currency="usd", principal_minor=4000, tax_minor=0, fee_minor=0,
        discount_minor=0, subscription_id=subscription_id,
        entitlement_instance_id=target_id,
    )
    session.add(line)
    session.commit()
    return line.id


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)
def test_postgres_migrated_paid_upgrade_and_direct_guard_contract():
    engine = _migrated_engine()
    suffix = uuid.uuid4().hex[:8]
    try:
        _assert_phase7_model_schema(engine)
        with Session(engine, expire_on_commit=False) as session:
            account_id, subscription_id, prior_id, target_id, line_id, paid_at = (
                _seed_migrated_paid_upgrade(session, suffix)
            )
            allocation, lot, state = apply_paid_upgrade(
                session, billing_account_id=account_id, subscription_id=subscription_id,
                prior_entitlement_instance_id=prior_id,
                target_entitlement_instance_id=target_id, financial_line_id=line_id,
                paid_at=paid_at, period_index=0, actor_type="system",
                actor_id="phase7-migrated-test", delivery_obligations=DELIVERIES,
            )
            session.commit()
            assert state == "inserted"
            assert allocation.credit_amount == 257
            assert lot.original_amount == 257
            assert session.query(UpgradeCreditAllocation).filter_by(
                billing_account_id=account_id,
            ).count() == 1
            replay = apply_paid_upgrade(
                session, billing_account_id=account_id, subscription_id=subscription_id,
                prior_entitlement_instance_id=prior_id,
                target_entitlement_instance_id=target_id, financial_line_id=line_id,
                paid_at=paid_at, period_index=0, actor_type="system",
                actor_id="phase7-migrated-test", delivery_obligations=DELIVERIES,
            )
            session.commit()
            assert replay[2] == "duplicate"

            old_amount = allocation.old_period_amount
            new_amount = allocation.new_period_amount
            for label, forged_old, forged_new, forged_start, forged_end in (
                (
                    "inflated", old_amount, new_amount + 1000,
                    _utc(allocation.period_starts_at), _utc(allocation.period_ends_at),
                ),
                (
                    "boundaries", old_amount, new_amount,
                    _utc(allocation.period_starts_at) + timedelta(days=1),
                    _utc(allocation.period_ends_at) + timedelta(days=1),
                ),
            ):
                forged_id = f"p7-forged-{label}-{suffix}"
                forged_key = f"upgrade:{subscription_id}:forged-{label}:{paid_at.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                forged_fingerprint = _fingerprint({"forgery": label, "id": forged_id})
                registry, inserted = _claim(
                    session, UPGRADE_NAMESPACE, forged_key,
                    forged_fingerprint, paid_at,
                )
                assert inserted
                domain_event, _messages, event_state = _event(session, {
                    "billing_account_id": account_id,
                    "event_key": f"plan_change_applied:upgrade:{forged_id}",
                    "event_type": "plan_change_applied",
                    "aggregate_type": "upgrade_credit_allocation",
                    "aggregate_id": forged_id, "occurred_at": paid_at,
                    "reference_ids": [
                        forged_id, subscription_id, prior_id, target_id, line_id,
                    ],
                }, DELIVERIES)
                assert event_state == "inserted"
                forged_total = int((forged_end - forged_start).total_seconds())
                forged_remaining = max(0, int((forged_end - paid_at).total_seconds()))
                forged_credit = ((forged_new - forged_old) * forged_remaining) // forged_total
                with pytest.raises(sa.exc.IntegrityError):
                    session.execute(sa.text("""
                        INSERT INTO upgrade_credit_allocations (
                          id,billing_account_id,subscription_id,
                          prior_entitlement_instance_id,target_entitlement_instance_id,
                          financial_line_id,idempotency_registry_id,domain_event_id,
                          funded_lot_id,grant_entry_id,allocation_key,request_fingerprint,
                          old_period_amount,new_period_amount,period_starts_at,
                          period_ends_at,paid_at,credit_amount
                        ) VALUES (
                          :id,:account,:subscription,:prior,:target,:line,:registry,
                          :event,:lot,:entry,:key,:fingerprint,:old,:new,:starts,
                          :ends,:paid,:credit
                        )
                    """), {
                        "id": forged_id, "account": account_id,
                        "subscription": subscription_id, "prior": prior_id,
                        "target": target_id, "line": line_id,
                        "registry": registry.id, "event": domain_event.id,
                        "lot": f"p7-forged-lot-{label}-{suffix}",
                        "entry": f"p7-forged-entry-{label}-{suffix}",
                        "key": forged_key, "fingerprint": forged_fingerprint,
                        "old": forged_old, "new": forged_new,
                        "starts": forged_start, "ends": forged_end,
                        "paid": paid_at, "credit": forged_credit,
                    })
                    session.execute(sa.text("""
                        INSERT INTO credit_lots (
                          id,billing_account_id,source_type,source_id,
                          original_amount,available_at,expires_at,origin_evidence_json
                        ) VALUES (
                          :lot,:account,'subscription_recurring',:allocation,
                          :credit,:paid,:ends,CAST(:evidence AS jsonb)
                        )
                    """), {
                        "lot": f"p7-forged-lot-{label}-{suffix}",
                        "account": account_id, "allocation": forged_id,
                        "credit": forged_credit, "paid": paid_at,
                        "ends": forged_end,
                        "evidence": json.dumps({"upgrade_credit_allocation_id": forged_id}),
                    })
                    session.execute(sa.text("""
                        INSERT INTO credit_ledger_entries (
                          id,billing_account_id,lot_id,entry_type,available_delta,
                          held_delta,idempotency_registry_id,effective_at,actor_type,
                          actor_id,reason_code,evidence_json
                        ) VALUES (
                          :entry,:account,:lot,'grant',:credit,0,:registry,:paid,
                          'test','forged-direct-sql','upgrade_proration',
                          CAST(:evidence AS jsonb)
                        )
                    """), {
                        "entry": f"p7-forged-entry-{label}-{suffix}",
                        "account": account_id,
                        "lot": f"p7-forged-lot-{label}-{suffix}",
                        "credit": forged_credit, "registry": registry.id,
                        "paid": paid_at,
                        "evidence": json.dumps({"upgrade_credit_allocation_id": forged_id}),
                    })
                    _complete_registry_if_claimed(
                        session, registry, completed_at=paid_at,
                        result_type="upgrade_credit_allocation", result_id=forged_id,
                    )
                    session.commit()
                session.rollback()

            prior_definition_id = session.get(
                EntitlementInstance, prior_id,
            ).entitlement_definition_id
            with pytest.raises(sa.exc.IntegrityError):
                session.execute(sa.text("""
                    UPDATE billing_subscriptions
                    SET current_entitlement_definition_id=:definition
                    WHERE id=:subscription
                """), {
                    "definition": prior_definition_id,
                    "subscription": subscription_id,
                })
                session.commit()
            session.rollback()

            with pytest.raises(sa.exc.IntegrityError):
                session.execute(sa.text("""
                    INSERT INTO credit_lots (
                      id,billing_account_id,source_type,source_id,original_amount,
                      available_at,expires_at,origin_evidence_json
                    ) VALUES (
                      :id,:account,'subscription_recurring','direct-phase7-bypass',1,
                      :paid_at,:expires_at,CAST(:evidence AS jsonb)
                    )
                """), {
                    "id": f"p7-direct-lot-{suffix}", "account": account_id,
                    "paid_at": paid_at,
                    "expires_at": datetime(2026, 2, 28, 15, 45, tzinfo=timezone.utc),
                    "evidence": '{"direct":true}',
                })
                session.commit()
            session.rollback()

            with pytest.raises(sa.exc.IntegrityError):
                session.execute(sa.text(
                    "UPDATE upgrade_credit_allocations SET credit_amount=credit_amount+1 WHERE id=:id"
                ), {"id": allocation.id})
                session.commit()
            session.rollback()

            with pytest.raises(sa.exc.IntegrityError):
                session.execute(sa.text("TRUNCATE upgrade_credit_allocations CASCADE"))
                session.commit()
            session.rollback()
    finally:
        engine.dispose()


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)
def test_postgres_fractional_second_proration_uses_floor_consistently():
    engine = _migrated_engine()
    suffix = uuid.uuid4().hex[:8]
    paid_at = datetime(2026, 2, 10, 15, 45, 0, 400000, tzinfo=timezone.utc)
    try:
        with Session(engine, expire_on_commit=False) as session:
            account_id, subscription_id, prior_id, target_id, line_id, _paid_at = (
                _seed_migrated_paid_upgrade(
                    session, suffix, old_amount=500, new_amount=2_419_700,
                    paid_at=paid_at,
                )
            )
            allocation, lot, state = apply_paid_upgrade(
                session, billing_account_id=account_id,
                subscription_id=subscription_id,
                prior_entitlement_instance_id=prior_id,
                target_entitlement_instance_id=target_id,
                financial_line_id=line_id, paid_at=paid_at, period_index=0,
                actor_type="system", actor_id="phase7-fractional-test",
                delivery_obligations=DELIVERIES,
            )
            session.commit()
            assert state == "inserted"
            assert allocation.credit_amount == 1_555_199
            assert lot.original_amount == 1_555_199
    finally:
        engine.dispose()


_BIGINT_MAX = 9_223_372_036_854_775_807


def _large_upgrade_amounts(paid_at, old_amount=500):
    """A valid new amount near the bigint limit whose exact proration has a
    fractional part of at least one half, so the guard must use an exact
    integer quotient: the old bigint product overflows, and a rounded numeric
    quotient would come out one too high."""
    from app.billing_entitlements import monthly_period_bounds
    start, end = monthly_period_bounds(ANCHOR, 0)
    total = int((end - start).total_seconds())
    remaining = max(0, int((end - paid_at).total_seconds()))
    for new_amount in range(_BIGINT_MAX, _BIGINT_MAX - 10_000, -1):
        product = (new_amount - old_amount) * remaining
        if product > _BIGINT_MAX and 2 * (product % total) >= total:
            return new_amount, product // total
    raise AssertionError("no qualifying amount found")


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)
def test_postgres_large_credit_upgrade_prorates_exactly_without_overflow():
    engine = _migrated_engine()
    suffix = uuid.uuid4().hex[:8]
    paid_at = datetime(2026, 2, 10, 15, 45, tzinfo=timezone.utc)
    new_amount, expected_credit = _large_upgrade_amounts(paid_at)
    try:
        with Session(engine, expire_on_commit=False) as session:
            account_id, subscription_id, prior_id, target_id, line_id, _paid_at = (
                _seed_migrated_paid_upgrade(
                    session, suffix, old_amount=500, new_amount=new_amount,
                    paid_at=paid_at,
                )
            )
            allocation, lot, state = apply_paid_upgrade(
                session, billing_account_id=account_id,
                subscription_id=subscription_id,
                prior_entitlement_instance_id=prior_id,
                target_entitlement_instance_id=target_id,
                financial_line_id=line_id, paid_at=paid_at, period_index=0,
                actor_type="system", actor_id="phase7-overflow-test",
                delivery_obligations=DELIVERIES,
            )
            session.commit()  # the deferred guard runs here
            assert state == "inserted"
            assert allocation.credit_amount == expected_credit
            assert lot.original_amount == expected_credit
            stored = session.execute(sa.text(
                "SELECT credit_amount FROM upgrade_credit_allocations WHERE id=:id"
            ), {"id": allocation.id}).scalar_one()
            assert stored == expected_credit
    finally:
        engine.dispose()


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)
def test_postgres_upgrade_amount_beyond_bigint_is_rejected_without_evidence():
    """Adversarial: a target amount one past the bigint limit never becomes an
    approved definition, so no proration can be computed from it."""
    engine = _migrated_engine()
    suffix = uuid.uuid4().hex[:8]
    paid_at = datetime(2026, 2, 10, 15, 45, tzinfo=timezone.utc)
    try:
        with Session(engine, expire_on_commit=False) as session:
            with pytest.raises(sa.exc.IntegrityError, match="credit_amount must be a finite nonnegative integer"):
                _seed_migrated_paid_upgrade(
                    session, suffix, old_amount=500, new_amount=_BIGINT_MAX + 1,
                    paid_at=paid_at,
                )
            session.rollback()
            assert session.query(EntitlementDefinition).filter(
                EntitlementDefinition.id.in_([
                    f"p7-old-definition-{suffix}", f"p7-new-definition-{suffix}",
                ]),
            ).count() == 0
            assert session.query(UpgradeCreditAllocation).filter_by(
                billing_account_id=f"p7-account-{suffix}",
            ).count() == 0
    finally:
        engine.dispose()


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)
def test_postgres_migrated_schedule_precedence_replay_and_direct_fence():
    engine = _migrated_engine()
    suffix = uuid.uuid4().hex[:8]
    try:
        with Session(engine, expire_on_commit=False) as session:
            account_id, subscription_id, _prior, _target, _line, _paid_at = (
                _seed_migrated_paid_upgrade(session, suffix)
            )
            lower_id, _lower_instance_id, effective = _add_migrated_lower_schedule_target(
                session, account_id, subscription_id, suffix,
            )
            downgrade, state = schedule_plan_change(
                session, billing_account_id=account_id, subscription_id=subscription_id,
                client_command_id="migrated-downgrade", kind="downgrade",
                target_entitlement_definition_id=lower_id, requested_at=ANCHOR,
                effective_at=effective, compatible_supersede=False,
                actor_type="user", actor_id="phase7-test",
                delivery_obligations=DELIVERIES,
            )
            session.commit()
            assert state == "inserted"
            replay = schedule_plan_change(
                session, billing_account_id=account_id, subscription_id=subscription_id,
                client_command_id="migrated-downgrade", kind="downgrade",
                target_entitlement_definition_id=lower_id, requested_at=ANCHOR,
                effective_at=effective, compatible_supersede=False,
                actor_type="user", actor_id="phase7-test",
                delivery_obligations=DELIVERIES,
            )
            session.commit()
            assert replay[1] == "duplicate"
            cancellation, state = schedule_plan_change(
                session, billing_account_id=account_id, subscription_id=subscription_id,
                client_command_id="migrated-cancel", kind="cancellation",
                target_entitlement_definition_id=None, requested_at=ANCHOR,
                effective_at=effective, compatible_supersede=False,
                actor_type="user", actor_id="phase7-test",
                delivery_obligations=DELIVERIES,
            )
            session.commit()
            assert state == "inserted"
            assert session.get(ScheduledPlanChange, downgrade.id).state == "superseded"
            assert cancellation.state == "pending"
            anchor = _utc(session.get(BillingSubscription, subscription_id).anchor_at)
            resumed, resume_state = resume_cancellation(
                session, scheduled_change_id=cancellation.id,
                resumed_at=ANCHOR + timedelta(days=1), actor_type="user",
                actor_id="phase7-test", delivery_obligations=DELIVERIES,
            )
            session.commit()
            assert resume_state == "inserted"
            assert resumed.state == "cancelled"
            subscription = session.get(BillingSubscription, subscription_id)
            assert subscription.state == "active"
            assert _utc(subscription.anchor_at) == anchor
            with pytest.raises(sa.exc.IntegrityError):
                session.execute(sa.text("""
                    INSERT INTO scheduled_plan_changes (
                      id,billing_account_id,subscription_id,target_entitlement_definition_id,
                      kind,effective_rule,effective_at,state,command_key,request_fingerprint,
                      idempotency_registry_id,domain_event_id
                    ) VALUES (
                      :id,:account,:subscription,:target,'downgrade','next_monthly_renewal',
                      :effective,'pending','direct-bypass',:fingerprint,:registry,:event
                    )
                """), {
                    "id": f"p7-direct-schedule-{suffix}", "account": account_id,
                    "subscription": subscription_id, "target": lower_id,
                    "effective": effective, "fingerprint": "a" * 64,
                    "registry": cancellation.idempotency_registry_id,
                    "event": cancellation.domain_event_id,
                })
                session.commit()
            session.rollback()
    finally:
        engine.dispose()


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)
def test_postgres_migrated_downgrade_failure_then_paid_application():
    engine = _migrated_engine()
    suffix = uuid.uuid4().hex[:8]
    try:
        with Session(engine, expire_on_commit=False) as session:
            account_id, subscription_id, prior_id, _target, _line, _paid_at = (
                _seed_migrated_paid_upgrade(session, suffix)
            )
            lower_id, lower_instance_id, effective = _add_migrated_lower_schedule_target(
                session, account_id, subscription_id, suffix,
            )
            change, _state = schedule_plan_change(
                session, billing_account_id=account_id, subscription_id=subscription_id,
                client_command_id="migrated-lower", kind="downgrade",
                target_entitlement_definition_id=lower_id, requested_at=ANCHOR,
                effective_at=effective, compatible_supersede=False,
                actor_type="user", actor_id="phase7-test",
                delivery_obligations=DELIVERIES,
            )
            session.commit()
            with pytest.raises(sa.exc.IntegrityError):
                _transition_schedule(
                    session, change=change, to_state="applied",
                    transition="downgrade_applied", effective_at=effective,
                    actor_type="system", actor_id="forged-direct-application",
                    evidence={"recurring_credit_allocation_id": None},
                    delivery_obligations=DELIVERIES,
                )
                session.commit()
            session.rollback()
            change = session.get(ScheduledPlanChange, change.id)
            assert change.state == "pending"
            mark_scheduled_renewal_unpaid(
                session, scheduled_change_id=change.id, observed_at=effective,
                actor_type="system", actor_id="phase7-test",
                delivery_obligations=DELIVERIES,
            )
            session.commit()
            assert session.get(ScheduledPlanChange, change.id).state == "awaiting_renewal_payment"
            assert session.get(EntitlementInstance, prior_id).state == "active"
            line_id = _add_migrated_paid_line(
                session, account_id, subscription_id, lower_instance_id, effective, suffix,
            )
            applied, allocation, state = apply_scheduled_change(
                session, scheduled_change_id=change.id,
                target_entitlement_instance_id=lower_instance_id,
                financial_line_id=line_id, period_index=2, applied_at=effective,
                actor_type="system", actor_id="phase7-test",
                change_delivery_obligations=DELIVERIES,
                funding_delivery_obligations=FUNDING_DELIVERIES,
            )
            session.commit()
            assert state == "inserted"
            assert applied.state == "applied"
            assert allocation.credit_amount == 200
            assert session.get(EntitlementInstance, prior_id).state == "expired"
            assert session.get(EntitlementInstance, lower_instance_id).state == "active"
            assert session.get(BillingSubscription, subscription_id).current_entitlement_definition_id == lower_id
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
def test_postgres_concurrent_paid_upgrade_converges(isolation_level):
    engine = _migrated_engine()
    suffix = uuid.uuid4().hex[:8]
    try:
        with Session(engine, expire_on_commit=False) as seed_session:
            args = _seed_migrated_paid_upgrade(seed_session, suffix)
        account_id, subscription_id, prior_id, target_id, line_id, paid_at = args
        worker_engine = engine.execution_options(isolation_level=isolation_level)

        def run_upgrade(_index):
            with Session(worker_engine, expire_on_commit=False) as session:
                try:
                    result = apply_paid_upgrade(
                        session, billing_account_id=account_id,
                        subscription_id=subscription_id,
                        prior_entitlement_instance_id=prior_id,
                        target_entitlement_instance_id=target_id,
                        financial_line_id=line_id, paid_at=paid_at, period_index=0,
                        actor_type="system", actor_id="phase7-concurrency-test",
                        delivery_obligations=DELIVERIES,
                    )
                    session.commit()
                    return result[2]
                except sa.exc.DBAPIError as exc:
                    session.rollback()
                    code = getattr(exc.orig, "sqlstate", None)
                    if code in {"40001", "40P01"}:
                        return code
                    raise

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(run_upgrade, range(2)))
        assert outcomes.count("inserted") == 1
        assert set(outcomes) <= {"inserted", "duplicate", "40001", "40P01"}
        if isolation_level == "READ COMMITTED":
            assert sorted(outcomes) == ["duplicate", "inserted"]
        with Session(engine) as verify:
            assert verify.query(UpgradeCreditAllocation).filter_by(
                billing_account_id=account_id,
            ).count() == 1
            assert verify.query(CreditLot).filter_by(
                billing_account_id=account_id, source_type="subscription_recurring",
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
def test_postgres_competing_schedule_commands_keep_one_active(isolation_level):
    engine = _migrated_engine()
    suffix = uuid.uuid4().hex[:8]
    try:
        with Session(engine, expire_on_commit=False) as seed_session:
            account_id, subscription_id, _prior, _target, _line, _paid_at = (
                _seed_migrated_paid_upgrade(seed_session, suffix)
            )
            lower_id, _lower_instance_id, effective = _add_migrated_lower_schedule_target(
                seed_session, account_id, subscription_id, suffix,
            )
        worker_engine = engine.execution_options(isolation_level=isolation_level)

        def schedule(index):
            with Session(worker_engine, expire_on_commit=False) as session:
                try:
                    _change, state = schedule_plan_change(
                        session, billing_account_id=account_id,
                        subscription_id=subscription_id,
                        client_command_id=f"competing-{index}", kind="downgrade",
                        target_entitlement_definition_id=lower_id,
                        requested_at=ANCHOR, effective_at=effective,
                        compatible_supersede=False, actor_type="user",
                        actor_id="phase7-concurrency-test",
                        delivery_obligations=DELIVERIES,
                    )
                    session.commit()
                    return state
                except PlanChangeConflictError:
                    session.rollback()
                    return "conflict"
                except sa.exc.DBAPIError as exc:
                    session.rollback()
                    code = getattr(exc.orig, "sqlstate", None)
                    if code in {"23505", "40001", "40P01"}:
                        return code
                    raise

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(schedule, range(2)))
        assert outcomes.count("inserted") == 1
        assert set(outcomes) <= {"inserted", "conflict", "23505", "40001", "40P01"}
        with Session(engine) as verify:
            active = verify.query(ScheduledPlanChange).filter(
                ScheduledPlanChange.billing_account_id == account_id,
                ScheduledPlanChange.state.in_(("pending", "awaiting_renewal_payment")),
            ).all()
            assert len(active) == 1
    finally:
        engine.dispose()
