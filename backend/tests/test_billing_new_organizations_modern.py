"""Staging: with every modern billing family on, a new organization starts modern."""

from app.billing_cutover import FAMILIES, organization_billing_model
from app.models import User


ALL = ",".join(FAMILIES)


def _signup(client, email):
    resp = client.post("/api/v1/auth/signup", json={
        "name": "New User", "email": email, "password": "StrongPass1", "plan_key": "free"})
    assert resp.status_code == 201, resp.get_json()
    return User.query.filter_by(email=email).one()


def test_a_new_signup_starts_on_the_modern_model_when_every_family_is_on(client, db, monkeypatch):
    monkeypatch.setenv("BILLING_MODERN_FAMILIES", ALL)
    user = _signup(client, "modern-signup@example.com")
    assert user.active_organization_id
    assert organization_billing_model(db.session, user.active_organization_id) == "modern"


def test_a_new_signup_stays_legacy_while_any_family_is_off(client, db, monkeypatch):
    monkeypatch.setenv("BILLING_MODERN_FAMILIES", ",".join(FAMILIES[:-1]))
    user = _signup(client, "partial-signup@example.com")
    assert organization_billing_model(db.session, user.active_organization_id) == "legacy"


def test_a_new_signup_stays_legacy_with_the_switches_unset(client, db, monkeypatch):
    monkeypatch.delenv("BILLING_MODERN_FAMILIES", raising=False)
    user = _signup(client, "default-signup@example.com")
    assert organization_billing_model(db.session, user.active_organization_id) == "legacy"


def test_a_user_with_legacy_credits_keeps_a_legacy_organization_and_nothing_is_claimed(db, monkeypatch):
    from werkzeug.security import generate_password_hash
    from app.models_billing_identity import BillingModelAssignment
    from app.orgs import ensure_default_organization_for_user

    monkeypatch.setenv("BILLING_MODERN_FAMILIES", ALL)
    user = User(email="legacy-credits@example.com", name="Legacy",
                password_hash=generate_password_hash("ValidPass1", method="pbkdf2:sha256"),
                subscription_plan="free", credits_remaining=1_000_000, seat_limit=1, max_seats=1)
    db.session.add(user)
    db.session.commit()
    org, _membership, _changed = ensure_default_organization_for_user(user)
    db.session.commit()
    assert organization_billing_model(db.session, org.id) == "legacy"
    assert db.session.query(BillingModelAssignment).count() == 0
