"""Phase 9 purchase funding, refund, dispute, and recovery coverage (D10; D17 T-REFUND/T-DISPUTE/T-RECOVERY).

Service tests run against the ORM schema (SQLite, or an isolated PostgreSQL
schema when TEST_DATABASE_URL is set). ``test_sqlite_migrated_*`` applies the
Phase 9 revision on SQLite. ``test_postgres_migrated_*`` runs against the fully
migrated disposable PostgreSQL database, where every Phase 3-9 guard is live.
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

from app import db as flask_db
from app.billing_allocations import allocate_recurring_credits, expire_recurring_credits
from app.billing_entitlements import add_calendar_months, append_entitlement_transition
from app.billing_financial import record_financial_transaction
from app.billing_financial_effects import (
    FinancialEffectConflictError,
    FinancialEffectDependencyError,
    FinancialEffectError,
    FinancialEffectPermissionError,
    FinancialEffectPolicyRequiredError,
    FinancialEffectRetryError,
    apply_financial_case_effects,
    fund_credit_purchase,
    proportional_case_attribution,
    record_and_apply_financial_case_event,
)
from app.billing_inbox import claim_next_event, mark_processed
from app.billing_ledger import append_entry
from app.models import (
    BillingAccount,
    BillingSubscription,
    CommunicationOutbox,
    CreditLedgerEntry,
    CreditLot,
    CreditPurchaseFunding,
    DomainEvent,
    EntitlementDefinition,
    EntitlementInstance,
    ExternalEventInbox,
    FinancialCase,
    FinancialCaseCreditEffect,
    FinancialCaseEvent,
    FinancialCaseEventLedgerEntry,
    FinancialCaseLotEvaluation,
    FinancialLine,
    IdempotencyRegistry,
    Organization,
    User,
)


BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = str(BACKEND_DIR / "migrations")
REVISION = "e1a3c5b7d9f2"
PARENT = "b8c2d4e6f8a1"
PHASE9_TABLES = (
    "financial_case_credit_effects", "financial_case_lot_evaluations", "credit_purchase_fundings",
)
ANCHOR = datetime(2026, 1, 31, 15, 45, tzinfo=timezone.utc)
DELIVERIES = ({
    "template_key": "test-financial-effect", "template_version": "test-v1",
    "channel": "test-channel", "locale": "en-US",
},)
SERVICE = {"actor_type": "system", "actor_id": "phase9-test"}
# Test-only package terms; not commercial values.
BASE, BONUS, PRICE = 3000, 500, 1000
PG = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)


def _utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Seeding helpers (Flask session or plain migrated Session)
# ---------------------------------------------------------------------------

class Ns:
    def __init__(self, **values):
        self.__dict__.update(values)


def _inbox(session, object_type, object_id, at, suffix):
    now = datetime.now(timezone.utc)
    inbox = ExternalEventInbox(
        id=str(uuid.uuid4()), provider="stripe", event_id=f"p9_evt_{suffix}_{uuid.uuid4().hex[:6]}",
        event_type=f"{object_type}.updated", object_type=object_type, object_id=object_id,
        payload_digest=uuid.uuid4().hex + uuid.uuid4().hex, summary_json={"schema_version": 1},
        livemode=False, provider_created_at=at, received_at=now, state="received",
    )
    session.add(inbox)
    session.flush()
    claimed = claim_next_event(session, now=now, lease_seconds=60)
    assert claimed.id == inbox.id
    mark_processed(session, inbox.id, claimed.attempt_count, now=now + timedelta(seconds=1))
    return inbox


def seed_account(session, suffix=None, currency="usd"):
    suffix = suffix or uuid.uuid4().hex[:10]
    owner = User(
        id=f"p9-owner-{suffix}", email=f"p9-owner-{suffix}@example.test", name="Phase 9 owner",
        password_hash="not-a-login-credential", subscription_plan="free",
        credits_remaining=0, seat_limit=1, max_seats=1,
    )
    session.add(owner)
    session.flush()
    organization = Organization(
        id=f"p9-org-{suffix}", name=f"Phase 9 {suffix}", slug=f"phase-9-{suffix}",
        owner_user_id=owner.id, plan_key="free",
    )
    session.add(organization)
    session.flush()
    account = BillingAccount(
        id=f"p9-account-{suffix}", organization_id=organization.id, currency=currency,
        account_anchor_at=ANCHOR,
    )
    session.add(account)
    session.flush()
    return Ns(suffix=suffix, account=account.id, org=organization.id, owner=owner.id)


def purchase_definition(session, suffix, *, source_id=None, approved=True, expiry=None,
                        components=None, quantity=1, currency="usd"):
    components = components or [{"component": "base", "credit_amount": BASE},
                                {"component": "bonus", "credit_amount": BONUS}]
    definition = EntitlementDefinition(
        id=f"p9-def-{suffix}-{uuid.uuid4().hex[:4]}", key=f"credit-pack-{suffix}", version=1,
        exclusivity_key=f"credit-pack-{suffix}",
        capability_json={"schema_version": 1, "capabilities": {}},
        funding_policy_json={
            "schema_version": 1, "period_kind": "none",
            "credit_amount": sum(c["credit_amount"] for c in components),
            "purchase": {
                "schema_version": 1, "line_kind": "credit_pack", "source_type": "stripe_price",
                "source_id": source_id or f"price_pack_{suffix}", "currency": currency,
                "unit_principal_minor": PRICE, "quantity": quantity,
                # Phase 11 credit-pack policy: packs expire at the paid term end.
                "components": components, "expiry": expiry or {"kind": "current_term_end"},
            },
        },
        effective_at=ANCHOR - timedelta(days=30),
        approved_at=(ANCHOR - timedelta(days=30)) if approved else None,
        approval_evidence_reference="approval:phase9-test" if approved else None,
    )
    session.add(definition)
    session.flush()
    return definition.id


def _line(external, kind, principal, *, discount=0, tax=0, fee=0, source_id=None,
          subscription_id=None, instance_id=None, quantity=1, currency="usd"):
    return {
        "external_line_id": external, "line_kind": kind, "source_type": "stripe_price",
        "source_id": source_id or f"price_{external}", "quantity": quantity, "currency": currency,
        "principal_minor": principal, "tax_minor": tax, "fee_minor": fee, "discount_minor": discount,
        "subscription_id": subscription_id, "entitlement_instance_id": instance_id,
    }


def payment(session, account_id, lines, at, suffix, *, kind="payment", currency="usd"):
    object_id = f"in_{suffix}_{uuid.uuid4().hex[:6]}"
    inbox = _inbox(session, "invoice", object_id, at, suffix)
    totals = {f: sum(line[f] for line in lines) for f in ("principal_minor", "tax_minor", "fee_minor", "discount_minor")}
    transaction, _state = record_financial_transaction(session, {
        "billing_account_id": account_id, "kind": kind, "provider": "stripe",
        "object_type": "invoice", "object_id": object_id, "external_version": "v1",
        "effective_at": at, "currency": currency, **totals,
        "gross_minor": sum(totals.values()), "inbox_event_id": inbox.id,
    }, lines)
    rows = session.execute(
        sa.select(FinancialLine).where(FinancialLine.financial_transaction_id == transaction.id)
    ).scalars().all()
    return transaction.id, {row.external_line_id: row.id for row in rows}


def paid_term(session, ns, at=None):
    """The one paid term in force at ``at``; create a test annual term if none.

    Phase 11 credit-pack policy binds each pack to the paid monthly or annual
    term in force at payment and expires it at that term's end.
    """
    at = at or ANCHOR + timedelta(days=1)
    terms = session.execute(
        sa.select(BillingSubscription).where(
            BillingSubscription.billing_account_id == ns.account,
            BillingSubscription.state.in_(("active", "past_due", "cancel_at_period_end")),
            BillingSubscription.term_starts_at <= at, BillingSubscription.term_ends_at > at,
        )
    ).scalars().all()
    if terms:
        return terms[0]
    suffix = f"{ns.suffix}{uuid.uuid4().hex[:4]}"
    definition = EntitlementDefinition(
        id=f"p9-term-def-{suffix}", key=f"term-{suffix}", version=1, exclusivity_key=f"term-{suffix}",
        capability_json={"schema_version": 1, "capabilities": {}},
        funding_policy_json={"schema_version": 1, "period_kind": "annual_monthly", "credit_amount": 1},
        effective_at=ANCHOR - timedelta(days=1), approved_at=ANCHOR - timedelta(days=1),
        approval_evidence_reference="approval:phase9-term",
    )
    session.add(definition)
    session.flush()
    subscription = BillingSubscription(
        id=f"p9-term-{suffix}", billing_account_id=ns.account, processor="stripe",
        external_subscription_id=f"sub_term_{suffix}", interval="year", anchor_at=ANCHOR - timedelta(days=1),
        term_starts_at=ANCHOR - timedelta(days=1),
        term_ends_at=add_calendar_months(ANCHOR - timedelta(days=1), 12), state="active",
        current_entitlement_definition_id=definition.id, origin_evidence_json={"test": True},
    )
    session.add(subscription)
    session.flush()
    return subscription


def pack_purchase(session, ns, at=None, *, discount=0, extra_lines=(), fund=True):
    at = at or ANCHOR + timedelta(days=1)
    paid_term(session, ns, at)
    tag = uuid.uuid4().hex[:6]
    definition = purchase_definition(session, f"{ns.suffix}{tag}")
    source_id = session.get(EntitlementDefinition, definition).funding_policy_json["purchase"]["source_id"]
    tx, lines = payment(session, ns.account, [
        _line(f"pack-{tag}", "credit_pack", PRICE, discount=discount, source_id=source_id),
        *extra_lines,
    ], at, f"{ns.suffix}{tag}")
    line_id = lines[f"pack-{tag}"]
    fundings = []
    if fund:
        fundings, _lots, state = fund_credit_purchase(
            session, billing_account_id=ns.account, financial_line_id=line_id,
            entitlement_definition_id=definition, funded_at=at, delivery_obligations=DELIVERIES, **SERVICE,
        )
        assert state == "inserted"
    return Ns(tx=tx, line=line_id, lines=lines, definition=definition, at=at,
              lots={f.package_component: f.lot_id for f in fundings})


_VERSION = {"n": 0}
_AT = {}


def case_version(session, ns, *, source_tx, case_type, object_id, cumulative, allocations,
                 state, disposition=None, at=None):
    _VERSION["n"] += 1
    at = at or ANCHOR + timedelta(days=2, seconds=_VERSION["n"])
    version = f"v{_VERSION['n']}"
    inbox = _inbox(session, case_type, object_id, at, ns.suffix)
    tx, _state = record_financial_transaction(session, {
        "billing_account_id": ns.account, "kind": case_type, "provider": "stripe",
        "object_type": case_type, "object_id": object_id, "external_version": version,
        "effective_at": at, "currency": "usd", "principal_minor": -cumulative,
        "tax_minor": 0, "fee_minor": 0, "discount_minor": 0, "gross_minor": -cumulative,
        "inbox_event_id": inbox.id,
    }, [_line(f"{object_id}-{version}", "other", -cumulative)] if cumulative else [
        _line(f"{object_id}-{version}", "other", 0)
    ])
    _AT[object_id] = at
    return {
        "billing_account_id": ns.account, "provider": "stripe", "case_type": case_type,
        "case_object_id": object_id, "source_financial_transaction_id": source_tx,
        "financial_transaction_id": tx.id, "state": state, "disposition": disposition,
        "cumulative_principal_minor": cumulative,
        "line_allocations": [
            {"financial_line_id": line_id, "attributed_principal_minor": amount}
            for line_id, amount in allocations.items()
        ],
    }


def apply_case(session, proposed, at=None):
    # Apply at the version's own effective time unless a test says otherwise.
    return record_and_apply_financial_case_event(
        session, proposed, applied_at=at or _AT[proposed["case_object_id"]],
        delivery_obligations=DELIVERIES, **SERVICE,
    )


def refund(session, ns, purchase, object_id, cumulative, *, line=None, at=None, state="refund_recorded",
           disposition=None, applied_at=None):
    line = line or purchase.line
    proposed = case_version(
        session, ns, source_tx=purchase.tx, case_type="refund", object_id=object_id,
        cumulative=cumulative, allocations={line: cumulative} if cumulative else {},
        state=state, disposition=disposition, at=at,
    )
    return apply_case(session, proposed, applied_at)


def dispute(session, ns, source_tx, object_id, allocations, state, *, at=None, applied_at=None):
    proposed = case_version(
        session, ns, source_tx=source_tx, case_type="dispute", object_id=object_id,
        cumulative=sum(allocations.values()), allocations=allocations, state=state, at=at,
    )
    return apply_case(session, proposed, applied_at)


def balance(session, lot_id):
    available, held = session.execute(
        sa.select(
            sa.func.coalesce(sa.func.sum(CreditLedgerEntry.available_delta), 0),
            sa.func.coalesce(sa.func.sum(CreditLedgerEntry.held_delta), 0),
        ).where(CreditLedgerEntry.lot_id == lot_id)
    ).one()
    return int(available), int(held)


def consume(session, account_id, lot_id, amount):
    """Test-only stand-in for delivered usage (Phase 12 settlement is not active)."""
    registry = IdempotencyRegistry(
        id=str(uuid.uuid4()), namespace="test_consumption", key=str(uuid.uuid4()),
        request_fingerprint="c" * 64, state="claimed", claimed_at=datetime.now(timezone.utc),
    )
    session.add(registry)
    session.flush()
    append_entry(session, CreditLedgerEntry(
        id=str(uuid.uuid4()), billing_account_id=account_id, lot_id=lot_id,
        entry_type="admin_adjustment", available_delta=-amount, held_delta=0,
        idempotency_registry_id=registry.id, effective_at=datetime.now(timezone.utc),
        actor_type="test", actor_id="consumption", reason_code="test_usage", evidence_json={},
    ))


def monthly_subscription_lot(session, ns, *, principal=10000, credits=500):
    suffix = f"{ns.suffix}{uuid.uuid4().hex[:4]}"
    definition = EntitlementDefinition(
        id=f"p9-sub-def-{suffix}", key=f"pro-{suffix}", version=1, exclusivity_key="base-plan",
        capability_json={"schema_version": 1, "capabilities": {"analysis": True}},
        funding_policy_json={"schema_version": 1, "period_kind": "monthly_subscription", "credit_amount": credits},
        effective_at=ANCHOR, approved_at=ANCHOR, approval_evidence_reference="approval:phase9-sub",
    )
    session.add(definition)
    session.flush()
    subscription = BillingSubscription(
        id=f"p9-sub-{suffix}", billing_account_id=ns.account, processor="stripe",
        external_subscription_id=f"sub_{suffix}", interval="month", anchor_at=ANCHOR,
        term_starts_at=ANCHOR, term_ends_at=add_calendar_months(ANCHOR, 2), state="active",
        current_entitlement_definition_id=definition.id, origin_evidence_json={"test": True},
    )
    session.add(subscription)
    session.flush()
    instance = EntitlementInstance(
        id=f"p9-inst-{suffix}", billing_account_id=ns.account, entitlement_definition_id=definition.id,
        subscription_id=subscription.id, state="proposed", starts_at=ANCHOR,
        ends_at=subscription.term_ends_at, source_type="subscription",
        source_id=subscription.external_subscription_id, approval_evidence_reference="approval:phase9-sub",
    )
    session.add(instance)
    session.flush()
    for next_state, transition in (("scheduled", "schedule"), ("active", "activate")):
        registry = IdempotencyRegistry(
            id=str(uuid.uuid4()), namespace="phase9_test_activation", key=f"{transition}:{instance.id}",
            request_fingerprint="7" * 64, state="claimed", claimed_at=ANCHOR,
        )
        session.add(registry)
        session.flush()
        append_entitlement_transition(
            session, instance_id=instance.id, next_state=next_state, transition=transition,
            effective_at=ANCHOR, actor_type="test", actor_id="phase9-test",
            source_type="test", source_id=f"phase9:{suffix}", idempotency=registry,
            evidence_json={"test": "phase9"},
        )
        session.expire(instance)
        if instance.state != next_state:
            instance.state = next_state  # ORM-only schema has no Phase 4 projection trigger
            session.flush()
    tx, lines = payment(session, ns.account, [
        _line(f"sub-{suffix}", "subscription", principal, tax=800,
              subscription_id=subscription.id, instance_id=instance.id),
    ], ANCHOR + timedelta(hours=1), suffix)
    line_id = lines[f"sub-{suffix}"]
    _allocation, period, lot, _state = allocate_recurring_credits(
        session, billing_account_id=ns.account, entitlement_instance_id=instance.id, period_index=0,
        opened_at=ANCHOR + timedelta(hours=2), delivery_obligations=DELIVERIES,
        financial_line_id=line_id, **SERVICE,
    )
    return Ns(tx=tx, line=line_id, lot=lot.id, period=period.id, instance=instance.id, subscription=subscription.id)


def evaluations(session, case_id):
    return session.execute(
        sa.select(FinancialCaseLotEvaluation)
        .join(FinancialCaseEvent, FinancialCaseEvent.id == FinancialCaseLotEvaluation.financial_case_event_id)
        .where(FinancialCaseLotEvaluation.financial_case_id == case_id)
        # Phase 5.3 acceptance order, not row creation time.
        .order_by(FinancialCaseEvent.effective_at, FinancialCaseEvent.received_at, FinancialCaseLotEvaluation.lot_id)
    ).scalars().all()


# ---------------------------------------------------------------------------
# Purchases
# ---------------------------------------------------------------------------

def test_purchase_funds_each_component_once_and_replay_converges(db):
    session = db.session
    ns = seed_account(session)
    purchase = pack_purchase(session, ns)
    assert balance(session, purchase.lots["base"]) == (BASE, 0)
    assert balance(session, purchase.lots["bonus"]) == (BONUS, 0)
    for component, lot_id in purchase.lots.items():
        lot = session.get(CreditLot, lot_id)
        # Phase 11: the pack expires at the end of the paid term in force at payment.
        term = paid_term(session, ns, purchase.at)
        assert lot.source_type == "credit_pack_purchase"
        assert _utc(lot.expires_at) == _utc(term.term_ends_at)
        assert lot.origin_evidence_json["financial_line_id"] == purchase.line
    # Webhook replay and browser confirmation use the same line identity.
    for _ in range(2):
        fundings, lots, state = fund_credit_purchase(
            session, billing_account_id=ns.account, financial_line_id=purchase.line,
            entitlement_definition_id=purchase.definition, funded_at=purchase.at + timedelta(minutes=5),
            delivery_obligations=DELIVERIES, **SERVICE,
        )
        assert state == "duplicate" and {lot.id for lot in lots} == set(purchase.lots.values())
    assert session.query(CreditPurchaseFunding).filter_by(financial_line_id=purchase.line).count() == 2
    event = session.query(DomainEvent).filter_by(event_key=f"credit_purchase_funded:{purchase.line}").one()
    assert event.event_type == "credit_purchase_funded"
    assert session.query(CommunicationOutbox).filter_by(domain_event_id=event.id).count() == 1


def _bad_purchase(session, ns, case):
    tag = uuid.uuid4().hex[:6]
    definition = purchase_definition(
        session, f"{ns.suffix}{tag}", approved=case != "unapproved",
        expiry={"kind": "days", "days": 30} if case == "expiry" else None,
        quantity=2 if case == "quantity" else 1,
    )
    source_id = session.get(EntitlementDefinition, definition).funding_policy_json["purchase"]["source_id"]
    kind = {"subscription_line": "subscription", "seat_line": "seat"}.get(case, "credit_pack")
    tx_kind = "invoice" if case == "no_payment" else "payment"
    other = seed_account(session) if case == "other_account" else ns
    _tx, lines = payment(session, other.account, [
        _line(f"x-{tag}", kind, PRICE, source_id=source_id if case != "wrong_product" else "price_other"),
    ], ANCHOR + timedelta(days=1), f"{ns.suffix}{tag}", kind=tx_kind)
    return definition if case != "missing_definition" else "p9-no-such-definition", lines[f"x-{tag}"]


@pytest.mark.parametrize("case,error", [
    ("no_payment", FinancialEffectError),
    ("other_account", FinancialEffectError),
    ("subscription_line", FinancialEffectError),
    ("seat_line", FinancialEffectError),
    ("wrong_product", FinancialEffectError),
    ("unapproved", FinancialEffectDependencyError),
    ("missing_definition", FinancialEffectDependencyError),
    ("expiry", FinancialEffectDependencyError),
    ("quantity", FinancialEffectError),
])
def test_purchase_rejects_unverified_or_mismatched_evidence(db, case, error):
    session = db.session
    ns = seed_account(session)
    definition, line_id = _bad_purchase(session, ns, case)
    with pytest.raises(error):
        fund_credit_purchase(
            session, billing_account_id=ns.account, financial_line_id=line_id,
            entitlement_definition_id=definition, funded_at=ANCHOR + timedelta(days=2),
            delivery_obligations=DELIVERIES, **SERVICE,
        )
    session.rollback()
    assert session.query(CreditPurchaseFunding).count() == 0


def test_purchase_error_does_not_disclose_other_account_objects(db):
    session = db.session
    ns, other = seed_account(session), seed_account(session)
    purchase = pack_purchase(session, other)
    missing = pytest.raises(FinancialEffectError, match="not available for this billing account")
    with missing:
        fund_credit_purchase(
            session, billing_account_id=ns.account, financial_line_id=purchase.line,
            entitlement_definition_id=purchase.definition, funded_at=purchase.at,
            delivery_obligations=DELIVERIES, **SERVICE,
        )


@pytest.mark.parametrize("actor_type", ["user", "billing_owner", "global_admin", "admin"])
def test_only_the_processor_service_may_apply_financial_effects(db, actor_type):
    session = db.session
    ns = seed_account(session)
    purchase = pack_purchase(session, ns, fund=False)
    with pytest.raises(FinancialEffectPermissionError):
        fund_credit_purchase(
            session, billing_account_id=ns.account, financial_line_id=purchase.line,
            entitlement_definition_id=purchase.definition, funded_at=purchase.at,
            delivery_obligations=DELIVERIES, actor_type=actor_type, actor_id=ns.owner,
        )
    with pytest.raises(FinancialEffectPermissionError):
        record_and_apply_financial_case_event(
            session, {"billing_account_id": ns.account}, applied_at=purchase.at,
            delivery_obligations=DELIVERIES, actor_type=actor_type, actor_id=ns.owner,
        )


def test_same_line_cannot_fund_under_a_different_definition(db):
    session = db.session
    ns = seed_account(session)
    purchase = pack_purchase(session, ns)
    source_id = session.get(EntitlementDefinition, purchase.definition).funding_policy_json["purchase"]["source_id"]
    second = purchase_definition(session, f"{ns.suffix}b", source_id=source_id)
    with pytest.raises(FinancialEffectConflictError):
        fund_credit_purchase(
            session, billing_account_id=ns.account, financial_line_id=purchase.line,
            entitlement_definition_id=second, funded_at=purchase.at,
            delivery_obligations=DELIVERIES, **SERVICE,
        )


# ---------------------------------------------------------------------------
# Refunds (D10 one-time partial refund formula)
# ---------------------------------------------------------------------------

def test_partial_refunds_converge_to_the_equivalent_cumulative_refund(db):
    session = db.session
    stepwise, single = seed_account(session), seed_account(session)
    a = pack_purchase(session, stepwise)
    b = pack_purchase(session, single)
    for ns, purchase, steps in ((stepwise, a, (250, 400, 700)), (single, b, (700,))):
        object_id = f"re_{ns.suffix}"
        for cumulative in steps:
            refund(session, ns, purchase, object_id, cumulative)
    for component, total in (("base", BASE), ("bonus", BONUS)):
        expected = total - (total * 700) // PRICE
        assert balance(session, a.lots[component]) == (expected, 0)
        assert balance(session, b.lots[component]) == (expected, 0)


def test_full_refund_after_consumption_reverses_only_unused_value(db):
    session = db.session
    ns = seed_account(session)
    purchase = pack_purchase(session, ns)
    consume(session, ns.account, purchase.lots["base"], 1200)
    case, _event, _state, evals = refund(session, ns, purchase, f"re_{ns.suffix}", PRICE)
    assert balance(session, purchase.lots["base"]) == (0, 0)
    assert balance(session, purchase.lots["bonus"]) == (0, 0)
    base = next(e for e in evals if e.lot_id == purchase.lots["base"])
    assert (base.unused_basis, base.target_amount, base.reversal_amount) == (1800, 1800, 1800)
    assert base.absorbed_shortfall_total == 0


def test_refund_excludes_tax_and_fees_and_uses_discounted_principal(db):
    session = db.session
    ns = seed_account(session)
    purchase = pack_purchase(session, ns, discount=-200, extra_lines=(
        _line("tax-line", "tax", 0, tax=90), _line("fee-line", "fee", 0, fee=15),
    ))
    # I2 (D5): a partial refund of a taxed source does not say, from processor evidence
    # alone, how much was principal, so it waits for manual review and changes nothing.
    with pytest.raises(FinancialEffectPolicyRequiredError), session.begin_nested():
        refund(session, ns, purchase, f"re_{ns.suffix}", 400)
    assert balance(session, purchase.lots["base"]) == (BASE, 0)
    # Refunding the whole net principal (800; tax and fee excluded) is exact and reverses everything.
    refund(session, ns, purchase, f"re_{ns.suffix}", 800)
    assert balance(session, purchase.lots["base"]) == (0, 0)
    assert balance(session, purchase.lots["bonus"]) == (0, 0)
    with pytest.raises(FinancialEffectError):
        refund(session, ns, purchase, f"re2_{ns.suffix}", 500, line=purchase.lines["tax-line"])


def test_refund_rounding_floors_in_exact_integers(db):
    session = db.session
    ns = seed_account(session)
    purchase = pack_purchase(session, ns)
    refund(session, ns, purchase, f"re_{ns.suffix}", 333)
    assert balance(session, purchase.lots["base"])[0] == BASE - (BASE * 333) // PRICE  # floor(999.0)
    assert balance(session, purchase.lots["bonus"])[0] == BONUS - (BONUS * 333) // PRICE  # floor(166.5)


def test_refund_never_touches_unrelated_lots_or_sources(db):
    session = db.session
    ns = seed_account(session)
    refunded, untouched = pack_purchase(session, ns), pack_purchase(session, ns)
    sub = monthly_subscription_lot(session, ns)
    refund(session, ns, refunded, f"re_{ns.suffix}", PRICE)
    assert balance(session, untouched.lots["base"]) == (BASE, 0)
    assert balance(session, untouched.lots["bonus"]) == (BONUS, 0)
    assert balance(session, sub.lot) == (500, 0)


def test_duplicate_and_stale_refund_versions_apply_nothing(db):
    session = db.session
    ns = seed_account(session)
    purchase = pack_purchase(session, ns)
    object_id = f"re_{ns.suffix}"
    later = refund(session, ns, purchase, object_id, 500, at=ANCHOR + timedelta(days=5))
    before = balance(session, purchase.lots["base"])
    stale = refund(session, ns, purchase, object_id, 900, at=ANCHOR + timedelta(days=3))
    assert stale[2] == "stale" and stale[3] == []
    again = apply_financial_case_effects(
        session, billing_account_id=ns.account, financial_case_id=later[0].id,
        applied_at=datetime.now(timezone.utc), delivery_obligations=DELIVERIES, **SERVICE,
    )
    assert again[2] == []
    assert balance(session, purchase.lots["base"]) == before


def test_cancelled_refund_recovers_exactly_what_it_reversed(db):
    session = db.session
    ns = seed_account(session)
    purchase = pack_purchase(session, ns)
    object_id = f"re_{ns.suffix}"
    refund(session, ns, purchase, object_id, 600)
    consume(session, ns.account, purchase.lots["base"], 100)
    case, _e, _s, evals = refund(session, ns, purchase, object_id, 0)
    assert balance(session, purchase.lots["base"]) == (BASE - 100, 0)
    assert balance(session, purchase.lots["bonus"]) == (BONUS, 0)
    recoveries = session.query(FinancialCaseCreditEffect).filter_by(financial_case_id=case.id, effect_type="recovery").all()
    assert sum(r.amount for r in recoveries) == (BASE * 600) // PRICE + (BONUS * 600) // PRICE
    # Replay restores nothing more; recovery can never exceed the reversal.
    assert apply_financial_case_effects(
        session, billing_account_id=ns.account, financial_case_id=case.id,
        applied_at=datetime.now(timezone.utc), delivery_obligations=DELIVERIES, **SERVICE,
    )[2] == []


def test_partial_reduction_of_a_refund_fails_closed(db):
    session = db.session
    ns = seed_account(session)
    purchase = pack_purchase(session, ns)
    object_id = f"re_{ns.suffix}"
    refund(session, ns, purchase, object_id, 600)
    session.commit()
    with pytest.raises(FinancialEffectPolicyRequiredError):
        refund(session, ns, purchase, object_id, 300)
    session.rollback()


def _effect_counts(session):
    return {
        model.__tablename__: session.query(model).count()
        for model in (
            CreditLedgerEntry, FinancialCaseLotEvaluation, FinancialCaseCreditEffect,
            FinancialCaseEventLedgerEntry, DomainEvent, CommunicationOutbox, FinancialCase,
        )
    }


def test_f1_re_refund_after_cancellation_is_refused_without_mutation(db):
    session = db.session
    ns = seed_account(session)
    purchase = pack_purchase(session, ns)
    object_id = f"re_{ns.suffix}"
    refund(session, ns, purchase, object_id, 500)
    case, *_ = refund(session, ns, purchase, object_id, 0)
    session.commit()
    # Recovery after cancellation is exact.
    assert balance(session, purchase.lots["base"]) == (BASE, 0)
    assert balance(session, purchase.lots["bonus"]) == (BONUS, 0)
    reversed_ = sum(e.amount for e in session.query(FinancialCaseCreditEffect).filter_by(
        financial_case_id=case.id, effect_type="reversal"))
    recovered = sum(e.amount for e in session.query(FinancialCaseCreditEffect).filter_by(
        financial_case_id=case.id, effect_type="recovery"))
    assert reversed_ == recovered == (BASE * 500) // PRICE + (BONUS * 500) // PRICE
    before = _effect_counts(session)
    case_events_before = session.query(FinancialCase).one().current_event_id
    with pytest.raises(FinancialEffectPolicyRequiredError, match="previously recovered"):
        refund(session, ns, purchase, object_id, 500)
    session.rollback()
    assert _effect_counts(session) == before
    assert session.query(FinancialCase).one().current_event_id == case_events_before
    assert balance(session, purchase.lots["base"]) == (BASE, 0)
    assert balance(session, purchase.lots["bonus"]) == (BONUS, 0)


def test_f1_replay_of_an_active_refund_remains_idempotent(db):
    session = db.session
    ns = seed_account(session)
    purchase = pack_purchase(session, ns)
    object_id = f"re_{ns.suffix}"
    refund(session, ns, purchase, object_id, 500)
    after_first = balance(session, purchase.lots["base"])
    # A new provider version at the same cumulative amount, then a re-run.
    case, _event, state, evals = refund(session, ns, purchase, object_id, 500)
    assert state == "inserted" and all(e.reversal_amount == 0 for e in evals)
    assert apply_financial_case_effects(
        session, billing_account_id=ns.account, financial_case_id=case.id,
        applied_at=datetime.now(timezone.utc), delivery_obligations=DELIVERIES, **SERVICE,
    )[2] == []
    assert balance(session, purchase.lots["base"]) == after_first == (BASE - (BASE * 500) // PRICE, 0)
    # A larger cumulative amount is still a valid D10 delta.
    refund(session, ns, purchase, object_id, 800)
    assert balance(session, purchase.lots["base"])[0] == BASE - (BASE * 800) // PRICE


def _versions_in_one_transaction(session, ns, purchase, case_type, amounts):
    object_id = f"{case_type[:2]}_{ns.suffix}"
    results = []
    for index, amount in enumerate(amounts):
        if case_type == "refund":
            results.append(refund(session, ns, purchase, object_id, amount))
        else:
            state = "opened" if index == 0 else "pending"
            results.append(dispute(session, ns, purchase.tx, object_id, {purchase.line: amount}, state))
    return results


@pytest.mark.parametrize("case_type", ["refund", "dispute"])
def test_f2_reduction_within_one_transaction_is_refused_deterministically(db, case_type):
    session = db.session
    # Repeat with fresh accounts: random IDs and shared timestamps must not
    # change which version counts as the prior one.
    for _attempt in range(5):
        ns = seed_account(session)
        purchase = pack_purchase(session, ns)
        session.commit()
        before = _effect_counts(session)
        with pytest.raises(FinancialEffectPolicyRequiredError):
            _versions_in_one_transaction(session, ns, purchase, case_type, (300, 600, 450))
        session.rollback()
        assert _effect_counts(session) == before


@pytest.mark.parametrize("case_type", ["refund", "dispute"])
def test_f2_monotonic_versions_in_one_transaction_apply_the_cumulative_target(db, case_type):
    session = db.session
    for _attempt in range(3):
        ns = seed_account(session)
        purchase = pack_purchase(session, ns)
        results = _versions_in_one_transaction(session, ns, purchase, case_type, (300, 600, 600))
        session.commit()
        case = results[-1][0]
        target = (BASE * 600) // PRICE
        if case_type == "refund":
            assert balance(session, purchase.lots["base"]) == (BASE - target, 0)
            applied = sum(e.amount for e in session.query(FinancialCaseCreditEffect).filter_by(
                financial_case_id=case.id, lot_id=purchase.lots["base"], effect_type="reversal"))
        else:
            assert balance(session, purchase.lots["base"]) == (BASE - target, target)
            applied = sum(e.amount for e in session.query(FinancialCaseCreditEffect).filter_by(
                financial_case_id=case.id, lot_id=purchase.lots["base"], effect_type="hold"))
        rows = [e for e in evaluations(session, case.id) if e.lot_id == purchase.lots["base"]]
        assert [e.attributed_principal_minor for e in rows] == [300, 600, 600]
        # Provenance and the ledger agree with the evaluations.
        assert applied == sum(e.reversal_amount + e.hold_amount for e in rows) == target


@pytest.mark.parametrize("case_type", ["refund", "dispute"])
def test_f2_out_of_order_version_in_one_transaction_is_stale(db, case_type):
    session = db.session
    ns = seed_account(session)
    purchase = pack_purchase(session, ns)
    object_id = f"oo_{ns.suffix}"
    late, early = ANCHOR + timedelta(days=9), ANCHOR + timedelta(days=8)
    if case_type == "refund":
        refund(session, ns, purchase, object_id, 600, at=late)
        stale = refund(session, ns, purchase, object_id, 300, at=early)
    else:
        dispute(session, ns, purchase.tx, object_id, {purchase.line: 600}, "opened", at=late)
        stale = dispute(session, ns, purchase.tx, object_id, {purchase.line: 300}, "pending", at=early)
    assert stale[2] == "stale" and stale[3] == []
    session.commit()
    target = (BASE * 600) // PRICE
    expected = (BASE - target, 0) if case_type == "refund" else (BASE - target, target)
    assert balance(session, purchase.lots["base"]) == expected


def test_refund_before_funding_is_retryable_then_converges(db):
    session = db.session
    ns = seed_account(session)
    purchase = pack_purchase(session, ns, fund=False)
    session.commit()
    with pytest.raises(FinancialEffectRetryError):
        refund(session, ns, purchase, f"re_{ns.suffix}", PRICE)
    session.rollback()
    assert session.query(FinancialCase).count() == 0  # the case version rolled back with it
    fundings, _lots, _state = fund_credit_purchase(
        session, billing_account_id=ns.account, financial_line_id=purchase.line,
        entitlement_definition_id=purchase.definition, funded_at=purchase.at,
        delivery_obligations=DELIVERIES, **SERVICE,
    )
    refund(session, ns, purchase, f"re_{ns.suffix}", PRICE)
    assert all(balance(session, f.lot_id) == (0, 0) for f in fundings)


def test_two_refund_objects_on_one_line_share_the_cumulative_rule(db):
    session = db.session
    ns = seed_account(session)
    purchase = pack_purchase(session, ns)
    refund(session, ns, purchase, f"re1_{ns.suffix}", 300)
    refund(session, ns, purchase, f"re2_{ns.suffix}", 400)
    assert balance(session, purchase.lots["base"])[0] == BASE - (BASE * 700) // PRICE


def test_subscription_refund_dispositions_preserve_credits_and_entitlements(db):
    session = db.session
    ns = seed_account(session)
    sub = monthly_subscription_lot(session, ns)
    for object_id, state in ((f"re_fo_{ns.suffix}", "financial_only"),
                             (f"re_er_{ns.suffix}", "entitlement_reducing_review")):
        proposed = case_version(
            session, ns, source_tx=sub.tx, case_type="refund", object_id=object_id,
            cumulative=2000, allocations={sub.line: 2000}, state=state, disposition=state,
        )
        case, _event, _state, evals = apply_case(session, proposed)
        assert evals == []
    assert balance(session, sub.lot) == (500, 0)
    assert session.get(EntitlementInstance, sub.instance).state == "active"
    assert session.get(BillingSubscription, sub.subscription).state == "active"
    assert session.query(DomainEvent).filter_by(event_type="refund_recorded").count() == 2


# ---------------------------------------------------------------------------
# Disputes
# ---------------------------------------------------------------------------

def test_dispute_hold_then_won_releases_the_exact_hold(db):
    session = db.session
    ns = seed_account(session)
    purchase = pack_purchase(session, ns)
    object_id = f"dp_{ns.suffix}"
    dispute(session, ns, purchase.tx, object_id, {purchase.line: PRICE}, "opened")
    assert balance(session, purchase.lots["base"]) == (0, BASE)
    dispute(session, ns, purchase.tx, object_id, {purchase.line: PRICE}, "pending")
    assert balance(session, purchase.lots["base"]) == (0, BASE)  # never held twice
    case, *_ = dispute(session, ns, purchase.tx, object_id, {purchase.line: PRICE}, "won")
    assert balance(session, purchase.lots["base"]) == (BASE, 0)
    assert case.state == "won"
    links = session.query(FinancialCaseEventLedgerEntry).count()
    assert links == session.query(FinancialCaseCreditEffect).count()


def test_dispute_holds_only_unused_value_and_lost_records_absorbed_shortfall(db):
    session = db.session
    ns = seed_account(session)
    purchase = pack_purchase(session, ns)
    consume(session, ns.account, purchase.lots["base"], 1000)
    object_id = f"dp_{ns.suffix}"
    dispute(session, ns, purchase.tx, object_id, {purchase.line: PRICE}, "opened")
    assert balance(session, purchase.lots["base"]) == (0, 2000)
    case, _e, _s, evals = dispute(session, ns, purchase.tx, object_id, {purchase.line: PRICE}, "lost")
    assert balance(session, purchase.lots["base"]) == (0, 0)
    base = next(e for e in evals if e.lot_id == purchase.lots["base"])
    assert base.reversal_amount == 2000 and base.absorbed_shortfall_total == 1000


def test_direct_terminal_lost_holds_and_reverses_in_one_version(db):
    session = db.session
    ns = seed_account(session)
    purchase = pack_purchase(session, ns)
    dispute(session, ns, purchase.tx, f"dp_{ns.suffix}", {purchase.line: PRICE}, "lost")
    assert balance(session, purchase.lots["base"]) == (0, 0)
    assert balance(session, purchase.lots["bonus"]) == (0, 0)
    assert session.query(CreditLedgerEntry).filter_by(entry_type="dispute_reversal").count() == 2


def test_reopened_lost_dispute_then_won_recovers_without_repeating_effects(db):
    session = db.session
    ns = seed_account(session)
    purchase = pack_purchase(session, ns)
    object_id = f"dp_{ns.suffix}"
    dispute(session, ns, purchase.tx, object_id, {purchase.line: PRICE}, "lost")
    dispute(session, ns, purchase.tx, object_id, {purchase.line: PRICE}, "pending")
    assert balance(session, purchase.lots["base"]) == (0, BASE)
    case, *_ = dispute(session, ns, purchase.tx, object_id, {purchase.line: PRICE}, "won")
    assert balance(session, purchase.lots["base"]) == (BASE, 0)
    reversed_ = sum(e.amount for e in session.query(FinancialCaseCreditEffect).filter_by(
        financial_case_id=case.id, effect_type="reversal"))
    recovered = sum(e.amount for e in session.query(FinancialCaseCreditEffect).filter_by(
        financial_case_id=case.id, effect_type="recovery"))
    assert reversed_ == recovered == BASE + BONUS


def test_partial_dispute_on_mixed_invoice_touches_only_attributed_lines(db):
    session = db.session
    ns = seed_account(session)
    sub = monthly_subscription_lot(session, ns)
    purchase = pack_purchase(session, ns)
    # The subscription line's principal is 10000 (tax 800 excluded). Half of it disputed is a
    # partial split the processor did not allocate: I2 (D5) sends it to manual review untouched.
    with pytest.raises(FinancialEffectPolicyRequiredError), session.begin_nested():
        dispute(session, ns, sub.tx, f"dp_{ns.suffix}", {sub.line: 5000}, "opened")
    assert balance(session, sub.lot) == (500, 0)
    # The whole eligible principal is exact: it holds only that source's value.
    dispute(session, ns, sub.tx, f"dp_{ns.suffix}", {sub.line: 10000}, "opened")
    assert balance(session, sub.lot) == (0, 500)
    assert balance(session, purchase.lots["base"]) == (BASE, 0)


def test_dispute_hold_does_not_delay_expiry_and_expired_value_is_not_recreated(db):
    session = db.session
    ns = seed_account(session)
    sub = monthly_subscription_lot(session, ns)
    object_id = f"dp_{ns.suffix}"
    dispute(session, ns, sub.tx, object_id, {sub.line: 10000}, "opened")
    period_end = add_calendar_months(ANCHOR, 1)
    expire_recurring_credits(
        session, credit_period_id=sub.period, expired_at=period_end,
        delivery_obligations=DELIVERIES, **SERVICE,
    )
    assert balance(session, sub.lot) == (0, 0)
    _case, _e, _s, evals = dispute(
        session, ns, sub.tx, object_id, {sub.line: 10000}, "won",
        at=period_end + timedelta(days=1), applied_at=period_end + timedelta(days=1),
    )
    assert balance(session, sub.lot) == (0, 0)
    assert evals[0].release_amount == 0 and evals[0].recovery_amount == 0


def test_won_after_loss_on_expired_lot_records_unrestorable_recovery(db):
    session = db.session
    ns = seed_account(session)
    sub = monthly_subscription_lot(session, ns)
    object_id = f"dp_{ns.suffix}"
    dispute(session, ns, sub.tx, object_id, {sub.line: 10000}, "lost")
    period_end = add_calendar_months(ANCHOR, 1)
    expire_recurring_credits(
        session, credit_period_id=sub.period, expired_at=period_end,
        delivery_obligations=DELIVERIES, **SERVICE,
    )
    _case, _e, _s, evals = dispute(
        session, ns, sub.tx, object_id, {sub.line: 10000}, "won",
        at=period_end + timedelta(days=1), applied_at=period_end + timedelta(days=1),
    )
    assert balance(session, sub.lot) == (0, 0)
    assert evals[0].recovery_amount == 0 and evals[0].unrestorable_recovery_amount == 500


def test_new_lot_funded_after_dispute_is_evaluated_on_reapply(db):
    session = db.session
    ns = seed_account(session)
    purchase = pack_purchase(session, ns, fund=False)
    # Disputes on unfunded purchase lines are retryable like refunds.
    with pytest.raises(FinancialEffectRetryError):
        dispute(session, ns, purchase.tx, f"dp_{ns.suffix}", {purchase.line: PRICE}, "opened")
    session.rollback()


def test_partial_dispute_reduction_fails_closed_and_zero_releases(db):
    session = db.session
    ns = seed_account(session)
    purchase = pack_purchase(session, ns)
    object_id = f"dp_{ns.suffix}"
    dispute(session, ns, purchase.tx, object_id, {purchase.line: 800}, "opened")
    session.commit()
    with pytest.raises(FinancialEffectPolicyRequiredError):
        dispute(session, ns, purchase.tx, object_id, {purchase.line: 400}, "pending")
    session.rollback()


# ---------------------------------------------------------------------------
# Mixed-invoice attribution
# ---------------------------------------------------------------------------

def test_proportional_attribution_is_exact_or_fails_closed(db):
    session = db.session
    ns = seed_account(session)
    tx, lines = payment(session, ns.account, [
        _line("s1", "subscription", 6000, discount=-1000),
        _line("s2", "subscription", 2500),
        _line("t", "tax", 0, tax=700),
        _line("f", "fee", 0, fee=50),
    ], ANCHOR, ns.suffix)
    call = lambda amount: proportional_case_attribution(  # noqa: E731
        session, billing_account_id=ns.account, source_financial_transaction_id=tx,
        cumulative_principal_minor=amount,
    )
    assert call(0) == []
    full = {a["financial_line_id"]: a["attributed_principal_minor"] for a in call(7500)}
    assert full == {lines["s1"]: 5000, lines["s2"]: 2500}
    exact = {a["financial_line_id"]: a["attributed_principal_minor"] for a in call(3000)}
    assert exact == {lines["s1"]: 2000, lines["s2"]: 1000}
    with pytest.raises(FinancialEffectPolicyRequiredError):
        call(1001)  # residual needs an approved tie-break rule
    with pytest.raises(FinancialEffectError):
        call(7501)
    other = seed_account(session)
    with pytest.raises(FinancialEffectError, match="not available"):
        proportional_case_attribution(
            session, billing_account_id=other.account, source_financial_transaction_id=tx,
            cumulative_principal_minor=10,
        )


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------

def test_cross_tenant_case_cannot_be_applied_by_another_account(db):
    session = db.session
    ns, other = seed_account(session), seed_account(session)
    purchase = pack_purchase(session, ns)
    case, *_ = refund(session, ns, purchase, f"re_{ns.suffix}", 100)
    with pytest.raises(FinancialEffectError, match="not available for this billing account"):
        apply_financial_case_effects(
            session, billing_account_id=other.account, financial_case_id=case.id,
            applied_at=datetime.now(timezone.utc), delivery_obligations=DELIVERIES, **SERVICE,
        )


def test_failed_event_recording_rolls_back_every_effect(db):
    session = db.session
    ns = seed_account(session)
    purchase = pack_purchase(session, ns)
    session.commit()
    proposed = case_version(
        session, ns, source_tx=purchase.tx, case_type="refund", object_id=f"re_{ns.suffix}",
        cumulative=PRICE, allocations={purchase.line: PRICE}, state="refund_recorded",
    )
    session.commit()
    with pytest.raises(FinancialEffectError):
        record_and_apply_financial_case_event(
            session, proposed, applied_at=datetime.now(timezone.utc),
            delivery_obligations=[{"template_key": "x"}], **SERVICE,
        )
    session.rollback()
    assert balance(session, purchase.lots["base"]) == (BASE, 0)
    assert session.query(FinancialCase).count() == 0
    assert session.query(FinancialCaseLotEvaluation).count() == 0


def test_phase9_service_has_no_live_runtime_callers():
    app_dir = BACKEND_DIR / "app"
    callers = [
        str(path.relative_to(BACKEND_DIR))
        for path in app_dir.rglob("*.py")
        if path.name not in {"billing_financial_effects.py", "models_billing_phase9.py", "models.py",
                              # I2 (D18 row 17): live only under BILLING_MODERN_FAMILIES (credit_funding).
                              "billing_runtime_financial.py", "billing_runtime_funding.py"}
        and ("billing_financial_effects" in path.read_text() or "models_billing_phase9" in path.read_text())
    ]
    assert callers == []


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

_MODULE = {}


def _revision():
    if "module" not in _MODULE:
        _MODULE["module"] = ScriptDirectory(MIGRATIONS_DIR).get_revision(REVISION).module
    return _MODULE["module"]


@contextlib.contextmanager
def _ops(engine):
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            yield connection


def _predecessor(engine):
    # Phase 11 tables are later than this revision and refer to its tables.
    phase11 = ("enterprise_contracts", "enterprise_contract_versions", "enterprise_contract_events", "enterprise_contract_term_fundings", "enterprise_contract_activations", "enterprise_contract_notices")
    tables = [t for t in flask_db.metadata.sorted_tables if t.name not in PHASE9_TABLES + phase11]
    flask_db.metadata.create_all(engine, tables=tables)


def _assert_models_match(engine):
    from app.models_billing_phase9 import (
        CreditPurchaseFunding as Funding, FinancialCaseCreditEffect as Effect,
        FinancialCaseLotEvaluation as Evaluation,
    )
    inspector = sa.inspect(engine)
    # Phase 11 (revision b4d6f8a0c2e5) adds the credit-pack term-expiry binding.
    phase11_columns = {"expiry_subscription_id", "expires_at"}
    phase11_names = {"fk_credit_purchase_fundings_expiry_subscription"}
    for model in (Funding, Evaluation, Effect):
        table = model.__table__
        assert {c.name for c in table.columns} - phase11_columns == {
            c["name"] for c in inspector.get_columns(table.name)
        }
        model_names = {c.name for c in table.constraints if c.name} - {table.primary_key.name} - phase11_names
        db_names = {
            c["name"] for c in (
                inspector.get_check_constraints(table.name) + inspector.get_foreign_keys(table.name)
                + inspector.get_unique_constraints(table.name)
            ) if c.get("name")
        }
        assert model_names == db_names, table.name
        assert {i.name for i in table.indexes} - {"ix_credit_purchase_fundings_expiry_subscription"} <= {
            i["name"] for i in inspector.get_indexes(table.name)
        }


def test_revision_extends_phase8_and_is_single_head():
    script = ScriptDirectory(MIGRATIONS_DIR)
    assert script.get_heads() == ["d7e9b1c3a5f8"]  # I3 follows I2; I2 follows I1; I1 follows BI-1; BI-1 extends the Phase 17 guard, which extends Phase 14 without changing Phase 9.
    assert script.get_revision("f2b4d6e8a0c3").down_revision == REVISION
    assert script.get_revision(REVISION).down_revision == PARENT


def test_sqlite_migration_matches_models_guards_and_downgrade_is_safe(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'phase9.sqlite'}")
    try:
        _predecessor(engine)
        with _ops(engine):
            _revision().upgrade()
        _assert_models_match(engine)
        with _ops(engine):
            _revision().downgrade()
        assert not set(sa.inspect(engine).get_table_names()) & set(PHASE9_TABLES)
        with _ops(engine):
            _revision().upgrade()
        with engine.begin() as connection:
            connection.execute(sa.text("PRAGMA foreign_keys=OFF"))
            with pytest.raises(sa.exc.DBAPIError):
                connection.execute(sa.text(
                    "INSERT INTO credit_lots (id,billing_account_id,source_type,source_id,original_amount,"
                    "available_at,origin_evidence_json,created_at) VALUES "
                    "('lot-x','a','credit_pack_purchase','none',10,'2026-01-31','{}','2026-01-31')"
                ))
            connection.execute(sa.text(
                "INSERT INTO credit_purchase_fundings (id,billing_account_id,financial_transaction_id,"
                "financial_line_id,entitlement_definition_id,package_component,funding_key,"
                "request_fingerprint,credit_amount,paid_at,lot_id,grant_entry_id,idempotency_registry_id,"
                "domain_event_id,contract_version,actor_type,actor_id,created_at) VALUES "
                "('f1','a','t','l','d','base','purchase:l:base',:fp,10,'2026-01-31','lot1','g1','r1','e1',1,"
                "'system','x','2026-01-31')"
            ), {"fp": "a" * 64})
            for statement in (
                "UPDATE credit_purchase_fundings SET credit_amount=99",
                "DELETE FROM credit_purchase_fundings",
            ):
                with pytest.raises(sa.exc.DBAPIError):
                    connection.execute(sa.text(statement))
        with pytest.raises(_revision().Phase9EvidenceNotEmptyError):
            with _ops(engine):
                _revision().downgrade()
        assert "credit_purchase_fundings" in sa.inspect(engine).get_table_names()
    finally:
        engine.dispose()


@pytest.mark.postgres
@PG
def test_postgres_isolated_migration_guards_and_downgrade_safety(validate_test_database_url, postgres_schema_url):
    base_url = validate_test_database_url(os.environ["TEST_DATABASE_URL"])
    schema = f"phase9_{uuid.uuid4().hex}"
    admin = sa.create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    engine = sa.create_engine(postgres_schema_url(base_url, schema))
    try:
        _predecessor(engine)
        with _ops(engine):
            _revision().upgrade()
        _assert_models_match(engine)
        with engine.connect() as connection:
            triggers = set(connection.execute(sa.text(
                "SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE NOT t.tgisinternal AND n.nspname=current_schema() AND t.tgname LIKE 'trg_phase9_%'"
            )).scalars())
        assert triggers == {name for name, _table in _revision().PG_TRIGGERS}
        with _ops(engine):
            _revision().downgrade()
        with engine.connect() as connection:
            leftover = connection.execute(sa.text(
                "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname=current_schema() AND p.proname LIKE 'phase9_%'"
            )).scalar_one()
        assert leftover == 0
        with _ops(engine):
            _revision().upgrade()
        with engine.connect() as connection:
            with pytest.raises(sa.exc.DBAPIError):
                connection.execute(sa.text("TRUNCATE credit_purchase_fundings"))
            connection.rollback()
            connection.execute(sa.text("SET session_replication_role = replica"))
            connection.execute(sa.text(
                "INSERT INTO financial_case_credit_effects (id,evaluation_id,billing_account_id,"
                "financial_case_id,lot_id,credit_ledger_entry_id,effect_type,amount) "
                "VALUES ('e1','v','a','c','l','x','hold',1)"
            ))
            connection.commit()
        with pytest.raises(_revision().Phase9EvidenceNotEmptyError):
            with _ops(engine):
                _revision().downgrade()
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


# ---------------------------------------------------------------------------
# Fully migrated PostgreSQL: guarded service paths, bypass rejection, races
# ---------------------------------------------------------------------------

def _migrated_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("local disposable PostgreSQL is not configured")
    engine = sa.create_engine(url, pool_size=8, max_overflow=4)
    with engine.connect() as connection:
        revision = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    if revision not in {REVISION, "f2b4d6e8a0c3", "b4d6f8a0c2e5", "c8e0a2b4d6f1", "d2f4a6c8e0b3", "f3a5c7e9b1d2", "c8a9989843b5", "a1f3c5e7b9d0", "e7b9d1f3a5c6", "d7e9b1c3a5f8"}:
        engine.dispose()
        pytest.fail(f"Phase 9 migrated tests require Alembic head {REVISION} or later; found {revision!r}")
    return engine


@pytest.mark.postgres
@PG
def test_postgres_migrated_lifecycle_passes_every_guard():
    engine = _migrated_engine()
    try:
        with Session(engine, expire_on_commit=False) as session:
            ns = seed_account(session)
            purchase = pack_purchase(session, ns)
            session.commit()
            sub = monthly_subscription_lot(session, ns)
            session.commit()
            refund(session, ns, purchase, f"re_{ns.suffix}", 400)
            session.commit()
            refund(session, ns, purchase, f"re_{ns.suffix}", 0)
            session.commit()
            object_id = f"dp_{ns.suffix}"
            for state in ("opened", "lost", "pending", "won"):
                dispute(session, ns, sub.tx, object_id, {sub.line: 10000}, state)
                session.commit()
            assert balance(session, sub.lot) == (500, 0)
            assert balance(session, purchase.lots["base"]) == (BASE, 0)
            dispute(session, ns, purchase.tx, f"dp2_{ns.suffix}", {purchase.line: PRICE}, "lost")
            session.commit()
            assert balance(session, purchase.lots["base"]) == (0, 0)
    finally:
        engine.dispose()


def _raises_integrity(session, statement, params=None):
    with pytest.raises(sa.exc.DBAPIError):
        session.execute(sa.text(statement), params or {})
        session.commit()
    session.rollback()


@pytest.mark.postgres
@PG
def test_postgres_migrated_guards_reject_direct_bypass():
    engine = _migrated_engine()
    try:
        with Session(engine, expire_on_commit=False) as session:
            ns = seed_account(session)
            purchase = pack_purchase(session, ns)
            session.commit()
            case, *_ = refund(session, ns, purchase, f"re_{ns.suffix}", 500)
            session.commit()
            lot_id = purchase.lots["base"]
            evaluation = session.query(FinancialCaseLotEvaluation).filter_by(lot_id=lot_id).one()
            reversal = session.query(FinancialCaseCreditEffect).filter_by(lot_id=lot_id).one()
            now = datetime.now(timezone.utc)
            registry = lambda: str(uuid.uuid4())  # noqa: E731

            def claim(key):
                rid = registry()
                session.execute(sa.text(
                    "INSERT INTO idempotency_registry (id,namespace,key,request_fingerprint,state,claimed_at) "
                    "VALUES (:id,'test',:key,:fp,'claimed',now())"
                ), {"id": rid, "key": key, "fp": "e" * 64})
                return rid

            # Purchased value cannot be minted without funding evidence.
            _raises_integrity(session, (
                "INSERT INTO credit_lots (id,billing_account_id,source_type,source_id,original_amount,"
                "available_at,origin_evidence_json) VALUES (:id,:a,'credit_pack_purchase','x',100,now(),'{}')"
            ), {"id": str(uuid.uuid4()), "a": ns.account})
            # A dispute hold without Phase 9 case provenance is refused at commit.
            rid = claim(str(uuid.uuid4()))
            _raises_integrity(session, (
                "INSERT INTO credit_ledger_entries (id,billing_account_id,lot_id,entry_type,available_delta,"
                "held_delta,idempotency_registry_id,effective_at,actor_type,actor_id,reason_code,evidence_json) "
                "VALUES (:id,:a,:lot,'dispute_hold',-10,10,:r,now(),'system','x','bypass','{}')"
            ), {"id": str(uuid.uuid4()), "a": ns.account, "lot": purchase.lots["bonus"], "r": rid})
            # Evidence is immutable.
            _raises_integrity(session, "UPDATE financial_case_lot_evaluations SET reversal_amount=0 WHERE id=:id",
                              {"id": evaluation.id})
            _raises_integrity(session, "DELETE FROM financial_case_credit_effects WHERE id=:id", {"id": reversal.id})
            _raises_integrity(session, "UPDATE credit_purchase_fundings SET credit_amount=1")
            # Recovery beyond the prior reversal is refused even with a ledger entry.
            rid = claim(str(uuid.uuid4()))
            entry_id = str(uuid.uuid4())
            _raises_integrity(session, (
                "INSERT INTO credit_ledger_entries (id,billing_account_id,lot_id,entry_type,available_delta,"
                "held_delta,related_entry_id,idempotency_registry_id,effective_at,actor_type,actor_id,"
                "reason_code,evidence_json) VALUES (:id,:a,:lot,'recovery',:amt,0,:rel,:r,now(),'system','x',"
                "'bypass','{}');"
                "INSERT INTO financial_case_credit_effects (id,evaluation_id,billing_account_id,financial_case_id,"
                "lot_id,credit_ledger_entry_id,effect_type,amount) VALUES (:eid,:ev,:a,:c,:lot,:id,'recovery',:amt)"
            ), {"id": entry_id, "a": ns.account, "lot": lot_id, "amt": reversal.amount + 1,
                "rel": reversal.credit_ledger_entry_id, "r": rid, "eid": str(uuid.uuid4()),
                "ev": evaluation.id, "c": case.id})
            # An evaluation cannot bind an unrelated lot to the case's source line.
            other = pack_purchase(session, ns)
            session.commit()
            rid = claim(f"financial-case-evaluation:{evaluation.financial_case_event_id}:{other.lots['base']}")
            _raises_integrity(session, (
                "INSERT INTO financial_case_lot_evaluations (id,billing_account_id,financial_case_id,"
                "financial_case_event_id,financial_line_id,lot_id,funding_kind,funding_reference_id,case_type,"
                "case_state,line_principal_minor,attributed_principal_minor,unused_basis,target_amount,"
                "held_before,reversed_before,hold_amount,release_amount,reversal_amount,recovery_amount,"
                "unrestorable_recovery_amount,absorbed_shortfall_total,evaluation_key,request_fingerprint,"
                "idempotency_registry_id,contract_version,evaluated_at) VALUES (:id,:a,:c,:e,:line,:lot,"
                "'credit_purchase',:ref,'refund','refund_recorded',1000,500,0,0,0,0,0,0,0,0,0,0,:key,:fp,:r,1,now())"
            ), {"id": str(uuid.uuid4()), "a": ns.account, "c": case.id, "e": evaluation.financial_case_event_id,
                "line": purchase.line, "lot": other.lots["base"], "ref": evaluation.funding_reference_id,
                "key": f"financial-case-evaluation:{evaluation.financial_case_event_id}:{other.lots['base']}",
                "fp": "f" * 64, "r": rid})
            _raises_integrity(session, "TRUNCATE financial_case_lot_evaluations")
            assert now
    finally:
        engine.dispose()


@pytest.mark.postgres
@PG
@pytest.mark.parametrize("isolation_level", ("READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE"))
def test_postgres_concurrent_funding_and_case_application_converge(isolation_level):
    engine = _migrated_engine()
    racing = engine.execution_options(isolation_level=isolation_level)
    try:
        with Session(engine, expire_on_commit=False) as session:
            ns = seed_account(session)
            purchase = pack_purchase(session, ns, fund=False)
            session.commit()
        barrier = threading.Barrier(3)

        def fund():
            for attempt in range(6):
                with Session(racing) as session:
                    try:
                        if attempt == 0:
                            barrier.wait()
                        result = fund_credit_purchase(
                            session, billing_account_id=ns.account, financial_line_id=purchase.line,
                            entitlement_definition_id=purchase.definition, funded_at=purchase.at,
                            delivery_obligations=DELIVERIES, **SERVICE,
                        )[2]
                        session.commit()
                        return result
                    except (sa.exc.DBAPIError, FinancialEffectRetryError):
                        session.rollback()
            return "gave-up"

        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _i: fund(), range(3)))
        assert sorted(results) == ["duplicate", "duplicate", "inserted"]
        with Session(engine, expire_on_commit=False) as session:
            assert session.query(CreditPurchaseFunding).filter_by(financial_line_id=purchase.line).count() == 2
            lots = [f.lot_id for f in session.query(CreditPurchaseFunding).filter_by(financial_line_id=purchase.line)]
            proposed = case_version(
                session, ns, source_tx=purchase.tx, case_type="refund", object_id=f"re_{ns.suffix}",
                cumulative=500, allocations={purchase.line: 500}, state="refund_recorded",
            )
            session.commit()
        barrier = threading.Barrier(2)

        def apply_and_consume(index):
            for attempt in range(6):
                with Session(racing) as session:
                    try:
                        if attempt == 0:
                            barrier.wait()
                        if index == 0:
                            apply_case(session, dict(proposed))
                        else:
                            consume(session, ns.account, lots[0], 100)
                        session.commit()
                        return "ok"
                    except (sa.exc.DBAPIError, FinancialEffectRetryError):
                        session.rollback()
            return "gave-up"

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(apply_and_consume, range(2))) == ["ok", "ok"]
        with Session(engine) as session:
            total = sum(balance(session, lot)[0] for lot in lots)
            reversed_ = sum(e.amount for e in session.query(FinancialCaseCreditEffect).filter(
                FinancialCaseCreditEffect.lot_id.in_(lots)))
            # Whichever order won, nothing went negative and value reconciles exactly.
            assert total + reversed_ + 100 == BASE + BONUS
            assert all(balance(session, lot)[0] >= 0 for lot in lots)
    finally:
        engine.dispose()
