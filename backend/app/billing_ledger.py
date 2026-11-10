"""Inactive Phase 3 credit-ledger primitives.

Nothing in the runtime imports this module. It provides the deterministic lock
order and the SQLite parity invariant required before later command cutover.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, func, or_, select, text

from .models import BillingAccount, CreditLedgerEntry, CreditLot


SOURCE_PRIORITY = {
    "free_recurring": 0,
    "subscription_recurring": 0,
    "enterprise_recurring": 0,
    "trial": 1,
    "promotional": 1,
    "comp": 1,
    "internal": 2,
    "legacy_unattributed": 3,
    "credit_pack_purchase": 4,
}


class CreditLedgerInvariantError(ValueError):
    """Raised before a write that would violate a ledger invariant."""


@dataclass(frozen=True)
class LotBalance:
    lot: CreditLot
    available: int
    held: int


def _begin_serialized_sqlite_write(session):
    bind = session.get_bind()
    actual_session = session() if hasattr(session, "registry") else session
    if bind.dialect.name == "sqlite" and not actual_session.in_transaction():
        session.execute(text("BEGIN IMMEDIATE"))


def lock_billing_account(session, billing_account_id):
    """Acquire the account-first lock used by every future ledger command."""
    _begin_serialized_sqlite_write(session)
    account = session.execute(
        select(BillingAccount)
        .where(BillingAccount.id == billing_account_id)
        .with_for_update()
    ).scalar_one_or_none()
    if account is None:
        raise CreditLedgerInvariantError("billing account does not exist")
    return account


def ordered_lot_balances(session, billing_account_id, effective_at: datetime):
    """Lock eligible lots in the approved expiry/source/time/ID order."""
    lock_billing_account(session, billing_account_id)
    priority = case(SOURCE_PRIORITY, value=CreditLot.source_type, else_=99)
    lots = session.execute(
        select(CreditLot)
        .where(
            CreditLot.billing_account_id == billing_account_id,
            CreditLot.available_at <= effective_at,
            or_(CreditLot.expires_at.is_(None), CreditLot.expires_at > effective_at),
        )
        .order_by(
            CreditLot.expires_at.is_(None),
            CreditLot.expires_at,
            priority,
            CreditLot.available_at,
            CreditLot.id,
        )
        .with_for_update()
    ).scalars().all()
    if not lots:
        return []

    totals = {
        row.lot_id: (int(row.available or 0), int(row.held or 0))
        for row in session.execute(
            select(
                CreditLedgerEntry.lot_id,
                func.coalesce(func.sum(CreditLedgerEntry.available_delta), 0).label(
                    "available"
                ),
                func.coalesce(func.sum(CreditLedgerEntry.held_delta), 0).label("held"),
            )
            .where(CreditLedgerEntry.lot_id.in_([lot.id for lot in lots]))
            .group_by(CreditLedgerEntry.lot_id)
        )
    }
    return [
        LotBalance(lot, *totals.get(lot.id, (0, 0)))
        for lot in lots
    ]


def append_entry(session, entry: CreditLedgerEntry):
    """Append one entry after applying the production zero-floor invariant.

    PostgreSQL repeats this check in a locking BEFORE INSERT trigger. SQLite
    uses the explicit write transaction here and also has migration triggers so
    direct test writes cannot silently weaken the invariant.
    """
    lock_billing_account(session, entry.billing_account_id)
    lot = session.execute(
        select(CreditLot)
        .where(CreditLot.id == entry.lot_id)
        .with_for_update()
    ).scalar_one_or_none()
    if lot is None or lot.billing_account_id != entry.billing_account_id:
        raise CreditLedgerInvariantError("ledger lot/account mismatch")

    available, held = session.execute(
        select(
            func.coalesce(func.sum(CreditLedgerEntry.available_delta), 0),
            func.coalesce(func.sum(CreditLedgerEntry.held_delta), 0),
        ).where(CreditLedgerEntry.lot_id == entry.lot_id)
    ).one()
    next_available = int(available or 0) + int(entry.available_delta)
    next_held = int(held or 0) + int(entry.held_delta)
    if next_available < 0 or next_held < 0:
        raise CreditLedgerInvariantError("credit ledger zero-floor violation")
    if next_available + next_held > int(lot.original_amount):
        raise CreditLedgerInvariantError("credit ledger exceeds original lot amount")

    session.add(entry)
    session.flush()
    return entry
