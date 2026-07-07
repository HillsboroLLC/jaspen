import os
import importlib

import pytest
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from app import connector_store
from app import create_app, db as _db
from app.models import (
    AdminAuditEvent,
    AppSetting,
    ConnectorSyncLog,
    Organization,
    OrganizationInvitation,
    OrganizationMember,
    SavedStarter,
    User,
    UserDataset,
    UserSession,
)


@pytest.fixture(scope="session")
def app(tmp_path_factory):
    db_file = tmp_path_factory.mktemp("db") / "test.sqlite"
    connectors_dir = tmp_path_factory.mktemp("connectors")
    original_connectors_dir = connector_store.CONNECTORS_DIR
    original_env = {key: os.environ.get(key) for key in (
        "DATABASE_URL",
        "JWT_SECRET_KEY",
        "SECRET_KEY",
        "STRIPE_SECRET_KEY",
        "FRONTEND_BASE_URL",
        "ADMIN_EMAILS",
        "ENABLE_FLASK_CORS",
        "REQUIRE_EMAIL_VERIFICATION",
    )}

    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["JWT_SECRET_KEY"] = "test-secret-key"
    os.environ["SECRET_KEY"] = "test-secret"
    os.environ["STRIPE_SECRET_KEY"] = "sk_test_123"
    os.environ["FRONTEND_BASE_URL"] = "http://localhost:3000"
    os.environ["ADMIN_EMAILS"] = "support@jaspen.ai"
    os.environ["ENABLE_FLASK_CORS"] = "false"
    os.environ["REQUIRE_EMAIL_VERIFICATION"] = "false"

    app = create_app()
    app.config.update(
        TESTING=True,
        JWT_COOKIE_CSRF_PROTECT=False,
        RATELIMIT_ENABLED=False,
    )
    connector_store.CONNECTORS_DIR = str(connectors_dir)
    auth_routes = importlib.import_module("app.routes.auth")
    original_generate_password_hash = auth_routes.generate_password_hash
    auth_routes.generate_password_hash = lambda password, salt_length=16: generate_password_hash(
        password,
        method="pbkdf2:sha256",
        salt_length=salt_length,
    )

    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()

    auth_routes.generate_password_hash = original_generate_password_hash
    connector_store.CONNECTORS_DIR = original_connectors_dir
    for key, value in original_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    with app.app_context():
        for model in (
            AdminAuditEvent,
            AppSetting,
            ConnectorSyncLog,
            OrganizationInvitation,
            OrganizationMember,
            Organization,
            SavedStarter,
            UserDataset,
            UserSession,
            User,
        ):
            _db.session.query(model).delete()
        _db.session.commit()
        yield _db
        _db.session.rollback()


@pytest.fixture
def test_user(db):
    user = User(
        email="test@example.com",
        name="Test User",
        password_hash=generate_password_hash("ValidPass1", method="pbkdf2:sha256"),
        subscription_plan="free",
        credits_remaining=300,
        seat_limit=1,
        max_seats=1,
    )
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def admin_user(db):
    user = User(
        email="support@jaspen.ai",
        name="Admin User",
        password_hash=generate_password_hash("ValidPass1", method="pbkdf2:sha256"),
        subscription_plan="enterprise",
        credits_remaining=None,
        seat_limit=1,
        max_seats=1,
        stripe_customer_id="cus_test_hidden",
        stripe_subscription_id="sub_test_hidden",
    )
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def auth_headers(app, test_user):
    with app.app_context():
        token = create_access_token(identity=str(test_user.id))
        return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_auth_headers(app, admin_user):
    with app.app_context():
        token = create_access_token(identity=str(admin_user.id))
        return {"Authorization": f"Bearer {token}"}
