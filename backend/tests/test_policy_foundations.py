"""Focused ORM coverage for the inactive Phase 2.2 foundations."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import (
    AIOperation,
    CapacityPolicyVersion,
    IdempotencyRegistry,
    PricingPolicyVersion,
    ProviderRateEntry,
)


NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


def _pricing_policy(identifier="pricing-draft", state="draft"):
    approved = state != "draft"
    return PricingPolicyVersion(
        id=identifier,
        version=identifier,
        state=state,
        effective_at=NOW + timedelta(days=1) if approved else None,
        approved_at=NOW if approved else None,
        credit_conversion_version="conversion-test-only",
        rounding_rule="ceil_whole_credit",
        conversion_json={"test_only": True},
        customer_credit_impact=False,
        notice_required=False,
    )


def _capacity_policy(identifier="capacity-draft", state="draft"):
    approved = state != "draft"
    return CapacityPolicyVersion(
        id=identifier,
        version=identifier,
        state=state,
        effective_at=NOW + timedelta(days=1) if approved else None,
        approved_at=NOW if approved else None,
        approval_evidence_reference="test-only-approval" if approved else None,
        rules_json={"test_only": True},
    )


def test_existing_application_activity_creates_no_foundation_rows(db, test_user):
    assert test_user.id
    assert db.session.query(IdempotencyRegistry).count() == 0
    assert db.session.query(PricingPolicyVersion).count() == 0
    assert db.session.query(ProviderRateEntry).count() == 0
    assert db.session.query(CapacityPolicyVersion).count() == 0


def test_phase_2_2_does_not_link_the_legacy_ai_operation_model():
    columns = set(AIOperation.__table__.columns.keys())

    assert "pricing_policy_version_id" not in columns
    assert "capacity_policy_version_id" not in columns
    assert "idempotency_registry_id" not in columns


def test_duplicate_idempotency_identity_cannot_replace_fingerprint(db):
    original = IdempotencyRegistry(
        id="claim-original",
        namespace="billing-command",
        key="stable-business-key",
        request_fingerprint="a" * 64,
        state="claimed",
        claimed_at=NOW,
    )
    db.session.add(original)
    db.session.commit()

    db.session.add(IdempotencyRegistry(
        id="claim-conflict",
        namespace="billing-command",
        key="stable-business-key",
        request_fingerprint="b" * 64,
        state="claimed",
        claimed_at=NOW,
    ))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    retained = db.session.get(IdempotencyRegistry, "claim-original")
    assert retained.request_fingerprint == "a" * 64
    assert db.session.query(IdempotencyRegistry).count() == 1


def test_approved_vocabularies_and_rate_constraints(db):
    policy = _pricing_policy()
    db.session.add(policy)
    db.session.flush()
    db.session.add(ProviderRateEntry(
        id="rate-valid",
        pricing_policy_version_id=policy.id,
        provider="test-provider",
        model="test-model",
        currency="usd",
        unit_basis="per_1m_tokens",
        input_rate=Decimal("0.0000000000"),
        output_rate=Decimal("0.0000000000"),
        source_reference="test-only-source",
        source_observed_at=NOW,
    ))
    db.session.commit()

    invalid = _pricing_policy("pricing-invalid")
    invalid.rounding_rule = "nearest_credit"
    db.session.add(invalid)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    db.session.add(ProviderRateEntry(
        id="rate-invalid-unit",
        pricing_policy_version_id=policy.id,
        provider="another-provider",
        model="another-model",
        currency="usd",
        unit_basis="per_token",
        input_rate=Decimal("0"),
        output_rate=Decimal("0"),
        source_reference="test-only-source",
        source_observed_at=NOW,
    ))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    db.session.add(ProviderRateEntry(
        id="rate-negative",
        pricing_policy_version_id=policy.id,
        provider="negative-provider",
        model="negative-model",
        currency="usd",
        unit_basis="per_1m_tokens",
        input_rate=Decimal("-0.0000000001"),
        output_rate=Decimal("0"),
        source_reference="test-only-source",
        source_observed_at=NOW,
    ))
    with pytest.raises(IntegrityError):
        db.session.commit()


def test_only_one_pricing_and_capacity_policy_can_be_effective(db):
    db.session.add(_pricing_policy("pricing-effective-one", "effective"))
    db.session.add(_capacity_policy("capacity-effective-one", "effective"))
    db.session.commit()

    db.session.add(_pricing_policy("pricing-effective-two", "effective"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    db.session.add(_capacity_policy("capacity-effective-two", "effective"))
    with pytest.raises(IntegrityError):
        db.session.commit()
