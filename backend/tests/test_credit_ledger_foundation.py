"""Focused ORM/service coverage for the inactive Phase 3 credit ledger."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.billing_ledger import (
    CreditLedgerInvariantError,
    append_entry,
    ordered_lot_balances,
)
from app.models import (
    BillingAccount,
    CreditLedgerEntry,
    CreditLot,
    IdempotencyRegistry,
    Organization,
)


NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


def _account(db, test_user, suffix):
    organization = Organization(
        name=f"Phase 3 ledger organization {suffix}",
        slug=f"phase-3-ledger-organization-{suffix}",
        owner_user_id=test_user.id,
        plan_key="free",
    )
    db.session.add(organization)
    db.session.flush()
    account = BillingAccount(
        id=f"ledger-account-{suffix}",
        organization_id=organization.id,
        currency="usd",
        account_anchor_at=NOW,
    )
    db.session.add(account)
    db.session.commit()
    return account


def _claim(db, identifier):
    claim = IdempotencyRegistry(
        id=identifier,
        namespace="phase-3-test",
        key=identifier,
        request_fingerprint="a" * 64,
        state="claimed",
        claimed_at=NOW,
    )
    db.session.add(claim)
    db.session.flush()
    return claim


def _lot(db, account, identifier, source_type, expires_at=None, available_at=NOW):
    lot = CreditLot(
        id=identifier,
        billing_account_id=account.id,
        source_type=source_type,
        source_id=f"source-{identifier}",
        original_amount=100,
        available_at=available_at,
        expires_at=expires_at,
        origin_evidence_json={"test_only": True},
    )
    db.session.add(lot)
    db.session.flush()
    return lot


def _entry(db, lot, identifier, entry_type, available_delta, held_delta):
    claim = _claim(db, f"claim-{identifier}")
    return CreditLedgerEntry(
        id=identifier,
        billing_account_id=lot.billing_account_id,
        lot_id=lot.id,
        entry_type=entry_type,
        available_delta=available_delta,
        held_delta=held_delta,
        idempotency_registry_id=claim.id,
        effective_at=NOW,
        actor_type="test",
        actor_id="phase-3-test",
        reason_code="test_only",
        evidence_json={"test_only": True},
    )


def test_phase_3_tables_start_empty_and_are_not_legacy_authorities(db, test_user):
    assert test_user.id
    assert db.session.query(CreditLot).count() == 0
    assert db.session.query(CreditLedgerEntry).count() == 0


def test_append_entry_enforces_zero_floor_and_original_amount(db, test_user):
    account = _account(db, test_user, "zero-floor")
    lot = _lot(db, account, "lot-zero-floor", "credit_pack_purchase")
    append_entry(db.session, _entry(db, lot, "grant-100", "grant", 100, 0))
    db.session.commit()

    with pytest.raises(CreditLedgerInvariantError, match="zero-floor"):
        append_entry(
            db.session,
            _entry(db, lot, "refund-101", "refund_reversal", -101, 0),
        )
    db.session.rollback()

    with pytest.raises(CreditLedgerInvariantError, match="original lot amount"):
        append_entry(db.session, _entry(db, lot, "recovery-one", "recovery", 1, 0))
    db.session.rollback()
    assert db.session.query(CreditLedgerEntry).count() == 1


def test_lot_order_is_expiry_then_source_then_time_then_id(db, test_user):
    account = _account(db, test_user, "ordering")
    later = _lot(
        db,
        account,
        "lot-later-expiry",
        "free_recurring",
        expires_at=NOW + timedelta(days=5),
    )
    sooner = _lot(
        db,
        account,
        "lot-sooner-expiry",
        "credit_pack_purchase",
        expires_at=NOW + timedelta(days=1),
    )
    recurring = _lot(db, account, "lot-recurring", "free_recurring")
    purchased = _lot(db, account, "lot-purchased", "credit_pack_purchase")
    for lot in (later, sooner, recurring, purchased):
        append_entry(
            db.session,
            _entry(db, lot, f"grant-{lot.id}", "grant", 100, 0),
        )
    db.session.commit()

    ordered = ordered_lot_balances(db.session, account.id, NOW)
    assert [item.lot.id for item in ordered] == [
        "lot-sooner-expiry",
        "lot-later-expiry",
        "lot-recurring",
        "lot-purchased",
    ]
    assert [item.available for item in ordered] == [100, 100, 100, 100]


def test_duplicate_funding_origin_and_entry_idempotency_are_rejected(db, test_user):
    account = _account(db, test_user, "idempotency")
    lot = _lot(db, account, "lot-original", "internal")
    db.session.commit()

    db.session.add(CreditLot(
        id="lot-duplicate",
        billing_account_id=account.id,
        source_type=lot.source_type,
        source_id=lot.source_id,
        original_amount=100,
        available_at=NOW,
        origin_evidence_json={"test_only": True},
    ))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    entry = _entry(db, lot, "grant-original", "grant", 100, 0)
    append_entry(db.session, entry)
    db.session.commit()
    duplicate = CreditLedgerEntry(
        id="grant-duplicate",
        billing_account_id=account.id,
        lot_id=lot.id,
        entry_type="admin_adjustment",
        available_delta=-1,
        held_delta=0,
        idempotency_registry_id=entry.idempotency_registry_id,
        effective_at=NOW,
        actor_type="test",
        actor_id="phase-3-test",
        reason_code="test_only",
        evidence_json={"test_only": True},
    )
    db.session.add(duplicate)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
    assert db.session.query(CreditLedgerEntry).filter_by(lot_id=lot.id).count() == 1
