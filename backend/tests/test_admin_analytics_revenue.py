"""Revenue metrics must come from money received, not plan membership.

The bug these guard against: the dashboard counted accounts sitting on a paid
plan and multiplied by hardcoded prices, so six $0 coupon redemptions read as
"6 Completed Purchases, $138 MRR" while a real $999 purchase was invisible.

Every test seeds `payments` rows directly — no Stripe calls.
"""

from datetime import datetime, timedelta

import pytest
from werkzeug.security import generate_password_hash

from app.models import Payment, User

ANALYTICS_URL = "/api/v1/admin/master/analytics"


def _user(db, email, *, plan="free", status=None):
    user = User(
        email=email,
        name="Person",
        password_hash=generate_password_hash("ValidPass1", method="pbkdf2:sha256"),
        subscription_plan=plan,
        subscription_status=status,
        credits_remaining=300,
        seat_limit=1,
        max_seats=1,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _payment(db, *, user=None, reference, source="subscription_invoice",
             paid_cents=3900, due_cents=None, interval="month", days_ago=1,
             subscription_id=None):
    due = due_cents if due_cents is not None else paid_cents
    payment = Payment(
        user_id=str(user.id) if user else None,
        external_reference=reference,
        source=source,
        amount_paid_cents=paid_cents,
        amount_due_cents=due,
        discount_cents=max(0, due - paid_cents),
        is_comped=(paid_cents == 0 and due > 0),
        billing_interval=interval,
        stripe_subscription_id=subscription_id,
        paid_at=datetime.utcnow() - timedelta(days=days_ago),
    )
    db.session.add(payment)
    db.session.commit()
    return payment


def _metrics(client, admin_auth_headers):
    response = client.get(ANALYTICS_URL, headers=admin_auth_headers)
    assert response.status_code == 200
    return response.get_json()["metrics"]


# --- The original bug, asserted directly ------------------------------------

def test_a_comped_plan_with_no_payment_row_is_not_revenue(client, db, admin_auth_headers):
    """Six accounts on paid plans, no money — the exact reported symptom."""
    for index in range(3):
        _user(db, f"comped-essential-{index}@example.com", plan="essential", status="active")
    for index in range(3):
        _user(db, f"comped-starter-{index}@example.com", plan="starter", status="active")

    metrics = _metrics(client, admin_auth_headers)

    assert metrics["completed_purchases_30d"] == 0
    assert metrics["gross_revenue_30d"] == 0
    assert metrics["mrr"] == 0


def test_a_fully_discounted_invoice_counts_as_a_redemption_not_revenue(client, db, admin_auth_headers):
    user = _user(db, "coupon@example.com", plan="essential", status="active")
    _payment(db, user=user, reference="in_comped_1", paid_cents=0, due_cents=3900)

    metrics = _metrics(client, admin_auth_headers)

    assert metrics["coupon_redemptions_30d"] == 1
    assert metrics["completed_purchases_30d"] == 0
    assert metrics["gross_revenue_30d"] == 0
    assert metrics["mrr"] == 0


# --- Window behaviour -------------------------------------------------------

def test_a_payment_outside_the_window_leaves_the_30_day_metrics_alone(client, db, admin_auth_headers):
    user = _user(db, "older@example.com", plan="essential", status="active")
    _payment(db, user=user, reference="in_old_1", paid_cents=3900, days_ago=45,
             subscription_id="sub_old")

    metrics = _metrics(client, admin_auth_headers)

    assert metrics["completed_purchases_30d"] == 0
    assert metrics["gross_revenue_30d"] == 0
    # MRR is point-in-time, so an active subscription still contributes.
    assert metrics["mrr"] == 39.0


def test_payments_inside_the_window_are_summed(client, db, admin_auth_headers):
    user = _user(db, "payer@example.com", plan="essential", status="active")
    _payment(db, user=user, reference="in_1", paid_cents=3900, days_ago=2, subscription_id="sub_1")
    _payment(db, user=user, reference="in_2", paid_cents=700, days_ago=10, subscription_id="sub_1")

    metrics = _metrics(client, admin_auth_headers)

    assert metrics["completed_purchases_30d"] == 2
    assert metrics["gross_revenue_30d"] == 46.0


# --- MRR --------------------------------------------------------------------

def test_a_canceled_subscription_contributes_nothing_to_mrr(client, db, admin_auth_headers):
    user = _user(db, "canceled@example.com", plan="essential", status="canceled")
    _payment(db, user=user, reference="in_canceled_1", paid_cents=3900, subscription_id="sub_c")

    metrics = _metrics(client, admin_auth_headers)

    assert metrics["mrr"] == 0
    # The money was still received, so revenue keeps it.
    assert metrics["gross_revenue_30d"] == 39.0


def test_a_past_due_subscription_contributes_nothing_to_mrr(client, db, admin_auth_headers):
    user = _user(db, "pastdue@example.com", plan="essential", status="past_due")
    _payment(db, user=user, reference="in_pastdue_1", paid_cents=3900, subscription_id="sub_p")

    assert _metrics(client, admin_auth_headers)["mrr"] == 0


def test_an_annual_subscriber_contributes_one_twelfth_to_mrr(client, db, admin_auth_headers):
    user = _user(db, "annual@example.com", plan="essential", status="active")
    _payment(db, user=user, reference="in_annual_1", paid_cents=38400,
             interval="year", subscription_id="sub_a")

    assert _metrics(client, admin_auth_headers)["mrr"] == 32.0


def test_mrr_counts_each_subscription_once_at_its_latest_invoice(client, db, admin_auth_headers):
    user = _user(db, "renewing@example.com", plan="essential", status="active")
    _payment(db, user=user, reference="in_old_cycle", paid_cents=700, days_ago=40,
             subscription_id="sub_r")
    _payment(db, user=user, reference="in_new_cycle", paid_cents=3900, days_ago=2,
             subscription_id="sub_r")

    # The upgrade, not the sum of both cycles.
    assert _metrics(client, admin_auth_headers)["mrr"] == 39.0


def test_a_team_subscription_contributes_its_actual_invoice_amount(client, db, admin_auth_headers):
    """Team was previously hardcoded to $0 in the MRR table."""
    user = _user(db, "team@example.com", plan="team", status="active")
    _payment(db, user=user, reference="in_team_1", paid_cents=51600, subscription_id="sub_t")

    assert _metrics(client, admin_auth_headers)["mrr"] == 516.0


def test_a_one_time_300k_purchase_is_revenue_but_not_mrr(client, db, admin_auth_headers):
    user = _user(db, "buyer300k@example.com", plan="free", status="active")
    _payment(db, user=user, reference="in_300k_1", source="limited_time_300k",
             paid_cents=99900, interval=None)

    metrics = _metrics(client, admin_auth_headers)

    assert metrics["completed_purchases_30d"] == 1
    assert metrics["gross_revenue_30d"] == 999.0
    assert metrics["mrr"] == 0


def test_a_credit_pack_is_revenue_but_not_mrr(client, db, admin_auth_headers):
    user = _user(db, "packbuyer@example.com", plan="essential", status="active")
    _payment(db, user=user, reference="pi_pack_1", source="credit_pack",
             paid_cents=2500, interval=None)

    metrics = _metrics(client, admin_auth_headers)

    assert metrics["gross_revenue_30d"] == 25.0
    assert metrics["mrr"] == 0


# --- Payload shape ----------------------------------------------------------

def test_the_renamed_key_replaces_the_old_one(client, db, admin_auth_headers):
    metrics = _metrics(client, admin_auth_headers)

    assert "completed_purchases_30d" in metrics
    # The old key carried a different meaning; leaving it would be a silent lie.
    assert "completed_purchases" not in metrics


def _signup_row(client, admin_auth_headers, email):
    response = client.get(ANALYTICS_URL, headers=admin_auth_headers)
    rows = response.get_json()["recent_signups"]
    return next(row for row in rows if row["email"] == email)


def test_a_300k_buyer_is_labelled_300k_not_free(client, db, admin_auth_headers):
    """Buying the 300K offer never touches subscription_plan, so a buyer used
    to appear as 'free' — indistinguishable from someone who bought nothing."""
    from app.founder_entitlements import grant_limited_time_300k_offer

    buyer = _user(db, "buyer300k@example.com", plan="free")
    assert _signup_row(client, admin_auth_headers, buyer.email)["plan"] == "free"

    grant_limited_time_300k_offer(buyer, 300000, payment_reference="in_label_1")
    db.session.commit()

    assert _signup_row(client, admin_auth_headers, buyer.email)["plan"] == "300K"


def test_a_300k_buyer_on_a_paid_plan_shows_both(client, db, admin_auth_headers):
    from app.founder_entitlements import grant_limited_time_300k_offer

    buyer = _user(db, "both@example.com", plan="essential", status="active")
    grant_limited_time_300k_offer(buyer, 300000, payment_reference="in_label_2")
    db.session.commit()

    # Neither fact should mask the other.
    assert _signup_row(client, admin_auth_headers, buyer.email)["plan"] == "essential + 300K"


def test_a_revoked_300k_entitlement_stops_being_labelled(client, db, admin_auth_headers):
    from app.founder_entitlements import (
        grant_limited_time_300k_offer,
        reverse_limited_time_300k_credits,
    )

    buyer = _user(db, "refunded@example.com", plan="free")
    grant_limited_time_300k_offer(buyer, 300000, payment_reference="in_label_3")
    db.session.commit()
    assert _signup_row(client, admin_auth_headers, buyer.email)["plan"] == "300K"

    reverse_limited_time_300k_credits(buyer, reason="refund", external_reference="re_1")
    db.session.commit()

    assert _signup_row(client, admin_auth_headers, buyer.email)["plan"] == "free"


def test_a_plain_free_signup_is_untouched(client, db, admin_auth_headers):
    user = _user(db, "plainfree@example.com", plan="free")

    assert _signup_row(client, admin_auth_headers, user.email)["plan"] == "free"


def test_the_notes_say_where_each_number_comes_from(client, db, admin_auth_headers):
    response = client.get(ANALYTICS_URL, headers=admin_auth_headers)
    notes = response.get_json()["notes"]

    assert "coupon_redemptions_30d" in notes
    assert "mrr" in notes
    # The superseded claim must be gone.
    assert "Self-serve MRR estimate" not in notes["mrr"]
