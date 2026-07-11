from datetime import datetime
from itsdangerous import URLSafeTimedSerializer
from werkzeug.security import generate_password_hash

from app.models import User


def test_signup_success(client):
    resp = client.post(
        "/api/v1/auth/signup",
        json={
            "name": "New User",
            "email": "new@example.com",
            "password": "StrongPass1",
            "plan_key": "free",
        },
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert "token" in data
    assert data["user"]["email_verified"] is False
    assert data["user"]["referral_code"]


def test_signup_weak_password(client):
    resp = client.post(
        "/api/v1/auth/signup",
        json={
            "name": "New User",
            "email": "weak@example.com",
            "password": "abc",
            "plan_key": "free",
        },
    )
    assert resp.status_code == 400


def test_signup_invalid_email(client):
    resp = client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Bad Email",
            "email": "notanemail",
            "password": "StrongPass1",
            "plan_key": "free",
        },
    )
    assert resp.status_code == 400


def test_login_success(client, test_user):
    resp = client.post(
        "/api/v1/auth/login",
        json={
            "email": "test@example.com",
            "password": "ValidPass1",
        },
    )
    assert resp.status_code == 200
    assert "token" in resp.get_json()


def test_login_wrong_password(client, test_user):
    resp = client.post(
        "/api/v1/auth/login",
        json={
            "email": "test@example.com",
            "password": "WrongPass1",
        },
    )
    assert resp.status_code == 401


def test_login_lockout(client, test_user):
    for _ in range(5):
        client.post(
            "/api/v1/auth/login",
            json={
                "email": "test@example.com",
                "password": "WrongPass1",
            },
        )

    resp = client.post(
        "/api/v1/auth/login",
        json={
            "email": "test@example.com",
            "password": "ValidPass1",
        },
    )
    assert resp.status_code == 429


def test_signup_records_referral_attribution(client, db, test_user):
    resp = client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Referred User",
            "email": "referred@example.com",
            "password": "StrongPass1",
            "plan_key": "free",
            "referral_code": test_user.referral_code,
        },
    )

    assert resp.status_code == 201
    created = User.query.filter_by(email="referred@example.com").first()
    referrer = User.query.get(test_user.id)
    assert created is not None
    assert created.referred_by_user_id == test_user.id
    assert created.signup_referral_code_used == test_user.referral_code
    assert referrer.referrals_earned == 1


def test_signup_blocks_when_open_signup_disabled_without_invite(client, app):
    original = app.config.get("OPEN_SIGNUP")
    app.config["OPEN_SIGNUP"] = False
    try:
        resp = client.post(
            "/api/v1/auth/signup",
            json={
                "name": "Blocked User",
                "email": "blocked@example.com",
                "password": "StrongPass1",
                "plan_key": "free",
            },
            environ_overrides={"REMOTE_ADDR": "10.0.0.110"},
        )
    finally:
        app.config["OPEN_SIGNUP"] = original

    assert resp.status_code == 403
    assert resp.get_json()["signup_closed"] is True


def test_signup_allows_valid_invite_when_open_signup_disabled(client, app, db, test_user):
    original = app.config.get("OPEN_SIGNUP")
    app.config["OPEN_SIGNUP"] = False
    try:
        resp = client.post(
            "/api/v1/auth/signup",
            json={
                "name": "Invited User",
                "email": "invited@example.com",
                "password": "StrongPass1",
                "plan_key": "free",
                "referral_code": test_user.referral_code,
            },
            environ_overrides={"REMOTE_ADDR": "10.0.0.111"},
        )
    finally:
        app.config["OPEN_SIGNUP"] = original

    assert resp.status_code == 201
    created = User.query.filter_by(email="invited@example.com").first()
    assert created is not None
    assert created.access_approval_status == "approved"


def test_signup_returns_pending_when_admin_approval_required(client, app, db):
    original = app.config.get("REQUIRE_ADMIN_APPROVAL")
    app.config["REQUIRE_ADMIN_APPROVAL"] = True
    try:
        resp = client.post(
            "/api/v1/auth/signup",
            json={
                "name": "Pending User",
                "email": "pending@example.com",
                "password": "StrongPass1",
                "plan_key": "free",
            },
            environ_overrides={"REMOTE_ADDR": "10.0.0.112"},
        )
    finally:
        app.config["REQUIRE_ADMIN_APPROVAL"] = original

    assert resp.status_code == 202
    data = resp.get_json()
    assert data["approval_required"] is True
    assert data["approval_status"] == "pending"
    created = User.query.filter_by(email="pending@example.com").first()
    assert created is not None
    assert created.access_approval_status == "pending"


def test_paid_plan_request_signs_up_free_before_upgrade(client, app, monkeypatch):
    def fake_send_verification(user, url_root=None, *, pending_plan=None):
        return None

    original = app.config.get("REQUIRE_EMAIL_VERIFICATION")
    app.config["REQUIRE_EMAIL_VERIFICATION"] = True
    monkeypatch.setattr("app.routes.auth._send_email_verification_email", fake_send_verification)
    try:
        resp = client.post(
            "/api/v1/auth/signup",
            json={
                "name": "Paid User",
                "email": "paid@example.com",
                "password": "StrongPass1",
                "plan_key": "essential",
            },
            environ_overrides={"REMOTE_ADDR": "10.0.0.113"},
        )
    finally:
        app.config["REQUIRE_EMAIL_VERIFICATION"] = original

    assert resp.status_code == 202
    data = resp.get_json()
    assert data["verification_required"] is True
    assert data["payment_pending"] is False
    assert data["plan_key"] == "free"
    created = User.query.filter_by(email="paid@example.com").first()
    assert created.subscription_plan == "free"


def test_login_blocks_pending_user_when_admin_approval_required(client, app, db):
    with app.app_context():
        pending_user = User(
            email="pending-login@example.com",
            name="Pending Login",
            password_hash=generate_password_hash("ValidPass1", method="pbkdf2:sha256"),
            subscription_plan="free",
            credits_remaining=300,
            seat_limit=1,
            max_seats=1,
            access_approval_status="pending",
        )
        db.session.add(pending_user)
        db.session.commit()
    original = app.config.get("REQUIRE_ADMIN_APPROVAL")
    app.config["REQUIRE_ADMIN_APPROVAL"] = True
    try:
        resp = client.post(
            "/api/v1/auth/login",
            json={
                "email": "pending-login@example.com",
                "password": "ValidPass1",
            },
            environ_overrides={"REMOTE_ADDR": "10.0.0.113"},
        )
    finally:
        app.config["REQUIRE_ADMIN_APPROVAL"] = original

    assert resp.status_code == 403
    data = resp.get_json()
    assert data["approval_required"] is True
    assert data["approval_status"] == "pending"


def test_login_blocks_rejected_user(client, app, db):
    with app.app_context():
        rejected_user = User(
            email="rejected@example.com",
            name="Rejected User",
            password_hash=generate_password_hash("ValidPass1", method="pbkdf2:sha256"),
            subscription_plan="free",
            credits_remaining=300,
            seat_limit=1,
            max_seats=1,
            access_approval_status="rejected",
        )
        db.session.add(rejected_user)
        db.session.commit()

    resp = client.post(
        "/api/v1/auth/login",
        json={
            "email": "rejected@example.com",
            "password": "ValidPass1",
        },
        environ_overrides={"REMOTE_ADDR": "10.0.0.114"},
    )

    assert resp.status_code == 403
    data = resp.get_json()
    assert data["approval_required"] is True
    assert data["approval_status"] == "rejected"


def test_login_blocks_deactivated_user(client, app, db):
    with app.app_context():
        deactivated_user = User(
            email="deactivated@example.com",
            name="Deactivated User",
            password_hash=generate_password_hash("ValidPass1", method="pbkdf2:sha256"),
            subscription_plan="free",
            credits_remaining=300,
            seat_limit=1,
            max_seats=1,
            deactivated_at=datetime.utcnow(),
        )
        db.session.add(deactivated_user)
        db.session.commit()

    resp = client.post(
        "/api/v1/auth/login",
        json={
            "email": "deactivated@example.com",
            "password": "ValidPass1",
        },
        environ_overrides={"REMOTE_ADDR": "10.0.0.115"},
    )

    assert resp.status_code == 403
    assert resp.get_json()["account_deactivated"] is True


def test_verify_email_marks_user_verified(client, app, test_user, db):
    with app.app_context():
        serializer = URLSafeTimedSerializer(
            secret_key=app.config["SECRET_KEY"] or app.config["JWT_SECRET_KEY"],
            salt="email-verification",
        )
        token = serializer.dumps({
            "user_id": str(test_user.id),
            "email": str(test_user.email).lower(),
        })

    resp = client.post(
        "/api/v1/auth/verify-email",
        json={"token": token},
    )

    assert resp.status_code == 200
    db.session.refresh(test_user)
    assert test_user.email_verified is True
    assert test_user.email_verified_at is not None


def test_verify_email_ignores_legacy_paid_pending_plan(client, app, test_user, db):
    with app.app_context():
        serializer = URLSafeTimedSerializer(
            secret_key=app.config["SECRET_KEY"] or app.config["JWT_SECRET_KEY"],
            salt="email-verification",
        )
        token = serializer.dumps({
            "user_id": str(test_user.id),
            "email": str(test_user.email).lower(),
            "pending_plan": "essential",
        })

    resp = client.get(f"/api/v1/auth/verify-email?token={token}")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "http://localhost:3000/?auth=1&verified=1"
    db.session.refresh(test_user)
    assert test_user.email_verified is True


def test_forgot_password_sends_reset_email_for_existing_user(client, app, test_user, db, monkeypatch):
    sent_messages = []

    def fake_send(msg):
        sent_messages.append(msg)

    monkeypatch.setattr("app.routes.auth.mail.send", fake_send)

    resp = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "test@example.com"},
    )

    assert resp.status_code == 200
    assert "If that account exists" in resp.get_json()["message"]
    assert len(sent_messages) == 1
    assert sent_messages[0].subject == "Reset your Jaspen password"
    assert "/reset-password?token=" in (sent_messages[0].body or "")
    db.session.refresh(test_user)
    assert test_user.password_reset_requested_at is not None


def test_forgot_password_is_neutral_for_unknown_user(client, monkeypatch):
    sent_messages = []

    def fake_send(msg):
        sent_messages.append(msg)

    monkeypatch.setattr("app.routes.auth.mail.send", fake_send)

    resp = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "missing@example.com"},
    )

    assert resp.status_code == 200
    assert "If that account exists" in resp.get_json()["message"]
    assert sent_messages == []


def test_reset_password_updates_password_and_invalidates_old_sessions(app, client, test_user, db, auth_headers):
    with app.app_context():
        serializer = URLSafeTimedSerializer(
            secret_key=app.config["SECRET_KEY"] or app.config["JWT_SECRET_KEY"],
            salt="password-reset",
        )
        token = serializer.dumps({
            "user_id": str(test_user.id),
            "email": str(test_user.email).lower(),
            "reset_version": int(test_user.password_reset_version or 0),
        })

    resp = client.post(
        "/api/v1/auth/reset-password",
        json={
            "token": token,
            "new_password": "ResetPass2",
        },
    )

    assert resp.status_code == 200
    db.session.refresh(test_user)
    assert test_user.auth_token_version == 1
    assert test_user.password_reset_version == 1

    stale_client = app.test_client(use_cookies=False)
    stale_resp = stale_client.get(
        "/api/v1/auth/me",
        headers=auth_headers,
    )
    assert stale_resp.status_code == 401

    fresh_login_client = app.test_client(use_cookies=False)
    login_resp = fresh_login_client.post(
        "/api/v1/auth/login",
        json={
            "email": "test@example.com",
            "password": "ResetPass2",
        },
        environ_overrides={"REMOTE_ADDR": "10.0.0.210"},
    )
    assert login_resp.status_code == 200


def test_reset_password_rejects_reused_token(client, app, test_user):
    with app.app_context():
        serializer = URLSafeTimedSerializer(
            secret_key=app.config["SECRET_KEY"] or app.config["JWT_SECRET_KEY"],
            salt="password-reset",
        )
        token = serializer.dumps({
            "user_id": str(test_user.id),
            "email": str(test_user.email).lower(),
            "reset_version": int(test_user.password_reset_version or 0),
        })

    first = client.post(
        "/api/v1/auth/reset-password",
        json={
            "token": token,
            "new_password": "ResetPass2",
        },
    )
    assert first.status_code == 200

    second = client.post(
        "/api/v1/auth/reset-password",
        json={
            "token": token,
            "new_password": "AnotherPass3",
        },
    )
    assert second.status_code == 400
    assert "invalid" in second.get_json()["message"].lower()


def test_login_requires_verified_email_when_flag_enabled(client, app, db):
    with app.app_context():
        gated_user = User(
            email="gated@example.com",
            name="Gated User",
            password_hash=generate_password_hash("ValidPass1", method="pbkdf2:sha256"),
            subscription_plan="free",
            credits_remaining=300,
            seat_limit=1,
            max_seats=1,
            email_verified=False,
        )
        db.session.add(gated_user)
        db.session.commit()
    original = app.config.get("REQUIRE_EMAIL_VERIFICATION")
    app.config["REQUIRE_EMAIL_VERIFICATION"] = True
    try:
        resp = client.post(
            "/api/v1/auth/login",
            json={
                "email": "gated@example.com",
                "password": "ValidPass1",
            },
            environ_overrides={"REMOTE_ADDR": "10.0.0.99"},
        )
    finally:
        app.config["REQUIRE_EMAIL_VERIFICATION"] = original

    assert resp.status_code == 403
    assert resp.get_json()["verification_required"] is True


def test_password_change_invalidates_old_sessions(app, auth_headers, test_user):
    changing_client = app.test_client(use_cookies=False)
    change_resp = changing_client.post(
        "/api/v1/auth/password/change",
        json={
            "current_password": "ValidPass1",
            "new_password": "BetterPass2",
        },
        headers=auth_headers,
    )

    assert change_resp.status_code == 200
    new_token = change_resp.get_json()["token"]
    assert new_token

    stale_client = app.test_client(use_cookies=False)
    stale_resp = stale_client.get(
        "/api/v1/auth/me",
        headers=auth_headers,
    )
    assert stale_resp.status_code == 401

    fresh_client = app.test_client(use_cookies=False)
    fresh_resp = fresh_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {new_token}"},
    )
    assert fresh_resp.status_code == 200
