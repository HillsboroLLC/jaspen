"""Migration and database-invariant coverage for the Phase 3 credit ledger."""

import contextlib
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
import os
from threading import Event
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

# The matrix is the test contract for the single ledger enforcement path.
# Every movement receives the shared row-level accounting invariants. Only
# movements that consume or produce an allocation add transaction-specific
# rules, and those differences identify the eligible producer entry rather
# than defining a second balance calculation.
SHARED_LEDGER_INVARIANTS = {
    "account_lot_ownership",
    "entry_shape",
    "idempotency",
    "provenance",
    "zero_floor_and_original_cap",
}
TRANSACTION_TYPE_COVERAGE_MATRIX = {
    "grant": SHARED_LEDGER_INVARIANTS | {"opening_uniqueness"},
    "reservation": SHARED_LEDGER_INVARIANTS | {"reservation_authorization_cap"},
    "settlement": SHARED_LEDGER_INVARIANTS
    | {"held_allocation", "reservation_binding"},
    "release": SHARED_LEDGER_INVARIANTS
    | {"held_allocation", "conditional_reservation_binding"},
    "expiration": SHARED_LEDGER_INVARIANTS | {"conditional_held_allocation"},
    "refund_reversal": SHARED_LEDGER_INVARIANTS | {"related_entry_ownership"},
    "dispute_hold": SHARED_LEDGER_INVARIANTS,
    "dispute_reversal": SHARED_LEDGER_INVARIANTS | {"held_allocation"},
    "recovery": SHARED_LEDGER_INVARIANTS | {"related_entry_ownership"},
    "admin_adjustment": SHARED_LEDGER_INVARIANTS,
    "migration_opening": SHARED_LEDGER_INVARIANTS | {"opening_uniqueness"},
}


def _revision_module():
    return ScriptDirectory(MIGRATIONS_DIR).get_revision(MIGRATION_REVISION).module


def _sqlstate(exc):
    return getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)


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
            "('operation-three', 'ledger-account'), "
            "('operation-four', 'ledger-account'), "
            "('operation-five', 'ledger-account'), "
            "('operation-six', 'ledger-account'), "
            "('operation-other', 'other-account')"
        ))
        connection.execute(sa.text(
            "INSERT INTO pricing_policy_versions (id, state) VALUES "
            "('pricing-approved', 'approved'), "
            "('pricing-approved-two', 'approved'), "
            "('pricing-draft', 'draft')"
        ))
        connection.execute(sa.text(
            "INSERT INTO capacity_policy_versions (id) VALUES ('capacity-approved')"
        ))
        claim_values = ", ".join(
            f"('claim-{number}', '{'a' * 64}')" for number in range(1, 81)
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
    assert MIGRATION_REVISION in {
        item.revision for item in script.iterate_revisions(script.get_current_head(), "base")
    }


@pytest.mark.parametrize(
    ("entry_type", "specific_invariants"),
    sorted(TRANSACTION_TYPE_COVERAGE_MATRIX.items()),
)
def test_transaction_type_financial_invariant_coverage_matrix(
    entry_type,
    specific_invariants,
):
    assert set(TRANSACTION_TYPE_COVERAGE_MATRIX) == set(
        _revision_module().LEDGER_ENTRY_TYPES
    )
    assert SHARED_LEDGER_INVARIANTS.issubset(specific_invariants)
    if entry_type in {"settlement", "release", "dispute_reversal"}:
        assert "held_allocation" in specific_invariants
    if entry_type == "release":
        assert "conditional_reservation_binding" in specific_invariants
    if entry_type == "expiration":
        assert "conditional_held_allocation" in specific_invariants
    if entry_type in {"refund_reversal", "recovery"}:
        assert "related_entry_ownership" in specific_invariants


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

    with pytest.raises(
        sa.exc.IntegrityError,
        match="held movement exceeds referenced allocation",
    ):
        with engine.begin() as connection:
            _insert_entry(
                connection, "settle-too-much", "claim-15", "settlement", 0, -81,
                reservation="reservation-one", operation="operation-one",
                related="reserve",
            )
    with pytest.raises(
        sa.exc.IntegrityError,
        match="reservation entries exceed authorized allocation",
    ):
        with engine.begin() as connection:
            _insert_entry(
                connection, "reserve-over-authorized", "claim-18",
                "reservation", -1, 1,
                reservation="reservation-one", operation="operation-one",
            )
    with pytest.raises(
        sa.exc.IntegrityError,
        match="held movement must reference an eligible allocation",
    ):
        with engine.begin() as connection:
            _insert_entry(
                connection, "release-grant", "claim-16", "release", 1, -1,
                reservation="reservation-one", operation="operation-one",
                related="grant",
            )
    with engine.begin() as connection:
        _insert_reservation(
            connection,
            identifier="reservation-two",
            operation="operation-two",
            claim="claim-14",
            amount=10,
        )
    with pytest.raises(
        sa.exc.IntegrityError,
        match="held movement must reference an eligible allocation",
    ):
        with engine.begin() as connection:
            _insert_entry(
                connection, "settle-other-reservation", "claim-17", "settlement", 0, -1,
                reservation="reservation-two", operation="operation-two",
                related="reserve",
            )

    with engine.begin() as connection:
        connection.execute(sa.text(
            "UPDATE pricing_policy_versions SET state = 'superseded' "
            "WHERE id = 'pricing-approved'"
        ))
        _insert_entry(
            connection, "settle", "claim-4", "settlement", 0, -50,
            reservation="reservation-one", operation="operation-one", related="reserve",
        )
        _insert_entry(
            connection, "release", "claim-5", "release", 30, -30,
            reservation="reservation-one", operation="operation-one", related="reserve",
        )
        connection.execute(sa.text(
            "UPDATE credit_reservations SET state = 'settled', "
            "finalized_at = :finalized_at WHERE id = 'reservation-one'"
        ), {"finalized_at": LATER})
    with engine.connect() as connection:
        assert connection.execute(sa.text("""
            SELECT SUM(available_delta), SUM(held_delta)
            FROM credit_ledger_entries WHERE lot_id = 'lot-one'
        """)).one() == (50, 0)
        assert connection.execute(sa.text(
            "SELECT state FROM credit_reservations WHERE id = 'reservation-one'"
        )).scalar_one() == "settled"

    with pytest.raises(
        sa.exc.IntegrityError,
        match="terminal reservation state cannot be reopened",
    ):
        with engine.begin() as connection:
            connection.execute(sa.text(
                "UPDATE credit_reservations SET state = 'reserved', "
                "finalized_at = NULL WHERE id = 'reservation-one'"
            ))
    with pytest.raises(
        sa.exc.IntegrityError,
        match="reservation identity and authorization are immutable",
    ):
        with engine.begin() as connection:
            connection.execute(sa.text(
                "UPDATE credit_reservations SET authorized_amount = 79 "
                "WHERE id = 'reservation-one'"
            ))

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
            lot="lot-expiring", related="dispute-hold",
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
                pricing="pricing-approved-two",
            )
    engine.dispose()


def test_sqlite_held_expiration_and_dispute_reversal_are_allocation_bound(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'phase_3_held.sqlite'}")
    _create_predecessor_tables(engine)
    with _migration_ops(engine):
        _revision_module().upgrade()

    with engine.begin() as connection:
        connection.execute(sa.text("PRAGMA foreign_keys = ON"))
        _insert_lot(connection, amount=200)
        _insert_reservation(connection, amount=30)
        _insert_reservation(
            connection,
            identifier="reservation-two",
            operation="operation-two",
            claim="claim-2",
            amount=40,
        )
        _insert_entry(connection, "grant", "claim-3", "grant", 200, 0)
        _insert_entry(
            connection, "reserve-30", "claim-4", "reservation", -30, 30,
            reservation="reservation-one", operation="operation-one",
        )
        _insert_entry(
            connection, "reserve-40", "claim-5", "reservation", -40, 40,
            reservation="reservation-two", operation="operation-two",
        )
        _insert_lot(connection, identifier="lot-other", amount=10)
        _insert_entry(
            connection, "grant-other", "claim-20", "grant", 10, 0,
            lot="lot-other",
        )

    with pytest.raises(
        sa.exc.IntegrityError,
        match="held movement exceeds referenced allocation",
    ):
        with engine.begin() as connection:
            _insert_entry(
                connection, "expire-40-from-30", "claim-6", "expiration", 0, -40,
                related="reserve-30",
            )
    with pytest.raises(
        sa.exc.IntegrityError,
        match="held movement must reference an eligible allocation",
    ):
        with engine.begin() as connection:
            _insert_entry(
                connection, "expire-unreferenced", "claim-7", "expiration", 0, -10,
            )
    with pytest.raises(
        sa.exc.IntegrityError,
        match="held movement must reference an eligible allocation",
    ):
        with engine.begin() as connection:
            _insert_entry(
                connection, "expire-grant", "claim-8", "expiration", 0, -10,
                related="grant",
            )
    with pytest.raises(
        sa.exc.IntegrityError,
        match="related ledger entry must share account and lot",
    ):
        with engine.begin() as connection:
            _insert_entry(
                connection, "refund-cross-lot", "claim-21",
                "refund_reversal", -1, 0, related="grant-other",
            )
    with engine.begin() as connection:
        _insert_entry(
            connection, "expire-reservation", "claim-9", "expiration", 0, -30,
            related="reserve-30",
        )
    with pytest.raises(
        sa.exc.IntegrityError,
        match="held movement exceeds referenced allocation",
    ):
        with engine.begin() as connection:
            _insert_entry(
                connection, "expire-reservation-again", "claim-10",
                "expiration", 0, -1, related="reserve-30",
            )
    with pytest.raises(
        sa.exc.IntegrityError,
        match="held movement exceeds referenced allocation",
    ):
        with engine.begin() as connection:
            _insert_entry(
                connection, "settle-expired-reservation", "claim-18",
                "settlement", 0, -1,
                reservation="reservation-one", operation="operation-one",
                related="reserve-30",
            )

    with engine.begin() as connection:
        _insert_entry(
            connection, "dispute-10", "claim-11", "dispute_hold", -10, 10,
        )
        _insert_entry(
            connection, "dispute-20", "claim-12", "dispute_hold", -20, 20,
        )
        _insert_entry(
            connection, "dispute-30", "claim-22", "dispute_hold", -30, 30,
        )
        _insert_entry(
            connection, "dispute-15", "claim-23", "dispute_hold", -15, 15,
        )
    with pytest.raises(
        sa.exc.IntegrityError,
        match="held movement exceeds referenced allocation",
    ):
        with engine.begin() as connection:
            _insert_entry(
                connection, "release-20-from-10", "claim-24",
                "release", 20, -20, related="dispute-10",
            )
    with pytest.raises(
        sa.exc.IntegrityError,
        match="held movement must reference an eligible allocation",
    ):
        with engine.begin() as connection:
            _insert_entry(
                connection, "release-grant-as-dispute", "claim-25",
                "release", 1, -1, related="grant",
            )
    with pytest.raises(
        sa.exc.IntegrityError,
        match="held movement exceeds referenced allocation",
    ):
        with engine.begin() as connection:
            _insert_entry(
                connection, "reverse-20-from-10", "claim-13",
                "dispute_reversal", 0, -20, related="dispute-10",
            )
    with pytest.raises(
        sa.exc.IntegrityError,
        match="held movement must reference an eligible allocation",
    ):
        with engine.begin() as connection:
            _insert_entry(
                connection, "reverse-reservation", "claim-14",
                "dispute_reversal", 0, -5, related="reserve-40",
            )
    with engine.begin() as connection:
        _insert_entry(
            connection, "reverse-dispute", "claim-15",
            "dispute_reversal", 0, -10, related="dispute-10",
        )
        _insert_entry(
            connection, "expire-dispute", "claim-16", "expiration", 0, -20,
            related="dispute-20",
        )
        _insert_entry(
            connection, "reverse-partial-dispute", "claim-26",
            "dispute_reversal", 0, -10, related="dispute-30",
        )
        _insert_entry(
            connection, "release-remaining-dispute", "claim-27",
            "release", 20, -20, related="dispute-30",
        )
        _insert_entry(
            connection, "release-won-dispute", "claim-28",
            "release", 15, -15, related="dispute-15",
        )
    with pytest.raises(
        sa.exc.IntegrityError,
        match="held movement exceeds referenced allocation",
    ):
        with engine.begin() as connection:
            _insert_entry(
                connection, "reverse-dispute-again", "claim-17",
                "dispute_reversal", 0, -1, related="dispute-10",
            )
    with pytest.raises(
        sa.exc.IntegrityError,
        match="held movement exceeds referenced allocation",
    ):
        with engine.begin() as connection:
            _insert_entry(
                connection, "reverse-expired-dispute", "claim-19",
                "dispute_reversal", 0, -1, related="dispute-20",
            )
    with pytest.raises(
        sa.exc.IntegrityError,
        match="held movement exceeds referenced allocation",
    ):
        with engine.begin() as connection:
            _insert_entry(
                connection, "release-consumed-dispute", "claim-29",
                "release", 1, -1, related="dispute-30",
            )

    with engine.connect() as connection:
        assert connection.execute(sa.text("""
            SELECT SUM(available_delta), SUM(held_delta)
            FROM credit_ledger_entries WHERE lot_id = 'lot-one'
        """)).one() == (90, 40)
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
        with pytest.raises(sa.exc.IntegrityError) as draft_error:
            with engine.begin() as connection:
                _insert_reservation(
                    connection,
                    identifier="reservation-draft",
                    operation="operation-two",
                    claim="claim-7",
                    pricing="pricing-draft",
                )
        assert _sqlstate(draft_error.value) == "23514"
        with pytest.raises(sa.exc.IntegrityError) as fingerprint_error:
            with engine.begin() as connection:
                _insert_reservation(
                    connection,
                    identifier="reservation-fingerprint-conflict",
                    operation="operation-two",
                    claim="claim-7",
                    pricing="pricing-approved-two",
                    fingerprint="b" * 64,
                )
        assert _sqlstate(fingerprint_error.value) == "23514"

        with engine.begin() as connection:
            _insert_entry(
                connection, "reserve", "claim-3", "reservation", -80, 80,
                reservation="reservation-one", operation="operation-one",
            )

        with pytest.raises(sa.exc.IntegrityError) as over_settlement:
            with engine.begin() as connection:
                _insert_entry(
                    connection, "settle-too-much", "claim-15", "settlement", 0, -81,
                    reservation="reservation-one", operation="operation-one",
                    related="reserve",
                )
        assert _sqlstate(over_settlement.value) == "23514"
        with pytest.raises(sa.exc.IntegrityError) as over_authorized:
            with engine.begin() as connection:
                _insert_entry(
                    connection, "reserve-over-authorized", "claim-18",
                    "reservation", -1, 1,
                    reservation="reservation-one", operation="operation-one",
                )
        assert _sqlstate(over_authorized.value) == "23514"
        with pytest.raises(sa.exc.IntegrityError) as grant_release:
            with engine.begin() as connection:
                _insert_entry(
                    connection, "release-grant", "claim-16", "release", 1, -1,
                    reservation="reservation-one", operation="operation-one",
                    related="grant",
                )
        assert _sqlstate(grant_release.value) == "23514"

        with engine.begin() as connection:
            _insert_reservation(
                connection,
                identifier="reservation-two",
                operation="operation-two",
                claim="claim-14",
                amount=10,
            )
        with pytest.raises(sa.exc.IntegrityError) as other_reservation:
            with engine.begin() as connection:
                _insert_entry(
                    connection, "settle-other-reservation", "claim-17",
                    "settlement", 0, -1,
                    reservation="reservation-two", operation="operation-two",
                    related="reserve",
                )
        assert _sqlstate(other_reservation.value) == "23514"

        with engine.begin() as connection:
            connection.execute(sa.text(
                "UPDATE pricing_policy_versions SET state = 'superseded' "
                "WHERE id = 'pricing-approved'"
            ))
            _insert_entry(
                connection, "settle", "claim-4", "settlement", 0, -50,
                reservation="reservation-one", operation="operation-one",
                related="reserve",
            )
            _insert_entry(
                connection, "release", "claim-5", "release", 30, -30,
                reservation="reservation-one", operation="operation-one",
                related="reserve",
            )
            connection.execute(sa.text(
                "UPDATE credit_reservations SET state = 'settled', "
                "finalized_at = :finalized_at WHERE id = 'reservation-one'"
            ), {"finalized_at": LATER})

        with pytest.raises(sa.exc.IntegrityError) as reopen_error:
            with engine.begin() as connection:
                connection.execute(sa.text(
                    "UPDATE credit_reservations SET state = 'reserved', "
                    "finalized_at = NULL WHERE id = 'reservation-one'"
                ))
        assert _sqlstate(reopen_error.value) == "23514"
        with pytest.raises(sa.exc.IntegrityError) as amount_edit_error:
            with engine.begin() as connection:
                connection.execute(sa.text(
                    "UPDATE credit_reservations SET authorized_amount = 79 "
                    "WHERE id = 'reservation-one'"
                ))
        assert _sqlstate(amount_edit_error.value) == "23514"

        with engine.begin() as connection:
            _insert_lot(connection, identifier="lot-held", amount=200)
            _insert_reservation(
                connection,
                identifier="reservation-five",
                operation="operation-five",
                claim="claim-40",
                pricing="pricing-approved-two",
                amount=30,
            )
            _insert_reservation(
                connection,
                identifier="reservation-six",
                operation="operation-six",
                claim="claim-41",
                pricing="pricing-approved-two",
                amount=40,
            )
            _insert_entry(
                connection, "grant-held", "claim-42", "grant", 200, 0,
                lot="lot-held",
            )
            _insert_entry(
                connection, "reserve-30", "claim-43", "reservation", -30, 30,
                lot="lot-held", reservation="reservation-five",
                operation="operation-five",
            )
            _insert_entry(
                connection, "reserve-40", "claim-44", "reservation", -40, 40,
                lot="lot-held", reservation="reservation-six",
                operation="operation-six",
            )
            _insert_lot(connection, identifier="lot-held-other", amount=10)
            _insert_entry(
                connection, "grant-held-other", "claim-58", "grant", 10, 0,
                lot="lot-held-other",
            )

        with pytest.raises(sa.exc.IntegrityError) as expiration_too_large:
            with engine.begin() as connection:
                _insert_entry(
                    connection, "expire-40-from-30", "claim-45",
                    "expiration", 0, -40, lot="lot-held", related="reserve-30",
                )
        assert _sqlstate(expiration_too_large.value) == "23514"
        with pytest.raises(sa.exc.IntegrityError) as expiration_unreferenced:
            with engine.begin() as connection:
                _insert_entry(
                    connection, "expire-unreferenced", "claim-46",
                    "expiration", 0, -10, lot="lot-held",
                )
        assert _sqlstate(expiration_unreferenced.value) == "23514"
        with pytest.raises(sa.exc.IntegrityError) as refund_cross_lot:
            with engine.begin() as connection:
                _insert_entry(
                    connection, "refund-cross-lot", "claim-59",
                    "refund_reversal", -1, 0, lot="lot-held",
                    related="grant-held-other",
                )
        assert _sqlstate(refund_cross_lot.value) == "23514"
        with engine.begin() as connection:
            _insert_entry(
                connection, "expire-reservation", "claim-47",
                "expiration", 0, -30, lot="lot-held", related="reserve-30",
            )
            _insert_entry(
                connection, "dispute-10", "claim-48", "dispute_hold", -10, 10,
                lot="lot-held",
            )
            _insert_entry(
                connection, "dispute-20", "claim-49", "dispute_hold", -20, 20,
                lot="lot-held",
            )
            _insert_entry(
                connection, "dispute-30", "claim-60", "dispute_hold", -30, 30,
                lot="lot-held",
            )
            _insert_entry(
                connection, "dispute-15", "claim-61", "dispute_hold", -15, 15,
                lot="lot-held",
            )
        with pytest.raises(sa.exc.IntegrityError) as expiration_consumed:
            with engine.begin() as connection:
                _insert_entry(
                    connection, "expire-reservation-again", "claim-55",
                    "expiration", 0, -1, lot="lot-held", related="reserve-30",
                )
        assert _sqlstate(expiration_consumed.value) == "23514"
        with pytest.raises(sa.exc.IntegrityError) as settlement_after_expiration:
            with engine.begin() as connection:
                _insert_entry(
                    connection, "settle-expired-reservation", "claim-56",
                    "settlement", 0, -1, lot="lot-held",
                    reservation="reservation-five", operation="operation-five",
                    related="reserve-30",
                )
        assert _sqlstate(settlement_after_expiration.value) == "23514"
        with pytest.raises(sa.exc.IntegrityError) as dispute_too_large:
            with engine.begin() as connection:
                _insert_entry(
                    connection, "reverse-20-from-10", "claim-50",
                    "dispute_reversal", 0, -20, lot="lot-held",
                    related="dispute-10",
                )
        assert _sqlstate(dispute_too_large.value) == "23514"
        with pytest.raises(sa.exc.IntegrityError) as dispute_wrong_type:
            with engine.begin() as connection:
                _insert_entry(
                    connection, "reverse-reservation", "claim-51",
                    "dispute_reversal", 0, -5, lot="lot-held",
                    related="reserve-40",
                )
        assert _sqlstate(dispute_wrong_type.value) == "23514"
        with pytest.raises(sa.exc.IntegrityError) as release_other_dispute:
            with engine.begin() as connection:
                _insert_entry(
                    connection, "release-20-from-10", "claim-62",
                    "release", 20, -20, lot="lot-held", related="dispute-10",
                )
        assert _sqlstate(release_other_dispute.value) == "23514"
        with pytest.raises(sa.exc.IntegrityError) as release_wrong_type:
            with engine.begin() as connection:
                _insert_entry(
                    connection, "release-grant-as-dispute", "claim-63",
                    "release", 1, -1, lot="lot-held", related="grant-held",
                )
        assert _sqlstate(release_wrong_type.value) == "23514"
        with engine.begin() as connection:
            _insert_entry(
                connection, "reverse-dispute", "claim-52",
                "dispute_reversal", 0, -10, lot="lot-held",
                related="dispute-10",
            )
            _insert_entry(
                connection, "expire-dispute", "claim-53",
                "expiration", 0, -20, lot="lot-held", related="dispute-20",
            )
            _insert_entry(
                connection, "reverse-partial-dispute", "claim-64",
                "dispute_reversal", 0, -10, lot="lot-held",
                related="dispute-30",
            )
            _insert_entry(
                connection, "release-remaining-dispute", "claim-65",
                "release", 20, -20, lot="lot-held", related="dispute-30",
            )
            _insert_entry(
                connection, "release-won-dispute", "claim-66",
                "release", 15, -15, lot="lot-held", related="dispute-15",
            )
        with pytest.raises(sa.exc.IntegrityError) as dispute_consumed:
            with engine.begin() as connection:
                _insert_entry(
                    connection, "reverse-dispute-again", "claim-54",
                    "dispute_reversal", 0, -1, lot="lot-held",
                    related="dispute-10",
                )
        assert _sqlstate(dispute_consumed.value) == "23514"
        with pytest.raises(sa.exc.IntegrityError) as dispute_expired:
            with engine.begin() as connection:
                _insert_entry(
                    connection, "reverse-expired-dispute", "claim-57",
                    "dispute_reversal", 0, -1, lot="lot-held",
                    related="dispute-20",
                )
        assert _sqlstate(dispute_expired.value) == "23514"
        with pytest.raises(sa.exc.IntegrityError) as release_consumed_dispute:
            with engine.begin() as connection:
                _insert_entry(
                    connection, "release-consumed-dispute", "claim-67",
                    "release", 1, -1, lot="lot-held", related="dispute-30",
                )
        assert _sqlstate(release_consumed_dispute.value) == "23514"

        with engine.begin() as connection:
            _insert_lot(connection, identifier="lot-concurrent", amount=100)
            _insert_reservation(
                connection,
                identifier="reservation-three",
                operation="operation-three",
                claim="claim-19",
                pricing="pricing-approved-two",
            )
            _insert_reservation(
                connection,
                identifier="reservation-four",
                operation="operation-four",
                claim="claim-20",
                pricing="pricing-approved-two",
            )
            _insert_entry(
                connection, "grant-concurrent", "claim-21", "grant", 100, 0,
                lot="lot-concurrent",
            )

        first_connection = engine.connect()
        first_transaction = first_connection.begin()
        _insert_entry(
            first_connection, "reserve-three", "claim-22", "reservation", -80, 80,
            lot="lot-concurrent", reservation="reservation-three",
            operation="operation-three",
        )

        competitor_started = Event()

        def competing_reservation():
            competitor_started.set()
            try:
                with engine.begin() as connection:
                    _insert_entry(
                        connection, "reserve-four", "claim-23", "reservation", -80, 80,
                        lot="lot-concurrent", reservation="reservation-four",
                        operation="operation-four",
                    )
            except sa.exc.IntegrityError as exc:
                return _sqlstate(exc)
            return None

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(competing_reservation)
            assert competitor_started.wait(timeout=2)
            with pytest.raises(FutureTimeoutError):
                future.result(timeout=0.25)
            first_transaction.commit()
            first_connection.close()
            assert future.result(timeout=10) == "23514"

        with engine.connect() as connection:
            assert connection.execute(sa.text("""
                SELECT SUM(available_delta), SUM(held_delta)
                FROM credit_ledger_entries WHERE lot_id = 'lot-held'
            """)).one() == (90, 40)
            assert connection.execute(sa.text("""
                SELECT SUM(available_delta), SUM(held_delta)
                FROM credit_ledger_entries WHERE lot_id = 'lot-concurrent'
            """)).one() == (20, 80)
        with pytest.raises(revision_module.CreditLedgerNotEmptyError):
            with _migration_ops(engine):
                revision_module.downgrade()
    finally:
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)
def test_postgres_repeatable_read_and_mixed_isolation_prevent_overspend(
    validate_test_database_url,
    postgres_schema_url,
):
    base_url = validate_test_database_url(os.environ["TEST_DATABASE_URL"])
    schema = f"phase_3_isolation_{uuid.uuid4().hex}"
    admin_engine = sa.create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    engine = sa.create_engine(postgres_schema_url(base_url, schema))
    try:
        _create_predecessor_tables(engine)
        with _migration_ops(engine):
            _revision_module().upgrade()
        with engine.begin() as connection:
            _insert_lot(connection, identifier="lot-isolation", amount=100)
            _insert_reservation(
                connection,
                identifier="reservation-five",
                operation="operation-five",
                claim="claim-30",
            )
            _insert_reservation(
                connection,
                identifier="reservation-six",
                operation="operation-six",
                claim="claim-31",
            )
            _insert_entry(
                connection, "grant-isolation", "claim-32", "grant", 100, 0,
                lot="lot-isolation",
            )

        repeatable = engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        )
        repeatable_transaction = repeatable.begin()
        repeatable.execute(sa.text("SELECT COUNT(*) FROM billing_accounts"))
        with engine.begin() as connection:
            _insert_entry(
                connection, "reserve-five", "claim-33", "reservation", -80, 80,
                lot="lot-isolation", reservation="reservation-five",
                operation="operation-five",
            )
        try:
            with pytest.raises(sa.exc.OperationalError) as stale_snapshot:
                _insert_entry(
                    repeatable, "reserve-six", "claim-34", "reservation", -80, 80,
                    lot="lot-isolation", reservation="reservation-six",
                    operation="operation-six",
                )
            assert _sqlstate(stale_snapshot.value) == "40001"
        finally:
            repeatable_transaction.rollback()
            repeatable.close()

        with engine.begin() as connection:
            _insert_lot(connection, identifier="lot-mixed", amount=100)
            _insert_reservation(
                connection,
                identifier="reservation-three",
                operation="operation-three",
                claim="claim-35",
            )
            _insert_reservation(
                connection,
                identifier="reservation-four",
                operation="operation-four",
                claim="claim-36",
            )
            _insert_entry(
                connection, "grant-mixed", "claim-37", "grant", 100, 0,
                lot="lot-mixed",
            )

        first_connection = engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        )
        first_transaction = first_connection.begin()
        _insert_entry(
            first_connection, "reserve-three", "claim-38", "reservation", -80, 80,
            lot="lot-mixed", reservation="reservation-three",
            operation="operation-three",
        )
        competitor_started = Event()

        def read_committed_competitor():
            competitor_started.set()
            try:
                with engine.begin() as connection:
                    _insert_entry(
                        connection, "reserve-four", "claim-39", "reservation", -80, 80,
                        lot="lot-mixed", reservation="reservation-four",
                        operation="operation-four",
                    )
            except sa.exc.IntegrityError as exc:
                return _sqlstate(exc)
            return None

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(read_committed_competitor)
            assert competitor_started.wait(timeout=2)
            with pytest.raises(FutureTimeoutError):
                future.result(timeout=0.25)
            first_transaction.commit()
            first_connection.close()
            assert future.result(timeout=10) == "23514"

        with engine.connect() as connection:
            assert connection.execute(sa.text("""
                SELECT SUM(available_delta), SUM(held_delta)
                FROM credit_ledger_entries WHERE lot_id = 'lot-isolation'
            """)).one() == (20, 80)
            assert connection.execute(sa.text("""
                SELECT SUM(available_delta), SUM(held_delta)
                FROM credit_ledger_entries WHERE lot_id = 'lot-mixed'
            """)).one() == (20, 80)
    finally:
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()
