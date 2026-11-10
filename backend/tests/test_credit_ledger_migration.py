"""Migration and database-invariant coverage for the Phase 3 credit ledger."""

import contextlib
from concurrent.futures import ThreadPoolExecutor
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
PARENT_REVISION = "d7a9e1c3f5b2"
MIGRATION_REVISION = "e8b0f2d4a6c3"
TABLES = {"credit_lots", "credit_reservations", "credit_ledger_entries"}
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 11, 10, 13, 0, tzinfo=timezone.utc)


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
    sa.Table("users", metadata, sa.Column("id", sa.String(36), primary_key=True))
    sa.Table("organizations", metadata, sa.Column("id", sa.String(36), primary_key=True))
    sa.Table(
        "billing_accounts",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
    )
    sa.Table(
        "ai_operations",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("billing_account_id", sa.String(36), nullable=True),
    )
    sa.Table(
        "pricing_policy_versions",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("state", sa.String(20), nullable=False),
    )
    sa.Table(
        "capacity_policy_versions",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
    )
    sa.Table(
        "idempotency_registry",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO users (id) VALUES ('ledger-user')"))
        connection.execute(sa.text(
            "INSERT INTO organizations (id) VALUES ('ledger-org')"
        ))
        connection.execute(sa.text(
            "INSERT INTO billing_accounts (id, organization_id) "
            "VALUES ('ledger-account', 'ledger-org'), ('other-account', 'ledger-org')"
        ))
        connection.execute(sa.text(
            "INSERT INTO ai_operations (id, billing_account_id) VALUES "
            "('operation-one', 'ledger-account'), "
            "('operation-two', 'ledger-account'), "
            "('operation-other', 'other-account')"
        ))
        connection.execute(sa.text(
            "INSERT INTO pricing_policy_versions (id, state) VALUES "
            "('pricing-approved', 'approved'), ('pricing-draft', 'draft')"
        ))
        connection.execute(sa.text(
            "INSERT INTO capacity_policy_versions (id) VALUES ('capacity-approved')"
        ))
        claim_values = ", ".join(
            f"('claim-{number}', '{'a' * 64}')" for number in range(1, 30)
        )
        connection.execute(sa.text(
            "INSERT INTO idempotency_registry (id, request_fingerprint) VALUES "
            f"{claim_values}"
        ))


def _assert_schema(engine):
    inspector = sa.inspect(engine)
    assert TABLES.issubset(inspector.get_table_names())
    assert {column["name"] for column in inspector.get_columns("credit_lots")} == {
        "id", "billing_account_id", "source_type", "source_id",
        "member_attribution_id", "eligibility_scope", "original_amount",
        "available_at", "expires_at", "origin_evidence_json", "created_at",
    }
    assert {column["name"] for column in inspector.get_columns("credit_reservations")} == {
        "id", "billing_account_id", "operation_id", "pricing_policy_version_id",
        "capacity_policy_version_id", "idempotency_registry_id", "requested_amount",
        "authorized_amount", "state", "request_fingerprint", "created_at",
        "expires_at", "finalized_at",
    }
    assert {column["name"] for column in inspector.get_columns("credit_ledger_entries")} == {
        "id", "billing_account_id", "lot_id", "entry_type", "available_delta",
        "held_delta", "reservation_id", "operation_id", "related_entry_id",
        "idempotency_registry_id", "effective_at", "created_at", "actor_type",
        "actor_id", "reason_code", "evidence_json",
    }
    assert {
        "ix_credit_lots_account_allocation_order",
        "ix_credit_lots_member_attribution_id",
    }.issubset(index["name"] for index in inspector.get_indexes("credit_lots"))
    assert {
        "ix_credit_ledger_entries_account_effective",
        "ix_credit_ledger_entries_lot_effective",
        "ix_credit_ledger_entries_reservation_id",
        "ix_credit_ledger_entries_operation_id",
        "ix_credit_ledger_entries_related_entry_id",
        "uq_credit_ledger_entries_lot_opening",
    }.issubset(index["name"] for index in inspector.get_indexes("credit_ledger_entries"))


def _insert_lot(connection, identifier="lot-one", account="ledger-account", amount=100):
    connection.execute(sa.text("""
        INSERT INTO credit_lots (
            id, billing_account_id, source_type, source_id, original_amount,
            available_at, origin_evidence_json
        ) VALUES (
            :id, :account, 'credit_pack_purchase', :source_id, :amount,
            :available_at, :evidence
        )
    """), {
        "id": identifier,
        "account": account,
        "source_id": f"source-{identifier}",
        "amount": amount,
        "available_at": NOW,
        "evidence": '{"test_only": true}',
    })


def _insert_reservation(
    connection,
    identifier="reservation-one",
    operation="operation-one",
    claim="claim-1",
    pricing="pricing-approved",
    account="ledger-account",
    amount=80,
    fingerprint="a" * 64,
):
    connection.execute(sa.text("""
        INSERT INTO credit_reservations (
            id, billing_account_id, operation_id, pricing_policy_version_id,
            capacity_policy_version_id, idempotency_registry_id,
            requested_amount, authorized_amount, state, request_fingerprint,
            created_at, expires_at
        ) VALUES (
            :id, :account, :operation, :pricing, 'capacity-approved', :claim,
            :amount, :amount, 'reserved', :fingerprint, :created_at, :expires_at
        )
    """), {
        "id": identifier,
        "account": account,
        "operation": operation,
        "pricing": pricing,
        "claim": claim,
        "amount": amount,
        "fingerprint": fingerprint,
        "created_at": NOW,
        "expires_at": LATER,
    })


def _insert_entry(
    connection,
    identifier,
    claim,
    entry_type,
    available_delta,
    held_delta,
    lot="lot-one",
    account="ledger-account",
    reservation=None,
    operation=None,
    related=None,
):
    connection.execute(sa.text("""
        INSERT INTO credit_ledger_entries (
            id, billing_account_id, lot_id, entry_type, available_delta,
            held_delta, reservation_id, operation_id, related_entry_id,
            idempotency_registry_id, effective_at, actor_type, actor_id,
            reason_code, evidence_json
        ) VALUES (
            :id, :account, :lot, :entry_type, :available_delta,
            :held_delta, :reservation, :operation, :related,
            :claim, :effective_at, 'test', 'phase-3-test',
            'test_only', :evidence
        )
    """), {
        "id": identifier,
        "account": account,
        "lot": lot,
        "entry_type": entry_type,
        "available_delta": available_delta,
        "held_delta": held_delta,
        "reservation": reservation,
        "operation": operation,
        "related": related,
        "claim": claim,
        "effective_at": NOW,
        "evidence": '{"test_only": true}',
    })


def test_revision_extends_phase_2_3_head():
    script = ScriptDirectory(MIGRATIONS_DIR)
    revision = script.get_revision(MIGRATION_REVISION)
    assert revision.down_revision == PARENT_REVISION
    assert script.get_heads() == [MIGRATION_REVISION]


def test_sqlite_upgrade_empty_downgrade_and_legacy_preservation(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'phase_3_empty.sqlite'}")
    _create_predecessor_tables(engine)
    with _migration_ops(engine):
        _revision_module().upgrade()
    _assert_schema(engine)
    with engine.connect() as connection:
        assert connection.execute(sa.text(
            "SELECT billing_account_id FROM ai_operations WHERE id = 'operation-one'"
        )).scalar_one() == "ledger-account"
        assert all(
            connection.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one() == 0
            for table in TABLES
        )
    with _migration_ops(engine):
        _revision_module().downgrade()
    assert TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    engine.dispose()


def test_sqlite_arithmetic_append_only_and_pricing_invariants(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'phase_3_invariants.sqlite'}")
    _create_predecessor_tables(engine)
    with _migration_ops(engine):
        _revision_module().upgrade()

    with engine.begin() as connection:
        connection.execute(sa.text("PRAGMA foreign_keys = ON"))
        _insert_lot(connection)
        _insert_reservation(connection)
        _insert_entry(connection, "grant", "claim-2", "grant", 100, 0)
        _insert_entry(
            connection, "reserve", "claim-3", "reservation", -80, 80,
            reservation="reservation-one", operation="operation-one",
        )
        _insert_entry(
            connection, "settle", "claim-4", "settlement", 0, -50,
            reservation="reservation-one", operation="operation-one", related="reserve",
        )
        _insert_entry(
            connection, "release", "claim-5", "release", 30, -30,
            reservation="reservation-one", operation="operation-one", related="reserve",
        )
    with engine.connect() as connection:
        assert connection.execute(sa.text("""
            SELECT SUM(available_delta), SUM(held_delta)
            FROM credit_ledger_entries WHERE lot_id = 'lot-one'
        """)).one() == (50, 0)

    with engine.begin() as connection:
        _insert_lot(connection, identifier="lot-expiring", amount=50)
        _insert_entry(
            connection, "grant-expiring", "claim-10", "grant", 50, 0,
            lot="lot-expiring",
        )
        _insert_entry(
            connection, "dispute-hold", "claim-11", "dispute_hold", -20, 20,
            lot="lot-expiring",
        )
        _insert_entry(
            connection, "expire-held", "claim-12", "expiration", -30, -20,
            lot="lot-expiring",
        )
    with engine.connect() as connection:
        assert connection.execute(sa.text("""
            SELECT SUM(available_delta), SUM(held_delta)
            FROM credit_ledger_entries WHERE lot_id = 'lot-expiring'
        """)).one() == (0, 0)

    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as connection:
            connection.execute(sa.text("PRAGMA foreign_keys = ON"))
            _insert_entry(
                connection, "overspend", "claim-6", "admin_adjustment", -51, 0,
            )
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as connection:
            _insert_entry(
                connection, "duplicate-grant", "claim-13", "grant", 1, 0,
            )
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as connection:
            connection.execute(sa.text(
                "UPDATE credit_ledger_entries SET reason_code = 'rewrite' "
                "WHERE id = 'grant'"
            ))
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as connection:
            connection.execute(sa.text(
                "DELETE FROM credit_ledger_entries WHERE id = 'grant'"
            ))
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as connection:
            connection.execute(sa.text(
                "UPDATE credit_lots SET source_id = 'rewritten' WHERE id = 'lot-one'"
            ))
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as connection:
            _insert_reservation(
                connection,
                identifier="reservation-draft",
                operation="operation-two",
                claim="claim-7",
                pricing="pricing-draft",
            )
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as connection:
            connection.execute(sa.text(
                "UPDATE idempotency_registry SET request_fingerprint = :fingerprint "
                "WHERE id = 'claim-7'"
            ), {"fingerprint": "b" * 64})
            _insert_reservation(
                connection,
                identifier="reservation-fingerprint-conflict",
                operation="operation-two",
                claim="claim-7",
            )
    engine.dispose()


def test_sqlite_correction_and_dispute_taxonomy_arithmetic(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'phase_3_taxonomy.sqlite'}")
    _create_predecessor_tables(engine)
    with _migration_ops(engine):
        _revision_module().upgrade()

    with engine.begin() as connection:
        connection.execute(sa.text("PRAGMA foreign_keys = ON"))
        _insert_lot(connection)
        _insert_entry(connection, "grant", "claim-2", "grant", 100, 0)
        _insert_entry(
            connection, "refund", "claim-3", "refund_reversal", -20, 0,
            related="grant",
        )
        _insert_entry(
            connection, "recovery", "claim-4", "recovery", 10, 0,
            related="refund",
        )
        _insert_entry(
            connection, "adjustment", "claim-5", "admin_adjustment", -5, 0,
        )
        _insert_entry(
            connection, "dispute", "claim-6", "dispute_hold", -20, 20,
        )
        _insert_entry(
            connection, "dispute-loss", "claim-7", "dispute_reversal", 0, -20,
            related="dispute",
        )
        _insert_entry(
            connection, "expiration", "claim-8", "expiration", -65, 0,
            related="grant",
        )
        _insert_lot(connection, identifier="lot-opening", amount=50)
        _insert_entry(
            connection, "opening", "claim-9", "migration_opening", 50, 0,
            lot="lot-opening",
        )

    with engine.connect() as connection:
        assert connection.execute(sa.text("""
            SELECT SUM(available_delta), SUM(held_delta)
            FROM credit_ledger_entries WHERE lot_id = 'lot-one'
        """)).one() == (0, 0)
        assert connection.execute(sa.text("""
            SELECT SUM(available_delta), SUM(held_delta)
            FROM credit_ledger_entries WHERE lot_id = 'lot-opening'
        """)).one() == (50, 0)
    engine.dispose()


@pytest.mark.parametrize("populated_table", sorted(TABLES))
def test_guarded_downgrade_refuses_each_populated_table(tmp_path, populated_table):
    engine = sa.create_engine(
        f"sqlite:///{tmp_path / f'phase_3_guard_{populated_table}.sqlite'}"
    )
    _create_predecessor_tables(engine)
    revision_module = _revision_module()
    with _migration_ops(engine):
        revision_module.upgrade()
    with engine.begin() as connection:
        connection.execute(sa.text("PRAGMA foreign_keys = ON"))
        if populated_table == "credit_lots":
            _insert_lot(connection)
        elif populated_table == "credit_reservations":
            _insert_reservation(connection)
        else:
            _insert_lot(connection)
            _insert_entry(connection, "grant", "claim-2", "grant", 100, 0)

    with pytest.raises(
        revision_module.CreditLedgerNotEmptyError,
        match=f"{populated_table}=1",
    ):
        with _migration_ops(engine):
            revision_module.downgrade()
    assert TABLES.issubset(sa.inspect(engine).get_table_names())
    engine.dispose()


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)
def test_postgres_phase_3_constraints_and_concurrent_zero_floor(
    validate_test_database_url,
    postgres_schema_url,
):
    base_url = validate_test_database_url(os.environ["TEST_DATABASE_URL"])
    schema = f"phase_3_{uuid.uuid4().hex}"
    admin_engine = sa.create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    engine = sa.create_engine(postgres_schema_url(base_url, schema))
    revision_module = _revision_module()
    try:
        _create_predecessor_tables(engine)
        with _migration_ops(engine):
            revision_module.upgrade()
        _assert_schema(engine)
        with engine.connect() as connection:
            assert connection.execute(sa.text(
                "SELECT billing_account_id FROM ai_operations "
                "WHERE id = 'operation-one'"
            )).scalar_one() == "ledger-account"
        with _migration_ops(engine):
            revision_module.downgrade()
        assert TABLES.isdisjoint(sa.inspect(engine).get_table_names())
        with _migration_ops(engine):
            revision_module.upgrade()
        _assert_schema(engine)
        with engine.begin() as connection:
            _insert_lot(connection)
            _insert_reservation(connection)
            _insert_entry(connection, "grant", "claim-2", "grant", 100, 0)

        with pytest.raises(sa.exc.DBAPIError):
            with engine.begin() as connection:
                _insert_entry(
                    connection, "duplicate-grant", "claim-10", "grant", 1, 0,
                )
        with pytest.raises(sa.exc.DBAPIError):
            with engine.begin() as connection:
                connection.execute(sa.text(
                    "UPDATE credit_ledger_entries SET reason_code = 'rewrite' "
                    "WHERE id = 'grant'"
                ))
        with pytest.raises(sa.exc.DBAPIError):
            with engine.begin() as connection:
                connection.execute(sa.text(
                    "UPDATE credit_lots SET source_id = 'rewrite' "
                    "WHERE id = 'lot-one'"
                ))
        with pytest.raises(sa.exc.DBAPIError):
            with engine.begin() as connection:
                _insert_reservation(
                    connection,
                    identifier="reservation-draft",
                    operation="operation-two",
                    claim="claim-7",
                    pricing="pricing-draft",
                )
        with pytest.raises(sa.exc.DBAPIError):
            with engine.begin() as connection:
                _insert_reservation(
                    connection,
                    identifier="reservation-fingerprint-conflict",
                    operation="operation-two",
                    claim="claim-7",
                    fingerprint="b" * 64,
                )
        with engine.begin() as connection:
            _insert_reservation(
                connection,
                identifier="reservation-two",
                operation="operation-two",
                claim="claim-8",
            )

        first_connection = engine.connect()
        first_transaction = first_connection.begin()
        _insert_entry(
            first_connection, "reserve-one", "claim-3", "reservation", -80, 80,
            reservation="reservation-one", operation="operation-one",
        )

        def competing_reservation():
            try:
                with engine.begin() as connection:
                    _insert_entry(
                        connection, "reserve-two", "claim-9", "reservation", -80, 80,
                        reservation="reservation-two", operation="operation-two",
                    )
            except (sa.exc.IntegrityError, sa.exc.InternalError):
                return "rejected"
            return "inserted"

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(competing_reservation)
            first_transaction.commit()
            first_connection.close()
            assert future.result(timeout=10) == "rejected"

        with engine.connect() as connection:
            assert connection.execute(sa.text("""
                SELECT SUM(available_delta), SUM(held_delta)
                FROM credit_ledger_entries WHERE lot_id = 'lot-one'
            """)).one() == (20, 80)
        with pytest.raises(revision_module.CreditLedgerNotEmptyError):
            with _migration_ops(engine):
                revision_module.downgrade()
    finally:
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()
