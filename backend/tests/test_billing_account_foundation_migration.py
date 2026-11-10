"""Upgrade, graph, and guarded-downgrade coverage for Phase 2.1."""

import contextlib
from datetime import datetime, timezone
import os
import uuid

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRATIONS_DIR = os.path.join(BACKEND_DIR, "migrations")
PARENT_REVISION = "a4d7c9e2f105"
MIGRATION_REVISION = "b5e7c9a1d3f2"


def _revision_module():
    return ScriptDirectory(MIGRATIONS_DIR).get_revision(MIGRATION_REVISION).module


@contextlib.contextmanager
def _migration_ops(engine):
    with engine.begin() as connection:
        if connection.dialect.name == "sqlite":
            connection.execute(sa.text("PRAGMA foreign_keys = ON"))
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            yield connection


def _create_predecessor_tables(engine):
    metadata = sa.MetaData()
    sa.Table(
        "organizations",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
    )
    sa.Table(
        "users",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
    )
    metadata.create_all(engine)


def _assert_upgraded_schema(engine):
    inspector = sa.inspect(engine)
    assert {"billing_accounts", "billing_role_grants"}.issubset(inspector.get_table_names())

    account_columns = {column["name"] for column in inspector.get_columns("billing_accounts")}
    assert account_columns == {
        "id", "organization_id", "status", "currency", "account_anchor_at",
        "processor", "processor_customer_id", "tax_context_json", "created_at",
        "updated_at",
    }
    role_columns = {column["name"] for column in inspector.get_columns("billing_role_grants")}
    assert role_columns == {
        "id", "billing_account_id", "user_id", "role", "state", "starts_at",
        "ends_at", "granted_by_user_id", "origin_type", "origin_id", "created_at",
    }

    account_indexes = {index["name"] for index in inspector.get_indexes("billing_accounts")}
    assert account_indexes == {
        "ix_billing_accounts_status_created_at",
        "uq_billing_accounts_processor_customer",
    }
    role_indexes = {index["name"] for index in inspector.get_indexes("billing_role_grants")}
    assert role_indexes == {
        "ix_billing_role_grants_account_state",
        "ix_billing_role_grants_user_state",
        "uq_billing_role_grants_open_role",
    }


def test_revision_extends_the_single_validated_head():
    script = ScriptDirectory(MIGRATIONS_DIR)
    revision = script.get_revision(MIGRATION_REVISION)

    assert revision.down_revision == PARENT_REVISION
    assert script.get_heads() == [MIGRATION_REVISION]


def test_sqlite_upgrade_creates_empty_schema_and_empty_downgrade_removes_it(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'phase_2_1.sqlite'}")
    _create_predecessor_tables(engine)

    with _migration_ops(engine):
        _revision_module().upgrade()
    _assert_upgraded_schema(engine)
    with engine.begin() as connection:
        connection.execute(sa.text("PRAGMA foreign_keys = ON"))
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(sa.text(
                "INSERT INTO billing_accounts "
                "(id, organization_id, currency, account_anchor_at) "
                "VALUES ('invalid-account', 'missing-org', 'usd', :now)"
            ), {"now": datetime.now(timezone.utc)})
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT COUNT(*) FROM billing_accounts")).scalar() == 0
        assert connection.execute(sa.text("SELECT COUNT(*) FROM billing_role_grants")).scalar() == 0

    with _migration_ops(engine):
        _revision_module().downgrade()
    assert "billing_accounts" not in sa.inspect(engine).get_table_names()
    assert "billing_role_grants" not in sa.inspect(engine).get_table_names()
    engine.dispose()


def test_guarded_downgrade_refuses_without_partial_schema_change(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'phase_2_1_guard.sqlite'}")
    revision_module = _revision_module()
    _create_predecessor_tables(engine)
    with _migration_ops(engine):
        revision_module.upgrade()

    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO organizations (id) VALUES ('org-retained')"))
        connection.execute(sa.text(
            "INSERT INTO billing_accounts "
            "(id, organization_id, currency, account_anchor_at) "
            "VALUES ('account-retained', 'org-retained', 'usd', :now)"
        ), {"now": now})

    with pytest.raises(
        revision_module.BillingFoundationNotEmptyError,
        match="billing_accounts contains 1 row",
    ):
        with _migration_ops(engine):
            revision_module.downgrade()

    assert {"billing_accounts", "billing_role_grants"}.issubset(
        sa.inspect(engine).get_table_names()
    )
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT COUNT(*) FROM billing_accounts")).scalar() == 1
    engine.dispose()


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)
def test_postgres_upgrade_and_empty_downgrade(
    validate_test_database_url,
    postgres_schema_url,
):
    base_url = validate_test_database_url(os.environ["TEST_DATABASE_URL"])
    schema = f"phase_2_1_{uuid.uuid4().hex}"
    admin_engine = sa.create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))

    test_url = postgres_schema_url(base_url, schema)
    engine = sa.create_engine(test_url)
    try:
        _create_predecessor_tables(engine)
        with _migration_ops(engine):
            _revision_module().upgrade()
        _assert_upgraded_schema(engine)
        with _migration_ops(engine):
            _revision_module().downgrade()
        assert "billing_accounts" not in sa.inspect(engine).get_table_names()
        assert "billing_role_grants" not in sa.inspect(engine).get_table_names()
    finally:
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()
