"""Shared I2 test support: a modern organization, configured test prices, and recorded processor objects.

All processor data is synthetic (no real Stripe identifiers, customers or cards).
"""

from datetime import timedelta
import json
import uuid

from app import billing_cutover as bc
from app import billing_inbox as inbox
from app import billing_runtime_funding as funding
from app.billing_entitlements import add_calendar_months
from tests.test_billing_cutover import _establish, _org, _user

ALL_I2 = ",".join(bc.FAMILIES[:3])
PRICES = {
    "STRIPE_PRICE_IDS": {"starter": "price_i2starterm", "essential": "price_i2essentialm", "team": "price_i2teamm"},
    "STRIPE_ANNUAL_PRICE_IDS": {"starter": "price_i2startera", "essential": "price_i2essentiala",
                                "team": "price_i2teama"},
    "STRIPE_ADDITIONAL_SEAT_PRICE_IDS": {"team": "price_i2teamseatm"},
    "STRIPE_ANNUAL_ADDITIONAL_SEAT_PRICE_IDS": {"team": "price_i2teamseata"},
}
PLAN_PRICE_MINOR = {"starter": 700, "essential": 3900, "team": 12900}


def ts(value):
    return int(value.timestamp())


def configure_prices(app, monkeypatch):
    for name, mapping in PRICES.items():
        monkeypatch.setitem(app.config, name, dict(mapping))


def modern_org(session, *, members=()):
    owner = _user(session)
    org = _org(session, owner, members=members)
    assignment, _state = _establish(session, org)
    session.commit()
    return owner, org, assignment


def define_catalog(session, app, approver, *, days=400):
    funding.define_test_catalog(session, approver_user_id=approver.id, app_config=app.config,
                                effective_at=bc._database_now(session) - timedelta(days=days))
    session.commit()


def bind_customer(session, assignment, owner, customer=None):
    customer = customer or f"cus_i2{uuid.uuid4().hex[:12]}"
    bc.bind_processor_customer(session, billing_account_id=assignment.billing_account_id, processor="stripe",
                               processor_customer_id=customer, actor_user_id=owner.id)
    session.commit()
    return customer


class FakeGateway:
    """Recorded processor objects keyed by id (the authoritative re-fetch in tests)."""

    def __init__(self):
        self.objects = {}
        self.invoice_payments = {}
        self.payment_customers = {}

    def put(self, obj):
        self.objects[obj["id"]] = obj
        return obj

    def _get(self, object_id):
        return json.loads(json.dumps(self.objects[object_id]))

    invoice = payment_intent = refund = dispute = subscription = _get

    def invoice_for_payment_intent(self, payment_intent_id):
        return self.invoice_payments.get(payment_intent_id)

    def customer_for_payment(self, payment_intent_id=None, charge_id=None):
        return self.payment_customers.get(payment_intent_id) or self.payment_customers.get(charge_id)


def invoice_line(price, amount, start, end, *, quantity=1, tax=0, discount=0, line_id=None):
    return {
        "id": line_id or f"il_i2{uuid.uuid4().hex[:12]}", "object": "line_item", "amount": amount,
        "quantity": quantity, "pricing": {"price_details": {"price": price}},
        "period": {"start": ts(start), "end": ts(end)},
        "taxes": [{"amount": tax}] if tax else [], "discount_amounts": [{"amount": discount}] if discount else [],
    }


def invoice(customer, subscription, lines, *, reason, paid_at, metadata=None, invoice_id=None, status="paid"):
    total = sum(line["amount"] + sum(t["amount"] for t in line["taxes"])
                - sum(d["amount"] for d in line["discount_amounts"]) for line in lines)
    return {
        "id": invoice_id or f"in_i2{uuid.uuid4().hex[:12]}", "object": "invoice", "customer": customer,
        "status": status, "billing_reason": reason, "currency": "usd", "total": total, "amount_paid": total,
        "amount_due": total, "status_transitions": {"paid_at": ts(paid_at)},
        "parent": {"subscription_details": {"subscription": subscription, "metadata": metadata or {}}},
        "lines": {"data": lines},
    }


def event(obj, event_type, *, created, event_id=None):
    payload = {
        "id": event_id or f"evt_i2{uuid.uuid4().hex[:16]}", "object": "event", "api_version": "2026-06-24",
        "created": ts(created), "livemode": False, "type": event_type, "data": {"object": obj},
    }
    return json.dumps(payload, sort_keys=True).encode(), payload


def record(session, gateway, obj, event_type, *, created, event_id=None):
    """Record a verified event in the inbox, as the webhook does for a modern account."""
    gateway.put(obj)
    raw, payload = event(obj, event_type, created=created, event_id=event_id)
    row, outcome = inbox.record_event(session, raw, payload)
    session.commit()
    return row.id, outcome


def monthly_term(anchor, index=0):
    return add_calendar_months(anchor, index), add_calendar_months(anchor, index + 1)
