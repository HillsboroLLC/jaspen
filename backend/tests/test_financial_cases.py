"""Phase 5.3 refund and dispute case foundation tests."""

import contextlib
import hashlib
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import billing_financial, billing_financial_cases, billing_inbox
from app.models import (
    FinancialCase,
    FinancialCaseEvent,
    FinancialCaseEventLedgerEntry,
    FinancialCaseEventLine,
    FinancialCaseSourceFence,
    FinancialLine,
    FinancialTransaction,
)
from app.models_billing_phase5 import ExternalEventInbox, ExternalEventInboxConflict


BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = str(BACKEND_DIR / "migrations")
PARENT = "c3e5a7b9d1f4"
REVISION = "d3e5a7b9c1f4"
NOW = datetime.now(timezone.utc).replace(microsecond=0)
_REVISION_MODULES = {}


def _revision(revision=REVISION):
    if revision not in _REVISION_MODULES:
        _REVISION_MODULES[revision] = ScriptDirectory(MIGRATIONS_DIR).get_revision(revision).module
    return _REVISION_MODULES[revision]


@contextlib.contextmanager
def _ops(engine):
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            yield connection


def _predecessor(engine):
    statements = (
        "CREATE TABLE billing_accounts (id VARCHAR(36) PRIMARY KEY, currency VARCHAR(3) NOT NULL)",
        "CREATE TABLE billing_subscriptions (id VARCHAR(36) PRIMARY KEY, billing_account_id VARCHAR(36) NOT NULL)",
        "CREATE TABLE entitlement_instances (id VARCHAR(36) PRIMARY KEY, billing_account_id VARCHAR(36) NOT NULL, subscription_id VARCHAR(36))",
        "CREATE TABLE credit_ledger_entries (id VARCHAR(36) PRIMARY KEY, billing_account_id VARCHAR(36), entry_type VARCHAR(32))",
        "CREATE TABLE legacy_ledger_sentinel (id INTEGER PRIMARY KEY, amount BIGINT NOT NULL)",
    )
    with engine.begin() as connection:
        if engine.dialect.name == "sqlite":
            connection.execute(sa.text("PRAGMA foreign_keys=ON"))
        for statement in statements:
            connection.execute(sa.text(statement))
        connection.execute(sa.text("INSERT INTO legacy_ledger_sentinel VALUES (1, 77)"))
    with _ops(engine):
        _revision("b2d4f6a8c0e3").upgrade()
    with _ops(engine):
        _revision(PARENT).upgrade()


def _upgrade(engine):
    with _ops(engine):
        _revision().upgrade()


def _new_engine(url):
    engine = sa.create_engine(url)

    @sa.event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


@pytest.fixture
def sqlite_engine(tmp_path):
    engine = _new_engine(f"sqlite:///{tmp_path / 'financial-cases.sqlite'}")
    _predecessor(engine)
    _upgrade(engine)
    yield engine
    engine.dispose()


@contextlib.contextmanager
def _postgres_schema(validate_test_database_url, postgres_schema_url):
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("local disposable PostgreSQL is not configured")
    base_url = validate_test_database_url(os.environ["TEST_DATABASE_URL"])
    schema = f"phase_5_3_{uuid.uuid4().hex}"
    admin = sa.create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    engine = sa.create_engine(postgres_schema_url(base_url, schema), pool_size=8)
    try:
        _predecessor(engine)
        _upgrade(engine)
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def postgres_engine(validate_test_database_url, postgres_schema_url):
    with _postgres_schema(validate_test_database_url, postgres_schema_url) as engine:
        yield engine


def _add_inbox(session, event_id, object_type, object_id, *, received_at=NOW):
    row = ExternalEventInbox(
        id=str(uuid.uuid4()),
        provider="stripe",
        event_id=event_id,
        event_type=f"{object_type}.updated",
        object_type=object_type,
        object_id=object_id,
        payload_digest=hashlib.sha256(event_id.encode()).hexdigest(),
        summary_json={},
        livemode=False,
        provider_created_at=received_at - timedelta(seconds=1),
        received_at=received_at,
        state="received",
        attempt_count=0,
    )
    session.add(row)
    session.flush()
    claimed = billing_inbox.claim_next_event(
        session, now=received_at + timedelta(seconds=2), lease_seconds=600,
    )
    assert claimed is not None and claimed.id == row.id
    billing_inbox.mark_processed(
        session, row.id, claimed.attempt_count, now=received_at + timedelta(seconds=3),
    )
    return row


def _financial_header(
    account_id, inbox_id, *, kind, object_type, object_id, version, effective_at,
    principal, discount=0,
):
    return {
        "billing_account_id": account_id,
        "kind": kind,
        "provider": "stripe",
        "object_type": object_type,
        "object_id": object_id,
        "external_version": version,
        "effective_at": effective_at,
        "currency": "usd",
        "principal_minor": principal,
        "tax_minor": 0,
        "fee_minor": 0,
        "discount_minor": discount,
        "gross_minor": principal + discount,
        "inbox_event_id": inbox_id,
    }


def _financial_line(line_id, line_kind, amount, *, discount=0):
    return {
        "external_line_id": line_id,
        "line_kind": line_kind,
        "source_type": "stripe_price",
        "source_id": f"price_{line_id}",
        "quantity": 1,
        "currency": "usd",
        "principal_minor": amount,
        "tax_minor": 0,
        "fee_minor": 0,
        "discount_minor": discount,
        "subscription_id": None,
        "entitlement_instance_id": None,
    }


def _seed_source(engine, *, source_line_kind="credit_pack", additional_lines=()):
    account_id = "account-one"
    source_version = "invoice:1"
    source_effective = NOW
    lines = [
        _financial_line("source-line", source_line_kind, 1000, discount=-100),
        *(_financial_line(*line) for line in additional_lines),
    ]
    with Session(engine, expire_on_commit=False) as session:
        session.execute(sa.text(
            "INSERT INTO billing_accounts (id,currency) VALUES (:id,'usd')"
        ), {"id": account_id})
        inbox = _add_inbox(session, "evt_source_invoice", "invoice", "in_source")
        principal = sum(line["principal_minor"] for line in lines)
        discount = sum(line["discount_minor"] for line in lines)
        source, _ = billing_financial.record_financial_transaction(
            session,
            _financial_header(
                account_id, inbox.id, kind="invoice", object_type="invoice",
                object_id="in_source", version=source_version,
                effective_at=source_effective, principal=principal, discount=discount,
            ),
            lines,
        )
        session.commit()
        return source.id, session.query(FinancialLine).filter_by(
            financial_transaction_id=source.id, external_line_id="source-line"
        ).one().id


def _seed_case_version(
    engine, source_id, *, case_type="refund", case_object_id="re_case",
    version=1, effective_at=None, received_at=None, principal=-200,
    conflict=False,
):
    effective_at = effective_at or (NOW + timedelta(minutes=version))
    received_at = received_at or (effective_at + timedelta(seconds=1))
    with Session(engine, expire_on_commit=False) as session:
        inbox = _add_inbox(
            session, f"evt_{case_object_id}_{version}", case_type,
            case_object_id, received_at=received_at,
        )
        event_tx, _ = billing_financial.record_financial_transaction(
            session,
            _financial_header(
                "account-one", inbox.id, kind=case_type, object_type=case_type,
                object_id=case_object_id, version=f"{case_type}:{version}",
                effective_at=effective_at, principal=principal,
            ),
            [_financial_line(f"event-line-{version}", "other", principal)],
        )
        if conflict:
            session.add(ExternalEventInboxConflict(
                id=str(uuid.uuid4()),
                inbox_event_id=inbox.id,
                conflicting_digest="f" * 64,
                state_at_detection="processed",
            ))
        session.commit()
        return event_tx.id


def _case_input(source_id, source_line_id, event_tx_id, *, state="refund_recorded",
                amount=200, disposition=None, allocation=None):
    if allocation is None:
        allocation = amount
    return {
        "billing_account_id": "account-one",
        "provider": "stripe",
        "case_type": "refund",
        "case_object_id": "re_case",
        "source_financial_transaction_id": source_id,
        "financial_transaction_id": event_tx_id,
        "state": state,
        "disposition": disposition,
        "cumulative_principal_minor": amount,
        "line_allocations": (
            [{"financial_line_id": source_line_id, "attributed_principal_minor": allocation}]
            if allocation else []
        ),
    }


def _record_case(engine, case):
    with Session(engine, expire_on_commit=False) as session:
        result = billing_financial_cases.record_financial_case_event(session, case)
        session.commit()
        return result[0].id, result[1].id if result[1] else None, result[2]


def _insert_case_version_direct(
    session, source_id, event_tx_id, *, cumulative_principal_minor, allocations,
):
    event_transaction = session.get(FinancialTransaction, event_tx_id)
    inbox_event = session.get(ExternalEventInbox, event_transaction.inbox_event_id)
    case_id, event_id = str(uuid.uuid4()), str(uuid.uuid4())
    state = "opened" if event_transaction.kind == "dispute" else "refund_recorded"
    session.add(FinancialCase(
        id=case_id,
        billing_account_id=event_transaction.billing_account_id,
        provider=event_transaction.provider,
        case_type=event_transaction.kind,
        case_object_id=event_transaction.object_id,
        source_financial_transaction_id=source_id,
        state=state,
        disposition=None,
        cumulative_principal_minor=cumulative_principal_minor,
        current_external_version=event_transaction.external_version,
        current_event_id=event_id,
        current_effective_at=event_transaction.effective_at,
        current_received_at=inbox_event.received_at,
    ))
    session.flush()
    session.add(FinancialCaseEvent(
        id=event_id,
        financial_case_id=case_id,
        financial_transaction_id=event_tx_id,
        inbox_event_id=inbox_event.id,
        external_version=event_transaction.external_version,
        event_fingerprint="a" * 64,
        state=state,
        disposition=None,
        cumulative_principal_minor=cumulative_principal_minor,
        effective_at=event_transaction.effective_at,
        received_at=inbox_event.received_at,
    ))
    session.flush()
    for financial_line_id, attributed_principal_minor in allocations:
        session.add(FinancialCaseEventLine(
            financial_case_event_id=event_id,
            financial_line_id=financial_line_id,
            attributed_principal_minor=attributed_principal_minor,
        ))
    session.flush()
    return case_id, event_id


def test_phase53_migration_is_linear_additive_and_model_consistent(sqlite_engine):
    script = ScriptDirectory(MIGRATIONS_DIR)
    heads = script.get_heads()
    assert len(heads) == 1
    assert script.get_revision(REVISION).down_revision == PARENT
    assert REVISION in {
        revision.revision
        for revision in script.iterate_revisions(heads[0], "base")
    }
    assert set((
        "financial_cases", "financial_case_events", "financial_case_event_lines",
        "financial_case_event_ledger_entries", "financial_case_source_fences",
    )).issubset(sa.inspect(sqlite_engine).get_table_names())
    for model in (
        FinancialCase, FinancialCaseEvent, FinancialCaseEventLine,
        FinancialCaseEventLedgerEntry, FinancialCaseSourceFence,
    ):
        assert {
            column["name"] for column in sa.inspect(sqlite_engine).get_columns(model.__tablename__)
        } == set(model.__table__.columns.keys())
    assert sa.inspect(sqlite_engine).get_table_names().__contains__("financial_transactions")
    assert sa.inspect(sqlite_engine).get_table_names().__contains__("external_event_inbox")


def test_empty_downgrade_removes_only_phase53_tables(sqlite_engine):
    _seed_source(sqlite_engine)
    with _ops(sqlite_engine):
        _revision().downgrade()
    tables = set(sa.inspect(sqlite_engine).get_table_names())
    assert not {
        "financial_cases", "financial_case_events", "financial_case_event_lines",
        "financial_case_event_ledger_entries", "financial_case_source_fences",
    } & tables
    assert {"financial_transactions", "financial_lines", "external_event_inbox"} <= tables


def test_downgrade_refuses_case_evidence(sqlite_engine):
    source_id, source_line_id = _seed_source(sqlite_engine)
    event_tx_id = _seed_case_version(sqlite_engine, source_id)
    _record_case(sqlite_engine, _case_input(source_id, source_line_id, event_tx_id))
    with pytest.raises(RuntimeError, match="downgrade may remove only empty tables"):
        with _ops(sqlite_engine):
            _revision().downgrade()


def test_case_recording_is_idempotent_immutable_and_does_not_touch_ledger(sqlite_engine):
    source_id, source_line_id = _seed_source(sqlite_engine)
    event_tx_id = _seed_case_version(sqlite_engine, source_id)
    case = _case_input(source_id, source_line_id, event_tx_id)
    case_id, event_id, outcome = _record_case(sqlite_engine, case)
    assert outcome == "inserted"
    assert _record_case(sqlite_engine, case) == (case_id, event_id, "duplicate")
    with Session(sqlite_engine) as session:
        assert session.query(FinancialCase).count() == 1
        assert session.query(FinancialCaseEvent).count() == 1
        assert session.query(FinancialCaseEventLine).count() == 1
        assert session.execute(sa.text("SELECT COUNT(*) FROM credit_ledger_entries")).scalar_one() == 0
        with pytest.raises(IntegrityError):
            session.execute(sa.text(
                "UPDATE financial_case_events SET state='won' WHERE id=:id"
            ), {"id": event_id})
            session.flush()
        session.rollback()


def test_case_preserves_exact_line_allocations_and_audit_references(sqlite_engine):
    source_id, first_line_id = _seed_source(
        sqlite_engine,
        additional_lines=(("source-line-2", "other", 505),),
    )
    with Session(sqlite_engine) as session:
        second_line_id = session.query(FinancialLine).filter_by(
            financial_transaction_id=source_id, external_line_id="source-line-2",
        ).one().id
    event_tx_id = _seed_case_version(
        sqlite_engine, source_id, version=7, principal=-317,
    )
    case = _case_input(source_id, first_line_id, event_tx_id, amount=317, allocation=109)
    case["line_allocations"] = [
        {"financial_line_id": first_line_id, "attributed_principal_minor": 109},
        {"financial_line_id": second_line_id, "attributed_principal_minor": 208},
    ]

    case_id, event_id, outcome = _record_case(sqlite_engine, case)

    assert outcome == "inserted"
    with Session(sqlite_engine) as session:
        event = session.get(FinancialCaseEvent, event_id)
        case_row = session.get(FinancialCase, case_id)
        event_transaction = session.get(FinancialTransaction, event_tx_id)
        inbox_event = session.get(ExternalEventInbox, event_transaction.inbox_event_id)
        allocations = {
            line.financial_line_id: line.attributed_principal_minor
            for line in session.query(FinancialCaseEventLine).filter_by(
                financial_case_event_id=event_id,
            )
        }
        assert allocations == {first_line_id: 109, second_line_id: 208}
        assert event.cumulative_principal_minor == 317
        assert event.financial_transaction_id == event_tx_id
        assert event.inbox_event_id == inbox_event.id
        assert event.external_version == event_transaction.external_version == "refund:7"
        assert event.effective_at == event_transaction.effective_at
        assert event.received_at == inbox_event.received_at
        assert event.event_fingerprint
        assert case_row.current_event_id == event.id


def test_case_principal_matches_signed_cumulative_financial_snapshot(sqlite_engine):
    source_id, source_line_id = _seed_source(sqlite_engine)
    mismatched_tx = _seed_case_version(sqlite_engine, source_id, principal=-1)
    with pytest.raises(
        billing_financial_cases.FinancialCaseInvariantError,
        match="signed financial transaction version",
    ):
        _record_case(
            sqlite_engine,
            _case_input(source_id, source_line_id, mismatched_tx, amount=200),
        )

    positive_tx = _seed_case_version(sqlite_engine, source_id, version=2, principal=200)
    with pytest.raises(
        billing_financial_cases.FinancialCaseInvariantError,
        match="signed financial transaction version",
    ):
        _record_case(
            sqlite_engine,
            _case_input(source_id, source_line_id, positive_tx, amount=200),
        )

    first_tx = _seed_case_version(sqlite_engine, source_id, version=3, principal=-200)
    case = _case_input(source_id, source_line_id, first_tx, amount=200)
    case_id, first_event, _ = _record_case(sqlite_engine, case)
    correction_tx = _seed_case_version(
        sqlite_engine, source_id, version=4, principal=-350,
    )
    correction = _case_input(source_id, source_line_id, correction_tx, amount=350)
    assert _record_case(sqlite_engine, correction)[0] == case_id
    reversal_tx = _seed_case_version(
        sqlite_engine, source_id, version=5, principal=-100,
    )
    reversal = _case_input(source_id, source_line_id, reversal_tx, amount=100)
    assert _record_case(sqlite_engine, reversal)[0] == case_id

    with Session(sqlite_engine) as session:
        current = session.get(FinancialCase, case_id)
        assert current.cumulative_principal_minor == 100
        assert current.current_event_id != first_event
        assert session.query(FinancialCaseEvent).filter_by(
            financial_case_id=case_id,
        ).count() == 3


def test_database_rejects_case_principal_mismatch(sqlite_engine):
    source_id, source_line_id = _seed_source(sqlite_engine)
    event_tx_id = _seed_case_version(sqlite_engine, source_id, principal=-1)
    with Session(sqlite_engine) as session:
        with pytest.raises(IntegrityError):
            _insert_case_version_direct(
                session, source_id, event_tx_id,
                cumulative_principal_minor=200,
                allocations=[(source_line_id, 200)],
            )
        session.rollback()
    with Session(sqlite_engine) as session:
        assert session.query(FinancialCase).count() == 0
        assert session.query(FinancialCaseEvent).count() == 0


@pytest.mark.postgres
def test_postgres_database_rejects_case_principal_mismatch(postgres_engine):
    source_id, source_line_id = _seed_source(postgres_engine)
    event_tx_id = _seed_case_version(postgres_engine, source_id, principal=-1)
    with Session(postgres_engine) as session:
        with pytest.raises(IntegrityError):
            _insert_case_version_direct(
                session, source_id, event_tx_id,
                cumulative_principal_minor=200,
                allocations=[(source_line_id, 200)],
            )
            session.commit()
        session.rollback()
    with Session(postgres_engine) as session:
        assert session.query(FinancialCase).count() == 0
        assert session.query(FinancialCaseEvent).count() == 0


def test_current_case_attributions_release_capacity_on_cumulative_correction(sqlite_engine):
    source_id, source_line_id = _seed_source(sqlite_engine)
    first_tx = _seed_case_version(
        sqlite_engine, source_id, case_object_id="re_case_a", version=1, principal=-800,
    )
    first = _case_input(source_id, source_line_id, first_tx, amount=800, allocation=800)
    first["case_object_id"] = "re_case_a"
    case_a_id, _, _ = _record_case(sqlite_engine, first)

    correction_tx = _seed_case_version(
        sqlite_engine, source_id, case_object_id="re_case_a", version=2, principal=-500,
    )
    correction = _case_input(
        source_id, source_line_id, correction_tx, amount=500, allocation=500,
    )
    correction["case_object_id"] = "re_case_a"
    _record_case(sqlite_engine, correction)

    reversal_tx = _seed_case_version(
        sqlite_engine, source_id, case_object_id="re_case_a", version=3, principal=0,
    )
    reversal = _case_input(
        source_id, source_line_id, reversal_tx, amount=0, allocation=0,
    )
    reversal["case_object_id"] = "re_case_a"
    _record_case(sqlite_engine, reversal)

    second_tx = _seed_case_version(
        sqlite_engine, source_id, case_object_id="re_case_b", principal=-900,
    )
    second = _case_input(
        source_id, source_line_id, second_tx, amount=900, allocation=900,
    )
    second["case_object_id"] = "re_case_b"
    _record_case(sqlite_engine, second)

    with Session(sqlite_engine) as session:
        current_total = session.execute(sa.text("""
            SELECT COALESCE(SUM(line.attributed_principal_minor), 0)
            FROM financial_case_event_lines AS line
            JOIN financial_cases AS case_row
              ON case_row.current_event_id = line.financial_case_event_id
            WHERE line.financial_line_id = :line_id
        """), {"line_id": source_line_id}).scalar_one()
        historical_total = session.execute(
            sa.select(sa.func.sum(FinancialCaseEventLine.attributed_principal_minor))
        ).scalar_one()
        assert current_total == 900
        assert historical_total == 2200
        assert session.get(FinancialCase, case_a_id).cumulative_principal_minor == 0


def test_sequential_current_cases_cannot_overattribute_source_line(sqlite_engine):
    source_id, source_line_id = _seed_source(sqlite_engine)
    first_tx = _seed_case_version(
        sqlite_engine, source_id, case_object_id="re_case_a", principal=-900,
    )
    first = _case_input(source_id, source_line_id, first_tx, amount=900, allocation=900)
    first["case_object_id"] = "re_case_a"
    _record_case(sqlite_engine, first)

    second_tx = _seed_case_version(
        sqlite_engine, source_id, case_object_id="re_case_b", principal=-900,
    )
    second = _case_input(source_id, source_line_id, second_tx, amount=900, allocation=900)
    second["case_object_id"] = "re_case_b"
    with pytest.raises(
        billing_financial_cases.FinancialCaseInvariantError,
        match="current case attributions",
    ):
        _record_case(sqlite_engine, second)

    with Session(sqlite_engine) as session:
        assert session.query(FinancialCase).count() == 1
        assert session.query(FinancialCaseEvent).count() == 1


def _assert_database_rejects_aggregate_overattribution(engine):
    source_id, source_line_id = _seed_source(engine)
    first_tx = _seed_case_version(
        engine, source_id, case_object_id="re_case_a", principal=-600,
    )
    first = _case_input(source_id, source_line_id, first_tx, amount=600, allocation=600)
    first["case_object_id"] = "re_case_a"
    _record_case(engine, first)

    second_tx = _seed_case_version(
        engine, source_id, case_object_id="re_case_b", principal=-600,
    )
    with Session(engine) as session:
        with pytest.raises(IntegrityError):
            _insert_case_version_direct(
                session, source_id, second_tx,
                cumulative_principal_minor=600,
                allocations=[(source_line_id, 600)],
            )
            session.commit()
        session.rollback()

    with Session(engine) as session:
        assert session.query(FinancialCase).count() == 1
        assert session.query(FinancialCaseEvent).count() == 1
        current_total = session.execute(sa.text("""
            SELECT COALESCE(SUM(line.attributed_principal_minor), 0)
            FROM financial_case_event_lines AS line
            JOIN financial_cases AS case_row
              ON case_row.current_event_id = line.financial_case_event_id
            WHERE line.financial_line_id = :line_id
        """), {"line_id": source_line_id}).scalar_one()
        assert current_total == 600


def test_database_rejects_aggregate_overattribution(sqlite_engine):
    _assert_database_rejects_aggregate_overattribution(sqlite_engine)


@pytest.mark.postgres
def test_postgres_database_rejects_aggregate_overattribution(postgres_engine):
    _assert_database_rejects_aggregate_overattribution(postgres_engine)


@pytest.mark.parametrize(
    "isolation_level", ["READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE"],
)
def test_postgres_concurrent_cases_cannot_overattribute_source_line(
    postgres_engine, isolation_level,
):
    source_id, source_line_id = _seed_source(postgres_engine)
    proposals = []
    for case_object_id in ("re_case_a", "re_case_b"):
        event_tx_id = _seed_case_version(
            postgres_engine, source_id, case_object_id=case_object_id, principal=-600,
        )
        case = _case_input(
            source_id, source_line_id, event_tx_id, amount=600, allocation=600,
        )
        case["case_object_id"] = case_object_id
        proposals.append(case)

    barrier = threading.Barrier(2)

    def record(case):
        with Session(postgres_engine) as session:
            session.execute(sa.text(f"SET TRANSACTION ISOLATION LEVEL {isolation_level}"))
            session.execute(
                sa.select(FinancialTransaction.id).where(
                    FinancialTransaction.id == source_id,
                )
            ).scalar_one()
            barrier.wait(timeout=10)
            try:
                result = billing_financial_cases.record_financial_case_event(session, case)
                session.commit()
                return result[2]
            except billing_financial_cases.FinancialCaseInvariantError:
                session.rollback()
                return "rejected"
            except sa.exc.DBAPIError as error:
                sqlstate = (
                    getattr(error.orig, "sqlstate", None)
                    or getattr(error.orig, "pgcode", None)
                )
                if sqlstate not in {"23514", "40001", "40P01"}:
                    raise
                session.rollback()
                return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(record, proposals))
    assert sorted(outcomes) == ["inserted", "rejected"]

    with Session(postgres_engine) as session:
        assert session.query(FinancialCase).count() == 1
        assert session.query(FinancialCaseEvent).count() == 1
        current_total = session.execute(sa.text("""
            SELECT COALESCE(SUM(line.attributed_principal_minor), 0)
            FROM financial_case_event_lines AS line
            JOIN financial_cases AS case_row
              ON case_row.current_event_id = line.financial_case_event_id
            WHERE line.financial_line_id = :line_id
        """), {"line_id": source_line_id}).scalar_one()
        assert current_total == 600


@pytest.mark.parametrize(
    "isolation_level", ["READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE"],
)
def test_postgres_competing_case_corrections_preserve_source_capacity(
    postgres_engine, isolation_level,
):
    source_id, source_line_id = _seed_source(postgres_engine)
    proposals = {}
    case_ids = {}
    initial_event_ids = {}

    for case_object_id in ("re_case_a", "re_case_b"):
        initial_tx = _seed_case_version(
            postgres_engine, source_id, case_object_id=case_object_id,
            version=1, principal=-300,
        )
        initial = _case_input(
            source_id, source_line_id, initial_tx, amount=300, allocation=300,
        )
        initial["case_object_id"] = case_object_id
        case_id, event_id, outcome = _record_case(postgres_engine, initial)
        assert outcome == "inserted"
        case_ids[case_object_id] = case_id
        initial_event_ids[case_object_id] = event_id

        correction_tx = _seed_case_version(
            postgres_engine, source_id, case_object_id=case_object_id,
            version=2, principal=-600,
        )
        correction = _case_input(
            source_id, source_line_id, correction_tx, amount=600, allocation=600,
        )
        correction["case_object_id"] = case_object_id
        proposals[case_object_id] = correction

    barrier = threading.Barrier(2)

    def record_correction(case_object_id, case):
        with Session(postgres_engine) as session:
            session.execute(sa.text(f"SET TRANSACTION ISOLATION LEVEL {isolation_level}"))
            session.execute(
                sa.select(FinancialTransaction.id).where(
                    FinancialTransaction.id == source_id,
                )
            ).scalar_one()
            barrier.wait(timeout=10)
            try:
                result = billing_financial_cases.record_financial_case_event(session, case)
                session.commit()
                return case_object_id, result[1].id, result[2]
            except billing_financial_cases.FinancialCaseInvariantError:
                session.rollback()
                return case_object_id, None, "rejected"
            except sa.exc.DBAPIError as error:
                sqlstate = (
                    getattr(error.orig, "sqlstate", None)
                    or getattr(error.orig, "pgcode", None)
                )
                if sqlstate not in {"23514", "40001", "40P01"}:
                    raise
                session.rollback()
                return case_object_id, None, "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda item: record_correction(*item),
            proposals.items(),
        ))
    outcomes = {case_object_id: outcome for case_object_id, _, outcome in results}
    assert sorted(outcomes.values()) == ["inserted", "rejected"]
    winner = next(name for name, outcome in outcomes.items() if outcome == "inserted")
    loser = next(name for name, outcome in outcomes.items() if outcome == "rejected")
    race_event_ids = {
        case_object_id: event_id
        for case_object_id, event_id, _ in results
    }
    assert race_event_ids[winner] is not None
    assert race_event_ids[loser] is None

    with Session(postgres_engine) as session:
        cases = {
            case.case_object_id: case
            for case in session.query(FinancialCase).all()
        }
        assert set(cases) == set(case_ids)
        assert {name: case.id for name, case in cases.items()} == case_ids
        assert cases[winner].current_external_version == "refund:2"
        assert cases[loser].current_external_version == "refund:1"
        assert cases[loser].current_event_id == initial_event_ids[loser]
        assert session.query(FinancialCaseEvent).count() == 3
        assert (
            session.get(FinancialCaseEvent, initial_event_ids[winner])
            .cumulative_principal_minor == 300
        )
        assert (
            session.get(FinancialCaseEvent, initial_event_ids[loser])
            .cumulative_principal_minor == 300
        )
        assert (
            session.get(FinancialCaseEvent, race_event_ids[winner])
            .cumulative_principal_minor == 600
        )
        assert session.query(FinancialCaseEvent).filter_by(
            financial_case_id=case_ids[loser],
        ).count() == 1
        current_total = session.execute(sa.text("""
            SELECT COALESCE(SUM(line.attributed_principal_minor), 0)
            FROM financial_case_event_lines AS line
            JOIN financial_cases AS case_row
              ON case_row.current_event_id = line.financial_case_event_id
            WHERE line.financial_line_id = :line_id
        """), {"line_id": source_line_id}).scalar_one()
        assert current_total == 900
        current_by_case = dict(session.execute(sa.text("""
            SELECT case_row.case_object_id,
                   COALESCE(SUM(line.attributed_principal_minor), 0)
            FROM financial_cases AS case_row
            JOIN financial_case_event_lines AS line
              ON line.financial_case_event_id = case_row.current_event_id
            WHERE case_row.source_financial_transaction_id = :source_id
            GROUP BY case_row.case_object_id
        """), {"source_id": source_id}).all())
        assert current_by_case == {winner: 600, loser: 300}

    release_tx = _seed_case_version(
        postgres_engine, source_id, case_object_id=winner,
        version=3, principal=-300,
    )
    release = _case_input(
        source_id, source_line_id, release_tx, amount=300, allocation=300,
    )
    release["case_object_id"] = winner
    _, release_event_id, release_outcome = _record_case(postgres_engine, release)
    assert release_outcome == "inserted"

    _, retry_event_id, retry_outcome = _record_case(postgres_engine, proposals[loser])
    assert retry_outcome == "inserted"

    with Session(postgres_engine) as session:
        cases = {
            case.case_object_id: case
            for case in session.query(FinancialCase).all()
        }
        assert cases[winner].current_external_version == "refund:3"
        assert cases[winner].cumulative_principal_minor == 300
        assert cases[loser].current_external_version == "refund:2"
        assert cases[loser].cumulative_principal_minor == 600
        assert session.query(FinancialCaseEvent).count() == 5
        assert session.query(FinancialCaseEvent).filter_by(
            financial_case_id=case_ids[winner],
        ).count() == 3
        assert session.query(FinancialCaseEvent).filter_by(
            financial_case_id=case_ids[loser],
        ).count() == 2
        assert session.get(FinancialCaseEvent, initial_event_ids[winner]) is not None
        assert session.get(FinancialCaseEvent, initial_event_ids[loser]) is not None
        assert session.get(FinancialCaseEvent, release_event_id) is not None
        assert session.get(FinancialCaseEvent, retry_event_id) is not None
        assert (
            session.get(FinancialCaseEvent, initial_event_ids[winner])
            .cumulative_principal_minor == 300
        )
        assert (
            session.get(FinancialCaseEvent, initial_event_ids[loser])
            .cumulative_principal_minor == 300
        )
        assert (
            session.get(FinancialCaseEvent, race_event_ids[winner])
            .cumulative_principal_minor == 600
        )
        assert (
            session.get(FinancialCaseEvent, release_event_id)
            .cumulative_principal_minor == 300
        )
        assert (
            session.get(FinancialCaseEvent, retry_event_id)
            .cumulative_principal_minor == 600
        )
        current_total = session.execute(sa.text("""
            SELECT COALESCE(SUM(line.attributed_principal_minor), 0)
            FROM financial_case_event_lines AS line
            JOIN financial_cases AS case_row
              ON case_row.current_event_id = line.financial_case_event_id
            WHERE line.financial_line_id = :line_id
        """), {"line_id": source_line_id}).scalar_one()
        assert current_total == 900
        current_by_case = dict(session.execute(sa.text("""
            SELECT case_row.case_object_id,
                   COALESCE(SUM(line.attributed_principal_minor), 0)
            FROM financial_cases AS case_row
            JOIN financial_case_event_lines AS line
              ON line.financial_case_event_id = case_row.current_event_id
            WHERE case_row.source_financial_transaction_id = :source_id
            GROUP BY case_row.case_object_id
        """), {"source_id": source_id}).all())
        assert current_by_case == {winner: 300, loser: 600}


def test_case_ledger_links_enforce_account_and_effect_type(sqlite_engine):
    source_id, source_line_id = _seed_source(sqlite_engine)
    event_tx_id = _seed_case_version(sqlite_engine, source_id)
    _, event_id, _ = _record_case(
        sqlite_engine, _case_input(source_id, source_line_id, event_tx_id)
    )
    invalid_links = (
        ("account-one", "dispute_hold", "hold"),
        ("account-other", "refund_reversal", "reversal"),
    )
    for account_id, entry_type, effect_type in invalid_links:
        with Session(sqlite_engine) as session:
            if account_id == "account-other":
                session.execute(sa.text(
                    "INSERT INTO billing_accounts (id,currency) VALUES (:id,'usd')"
                ), {"id": account_id})
            ledger_id = str(uuid.uuid4())
            session.execute(sa.text(
                "INSERT INTO credit_ledger_entries (id,billing_account_id,entry_type) "
                "VALUES (:id,:account_id,:entry_type)"
            ), {"id": ledger_id, "account_id": account_id, "entry_type": entry_type})
            session.add(FinancialCaseEventLedgerEntry(
                financial_case_event_id=event_id,
                credit_ledger_entry_id=ledger_id,
                effect_type=effect_type,
            ))
            with pytest.raises(IntegrityError):
                session.flush()
            session.rollback()


def _assert_ledger_entry_has_one_case_version_owner(engine):
    source_id, source_line_id = _seed_source(engine)
    first_tx = _seed_case_version(engine, source_id, principal=-200)
    first_case = _case_input(source_id, source_line_id, first_tx, amount=200)
    _, first_event_id, _ = _record_case(engine, first_case)

    correction_tx = _seed_case_version(
        engine, source_id, version=2, principal=-250,
    )
    correction_case = _case_input(
        source_id, source_line_id, correction_tx, amount=250,
    )
    _, correction_event_id, _ = _record_case(engine, correction_case)

    unrelated_tx = _seed_case_version(
        engine, source_id, case_object_id="re_other_case", principal=-200,
    )
    unrelated_case = _case_input(
        source_id, source_line_id, unrelated_tx, amount=200,
    )
    unrelated_case["case_object_id"] = "re_other_case"
    _, unrelated_event_id, _ = _record_case(engine, unrelated_case)

    ledger_entry_id = str(uuid.uuid4())
    correction_ledger_entry_id = str(uuid.uuid4())
    additional_correction_ledger_entry_id = str(uuid.uuid4())
    with Session(engine) as session:
        session.execute(sa.text(
            "INSERT INTO credit_ledger_entries (id,billing_account_id,entry_type) "
            "VALUES (:id,'account-one','refund_reversal'),"
            "(:correction_id,'account-one','refund_reversal'),"
            "(:additional_correction_id,'account-one','refund_reversal')"
        ), {
            "id": ledger_entry_id,
            "correction_id": correction_ledger_entry_id,
            "additional_correction_id": additional_correction_ledger_entry_id,
        })
        session.add_all([
            FinancialCaseEventLedgerEntry(
                financial_case_event_id=first_event_id,
                credit_ledger_entry_id=ledger_entry_id,
                effect_type="reversal",
            ),
            FinancialCaseEventLedgerEntry(
                financial_case_event_id=correction_event_id,
                credit_ledger_entry_id=correction_ledger_entry_id,
                effect_type="reversal",
            ),
            FinancialCaseEventLedgerEntry(
                financial_case_event_id=correction_event_id,
                credit_ledger_entry_id=additional_correction_ledger_entry_id,
                effect_type="reversal",
            ),
        ])
        session.commit()

    for event_id in (correction_event_id, unrelated_event_id):
        with Session(engine) as session:
            session.add(FinancialCaseEventLedgerEntry(
                financial_case_event_id=event_id,
                credit_ledger_entry_id=ledger_entry_id,
                effect_type="reversal",
            ))
            with pytest.raises(IntegrityError):
                session.flush()
            session.rollback()

    with Session(engine) as session:
        assert session.query(FinancialCaseEventLedgerEntry).count() == 3
        assert session.query(FinancialCaseEventLedgerEntry).filter_by(
            credit_ledger_entry_id=ledger_entry_id,
        ).one().financial_case_event_id == first_event_id
        assert session.query(FinancialCaseEventLedgerEntry).filter_by(
            credit_ledger_entry_id=correction_ledger_entry_id,
        ).one().financial_case_event_id == correction_event_id


def test_ledger_entry_has_one_case_version_owner(sqlite_engine):
    _assert_ledger_entry_has_one_case_version_owner(sqlite_engine)


@pytest.mark.postgres
def test_postgres_ledger_entry_has_one_case_version_owner(postgres_engine):
    _assert_ledger_entry_has_one_case_version_owner(postgres_engine)


def test_case_recorder_has_no_live_runtime_callers():
    app_dir = BACKEND_DIR / "app"
    callers = []
    for path in app_dir.rglob("*.py"):
        if path.name in {
            "billing_financial_cases.py", "billing_financial_effects.py", "models_billing_phase5.py", "models.py",
        }:
            continue
        if "billing_financial_cases" in path.read_text():
            callers.append(str(path.relative_to(BACKEND_DIR)))
    assert callers == []


def test_case_event_rejects_reused_version_with_different_evidence(sqlite_engine):
    source_id, source_line_id = _seed_source(sqlite_engine)
    event_tx_id = _seed_case_version(sqlite_engine, source_id)
    _record_case(sqlite_engine, _case_input(source_id, source_line_id, event_tx_id))
    changed = _case_input(
        source_id, source_line_id, event_tx_id, state="financial_only",
        disposition="financial_only", amount=200, allocation=200,
    )
    with pytest.raises(billing_financial_cases.FinancialCaseIdentityConflictError):
        with Session(sqlite_engine) as session:
            billing_financial_cases.record_financial_case_event(session, changed)


def test_stale_refund_case_version_is_ignored(sqlite_engine):
    source_id, source_line_id = _seed_source(sqlite_engine)
    initial_tx = _seed_case_version(
        sqlite_engine, source_id, effective_at=NOW + timedelta(hours=2),
    )
    initial = _case_input(source_id, source_line_id, initial_tx)
    initial["case_type"] = "refund"
    _record_case(sqlite_engine, initial)

    stale_tx = _seed_case_version(
        sqlite_engine, source_id, version=2,
        effective_at=NOW + timedelta(hours=1), principal=-150,
    )
    stale = _case_input(source_id, source_line_id, stale_tx, amount=150)
    assert _record_case(sqlite_engine, stale)[2] == "stale"
    with Session(sqlite_engine) as session:
        case_row = session.query(FinancialCase).one()
        assert case_row.current_external_version == "refund:1"
        assert session.query(FinancialCaseEvent).count() == 1


def test_same_effective_time_uses_received_time_as_ordering_tiebreaker(sqlite_engine):
    source_id, source_line_id = _seed_source(sqlite_engine)
    effective_at = NOW + timedelta(hours=2)
    first_tx = _seed_case_version(
        sqlite_engine, source_id, effective_at=effective_at,
        received_at=effective_at + timedelta(hours=1),
    )
    _record_case(sqlite_engine, _case_input(source_id, source_line_id, first_tx))
    later_tx = _seed_case_version(
        sqlite_engine, source_id, version=2, effective_at=effective_at,
        received_at=effective_at + timedelta(hours=2), principal=-250,
    )
    result = _case_input(source_id, source_line_id, later_tx, amount=250)
    assert _record_case(sqlite_engine, result)[2] == "inserted"
    with Session(sqlite_engine) as session:
        assert session.query(FinancialCase).one().current_external_version == "refund:2"


def test_case_attribution_cannot_exceed_eligible_source_principal(sqlite_engine):
    source_id, source_line_id = _seed_source(sqlite_engine)
    event_tx_id = _seed_case_version(sqlite_engine, source_id, principal=-950)
    invalid = _case_input(
        source_id, source_line_id, event_tx_id, amount=950, allocation=950,
    )
    with pytest.raises(billing_financial_cases.FinancialCaseInvariantError, match="source-line"):
        with Session(sqlite_engine) as session:
            billing_financial_cases.record_financial_case_event(session, invalid)
            session.commit()


def test_dispute_transitions_append_versions_and_reopen_from_terminal(sqlite_engine):
    source_id, source_line_id = _seed_source(sqlite_engine)
    case_object_id = "dp_case"
    first_tx = _seed_case_version(
        sqlite_engine, source_id, case_type="dispute", case_object_id=case_object_id,
        version=1, principal=-200,
    )
    first = _case_input(source_id, source_line_id, first_tx, state="opened")
    first.update(case_type="dispute", case_object_id=case_object_id)
    case_id, _, _ = _record_case(sqlite_engine, first)

    pending_tx = _seed_case_version(
        sqlite_engine, source_id, case_type="dispute", case_object_id=case_object_id,
        version=2, principal=-250,
    )
    pending = _case_input(source_id, source_line_id, pending_tx, state="pending", amount=250)
    pending.update(case_type="dispute", case_object_id=case_object_id)
    _record_case(sqlite_engine, pending)

    won_tx = _seed_case_version(
        sqlite_engine, source_id, case_type="dispute", case_object_id=case_object_id,
        version=3, principal=-250,
    )
    won = _case_input(source_id, source_line_id, won_tx, state="won", amount=250)
    won.update(case_type="dispute", case_object_id=case_object_id)
    _record_case(sqlite_engine, won)

    reopen_tx = _seed_case_version(
        sqlite_engine, source_id, case_type="dispute", case_object_id=case_object_id,
        version=4, principal=-250,
    )
    reopened = _case_input(source_id, source_line_id, reopen_tx, state="opened", amount=250)
    reopened.update(case_type="dispute", case_object_id=case_object_id)
    _record_case(sqlite_engine, reopened)
    with Session(sqlite_engine) as session:
        row = session.get(FinancialCase, case_id)
        assert row.state == "opened"
        assert row.cumulative_principal_minor == 250
        assert session.query(FinancialCaseEvent).count() == 4


def test_subscription_refund_requires_explicit_disposition_and_rollback_is_atomic(sqlite_engine):
    source_id, source_line_id = _seed_source(sqlite_engine, source_line_kind="subscription")
    event_tx_id = _seed_case_version(sqlite_engine, source_id)
    missing_disposition = _case_input(source_id, source_line_id, event_tx_id)
    with pytest.raises(billing_financial_cases.FinancialCaseInvariantError, match="explicit disposition"):
        with Session(sqlite_engine) as session:
            billing_financial_cases.record_financial_case_event(session, missing_disposition)

    approved = _case_input(
        source_id, source_line_id, event_tx_id,
        state="financial_only", disposition="financial_only",
    )
    with Session(sqlite_engine) as session:
        billing_financial_cases.record_financial_case_event(session, approved)
        session.rollback()
    with Session(sqlite_engine) as session:
        assert session.query(FinancialCase).count() == 0
        assert session.query(FinancialCaseEvent).count() == 0
    case_id, event_id, outcome = _record_case(sqlite_engine, approved)
    assert outcome == "inserted"
    with Session(sqlite_engine) as session:
        assert session.get(FinancialCase, case_id).disposition == "financial_only"
        event = session.get(FinancialCaseEvent, event_id)
        assert event.disposition == "financial_only"
        assert event.financial_transaction_id == event_tx_id
        assert event.inbox_event_id


def test_conflicted_inbox_evidence_cannot_support_a_case(sqlite_engine):
    source_id, source_line_id = _seed_source(sqlite_engine)
    event_tx_id = _seed_case_version(sqlite_engine, source_id, conflict=True)
    with pytest.raises(billing_financial_cases.FinancialCaseInvariantError, match="conflicted"):
        with Session(sqlite_engine) as session:
            billing_financial_cases.record_financial_case_event(
                session, _case_input(source_id, source_line_id, event_tx_id)
            )


def test_postgres_concurrent_duplicate_case_versions_converge(postgres_engine):
    source_id, source_line_id = _seed_source(postgres_engine)
    event_tx_id = _seed_case_version(postgres_engine, source_id)
    proposed = _case_input(source_id, source_line_id, event_tx_id)
    barrier = threading.Barrier(2)

    def record():
        with Session(postgres_engine, expire_on_commit=False) as session:
            barrier.wait(timeout=10)
            result = billing_financial_cases.record_financial_case_event(session, proposed)
            session.commit()
            return result[0].id, result[1].id, result[2]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: record(), range(2)))
    assert results[0][0] == results[1][0]
    assert results[0][1] == results[1][1]
    assert sorted(result[2] for result in results) == ["duplicate", "inserted"]
    with Session(postgres_engine) as session:
        assert session.query(FinancialCase).count() == 1
        assert session.query(FinancialCaseEvent).count() == 1


def test_postgres_case_recording_keeps_event_lines_atomic_across_savepoint(postgres_engine):
    source_id, source_line_id = _seed_source(postgres_engine)
    event_tx_id = _seed_case_version(postgres_engine, source_id)
    proposed = _case_input(source_id, source_line_id, event_tx_id)
    with Session(postgres_engine) as session:
        with session.begin():
            with session.begin_nested():
                result = billing_financial_cases.record_financial_case_event(session, proposed)
                assert result[2] == "inserted"
        assert session.query(FinancialCaseEventLine).count() == 1
    with Session(postgres_engine) as session:
        assert session.query(FinancialCaseEvent).count() == 1


def test_postgres_deferred_case_line_reconciliation_rejects_partial_commit(postgres_engine):
    source_id, source_line_id = _seed_source(postgres_engine)
    event_tx_id = _seed_case_version(postgres_engine, source_id)
    with Session(postgres_engine) as session:
        event_tx = session.get(FinancialTransaction, event_tx_id)
        inbox = session.get(ExternalEventInbox, event_tx.inbox_event_id)
        case_id, event_id = str(uuid.uuid4()), str(uuid.uuid4())
        session.add(FinancialCase(
            id=case_id,
            billing_account_id="account-one",
            provider="stripe",
            case_type="refund",
            case_object_id="re_case",
            source_financial_transaction_id=source_id,
            state="refund_recorded",
            disposition=None,
            cumulative_principal_minor=200,
            current_external_version=event_tx.external_version,
            current_event_id=event_id,
            current_effective_at=event_tx.effective_at,
            current_received_at=inbox.received_at,
        ))
        session.flush()
        session.add(FinancialCaseEvent(
            id=event_id,
            financial_case_id=case_id,
            financial_transaction_id=event_tx.id,
            inbox_event_id=inbox.id,
            external_version=event_tx.external_version,
            event_fingerprint="a" * 64,
            state="refund_recorded",
            disposition=None,
            cumulative_principal_minor=200,
            effective_at=event_tx.effective_at,
            received_at=inbox.received_at,
        ))
        with pytest.raises(IntegrityError):
            session.commit()
