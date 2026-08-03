"""The homepage promotion control plane.

The promotion is an offer shown to strangers on the highest-traffic page in
the app, so the tests here are mostly about what makes it STOP: the operator
switch, the sales cap, an end date if one is ever set, and the buyer who
already owns the offer.
"""

from datetime import datetime, timedelta, timezone

import pytest
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from app.founder_entitlements import grant_limited_time_300k_offer
from app.homepage_promotion import (
    DEFAULT_SALES_CAP,
    PROMOTION_SETTING_KEY,
    get_promotion_config,
    limited_time_300k_sales_count,
    normalize_promotion_config,
    promotion_is_live,
    public_promotion_state,
    reset_promotion_cache,
    save_promotion_config,
)
from app.models import AppSetting, User

PUBLIC_URL = "/api/v1/public/promotions/homepage"
ADMIN_URL = "/api/v1/admin/homepage-promotion"


def _activate(db, **overrides):
    save_promotion_config({"active": True, **overrides})
    db.session.commit()
    reset_promotion_cache()


def _make_user(db, email="buyer@example.com"):
    user = User(
        email=email,
        name="Buyer",
        password_hash=generate_password_hash("ValidPass1", method="pbkdf2:sha256"),
        subscription_plan="free",
        credits_remaining=300,
        seat_limit=1,
        max_seats=1,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _headers(app, user):
    with app.app_context():
        return {"Authorization": f"Bearer {create_access_token(identity=str(user.id))}"}


# --- Config normalization ---------------------------------------------------

def test_promotion_is_off_until_an_operator_turns_it_on(db):
    config = get_promotion_config()
    assert config["active"] is False
    assert config["sales_cap"] == DEFAULT_SALES_CAP


def test_a_partial_patch_leaves_the_rest_of_the_config_alone(db):
    save_promotion_config({"active": True, "campaign_path": "/limited-time/client-decisions"})
    db.session.commit()

    save_promotion_config({"frequency": {"max_impressions": 2}})
    db.session.commit()

    config = get_promotion_config()
    assert config["active"] is True
    assert config["campaign_path"] == "/limited-time/client-decisions"
    assert config["frequency"]["max_impressions"] == 2
    assert config["frequency"]["cooldown_hours"] == 72


def test_a_junk_payload_degrades_to_the_previous_values(db):
    save_promotion_config({"active": True, "sales_cap": 500})
    db.session.commit()

    save_promotion_config({
        "campaign_path": "https://evil.example.com/steal",
        "sales_cap": "not a number",
        "frequency": {"cooldown_hours": "soon"},
    })
    db.session.commit()

    config = get_promotion_config()
    assert config["campaign_path"] == "/limited-time/project-prioritization"
    assert config["sales_cap"] == 500
    assert config["frequency"]["cooldown_hours"] == 72


def test_frequency_values_are_clamped_to_sane_ceilings(db):
    normalized = normalize_promotion_config({
        "frequency": {"delay_seconds": 99999, "cooldown_hours": -5, "max_impressions": 400},
    })
    assert normalized["frequency"]["delay_seconds"] == 600
    assert normalized["frequency"]["cooldown_hours"] == 0
    assert normalized["frequency"]["max_impressions"] == 25


# --- Stop conditions --------------------------------------------------------

def test_the_promotion_stops_itself_at_the_sales_cap():
    config = normalize_promotion_config({"active": True, "sales_cap": 1002})
    assert promotion_is_live(config, 1001) is True
    assert promotion_is_live(config, 1002) is False
    assert promotion_is_live(config, 1500) is False


def test_an_end_date_can_be_added_later_and_stops_the_promotion():
    now = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
    config = normalize_promotion_config({
        "active": True,
        "ends_at": (now + timedelta(hours=1)).isoformat(),
    })
    assert promotion_is_live(config, 0, now=now) is True
    assert promotion_is_live(config, 0, now=now + timedelta(hours=2)) is False


def test_no_end_date_means_the_promotion_keeps_running(db):
    _activate(db)
    assert get_promotion_config()["ends_at"] is None
    assert public_promotion_state()["active"] is True


def test_only_live_sales_count_against_the_cap(db):
    user = _make_user(db)
    grant_limited_time_300k_offer(user, 300000, payment_reference="pi_live_1")
    db.session.commit()
    assert limited_time_300k_sales_count() == 1

    grant = user.persistent_credit_grants[0] if hasattr(user, "persistent_credit_grants") else None
    if grant is None:
        from app.models import PersistentCreditGrant
        grant = PersistentCreditGrant.query.filter_by(user_id=str(user.id)).first()
    grant.status = "reversed"
    db.session.commit()

    assert limited_time_300k_sales_count() == 0


# --- Public payload ---------------------------------------------------------

def test_the_public_payload_shows_neither_a_date_nor_a_remaining_count(db):
    _activate(db)
    state = public_promotion_state()

    assert state["active"] is True
    assert state["campaign_path"] == "/limited-time/project-prioritization"
    assert state["deadline"] is None
    assert state["remaining"] is None
    # No sales figure of any kind reaches a visitor.
    assert "sales_count" not in state
    assert "sales_cap" not in state


def test_turning_on_the_display_switches_populates_the_fields_the_modal_reads(db):
    _activate(db, show_remaining=True, sales_cap=1002, ends_at="2026-12-01T00:00:00+00:00", show_deadline=True)
    state = public_promotion_state()

    assert state["remaining"] == 1002
    assert state["deadline"] == "2026-12-01T00:00:00+00:00"


def test_an_inactive_promotion_returns_no_targeting_details(db):
    state = public_promotion_state()
    assert state["active"] is False
    assert state["campaign_path"] is None
    assert state["frequency"] is None


def test_public_endpoint_serves_visitors_who_are_not_signed_in(client, db):
    _activate(db)
    response = client.get(PUBLIC_URL)

    assert response.status_code == 200
    promotion = response.get_json()["promotion"]
    assert promotion["active"] is True
    assert promotion["frequency"]["max_impressions"] == 3
    assert promotion["suppressed"] is False


def test_a_stale_or_garbage_token_is_treated_as_signed_out(client, db):
    _activate(db)
    response = client.get(PUBLIC_URL, headers={"Authorization": "Bearer not-a-real-token"})

    assert response.status_code == 200
    assert response.get_json()["promotion"]["active"] is True


# --- Suppression for buyers -------------------------------------------------

def test_a_buyer_is_suppressed_by_their_entitlement_not_by_their_browser(app, client, db):
    _activate(db)
    user = _make_user(db)
    headers = _headers(app, user)

    before = client.get(PUBLIC_URL, headers=headers).get_json()["promotion"]
    assert before["active"] is True

    grant_limited_time_300k_offer(user, 300000, payment_reference="pi_bought_1")
    db.session.commit()
    reset_promotion_cache()

    after = client.get(PUBLIC_URL, headers=headers).get_json()["promotion"]
    assert after["active"] is False
    assert after["suppressed"] is True
    assert after["suppression_reason"] == "purchased"


def test_suppression_is_per_user_not_global(app, client, db):
    _activate(db)
    buyer = _make_user(db, email="buyer@example.com")
    visitor = _make_user(db, email="visitor@example.com")
    grant_limited_time_300k_offer(buyer, 300000, payment_reference="pi_bought_2")
    db.session.commit()
    reset_promotion_cache()

    buyer_state = client.get(PUBLIC_URL, headers=_headers(app, buyer)).get_json()["promotion"]
    visitor_state = client.get(PUBLIC_URL, headers=_headers(app, visitor)).get_json()["promotion"]

    assert buyer_state["suppressed"] is True
    assert visitor_state["suppressed"] is False
    assert visitor_state["active"] is True


# --- Admin switch -----------------------------------------------------------

def test_admin_can_activate_and_end_the_promotion(client, db, admin_auth_headers):
    activate = client.patch(ADMIN_URL, json={"active": True}, headers=admin_auth_headers)
    assert activate.status_code == 200
    assert activate.get_json()["promotion"]["live"] is True
    assert client.get(PUBLIC_URL).get_json()["promotion"]["active"] is True

    end = client.patch(ADMIN_URL, json={"active": False}, headers=admin_auth_headers)
    assert end.status_code == 200
    assert end.get_json()["promotion"]["live"] is False
    # The modal disappears for visitors without waiting for a cache TTL.
    assert client.get(PUBLIC_URL).get_json()["promotion"]["active"] is False


def test_admin_can_extend_the_promotion_with_an_end_date(client, db, admin_auth_headers):
    ends_at = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    response = client.patch(ADMIN_URL, json={"active": True, "ends_at": ends_at}, headers=admin_auth_headers)

    assert response.status_code == 200
    assert response.get_json()["promotion"]["config"]["ends_at"] is not None
    # Still not shown to visitors, because the display switch stays off.
    assert client.get(PUBLIC_URL).get_json()["promotion"]["deadline"] is None


def test_admin_view_reports_the_sales_position(client, db, admin_auth_headers):
    user = _make_user(db)
    grant_limited_time_300k_offer(user, 300000, payment_reference="pi_admin_view")
    db.session.commit()

    view = client.get(ADMIN_URL, headers=admin_auth_headers).get_json()["promotion"]
    assert view["sales_count"] == 1
    assert view["sales_remaining"] == DEFAULT_SALES_CAP - 1
    assert view["allowed_campaign_paths"][0] == "/limited-time/project-prioritization"


def test_the_promotion_switch_is_admin_only(client, db, auth_headers):
    assert client.get(ADMIN_URL, headers=auth_headers).status_code in (401, 403)
    assert client.patch(ADMIN_URL, json={"active": True}, headers=auth_headers).status_code in (401, 403)
    assert client.get(ADMIN_URL).status_code == 401


def test_an_admin_change_is_audited(client, db, admin_auth_headers):
    from app.models import AdminAuditEvent

    client.patch(ADMIN_URL, json={"active": True}, headers=admin_auth_headers)

    event = AdminAuditEvent.query.filter_by(action="homepage_promotion.patch").first()
    assert event is not None
    assert event.details["before"]["active"] is False
    assert event.details["after"]["active"] is True


def test_a_promotion_that_hit_the_cap_is_off_for_visitors_while_still_switched_on(client, db, admin_auth_headers):
    client.patch(ADMIN_URL, json={"active": True, "sales_cap": 1}, headers=admin_auth_headers)
    user = _make_user(db)
    grant_limited_time_300k_offer(user, 300000, payment_reference="pi_cap_1")
    db.session.commit()
    reset_promotion_cache()

    assert client.get(PUBLIC_URL).get_json()["promotion"]["active"] is False
    admin_view = client.get(ADMIN_URL, headers=admin_auth_headers).get_json()["promotion"]
    assert admin_view["config"]["active"] is True
    assert admin_view["live"] is False
