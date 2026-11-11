"""Phase 5.2 immutable financial transaction and line foundations."""

import contextlib
import hashlib
import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.orm import Session

from app import billing_financial, billing_inbox
from app.models_billing_phase5 import FinancialLine, FinancialTransaction


BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = str(BACKEND_DIR / "migrations")
REVISION = "c3e5a7b9d1f4"
PARENT = "b2d4f6a8c0e3"
NOW = datetime.now(timezone.utc)
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
    timestamp = "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "DATETIME"
    statements = (
        "CREATE TABLE billing_accounts (id VARCHAR(36) PRIMARY KEY, currency VARCHAR(3) NOT NULL)",
        "CREATE TABLE billing_subscriptions (id VARCHAR(36) PRIMARY KEY, billing_account_id VARCHAR(36) NOT NULL)",
        "CREATE TABLE entitlement_instances (id VARCHAR(36) PRIMARY KEY, billing_account_id VARCHAR(36) NOT NULL, subscription_id VARCHAR(36))",
        "CREATE TABLE legacy_ledger_sentinel (id INTEGER PRIMARY KEY, amount BIGINT NOT NULL)",
    )
    with engine.begin() as connection:
        if engine.dialect.name == "sqlite":
            connection.execute(sa.text("PRAGMA foreign_keys=ON"))
        for statement in statements:
            connection.execute(sa.text(statement.format(timestamp=timestamp)))
        connection.execute(sa.text("INSERT INTO legacy_ledger_sentinel VALUES (1, 77)"))
    with _ops(engine):
        _revision(PARENT).upgrade()


def _upgrade(engine):
    with _ops(engine):
        _revision().upgrade()


def _downgrade(engine):
    with _ops(engine):
        _revision().downgrade()


@pytest.fixture
def sqlite_engine(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'financial.sqlite'}")

    @sa.event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    _predecessor(engine)
    _upgrade(engine)
    yield engine
    engine.dispose()


@contextlib.contextmanager
def _postgres_schema(validate_test_database_url, postgres_schema_url):
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("local disposable PostgreSQL is not configured")
    base_url = validate_test_database_url(os.environ["TEST_DATABASE_URL"])
    schema = f"phase_5_2_{uuid.uuid4().hex}"
    admin = sa.create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    engine = sa.create_engine(postgres_schema_url(base_url, schema), pool_size=6)
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


def _stripe_event(event_id="evt_financial001", object_id="in_financial001"):
    event = {
        "id": event_id,
        "object": "event",
        "api_version": "2024-06-20",
        "created": int(NOW.timestamp()),
        "livemode": False,
        "type": "invoice.paid",
        "data": {"object": {
            "id": object_id,
            "object": "invoice",
            "amount_paid": 1500,
            "currency": "usd",
            "status": "paid",
            "customer": "cus_financial001",
        }},
    }
    return json.dumps(event, sort_keys=True).encode(), event


def _seed_account_and_event(engine, *, account="account-one", event_id="evt_financial001"):
    with engine.begin() as connection:
        connection.execute(sa.text(
            "INSERT INTO billing_accounts (id,currency) VALUES (:id,'usd')"
        ), {"id": account})
    raw, event = _stripe_event(event_id)
    with Session(engine, expire_on_commit=False) as session:
        row, _ = billing_inbox.record_event(session, raw, event, now=NOW)
        session.commit()
        event_pk = row.id
    with Session(engine, expire_on_commit=False) as session:
        row = billing_inbox.claim_next_event(session, now=NOW, lease_seconds=600)
        session.commit()
        token = row.attempt_count
    with Session(engine) as session:
        billing_inbox.mark_processed(session, event_pk, token, now=NOW + timedelta(seconds=1))
        session.commit()
    return event_pk


def _header(event_pk, **updates):
    header = {
        "billing_account_id": "account-one",
        "kind": "invoice",
        "provider": "stripe",
        "object_type": "invoice",
        "object_id": "in_financial001",
        "external_version": "invoice:1",
        "effective_at": NOW,
        "currency": "usd",
        "principal_minor": 1500,
        "tax_minor": 80,
        "fee_minor": 20,
        "discount_minor": -100,
        "gross_minor": 1500,
        "inbox_event_id": event_pk,
    }
    header.update(updates)
    return header


def _lines(**first_updates):
    first = {
        "external_line_id": "il_subscription",
        "line_kind": "subscription",
        "source_type": "stripe_price",
        "source_id": "price_subscription",
        "quantity": 1,
        "currency": "usd",
        "principal_minor": 1000,
        "tax_minor": 80,
        "fee_minor": 0,
        "discount_minor": -100,
        "subscription_id": None,
        "entitlement_instance_id": None,
    }
    first.update(first_updates)
    return [first, {
        "external_line_id": "il_seat",
        "line_kind": "seat",
        "source_type": "stripe_price",
        "source_id": "price_seat",
        "quantity": 2,
        "currency": "usd",
        "principal_minor": 500,
        "tax_minor": 0,
        "fee_minor": 20,
        "discount_minor": 0,
        "subscription_id": None,
        "entitlement_instance_id": None,
    }]


def _record(engine, header, lines):
    with Session(engine, expire_on_commit=False) as session:
        row, outcome = billing_financial.record_financial_transaction(session, header, lines)
        session.commit()
        return row.id, outcome


def test_revision_is_linear_additive_and_empty(sqlite_engine):
    script = ScriptDirectory(MIGRATIONS_DIR)
    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == PARENT
    inspector = sa.inspect(sqlite_engine)
    assert {"financial_transactions", "financial_lines"}.issubset(inspector.get_table_names())
    assert {index["name"] for index in inspector.get_indexes("financial_transactions")} >= {
        "ix_financial_transactions_account_effective",
        "ix_financial_transactions_provider_object_effective",
        "ix_financial_transactions_inbox_event_id",
    }
    with sqlite_engine.connect() as connection:
        assert connection.execute(sa.text("SELECT amount FROM legacy_ledger_sentinel")).scalar_one() == 77
        assert connection.execute(sa.text("SELECT COUNT(*) FROM financial_transactions")).scalar_one() == 0
        assert connection.execute(sa.text("SELECT COUNT(*) FROM financial_lines")).scalar_one() == 0


def test_mixed_invoice_records_exact_integer_minor_units_and_sources(sqlite_engine):
    event_pk = _seed_account_and_event(sqlite_engine)
    transaction_id, outcome = _record(sqlite_engine, _header(event_pk), _lines())
    assert outcome == "inserted"
    with sqlite_engine.connect() as connection:
        transaction = connection.execute(sa.text("""
            SELECT principal_minor,tax_minor,fee_minor,discount_minor,gross_minor
            FROM financial_transactions WHERE id=:id
        """), {"id": transaction_id}).one()
        assert tuple(transaction) == (1500, 80, 20, -100, 1500)
        sources = connection.execute(sa.text("""
            SELECT external_line_id,line_kind,source_type,source_id,principal_minor,
                   tax_minor,fee_minor,discount_minor
            FROM financial_lines WHERE financial_transaction_id=:id ORDER BY external_line_id
        """), {"id": transaction_id}).all()
    assert [tuple(row) for row in sources] == [
        ("il_seat", "seat", "stripe_price", "price_seat", 500, 0, 20, 0),
        ("il_subscription", "subscription", "stripe_price", "price_subscription", 1000, 80, 0, -100),
    ]


@pytest.mark.parametrize("mutation", [
    lambda header, lines: header.update(principal_minor=1499, gross_minor=1499),
    lambda header, lines: lines[0].update(principal_minor=999),
    lambda header, lines: lines[0].update(principal_minor=1000.0),
    lambda header, lines: header.update(tax_minor=80.0),
])
def test_recorder_rejects_mismatch_and_floating_point(sqlite_engine, mutation):
    event_pk = _seed_account_and_event(sqlite_engine)
    header, lines = _header(event_pk), _lines()
    mutation(header, lines)
    with pytest.raises(billing_financial.FinancialInvariantError):
        _record(sqlite_engine, header, lines)


def test_business_version_is_idempotent_and_conflicts_fail(sqlite_engine):
    event_pk = _seed_account_and_event(sqlite_engine)
    first_id, first = _record(sqlite_engine, _header(event_pk), _lines())
    duplicate_id, duplicate = _record(sqlite_engine, _header(event_pk), list(reversed(_lines())))
    assert (first, duplicate, first_id == duplicate_id) == ("inserted", "duplicate", True)
    conflicting = _lines()
    conflicting[0]["source_id"] = "price_other"
    with pytest.raises(billing_financial.FinancialIdentityConflictError):
        _record(sqlite_engine, _header(event_pk), conflicting)


def test_out_of_order_versions_remain_distinct_immutable_facts(sqlite_engine):
    second_event = _seed_account_and_event(sqlite_engine, event_id="evt_financial002")
    first_raw, first_event = _stripe_event("evt_financial001")
    with Session(sqlite_engine, expire_on_commit=False) as session:
        first_row, _ = billing_inbox.record_event(session, first_raw, first_event, now=NOW)
        session.commit()
        first_event_pk = first_row.id
    with Session(sqlite_engine, expire_on_commit=False) as session:
        first_row = billing_inbox.claim_next_event(session, now=NOW, lease_seconds=600)
        session.commit()
        first_token = first_row.attempt_count
    with Session(sqlite_engine) as session:
        billing_inbox.mark_processed(
            session, first_event_pk, first_token, now=NOW + timedelta(seconds=1)
        )
        session.commit()

    second_id, _ = _record(
        sqlite_engine,
        _header(second_event, external_version="invoice:2", effective_at=NOW + timedelta(days=1)),
        _lines(),
    )
    first_id, _ = _record(
        sqlite_engine,
        _header(first_event_pk, external_version="invoice:1"),
        _lines(),
    )
    assert second_id != first_id
    with sqlite_engine.connect() as connection:
        assert connection.execute(sa.text(
            "SELECT COUNT(*) FROM financial_transactions WHERE object_id='in_financial001'"
        )).scalar_one() == 2


def test_inbox_evidence_must_match_provider_object_identity(sqlite_engine):
    event_pk = _seed_account_and_event(sqlite_engine)
    with pytest.raises(sa.exc.DBAPIError):
        _record(sqlite_engine, _header(event_pk, object_id="in_unrelated"), _lines())


def test_adjustment_can_use_authorized_internal_identity_without_external_inbox(sqlite_engine):
    with sqlite_engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO billing_accounts (id,currency) VALUES ('account-one','usd')"))
    header = _header(
        None, kind="adjustment", provider="jaspen", object_type="authorized_adjustment",
        object_id="adjustment-one", external_version="approval:1",
    )
    transaction_id, outcome = _record(sqlite_engine, header, _lines())
    assert outcome == "inserted"
    with sqlite_engine.connect() as connection:
        assert connection.execute(sa.text(
            "SELECT inbox_event_id FROM financial_transactions WHERE id=:id"
        ), {"id": transaction_id}).scalar_one_or_none() is None


def test_database_rejects_cross_account_links_and_currency_mismatch(sqlite_engine):
    event_pk = _seed_account_and_event(sqlite_engine)
    with sqlite_engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO billing_accounts (id,currency) VALUES ('account-two','usd')"))
        connection.execute(sa.text(
            "INSERT INTO billing_subscriptions (id,billing_account_id) VALUES ('subscription-two','account-two')"
        ))
    bad_lines = _lines(subscription_id="subscription-two")
    with pytest.raises(sa.exc.DBAPIError):
        _record(sqlite_engine, _header(event_pk), bad_lines)
    with pytest.raises(sa.exc.DBAPIError):
        _record(sqlite_engine, _header(event_pk, currency="eur"), [
            {**line, "currency": "eur"} for line in _lines()
        ])


def test_records_and_inbox_evidence_are_immutable_and_restricted(sqlite_engine):
    event_pk = _seed_account_and_event(sqlite_engine)
    transaction_id, _ = _record(sqlite_engine, _header(event_pk), _lines())
    statements = (
        ("UPDATE financial_transactions SET gross_minor=0 WHERE id=:id", {"id": transaction_id}),
        ("DELETE FROM financial_transactions WHERE id=:id", {"id": transaction_id}),
        ("UPDATE financial_lines SET principal_minor=0 WHERE financial_transaction_id=:id", {"id": transaction_id}),
        ("DELETE FROM financial_lines WHERE financial_transaction_id=:id", {"id": transaction_id}),
        ("DELETE FROM external_event_inbox WHERE id=:id", {"id": event_pk}),
    )
    for statement, params in statements:
        with pytest.raises(sa.exc.DBAPIError):
            with sqlite_engine.begin() as connection:
                connection.execute(sa.text(statement), params)


def test_empty_downgrade_and_populated_guard(sqlite_engine, tmp_path):
    _downgrade(sqlite_engine)
    assert not {"financial_transactions", "financial_lines"} & set(sa.inspect(sqlite_engine).get_table_names())

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'financial-populated.sqlite'}")
    @sa.event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")
    _predecessor(engine)
    _upgrade(engine)
    event_pk = _seed_account_and_event(engine)
    _record(engine, _header(event_pk), _lines())
    with pytest.raises(_revision().FinancialFoundationNotEmptyError, match="financial_transactions=1"):
        _downgrade(engine)
    assert {"financial_transactions", "financial_lines"}.issubset(sa.inspect(engine).get_table_names())
    engine.dispose()


def test_financial_recorder_has_no_live_runtime_importers():
    app_dir = BACKEND_DIR / "app"
    importers = []
    for path in app_dir.rglob("*.py"):
        if path.name in {"billing_financial.py", "models_billing_phase5.py", "models.py"}:
            continue
        text = path.read_text()
        if "billing_financial" in text or "FinancialTransaction" in text or "FinancialLine" in text:
            importers.append(str(path.relative_to(BACKEND_DIR)))
    assert importers == []


@pytest.mark.postgres
def test_postgres_deferred_reconciliation_and_truncate_guards(postgres_engine):
    event_pk = _seed_account_and_event(postgres_engine)
    transaction_id, _ = _record(postgres_engine, _header(event_pk), _lines())
    for table in ("financial_lines", "financial_transactions"):
        with pytest.raises(sa.exc.DBAPIError) as truncated:
            with postgres_engine.begin() as connection:
                connection.execute(sa.text(f"TRUNCATE {table} CASCADE"))
        assert getattr(truncated.value.orig, "sqlstate", None) == "23514"

    with pytest.raises(sa.exc.DBAPIError) as mismatch:
        with postgres_engine.begin() as connection:
            connection.execute(sa.text("""
                INSERT INTO financial_transactions
                  (id,billing_account_id,kind,provider,object_type,object_id,external_version,
                   effective_at,currency,principal_minor,tax_minor,fee_minor,discount_minor,
                   gross_minor,inbox_event_id)
                VALUES ('mismatch','account-one','invoice','stripe','invoice','in_other','invoice:2',
                  :now,'usd',10,0,0,0,10,:event)
            """), {"now": NOW, "event": event_pk})
            connection.execute(sa.text("""
                INSERT INTO financial_lines
                  (id,financial_transaction_id,external_line_id,line_kind,source_type,source_id,
                   quantity,currency,principal_minor,tax_minor,fee_minor,discount_minor)
                VALUES ('mismatch-line','mismatch','line','other','test','test',1,'usd',9,0,0,0)
            """))
    assert getattr(mismatch.value.orig, "sqlstate", None) == "23514"
    with postgres_engine.connect() as connection:
        assert connection.execute(sa.text(
            "SELECT COUNT(*) FROM financial_transactions WHERE id='mismatch'"
        )).scalar_one() == 0
        assert connection.execute(sa.text(
            "SELECT COUNT(*) FROM financial_transactions WHERE id=:id"
        ), {"id": transaction_id}).scalar_one() == 1

    with pytest.raises(sa.exc.DBAPIError) as late_line:
        with postgres_engine.begin() as connection:
            connection.execute(sa.text("""
                INSERT INTO financial_lines
                  (id,financial_transaction_id,external_line_id,line_kind,source_type,source_id,
                   quantity,currency,principal_minor,tax_minor,fee_minor,discount_minor)
                VALUES ('late-line',:transaction,'late','other','test','test',1,'usd',0,0,0,0)
            """), {"transaction": transaction_id})
    assert getattr(late_line.value.orig, "sqlstate", None) == "23514"


@pytest.mark.postgres
def test_postgres_concurrent_business_identity_converges(postgres_engine):
    event_pk = _seed_account_and_event(postgres_engine)
    barrier = threading.Barrier(4)
    outcomes, errors = [], []

    def worker():
        try:
            with Session(postgres_engine, expire_on_commit=False) as session:
                barrier.wait()
                row, outcome = billing_financial.record_financial_transaction(
                    session, _header(event_pk), _lines()
                )
                session.commit()
                outcomes.append((row.id, outcome))
        except Exception as exc:  # pragma: no cover - surfaced by assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(20)
    assert errors == []
    assert sorted(outcome for _, outcome in outcomes) == ["duplicate", "duplicate", "duplicate", "inserted"]
    assert len({identifier for identifier, _ in outcomes}) == 1


@pytest.mark.postgres
def test_postgres_downgrade_uses_exclusive_lock_and_refuses_data(postgres_engine):
    event_pk = _seed_account_and_event(postgres_engine)
    _record(postgres_engine, _header(event_pk), _lines())
    with pytest.raises(_revision().FinancialFoundationNotEmptyError):
        _downgrade(postgres_engine)
    assert "financial_transactions" in sa.inspect(postgres_engine).get_table_names()
