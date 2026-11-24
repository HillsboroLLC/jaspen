"""Phase 11: organization pools, Enterprise contracts, and term-bound credit expiry.

Founder-approved directions (2026-11-15): P11-DEP-001 annual carryforward,
P11-DEP-002 Stripe-verified Enterprise funding, P11-DEP-003 explicit staff
permission, P11-DEP-004 option A contract-backed terms, the credit-pack term
expiry rule, 30-day nonrenewal notice, 15-day read-only renewal grace, and the
180-day retention-review record.

Service tests run on the ORM schema (SQLite, or an isolated PostgreSQL schema
when TEST_DATABASE_URL is set). ``test_sqlite_migration_*`` applies the
Phase 11 revision on SQLite. ``test_postgres_migrated_*`` runs on the fully
migrated disposable PostgreSQL database where every Phase 3-11 guard is live.

All prices, credits, and seat counts below are test fixtures, not commercial
terms.
"""

from concurrent.futures import ThreadPoolExecutor
import contextlib
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import threading
import uuid

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.orm import Session

import app.billing_enterprise_contracts as contracts
from app import db as flask_db
from app.billing_allocations import (
    RecurringAllocationError,
    allocate_recurring_credits,
    expire_recurring_credits,
)
from app.billing_entitlements import add_calendar_months, append_entitlement_transition, monthly_period_bounds
from app.billing_enterprise_contracts import (
    ContractError,
    ContractFundingError,
    ContractIsolationError,
    ContractPermissionError,
    ContractPolicyRequiredError,
    activate_contract_version,
    approve_contract_version,
    cancel_contract_version,
    complete_contract_term,
    contract_access_state,
    end_contract_after_grace,
    funded_versions_for_review,
    prepare_automatic_renewal,
    record_contract_funding,
    record_contract_version,
    record_enterprise_contract,
    record_nonrenewal_notice,
    reverse_nonrenewal_notice,
)
from app.billing_financial import record_financial_transaction
from app.billing_financial_effects import (
    FinancialEffectError,
    FinancialEffectPolicyRequiredError,
    credit_pack_expiry_quote,
    expire_purchased_credits,
    fund_credit_purchase,
)
from app.billing_ledger import ordered_lot_balances
from app.billing_offers import record_staff_billing_permission, revoke_staff_billing_permission
from app.billing_plan_changes import PlanChangeError, schedule_plan_change
from app.billing_seats import SeatChangePermissionError, apply_paid_seat_increase, current_seat_commitment
from app.models import (
    BillingAccount,
    EnterpriseContractTermFunding,
    BillingRoleGrant,
    BillingSubscription,
    CreditLedgerEntry,
    CreditLot,
    CreditPeriod,
    EnterpriseContract,
    EnterpriseContractActivation,
    EnterpriseContractVersion,
    EntitlementDefinition,
    EntitlementInstance,
    FinancialLine,
    IdempotencyRegistry,
    Organization,
    OrganizationMember,
    RecurringCreditAllocation,
    SeatCommitment,
    User,
)
from app.models_billing_phase11 import CONTRACT_PERMISSION, CONTRACT_PROCESSOR
from tests.test_billing_financial_effects import _inbox, _line, purchase_definition


BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = str(BACKEND_DIR / "migrations")
REVISION = "b4d6f8a0c2e5"
PARENT = "f2b4d6e8a0c3"
PHASE11_TABLES = (
    "enterprise_contract_notices", "enterprise_contract_activations",
    "enterprise_contract_term_fundings", "enterprise_contract_events",
    "enterprise_contract_versions", "enterprise_contracts",
)
ANCHOR = datetime(2026, 1, 31, 15, 45, tzinfo=timezone.utc)
DELIVERIES = ({
    "template_key": "test-contract", "template_version": "test-v1",
    "channel": "test-channel", "locale": "en-US",
},)
PROVISIONER = {"actor_type": "system", "actor_id": "phase11-provisioning"}
SERVICE = {"actor_type": "system", "actor_id": "phase11-test"}
# Test fixtures only.
PRICE, CREDITS, SEATS = 1_200_000, 1000, 5
PG = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)


def _utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class Ns:
    def __init__(self, **values):
        self.__dict__.update(values)


def db_now(session):
    from app.billing_offers import _database_now
    return _database_now(session)


def refused(session, error, match, fn, *args, **kwargs):
    """Assert a command fails; roll back its savepoint as the caller's transaction would."""
    savepoint = session.begin_nested()
    try:
        with pytest.raises(error, match=match):
            fn(*args, **kwargs)
    finally:
        savepoint.rollback()


def at_time(monkeypatch, when):
    """Advance only the contract service's clock (ORM schemas have no time guard)."""
    monkeypatch.setattr(contracts, "_database_now", lambda _session: when)
    monkeypatch.setattr(contracts, "_database_clock", lambda _session: when)


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------

def _user(session, label):
    user = User(
        id=f"p11-{label}-{uuid.uuid4().hex[:8]}", email=f"p11-{label}-{uuid.uuid4().hex[:8]}@example.test",
        name=f"Phase 11 {label}", password_hash="not-a-login-credential", subscription_plan="free",
        credits_remaining=0, seat_limit=1, max_seats=1,
    )
    session.add(user)
    session.flush()
    return user.id


def seed_org(session, *, members=1, currency="usd"):
    """Every account is an organization; ``members`` paid-role members including the owner."""
    suffix = uuid.uuid4().hex[:10]
    owner = _user(session, "owner")
    organization = Organization(
        id=f"p11-org-{suffix}", name=f"Phase 11 {suffix}", slug=f"phase-11-{suffix}",
        owner_user_id=owner, plan_key="enterprise",
    )
    session.add(organization)
    session.flush()
    member_ids = [owner]
    session.add(OrganizationMember(organization_id=organization.id, user_id=owner, role="owner", status="active"))
    for index in range(members - 1):
        member = _user(session, f"member{index}")
        member_ids.append(member)
        session.add(OrganizationMember(
            organization_id=organization.id, user_id=member, role="collaborator", status="active",
        ))
    account = BillingAccount(
        id=f"p11-account-{suffix}", organization_id=organization.id, currency=currency,
        account_anchor_at=ANCHOR, status="active",
    )
    session.add(account)
    session.flush()
    session.add(BillingRoleGrant(
        billing_account_id=account.id, user_id=owner, role="billing_owner", state="active",
        starts_at=ANCHOR - timedelta(days=365), origin_type="test", origin_id=f"seed:{suffix}",
    ))
    session.flush()
    return Ns(suffix=suffix, account=account.id, org=organization.id, owner=owner, members=member_ids)


def staff(session, permission=CONTRACT_PERMISSION):
    user_id = _user(session, "staff")
    grant, _state = record_staff_billing_permission(
        session, grant_command_id=f"grant-{uuid.uuid4().hex[:10]}", user_id=user_id, permission=permission,
        starts_at=datetime(2020, 1, 1, tzinfo=timezone.utc), ends_at=None,
        approval_evidence_reference="approval:founder-test", justification="Phase 11 test staff",
        **PROVISIONER,
    )
    return Ns(user=user_id, grant=grant.id)


def terms(start, **overrides):
    value = {
        "interval": "year", "term_starts_at": start, "currency": "usd", "price_minor": PRICE,
        "monthly_credit_amount": CREDITS, "committed_seats": SEATS,
        "capabilities": {"analysis": True}, "renewal_mode": "automatic", "exclusivity_key": "base-plan",
    }
    value.update(overrides)
    return value


def record(session, ns, who, start, **overrides):
    contract, version, state = record_enterprise_contract(
        session, command_id=f"rec-{uuid.uuid4().hex[:10]}", billing_account_id=ns.account,
        contract_reference=f"MSA-{uuid.uuid4().hex[:10]}", terms=terms(start, **overrides),
        executed_reference="executed:msa", executed_evidence_reference="evidence:signed-pdf",
        actor_user_id=who.user, delivery_obligations=DELIVERIES,
    )
    assert state == "inserted"
    return contract, version


def approve(session, ns, who, contract, version):
    version, _state = approve_contract_version(
        session, command_id=f"apr-{uuid.uuid4().hex[:8]}", billing_account_id=ns.account,
        contract_id=contract.id, version_id=version.id, approval_evidence_reference="approval:countersigned",
        actor_user_id=who.user, delivery_obligations=DELIVERIES,
    )
    return version


def stripe_payment(session, ns, version, *, at=None, amount=None, kind="payment", seat=False,
                   currency="usd", discount=0, subscription_id=None, instance_id="default"):
    """A Stripe-invoice payment recorded from a processed inbox event (Phase 5.1/5.2)."""
    at = at or datetime.now(timezone.utc) - timedelta(minutes=5)
    tag = uuid.uuid4().hex[:6]
    line = _line(
        f"ent-{tag}", "seat" if seat else "subscription", amount if amount is not None else version.price_minor,
        discount=discount, currency=currency,
        subscription_id=subscription_id or version.subscription_id,
        instance_id=None if seat else (version.entitlement_instance_id if instance_id == "default" else instance_id),
    )
    object_id = f"in_p11_{tag}"
    header = {
        "billing_account_id": ns.account, "kind": kind, "provider": "stripe",
        "object_type": "invoice", "object_id": object_id, "external_version": "v1",
        "effective_at": at, "currency": currency, "principal_minor": line["principal_minor"],
        "tax_minor": 0, "fee_minor": 0, "discount_minor": discount,
        "gross_minor": line["principal_minor"] + discount,
    }
    header["inbox_event_id"] = None if kind == "adjustment" else _inbox(session, "invoice", object_id, at, ns.suffix).id
    transaction, _state = record_financial_transaction(session, header, [line])
    return session.execute(
        sa.select(FinancialLine.id).where(FinancialLine.financial_transaction_id == transaction.id)
    ).scalar_one()


def fund(session, ns, who, contract, version, line_id):
    funding, _state = record_contract_funding(
        session, command_id=f"fund-{uuid.uuid4().hex[:8]}", billing_account_id=ns.account,
        contract_id=contract.id, version_id=version.id, financial_line_id=line_id,
        actor_user_id=who.user, delivery_obligations=DELIVERIES,
    )
    return funding


def activate(session, ns, who, contract, version):
    return activate_contract_version(
        session, command_id=f"act-{uuid.uuid4().hex[:8]}", billing_account_id=ns.account,
        contract_id=contract.id, version_id=version.id, actor_user_id=who.user, delivery_obligations=DELIVERIES,
    )


def active_contract(session, ns, who, start=None, **overrides):
    start = start or db_now(session) - timedelta(hours=1)
    contract, version = record(session, ns, who, start, **overrides)
    version = approve(session, ns, who, contract, version)
    fund(session, ns, who, contract, version, stripe_payment(session, ns, version))
    activation, state = activate(session, ns, who, contract, version)
    assert state == "inserted"
    return contract, version, activation


def lots_of(session, account_id, source_type=None):
    query = sa.select(CreditLot).where(CreditLot.billing_account_id == account_id)
    if source_type:
        query = query.where(CreditLot.source_type == source_type)
    return session.execute(query.order_by(CreditLot.available_at, CreditLot.id)).scalars().all()


def balance(session, lot_id):
    available, held = session.execute(
        sa.select(
            sa.func.coalesce(sa.func.sum(CreditLedgerEntry.available_delta), 0),
            sa.func.coalesce(sa.func.sum(CreditLedgerEntry.held_delta), 0),
        ).where(CreditLedgerEntry.lot_id == lot_id)
    ).one()
    return int(available), int(held)


def spendable(session, account_id, at):
    return sum(b.available for b in ordered_lot_balances(session, account_id, at))


def self_serve(session, ns, interval, *, credits=500, principal=10000, anchor=ANCHOR):
    """An ordinary Stripe subscription (monthly or annual) with an active entitlement."""
    suffix = uuid.uuid4().hex[:8]
    kind = {"month": "monthly_subscription", "year": "annual_monthly"}[interval]
    definition = EntitlementDefinition(
        id=f"p11-sub-def-{suffix}", key=f"pro-{suffix}", version=1, exclusivity_key=f"self-serve-{suffix}",
        capability_json={"schema_version": 1, "capabilities": {"analysis": True}},
        funding_policy_json={"schema_version": 1, "period_kind": kind, "credit_amount": credits},
        effective_at=anchor, approved_at=anchor, approval_evidence_reference="approval:phase11-sub",
    )
    session.add(definition)
    session.flush()
    term_end = add_calendar_months(anchor, 1 if interval == "month" else 12)
    subscription = BillingSubscription(
        id=f"p11-sub-{suffix}", billing_account_id=ns.account, processor="stripe",
        external_subscription_id=f"sub_{suffix}", interval=interval, anchor_at=anchor,
        term_starts_at=anchor, term_ends_at=term_end, state="active",
        current_entitlement_definition_id=definition.id, origin_evidence_json={"test": True},
    )
    session.add(subscription)
    session.flush()
    instance = EntitlementInstance(
        id=f"p11-inst-{suffix}", billing_account_id=ns.account, entitlement_definition_id=definition.id,
        subscription_id=subscription.id, state="proposed", starts_at=anchor, ends_at=term_end,
        source_type="subscription", source_id=subscription.external_subscription_id,
        approval_evidence_reference="approval:phase11-sub",
    )
    session.add(instance)
    session.flush()
    for next_state in ("scheduled", "active"):
        registry = IdempotencyRegistry(
            id=str(uuid.uuid4()), namespace="phase11_test_activation", key=f"{next_state}:{instance.id}",
            request_fingerprint="7" * 64, state="claimed", claimed_at=anchor,
        )
        session.add(registry)
        session.flush()
        append_entitlement_transition(
            session, instance_id=instance.id, next_state=next_state, transition=next_state,
            effective_at=anchor, actor_type="test", actor_id="phase11", source_type="test",
            source_id=f"phase11:{suffix}", idempotency=registry, evidence_json={"test": "phase11"},
        )
        session.expire(instance)
        if instance.state != next_state:
            instance.state = next_state
            session.flush()
    tag = uuid.uuid4().hex[:6]
    object_id = f"in_p11_sub_{tag}"
    inbox = _inbox(session, "invoice", object_id, anchor, ns.suffix)
    transaction, _state = record_financial_transaction(session, {
        "billing_account_id": ns.account, "kind": "payment", "provider": "stripe",
        "object_type": "invoice", "object_id": object_id, "external_version": "v1",
        "effective_at": anchor + timedelta(hours=1), "currency": "usd", "principal_minor": principal,
        "tax_minor": 0, "fee_minor": 0, "discount_minor": 0, "gross_minor": principal,
        "inbox_event_id": inbox.id,
    }, [_line(f"sub-{tag}", "subscription", principal, subscription_id=subscription.id, instance_id=instance.id)])
    line_id = session.execute(
        sa.select(FinancialLine.id).where(FinancialLine.financial_transaction_id == transaction.id)
    ).scalar_one()
    return Ns(subscription=subscription, instance=instance, line=line_id, term_end=term_end, credits=credits)


def allocate(session, ns, sub, index, at=None):
    start, end = monthly_period_bounds(ANCHOR, index)
    _allocation, period, lot, state = allocate_recurring_credits(
        session, billing_account_id=ns.account, entitlement_instance_id=sub.instance.id, period_index=index,
        opened_at=at or start + timedelta(hours=2), delivery_obligations=DELIVERIES,
        financial_line_id=sub.line, **SERVICE,
    )
    return period, lot, state


def expire(session, period, at):
    return expire_recurring_credits(
        session, credit_period_id=period.id, expired_at=at, delivery_obligations=DELIVERIES, **SERVICE,
    )


# ---------------------------------------------------------------------------
# 1-3. Monthly and annual recurring credits (P11-DEP-001), identical for every size
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("members", [1, 5])
def test_monthly_recurring_credits_expire_at_the_month_end_without_rollover(db, members):
    session = db.session
    ns = seed_org(session, members=members)
    sub = self_serve(session, ns, "month")
    period, lot, _state = allocate(session, ns, sub, 0)
    _start, end = monthly_period_bounds(ANCHOR, 0)
    assert _utc(lot.expires_at) == end == _utc(sub.term_end)
    with pytest.raises(RecurringAllocationError, match="not reached their expiry"):
        expire(session, period, end - timedelta(seconds=1))
    assert spendable(session, ns.account, end - timedelta(seconds=1)) == sub.credits
    assert spendable(session, ns.account, end) == 0  # nothing carries into the next month
    period, state = expire(session, period, end)
    assert (state, period.state, balance(session, lot.id)) == ("expired", "expired", (0, 0))


@pytest.mark.parametrize("members", [1, 5])
def test_annual_monthly_releases_accumulate_within_the_term_and_expire_at_its_end(db, members):
    session = db.session
    ns = seed_org(session, members=members)
    sub = self_serve(session, ns, "year")
    released = [allocate(session, ns, sub, index) for index in range(3)]
    for period, lot, _state in released:
        assert _utc(lot.expires_at) == _utc(sub.term_end)  # every release runs to the term end
        assert _utc(lot.available_at) == _utc(period.starts_at)  # never before its month opens
    # A future month is never spendable early; past months carry forward.
    month3_start, _ = monthly_period_bounds(ANCHOR, 3)
    assert spendable(session, ns.account, month3_start - timedelta(seconds=1)) == 3 * sub.credits
    first_period, first_lot, _ = released[0]
    _s, first_end = monthly_period_bounds(ANCHOR, 0)
    with pytest.raises(RecurringAllocationError, match="not reached their expiry"):
        expire(session, first_period, first_end)  # month end is not the annual expiry
    term_end = _utc(sub.term_end)
    assert spendable(session, ns.account, term_end - timedelta(seconds=1)) == 3 * sub.credits
    assert spendable(session, ns.account, term_end) == 0
    for period, lot, _state in released:
        period, state = expire(session, period, term_end)
        assert state == "expired" and balance(session, lot.id) == (0, 0)


def test_single_and_multi_member_organizations_follow_identical_credit_rules(db):
    session = db.session
    outcomes = []
    for members in (1, 40):
        ns = seed_org(session, members=members)
        sub = self_serve(session, ns, "year")
        lots = [allocate(session, ns, sub, index)[1] for index in range(2)]
        outcomes.append([
            (lot.source_type, lot.original_amount, _utc(lot.expires_at) - ANCHOR, lot.member_attribution_id)
            for lot in lots
        ])
        assert {lot.billing_account_id for lot in lots} == {ns.account}  # one shared organization pool
    assert outcomes[0] == outcomes[1]


def test_duplicate_annual_allocation_converges_without_a_second_lot(db):
    session = db.session
    ns = seed_org(session)
    sub = self_serve(session, ns, "year")
    _p, lot, state = allocate(session, ns, sub, 1)
    _p2, again, second = allocate(session, ns, sub, 1)
    assert (state, second, again.id) == ("inserted", "duplicate", lot.id)
    assert len(lots_of(session, ns.account, "subscription_recurring")) == 1


# ---------------------------------------------------------------------------
# 4-7. Credit packs: full quantity, expire at the current paid term end
# ---------------------------------------------------------------------------

def _buy_pack(session, ns, at, *, fund=True):
    definition = purchase_definition(session, f"{ns.suffix}{uuid.uuid4().hex[:4]}")
    source_id = session.get(EntitlementDefinition, definition).funding_policy_json["purchase"]["source_id"]
    tag = uuid.uuid4().hex[:6]
    object_id = f"in_p11_pack_{tag}"
    inbox = _inbox(session, "invoice", object_id, at, ns.suffix)
    transaction, _state = record_financial_transaction(session, {
        "billing_account_id": ns.account, "kind": "payment", "provider": "stripe",
        "object_type": "invoice", "object_id": object_id, "external_version": "v1", "effective_at": at,
        "currency": "usd", "principal_minor": 1000, "tax_minor": 0, "fee_minor": 0, "discount_minor": 0,
        "gross_minor": 1000, "inbox_event_id": inbox.id,
    }, [_line(f"pack-{tag}", "credit_pack", 1000, source_id=source_id)])
    line_id = session.execute(
        sa.select(FinancialLine.id).where(FinancialLine.financial_transaction_id == transaction.id)
    ).scalar_one()
    if not fund:
        return Ns(line=line_id, definition=definition)
    fundings, lots, state = fund_credit_purchase(
        session, billing_account_id=ns.account, financial_line_id=line_id, entitlement_definition_id=definition,
        funded_at=at, delivery_obligations=DELIVERIES, **SERVICE,
    )
    return Ns(line=line_id, definition=definition, fundings=fundings, lots=lots, state=state)


@pytest.mark.parametrize("interval", ["month", "year"])
def test_credit_pack_releases_its_full_quantity_and_expires_at_the_current_term_end(db, interval):
    session = db.session
    ns = seed_org(session)
    sub = self_serve(session, ns, interval)
    _p, recurring, _s = allocate(session, ns, sub, 0)
    allocations_before = session.query(RecurringCreditAllocation).count()
    at = ANCHOR + timedelta(days=10)
    quote = credit_pack_expiry_quote(session, billing_account_id=ns.account, at=at)
    assert quote["expires_at"] == _utc(sub.term_end) and quote["subscription_id"] == sub.subscription.id
    pack = _buy_pack(session, ns, at)
    assert pack.state == "inserted"
    assert sum(lot.original_amount for lot in pack.lots) == 3500  # full purchased quantity, no proration
    for lot, funding in zip(pack.lots, pack.fundings):
        assert lot.source_type == "credit_pack_purchase"  # distinct from recurring allocations
        assert _utc(lot.expires_at) == quote["expires_at"] == _utc(funding.expires_at)
        assert _utc(lot.available_at) == at and funding.expiry_subscription_id == sub.subscription.id
    # Packs change neither the recurring allocation nor any seat commitment.
    assert session.query(RecurringCreditAllocation).count() == allocations_before
    assert session.get(EntitlementDefinition, sub.instance.entitlement_definition_id).funding_policy_json[
        "credit_amount"] == sub.credits
    assert session.query(SeatCommitment).filter_by(billing_account_id=ns.account).count() == 0
    # Replay converges on the same lots.
    _f, again, state = fund_credit_purchase(
        session, billing_account_id=ns.account, financial_line_id=pack.line,
        entitlement_definition_id=pack.definition, funded_at=at, delivery_obligations=DELIVERIES, **SERVICE,
    )
    assert state == "duplicate" and {lot.id for lot in again} == {lot.id for lot in pack.lots}
    # At the term boundary nothing carries over; explicit expiration zeroes it.
    term_end = _utc(sub.term_end)
    assert spendable(session, ns.account, term_end) == 0
    funding = pack.fundings[0]
    with pytest.raises(FinancialEffectError, match="has not reached"):
        expire_purchased_credits(session, credit_purchase_funding_id=funding.id,
                                 expired_at=term_end - timedelta(seconds=1),
                                 delivery_obligations=DELIVERIES, **SERVICE)
    _funding, state = expire_purchased_credits(session, credit_purchase_funding_id=funding.id,
                                               expired_at=term_end, delivery_obligations=DELIVERIES, **SERVICE)
    assert state == "expired" and balance(session, funding.lot_id) == (0, 0)
    assert balance(session, recurring.id)[0] == sub.credits  # recurring lot untouched by pack expiry


def test_credit_pack_without_a_paid_term_or_after_it_ended_fails_closed(db):
    session = db.session
    ns = seed_org(session)
    before = session.query(CreditLot).count()
    with pytest.raises(FinancialEffectPolicyRequiredError, match="without a paid"):
        credit_pack_expiry_quote(session, billing_account_id=ns.account, at=ANCHOR)
    with pytest.raises(FinancialEffectPolicyRequiredError, match="without a paid"):
        _buy_pack(session, ns, ANCHOR + timedelta(days=1))
    sub = self_serve(session, ns, "month")
    pack = _buy_pack(session, ns, ANCHOR + timedelta(days=2), fund=False)
    with pytest.raises(FinancialEffectPolicyRequiredError, match="late credit-pack funding"):
        fund_credit_purchase(
            session, billing_account_id=ns.account, financial_line_id=pack.line,
            entitlement_definition_id=pack.definition, funded_at=_utc(sub.term_end),
            delivery_obligations=DELIVERIES, **SERVICE,
        )
    self_serve(session, ns, "year", anchor=ANCHOR - timedelta(days=1))
    with pytest.raises(FinancialEffectPolicyRequiredError, match="ambiguous"):
        credit_pack_expiry_quote(session, billing_account_id=ns.account, at=ANCHOR + timedelta(days=3))
    assert session.query(CreditLot).count() == before


# ---------------------------------------------------------------------------
# 9-10. Contract authority: explicit staff permission, tenant isolation
# ---------------------------------------------------------------------------

def test_customer_admins_billing_owners_and_global_admins_cannot_administer_contracts(db):
    session = db.session
    ns = seed_org(session)
    admin = session.get(User, ns.owner)
    admin.is_admin = True
    session.flush()
    with pytest.raises(ContractPermissionError):
        record(session, ns, Ns(user=ns.owner), db_now(session))
    other_staff = staff(session, permission="billing.comp.grant")
    with pytest.raises(ContractPermissionError):
        record(session, ns, other_staff, db_now(session))
    assert session.query(EnterpriseContract).count() == 0


def test_revoked_staff_grant_authorizes_no_contract_change(db):
    session = db.session
    ns, who = seed_org(session), staff(session)
    contract, version = record(session, ns, who, db_now(session) + timedelta(days=30))
    revoke_staff_billing_permission(
        session, grant_id=who.grant, reason="role ended", evidence_reference="evidence:offboard", **PROVISIONER,
    )
    with pytest.raises(ContractPermissionError):
        approve(session, ns, who, contract, version)
    assert session.get(EnterpriseContractVersion, version.id).state == "recorded"


def test_contract_and_funding_are_isolated_between_organizations(db):
    session = db.session
    first, second, who = seed_org(session), seed_org(session), staff(session)
    contract, version = record(session, first, who, db_now(session) - timedelta(hours=1))
    with pytest.raises(ContractError, match="not available for this billing account"):
        approve_contract_version(
            session, command_id="x-org", billing_account_id=second.account, contract_id=contract.id,
            version_id=version.id, approval_evidence_reference="e", actor_user_id=who.user,
            delivery_obligations=DELIVERIES,
        )
    version = approve(session, first, who, contract, version)
    other_contract, other_version = record(session, second, who, db_now(session) - timedelta(hours=1))
    other_version = approve(session, second, who, other_contract, other_version)
    foreign_line = stripe_payment(session, second, other_version)
    with pytest.raises(ContractFundingError, match="not available for this billing account"):
        fund(session, first, who, contract, version, foreign_line)


def test_customer_plan_and_seat_commands_cannot_change_a_contract_term(db):
    session = db.session
    ns, who = seed_org(session), staff(session)
    _contract, version, _activation = active_contract(session, ns, who)
    with pytest.raises(SeatChangePermissionError, match="Enterprise contract version"):
        apply_paid_seat_increase(
            session, billing_account_id=ns.account, subscription_id=version.subscription_id,
            client_command_id="cust-1", seat_delta=3, attribution_ids=[], requested_at=db_now(session),
            paid_at=db_now(session), requested_by_user_id=ns.owner, delivery_obligations=DELIVERIES,
        )
    with pytest.raises(PlanChangeError, match="Enterprise contract version"):
        schedule_plan_change(
            session, billing_account_id=ns.account, subscription_id=version.subscription_id,
            client_command_id="cust-2", kind="cancellation", target_entitlement_definition_id=None,
            requested_at=db_now(session), effective_at=_utc(version.term_ends_at), compatible_supersede=False,
            actor_type="user", actor_id=ns.owner, delivery_obligations=DELIVERIES,
        )



# ---------------------------------------------------------------------------
# Effective dates and verified Stripe funding (P11-DEP-002)
# ---------------------------------------------------------------------------

def test_approval_before_the_effective_date_grants_nothing_until_it_is_effective(db, monkeypatch):
    session = db.session
    ns, who = seed_org(session), staff(session)
    start = db_now(session) + timedelta(days=20)
    contract, version = record(session, ns, who, start)
    version = approve(session, ns, who, contract, version)
    fund(session, ns, who, contract, version, stripe_payment(session, ns, version))
    refused(session, ContractError, "not yet effective", activate, session, ns, who, contract, version)
    instance = session.get(EntitlementInstance, version.entitlement_instance_id)
    subscription = session.get(BillingSubscription, version.subscription_id)
    assert (instance.state, subscription.state, subscription.processor) == ("proposed", "proposed", CONTRACT_PROCESSOR)
    assert lots_of(session, ns.account) == [] and current_seat_commitment(session, subscription.id) is None
    assert contract_access_state(session, billing_account_id=ns.account)["state"] == "none"
    at_time(monkeypatch, start + timedelta(minutes=1))
    activation, state = activate(session, ns, who, contract, version)
    assert state == "inserted" and activation.seats == SEATS
    [lot] = lots_of(session, ns.account)
    assert (lot.source_type, lot.original_amount, _utc(lot.expires_at)) == (
        "subscription_recurring", CREDITS, _utc(version.term_ends_at),
    )


def test_activation_requires_verified_full_funding(db):
    session = db.session
    ns, who = seed_org(session), staff(session)
    contract, version = record(session, ns, who, db_now(session) - timedelta(hours=1))
    version = approve(session, ns, who, contract, version)
    with pytest.raises(ContractFundingError, match="requires verified funding"):
        activate(session, ns, who, contract, version)
    assert lots_of(session, ns.account) == []


@pytest.mark.parametrize("case,match", [
    ("adjustment", "verified Stripe payment"),
    ("partial", "agreed contract amount"),
    ("overpaid", "agreed contract amount"),
    ("currency", "agreed contract amount"),
    ("other_subscription", "agreed contract amount"),
    ("seat_line_for_term", "agreed contract amount"),
])
def test_unverified_or_mismatched_payments_never_fund_a_contract(db, case, match):
    session = db.session
    ns, who = seed_org(session), staff(session)
    contract, version = record(session, ns, who, db_now(session) - timedelta(hours=1))
    version = approve(session, ns, who, contract, version)
    other = self_serve(session, ns, "year") if case == "other_subscription" else None
    line = {
        "adjustment": lambda: stripe_payment(session, ns, version, kind="adjustment"),
        "partial": lambda: stripe_payment(session, ns, version, amount=PRICE // 4),
        "overpaid": lambda: stripe_payment(session, ns, version, amount=PRICE + 1),
        "currency": lambda: stripe_payment(session, ns, version, currency="eur"),
        "other_subscription": lambda: stripe_payment(
            session, ns, version, subscription_id=other.subscription.id, instance_id=other.instance.id),
        "seat_line_for_term": lambda: stripe_payment(session, ns, version, seat=True),
    }[case]
    try:
        line_id = line()
    except Exception:
        # Phase 5.2 itself refuses some shapes (for example an eur line on a usd account).
        assert case == "currency"
        return
    with pytest.raises(ContractFundingError, match=match):
        fund(session, ns, who, contract, version, line_id)
    with pytest.raises(ContractFundingError):
        activate(session, ns, who, contract, version)


def test_funding_and_activation_replay_converge_and_a_line_funds_one_version(db):
    session = db.session
    ns, who = seed_org(session), staff(session)
    contract, version = record(session, ns, who, db_now(session) - timedelta(hours=1))
    version = approve(session, ns, who, contract, version)
    line_id = stripe_payment(session, ns, version)
    first = fund(session, ns, who, contract, version, line_id)
    again, state = record_contract_funding(
        session, command_id="replay", billing_account_id=ns.account, contract_id=contract.id,
        version_id=version.id, financial_line_id=line_id, actor_user_id=who.user, delivery_obligations=DELIVERIES,
    )
    assert (state, again.id) == ("duplicate", first.id)
    activation, state = activate(session, ns, who, contract, version)
    again, replay = activate(session, ns, who, contract, version)
    assert (state, replay, again.id) == ("inserted", "duplicate", activation.id)
    assert len(lots_of(session, ns.account)) == 1
    assert session.query(SeatCommitment).filter_by(subscription_id=version.subscription_id).count() == 1
    # A second contract cannot reuse the same verified payment line.
    contract2, version2 = record(session, ns, who, db_now(session) + timedelta(days=400))
    version2 = approve(session, ns, who, contract2, version2)
    with pytest.raises(ContractFundingError):
        fund(session, ns, who, contract2, version2, line_id)


def test_activation_creates_one_shared_pool_entitlement_and_contracted_seats(db):
    session = db.session
    ns, who = seed_org(session, members=3), staff(session)
    contract, version, activation = active_contract(session, ns, who)
    session.refresh(contract)
    instance = session.get(EntitlementInstance, version.entitlement_instance_id)
    commitment = current_seat_commitment(session, version.subscription_id)
    assert (contract.state, version.state, instance.state, instance.source_type) == (
        "active", "active", "active", "enterprise_contract",
    )
    assert (commitment.origin_type, commitment.quantity) == ("contract", SEATS)
    [lot] = lots_of(session, ns.account)
    assert lot.billing_account_id == ns.account and lot.member_attribution_id is None
    state = contract_access_state(session, billing_account_id=ns.account)
    assert state["state"] == "paid" and state["paid_through"] == _utc(version.term_ends_at)


# ---------------------------------------------------------------------------
# Amendments, seats, and occupancy
# ---------------------------------------------------------------------------

def _amend(session, ns, who, contract, term, seats, *, price=50_000, effective_at=None, **extra):
    version, _state = record_contract_version(
        session, command_id=f"amd-{uuid.uuid4().hex[:8]}", billing_account_id=ns.account,
        contract_id=contract.id, version_kind="amendment", term_version_id=term.id,
        effective_at=effective_at or db_now(session) - timedelta(minutes=1), committed_seats=seats,
        price_minor=price, executed_reference="executed:amendment-1",
        executed_evidence_reference="evidence:amendment-pdf", actor_user_id=who.user,
        delivery_obligations=DELIVERIES, **extra,
    )
    return version


def test_mid_term_seat_increase_by_funded_amendment_and_no_mid_term_reduction(db):
    session = db.session
    ns, who = seed_org(session), staff(session)
    contract, term, _activation = active_contract(session, ns, who)
    lots_before = len(lots_of(session, ns.account))
    with pytest.raises(ContractError, match="reductions are not allowed"):
        _amend(session, ns, who, contract, term, SEATS - 1)
    with pytest.raises(ContractPolicyRequiredError, match="proration"):
        _amend(session, ns, who, contract, term, SEATS + 2, monthly_credit_amount=CREDITS * 2)
    amendment = _amend(session, ns, who, contract, term, SEATS + 3)
    amendment = approve(session, ns, who, contract, amendment)
    refused(session, ContractFundingError, "verified funding", activate, session, ns, who, contract, amendment)
    fund(session, ns, who, contract, amendment, stripe_payment(session, ns, amendment, seat=True))
    activation, state = activate(session, ns, who, contract, amendment)
    assert state == "inserted"
    commitment = current_seat_commitment(session, term.subscription_id)
    assert (commitment.quantity, commitment.origin_type) == (SEATS + 3, "contract")
    previous = session.get(SeatCommitment, commitment.previous_commitment_id)
    assert (previous.state, previous.quantity) == ("replaced", SEATS)
    assert len(lots_of(session, ns.account)) == lots_before  # seats change no credits


def test_member_removal_frees_occupancy_but_never_reduces_the_paid_commitment(db):
    session = db.session
    ns, who = seed_org(session, members=4), staff(session)
    _contract, version, _activation = active_contract(session, ns, who)
    member = session.execute(sa.select(OrganizationMember).where(
        OrganizationMember.organization_id == ns.org, OrganizationMember.user_id == ns.members[-1],
    )).scalar_one()
    member.status = "removed"
    session.flush()
    assert current_seat_commitment(session, version.subscription_id).quantity == SEATS
    assert session.query(OrganizationMember).filter_by(organization_id=ns.org).count() == 4


def test_renewal_may_reduce_seats_but_not_below_paid_occupancy(db, monkeypatch):
    session = db.session
    ns, who = seed_org(session, members=4), staff(session)
    contract, term, _activation = active_contract(session, ns, who)
    renewal, _ = record_contract_version(
        session, command_id="renew-low", billing_account_id=ns.account, contract_id=contract.id,
        version_kind="renewal", term_version_id=term.id, terms=terms(_utc(term.term_ends_at), committed_seats=3),
        executed_reference="executed:renewal", executed_evidence_reference="evidence:renewal",
        actor_user_id=who.user, delivery_obligations=DELIVERIES,
    )
    renewal = approve(session, ns, who, contract, renewal)
    fund(session, ns, who, contract, renewal, stripe_payment(session, ns, renewal))
    at_time(monkeypatch, _utc(term.term_ends_at) + timedelta(minutes=1))
    refused(session, ContractPolicyRequiredError, "occupancy", activate, session, ns, who, contract, renewal)
    # Freeing occupancy (no member or work is removed by billing) lets it apply.
    session.execute(sa.update(OrganizationMember).where(
        OrganizationMember.organization_id == ns.org, OrganizationMember.user_id == ns.members[-1],
    ).values(role="viewer"))
    session.flush()
    _activation, state = activate(session, ns, who, contract, renewal)
    assert state == "inserted"
    assert current_seat_commitment(session, renewal.subscription_id).quantity == 3


# ---------------------------------------------------------------------------
# Renewals, nonrenewal notices, grace, and end of paid access
# ---------------------------------------------------------------------------

def _auto_renew(session, ns, who, contract, term):
    return prepare_automatic_renewal(
        session, command_id=f"auto-{uuid.uuid4().hex[:6]}", billing_account_id=ns.account,
        contract_id=contract.id, term_version_id=term.id, actor_user_id=who.user, delivery_obligations=DELIVERIES,
    )


def test_automatic_renewal_keeps_terms_and_never_carries_prior_term_credits(db, monkeypatch):
    session = db.session
    ns, who = seed_org(session), staff(session)
    contract, term, _activation = active_contract(session, ns, who)
    [old_lot] = lots_of(session, ns.account)
    renewal, state = _auto_renew(session, ns, who, contract, term)
    assert state == "inserted" and renewal.state == "approved"
    assert (renewal.price_minor, renewal.committed_seats, renewal.monthly_credit_amount, renewal.interval) == (
        term.price_minor, term.committed_seats, term.monthly_credit_amount, term.interval,
    )
    assert _utc(renewal.term_starts_at) == _utc(term.term_ends_at)
    assert renewal.subscription_id != term.subscription_id  # a fresh annual cycle
    again, replay = _auto_renew(session, ns, who, contract, term)
    assert (replay, again.id) == ("duplicate", renewal.id)
    fund(session, ns, who, contract, renewal, stripe_payment(session, ns, renewal))
    boundary = _utc(term.term_ends_at)
    at_time(monkeypatch, boundary + timedelta(minutes=5))
    _activation, state = activate(session, ns, who, contract, renewal)
    assert state == "inserted"
    assert session.get(EnterpriseContractVersion, term.id).state == "completed"
    new_lots = [lot for lot in lots_of(session, ns.account) if lot.id != old_lot.id]
    assert [_utc(lot.expires_at) for lot in new_lots] == [_utc(renewal.term_ends_at)]
    # Prior-term credits are not spendable in the new term.
    available = {b.lot.id for b in ordered_lot_balances(session, ns.account, boundary + timedelta(minutes=6))}
    assert old_lot.id not in available and new_lots[0].id in available


def test_timely_nonrenewal_blocks_automatic_renewal_and_can_be_reversed_before_the_deadline(db, monkeypatch):
    session = db.session
    ns, who = seed_org(session), staff(session)
    contract, term, _activation = active_contract(session, ns, who)
    notice, _ = record_nonrenewal_notice(
        session, command_id="nr-1", billing_account_id=ns.account, contract_id=contract.id,
        term_version_id=term.id, evidence_reference="evidence:customer-email", actor_user_id=who.user,
        delivery_obligations=DELIVERIES,
    )
    assert notice.timely and _utc(notice.deadline_at) == _utc(term.term_ends_at) - timedelta(days=30)
    # A notice never shortens current paid access.
    assert contract_access_state(session, billing_account_id=ns.account)["state"] == "paid"
    refused(session, ContractError, "nonrenewal notice is in effect", _auto_renew, session, ns, who, contract, term)
    reversal, _ = reverse_nonrenewal_notice(
        session, command_id="nr-1-rev", billing_account_id=ns.account, contract_id=contract.id,
        notice_id=notice.id, evidence_reference="evidence:customer-email-2", actor_user_id=who.user,
        delivery_obligations=DELIVERIES,
    )
    assert reversal.reverses_notice_id == notice.id
    renewal, state = _auto_renew(session, ns, who, contract, term)
    assert state == "inserted"
    # A notice after the deadline is recorded as late and does not stop the renewal.
    at_time(monkeypatch, _utc(term.term_ends_at) - timedelta(days=10))
    late, _ = record_nonrenewal_notice(
        session, command_id="nr-late", billing_account_id=ns.account, contract_id=contract.id,
        term_version_id=term.id, evidence_reference="evidence:late", actor_user_id=who.user,
        delivery_obligations=DELIVERIES,
    )
    assert late.timely is False
    with pytest.raises(ContractError, match="deadline has passed|only an effective"):
        reverse_nonrenewal_notice(
            session, command_id="late-rev", billing_account_id=ns.account, contract_id=contract.id,
            notice_id=late.id, evidence_reference="e", actor_user_id=who.user, delivery_obligations=DELIVERIES,
        )
    assert session.get(EnterpriseContractVersion, renewal.id).state == "approved"


def test_timely_nonrenewal_ends_paid_access_at_term_end_without_grace(db, monkeypatch):
    session = db.session
    ns, who = seed_org(session, members=3), staff(session)
    contract, term, _activation = active_contract(session, ns, who)
    record_nonrenewal_notice(
        session, command_id="nr", billing_account_id=ns.account, contract_id=contract.id,
        term_version_id=term.id, evidence_reference="evidence:notice", actor_user_id=who.user,
        delivery_obligations=DELIVERIES,
    )
    refused(session, ContractError, "has not ended", complete_contract_term, session, command_id="early",
            billing_account_id=ns.account, contract_id=contract.id, version_id=term.id,
            actor_user_id=who.user, delivery_obligations=DELIVERIES)
    end = _utc(term.term_ends_at)
    at_time(monkeypatch, end + timedelta(minutes=1))
    complete_contract_term(
        session, command_id="done", billing_account_id=ns.account, contract_id=contract.id,
        version_id=term.id, actor_user_id=who.user, delivery_obligations=DELIVERIES,
    )
    session.refresh(contract)
    assert contract.state == "ended" and _utc(contract.paid_access_ended_at) == end
    assert _utc(contract.retention_review_until) == end + timedelta(days=180)
    state = contract_access_state(session, billing_account_id=ns.account, at=end + timedelta(minutes=1))
    assert state["state"] == "read_only_retention"
    # Members, the organization, and the billing account are never deleted.
    assert session.query(OrganizationMember).filter_by(organization_id=ns.org).count() == 3
    assert session.get(Organization, ns.org) is not None and session.get(BillingAccount, ns.account) is not None


def test_unpaid_renewal_grace_is_read_only_and_creates_no_funded_benefit(db, monkeypatch):
    session = db.session
    ns, who = seed_org(session), staff(session)
    contract, term, _activation = active_contract(session, ns, who)
    renewal, _ = _auto_renew(session, ns, who, contract, term)
    end = _utc(term.term_ends_at)
    lots_before = {lot.id for lot in lots_of(session, ns.account)}
    at_time(monkeypatch, end + timedelta(hours=1))
    complete_contract_term(
        session, command_id="complete", billing_account_id=ns.account, contract_id=contract.id,
        version_id=term.id, actor_user_id=who.user, delivery_obligations=DELIVERIES,
    )
    session.refresh(contract)
    assert contract.state == "renewal_grace"
    state = contract_access_state(session, billing_account_id=ns.account, at=end + timedelta(days=3))
    assert state["state"] == "read_only_grace" and state["grace_ends_at"] == end + timedelta(days=15)
    assert state["paid_access_ended_at"] == end  # paid benefits ended at the paid end date
    # No new-term benefit without payment.
    refused(session, ContractFundingError, "verified funding", activate, session, ns, who, contract, renewal)
    assert {lot.id for lot in lots_of(session, ns.account)} == lots_before
    assert spendable(session, ns.account, end + timedelta(hours=2)) == 0
    assert session.get(EntitlementInstance, renewal.entitlement_instance_id).state == "proposed"
    refused(session, ContractError, "has not ended", end_contract_after_grace, session, command_id="g1",
            billing_account_id=ns.account, contract_id=contract.id, actor_user_id=who.user,
            delivery_obligations=DELIVERIES)
    # Verified payment within grace restores paid access with fresh term credits.
    fund(session, ns, who, contract, renewal, stripe_payment(session, ns, renewal))
    at_time(monkeypatch, end + timedelta(days=5))
    _activation, state = activate(session, ns, who, contract, renewal)
    assert state == "inserted"
    session.refresh(contract)
    assert contract.state == "active"
    assert contract_access_state(session, billing_account_id=ns.account, at=end + timedelta(days=5, minutes=1))[
        "state"] == "paid"


def test_unpaid_grace_lapse_ends_access_at_the_paid_end_and_preserves_data(db, monkeypatch):
    session = db.session
    ns, who = seed_org(session, members=2), staff(session)
    contract, term, _activation = active_contract(session, ns, who)
    renewal, _ = _auto_renew(session, ns, who, contract, term)
    end = _utc(term.term_ends_at)
    at_time(monkeypatch, end + timedelta(hours=1))
    complete_contract_term(
        session, command_id="complete", billing_account_id=ns.account, contract_id=contract.id,
        version_id=term.id, actor_user_id=who.user, delivery_obligations=DELIVERIES,
    )
    at_time(monkeypatch, end + timedelta(days=15))
    end_contract_after_grace(session, command_id="lapse", billing_account_id=ns.account, contract_id=contract.id,
                             actor_user_id=who.user, delivery_obligations=DELIVERIES)
    session.refresh(contract)
    assert contract.state == "ended" and _utc(contract.paid_access_ended_at) == end
    assert _utc(contract.retention_review_until) == end + timedelta(days=180)
    # B1: the lapsed term's renewal stays open so a payment made within grace
    # but recorded later can still be bound to it.
    assert session.get(EnterpriseContractVersion, renewal.id).state == "approved"
    assert session.query(OrganizationMember).filter_by(organization_id=ns.org).count() == 2
    with pytest.raises(ContractError, match="ended or cancelled"):
        _amend(session, ns, who, contract, term, SEATS + 1)


def test_manual_renewal_term_without_a_renewal_ends_at_term_end(db, monkeypatch):
    session = db.session
    ns, who = seed_org(session), staff(session)
    contract, term, _activation = active_contract(session, ns, who, renewal_mode="manual")
    with pytest.raises(ContractError, match="renews manually"):
        _auto_renew(session, ns, who, contract, term)
    at_time(monkeypatch, _utc(term.term_ends_at))
    complete_contract_term(
        session, command_id="c", billing_account_id=ns.account, contract_id=contract.id, version_id=term.id,
        actor_user_id=who.user, delivery_obligations=DELIVERIES,
    )
    session.refresh(contract)
    assert contract.state == "ended"


def test_monthly_contract_credits_expire_monthly(db):
    session = db.session
    ns, who = seed_org(session), staff(session)
    _contract, version, _activation = active_contract(session, ns, who, interval="month", price_minor=100_000)
    [lot] = lots_of(session, ns.account)
    assert _utc(lot.expires_at) == _utc(version.term_ends_at)
    assert _utc(version.term_ends_at) == add_calendar_months(_utc(version.term_starts_at), 1)


def test_cancelling_a_funded_version_needs_a_refund_decision(db):
    session = db.session
    ns, who = seed_org(session), staff(session)
    contract, version = record(session, ns, who, db_now(session) + timedelta(days=10))
    version = approve(session, ns, who, contract, version)
    fund(session, ns, who, contract, version, stripe_payment(session, ns, version))
    with pytest.raises(ContractPolicyRequiredError, match="refund"):
        cancel_contract_version(
            session, command_id="cx", billing_account_id=ns.account, contract_id=contract.id,
            version_id=version.id, reason="customer withdrew", evidence_reference="e", actor_user_id=who.user,
            delivery_obligations=DELIVERIES,
        )


def test_automatic_renewal_after_a_priced_seat_amendment_needs_an_executed_renewal(db):
    session = db.session
    ns, who = seed_org(session), staff(session)
    contract, term, _activation = active_contract(session, ns, who)
    amendment = approve(session, ns, who, contract, _amend(session, ns, who, contract, term, SEATS + 1))
    with pytest.raises(ContractPolicyRequiredError, match="renewal price"):
        _auto_renew(session, ns, who, contract, term)
    assert amendment.state == "approved"


def test_phase11_service_has_no_live_runtime_callers():
    app_dir = BACKEND_DIR / "app"
    callers = [
        str(path.relative_to(BACKEND_DIR))
        for path in app_dir.rglob("*.py")
        if path.name not in {"billing_enterprise_contracts.py", "models_billing_phase11.py", "models.py",
                             "billing_allocations.py", "billing_plan_changes.py", "billing_seats.py",
                             "billing_projections.py"}  # Phase 13 projections are inactive and read only.
        and ("billing_enterprise_contracts" in path.read_text() or "models_billing_phase11" in path.read_text())
    ]
    assert callers == []


# ---------------------------------------------------------------------------
# Migration: SQLite parity, downgrade safety
# ---------------------------------------------------------------------------

def _revision():
    return ScriptDirectory(MIGRATIONS_DIR).get_revision(REVISION).module


@contextlib.contextmanager
def _ops(engine):
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            yield connection


def _statements(module_name, function_name):
    """Every statement an earlier revision's guard function executes, in order."""
    from importlib import import_module
    module = import_module(f"migrations.versions.{module_name}")
    recorder, original = _revision()._Recorder(), module.op
    module.op = recorder
    try:
        getattr(module, function_name)()
    finally:
        module.op = original
    return recorder.statements


def _predecessor(engine):
    """The Phase 10 schema: models without Phase 11 tables, columns, or constraint texts."""
    from alembic import op
    tables = [t for t in flask_db.metadata.sorted_tables if t.name not in PHASE11_TABLES]
    flask_db.metadata.create_all(engine, tables=tables)
    module = _revision()
    pg = engine.dialect.name == "postgresql"
    # Phase 14 extends the same permission CHECK; restore the Phase 11 form first.
    from alembic.script import ScriptDirectory
    phase14 = ScriptDirectory(str(MIGRATIONS_DIR)).get_revision("d2f4a6c8e0b3").module
    with _ops(engine) as connection:
        p14_table, p14_name, p14_old, p14_new = phase14.PERMISSION_CHECK
        if pg:
            connection.execute(sa.text(f"ALTER TABLE {p14_table} DROP CONSTRAINT {p14_name}"))
            connection.execute(sa.text(f"ALTER TABLE {p14_table} ADD CONSTRAINT {p14_name} CHECK ({p14_old})"))
        else:
            module._sqlite_replace_check(p14_table, p14_new, p14_old)
        for table, name, old, new in module.CHECKS:
            if pg:
                connection.execute(sa.text(f"ALTER TABLE {table} DROP CONSTRAINT {name}"))
                connection.execute(sa.text(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({old})"))
            else:
                module._sqlite_replace_check(table, new, old)
        op.drop_index("ix_credit_purchase_fundings_expiry_subscription", table_name="credit_purchase_fundings")
        if pg:
            op.drop_column("credit_purchase_fundings", "expires_at")
            op.drop_column("credit_purchase_fundings", "expiry_subscription_id")
        else:
            with op.batch_alter_table("credit_purchase_fundings", recreate="always") as batch:
                batch.drop_column("expires_at")
                batch.drop_column("expiry_subscription_id")
        # The earlier guards Phase 11 replaces or depends on, from their own revisions.
        if pg:
            for statement in _statements("b8c2d4e6f8a1_add_seat_commitments", "_postgresql_guards"):
                op.execute(statement)
            for statement in module._pg_originals().values():
                op.execute(statement)
        else:
            for statement in _statements("e1a3c5b7d9f2_add_financial_effects", "_sqlite_guards"):
                op.execute(statement)
            for name, statement in module._sqlite_originals().items():
                op.execute(f"DROP TRIGGER IF EXISTS {name}")
                op.execute(statement)


def _assert_models_match(engine):
    from app import models_billing_phase11 as phase11
    inspector = sa.inspect(engine)
    for model in (
        phase11.EnterpriseContract, phase11.EnterpriseContractVersion, phase11.EnterpriseContractEvent,
        phase11.EnterpriseContractTermFunding, phase11.EnterpriseContractActivation, phase11.EnterpriseContractNotice,
    ):
        table = model.__table__
        assert {c.name for c in table.columns} == {c["name"] for c in inspector.get_columns(table.name)}
        model_checks = {c.name for c in table.constraints if isinstance(c, sa.CheckConstraint)}
        model_uniques = {c.name for c in table.constraints if isinstance(c, sa.UniqueConstraint)}
        assert model_checks == {c["name"] for c in inspector.get_check_constraints(table.name)}, table.name
        assert model_uniques == {c["name"] for c in inspector.get_unique_constraints(table.name)}, table.name
        assert {i.name for i in table.indexes} <= {i["name"] for i in inspector.get_indexes(table.name)}
    funding_columns = {c["name"] for c in inspector.get_columns("credit_purchase_fundings")}
    assert {"expiry_subscription_id", "expires_at"} <= funding_columns


def test_revision_extends_phase10_and_is_single_head():
    script = ScriptDirectory(MIGRATIONS_DIR)
    assert script.get_heads() == ["c8a9989843b5"]  # BI-1 extends the Phase 17 guard, which extends Phase 14 without changing Phase 11.
    assert script.get_revision("c8e0a2b4d6f1").down_revision == REVISION
    assert script.get_revision(REVISION).down_revision == PARENT


def test_captured_guard_patches_apply_exactly_once():
    module = _revision()
    pg = module._pg_replacements(module._pg_originals())
    assert "current_term_end" in pg["phase9_purchase_funding_guard"]
    assert "jaspen_contract" in pg["phase6_allocation_guard"]
    assert "annual_monthly" in pg["phase6_recurring_lot_guard"]
    sqlite = module._sqlite_replacements(module._sqlite_originals())
    assert "julianday(f.expires_at)" in sqlite["trg_phase9_purchase_lot_insert"]


def test_sqlite_migration_matches_models_guards_and_downgrade_is_safe(tmp_path):
    module = _revision()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'phase11.sqlite'}")
    try:
        _predecessor(engine)
        with _ops(engine):
            module.upgrade()
        _assert_models_match(engine)
        with engine.connect() as connection:
            names = set(connection.execute(sa.text(
                "SELECT name FROM sqlite_master WHERE type='trigger'")).scalars())
            assert set(module._sqlite_trigger_names()) <= names
            sql = connection.execute(sa.text(
                "SELECT sql FROM sqlite_master WHERE name='entitlement_instances'")).scalar_one()
            assert "OR subscription_id IS NOT NULL" in sql and "state IN ('proposed','cancelled')" not in sql
        with _ops(engine):
            module.downgrade()
        assert not set(sa.inspect(engine).get_table_names()) & set(PHASE11_TABLES)
        with engine.connect() as connection:
            sql = connection.execute(sa.text(
                "SELECT sql FROM sqlite_master WHERE name='entitlement_instances'")).scalar_one()
            assert "state IN ('proposed','cancelled')" in sql
            lot_trigger = connection.execute(sa.text(
                "SELECT sql FROM sqlite_master WHERE name='trg_phase9_purchase_lot_insert'")).scalar_one()
            assert "NEW.expires_at IS NULL" in lot_trigger
            funding_sql = connection.execute(sa.text(
                "SELECT sql FROM sqlite_master WHERE name='credit_purchase_fundings'")).scalar_one()
            assert "ck_credit_purchase_fundings_identity" in funding_sql and "expires_at" not in funding_sql
            assert {"trg_phase9_credit_purchase_fundings_update", "trg_phase9_credit_purchase_fundings_delete"} <= set(
                connection.execute(sa.text("SELECT name FROM sqlite_master WHERE type='trigger'")).scalars())
        with _ops(engine):
            module.upgrade()
        with engine.begin() as connection:
            connection.execute(sa.text("PRAGMA foreign_keys=OFF"))
            connection.execute(sa.text(
                "INSERT INTO enterprise_contract_term_fundings (id,contract_id,version_id,billing_account_id,"
                "subscription_id,financial_transaction_id,financial_line_id,amount_minor,currency,paid_at,"
                "recorded_at,actor_user_id,permission_grant_id,idempotency_registry_id,domain_event_id) VALUES "
                "('f1','c','v','a','s','t','l',10,'usd','2026-01-31','2026-01-31','u','g','r','e')"
            ))
            for statement in ("UPDATE enterprise_contract_term_fundings SET amount_minor=99",
                              "DELETE FROM enterprise_contract_term_fundings"):
                with pytest.raises(sa.exc.DBAPIError):
                    connection.execute(sa.text(statement))
        with pytest.raises(module.Phase11EvidenceNotEmptyError):
            with _ops(engine):
                module.downgrade()
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# PostgreSQL: fully migrated database, every guard live
# ---------------------------------------------------------------------------

def _migrated_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("local disposable PostgreSQL is not configured")
    engine = sa.create_engine(url, pool_size=10, max_overflow=4)
    with engine.connect() as connection:
        revision = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    if revision not in {REVISION, "c8e0a2b4d6f1", "d2f4a6c8e0b3", "f3a5c7e9b1d2", "c8a9989843b5"}:
        engine.dispose()
        pytest.fail(f"Phase 11 migrated tests require Alembic head {REVISION}; found {revision!r}")
    return engine


@contextlib.contextmanager
def migrated_session(engine, isolation="READ COMMITTED"):
    with Session(engine.execution_options(isolation_level=isolation), expire_on_commit=False) as session:
        yield session


def _pg_contract(engine):
    """Record, approve, fund, and activate one annual contract on the migrated schema."""
    with migrated_session(engine) as session:
        ns, who = seed_org(session), staff(session)
        session.commit()
        contract, version = record(session, ns, who, db_now(session) - timedelta(hours=1))
        session.commit()
        version = approve(session, ns, who, contract, version)
        session.commit()
        line_id = stripe_payment(session, ns, version)
        session.commit()
        fund(session, ns, who, contract, version, line_id)
        session.commit()
        return ns, who, contract.id, version.id


@PG
def test_postgres_migrated_contract_lifecycle_passes_every_guard():
    engine = _migrated_engine()
    try:
        ns, who, contract_id, version_id = _pg_contract(engine)
        with migrated_session(engine) as session:
            contract = session.get(EnterpriseContract, contract_id)
            version = session.get(EnterpriseContractVersion, version_id)
            activation, state = activate(session, ns, who, contract, version)
            session.commit()
            assert state == "inserted"
            [lot] = lots_of(session, ns.account)
            assert _utc(lot.expires_at) == _utc(version.term_ends_at)
            assert current_seat_commitment(session, version.subscription_id).origin_type == "contract"
            amendment = _amend(session, ns, who, contract, version, SEATS + 2)
            session.commit()
            amendment = approve(session, ns, who, contract, amendment)
            session.commit()
            fund(session, ns, who, contract, amendment, stripe_payment(session, ns, amendment, seat=True))
            session.commit()
            activate(session, ns, who, contract, amendment)
            session.commit()
            assert current_seat_commitment(session, version.subscription_id).quantity == SEATS + 2
            period = session.execute(sa.select(CreditPeriod).where(CreditPeriod.funded_lot_id == lot.id)).scalar_one()
            # The annual lot runs to the term end, so its month-0 period cannot expire now.
            with pytest.raises(RecurringAllocationError, match="not reached their expiry"):
                expire(session, period, datetime.now(timezone.utc))
            session.rollback()
    finally:
        engine.dispose()


@PG
@pytest.mark.parametrize("statement,message", [
    ("UPDATE enterprise_contract_versions SET price_minor=price_minor+1 WHERE id=:version",
     "executed contract terms and evidence are immutable"),
    ("UPDATE enterprise_contracts SET state='ended' WHERE id=:contract",
     "require an append-only event"),
    ("DELETE FROM enterprise_contract_versions WHERE id=:version", "historical records"),
    ("UPDATE enterprise_contract_term_fundings SET amount_minor=1 WHERE version_id=:version", "immutable"),
])
def test_postgres_migrated_direct_sql_cannot_rewrite_contract_evidence(statement, message):
    engine = _migrated_engine()
    try:
        _ns, _who, contract_id, version_id = _pg_contract(engine)
        with engine.connect() as connection:
            with pytest.raises(sa.exc.DBAPIError, match=message):
                connection.execute(sa.text(statement), {"version": version_id, "contract": contract_id})
            connection.rollback()
    finally:
        engine.dispose()


@PG
def test_postgres_migrated_guards_refuse_bypass_of_activation_and_customer_commands():
    engine = _migrated_engine()
    try:
        ns, who, contract_id, version_id = _pg_contract(engine)
        with engine.connect() as connection:
            version = connection.execute(sa.text(
                "SELECT entitlement_instance_id, subscription_id FROM enterprise_contract_versions WHERE id=:v"
            ), {"v": version_id}).one()
            connection.execute(sa.text(
                "INSERT INTO idempotency_registry (id,namespace,key,request_fingerprint,state,claimed_at) "
                "VALUES ('p11-bypass-r','t','p11-bypass','" + "a" * 64 + "','claimed',now())"
            ))
            # Enterprise entitlement cannot leave proposed without activation evidence.
            with pytest.raises(sa.exc.DBAPIError, match="Phase 11 contract activation evidence"):
                connection.execute(sa.text(
                    "INSERT INTO entitlement_events (id,entitlement_instance_id,transition,from_state,to_state,"
                    "effective_at,created_at,actor_type,actor_id,source_type,source_id,idempotency_registry_id,"
                    "evidence_json) VALUES ('p11-e','" + version.entitlement_instance_id + "','t','proposed',"
                    "'scheduled',now(),now(),'system','x','test','x','p11-bypass-r','{}')"
                ))
            connection.rollback()
        with engine.connect() as connection:
            # A customer seat command row on a contract-backed term is refused.
            with pytest.raises(sa.exc.DBAPIError, match="Enterprise contract version"):
                connection.execute(sa.text(
                    "INSERT INTO seat_changes (id,billing_account_id,subscription_id,kind,state,base_commitment_id,"
                    "base_quantity,target_quantity,occupancy_at_request,requested_at,effective_at,"
                    "authorizing_role_grant_id,requested_by_user_id,command_key,request_fingerprint,"
                    "idempotency_registry_id,domain_event_id) VALUES ('p11-sc',:a,:s,'increase','increased','x',"
                    "1,2,1,now(),now(),'g',:u,'k','" + "b" * 64 + "','r','e')"
                ), {"a": ns.account, "s": version.subscription_id, "u": ns.owner})
            connection.rollback()
        with engine.connect() as connection:
            # Activation before the effective date is refused by the database.
            connection.execute(sa.text(
                "UPDATE enterprise_contract_versions SET state=state WHERE id=:v"), {"v": version_id})
            with pytest.raises(sa.exc.DBAPIError, match="approved, effective, fully funded"):
                connection.execute(sa.text(
                    "INSERT INTO enterprise_contract_activations (id,contract_id,version_id,billing_account_id,"
                    "subscription_id,entitlement_instance_id,term_funding_id,seat_commitment_id,seats,activated_at,"
                    "actor_user_id,permission_grant_id,idempotency_registry_id,domain_event_id) SELECT 'p11-a',"
                    "f.contract_id,f.version_id,f.billing_account_id,f.subscription_id,:i,f.id,'p11-sc',3,now(),"
                    ":u,:g,f.idempotency_registry_id,f.domain_event_id FROM enterprise_contract_term_fundings f "
                    "WHERE f.version_id=:v"
                ), {"v": version_id, "i": version.entitlement_instance_id, "u": who.user, "g": who.grant})
            connection.rollback()
    finally:
        engine.dispose()


@PG
def test_postgres_migrated_commands_require_read_committed():
    engine = _migrated_engine()
    try:
        ns, who, contract_id, version_id = _pg_contract(engine)
        for level in ("REPEATABLE READ", "SERIALIZABLE"):
            with migrated_session(engine, level) as session:
                contract = session.get(EnterpriseContract, contract_id)
                version = session.get(EnterpriseContractVersion, version_id)
                with pytest.raises(ContractIsolationError):
                    activate(session, ns, who, contract, version)
                session.rollback()
    finally:
        engine.dispose()


@PG
def test_postgres_concurrent_activation_and_funding_converge_to_one_effect():
    engine = _migrated_engine()
    try:
        ns, who, contract_id, version_id = _pg_contract(engine)
        barrier = threading.Barrier(2)

        def run(_index):
            with migrated_session(engine) as session:
                contract = session.get(EnterpriseContract, contract_id)
                version = session.get(EnterpriseContractVersion, version_id)
                barrier.wait()
                try:
                    _activation, state = activate_contract_version(
                        session, command_id=f"race-{_index}", billing_account_id=ns.account,
                        contract_id=contract.id, version_id=version.id, actor_user_id=who.user,
                        delivery_obligations=DELIVERIES,
                    )
                    session.commit()
                    return state
                except (ContractError, sa.exc.DBAPIError) as exc:
                    session.rollback()
                    return type(exc).__name__

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(run, range(2)))
        assert outcomes.count("inserted") == 1
        with migrated_session(engine) as session:
            assert session.query(EnterpriseContractActivation).filter_by(version_id=version_id).count() == 1
            assert len(lots_of(session, ns.account)) == 1
    finally:
        engine.dispose()


@PG
def test_postgres_purchased_credit_expiration_is_guarded_by_its_term_end():
    engine = _migrated_engine()
    try:
        with migrated_session(engine) as session:
            ns = seed_org(session)
            sub = self_serve(session, ns, "month", anchor=datetime.now(timezone.utc) - timedelta(days=2))
            pack = _buy_pack(session, ns, datetime.now(timezone.utc) - timedelta(days=1))
            session.commit()
            funding = pack.fundings[0]
            assert _utc(funding.expires_at) == _utc(sub.term_end)
        with engine.connect() as connection:
            connection.execute(sa.text(
                "INSERT INTO idempotency_registry (id,namespace,key,request_fingerprint,state,claimed_at) "
                "VALUES ('p11-exp-r','t','p11-exp-" + uuid.uuid4().hex + "','" + "c" * 64 + "','claimed',now())"
            ))
            with pytest.raises(sa.exc.DBAPIError, match="paid term end"):
                connection.execute(sa.text(
                    "INSERT INTO credit_ledger_entries (id,billing_account_id,lot_id,entry_type,available_delta,"
                    "held_delta,idempotency_registry_id,effective_at,actor_type,actor_id,reason_code,evidence_json,"
                    "created_at) VALUES ('p11-x',:a,:l,'expiration',-1,0,'p11-exp-r',now(),'system','x','x','{}',now())"
                ), {"a": ns.account, "l": funding.lot_id})
            connection.rollback()
    finally:
        engine.dispose()


@PG
def test_postgres_isolated_migration_round_trip_restores_earlier_guards(validate_test_database_url,
                                                                        postgres_schema_url):
    base_url = validate_test_database_url(os.environ["TEST_DATABASE_URL"])
    schema = f"phase11_{uuid.uuid4().hex}"
    admin = sa.create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    engine = sa.create_engine(postgres_schema_url(base_url, schema))
    module = _revision()
    replaced = ("phase4_period_guard", "phase6_allocation_guard", "phase6_period_guard",
                "phase6_recurring_lot_guard", "phase7_upgrade_final", "phase9_purchase_funding_guard",
                "phase9_purchase_lot_guard")

    def definitions():
        with engine.connect() as connection:
            return {
                name: connection.execute(sa.text(
                    "SELECT pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                    "WHERE n.nspname=current_schema() AND p.proname=:name"), {"name": name}).scalar_one()
                for name in replaced
            }

    try:
        _predecessor(engine)
        before = definitions()
        with _ops(engine):
            module.upgrade()
        _assert_models_match(engine)
        after = definitions()
        assert all(before[name] != after[name] for name in replaced)
        with _ops(engine):
            module.downgrade()
        assert definitions() == before
        assert not set(sa.inspect(engine).get_table_names()) & set(PHASE11_TABLES)
        with engine.connect() as connection:
            leftover = connection.execute(sa.text(
                "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname=current_schema() AND p.proname LIKE 'phase11_%'")).scalar_one()
        assert leftover == 0
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


# ---------------------------------------------------------------------------
# PostgreSQL concurrency for annual-term allocation and expiration (P11-DEP-001)
# ---------------------------------------------------------------------------

ISOLATION_LEVELS = ("READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE")


def _past_annual(engine):
    """An annual term that started 13 months ago and has already ended."""
    anchor = add_calendar_months(datetime.now(timezone.utc) - timedelta(days=1), 0) - timedelta(days=400)
    with migrated_session(engine) as session:
        ns = seed_org(session)
        sub = self_serve(session, ns, "year", anchor=anchor)
        session.commit()
        return ns, Ns(instance_id=sub.instance.id, line=sub.line, anchor=anchor, term_end=sub.term_end)


def _allocate_past(session, ns, sub, index):
    start, _end = monthly_period_bounds(sub.anchor, index)
    return allocate_recurring_credits(
        session, billing_account_id=ns.account, entitlement_instance_id=sub.instance_id, period_index=index,
        opened_at=start + timedelta(hours=2), delivery_obligations=DELIVERIES, financial_line_id=sub.line,
        **SERVICE,
    )


@PG
@pytest.mark.parametrize("isolation", ISOLATION_LEVELS)
def test_postgres_concurrent_annual_allocation_creates_one_term_bound_lot(isolation):
    engine = _migrated_engine()
    try:
        ns, sub = _past_annual(engine)
        barrier = threading.Barrier(2)

        def run(_index):
            with migrated_session(engine, isolation) as session:
                barrier.wait()
                try:
                    state = _allocate_past(session, ns, sub, 2)[3]
                    session.commit()
                    return state
                except (RecurringAllocationError, sa.exc.DBAPIError) as exc:
                    session.rollback()
                    return getattr(getattr(exc, "orig", None), "sqlstate", None) or type(exc).__name__

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(run, range(2)))
        assert outcomes.count("inserted") == 1, outcomes
        with migrated_session(engine) as session:
            lots = lots_of(session, ns.account, "subscription_recurring")
            assert len(lots) == 1 and _utc(lots[0].expires_at) == _utc(sub.term_end)
    finally:
        engine.dispose()


@PG
@pytest.mark.parametrize("isolation", ISOLATION_LEVELS)
def test_postgres_concurrent_annual_expiration_at_the_term_end_converges(isolation):
    engine = _migrated_engine()
    try:
        ns, sub = _past_annual(engine)
        with migrated_session(engine) as session:
            periods = [_allocate_past(session, ns, sub, index)[1].id for index in range(3)]
            session.commit()
        barrier = threading.Barrier(2)

        def run(_index):
            with migrated_session(engine, isolation) as session:
                period = session.get(CreditPeriod, periods[0])
                barrier.wait()
                try:
                    _period, state = expire(session, period, datetime.now(timezone.utc))
                    session.commit()
                    return state
                except (RecurringAllocationError, sa.exc.DBAPIError) as exc:
                    session.rollback()
                    return getattr(getattr(exc, "orig", None), "sqlstate", None) or type(exc).__name__

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(run, range(2)))
        assert outcomes.count("expired") == 1, outcomes
        with migrated_session(engine) as session:
            expired = session.get(CreditPeriod, periods[0])
            assert expired.state == "expired" and balance(session, expired.funded_lot_id) == (0, 0)
            # The other months of the same term carried forward until the term end and are still funded.
            assert {session.get(CreditPeriod, pid).state for pid in periods[1:]} == {"funded"}
    finally:
        engine.dispose()


@PG
def test_postgres_annual_lot_cannot_be_inserted_with_a_month_end_expiry():
    """Direct SQL cannot create an annual release that expires at its month end."""
    engine = _migrated_engine()
    try:
        ns, sub = _past_annual(engine)
        with migrated_session(engine) as session:
            _allocation, period, lot, _state = _allocate_past(session, ns, sub, 0)
            session.commit()
        with engine.connect() as connection:
            with pytest.raises(sa.exc.DBAPIError, match="recurring lot requires"):
                connection.execute(sa.text(
                    "INSERT INTO credit_lots (id,billing_account_id,source_type,source_id,original_amount,"
                    "available_at,expires_at,origin_evidence_json,created_at) VALUES "
                    "('p11-lot-x',:a,'subscription_recurring',:p,:amount,:start,:end,'{}',now())"
                ), {"a": ns.account, "p": period.id, "amount": lot.original_amount,
                    "start": period.starts_at, "end": period.ends_at})
            connection.rollback()
    finally:
        engine.dispose()



# ---------------------------------------------------------------------------
# B1: funded versions are never cancelled or stranded; grace eligibility by payment time
# ---------------------------------------------------------------------------

def _funding_snapshot(session, version_id):
    funding = session.execute(sa.select(EnterpriseContractTermFunding).where(
        EnterpriseContractTermFunding.version_id == version_id)).scalar_one()
    return (funding.id, funding.financial_transaction_id, funding.financial_line_id, int(funding.amount_minor),
            funding.currency, _utc(funding.paid_at), funding.subscription_id)


def _review(session, ns, who):
    return {row["version_id"]: row for row in funded_versions_for_review(
        session, billing_account_id=ns.account, actor_user_id=who.user)}


def _complete(session, ns, who, contract, term, command="complete"):
    return complete_contract_term(
        session, command_id=command, billing_account_id=ns.account, contract_id=contract.id, version_id=term.id,
        actor_user_id=who.user, delivery_obligations=DELIVERIES,
    )


def _lapse(session, ns, who, contract, command="lapse"):
    return end_contract_after_grace(session, command_id=command, billing_account_id=ns.account,
                                    contract_id=contract.id, actor_user_id=who.user, delivery_obligations=DELIVERIES)


def test_b1_funded_renewal_paid_after_grace_survives_the_lapse_for_refund_review(db, monkeypatch):
    session = db.session
    ns, who = seed_org(session), staff(session)
    contract, term, _activation = active_contract(session, ns, who)
    renewal, _ = _auto_renew(session, ns, who, contract, term)
    end = _utc(term.term_ends_at)
    at_time(monkeypatch, end + timedelta(hours=1))
    _complete(session, ns, who, contract, term)
    at_time(monkeypatch, end + timedelta(days=15))
    _lapse(session, ns, who, contract)
    # Payment arrives after the grace deadline and is still recorded as evidence.
    at_time(monkeypatch, end + timedelta(days=17))
    fund(session, ns, who, contract, renewal,
         stripe_payment(session, ns, renewal, at=end + timedelta(days=16)))
    before = _funding_snapshot(session, renewal.id)
    refused(session, ContractPolicyRequiredError, "paid after the grace deadline",
            activate, session, ns, who, contract, renewal)
    session.refresh(contract)
    assert contract.state == "ended"
    assert session.get(EnterpriseContractVersion, renewal.id).state == "approved"
    assert _review(session, ns, who)[renewal.id]["reason"] == "paid_after_grace"
    assert _funding_snapshot(session, renewal.id) == before  # immutable evidence preserved
    assert spendable(session, ns.account, end + timedelta(days=17)) == 0  # no unfunded or unearned credit
    refused(session, ContractPolicyRequiredError, "refund", cancel_contract_version, session, command_id="cx",
            billing_account_id=ns.account, contract_id=contract.id, version_id=renewal.id, reason="r",
            evidence_reference="e", actor_user_id=who.user, delivery_obligations=DELIVERIES)


def test_b1_funded_amendment_survives_term_completion_for_refund_review(db, monkeypatch):
    session = db.session
    ns, who = seed_org(session), staff(session)
    contract, term, _activation = active_contract(session, ns, who, renewal_mode="manual")
    amendment = approve(session, ns, who, contract, _amend(
        session, ns, who, contract, term, SEATS + 2, effective_at=_utc(term.term_ends_at) - timedelta(days=1)))
    fund(session, ns, who, contract, amendment, stripe_payment(session, ns, amendment, seat=True))
    before = _funding_snapshot(session, amendment.id)
    at_time(monkeypatch, _utc(term.term_ends_at) + timedelta(minutes=5))
    _complete(session, ns, who, contract, term)
    session.refresh(contract)
    assert contract.state == "ended"
    assert session.get(EnterpriseContractVersion, amendment.id).state == "approved"
    assert _review(session, ns, who)[amendment.id]["reason"] == "amended_term_ended"
    refused(session, ContractError, "only during its active term", activate, session, ns, who, contract, amendment)
    assert _funding_snapshot(session, amendment.id) == before


def test_b1_funded_renewal_blocked_by_seat_floor_is_preserved_then_activates(db, monkeypatch):
    session = db.session
    ns, who = seed_org(session, members=4), staff(session)
    contract, term, _activation = active_contract(session, ns, who)
    renewal, _ = record_contract_version(
        session, command_id="renew-3", billing_account_id=ns.account, contract_id=contract.id,
        version_kind="renewal", term_version_id=term.id, terms=terms(_utc(term.term_ends_at), committed_seats=3),
        executed_reference="executed:renewal", executed_evidence_reference="evidence:renewal",
        actor_user_id=who.user, delivery_obligations=DELIVERIES,
    )
    renewal = approve(session, ns, who, contract, renewal)
    end = _utc(term.term_ends_at)
    at_time(monkeypatch, end + timedelta(hours=1))
    _complete(session, ns, who, contract, term)
    fund(session, ns, who, contract, renewal, stripe_payment(session, ns, renewal, at=end + timedelta(days=2)))
    refused(session, ContractPolicyRequiredError, "occupancy", activate, session, ns, who, contract, renewal)
    at_time(monkeypatch, end + timedelta(days=16))
    # Grace cannot lapse while a renewal paid within grace awaits activation.
    refused(session, ContractError, "awaits activation", _lapse, session, ns, who, contract)
    assert _review(session, ns, who)[renewal.id]["reason"] == "awaiting_activation"
    assert session.get(EnterpriseContractVersion, renewal.id).state == "approved"
    session.execute(sa.update(OrganizationMember).where(
        OrganizationMember.organization_id == ns.org, OrganizationMember.user_id == ns.members[-1],
    ).values(role="viewer"))
    session.flush()
    _activation, state = activate(session, ns, who, contract, renewal)
    assert state == "inserted"
    assert current_seat_commitment(session, renewal.subscription_id).quantity == 3
    assert renewal.id not in _review(session, ns, who)


def test_b1_timely_nonrenewal_with_a_funded_renewal_ends_access_and_keeps_the_payment(db, monkeypatch):
    session = db.session
    ns, who = seed_org(session), staff(session)
    contract, term, _activation = active_contract(session, ns, who)
    renewal, _ = _auto_renew(session, ns, who, contract, term)
    fund(session, ns, who, contract, renewal, stripe_payment(session, ns, renewal))
    record_nonrenewal_notice(
        session, command_id="nr", billing_account_id=ns.account, contract_id=contract.id, term_version_id=term.id,
        evidence_reference="evidence:notice", actor_user_id=who.user, delivery_obligations=DELIVERIES,
    )
    end = _utc(term.term_ends_at)
    at_time(monkeypatch, end + timedelta(minutes=1))
    refused(session, ContractPolicyRequiredError, "nonrenewal", activate, session, ns, who, contract, renewal)
    _complete(session, ns, who, contract, term)
    session.refresh(contract)
    assert contract.state == "ended" and _utc(contract.paid_access_ended_at) == end
    assert session.get(EnterpriseContractVersion, renewal.id).state == "approved"
    assert _review(session, ns, who)[renewal.id]["reason"] == "nonrenewal_in_effect"


@pytest.mark.parametrize("lapsed_first", [False, True])
def test_b1_payment_within_grace_activates_after_grace_without_extra_credit(db, monkeypatch, lapsed_first):
    session = db.session
    ns, who = seed_org(session), staff(session)
    contract, term, _activation = active_contract(session, ns, who)
    renewal, _ = _auto_renew(session, ns, who, contract, term)
    end = _utc(term.term_ends_at)
    at_time(monkeypatch, end + timedelta(hours=1))
    _complete(session, ns, who, contract, term)
    line_id = stripe_payment(session, ns, renewal, at=end + timedelta(days=3))  # verified within grace
    if lapsed_first:
        # Internal processing was late: the lapse ran before the payment was bound.
        at_time(monkeypatch, end + timedelta(days=16))
        _lapse(session, ns, who, contract)
        session.refresh(contract)
        assert contract.state == "ended"
    at_time(monkeypatch, end + timedelta(days=20))
    fund(session, ns, who, contract, renewal, line_id)
    activation, state = activate(session, ns, who, contract, renewal)
    again, replay = activate(session, ns, who, contract, renewal)
    assert (state, replay, again.id) == ("inserted", "duplicate", activation.id)
    session.refresh(contract)
    assert contract.state == "active" and contract.paid_access_ended_at is None
    assert contract.retention_review_until is None
    # The paid term is not extended and exactly one month's credits are released.
    assert _utc(renewal.term_starts_at) == end
    new_lots = [lot for lot in lots_of(session, ns.account) if _utc(lot.expires_at) == _utc(renewal.term_ends_at)]
    assert [lot.original_amount for lot in new_lots] == [CREDITS]
    assert contract_access_state(session, billing_account_id=ns.account, at=end + timedelta(days=20))["state"] == "paid"


def test_b1_term_activation_after_its_first_month_needs_a_catch_up_decision(db, monkeypatch):
    session = db.session
    ns, who = seed_org(session), staff(session)
    start = db_now(session) - timedelta(hours=1)
    contract, version = record(session, ns, who, start)
    version = approve(session, ns, who, contract, version)
    fund(session, ns, who, contract, version, stripe_payment(session, ns, version))
    at_time(monkeypatch, add_calendar_months(start, 1) + timedelta(minutes=1))
    refused(session, ContractPolicyRequiredError, "catch-up", activate, session, ns, who, contract, version)
    assert lots_of(session, ns.account) == []
    assert _review(session, ns, who)[version.id]["reason"] == "catch_up_policy_required"


def test_b1_refund_review_is_staff_only_and_scoped_to_one_organization(db):
    session = db.session
    first, second, who = seed_org(session), seed_org(session), staff(session)
    contract, version = record(session, first, who, db_now(session) + timedelta(days=5))
    version = approve(session, first, who, contract, version)
    fund(session, first, who, contract, version, stripe_payment(session, first, version))
    assert set(_review(session, first, who)) == {version.id}
    assert _review(session, second, who) == {}
    with pytest.raises(ContractPermissionError):
        funded_versions_for_review(session, billing_account_id=first.account, actor_user_id=first.owner)
    with pytest.raises(ContractError, match="not available for this billing account"):
        cancel_contract_version(
            session, command_id="x", billing_account_id=second.account, contract_id=contract.id,
            version_id=version.id, reason="r", evidence_reference="e", actor_user_id=who.user,
            delivery_obligations=DELIVERIES,
        )


def test_b1_repeated_lapse_is_idempotent_per_term(db, monkeypatch):
    session = db.session
    ns, who = seed_org(session), staff(session)
    contract, term, _activation = active_contract(session, ns, who)
    _auto_renew(session, ns, who, contract, term)
    end = _utc(term.term_ends_at)
    at_time(monkeypatch, end + timedelta(hours=1))
    _complete(session, ns, who, contract, term)
    at_time(monkeypatch, end + timedelta(days=15))
    first, state = _lapse(session, ns, who, contract, "lapse-1")
    again, replay = _lapse(session, ns, who, contract, "lapse-2")
    assert (state, replay, again.id) == ("inserted", "duplicate", first.id)


def test_b1_sqlite_migration_refuses_cancelling_a_funded_version(tmp_path):
    module = _revision()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'b1.sqlite'}")
    try:
        _predecessor(engine)
        with _ops(engine):
            module.upgrade()
        with engine.begin() as connection:
            connection.execute(sa.text("PRAGMA foreign_keys=OFF"))
            connection.execute(sa.text(
                "INSERT INTO enterprise_contract_versions (id,contract_id,billing_account_id,version_number,"
                "version_kind,term_version_id,effective_at,currency,price_minor,committed_seats,executed_reference,"
                "executed_evidence_reference,recorded_by_user_id,recorded_permission_grant_id,request_fingerprint,"
                "idempotency_registry_id,recorded_at,state) VALUES ('v1','c','a',2,'amendment','t',"
                "'2026-02-01','usd',10,3,'x','y','u','g',:fp,'r','2026-02-01','approved')"
            ), {"fp": "a" * 64})
            connection.execute(sa.text(
                "INSERT INTO enterprise_contract_term_fundings (id,contract_id,version_id,billing_account_id,"
                "subscription_id,financial_transaction_id,financial_line_id,amount_minor,currency,paid_at,"
                "recorded_at,actor_user_id,permission_grant_id,idempotency_registry_id,domain_event_id) VALUES "
                "('f1','c','v1','a','s','t','l',10,'usd','2026-01-31','2026-01-31','u','g','r2','e')"
            ))
            with pytest.raises(sa.exc.DBAPIError, match="funded contract version cannot be cancelled"):
                connection.execute(sa.text(
                    "UPDATE enterprise_contract_versions SET state='cancelled', last_event_id='ev' WHERE id='v1'"))
    finally:
        engine.dispose()


@PG
def test_postgres_b1_database_refuses_cancelling_a_funded_version():
    engine = _migrated_engine()
    try:
        _ns, _who, _contract_id, version_id = _pg_contract(engine)  # approved and funded
        with engine.connect() as connection:
            with pytest.raises(sa.exc.DBAPIError, match="funded contract version cannot be cancelled"):
                connection.execute(sa.text(
                    "UPDATE enterprise_contract_versions SET state='cancelled' WHERE id=:v"), {"v": version_id})
            connection.rollback()
            with pytest.raises(sa.exc.DBAPIError):
                connection.execute(sa.text(
                    "DELETE FROM enterprise_contract_term_fundings WHERE version_id=:v"), {"v": version_id})
            connection.rollback()
    finally:
        engine.dispose()


@PG
def test_postgres_b1_concurrent_cancellation_and_funding_never_both_succeed():
    engine = _migrated_engine()
    try:
        with migrated_session(engine) as session:
            ns, who = seed_org(session), staff(session)
            session.commit()
            contract, version = record(session, ns, who, db_now(session) + timedelta(days=30))
            session.commit()
            version = approve(session, ns, who, contract, version)
            session.commit()
            line_id = stripe_payment(session, ns, version)
            session.commit()
            contract_id, version_id = contract.id, version.id
        barrier = threading.Barrier(2)

        def run(kind):
            with migrated_session(engine) as session:
                barrier.wait()
                try:
                    if kind == "fund":
                        record_contract_funding(
                            session, command_id="race-fund", billing_account_id=ns.account, contract_id=contract_id,
                            version_id=version_id, financial_line_id=line_id, actor_user_id=who.user,
                            delivery_obligations=DELIVERIES,
                        )
                    else:
                        cancel_contract_version(
                            session, command_id="race-cancel", billing_account_id=ns.account,
                            contract_id=contract_id, version_id=version_id, reason="race", evidence_reference="e",
                            actor_user_id=who.user, delivery_obligations=DELIVERIES,
                        )
                    session.commit()
                    return f"{kind}:ok"
                except (ContractError, sa.exc.DBAPIError):
                    session.rollback()
                    return f"{kind}:refused"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = sorted(pool.map(run, ("fund", "cancel")))
        assert outcomes in (["cancel:ok", "fund:refused"], ["cancel:refused", "fund:ok"]), outcomes
        with migrated_session(engine) as session:
            state = session.get(EnterpriseContractVersion, version_id).state
            funded = session.query(EnterpriseContractTermFunding).filter_by(version_id=version_id).count()
            assert (state, funded) in (("cancelled", 0), ("approved", 1))
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# C1: a renewal paid within grace but no longer activatable never strands the contract
# ---------------------------------------------------------------------------

def _grace_with_paid_renewal(session, monkeypatch, ns, who, *, paid_day=2):
    contract, term, _activation = active_contract(session, ns, who)
    renewal, _ = _auto_renew(session, ns, who, contract, term)
    end = _utc(term.term_ends_at)
    at_time(monkeypatch, end + timedelta(hours=1))
    _complete(session, ns, who, contract, term)
    line_id = stripe_payment(session, ns, renewal, at=end + timedelta(days=paid_day))  # verified within grace
    return contract, term, renewal, end, line_id


@pytest.mark.parametrize("bound_late", [False, True])
def test_c1_renewal_paid_in_grace_but_processed_after_its_first_month_can_lapse(db, monkeypatch, bound_late):
    session = db.session
    ns, who = seed_org(session), staff(session)
    contract, term, renewal, end, line_id = _grace_with_paid_renewal(session, monkeypatch, ns, who)
    if not bound_late:
        at_time(monkeypatch, end + timedelta(days=3))
        fund(session, ns, who, contract, renewal, line_id)
    day35 = end + timedelta(days=35)
    assert day35 >= add_calendar_months(end, 1)  # past the renewal's first monthly period
    at_time(monkeypatch, day35)
    if bound_late:
        fund(session, ns, who, contract, renewal, line_id)
    before = _funding_snapshot(session, renewal.id)
    lots_before = {lot.id for lot in lots_of(session, ns.account)}
    refused(session, ContractPolicyRequiredError, "catch-up", activate, session, ns, who, contract, renewal)
    ended, state = _lapse(session, ns, who, contract)
    assert state == "inserted"
    session.refresh(contract)
    assert contract.state == "ended"
    assert _utc(contract.paid_access_ended_at) == end  # the original paid end, not the lapse time
    assert _utc(contract.retention_review_until) == end + timedelta(days=180)
    version = session.get(EnterpriseContractVersion, renewal.id)
    assert version.state == "approved"
    assert _review(session, ns, who)[renewal.id]["reason"] == "catch_up_policy_required"
    assert _funding_snapshot(session, renewal.id) == before
    # Nothing is refunded, allocated, or activated automatically.
    assert {lot.id for lot in lots_of(session, ns.account)} == lots_before
    assert session.get(EntitlementInstance, renewal.entitlement_instance_id).state == "proposed"
    assert session.query(EnterpriseContractActivation).filter_by(version_id=renewal.id).count() == 0
    assert contract_access_state(session, billing_account_id=ns.account, at=day35)["state"] == "read_only_retention"
    # The ended contract cannot be reopened by this renewal later either.
    refused(session, ContractPolicyRequiredError, "catch-up", activate, session, ns, who, contract, renewal)
    # Repeated lapse commands converge on the same result.
    again, replay = _lapse(session, ns, who, contract, "lapse-again")
    assert (replay, again.id) == ("duplicate", ended.id)


def test_c1_activatable_paid_renewal_still_holds_the_contract_in_grace(db, monkeypatch):
    session = db.session
    ns, who = seed_org(session), staff(session)
    contract, term, renewal, end, line_id = _grace_with_paid_renewal(session, monkeypatch, ns, who)
    at_time(monkeypatch, end + timedelta(days=20))  # after grace, still within the first month
    fund(session, ns, who, contract, renewal, line_id)
    refused(session, ContractError, "awaits activation", _lapse, session, ns, who, contract)
    session.refresh(contract)
    assert contract.state == "renewal_grace"
    _activation, state = activate(session, ns, who, contract, renewal)
    assert state == "inserted"
    session.refresh(contract)
    assert contract.state == "active"


def test_c1_other_organizations_and_unauthorized_actors_cannot_lapse_the_contract(db, monkeypatch):
    session = db.session
    ns, who, other = seed_org(session), staff(session), seed_org(session)
    contract, _term, _renewal, end, _line = _grace_with_paid_renewal(session, monkeypatch, ns, who)
    at_time(monkeypatch, end + timedelta(days=35))
    with pytest.raises(ContractError, match="not available for this billing account"):
        end_contract_after_grace(session, command_id="x-org", billing_account_id=other.account,
                                 contract_id=contract.id, actor_user_id=who.user, delivery_obligations=DELIVERIES)
    for actor in (Ns(user=ns.owner), staff(session, permission="billing.comp.grant")):
        refused(session, ContractPermissionError, "explicit Enterprise contract permission",
                _lapse, session, ns, actor, contract, f"unauth-{uuid.uuid4().hex[:6]}")
    session.refresh(contract)
    assert contract.state == "renewal_grace"


@pytest.mark.parametrize("day,expected", [(20, ("active", "active")), (35, ("ended", "approved"))])
def test_c1_concurrent_lapse_and_activation_reach_one_consistent_state(db, monkeypatch, day, expected):
    session = db.session
    ns, who = seed_org(session), staff(session)
    contract, _term, renewal, end, line_id = _grace_with_paid_renewal(session, monkeypatch, ns, who)
    at_time(monkeypatch, end + timedelta(days=3))
    fund(session, ns, who, contract, renewal, line_id)
    session.commit()
    contract_id, renewal_id = contract.id, renewal.id
    at_time(monkeypatch, end + timedelta(days=day))
    engine = db.engine
    barrier = threading.Barrier(2)

    def run(kind):
        with Session(engine, expire_on_commit=False) as worker:
            barrier.wait()
            try:
                if kind == "lapse":
                    end_contract_after_grace(worker, command_id=f"race-{kind}", billing_account_id=ns.account,
                                             contract_id=contract_id, actor_user_id=who.user,
                                             delivery_obligations=DELIVERIES)
                else:
                    activate_contract_version(worker, command_id=f"race-{kind}", billing_account_id=ns.account,
                                              contract_id=contract_id, version_id=renewal_id,
                                              actor_user_id=who.user, delivery_obligations=DELIVERIES)
                worker.commit()
                return f"{kind}:ok"
            except (ContractError, sa.exc.DBAPIError):
                worker.rollback()
                return f"{kind}:refused"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(run, ("activate", "lapse")))
    winner = "activate:ok" if day == 20 else "lapse:ok"
    assert winner in outcomes and outcomes.count(winner) == 1, outcomes
    session.expire_all()
    assert (session.get(EnterpriseContract, contract_id).state,
            session.get(EnterpriseContractVersion, renewal_id).state) == expected
    activations = session.query(EnterpriseContractActivation).filter_by(version_id=renewal_id).count()
    assert activations == (1 if day == 20 else 0)
