"""I2 PostgreSQL journeys: recorded processor events through the fully migrated schema (every guard live).

Each journey uses its own synthetic modern organization and processor customer. It asserts that every
money path lands in exactly one model: the modern ledger, with nothing in the legacy money tables.
"""

from datetime import timedelta
import os
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app import billing_cutover as bc
from app import billing_runtime_financial as financial
from app import billing_runtime_funding as funding
from app.billing_plan_changes import schedule_plan_change
from app.models import (
    AccountEntitlement,
    BillingSubscription,
    CreditLedgerEntry,
    CreditLot,
    EntitlementDefinition,
    Payment,
    PersistentCreditGrant,
    User,
)
from app.models_billing_phase5 import DomainEvent, ExternalEventInbox, FinancialCase
from app.models_billing_phase7 import ScheduledPlanChange
from app.models_billing_phase8 import SeatCommitment
from tests import billing_i2_support as s

HEAD = "e7b9d1f3a5c6"
pytestmark = [pytest.mark.postgres, pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="local disposable PostgreSQL is not configured")]


@pytest.fixture
def journey(app, monkeypatch):
    engine = sa.create_engine(os.environ["TEST_DATABASE_URL"], pool_size=4)
    with engine.connect() as connection:
        if connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() != HEAD:
            engine.dispose()
            pytest.fail(f"I2 journeys require Alembic head {HEAD}")
    monkeypatch.setenv(bc.SETTING, s.ALL_I2)
    s.configure_prices(app, monkeypatch)
    session = Session(engine, expire_on_commit=False)
    owner, org, assignment = s.modern_org(session)
    s.define_catalog(session, app, owner)
    customer = s.bind_customer(session, assignment, owner)
    state = {"session": session, "owner": owner, "org": org, "account_id": assignment.billing_account_id,
             "customer": customer, "gateway": s.FakeGateway(), "app": app}
    yield state
    session.rollback()
    _assert_one_model(session, state)
    session.close()
    engine.dispose()


def _assert_one_model(session, j):
    """Nothing the modern organization paid for reached the legacy money model."""
    owner = session.get(User, j["owner"].id)
    assert owner.stripe_customer_id is None and owner.stripe_subscription_id is None
    assert str(owner.subscription_plan or "free") == "free"
    for model in (Payment, PersistentCreditGrant, AccountEntitlement):
        assert session.query(model).filter(sa.or_(model.organization_id == j["org"].id,
                                                  model.user_id == owner.id)).count() == 0
    # Every recorded modern event was resolved: processed or quarantined for review.
    states = {row.state for row in session.query(ExternalEventInbox).filter(
        ExternalEventInbox.id.in_(j.get("events", [])))}
    assert states <= {"processed", "quarantined"}


def _now(j):
    j["session"].commit()  # a fresh transaction: PostgreSQL now() is the transaction start
    return bc._database_now(j["session"]).replace(microsecond=0)


def _record(j, obj, event_type, created):
    event_pk, _ = s.record(j["session"], j["gateway"], obj, event_type, created=created)
    j.setdefault("events", []).append(event_pk)
    return event_pk


def _process(j):
    summary = financial.process_events(j["session"], limit=20, gateway=j["gateway"], app_config=j["app"].config)
    return summary


def _state(j, event_pk):
    j["session"].expire_all()
    row = j["session"].get(ExternalEventInbox, event_pk)
    return row.state, row.error_code


def _balance(session, lot_id):
    rows = session.query(CreditLedgerEntry).filter_by(lot_id=lot_id).all()
    return sum(r.available_delta for r in rows), sum(r.held_delta for r in rows)


def _context(j):
    return bc.modern_context(j["session"], family="credit_funding", organization_id=j["org"].id)


def _activate(j, plan="essential", *, anchor, interval="monthly", extra_lines=()):
    months = 12 if interval == "annual" else 1
    mapping = "STRIPE_ANNUAL_PRICE_IDS" if interval == "annual" else "STRIPE_PRICE_IDS"
    sub = f"sub_i2{uuid.uuid4().hex[:12]}"
    amount = s.PLAN_PRICE_MINOR[plan] * (10 if interval == "annual" else 1)
    inv = s.invoice(j["customer"], sub, [s.invoice_line(s.PRICES[mapping][plan], amount, anchor,
                                                        s.add_calendar_months(anchor, months)), *extra_lines],
                    reason="subscription_create", paid_at=anchor, metadata={"billing_account_id": j["account_id"]})
    event_pk = _record(j, inv, "invoice.paid", anchor)
    return sub, inv, event_pk


def test_journey_free_then_paid_then_renewal_then_pack_and_refund(journey):
    j, session = journey, journey["session"]
    # D4: the organization's own Free lot, from its account anchor.
    free = funding.allocate_free(session, _context(j))
    session.commit()
    assert (free.outcome, free.credit_amount) == ("inserted", 300)
    # The first paid invoice replaces Free (Phase 7 free-to-paid) and funds the full period. The account
    # anchor is the organization's creation time, so the paid anchor starts after it.
    import time
    time.sleep(1.1)  # processor times are whole seconds; the account anchor is this fixture's creation
    anchor = _now(j)
    sub, inv, activation = _activate(j, anchor=anchor)
    assert _process(j)["processed"] == 1, _state(j, activation)
    paid = session.query(CreditLot).filter_by(billing_account_id=j["account_id"],
                                              source_type="subscription_recurring").one()
    assert paid.original_amount == 7000
    assert funding.allocate_free(session, _context(j)).outcome == "paid_plan_active"
    session.rollback()
    # A credit pack during the paid term funds once, even when delivered twice.
    intent = {"id": f"pi_i2{uuid.uuid4().hex[:12]}", "object": "payment_intent", "status": "succeeded",
              "customer": j["customer"], "amount": 1000, "amount_received": 1000, "currency": "usd",
              "metadata": {"checkout_type": "credit_pack", "pack_key": "credits_3000",
                           "billing_account_id": j["account_id"]}}
    first = _record(j, intent, "payment_intent.succeeded", _now(j))
    second = _record(j, intent, "payment_intent.succeeded", _now(j))
    _process(j)
    assert _state(j, first) == ("processed", None) and _state(j, second) == ("processed", None)
    pack = session.query(CreditLot).filter_by(billing_account_id=j["account_id"],
                                              source_type="credit_pack_purchase").one()
    assert _balance(session, pack.id) == (3000, 0)
    # A full refund reverses the unused pack value (single-line evidence, D5 basis recorded).
    j["gateway"].payment_customers[intent["id"]] = j["customer"]
    refund = {"id": f"re_i2{uuid.uuid4().hex[:12]}", "object": "refund", "status": "succeeded", "amount": 1000,
              "payment_intent": intent["id"]}
    refund_pk = _record(j, refund, "refund.created", _now(j))
    assert _process(j)["processed"] == 1, _state(j, refund_pk)
    assert _balance(session, pack.id) == (0, 0)
    assert session.execute(sa.text(
        "SELECT e.allocation_basis FROM financial_case_events e JOIN financial_cases c ON c.id=e.financial_case_id "
        "WHERE c.case_object_id=:o"), {"o": refund["id"]}).scalar_one() == "full"


def test_journey_monthly_renewal_scheduled_downgrade_and_cancellation(journey):
    j, session = journey, journey["session"]
    now = _now(j)
    anchor = now - timedelta(days=70)
    sub, _inv, activation = _activate(j, anchor=anchor)
    assert _process(j)["processed"] == 1, _state(j, activation)
    start1, end1 = s.monthly_term(anchor, 1)
    renewal = s.invoice(j["customer"], sub, [s.invoice_line(s.PRICES["STRIPE_PRICE_IDS"]["essential"], 3900,
                                                            start1, end1)], reason="subscription_cycle", paid_at=start1)
    renewal_pk = _record(j, renewal, "invoice.paid", start1)
    assert _process(j)["processed"] == 1, _state(j, renewal_pk)
    subscription = session.query(BillingSubscription).filter_by(external_subscription_id=sub).one()
    # A downgrade scheduled during the term (requested in the past here, so its term end has passed).
    starter = funding.current_definition(session, "plan.starter.monthly", start1)
    schedule_plan_change(
        session, billing_account_id=j["account_id"], subscription_id=subscription.id,
        client_command_id=f"journey-downgrade-{uuid.uuid4().hex[:8]}", kind="downgrade",
        target_entitlement_definition_id=starter.id, requested_at=start1 + timedelta(days=1),
        effective_at=end1, compatible_supersede=True, actor_type="user", actor_id=j["owner"].id,
        delivery_obligations=funding.placeholder_obligations("plan_change_scheduled"))
    session.commit()
    start2, end2 = s.monthly_term(anchor, 2)
    lower = s.invoice(j["customer"], sub, [s.invoice_line(s.PRICES["STRIPE_PRICE_IDS"]["starter"], 700, start2, end2)],
                      reason="subscription_cycle", paid_at=start2)
    lower_pk = _record(j, lower, "invoice.paid", start2)
    summary = _process(j)
    assert summary["events"][-1]["outcome"] == "downgraded", _state(j, lower_pk)
    session.expire_all()
    subscription = session.get(BillingSubscription, subscription.id)
    assert session.get(EntitlementDefinition, subscription.current_entitlement_definition_id).key == \
        "plan.starter.monthly"
    lots = session.query(CreditLot).filter_by(billing_account_id=j["account_id"],
                                              source_type="subscription_recurring").order_by(CreditLot.available_at)
    assert [lot.original_amount for lot in lots] == [7000, 7000, 1000]


def test_journey_annual_dispute_release_and_review_quarantines(journey):
    j, session = journey, journey["session"]
    now = _now(j)
    anchor = now - timedelta(days=40)
    seat = s.invoice_line(s.PRICES["STRIPE_ANNUAL_ADDITIONAL_SEAT_PRICE_IDS"]["team"], 25000, anchor,
                          s.add_calendar_months(anchor, 12))
    sub, inv, activation = _activate(j, "team", anchor=anchor, interval="annual", extra_lines=[seat])
    assert _process(j)["processed"] == 1, _state(j, activation)
    local = session.query(BillingSubscription).filter_by(external_subscription_id=sub).one()
    assert session.query(SeatCommitment).filter_by(subscription_id=local.id, state="active").one().quantity == 4
    pi = f"pi_i2{uuid.uuid4().hex[:12]}"
    j["gateway"].invoice_payments[pi] = inv["id"]
    j["gateway"].payment_customers[pi] = j["customer"]
    partial = {"id": f"dp_i2{uuid.uuid4().hex[:12]}", "object": "dispute", "status": "needs_response",
               "amount": 5000, "payment_intent": pi}
    refund = {"id": f"re_i2{uuid.uuid4().hex[:12]}", "object": "refund", "status": "succeeded", "amount": 100,
              "payment_intent": pi}
    full = {"id": f"dp_i2{uuid.uuid4().hex[:12]}", "object": "dispute", "status": "needs_response",
            "amount": inv["total"], "payment_intent": pi}
    partial_pk = _record(j, partial, "charge.dispute.created", now)
    refund_pk = _record(j, refund, "refund.created", now)
    full_pk = _record(j, full, "charge.dispute.created", now)
    _process(j)
    assert _state(j, partial_pk) == ("quarantined", "allocation_manual_review")
    assert _state(j, refund_pk) == ("quarantined", "subscription_refund_review")
    assert _state(j, full_pk) == ("processed", None)
    release = funding.allocate_annual_release(session, _context(j))
    session.commit()
    assert (release.outcome, release.period_index, release.reapplied_cases) == ("inserted", 1, 1)
    lots = session.query(CreditLot).filter_by(billing_account_id=j["account_id"],
                                              source_type="subscription_recurring").all()
    assert sorted(_balance(session, lot.id) for lot in lots) == [(0, 29000), (0, 29000)]
    assert session.query(DomainEvent).filter(
        DomainEvent.billing_account_id == j["account_id"],
        DomainEvent.event_key.like("financial_case_version_applied:%:lot:%")).count() == 1
    # The dispute is won: holds release.
    full["status"] = "won"
    won_pk = _record(j, full, "charge.dispute.closed", _now(j))
    assert _process(j)["processed"] == 1, _state(j, won_pk)
    assert sorted(_balance(session, lot.id) for lot in lots) == [(29000, 0), (29000, 0)]
    assert session.query(FinancialCase).filter_by(case_object_id=full["id"]).one().state == "won"


def test_journey_upgrade_proration_and_a_paid_seat_increase(journey):
    j, session = journey, journey["session"]
    now = _now(j)
    anchor = now - timedelta(days=5)
    sub, _inv, activation = _activate(j, "team", anchor=anchor)
    assert _process(j)["processed"] == 1, _state(j, activation)
    end = s.add_calendar_months(anchor, 1)
    import time
    time.sleep(1.1)  # whole-second processor time after the owner's billing grant began
    paid_at = _now(j)
    seat = s.invoice(j["customer"], sub, [s.invoice_line(s.PRICES["STRIPE_ADDITIONAL_SEAT_PRICE_IDS"]["team"], 2100,
                                                         paid_at, end)], reason="subscription_update", paid_at=paid_at,
                     metadata={"jaspen_seat_command_id": f"seat-{uuid.uuid4().hex[:8]}",
                               "jaspen_seat_requested_by": j["owner"].id, "jaspen_seat_delta": "1"})
    seat_pk = _record(j, seat, "invoice.paid", paid_at)
    assert _process(j)["processed"] == 1, _state(j, seat_pk)
    local = session.query(BillingSubscription).filter_by(external_subscription_id=sub).one()
    assert session.query(SeatCommitment).filter_by(subscription_id=local.id, state="active").one().quantity == 4


def test_journey_upgrade_prorates_from_the_paid_time(journey):
    j, session = journey, journey["session"]
    now = _now(j)
    anchor = now - timedelta(days=5)
    sub, _inv, activation = _activate(j, "starter", anchor=anchor)
    assert _process(j)["processed"] == 1, _state(j, activation)
    end = s.add_calendar_months(anchor, 1)
    paid_at = _now(j)
    upgrade = s.invoice(j["customer"], sub, [
        s.invoice_line(s.PRICES["STRIPE_PRICE_IDS"]["starter"], -500, paid_at, end),
        s.invoice_line(s.PRICES["STRIPE_PRICE_IDS"]["essential"], 2600, paid_at, end),
    ], reason="subscription_update", paid_at=paid_at)
    upgrade_pk = _record(j, upgrade, "invoice.paid", paid_at)
    assert _process(j)["processed"] == 1, _state(j, upgrade_pk)
    subscription = session.query(BillingSubscription).filter_by(external_subscription_id=sub).one()
    assert session.get(EntitlementDefinition, subscription.current_entitlement_definition_id).key == \
        "plan.essential.monthly"
    proration = session.query(CreditLot).filter_by(billing_account_id=j["account_id"],
                                                   source_type="subscription_recurring").count()
    assert proration == 2  # the opening period plus the prorated difference


def test_journey_a_scheduled_cancellation_ends_at_term_end(journey):
    j, session = journey, journey["session"]
    now = _now(j)
    anchor = now - timedelta(days=40)
    sub, _inv, activation = _activate(j, anchor=anchor)
    assert _process(j)["processed"] == 1, _state(j, activation)
    subscription = session.query(BillingSubscription).filter_by(external_subscription_id=sub).one()
    schedule_plan_change(
        session, billing_account_id=j["account_id"], subscription_id=subscription.id,
        client_command_id=f"journey-cancel-{uuid.uuid4().hex[:8]}", kind="cancellation",
        target_entitlement_definition_id=None, requested_at=anchor + timedelta(days=1),
        effective_at=subscription.term_ends_at, compatible_supersede=False, actor_type="user",
        actor_id=j["owner"].id, delivery_obligations=funding.placeholder_obligations("plan_change_scheduled"))
    session.commit()
    ended = _record(j, {"id": sub, "object": "subscription", "customer": j["customer"], "status": "canceled"},
                    "customer.subscription.deleted", _now(j))
    assert _process(j)["processed"] == 1, _state(j, ended)
    session.expire_all()
    assert session.get(BillingSubscription, subscription.id).state == "cancelled"
    assert session.query(ScheduledPlanChange).filter_by(subscription_id=subscription.id).one().state == "applied"
