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
