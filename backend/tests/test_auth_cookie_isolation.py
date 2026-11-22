"""Auth cookie names: production keeps its defaults; staging uses its own for every auth cookie."""
import importlib

from app import DEFAULT_JWT_ACCESS_CSRF_COOKIE_NAME, _jwt_access_csrf_cookie_name

STAGING_CSRF = "staging_csrf_access_token"


def _enable_csrf(app, monkeypatch):
    # The shared test app turns CSRF off; production and staging run with it on.
    monkeypatch.setitem(app.config, "JWT_COOKIE_CSRF_PROTECT", True)


def _login(client):
    return client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "ValidPass1"},
    )


def test_production_default_name_is_unchanged(monkeypatch):
    monkeypatch.delenv("JWT_ACCESS_CSRF_COOKIE_NAME", raising=False)
    assert _jwt_access_csrf_cookie_name() == "csrf_access_token"
    monkeypatch.setenv("JWT_ACCESS_CSRF_COOKIE_NAME", "   ")
    assert _jwt_access_csrf_cookie_name() == "csrf_access_token"
    assert DEFAULT_JWT_ACCESS_CSRF_COOKIE_NAME == "csrf_access_token"


def test_staging_name_comes_from_environment(monkeypatch):
    monkeypatch.setenv("JWT_ACCESS_CSRF_COOKIE_NAME", f" {STAGING_CSRF} ")
    assert _jwt_access_csrf_cookie_name() == STAGING_CSRF


def test_default_config_sets_production_csrf_cookie(client, app, test_user, monkeypatch):
    _enable_csrf(app, monkeypatch)
    assert app.config["JWT_ACCESS_CSRF_COOKIE_NAME"] == "csrf_access_token"
    resp = _login(client)
    assert resp.status_code == 200
    assert client.get_cookie("csrf_access_token") is not None
    assert client.get_cookie(STAGING_CSRF) is None


def test_staging_config_sets_only_staging_csrf_cookie(client, app, test_user, monkeypatch):
    _enable_csrf(app, monkeypatch)
    monkeypatch.setitem(app.config, "JWT_ACCESS_CSRF_COOKIE_NAME", STAGING_CSRF)
    monkeypatch.setitem(app.config, "JWT_ACCESS_COOKIE_NAME", "jaspen_staging_access")
    resp = _login(client)
    assert resp.status_code == 200
    assert client.get_cookie(STAGING_CSRF) is not None
    assert client.get_cookie("csrf_access_token") is None
    assert client.get_cookie("jaspen_staging_access") is not None


def test_staging_cookie_requests_need_staging_csrf_token(client, app, test_user, monkeypatch):
    _enable_csrf(app, monkeypatch)
    monkeypatch.setitem(app.config, "JWT_ACCESS_CSRF_COOKIE_NAME", STAGING_CSRF)
    monkeypatch.setitem(app.config, "JWT_ACCESS_COOKIE_NAME", "jaspen_staging_access")
    assert _login(client).status_code == 200
    staging_token = client.get_cookie(STAGING_CSRF).value

    # A cookie-authenticated write without the matching CSRF header is refused.
    refused = client.patch("/api/v1/auth/me", json={"name": "Staging Tester"})
    assert refused.status_code in (401, 422)
    # A different (e.g. production) CSRF value is refused too.
    wrong = client.patch("/api/v1/auth/me", json={"name": "Staging Tester"}, headers={"X-CSRF-TOKEN": "production-token"})
    assert wrong.status_code in (401, 422)
    accepted = client.patch("/api/v1/auth/me", json={"name": "Staging Tester"}, headers={"X-CSRF-TOKEN": staging_token})
    assert accepted.status_code == 200


# --- every auth cookie, not only CSRF -------------------------------------

from flask import Response  # noqa: E402

from app import _cookie_name_from_env  # noqa: E402

STAGING_COOKIES = {
    "JWT_ACCESS_COOKIE_NAME": "jaspen_staging_access",
    "JWT_ACCESS_CSRF_COOKIE_NAME": STAGING_CSRF,
    "GOOGLE_MFA_PENDING_COOKIE_NAME": "jaspen_staging_mfa_pending",
    "SSO_STATE_COOKIE_NAME": "jaspen_staging_sso_state",
}


def _use_staging_cookies(app, monkeypatch):
    for key, value in STAGING_COOKIES.items():
        monkeypatch.setitem(app.config, key, value)


def test_production_keeps_every_existing_cookie_name(app):
    assert app.config["JWT_ACCESS_COOKIE_NAME"] == "jaspen_access"
    assert app.config["JWT_ACCESS_CSRF_COOKIE_NAME"] == "csrf_access_token"
    assert app.config["GOOGLE_MFA_PENDING_COOKIE_NAME"] == "jaspen_mfa_pending"
    assert app.config["SSO_STATE_COOKIE_NAME"] == "jaspen_sso_state"


def test_cookie_names_come_from_environment(monkeypatch):
    monkeypatch.setenv("SSO_STATE_COOKIE_NAME", " jaspen_staging_sso_state ")
    assert _cookie_name_from_env("SSO_STATE_COOKIE_NAME", "jaspen_sso_state") == "jaspen_staging_sso_state"
    monkeypatch.delenv("SSO_STATE_COOKIE_NAME")
    assert _cookie_name_from_env("SSO_STATE_COOKIE_NAME", "jaspen_sso_state") == "jaspen_sso_state"


def test_cookie_readers_use_configured_access_cookie(client, app, test_user, monkeypatch):
    _use_staging_cookies(app, monkeypatch)
    assert _login(client).status_code == 200
    assert client.get("/api/v1/auth/me-cookie").status_code == 200


def test_staging_ignores_production_access_cookie(client, app, test_user, monkeypatch):
    # Production's cookie is sent to api-staging on a shared .jaspen.ai domain;
    # staging must not read it, even when it carries a valid-looking token.
    assert _login(client).status_code == 200
    production_token = client.get_cookie("jaspen_access").value
    client.delete_cookie("jaspen_access")
    _use_staging_cookies(app, monkeypatch)
    client.set_cookie("jaspen_access", production_token)
    resp = client.get("/api/v1/auth/me-cookie")
    assert resp.status_code == 401
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_mfa_and_sso_cookie_helpers_follow_config(app, monkeypatch):
    auth_routes = importlib.import_module("app.routes.auth")
    with app.test_request_context():
        assert auth_routes._mfa_pending_cookie_name() == "jaspen_mfa_pending"
        assert auth_routes._sso_state_cookie_name() == "jaspen_sso_state"
        assert auth_routes._access_cookie_name() == "jaspen_access"
        _use_staging_cookies(app, monkeypatch)
        assert auth_routes._mfa_pending_cookie_name() == "jaspen_staging_mfa_pending"
        assert auth_routes._sso_state_cookie_name() == "jaspen_staging_sso_state"
        assert auth_routes._access_cookie_name() == "jaspen_staging_access"
        cleared = auth_routes._clear_sso_state_cookie(Response())
        header = " ".join(cleared.headers.getlist("Set-Cookie"))
        assert "jaspen_staging_sso_state=" in header
        assert "jaspen_sso_state=" not in header.replace("jaspen_staging_sso_state=", "")


def test_staging_logout_clears_only_staging_cookies(client, app, test_user, monkeypatch):
    _enable_csrf(app, monkeypatch)
    _use_staging_cookies(app, monkeypatch)
    assert _login(client).status_code == 200
    token = client.get_cookie(STAGING_CSRF).value
    resp = client.post("/api/v1/auth/logout", headers={"X-CSRF-TOKEN": token})
    assert resp.status_code == 200
    cleared = " ".join(resp.headers.getlist("Set-Cookie"))
    assert "jaspen_staging_access=" in cleared
    assert f"{STAGING_CSRF}=" in cleared
    for production_name in ("jaspen_access=", "csrf_access_token="):
        assert production_name not in cleared.replace("jaspen_staging_access=", "").replace(f"{STAGING_CSRF}=", "")
