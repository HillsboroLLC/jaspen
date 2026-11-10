import os
import importlib
import uuid

import pytest
from flask_jwt_extended import create_access_token
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from werkzeug.security import generate_password_hash

from app import connector_store
from app import create_app, db as _db
from app.models import (
    AdminAuditEvent,
    AdvisoryInquiry,
    AppSetting,
    AccountEntitlement,
    AIOperation,
    AIProviderAttempt,
    BillingAccount,
    BillingRoleGrant,
    ConnectorSyncLog,
    DecisionAssetEmail,
    DecisionShare,
    EmailSuppression,
    EnterpriseInquiry,
    Lead,
    LeadAttributionEvent,
    LeadDecisionProfile,
    LeadDecisionProfileResponse,
    LeadEmailDelivery,
    Organization,
    OrganizationInvitation,
    OrganizationMember,
    Payment,
    PersistentCreditGrant,
    PersistentCreditTransaction,
    OrgIdeaLedger,
    SavedStarter,
    SsoIdentity,
    SsoLoginState,
    Scorecard,
    UsageEvent,
    User,
    UserAuthSession,
    UserDataset,
    UserSession,
)
from app.models_pm_sync import PmSyncBinding, PmSyncLink


_ALLOWED_TEST_DATABASE_HOSTS = {"localhost", "127.0.0.1", "postgres"}


def _validated_test_database_url(value):
    """Return a safe Postgres test URL or fail before the app can connect."""
    try:
        url = make_url(value)
    except Exception as exc:
        raise pytest.UsageError("TEST_DATABASE_URL is not a valid database URL") from exc
    if not url.drivername.startswith("postgresql"):
        raise pytest.UsageError("TEST_DATABASE_URL must use PostgreSQL")
    if url.host not in _ALLOWED_TEST_DATABASE_HOSTS:
        raise pytest.UsageError(
            "TEST_DATABASE_URL host must be localhost, 127.0.0.1, or postgres"
        )
    if "test" not in str(url.database or "").lower():
        raise pytest.UsageError("TEST_DATABASE_URL database name must contain 'test'")
    return url


def _postgres_schema_url(base_url, schema):
    query = dict(base_url.query)
    query["options"] = f"-csearch_path={schema}"
    return base_url.set(query=query)


@pytest.fixture
def validate_test_database_url():
    return _validated_test_database_url


@pytest.fixture
def postgres_schema_url():
    return _postgres_schema_url


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "postgres: requires the local PostgreSQL test database configured by TEST_DATABASE_URL",
    )
    test_database_url = os.environ.get("TEST_DATABASE_URL")
    if test_database_url:
        _validated_test_database_url(test_database_url)


def pytest_collection_modifyitems(config, items):
    """Keep deliberately SQLite-specific coverage out of the Postgres job."""
    if not os.environ.get("TEST_DATABASE_URL"):
        return
    sqlite_only_files = {
        "tests/test_fresh_dev_baseline.py": (
            "exercises the SQLite-only fresh local database initializer"
        ),
        "tests/test_migrations_alembic.py": (
            "exercises historical migration branches against handcrafted SQLite schemas"
        ),
    }
    sqlite_only_tests = {
        "tests/test_org_access_gate.py::test_migration_backfills_existing_links_without_changing_them": (
            "binds a migration to a handcrafted SQLite database"
        ),
    }
    for item in items:
        reason = sqlite_only_tests.get(item.nodeid)
        if reason is None:
            for path, file_reason in sqlite_only_files.items():
                if item.nodeid.startswith(f"{path}::"):
                    reason = file_reason
                    break
        if reason is not None:
            item.add_marker(pytest.mark.skip(reason=f"SQLite-only: {reason}"))


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
        "RATELIMIT_STORAGE_URI",
        "APP_ENV",
        "ENV",
        "FLASK_ENV",
        "DECISION_IMPACT_NARRATIVE",
        "ANTHROPIC_API_KEY",
        "CLAUDE_API_KEY",
        "GEMINI_API_KEY",
        "SSO_ENABLED",
        "WORKOS_CLIENT_ID",
        "WORKOS_API_KEY",
    )}

    test_database_url = os.environ.get("TEST_DATABASE_URL")
    postgres_base_url = None
    postgres_admin_engine = None
    postgres_schema = None
    if test_database_url:
        postgres_base_url = _validated_test_database_url(test_database_url)
        postgres_schema = f"jaspen_test_{uuid.uuid4().hex}"
        postgres_admin_engine = create_engine(postgres_base_url, isolation_level="AUTOCOMMIT")
        with postgres_admin_engine.connect() as connection:
            connection.execute(text(f'CREATE SCHEMA "{postgres_schema}"'))
        database_url = _postgres_schema_url(
            postgres_base_url, postgres_schema,
        ).render_as_string(hide_password=False)
    else:
        database_url = f"sqlite:///{db_file}"

    os.environ["DATABASE_URL"] = database_url
    os.environ["JWT_SECRET_KEY"] = "test-secret-key"
    os.environ["SECRET_KEY"] = "test-secret"
    os.environ["STRIPE_SECRET_KEY"] = "sk_test_123"
    os.environ["FRONTEND_BASE_URL"] = "http://localhost:3000"
    os.environ["ADMIN_EMAILS"] = "support@jaspen.ai"
    os.environ["ENABLE_FLASK_CORS"] = "false"
    os.environ["REQUIRE_EMAIL_VERIFICATION"] = "false"
    os.environ["RATELIMIT_STORAGE_URI"] = "memory://"
    os.environ["APP_ENV"] = "test"
    # The impact report's "What changed" paragraph calls a model when one is
    # configured. Tests must not reach the network, and the deterministic
    # template is the behaviour worth asserting anyway — the model path has its
    # own tests, with the call stubbed.
    os.environ["DECISION_IMPACT_NARRATIVE"] = "off"
    # Never let the test app inherit billable developer credentials from the
    # repository's local environment. Provider-adapter tests inject fakes.
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ.pop("CLAUDE_API_KEY", None)
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ.pop("SSO_ENABLED", None)
    os.environ.pop("WORKOS_CLIENT_ID", None)
    os.environ.pop("WORKOS_API_KEY", None)
    os.environ.pop("ENV", None)
    os.environ.pop("FLASK_ENV", None)

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
        if _db.engine.dialect.name != "postgresql":
            _db.drop_all()

    if postgres_admin_engine is not None:
        with postgres_admin_engine.connect() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{postgres_schema}" CASCADE'))
        postgres_admin_engine.dispose()

    auth_routes.generate_password_hash = original_generate_password_hash
    connector_store.CONNECTORS_DIR = original_connectors_dir
    for key, value in original_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture(autouse=True)
def _fresh_rate_limit_counters(app):
    """Give every test its own rate-limit budget.

    The app fixture sets RATELIMIT_ENABLED=False, but Flask-Limiter reads
    `enabled` during init_app() — which create_app() already called — so
    enforcement has always stayed on. Rather than turn it off (a few tests
    assert real 429s), clear the shared memory:// counters between tests so
    one test's requests can no longer exhaust the per-IP budget of a test
    that runs later in the session.
    """
    from app import limiter

    try:
        limiter.reset()
    except (NotImplementedError, AttributeError):
        pass
    yield


@pytest.fixture(autouse=True)
def _fresh_promotion_cache(app):
    """The homepage promotion caches its config in-process for 30s. Clear it
    around every test so seeding an AppSetting row is immediately visible."""
    from app.homepage_promotion import reset_promotion_cache

    reset_promotion_cache()
    yield
    reset_promotion_cache()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    with app.app_context():
        from app.models_decision_record import DecisionRecord, DecisionSignal, OptionDecision

        for model in (
            PmSyncLink,
            PmSyncBinding,
            DecisionSignal,
            OptionDecision,
            DecisionRecord,
            AIProviderAttempt,
            AIOperation,
            OrgIdeaLedger,
            AdminAuditEvent,
            AppSetting,
            ConnectorSyncLog,
            DecisionAssetEmail,
            DecisionShare,
            LeadDecisionProfileResponse,
            LeadDecisionProfile,
            LeadEmailDelivery,
            LeadAttributionEvent,
            EmailSuppression,
            AdvisoryInquiry,
            EnterpriseInquiry,
            Lead,
            OrganizationInvitation,
            SsoIdentity,
            SsoLoginState,
            BillingRoleGrant,
            BillingAccount,
            OrganizationMember,
            Organization,
            SavedStarter,
            Payment,
            PersistentCreditTransaction,
            PersistentCreditGrant,
            AccountEntitlement,
            Scorecard,
            UsageEvent,
            UserAuthSession,
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
