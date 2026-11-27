"""I2: modern dispatch inside the existing billing routes (same request and response shapes)."""

from datetime import timedelta
from types import SimpleNamespace
import uuid

import pytest

from app import billing_cutover as bc
from app import billing_runtime_financial as financial
from app.models import BillingAccount, BillingSubscription, OrganizationMember
from app.models_billing_phase7 import ScheduledPlanChange
from app.models_billing_phase8 import SeatCommitment
from tests import billing_i2_support as s
from tests.test_billing_cutover import _establish, _org, _user


class FakeStripeObject(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


@pytest.fixture
def owner_org(db, app, test_user, monkeypatch):
    monkeypatch.setenv(bc.SETTING, s.ALL_I2)
    s.configure_prices(app, monkeypatch)
    session = db.session
    org = _org(session, test_user)
    assignment, _ = _establish(session, org)
    test_user.active_organization_id = org.id
    session.commit()
    s.define_catalog(session, app, test_user)
    return SimpleNamespace(session=session, org=org, account_id=assignment.billing_account_id, user=test_user,
                           gateway=s.FakeGateway(), app=app)


@pytest.fixture
def stripe_calls(monkeypatch):
    import app.routes.billing as routes

    calls = []

    def recorder(name, result):
        def call(*args, **kwargs):
            calls.append((name, args, kwargs))
            return result(*args, **kwargs) if callable(result) else result
        return call

    monkeypatch.setattr(routes.stripe.Customer, "create",
                        recorder("Customer.create", lambda **k: FakeStripeObject(id=f"cus_i2{uuid.uuid4().hex[:10]}")))
    monkeypatch.setattr(routes.stripe.Subscription, "create", recorder(
        "Subscription.create", lambda **k: FakeStripeObject(id="sub_i2created", status="incomplete",
                                                            latest_invoice=None, pending_setup_intent=None)))
    monkeypatch.setattr(routes, "_subscription_payment_client_secret", lambda sub: "seti_secret_i2")
    monkeypatch.setattr(routes.stripe.checkout.Session, "create",
                        recorder("Session.create", FakeStripeObject(id="cs_i2", url="https://checkout.invalid/cs")))
    monkeypatch.setattr(routes.stripe.PaymentIntent, "create",
                        recorder("PaymentIntent.create", FakeStripeObject(id="pi_i2", client_secret="pi_secret_i2")))
    return calls


def _activate(o, plan="essential", *, anchor=None, extra_lines=()):
    session = o.session
    account = session.get(BillingAccount, o.account_id)
    if account.processor_customer_id is None:
        s.bind_customer(session, SimpleNamespace(billing_account_id=o.account_id), o.user)
        account = session.get(BillingAccount, o.account_id)
    now = bc._database_now(session).replace(microsecond=0)
    anchor = anchor or now - timedelta(days=5)
    end = s.add_calendar_months(anchor, 1)
    sub = f"sub_i2{uuid.uuid4().hex[:12]}"
    lines = [s.invoice_line(s.PRICES["STRIPE_PRICE_IDS"][plan], s.PLAN_PRICE_MINOR[plan], anchor, end),
             *extra_lines]
    inv = s.invoice(account.processor_customer_id, sub, lines, reason="subscription_create",
                    paid_at=anchor + timedelta(minutes=1))
    s.record(session, o.gateway, inv, "invoice.paid", created=anchor + timedelta(minutes=1))
    assert _process(o)["processed"] >= 1
    return sub, anchor, account.processor_customer_id


def _process(o):
    return financial.process_events(o.session, limit=20, gateway=o.gateway, app_config=o.app.config)


def test_a_new_modern_subscription_creates_and_binds_the_account_customer(client, auth_headers, owner_org,
                                                                         stripe_calls):
    response = client.post("/api/v1/billing/create-subscription", json={"plan_key": "essential"},
                           headers=auth_headers)
    assert response.status_code == 200, response.get_json()
    assert set(response.get_json()) == {"subscription_id", "client_secret", "plan_key", "billing_interval",
                                        "publishable_key"}
    name, _args, customer = stripe_calls[0]
    assert name == "Customer.create"
    assert customer["metadata"]["billing_account_id"] == owner_org.account_id
    assert customer["idempotency_key"] == f"jaspen-billing-account-customer:{owner_org.account_id}"
    account = owner_org.session.get(BillingAccount, owner_org.account_id)
    assert account.processor_customer_id is not None and owner_org.user.stripe_customer_id is None
    _name, _args, created = stripe_calls[1]
    assert created["customer"] == account.processor_customer_id
    assert created["metadata"]["billing_account_id"] == owner_org.account_id
    assert "user_id" not in created["metadata"]
    # The customer is created once.
    client.post("/api/v1/billing/create-checkout-session", json={"plan_key": "essential"}, headers=auth_headers)
    assert [c[0] for c in stripe_calls].count("Customer.create") == 1
    session_call = [c for c in stripe_calls if c[0] == "Session.create"][0][2]
    assert session_call["subscription_data"]["metadata"]["billing_account_id"] == owner_org.account_id


def test_modern_commands_need_billing_authority(client, db, app, owner_org, stripe_calls):
    from flask_jwt_extended import create_access_token

    member = _user(owner_org.session)
    owner_org.session.add(OrganizationMember(organization_id=owner_org.org.id, user_id=member.id, role="admin",
                                             status="active"))
    member.active_organization_id = owner_org.org.id
    owner_org.session.commit()
    with app.app_context():
        headers = {"Authorization": f"Bearer {create_access_token(identity=member.id)}"}
    response = client.post("/api/v1/billing/create-subscription", json={"plan_key": "essential"}, headers=headers)
    assert response.status_code == 403
    assert stripe_calls == []


def test_a_disabled_family_keeps_the_i1_refusal(client, auth_headers, owner_org, stripe_calls, monkeypatch):
    monkeypatch.setenv(bc.SETTING, ",".join(bc.FAMILIES[:2]))
    response = client.post("/api/v1/billing/create-subscription", json={"plan_key": "essential"},
                           headers=auth_headers)
    assert response.status_code == 409 and response.get_json()["error"] == "billing_model_conflict"
    # An unimplemented command keeps the 409 even with every I2 family on.
    monkeypatch.setenv(bc.SETTING, s.ALL_I2)
    response = client.post("/api/v1/billing/create-portal-session", json={}, headers=auth_headers)
    assert response.status_code == 409
    assert stripe_calls == []


def test_a_credit_pack_is_refused_before_any_charge_without_a_paid_term(client, auth_headers, owner_org,
                                                                        stripe_calls):
    response = client.post("/api/v1/billing/create-credit-pack-payment-intent", json={"pack_key": "credits_3000"},
                           headers=auth_headers)
    assert response.status_code == 409
    assert stripe_calls == []


def test_a_credit_pack_purchase_and_confirmation(client, auth_headers, owner_org, stripe_calls, monkeypatch):
    _activate(owner_org)
    response = client.post("/api/v1/billing/create-credit-pack-payment-intent", json={"pack_key": "credits_3000"},
                           headers=auth_headers)
    assert response.status_code == 200, response.get_json()
    assert set(response.get_json()) == {"client_secret", "publishable_key", "pack_key", "pack_label", "price_label"}
    intent_call = [c for c in stripe_calls if c[0] == "PaymentIntent.create"][0][2]
    assert intent_call["amount"] == 1000 and intent_call["metadata"]["billing_account_id"] == owner_org.account_id
    import app.routes.billing as routes
    account = owner_org.session.get(BillingAccount, owner_org.account_id)
    intent = {"id": "pi_i2", "object": "payment_intent", "status": "succeeded",
              "customer": account.processor_customer_id, "amount": 1000, "amount_received": 1000,
              "currency": "usd", "metadata": intent_call["metadata"]}
    monkeypatch.setattr(routes.stripe.PaymentIntent, "retrieve", lambda pid: FakeStripeObject(intent))
    pending = client.post("/api/v1/billing/confirm-credit-pack-payment", json={"payment_intent_id": "pi_i2"},
                          headers=auth_headers)
    assert pending.status_code == 409
    s.record(owner_org.session, owner_org.gateway, intent, "payment_intent.succeeded",
             created=bc._database_now(owner_org.session))
    _process(owner_org)
    done = client.post("/api/v1/billing/confirm-credit-pack-payment", json={"payment_intent_id": "pi_i2"},
                       headers=auth_headers)
    assert done.status_code == 200 and done.get_json()["credits"] == 3000


def _processor_subscription(monkeypatch, sub, items):
    import app.routes.billing as routes

    calls = []
    monkeypatch.setattr(routes.stripe.Subscription, "retrieve",
                        lambda sid, **k: FakeStripeObject(id=sid, items={"data": items}, status="active"))

    def modify(sid, **kwargs):
        calls.append(kwargs)
        return FakeStripeObject(id=sid, status="active", cancel_at_period_end=kwargs.get("cancel_at_period_end"),
                                latest_invoice={"status": "paid"})
    monkeypatch.setattr(routes.stripe.Subscription, "modify", modify)
    return calls


def test_cancel_resume_and_the_term_end_apply_through_phase7(client, auth_headers, owner_org, stripe_calls,
                                                            monkeypatch):
    sub, _anchor, customer = _activate(owner_org)
    calls = _processor_subscription(monkeypatch, sub, [])
    response = client.post("/api/v1/billing/cancel-subscription", headers=auth_headers)
    assert response.status_code == 200, response.get_json()
    assert set(response.get_json()) == {"msg", "current_period_end", "current_period_end_iso"}
    assert calls[-1] == {"cancel_at_period_end": True}
    session = owner_org.session
    change = session.query(ScheduledPlanChange).one()
    assert (change.kind, change.state) == ("cancellation", "pending")
    response = client.post("/api/v1/billing/resume-subscription", headers=auth_headers)
    assert response.status_code == 200 and calls[-1] == {"cancel_at_period_end": False}
    session.expire_all()
    assert session.query(ScheduledPlanChange).one().state == "cancelled"
    assert session.query(BillingSubscription).one().state == "active"
    client.post("/api/v1/billing/cancel-subscription", headers=auth_headers)
    # The processor ends the subscription at term end; Phase 7 applies the cancellation.
    s.record(session, owner_org.gateway, {"id": sub, "object": "subscription", "customer": customer,
                                          "status": "canceled"}, "customer.subscription.deleted",
             created=bc._database_now(session))
    _summary = _process(owner_org); assert _summary["processed"] == 1, _summary["events"]
    session.expire_all()
    assert session.query(BillingSubscription).one().state == "cancelled"


def test_a_downgrade_is_scheduled_and_applies_at_the_paid_renewal(client, auth_headers, owner_org, stripe_calls,
                                                                 monkeypatch):
    now = bc._database_now(owner_org.session).replace(microsecond=0)
    sub, anchor, customer = _activate(owner_org, anchor=now - timedelta(days=40))
    session = owner_org.session
    # Renew once so the current term contains now.
    start, end = s.monthly_term(anchor, 1)
    renewal = s.invoice(customer, sub, [s.invoice_line(s.PRICES["STRIPE_PRICE_IDS"]["essential"], 3900, start,
                                                       end)], reason="subscription_cycle", paid_at=start)
    s.record(session, owner_org.gateway, renewal, "invoice.paid", created=start)
    _summary = _process(owner_org); assert _summary["processed"] == 1, _summary["events"]
    item = {"id": "si_plan", "price": {"id": s.PRICES["STRIPE_PRICE_IDS"]["essential"]}}
    calls = _processor_subscription(monkeypatch, sub, [item])
    response = client.post("/api/v1/billing/modify-subscription", json={"plan_key": "starter"}, headers=auth_headers)
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["effective"] == "period_end"
    assert calls[-1]["proration_behavior"] == "none"
    change = session.query(ScheduledPlanChange).one()
    assert (change.kind, change.state) == ("downgrade", "pending")
    assert session.query(BillingSubscription).one().current_entitlement_definition_id != \
        change.target_entitlement_definition_id
    # The processor's paid renewal at the lower price applies it. (This period starts in the future; only
    # the create_all schema accepts that. The PostgreSQL journeys use past periods.)
    nxt, nxt_end = s.monthly_term(anchor, 2)
    lower = s.invoice(customer, sub, [s.invoice_line(s.PRICES["STRIPE_PRICE_IDS"]["starter"], 700, nxt, nxt_end)],
                      reason="subscription_cycle", paid_at=nxt)
    s.record(session, owner_org.gateway, lower, "invoice.paid", created=now)
    summary = _process(owner_org)
    assert summary["events"][-1]["outcome"] == "downgraded", summary["events"]
    session.expire_all()
    subscription = session.query(BillingSubscription).one()
    from app.models import EntitlementDefinition
    assert session.get(EntitlementDefinition, subscription.current_entitlement_definition_id).key == \
        "plan.starter.monthly"
    assert session.query(ScheduledPlanChange).one().state == "applied"


def test_an_added_seat_is_paid_then_committed_by_the_processor(client, auth_headers, owner_org, stripe_calls,
                                                               monkeypatch):
    sub, anchor, customer = _activate(owner_org, plan="team")
    session = owner_org.session
    assert session.query(SeatCommitment).one().quantity == 3
    calls = _processor_subscription(monkeypatch, sub, [])
    response = client.post("/api/v1/billing/seats", headers=auth_headers)
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert (body["current_seats"], body["included_seats"], body["success"]) == (4, 3, True)
    metadata = calls[-1]["metadata"]
    assert metadata["jaspen_seat_requested_by"] == owner_org.user.id and metadata["jaspen_seat_delta"] == "1"
    import time
    time.sleep(1.1)  # processor times are whole seconds; the owner's grant began moments ago in this fixture
    now = bc._database_now(session).replace(microsecond=0)
    seat_invoice = s.invoice(customer, sub, [s.invoice_line(s.PRICES["STRIPE_ADDITIONAL_SEAT_PRICE_IDS"]["team"],
                                                            2000, now, s.add_calendar_months(anchor, 1))],
                             reason="subscription_update", paid_at=now, metadata=metadata)
    event_pk, _ = s.record(session, owner_org.gateway, seat_invoice, "invoice.paid", created=now)
    _summary = _process(owner_org); assert _summary["processed"] == 1, _summary["events"]
    session.expire_all()
    assert session.query(SeatCommitment).filter_by(state="active").one().quantity == 4
