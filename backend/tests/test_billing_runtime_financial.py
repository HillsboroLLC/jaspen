"""I2: modern webhook routing and the inbox processor (financial_events / credit_funding families)."""

from datetime import timedelta
import json
import uuid

import pytest

from app import billing_cutover as bc
from app import billing_runtime_financial as financial
from app.models import (
    BillingSubscription,
    CreditLedgerEntry,
    CreditLot,
    EntitlementInstance,
    FinancialTransaction,
    Payment,
    PersistentCreditGrant,
    StripeWebhookEvent,
)
from app.models_billing_phase5 import ExternalEventInbox, FinancialCase
from tests import billing_i2_support as s
from tests.test_billing_cutover import _org, _user


@pytest.fixture
def modern(db, app, monkeypatch):
    monkeypatch.setenv(bc.SETTING, s.ALL_I2)
    s.configure_prices(app, monkeypatch)
    session = db.session
    owner, org, assignment = s.modern_org(session)
    s.define_catalog(session, app, owner)
    customer = s.bind_customer(session, assignment, owner)
    return {"session": session, "owner": owner, "org": org, "account_id": assignment.billing_account_id,
            "customer": customer, "gateway": s.FakeGateway(), "app": app}


def _process(m, limit=20):
    return financial.process_events(m["session"], limit=limit, gateway=m["gateway"], app_config=m["app"].config)


def _state(session, event_pk):
    session.expire_all()
    row = session.get(ExternalEventInbox, event_pk)
    return row.state, row.error_code


def _activate(m, plan="essential", *, anchor=None, extra_lines=()):
    now = bc._database_now(m["session"]).replace(microsecond=0)
    anchor = anchor or (now - timedelta(days=5))
    end = s.add_calendar_months(anchor, 1)
    sub = f"sub_i2{uuid.uuid4().hex[:12]}"
    lines = [s.invoice_line(s.PRICES["STRIPE_PRICE_IDS"][plan], s.PLAN_PRICE_MINOR[plan], anchor, end),
             *extra_lines]
    inv = s.invoice(m["customer"], sub, lines, reason="subscription_create", paid_at=anchor + timedelta(minutes=1),
                    metadata={"billing_account_id": m["account_id"], "plan_key": plan})
    event_pk, _ = s.record(m["session"], m["gateway"], inv, "invoice.paid", created=anchor + timedelta(minutes=1))
    return sub, anchor, inv, event_pk


def test_a_paid_first_invoice_activates_and_funds_the_organization_once(modern):
    m, session = modern, modern["session"]
    sub, anchor, inv, event_pk = _activate(m)
    summary = _process(m)
    assert summary["processed"] == 1, summary
    assert _state(session, event_pk) == ("processed", None)
    subscription = session.query(BillingSubscription).one()
    assert (subscription.external_subscription_id, subscription.state, subscription.interval) == (sub, "active",
                                                                                                  "month")
    lot = session.query(CreditLot).filter_by(source_type="subscription_recurring").one()
    assert (lot.billing_account_id, lot.original_amount) == (m["account_id"], 7000)
    # A second delivery of the same paid invoice under a new event id converges.
    second, _ = s.record(session, m["gateway"], inv, "invoice.paid", created=anchor + timedelta(minutes=2))
    assert _process(m)["processed"] == 1
    assert session.query(CreditLot).filter_by(source_type="subscription_recurring").count() == 1
    assert session.query(FinancialTransaction).count() == 1
    # Nothing reached the legacy model.
    assert session.query(Payment).count() == 0 and session.query(PersistentCreditGrant).count() == 0


def test_renewal_moves_the_term_and_funds_the_next_period(modern):
    m, session = modern, modern["session"]
    sub, anchor, _inv, _pk = _activate(m, anchor=bc._database_now(session).replace(microsecond=0)
                                       - timedelta(days=40))
    _process(m)
    start, end = s.monthly_term(anchor, 1)
    renewal = s.invoice(m["customer"], sub, [s.invoice_line(s.PRICES["STRIPE_PRICE_IDS"]["essential"], 3900,
                                                            start, end)],
                        reason="subscription_cycle", paid_at=start + timedelta(hours=1))
    event_pk, _ = s.record(session, m["gateway"], renewal, "invoice.paid", created=start + timedelta(hours=1))
    assert _process(m)["processed"] == 1, _state(session, event_pk)
    subscription = session.query(BillingSubscription).one()
    assert (subscription.term_starts_at.replace(tzinfo=None), subscription.term_ends_at.replace(tzinfo=None)) == (
        start.replace(tzinfo=None), end.replace(tzinfo=None))
    assert session.query(CreditLot).filter_by(source_type="subscription_recurring").count() == 2
    states = sorted(i.state for i in session.query(EntitlementInstance).all())
    assert states == ["active", "expired"]


def test_an_upgrade_payment_funds_the_prorated_difference(modern):
    m, session = modern, modern["session"]
    sub, anchor, _inv, _pk = _activate(m, plan="starter")
    _process(m)
    now = bc._database_now(session).replace(microsecond=0)
    end = s.add_calendar_months(anchor, 1)
    upgrade = s.invoice(m["customer"], sub, [
        s.invoice_line(s.PRICES["STRIPE_PRICE_IDS"]["starter"], -300, now, end),
        s.invoice_line(s.PRICES["STRIPE_PRICE_IDS"]["essential"], 1800, now, end),
    ], reason="subscription_update", paid_at=now)
    event_pk, _ = s.record(session, m["gateway"], upgrade, "invoice.paid", created=now)
    assert _process(m)["processed"] == 1, _state(session, event_pk)
    subscription = session.query(BillingSubscription).one()
    from app.models import EntitlementDefinition
    assert session.get(EntitlementDefinition, subscription.current_entitlement_definition_id).key == \
        "plan.essential.monthly"


def test_a_credit_pack_needs_a_paid_term_and_funds_once(modern):
    m, session = modern, modern["session"]
    now = bc._database_now(session).replace(microsecond=0)
    intent = {"id": f"pi_i2{uuid.uuid4().hex[:12]}", "object": "payment_intent", "status": "succeeded",
              "customer": m["customer"], "amount": 1000, "amount_received": 1000, "currency": "usd",
              "metadata": {"checkout_type": "credit_pack", "pack_key": "credits_3000",
                           "billing_account_id": m["account_id"]}}
    first, _ = s.record(session, m["gateway"], intent, "payment_intent.succeeded", created=now)
    _process(m)
    assert _state(session, first) == ("quarantined", "manual_review_policy")  # no paid term in force
    _activate(m)
    _process(m)
    second, _ = s.record(session, m["gateway"], intent, "payment_intent.succeeded", created=now)
    assert _process(m)["processed"] == 1, _state(session, second)
    lot = session.query(CreditLot).filter_by(source_type="credit_pack_purchase").one()
    assert lot.original_amount == 3000
    # A full refund reverses the unused pack value.
    refund = {"id": f"re_i2{uuid.uuid4().hex[:12]}", "object": "refund", "status": "succeeded", "amount": 1000,
              "payment_intent": intent["id"], "currency": "usd"}
    m["gateway"].payment_customers[intent["id"]] = m["customer"]
    refund_pk, _ = s.record(session, m["gateway"], refund, "refund.created", created=now)
    assert _process(m)["processed"] == 1, _state(session, refund_pk)
    case = session.query(FinancialCase).one()
    assert (case.case_type, case.cumulative_principal_minor) == ("refund", 1000)
    balance = sum(e.available_delta for e in session.query(CreditLedgerEntry).filter_by(lot_id=lot.id))
    assert balance == 0


def test_subscription_refunds_and_refunded_disputes_are_quarantined_for_review(modern):
    m, session = modern, modern["session"]
    _sub, _anchor, inv, _pk = _activate(m)
    _process(m)
    now = bc._database_now(session).replace(microsecond=0)
    pi = f"pi_i2{uuid.uuid4().hex[:12]}"
    m["gateway"].invoice_payments[pi] = inv["id"]
    m["gateway"].payment_customers[pi] = m["customer"]
    refund = {"id": f"re_i2{uuid.uuid4().hex[:12]}", "object": "refund", "status": "succeeded", "amount": 100,
              "payment_intent": pi}
    refund_pk, _ = s.record(session, m["gateway"], refund, "refund.created", created=now)
    dispute = {"id": f"dp_i2{uuid.uuid4().hex[:12]}", "object": "dispute", "status": "charge_refunded",
               "amount": 3900, "payment_intent": pi}
    dispute_pk, _ = s.record(session, m["gateway"], dispute, "charge.dispute.closed", created=now)
    _process(m)
    assert _state(session, refund_pk) == ("quarantined", "subscription_refund_review")
    assert _state(session, dispute_pk) == ("quarantined", "dispute_charge_refunded_review")
    assert session.query(FinancialCase).count() == 0


def test_a_partial_dispute_on_a_multi_line_invoice_goes_to_manual_review_d5(modern):
    m, session = modern, modern["session"]
    now = bc._database_now(session).replace(microsecond=0)
    anchor = now - timedelta(days=40)
    end = s.add_calendar_months(anchor, 1)
    seat = s.invoice_line(s.PRICES["STRIPE_ADDITIONAL_SEAT_PRICE_IDS"]["team"], 2500, anchor, end)
    _sub, _anchor, inv, _pk = _activate(m, plan="team", anchor=anchor, extra_lines=[seat])
    _process(m)
    pi = f"pi_i2{uuid.uuid4().hex[:12]}"
    m["gateway"].invoice_payments[pi] = inv["id"]
    m["gateway"].payment_customers[pi] = m["customer"]
    partial = {"id": f"dp_i2{uuid.uuid4().hex[:12]}", "object": "dispute", "status": "needs_response",
               "amount": 5000, "payment_intent": pi}
    partial_pk, _ = s.record(session, m["gateway"], partial, "charge.dispute.created", created=now)
    full = {"id": f"dp_i2{uuid.uuid4().hex[:12]}", "object": "dispute", "status": "needs_response",
            "amount": inv["total"], "payment_intent": pi}
    full_pk, _ = s.record(session, m["gateway"], full, "charge.dispute.created", created=now)
    _process(m)
    assert _state(session, partial_pk) == ("quarantined", "allocation_manual_review")
    assert _state(session, full_pk) == ("processed", None)
    case = session.query(FinancialCase).one()
    assert (case.case_object_id, case.state) == (full["id"], "opened")


def test_events_wait_while_the_family_is_off(modern, monkeypatch):
    m, session = modern, modern["session"]
    _sub, _anchor, _inv, event_pk = _activate(m)
    config = bc.CutoverConfig(frozenset(bc.FAMILIES[:2]), ())
    monkeypatch.setenv(bc.SETTING, ",".join(bc.FAMILIES[:2]))
    summary = financial.process_events(session, limit=5, gateway=m["gateway"], app_config=m["app"].config,
                                       config=config)
    assert summary["retryable"] == 1
    assert _state(session, event_pk) == ("retryable", "family_disabled")
    assert session.query(CreditLot).count() == 0
    with pytest.raises(bc.BillingFamilyDisabledError):
        financial.process_events(session, limit=5, gateway=m["gateway"],
                                 config=bc.CutoverConfig(frozenset({"identity"}), ()))


def test_classify_failure_maps_retryable_causes():
    from app.billing_outbox import OutboxConcurrentUpdateError

    wrapped = ValueError("plain")
    wrapped.__cause__ = OutboxConcurrentUpdateError("raced")
    assert financial.classify_failure(wrapped) == ("retry", "OutboxConcurrentUpdateError")
    assert financial.classify_failure(financial.Quarantine("x")) == ("quarantine", "x")
    assert financial.classify_failure(RuntimeError("boom")) == ("quarantine", "unexpected:RuntimeError")
    import stripe
    assert financial.classify_failure(stripe.error.AuthenticationError("no key")) == ("retry",
                                                                                   "processor_unavailable")


# ---------------------------------------------------------------------------
# The webhook route
# ---------------------------------------------------------------------------

def _post(client, monkeypatch, payload):
    import app.routes.billing as routes

    monkeypatch.setitem(routes.current_app.config, "STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setattr(routes.stripe.Webhook, "construct_event",
                        lambda body, sig, secret: json.loads(body))
    return client.post("/api/v1/billing/webhook", data=payload, headers={"Stripe-Signature": "t"})


def test_a_modern_accounts_event_goes_only_to_the_inbox(client, modern, monkeypatch):
    m, session = modern, modern["session"]
    now = bc._database_now(session).replace(microsecond=0)
    obj = {"id": f"in_i2{uuid.uuid4().hex[:12]}", "object": "invoice", "customer": m["customer"], "status": "paid",
           "metadata": {"user_id": m["owner"].id, "checkout_type": "subscription"}}
    raw, _payload = s.event(obj, "checkout.session.completed", created=now)
    legacy_rows = session.query(StripeWebhookEvent).count()
    assert _post(client, monkeypatch, raw).status_code == 200
    assert session.query(ExternalEventInbox).count() == 1
    assert session.query(StripeWebhookEvent).count() == legacy_rows  # the legacy handler never ran
    monkeypatch.setenv(bc.SETTING, "identity")
    raw2, _ = s.event(obj, "invoice.paid", created=now)
    response = _post(client, monkeypatch, raw2)
    assert response.status_code == 503 and response.get_json()["error"] == "billing_family_disabled"
    assert session.query(ExternalEventInbox).count() == 1


def test_legacy_payers_keep_the_legacy_webhook_even_when_modern_accounts_exist(client, modern, monkeypatch, db):
    session = modern["session"]
    now = bc._database_now(session).replace(microsecond=0)
    obj = {"id": f"in_i2{uuid.uuid4().hex[:12]}", "object": "invoice", "customer": "cus_i2legacypayer",
           "status": "paid", "metadata": {}}
    raw, _ = s.event(obj, "invoice.payment_failed", created=now)
    legacy_rows = session.query(StripeWebhookEvent).count()
    assert _post(client, monkeypatch, raw).status_code == 200
    assert session.query(ExternalEventInbox).count() == 0
    assert session.query(StripeWebhookEvent).count() == legacy_rows + 1


def test_legacy_fulfillment_uses_the_checkout_organization_never_a_modern_one(client, modern, monkeypatch):
    """A user switches their active organization to a modern one between checkout and webhook."""
    session = modern["session"]
    buyer = _user(session)
    legacy = _org(session, buyer)
    from app.models import OrganizationMember
    session.add(OrganizationMember(organization_id=modern["org"].id, user_id=buyer.id, role="creator",
                                   status="active"))
    buyer.active_organization_id = modern["org"].id
    session.commit()
    now = bc._database_now(session).replace(microsecond=0)
    checkout = {"id": f"cs_i2{uuid.uuid4().hex[:12]}", "object": "checkout.session", "customer": None,
                "payment_intent": f"pi_i2{uuid.uuid4().hex[:12]}", "amount_total": 1000, "amount_subtotal": 1000,
                "currency": "usd", "metadata": {"user_id": buyer.id, "checkout_type": "credit_pack",
                                                "pack_key": "credits_3000", "tokens": "3000000",
                                                "organization_id": legacy.id}}
    raw, _ = s.event(checkout, "checkout.session.completed", created=now)
    assert _post(client, monkeypatch, raw).status_code == 200
    grant = session.query(PersistentCreditGrant).one()
    payment = session.query(Payment).one()
    assert grant.organization_id == legacy.id and payment.organization_id == legacy.id


def test_annual_releases_and_a_reapplied_dispute_announce_each_new_lot_f5(modern):
    from app import billing_runtime_funding as funding
    from app.models_billing_phase5 import DomainEvent
    from app.models_billing_phase9 import FinancialCaseLotEvaluation

    m, session = modern, modern["session"]
    now = bc._database_now(session).replace(microsecond=0)
    anchor = now - timedelta(days=40)
    end = s.add_calendar_months(anchor, 12)
    sub = f"sub_i2{uuid.uuid4().hex[:12]}"
    inv = s.invoice(m["customer"], sub, [s.invoice_line(s.PRICES["STRIPE_ANNUAL_PRICE_IDS"]["essential"], 38400,
                                                        anchor, end)],
                    reason="subscription_create", paid_at=anchor)
    s.record(session, m["gateway"], inv, "invoice.paid", created=anchor)
    assert _process(m)["processed"] == 1
    pi = f"pi_i2{uuid.uuid4().hex[:12]}"
    m["gateway"].invoice_payments[pi] = inv["id"]
    m["gateway"].payment_customers[pi] = m["customer"]
    dispute = {"id": f"dp_i2{uuid.uuid4().hex[:12]}", "object": "dispute", "status": "needs_response",
               "amount": inv["total"], "payment_intent": pi}
    s.record(session, m["gateway"], dispute, "charge.dispute.created", created=now)
    assert _process(m)["processed"] == 1
    assert session.query(FinancialCaseLotEvaluation).count() == 1
    context = bc.modern_context(session, family="credit_funding", organization_id=m["org"].id)
    release = funding.allocate_annual_release(session, context)
    session.commit()
    assert (release.outcome, release.period_index, release.reapplied_cases) == ("inserted", 1, 1)
    lots = session.query(CreditLot).filter_by(source_type="subscription_recurring").all()
    assert len(lots) == 2
    assert session.query(FinancialCaseLotEvaluation).count() == 2
    lot_events = session.query(DomainEvent).filter(DomainEvent.event_key.like("financial_case_version_applied:%:lot:%"))
    assert lot_events.count() == 1
    # Both lots are held by the dispute; running the release again adds nothing.
    for lot in lots:
        held = sum(e.held_delta for e in session.query(CreditLedgerEntry).filter_by(lot_id=lot.id))
        assert held == lot.original_amount
    again = funding.allocate_annual_release(session, context)
    session.commit()
    assert again.outcome == "duplicate"
    assert session.query(FinancialCaseLotEvaluation).count() == 2 and lot_events.count() == 1


def test_audit_fixes_seat_refunds_proration_disputes_and_ignored_failures(modern):
    m, session = modern, modern["session"]
    sub, anchor, inv, _pk = _activate(m, plan="starter")
    _process(m)
    now = bc._database_now(session).replace(microsecond=0)
    end = s.add_calendar_months(anchor, 1)
    upgrade = s.invoice(m["customer"], sub, [
        s.invoice_line(s.PRICES["STRIPE_PRICE_IDS"]["starter"], -300, now, end),
        s.invoice_line(s.PRICES["STRIPE_PRICE_IDS"]["essential"], 1800, now, end),
    ], reason="subscription_update", paid_at=now)
    s.record(session, m["gateway"], upgrade, "invoice.paid", created=now)
    assert _process(m)["processed"] == 1
    pi = f"pi_i2{uuid.uuid4().hex[:12]}"
    m["gateway"].invoice_payments[pi] = upgrade["id"]
    m["gateway"].payment_customers[pi] = m["customer"]
    # Q4: any refund of subscription money, including a proration-only invoice, waits for review.
    refund = {"id": f"re_i2{uuid.uuid4().hex[:12]}", "object": "refund", "status": "succeeded",
              "amount": upgrade["total"], "payment_intent": pi}
    refund_pk, _ = s.record(session, m["gateway"], refund, "refund.created", created=now)
    # D5: a full dispute of an invoice with a negative proration line is not an exact allocation.
    dispute = {"id": f"dp_i2{uuid.uuid4().hex[:12]}", "object": "dispute", "status": "needs_response",
               "amount": upgrade["total"], "payment_intent": pi}
    dispute_pk, _ = s.record(session, m["gateway"], dispute, "charge.dispute.created", created=now)
    # A failed first payment and an abandoned checkout are evidence only.
    failed = s.invoice(m["customer"], f"sub_i2{uuid.uuid4().hex[:8]}", [s.invoice_line(
        s.PRICES["STRIPE_PRICE_IDS"]["essential"], 3900, now, s.add_calendar_months(now, 1))],
        reason="subscription_create", paid_at=now, status="open")
    failed_pk, _ = s.record(session, m["gateway"], failed, "invoice.payment_failed", created=now)
    abandoned = {"id": f"sub_i2{uuid.uuid4().hex[:8]}", "object": "subscription", "customer": m["customer"],
                 "status": "incomplete_expired"}
    abandoned_pk, _ = s.record(session, m["gateway"], abandoned, "customer.subscription.deleted", created=now)
    _process(m)
    assert _state(session, refund_pk) == ("quarantined", "subscription_refund_review")
    assert _state(session, dispute_pk) == ("quarantined", "allocation_manual_review")
    assert _state(session, failed_pk) == ("processed", None)
    assert _state(session, abandoned_pk) == ("processed", None)


def test_legacy_value_is_held_when_its_organization_is_modern(client, modern, monkeypatch):
    """The recorded checkout organization, or the active one a grant falls back to, is modern."""
    session = modern["session"]
    buyer = _user(session)
    from app.models import OrganizationMember
    session.add(OrganizationMember(organization_id=modern["org"].id, user_id=buyer.id, role="creator",
                                   status="active"))
    buyer.active_organization_id = modern["org"].id
    session.commit()
    now = bc._database_now(session)
    grants = session.query(PersistentCreditGrant).count()
    for recorded in (modern["org"].id, None):
        metadata = {"user_id": buyer.id, "checkout_type": "credit_pack", "pack_key": "credits_3000",
                    "tokens": "3000000"}
        if recorded:
            metadata["organization_id"] = recorded
        checkout = {"id": f"cs_i2{uuid.uuid4().hex[:12]}", "object": "checkout.session", "customer": None,
                    "payment_intent": f"pi_i2{uuid.uuid4().hex[:12]}", "amount_total": 1000,
                    "amount_subtotal": 1000, "currency": "usd", "metadata": metadata}
        raw, _ = s.event(checkout, "checkout.session.completed", created=now)
        assert _post(client, monkeypatch, raw).status_code == 200
    assert session.query(PersistentCreditGrant).count() == grants
