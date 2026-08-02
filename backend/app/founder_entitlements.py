"""Durable Jaspen Advantage entitlement and persistent credit accounting."""

from datetime import datetime
import uuid

from sqlalchemy import func

from . import db
from .models import (
    AccountEntitlement,
    PersistentCreditGrant,
    PersistentCreditTransaction,
)


ADVANTAGE_ENTITLEMENT = 'jaspen_advantage'
ADVANTAGE_CREDIT_SOURCE = 'jaspen_advantage'
ADVANTAGE_HOURLY_REQUEST_LIMIT = 100
ADVANTAGE_DAILY_REQUEST_LIMIT = 300


def advantage_entitlement(user_id, *, include_revoked=False):
    user_id = getattr(user_id, 'id', user_id)
    query = AccountEntitlement.query.filter_by(
        user_id=str(user_id),
        entitlement_key=ADVANTAGE_ENTITLEMENT,
    )
    if not include_revoked:
        query = query.filter(AccountEntitlement.revoked_at.is_(None))
    return query.first()


def has_advantage_entitlement(user_or_id):
    user_id = getattr(user_or_id, 'id', user_or_id)
    return advantage_entitlement(user_id) is not None


def persistent_credit_balance(user_or_id, *, source=None):
    user_id = str(getattr(user_or_id, 'id', user_or_id))
    query = db.session.query(func.coalesce(func.sum(PersistentCreditGrant.remaining_amount), 0)).filter(
        PersistentCreditGrant.user_id == user_id,
        PersistentCreditGrant.status == 'active',
        PersistentCreditGrant.remaining_amount > 0,
    )
    if source:
        query = query.filter(PersistentCreditGrant.source == str(source))
    return int(query.scalar() or 0)


def advantage_credit_balance(user_or_id):
    return persistent_credit_balance(user_or_id, source=ADVANTAGE_CREDIT_SOURCE)


def grant_advantage_offer(
    user,
    amount,
    *,
    payment_reference,
    invoice_id=None,
    checkout_id=None,
    organization_id=None,
    metadata=None,
):
    """Idempotently grant the personal Advantage entitlement and credit lot."""
    user_id = str(user.id)
    payment_reference = str(payment_reference or '').strip()
    invoice_id = str(invoice_id or '').strip() or None
    if not payment_reference:
        raise ValueError('payment_reference is required for an auditable Advantage grant')
    amount = max(0, int(amount or 0))
    if amount <= 0:
        raise ValueError('Advantage credit amount must be positive')

    entitlement = advantage_entitlement(user_id, include_revoked=True)
    if entitlement is None:
        entitlement = AccountEntitlement(
            user_id=user_id,
            organization_id=organization_id or getattr(user, 'active_organization_id', None),
            entitlement_key=ADVANTAGE_ENTITLEMENT,
            source='stripe_jaspen_advantage',
            external_reference=f'advantage-entitlement:{payment_reference}',
            grant_metadata=dict(metadata or {}),
        )
        db.session.add(entitlement)
        db.session.flush()

    external_reference = f'advantage-credit:{payment_reference}'
    grant = PersistentCreditGrant.query.filter_by(external_reference=external_reference).first()
    if grant is not None:
        return entitlement, grant, False

    # The Advantage balance is a one-time benefit even if Stripe retries or
    # replaces an event with a different event id.
    existing_advantage_grant = PersistentCreditGrant.query.filter_by(
        user_id=user_id,
        source=ADVANTAGE_CREDIT_SOURCE,
    ).first()
    if existing_advantage_grant is not None:
        return entitlement, existing_advantage_grant, False

    grant = PersistentCreditGrant(
        user_id=user_id,
        organization_id=organization_id or getattr(user, 'active_organization_id', None),
        entitlement_id=entitlement.id,
        source=ADVANTAGE_CREDIT_SOURCE,
        original_amount=amount,
        remaining_amount=amount,
        external_reference=external_reference,
        stripe_checkout_id=str(checkout_id or '').strip() or None,
        stripe_invoice_id=invoice_id,
        grant_metadata=dict(metadata or {}),
    )
    db.session.add(grant)
    db.session.flush()
    db.session.add(PersistentCreditTransaction(
        grant_id=grant.id,
        user_id=user_id,
        transaction_type='grant',
        amount=amount,
        balance_after=amount,
        idempotency_key=f'{external_reference}:grant',
        transaction_metadata={'source': ADVANTAGE_CREDIT_SOURCE},
    ))
    return entitlement, grant, True


def consume_persistent_credits(user, amount, *, metadata=None):
    """Consume oldest-expiring-independent lots first; returns amount consumed."""
    remaining = max(0, int(amount or 0))
    if remaining <= 0:
        return 0
    consumed = 0
    grants = (
        PersistentCreditGrant.query
        .filter(
            PersistentCreditGrant.user_id == str(user.id),
            PersistentCreditGrant.status == 'active',
            PersistentCreditGrant.remaining_amount > 0,
        )
        .order_by(PersistentCreditGrant.granted_at.asc(), PersistentCreditGrant.id.asc())
        .all()
    )
    for grant in grants:
        debit = min(remaining, int(grant.remaining_amount or 0))
        if debit <= 0:
            continue
        grant.remaining_amount = int(grant.remaining_amount) - debit
        db.session.add(PersistentCreditTransaction(
            grant_id=grant.id,
            user_id=str(user.id),
            transaction_type='usage',
            amount=-debit,
            balance_after=int(grant.remaining_amount),
            idempotency_key=f'usage:{uuid.uuid4()}',
            transaction_metadata=dict(metadata or {}),
        ))
        consumed += debit
        remaining -= debit
        if remaining <= 0:
            break
    return consumed


def refund_persistent_usage(user, amount, *, metadata=None):
    """Restore the most recent persistent usage first; returns amount restored."""
    remaining = max(0, int(amount or 0))
    if remaining <= 0:
        return 0
    restored = 0
    usages = (
        PersistentCreditTransaction.query
        .join(PersistentCreditGrant, PersistentCreditTransaction.grant_id == PersistentCreditGrant.id)
        .filter(
            PersistentCreditTransaction.user_id == str(user.id),
            PersistentCreditTransaction.transaction_type == 'usage',
            PersistentCreditTransaction.amount < 0,
            PersistentCreditGrant.status == 'active',
        )
        .order_by(PersistentCreditTransaction.created_at.desc(), PersistentCreditTransaction.id.desc())
        .all()
    )
    for usage in usages:
        already_restored = int((usage.transaction_metadata or {}).get('restored_amount') or 0)
        available = max(0, abs(int(usage.amount)) - already_restored)
        credit = min(remaining, available)
        if credit <= 0:
            continue
        grant = PersistentCreditGrant.query.get(usage.grant_id)
        if grant is None:
            continue
        grant.remaining_amount = min(
            int(grant.original_amount),
            int(grant.remaining_amount or 0) + credit,
        )
        usage_metadata = dict(usage.transaction_metadata or {})
        usage_metadata['restored_amount'] = already_restored + credit
        usage.transaction_metadata = usage_metadata
        db.session.add(PersistentCreditTransaction(
            grant_id=grant.id,
            user_id=str(user.id),
            transaction_type='release',
            amount=credit,
            balance_after=int(grant.remaining_amount),
            idempotency_key=f'release:{uuid.uuid4()}',
            transaction_metadata=dict(metadata or {}),
        ))
        restored += credit
        remaining -= credit
        if remaining <= 0:
            break
    return restored


def reverse_advantage_credits(user, *, reason, external_reference):
    """Reverse unused Advantage value on refund/chargeback, retaining audit rows."""
    reversed_amount = 0
    grants = PersistentCreditGrant.query.filter_by(
        user_id=str(user.id),
        source=ADVANTAGE_CREDIT_SOURCE,
        status='active',
    ).all()
    for grant in grants:
        amount = int(grant.remaining_amount or 0)
        grant.remaining_amount = 0
        grant.status = 'reversed'
        grant.reversed_at = datetime.utcnow()
        reversed_amount += amount
        db.session.add(PersistentCreditTransaction(
            grant_id=grant.id,
            user_id=str(user.id),
            transaction_type='reversal',
            amount=-amount,
            balance_after=0,
            idempotency_key=f'reversal:{external_reference}:{grant.id}',
            transaction_metadata={'reason': str(reason or 'refund')},
        ))

    entitlement = advantage_entitlement(user, include_revoked=True)
    if entitlement is not None and entitlement.revoked_at is None:
        entitlement.revoked_at = datetime.utcnow()
    return reversed_amount


def advantage_limits_active(user_or_id):
    return has_advantage_entitlement(user_or_id) and advantage_credit_balance(user_or_id) > 0


# Temporary compatibility aliases for callsites outside this feature branch.
FOUNDER_ENTITLEMENT = ADVANTAGE_ENTITLEMENT
FOUNDER_CREDIT_SOURCE = ADVANTAGE_CREDIT_SOURCE
FOUNDER_HOURLY_REQUEST_LIMIT = ADVANTAGE_HOURLY_REQUEST_LIMIT
FOUNDER_DAILY_REQUEST_LIMIT = ADVANTAGE_DAILY_REQUEST_LIMIT
founder_entitlement = advantage_entitlement
has_founder_entitlement = has_advantage_entitlement
founder_credit_balance = advantage_credit_balance
founder_limits_active = advantage_limits_active


def grant_founder_offer(user, amount, *, invoice_id, checkout_id=None, organization_id=None, metadata=None):
    return grant_advantage_offer(
        user,
        amount,
        payment_reference=invoice_id,
        invoice_id=invoice_id,
        checkout_id=checkout_id,
        organization_id=organization_id,
        metadata=metadata,
    )


reverse_founder_credits = reverse_advantage_credits
