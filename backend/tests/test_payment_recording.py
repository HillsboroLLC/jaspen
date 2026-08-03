"""Payments are recorded once, with the discount preserved.

These exercise the fulfilment helpers directly, the way
test_limited_time_300k_refund_and_receipt.py does — no signature verification,
no Stripe calls.
"""

from datetime import datetime

import pytest
from werkzeug.security import generate_password_hash

from app.models import Payment, User


@pytest.fixture
def buyer(db):
    user = User(
        email="buyer@example.com",
        name="Buyer",
        password_hash=generate_password_hash("ValidPass1", method="pbkdf2:sha256"),
        subscription_plan="free",
        credits_remaining=300,
        seat_limit=1,
        max_seats=1,
        stripe_customer_id="cus_recording",
    )
    db.session.add(user)
    db.session.commit()
    return user


def _300k_invoice(reference, *, amount_paid, amount_due, buyer, promotion_code=None):
    from app.routes import billing

    metadata = {
        "user_id": str(buyer.id),
        "checkout_type": billing.LIMITED_TIME_300K_CHECKOUT_TYPE,
        "tokens": "300000000",
    }
    if promotion_code:
        metadata["promotion_code"] = promotion_code
    return {
        "id": reference,
        "status": "paid",
        "amount_paid": amount_paid,
        "amount_due": amount_due,
        "currency": "usd",
        "customer": "cus_recording",
        "metadata": metadata,
    }


def test_a_paid_300k_invoice_records_the_money(app, db, buyer, monkeypatch):
    from app.routes import billing

    monkeypatch.setattr(billing, "_send_limited_time_300k_welcome_email", lambda *a, **k: None)

    result = billing._fulfill_limited_time_300k_invoice(
        _300k_invoice("in_paid_300k", amount_paid=99900, amount_due=99900, buyer=buyer)
    )
    db.session.commit()

    assert result["granted"] is True
    payment = Payment.query.filter_by(external_reference="in_paid_300k").one()
    assert payment.amount_paid_cents == 99900
    assert payment.is_comped is False
    assert payment.source == "limited_time_300k"
    assert payment.user_id == str(buyer.id)


def test_a_fully_comped_300k_invoice_is_recorded_as_a_redemption(app, db, buyer, monkeypatch):
    """The $0 test redemptions that started all of this. The row has to exist,
    flagged, or the dashboard cannot tell a comp from a sale."""
    from app.routes import billing

    monkeypatch.setattr(billing, "_send_limited_time_300k_welcome_email", lambda *a, **k: None)

    billing._fulfill_limited_time_300k_invoice(
        _300k_invoice("in_comped_300k", amount_paid=0, amount_due=99900,
                      buyer=buyer, promotion_code="LAUNCH100")
    )
    db.session.commit()

    payment = Payment.query.filter_by(external_reference="in_comped_300k").one()
    assert payment.amount_paid_cents == 0
    assert payment.amount_due_cents == 99900
    assert payment.discount_cents == 99900
    assert payment.is_comped is True
    assert payment.promotion_code == "LAUNCH100"


def test_the_same_invoice_delivered_twice_records_one_payment(app, db, buyer, monkeypatch):
    from app.routes import billing

    monkeypatch.setattr(billing, "_send_limited_time_300k_welcome_email", lambda *a, **k: None)
    invoice = _300k_invoice("in_replayed", amount_paid=99900, amount_due=99900, buyer=buyer)

    billing._fulfill_limited_time_300k_invoice(invoice)
    db.session.commit()
    billing._fulfill_limited_time_300k_invoice(invoice)
    db.session.commit()

    assert Payment.query.filter_by(external_reference="in_replayed").count() == 1


def test_the_helper_itself_is_idempotent(app, db, buyer):
    """Guards the backfill script, which re-runs over live data on purpose."""
    from app.routes import billing

    first, created_first = billing._record_payment(
        external_reference="in_direct",
        source="subscription_invoice",
        user=buyer,
        amount_paid=3900,
        amount_due=3900,
    )
    db.session.commit()
    second, created_second = billing._record_payment(
        external_reference="in_direct",
        source="subscription_invoice",
        user=buyer,
        amount_paid=3900,
        amount_due=3900,
    )
    db.session.commit()

    assert created_first is True
    assert created_second is False
    assert first.id == second.id
    assert Payment.query.filter_by(external_reference="in_direct").count() == 1


def test_a_genuinely_free_invoice_is_not_counted_as_a_redemption(app, db, buyer):
    """Nothing was owed, so nothing was discounted."""
    from app.routes import billing

    payment, _ = billing._record_payment(
        external_reference="in_zero_zero",
        source="subscription_invoice",
        user=buyer,
        amount_paid=0,
        amount_due=0,
    )
    db.session.commit()

    assert payment.is_comped is False


def test_the_billing_interval_is_read_from_the_invoice_line(app, db):
    from app.routes import billing

    invoice = {
        "id": "in_annual",
        "lines": {"data": [{"price": {"recurring": {"interval": "year"}}}]},
    }
    assert billing._invoice_interval(invoice) == "year"
    assert billing._invoice_interval({"id": "in_onetime", "lines": {"data": []}}) is None


def test_a_credit_pack_intent_records_its_amount(app, db, buyer):
    from app.routes import billing

    intent = {
        "id": "pi_pack_recorded",
        "status": "succeeded",
        "amount": 2500,
        "amount_received": 2500,
        "currency": "usd",
        "customer": "cus_recording",
        "metadata": {
            "user_id": str(buyer.id),
            "checkout_type": "credit_pack",
            "tokens": "100000",
        },
    }

    result = billing._fulfill_credit_pack_payment_intent(intent)
    db.session.commit()

    assert result["granted"] is True
    payment = Payment.query.filter_by(external_reference="pi_pack_recorded").one()
    assert payment.source == "credit_pack"
    assert payment.amount_paid_cents == 2500
