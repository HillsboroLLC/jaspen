"""Staging only: the verification link is returned instead of emailed."""

import pytest

from app.models import User


@pytest.fixture
def verification_on(app):
    original = app.config.get("REQUIRE_EMAIL_VERIFICATION")
    app.config["REQUIRE_EMAIL_VERIFICATION"] = True
    yield
    app.config["REQUIRE_EMAIL_VERIFICATION"] = original


def _signup(client, email, ip):
    return client.post("/api/v1/auth/signup", json={
        "name": "Staging User", "email": email, "password": "StrongPass1", "plan_key": "free"},
        environ_overrides={"REMOTE_ADDR": ip})


def test_staging_returns_a_working_link_and_sends_no_email(client, db, verification_on, monkeypatch):
    sent = []
    monkeypatch.setattr("app.routes.auth._send_email_verification_email", lambda *a, **k: sent.append(a))
    monkeypatch.setenv("STAGING_EMAIL_VERIFICATION_LINKS", "true")
    monkeypatch.setenv("APP_ENV", "staging")
    resp = _signup(client, "link@example.com", "10.0.0.201")
    assert resp.status_code == 202
    url = resp.get_json()["staging_verification_url"]
    assert "/api/v1/auth/verify-email?token=" in url and sent == []
    path = url.split("://", 1)[1].split("/", 1)[1]
    assert client.get("/" + path).status_code == 302
    assert User.query.filter_by(email="link@example.com").one().email_verified is True


def test_an_unverified_sign_in_on_staging_returns_the_link(client, db, verification_on, monkeypatch):
    monkeypatch.setattr("app.routes.auth._send_email_verification_email", lambda *a, **k: None)
    monkeypatch.setenv("STAGING_EMAIL_VERIFICATION_LINKS", "true")
    monkeypatch.setenv("APP_ENV", "staging")
    _signup(client, "later@example.com", "10.0.0.202")
    resp = client.post("/api/v1/auth/login", json={"email": "later@example.com", "password": "StrongPass1"},
                       environ_overrides={"REMOTE_ADDR": "10.0.0.202"})
    assert resp.status_code == 403 and resp.get_json()["staging_verification_url"]


@pytest.mark.parametrize("env", [{"APP_ENV": "production"}, {"APP_ENV": "staging", "STAGING_EMAIL_VERIFICATION_LINKS": ""}])
def test_no_link_in_production_or_by_default(client, db, verification_on, monkeypatch, env):
    monkeypatch.setattr("app.routes.auth._send_email_verification_email", lambda *a, **k: None)
    monkeypatch.setenv("STAGING_EMAIL_VERIFICATION_LINKS", "true")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    resp = _signup(client, f"none-{env['APP_ENV']}@example.com", "10.0.0.203")
    assert resp.status_code == 202 and "staging_verification_url" not in resp.get_json()
