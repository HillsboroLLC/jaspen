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

    account_indexes = {
        index["name"]
        for index in inspector.get_indexes("billing_accounts")
        if not index.get("duplicates_constraint")
    }
    assert account_indexes == {
        "ix_billing_accounts_status_created_at",
        "uq_billing_accounts_processor_customer",
    }
    role_indexes = {
        index["name"]
        for index in inspector.get_indexes("billing_role_grants")
        if not index.get("duplicates_constraint")
    }
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
def test_postgres_complete_phase_2_1_verification(
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
    revision_module = _revision_module()
    try:
        _create_predecessor_tables(engine)
        with engine.begin() as connection:
            connection.execute(sa.text(
                "INSERT INTO organizations (id) VALUES "
                "('legacy-org-primary'), ('legacy-org-secondary')"
            ))
            connection.execute(sa.text(
                "INSERT INTO users (id) VALUES ('legacy-user')"
            ))

        with _migration_ops(engine):
            revision_module.upgrade()
        _assert_upgraded_schema(engine)

        inspector = sa.inspect(engine)
        account_checks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("billing_accounts")
        }
        assert account_checks == {
            "ck_billing_accounts_currency",
            "ck_billing_accounts_processor_identity",
            "ck_billing_accounts_status",
        }
        role_checks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("billing_role_grants")
        }
        assert role_checks == {
            "ck_billing_role_grants_interval",
            "ck_billing_role_grants_role",
            "ck_billing_role_grants_state",
        }
        assert {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("billing_accounts")
        } == {"uq_billing_accounts_organization_id"}
        assert {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("billing_role_grants")
        } == {"uq_billing_role_grants_account_user_role_start"}
        account_fks = {
            constraint["name"]: constraint
            for constraint in inspector.get_foreign_keys("billing_accounts")
        }
        assert account_fks["fk_billing_accounts_organization_id"]["referred_table"] == "organizations"
        assert account_fks["fk_billing_accounts_organization_id"]["options"]["ondelete"] == "RESTRICT"
        role_fks = {
            constraint["name"]: constraint
            for constraint in inspector.get_foreign_keys("billing_role_grants")
        }
        assert role_fks["fk_billing_role_grants_billing_account_id"]["options"]["ondelete"] == "RESTRICT"
        assert role_fks["fk_billing_role_grants_user_id"]["options"]["ondelete"] == "RESTRICT"
        assert role_fks["fk_billing_role_grants_granted_by_user_id"]["options"]["ondelete"] == "SET NULL"
        account_indexes = {
            index["name"]: index
            for index in inspector.get_indexes("billing_accounts")
        }
        assert account_indexes["uq_billing_accounts_processor_customer"]["unique"]
        role_indexes = {
            index["name"]: index
            for index in inspector.get_indexes("billing_role_grants")
        }
        assert role_indexes["uq_billing_role_grants_open_role"]["unique"]

        with engine.connect() as connection:
            assert connection.execute(sa.text(
                "SELECT COUNT(*) FROM billing_accounts"
            )).scalar_one() == 0
            assert connection.execute(sa.text(
                "SELECT COUNT(*) FROM billing_role_grants"
            )).scalar_one() == 0

        with pytest.raises(sa.exc.IntegrityError):
            with engine.begin() as connection:
                connection.execute(sa.text(
                    "INSERT INTO billing_accounts "
                    "(id, organization_id, currency, account_anchor_at) "
                    "VALUES ('bad-currency', 'legacy-org-primary', 'u5d', now())"
                ))

        with engine.begin() as connection:
            connection.execute(sa.text(
                "INSERT INTO billing_accounts "
                "(id, organization_id, currency, account_anchor_at, processor, "
                "processor_customer_id) VALUES "
                "('retained-account', 'legacy-org-primary', 'usd', now(), "
                "'stripe', 'cus_phase_2_1_postgres')"
            ))
            connection.execute(sa.text(
                "INSERT INTO billing_role_grants "
                "(id, billing_account_id, user_id, role, starts_at, origin_type, "
                "origin_id) VALUES "
                "('retained-role', 'retained-account', 'legacy-user', "
                "'billing_owner', now(), 'authorized_test', 'postgres-verification')"
            ))

        with pytest.raises(
            revision_module.BillingFoundationNotEmptyError,
            match="billing_accounts contains 1 row.*billing_role_grants contains 1 row",
        ):
            with _migration_ops(engine):
                revision_module.downgrade()

        assert {"billing_accounts", "billing_role_grants"}.issubset(
            sa.inspect(engine).get_table_names()
        )
        with engine.connect() as connection:
            assert connection.execute(sa.text(
                "SELECT id FROM billing_accounts"
            )).scalar_one() == "retained-account"
            assert connection.execute(sa.text(
                "SELECT id FROM billing_role_grants"
            )).scalar_one() == "retained-role"

        with engine.begin() as connection:
            connection.execute(sa.text("DELETE FROM billing_role_grants"))
            connection.execute(sa.text("DELETE FROM billing_accounts"))
        with _migration_ops(engine):
            revision_module.downgrade()
        assert "billing_accounts" not in sa.inspect(engine).get_table_names()
        assert "billing_role_grants" not in sa.inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert connection.execute(sa.text(
                "SELECT id FROM organizations ORDER BY id"
            )).scalars().all() == ["legacy-org-primary", "legacy-org-secondary"]
            assert connection.execute(sa.text(
                "SELECT id FROM users"
            )).scalar_one() == "legacy-user"
    finally:
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()
