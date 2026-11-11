"""Focused service/model coverage for the inactive Phase 4 foundation."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.billing_entitlements import (
    CREDIT_PERIOD_TRANSITIONS,
    ENTITLEMENT_TRANSITIONS,
    SUBSCRIPTION_TRANSITIONS,
    EntitlementInvariantError,
    add_calendar_months,
    fund_credit_period,
    monthly_period_bounds,
    new_credit_period,
    validate_definition_payloads,
)
from app.models import (
    BillingAccount,
    BillingSubscription,
    CreditLedgerEntry,
    CreditLot,
    CreditPeriod,
    EntitlementDefinition,
    EntitlementEvent,
    EntitlementInstance,
    IdempotencyRegistry,
    Organization,
)


NOW = datetime(2026, 1, 31, 15, 45, tzinfo=timezone.utc)
CAPABILITIES = {"schema_version": 1, "capabilities": {"analysis": True}}
FUNDING = {"schema_version": 1, "period_kind": "free", "credit_amount": 100}


def _claim(db, identifier):
    claim = IdempotencyRegistry(
        id=identifier, namespace="phase-4-test", key=identifier,
        request_fingerprint="a" * 64, state="claimed", claimed_at=NOW,
    )
    db.session.add(claim)
    db.session.flush()
    return claim


def _foundation(db, test_user, suffix="one"):
    organization = Organization(
        name=f"Phase 4 {suffix}", slug=f"phase-4-{suffix}",
        owner_user_id=test_user.id, plan_key="free",
    )
    db.session.add(organization)
    db.session.flush()
    account = BillingAccount(
        id=f"phase4-account-{suffix}", organization_id=organization.id,
        currency="usd", account_anchor_at=NOW,
    )
    definition = EntitlementDefinition(
        id=f"definition-{suffix}", key="free", version=1,
        exclusivity_key="base-plan", capability_json=CAPABILITIES,
        funding_policy_json=FUNDING, effective_at=NOW, approved_at=NOW,
        approval_evidence_reference="approval:test",
    )
    db.session.add_all([account, definition])
    db.session.flush()
    instance = EntitlementInstance(
        id=f"instance-{suffix}", billing_account_id=account.id,
        entitlement_definition_id=definition.id, state="proposed",
        starts_at=NOW, ends_at=add_calendar_months(NOW, 12),
        source_type="free", source_id=f"free-{suffix}",
        approval_evidence_reference="approval:test",
    )
    db.session.add(instance)
    db.session.flush()
    period = new_credit_period(
        billing_account_id=account.id, entitlement_instance_id=instance.id,
        subscription_id=None, kind="free", period_index=0,
        anchor_at=account.account_anchor_at, planned_allocation_amount=100,
    )
    db.session.add(period)
    db.session.commit()
    return account, definition, instance, period


def test_phase_4_tables_start_empty_and_do_not_replace_legacy_billing(db, test_user):
    assert test_user.subscription_plan == "free"
    for model in (
        EntitlementDefinition, BillingSubscription, EntitlementInstance,
        CreditPeriod, EntitlementEvent,
    ):
        assert db.session.query(model).count() == 0


def test_phase_4_policy_has_no_live_runtime_importers():
    app_dir = Path(__file__).resolve().parents[1] / "app"
    allowed = {"billing_entitlements.py", "models.py", "models_billing_phase4.py"}
    importers = []
    for path in app_dir.rglob("*.py"):
        if path.name not in allowed and "billing_entitlements" in path.read_text():
            importers.append(str(path.relative_to(app_dir)))
    assert importers == []


def test_transition_matrices_are_forward_only_and_terminal():
    assert SUBSCRIPTION_TRANSITIONS["past_due"] >= {"active", "unpaid"}
    assert SUBSCRIPTION_TRANSITIONS["cancel_at_period_end"] >= {"active", "expired"}
    assert not SUBSCRIPTION_TRANSITIONS["cancelled"]
    assert not SUBSCRIPTION_TRANSITIONS["expired"]
    assert ENTITLEMENT_TRANSITIONS["active"] == {"reducing", "expired"}
    assert not ENTITLEMENT_TRANSITIONS["superseded"]
    assert CREDIT_PERIOD_TRANSITIONS["unfunded"] == {"funded", "expired"}
    assert not CREDIT_PERIOD_TRANSITIONS["expired"]


def test_utc_calendar_month_end_leap_year_and_late_period_index():
    assert add_calendar_months(NOW, 1) == datetime(2026, 2, 28, 15, 45, tzinfo=timezone.utc)
    leap = datetime(2024, 1, 31, 3, 0, tzinfo=timezone.utc)
    assert add_calendar_months(leap, 1) == datetime(2024, 2, 29, 3, 0, tzinfo=timezone.utc)
    assert add_calendar_months(leap, 13) == datetime(2025, 2, 28, 3, 0, tzinfo=timezone.utc)
    assert monthly_period_bounds(NOW, 4) == (
        datetime(2026, 5, 31, 15, 45, tzinfo=timezone.utc),
        datetime(2026, 6, 30, 15, 45, tzinfo=timezone.utc),
    )
    with pytest.raises(EntitlementInvariantError, match="timezone-aware"):
        add_calendar_months(datetime(2026, 1, 1), 1)


def test_definition_contract_is_explicit_finite_and_never_unlimited():
    validate_definition_payloads(CAPABILITIES, FUNDING)
    invalid = [
        ({}, FUNDING),
        (CAPABILITIES, {**FUNDING, "credit_amount": None}),
        (CAPABILITIES, {**FUNDING, "credit_amount": -1}),
        ({"schema_version": 1, "capabilities": {"unlimited_credits": True}}, FUNDING),
        (CAPABILITIES, {**FUNDING, "unlimited": 1}),
    ]
    for capability, funding in invalid:
        with pytest.raises(EntitlementInvariantError):
            validate_definition_payloads(capability, funding)


def test_disposable_period_funding_uses_single_phase_3_lot_and_is_idempotent(db, test_user):
    account, _, _, period = _foundation(db, test_user, "funding")
    claim = _claim(db, "phase4-funding-claim")
    lot = fund_credit_period(
        db.session, period.id, claim, actor_type="test", actor_id="phase-4",
        evidence_json={"disposable_test": True, "financial_authority": False},
    )
    db.session.commit()
    same_lot = fund_credit_period(
        db.session, period.id, claim, actor_type="test", actor_id="phase-4",
        evidence_json={"disposable_test": True, "financial_authority": False},
    )
    assert same_lot.id == lot.id
    assert db.session.query(CreditLot).filter_by(billing_account_id=account.id).count() == 1
    assert db.session.query(CreditLedgerEntry).filter_by(lot_id=lot.id).count() == 1
    assert lot.source_id == period.id
    assert lot.original_amount == period.planned_allocation_amount
    assert lot.expires_at == period.ends_at
    assert period.funded_lot_id == lot.id
    assert period.state == "funded"
