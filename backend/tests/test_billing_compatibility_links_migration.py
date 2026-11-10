"""Phase 2.3 nullable compatibility-link migration coverage."""

import contextlib
import os
import uuid

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRATIONS_DIR = os.path.join(BACKEND_DIR, "migrations")
PARENT_REVISION = "c6f8d0b2e4a1"
MIGRATION_REVISION = "d7a9e1c3f5b2"

AI_LINKS = {
    "billing_account_id": "billing_accounts",
    "pricing_policy_version_id": "pricing_policy_versions",
    "capacity_policy_version_id": "capacity_policy_versions",
}


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
    for table in (
        "billing_accounts",
        "pricing_policy_versions",
        "capacity_policy_versions",
    ):
        sa.Table(table, metadata, sa.Column("id", sa.String(36), primary_key=True))
    sa.Table(
        "ai_operations",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=True),
    )
    sa.Table(
        "payments",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=True),
        sa.Column("external_reference", sa.String(255), nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(sa.text(
            "INSERT INTO ai_operations (id, policy_version, organization_id) "
            "VALUES ('legacy-operation', 'legacy-policy', 'legacy-org')"
        ))
        connection.execute(sa.text(
            "INSERT INTO payments (id, organization_id, external_reference) "
            "VALUES ('legacy-payment', 'legacy-org', 'legacy-payment-ref')"
        ))


def _assert_upgraded_schema(engine):
    inspector = sa.inspect(engine)
    ai_columns = {column["name"]: column for column in inspector.get_columns("ai_operations")}
    payment_columns = {
        column["name"]: column for column in inspector.get_columns("payments")
    }
    assert set(AI_LINKS).issubset(ai_columns)
    assert all(ai_columns[column]["nullable"] for column in AI_LINKS)
    assert payment_columns["billing_account_id"]["nullable"]
    assert "policy_version" in ai_columns

    ai_indexes = {index["name"] for index in inspector.get_indexes("ai_operations")}
    assert {
        "ix_ai_operations_billing_account_id",
        "ix_ai_operations_pricing_policy_version_id",
        "ix_ai_operations_capacity_policy_version_id",
    }.issubset(ai_indexes)
    payment_indexes = {index["name"] for index in inspector.get_indexes("payments")}
    assert "ix_payments_billing_account_id" in payment_indexes

    ai_fks = {foreign_key["name"]: foreign_key for foreign_key in inspector.get_foreign_keys("ai_operations")}
    for column, target in AI_LINKS.items():
        foreign_key = ai_fks[f"fk_ai_operations_{column}"]
        assert foreign_key["constrained_columns"] == [column]
        assert foreign_key["referred_table"] == target
        assert foreign_key["options"]["ondelete"] == "RESTRICT"
    payment_fks = {
        foreign_key["name"]: foreign_key
        for foreign_key in inspector.get_foreign_keys("payments")
    }
    assert payment_fks["fk_payments_billing_account_id"]["referred_table"] == "billing_accounts"
    assert payment_fks["fk_payments_billing_account_id"]["options"]["ondelete"] == "RESTRICT"


def _assert_legacy_rows_unchanged(engine):
    with engine.connect() as connection:
        operation = connection.execute(sa.text(
            "SELECT id, policy_version, organization_id, billing_account_id, "
            "pricing_policy_version_id, capacity_policy_version_id "
            "FROM ai_operations WHERE id = 'legacy-operation'"
        )).one()
        assert tuple(operation) == (
            "legacy-operation", "legacy-policy", "legacy-org", None, None, None,
        )
        payment = connection.execute(sa.text(
            "SELECT id, organization_id, external_reference, billing_account_id "
            "FROM payments WHERE id = 'legacy-payment'"
        )).one()
        assert tuple(payment) == (
            "legacy-payment", "legacy-org", "legacy-payment-ref", None,
        )


def test_revision_extends_phase_2_2_head():
    script = ScriptDirectory(MIGRATIONS_DIR)
    revision = script.get_revision(MIGRATION_REVISION)

    assert revision.down_revision == PARENT_REVISION
    assert script.get_heads() == [MIGRATION_REVISION]


def test_sqlite_upgrade_preserves_legacy_rows_and_empty_downgrade(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'phase_2_3.sqlite'}")
    _create_predecessor_tables(engine)
    revision_module = _revision_module()

    with _migration_ops(engine):
        revision_module.upgrade()
    _assert_upgraded_schema(engine)
    _assert_legacy_rows_unchanged(engine)

    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as connection:
            connection.execute(sa.text("PRAGMA foreign_keys = ON"))
            connection.execute(sa.text(
                "UPDATE ai_operations SET billing_account_id = 'missing' "
                "WHERE id = 'legacy-operation'"
            ))

    with _migration_ops(engine):
        revision_module.downgrade()
    inspector = sa.inspect(engine)
    assert not set(AI_LINKS).intersection(
        column["name"] for column in inspector.get_columns("ai_operations")
    )
    assert "billing_account_id" not in {
        column["name"] for column in inspector.get_columns("payments")
    }
    with engine.connect() as connection:
        assert connection.execute(sa.text(
            "SELECT policy_version FROM ai_operations WHERE id = 'legacy-operation'"
        )).scalar_one() == "legacy-policy"
        assert connection.execute(sa.text(
            "SELECT external_reference FROM payments WHERE id = 'legacy-payment'"
        )).scalar_one() == "legacy-payment-ref"
    engine.dispose()


@pytest.mark.parametrize(
    ("table", "column", "target_table"),
    (
        ("ai_operations", "billing_account_id", "billing_accounts"),
        ("ai_operations", "pricing_policy_version_id", "pricing_policy_versions"),
        ("ai_operations", "capacity_policy_version_id", "capacity_policy_versions"),
        ("payments", "billing_account_id", "billing_accounts"),
    ),
)
def test_guarded_downgrade_refuses_each_populated_link(
    tmp_path,
    table,
    column,
    target_table,
):
    engine = sa.create_engine(
        f"sqlite:///{tmp_path / f'phase_2_3_guard_{table}_{column}.sqlite'}"
    )
    _create_predecessor_tables(engine)
    revision_module = _revision_module()
    with _migration_ops(engine):
        revision_module.upgrade()

    with engine.begin() as connection:
        connection.execute(sa.text(f"INSERT INTO {target_table} (id) VALUES ('target')"))
        row_id = "legacy-payment" if table == "payments" else "legacy-operation"
        connection.execute(sa.text(
            f"UPDATE {table} SET {column} = 'target' WHERE id = :row_id"
        ), {"row_id": row_id})

    with pytest.raises(
        revision_module.CompatibilityLinksNotEmptyError,
        match=f"{table}.{column}=1",
    ):
        with _migration_ops(engine):
            revision_module.downgrade()

    _assert_upgraded_schema(engine)
    with engine.connect() as connection:
        assert connection.execute(sa.text(
            f"SELECT {column} FROM {table} WHERE id = :row_id"
        ), {"row_id": row_id}).scalar_one() == "target"
    engine.dispose()


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)
def test_postgres_phase_2_3_upgrade_constraints_and_downgrade(
    validate_test_database_url,
    postgres_schema_url,
):
    base_url = validate_test_database_url(os.environ["TEST_DATABASE_URL"])
    schema = f"phase_2_3_{uuid.uuid4().hex}"
    admin_engine = sa.create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))

    engine = sa.create_engine(postgres_schema_url(base_url, schema))
    revision_module = _revision_module()
    try:
        _create_predecessor_tables(engine)
        with _migration_ops(engine):
            revision_module.upgrade()
        _assert_upgraded_schema(engine)
        _assert_legacy_rows_unchanged(engine)

        with pytest.raises(sa.exc.IntegrityError):
            with engine.begin() as connection:
                connection.execute(sa.text(
                    "UPDATE payments SET billing_account_id = 'missing' "
                    "WHERE id = 'legacy-payment'"
                ))

        with engine.begin() as connection:
            connection.execute(sa.text(
                "INSERT INTO billing_accounts (id) VALUES ('postgres-account')"
            ))
            connection.execute(sa.text(
                "UPDATE payments SET billing_account_id = 'postgres-account' "
                "WHERE id = 'legacy-payment'"
            ))
        with pytest.raises(
            revision_module.CompatibilityLinksNotEmptyError,
            match="payments.billing_account_id=1",
        ):
            with _migration_ops(engine):
                revision_module.downgrade()
        assert "billing_account_id" in {
            column["name"] for column in sa.inspect(engine).get_columns("payments")
        }

        with engine.begin() as connection:
            connection.execute(sa.text(
                "UPDATE payments SET billing_account_id = NULL "
                "WHERE id = 'legacy-payment'"
            ))
        with _migration_ops(engine):
            revision_module.downgrade()
        assert "billing_account_id" not in {
            column["name"] for column in sa.inspect(engine).get_columns("payments")
        }
    finally:
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()
