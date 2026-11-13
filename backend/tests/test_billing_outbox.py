"""Phase 5.4 domain-event and transactional-outbox contract tests."""

import contextlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import threading
import time
import uuid

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.orm import Session

from app.billing_outbox import (
    DomainEventConflictError,
    OutboxAttemptConflictError,
    StaleOutboxClaimError,
    claim_next_outbox_message,
    record_domain_event,
    record_outbox_attempt,
)


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRATIONS_DIR = os.path.join(BACKEND_DIR, "migrations")
PARENT_REVISION = "d3e5a7b9c1f4"
MIGRATION_REVISION = "e4b7c2d9a1f0"


def _revision():
    return ScriptDirectory(MIGRATIONS_DIR).get_revision(MIGRATION_REVISION).module


def _migration(revision):
    return ScriptDirectory(MIGRATIONS_DIR).get_revision(revision).module


@contextlib.contextmanager
def _migration_ops(engine):
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            yield connection
        connection.commit()


def _engine(path):
    engine = sa.create_engine(f"sqlite:///{path}")

    @sa.event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys = ON")

    with engine.begin() as connection:
        connection.execute(sa.text(
            "CREATE TABLE billing_accounts (id VARCHAR(36) PRIMARY KEY)"
        ))
        connection.execute(sa.text(
            "INSERT INTO billing_accounts (id) VALUES ('account-phase54')"
        ))
    with _migration_ops(engine):
        _revision().upgrade()
    return engine


@contextlib.contextmanager
def _postgres_outbox_engine(validate_test_database_url, postgres_schema_url):
    base_url = validate_test_database_url(os.environ["TEST_DATABASE_URL"])
    schema = f"phase54_{uuid.uuid4().hex}"
    admin_engine = sa.create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    engine = sa.create_engine(postgres_schema_url(base_url, schema), pool_size=8)
    try:
        with engine.begin() as connection:
            connection.execute(sa.text(
                "CREATE TABLE billing_accounts (id VARCHAR(36) PRIMARY KEY)"
            ))
            connection.execute(sa.text(
                "INSERT INTO billing_accounts (id) VALUES ('account-phase54')"
            ))
        with _migration_ops(engine):
            _revision().upgrade()
        yield engine
    finally:
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


def _insert_domain_event_direct(session, event_id, event_key, reference_ids):
    statement = sa.text("""
        INSERT INTO domain_events (
          id, billing_account_id, event_key, event_type, aggregate_type,
          aggregate_id, occurred_at, reference_ids_json, request_fingerprint
        ) VALUES (
          :id, 'account-phase54', :event_key, 'refund_recorded', 'refund',
          'refund-1', :occurred_at, :reference_ids, :fingerprint
        )
    """).bindparams(sa.bindparam("reference_ids", type_=sa.JSON))
    session.execute(statement, {
        "id": event_id,
        "event_key": event_key,
        "occurred_at": datetime(2026, 11, 12, 12, tzinfo=timezone.utc),
        "reference_ids": reference_ids,
        "fingerprint": "a" * 64,
    })


def _assert_database_reference_and_dedupe_contracts(engine):
    with Session(engine) as session:
        session.execute(sa.text(
            "INSERT INTO billing_accounts (id) VALUES ('account-other')"
        ))
        session.commit()

    invalid_references = (
        {"shadow_balance": 1000},
        [""],
        ["duplicate", "duplicate"],
        [123],
    )
    for index, reference_ids in enumerate(invalid_references):
        with Session(engine) as session:
            with pytest.raises(sa.exc.IntegrityError):
                _insert_domain_event_direct(
                    session, f"invalid-reference-{index}",
                    f"invalid:reference:{index}", reference_ids,
                )
                session.commit()
            session.rollback()

    with Session(engine) as session:
        _insert_domain_event_direct(
            session, "valid-reference-event", "valid:reference:v1",
            ["financial-case-event-1", "financial-transaction-1"],
        )
        _insert_domain_event_direct(
            session, "valid-empty-reference-event", "valid:empty-reference:v1", [],
        )
        session.commit()

    valid_key = (
        "message:valid-reference-event:v1:account-phase54:email"
    )
    with Session(engine) as session:
        session.execute(sa.text("""
            INSERT INTO communication_outbox (
              id, domain_event_id, billing_account_id, template_key,
              template_version, channel, locale, dedupe_key
            ) VALUES (
              'valid-message', 'valid-reference-event', 'account-phase54',
              'refund-confirmation', 'v1', 'email', 'en', :dedupe_key
            )
        """), {"dedupe_key": valid_key})
        session.commit()

    with Session(engine) as session:
        with pytest.raises(sa.exc.IntegrityError):
            session.execute(sa.text("""
                INSERT INTO communication_outbox (
                  id, domain_event_id, billing_account_id, template_key,
                  template_version, channel, locale, dedupe_key
                ) VALUES (
                  'invalid-key', 'valid-reference-event', 'account-phase54',
                  'refund-confirmation', 'v2', 'email', 'en', 'not-canonical'
                )
            """))
            session.commit()
        session.rollback()

    with Session(engine) as session:
        with pytest.raises(sa.exc.IntegrityError):
            session.execute(sa.text("""
                INSERT INTO communication_outbox (
                  id, domain_event_id, billing_account_id, template_key,
                  template_version, channel, locale, dedupe_key
                ) VALUES (
                  'cross-account', 'valid-reference-event', 'account-other',
                  'refund-confirmation', 'v4', 'email', 'en',
                  'message:valid-reference-event:v4:account-other:email'
                )
            """))
            session.commit()
        session.rollback()

    with Session(engine) as session:
        with pytest.raises(sa.exc.IntegrityError):
            session.execute(sa.text("""
                INSERT INTO communication_outbox (
                  id, domain_event_id, billing_account_id, template_key,
                  template_version, channel, locale, dedupe_key
                ) VALUES (
                  'invalid-separator', 'valid-reference-event', 'account-phase54',
                  'refund-confirmation', 'v:3', 'sms', 'en',
                  'message:valid-reference-event:v:3:account-phase54:sms'
                )
            """))
            session.commit()
        session.rollback()


def _phase52_predecessor(engine):
    statements = (
        "CREATE TABLE billing_accounts (id VARCHAR(36) PRIMARY KEY, currency VARCHAR(3) NOT NULL)",
        "CREATE TABLE billing_subscriptions (id VARCHAR(36) PRIMARY KEY, billing_account_id VARCHAR(36) NOT NULL)",
        "CREATE TABLE entitlement_instances (id VARCHAR(36) PRIMARY KEY, billing_account_id VARCHAR(36) NOT NULL, subscription_id VARCHAR(36))",
        "CREATE TABLE credit_ledger_entries (id VARCHAR(36) PRIMARY KEY, billing_account_id VARCHAR(36), entry_type VARCHAR(32))",
    )
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(sa.text(statement))
    for revision in ("b2d4f6a8c0e3", "c3e5a7b9d1f4"):
        with _migration_ops(engine):
            _migration(revision).upgrade()


def _event(key="refund:object-1:v1", occurred_at=None):
    return {
        "billing_account_id": "account-phase54",
        "event_key": key,
        "event_type": "refund_recorded",
        "aggregate_type": "refund",
        "aggregate_id": "refund-1",
        "occurred_at": occurred_at or datetime(2026, 11, 12, 12, tzinfo=timezone.utc),
        "reference_ids": ["financial-case-event-1", "financial-transaction-1"],
    }


def _delivery():
    return {
        "template_key": "refund-confirmation",
        "template_version": "v1",
        "channel": "email",
        "locale": "en",
    }


def test_revision_extends_phase53_and_models_match_additive_schema(tmp_path):
    script = ScriptDirectory(MIGRATIONS_DIR)
    migration = script.get_revision(MIGRATION_REVISION)
    assert migration.down_revision == PARENT_REVISION

    engine = _engine(tmp_path / "outbox-model.sqlite")
    from app.models_billing_phase5 import (
        CommunicationOutbox,
        CommunicationOutboxAttempt,
        DomainEvent,
    )

    inspector = sa.inspect(engine)
    for model in (DomainEvent, CommunicationOutbox, CommunicationOutboxAttempt):
        assert {
            column.name for column in model.__table__.columns
        } == {
            column["name"] for column in inspector.get_columns(model.__tablename__)
        }
        model_constraint_names = {
            constraint.name
            for constraint in model.__table__.constraints
            if constraint.name
        }
        database_constraint_names = {
            constraint["name"]
            for constraint in (
                inspector.get_check_constraints(model.__tablename__)
                + inspector.get_foreign_keys(model.__tablename__)
                + inspector.get_unique_constraints(model.__tablename__)
            )
            if constraint.get("name")
        }
        assert model_constraint_names == database_constraint_names
        assert [
            column.name for column in model.__table__.primary_key.columns
        ] == inspector.get_pk_constraint(model.__tablename__)["constrained_columns"]
    engine.dispose()


def test_database_enforces_reference_dedupe_and_account_contracts(tmp_path):
    engine = _engine(tmp_path / "outbox-database-contracts.sqlite")
    _assert_database_reference_and_dedupe_contracts(engine)
    engine.dispose()


def test_phase52_to_phase54_migration_chain_and_empty_rollback(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'outbox-chain.sqlite'}")

    @sa.event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys = ON")

    _phase52_predecessor(engine)
    with _migration_ops(engine):
        _migration(PARENT_REVISION).upgrade()
    with _migration_ops(engine):
        _revision().upgrade()

    table_names = set(sa.inspect(engine).get_table_names())
    assert {
        "financial_cases",
        "financial_case_events",
        "financial_case_event_lines",
        "domain_events",
        "communication_outbox",
        "communication_outbox_attempts",
    }.issubset(table_names)
    heads = ScriptDirectory(MIGRATIONS_DIR).get_heads()
    assert heads == [MIGRATION_REVISION]

    with _migration_ops(engine):
        _revision().downgrade()
    table_names = set(sa.inspect(engine).get_table_names())
    assert "financial_cases" in table_names
    assert not {
        "domain_events",
        "communication_outbox",
        "communication_outbox_attempts",
    } & table_names
    engine.dispose()


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)
def test_postgres_phase52_to_phase54_migration_chain_and_empty_rollback(
    validate_test_database_url, postgres_schema_url,
):
    base_url = validate_test_database_url(os.environ["TEST_DATABASE_URL"])
    schema = f"phase54_chain_{uuid.uuid4().hex}"
    admin_engine = sa.create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    engine = sa.create_engine(
        postgres_schema_url(base_url, schema), pool_pre_ping=True,
    )
    try:
        _phase52_predecessor(engine)
        with _migration_ops(engine):
            _migration(PARENT_REVISION).upgrade()
        with _migration_ops(engine):
            _revision().upgrade()

        table_names = set(sa.inspect(engine).get_table_names())
        assert {
            "financial_cases",
            "financial_case_events",
            "financial_case_event_lines",
            "domain_events",
            "communication_outbox",
            "communication_outbox_attempts",
        }.issubset(table_names)

        with _migration_ops(engine):
            _revision().downgrade()
        table_names = set(sa.inspect(engine).get_table_names())
        assert "financial_cases" in table_names
        assert not {
            "domain_events",
            "communication_outbox",
            "communication_outbox_attempts",
        } & table_names
    finally:
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


def test_event_and_outbox_are_atomic_immutable_idempotent_and_auditable(tmp_path):
    engine = _engine(tmp_path / "outbox-contract.sqlite")
    session = Session(engine)
    event, messages, state = record_domain_event(session, _event(), [_delivery()])
    assert state == "inserted"
    assert len(messages) == 1
    session.rollback()
    assert session.execute(sa.text("SELECT count(*) FROM domain_events")).scalar_one() == 0
    assert session.execute(sa.text("SELECT count(*) FROM communication_outbox")).scalar_one() == 0

    event, messages, state = record_domain_event(session, _event(), [_delivery()])
    session.commit()
    assert state == "inserted"
    event_id = event.id
    outbox_id = messages[0].id
    assert messages[0].dedupe_key == (
        f"message:{event_id}:v1:account-phase54:email"
    )

    replay, replay_messages, state = record_domain_event(session, _event(), [_delivery()])
    assert state == "duplicate"
    assert replay.id == event_id
    assert [message.id for message in replay_messages] == [outbox_id]
    with pytest.raises(DomainEventConflictError):
        record_domain_event(session, _event().copy() | {"event_type": "payment_succeeded"}, [_delivery()])
    session.rollback()

    with pytest.raises(sa.exc.IntegrityError):
        session.execute(sa.text(
            "UPDATE domain_events SET event_type = 'changed' WHERE id = :event_id"
        ), {"event_id": event_id})
        session.flush()
    session.rollback()
    with pytest.raises(sa.exc.IntegrityError):
        session.execute(sa.text(
            "UPDATE communication_outbox SET state = 'delivered' WHERE id = :outbox_id"
        ), {"outbox_id": outbox_id})
        session.flush()
    session.rollback()

    now = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)
    outbox, first_attempt = claim_next_outbox_message(
        session, now=now, lease_seconds=30,
    )
    assert outbox.id == outbox_id
    assert first_attempt == 1
    session.commit()

    retry_at = now + timedelta(minutes=5)
    assert record_outbox_attempt(
        session, outbox_id, first_attempt,
        outcome="retryable_failure",
        completed_at=now + timedelta(seconds=2),
        error_code="provider_unavailable",
        next_attempt_at=retry_at,
    ) == "completed"
    session.commit()
    outbox_row = session.execute(sa.text(
        "SELECT state, attempt_count, next_attempt_at "
        "FROM communication_outbox WHERE id = :outbox_id"
    ), {"outbox_id": outbox_id}).one()
    assert outbox_row.state == "retryable"
    assert outbox_row.attempt_count == 1
    assert record_outbox_attempt(
        session, outbox_id, first_attempt,
        outcome="retryable_failure",
        completed_at=now + timedelta(seconds=2),
        error_code="provider_unavailable",
        next_attempt_at=retry_at,
    ) == "duplicate"

    with pytest.raises(OutboxAttemptConflictError):
        record_outbox_attempt(
            session, outbox_id, first_attempt,
            outcome="retryable_failure",
            completed_at=now + timedelta(seconds=2),
            error_code="different_failure",
            next_attempt_at=retry_at,
        )
    session.rollback()

    outbox, second_attempt = claim_next_outbox_message(
        session, now=retry_at, lease_seconds=30,
    )
    assert second_attempt == 2
    session.commit()
    assert record_outbox_attempt(
        session, outbox_id, second_attempt,
        outcome="delivered",
        completed_at=retry_at + timedelta(seconds=2),
        provider_message_id="provider-msg-1",
    ) == "completed"
    session.commit()
    assert record_outbox_attempt(
        session, outbox_id, second_attempt,
        outcome="delivered",
        completed_at=retry_at + timedelta(seconds=2),
        provider_message_id="provider-msg-1",
    ) == "duplicate"

    final = session.execute(sa.text(
        "SELECT state, attempt_count, delivered_at "
        "FROM communication_outbox WHERE id = :outbox_id"
    ), {"outbox_id": outbox_id}).one()
    attempts = session.execute(sa.text(
        "SELECT attempt_number, outcome, error_code, provider_message_id "
        "FROM communication_outbox_attempts WHERE outbox_id = :outbox_id "
        "ORDER BY attempt_number"
    ), {"outbox_id": outbox_id}).all()
    assert final.state == "delivered"
    assert final.attempt_count == 2
    assert [(row.attempt_number, row.outcome) for row in attempts] == [
        (1, "retryable_failure"), (2, "delivered"),
    ]
    assert attempts[0].error_code == "provider_unavailable"
    assert attempts[1].provider_message_id == "provider-msg-1"
    with pytest.raises(sa.exc.IntegrityError):
        session.execute(sa.text(
            "DELETE FROM communication_outbox_attempts WHERE outbox_id = :outbox_id"
        ), {"outbox_id": outbox_id})
        session.flush()
    session.rollback()

    migration = _revision()
    with pytest.raises(migration.BillingOutboxNotEmptyError):
        with _migration_ops(engine):
            migration.downgrade()
    assert "communication_outbox" in sa.inspect(engine).get_table_names()
    session.close()
    engine.dispose()


def test_empty_downgrade_removes_only_phase54_tables(tmp_path):
    engine = _engine(tmp_path / "outbox-empty-downgrade.sqlite")
    with _migration_ops(engine):
        _revision().downgrade()
    assert not {
        "domain_events",
        "communication_outbox",
        "communication_outbox_attempts",
    }.intersection(sa.inspect(engine).get_table_names())
    assert "billing_accounts" in sa.inspect(engine).get_table_names()
    engine.dispose()


def test_outbox_service_has_no_live_runtime_callers():
    app_dir = Path(BACKEND_DIR) / "app"
    callers = []
    for path in app_dir.rglob("*.py"):
        if path.name in {"billing_outbox.py", "models_billing_phase5.py", "models.py"}:
            continue
        if "billing_outbox" in path.read_text():
            callers.append(str(path.relative_to(BACKEND_DIR)))
    assert callers == []


def test_expired_claim_is_audited_and_cannot_complete_after_reclaim(tmp_path):
    engine = _engine(tmp_path / "outbox-expired-claim.sqlite")
    session = Session(engine)
    _, messages, _ = record_domain_event(session, _event(), [_delivery()])
    session.commit()
    now = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)
    outbox_id = messages[0].id
    _, first_attempt = claim_next_outbox_message(
        session, now=now, lease_seconds=30,
    )
    session.commit()
    _, second_attempt = claim_next_outbox_message(
        session, now=now + timedelta(seconds=31), lease_seconds=30,
    )
    assert second_attempt == first_attempt + 1
    session.commit()

    with pytest.raises(StaleOutboxClaimError):
        record_outbox_attempt(
            session, outbox_id, first_attempt,
            outcome="delivered",
            completed_at=now + timedelta(seconds=32),
            provider_message_id="late-provider-result",
        )
    session.rollback()
    rows = session.execute(sa.text(
        "SELECT attempt_number, outcome, error_code "
        "FROM communication_outbox_attempts WHERE outbox_id = :outbox_id "
        "ORDER BY attempt_number"
    ), {"outbox_id": outbox_id}).all()
    assert [(row.attempt_number, row.outcome) for row in rows] == [
        (1, "retryable_failure"), (2, "started"),
    ]
    assert rows[0].error_code == "delivery_lease_expired"
    session.close()
    engine.dispose()


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)
def test_postgres_outbox_skip_locked_claims_and_trigger_projection(
    validate_test_database_url, postgres_schema_url,
):
    with _postgres_outbox_engine(
        validate_test_database_url, postgres_schema_url,
    ) as engine:
        with Session(engine, expire_on_commit=False) as seed:
            _, first_messages, _ = record_domain_event(
                seed, _event("refund:one:v1"), [_delivery()],
            )
            _, second_messages, _ = record_domain_event(
                seed, _event("refund:two:v1"), [_delivery()],
            )
            first_message_id = first_messages[0].id
            second_message_id = second_messages[0].id
            seed.commit()

        with Session(engine) as first, Session(engine) as second:
            now = datetime.now(timezone.utc)
            first_claim, _ = claim_next_outbox_message(first, now=now, lease_seconds=60)
            second_claim, _ = claim_next_outbox_message(second, now=now, lease_seconds=60)
            assert first_claim.id != second_claim.id
            assert {first_claim.id, second_claim.id} == {
                first_message_id, second_message_id,
            }
            first.commit()
            second.commit()

        barrier = threading.Barrier(2)

        def _record_same_event():
            with Session(engine) as session:
                barrier.wait(timeout=10)
                event_row, messages, state = record_domain_event(
                    session, _event("refund:concurrent:v1"), [_delivery()],
                )
                session.commit()
                return event_row.id, [message.id for message in messages], state

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _index: _record_same_event(), range(2)))
        assert sorted(result[2] for result in results) == ["duplicate", "inserted"]
        assert results[0][0] == results[1][0]
        assert results[0][1] == results[1][1]
        with Session(engine) as verification:
            assert verification.execute(sa.text(
                "SELECT count(*) FROM domain_events WHERE event_key = 'refund:concurrent:v1'"
            )).scalar_one() == 1
            assert verification.execute(sa.text(
                "SELECT count(*) FROM communication_outbox WHERE domain_event_id = :event_id"
            ), {"event_id": results[0][0]}).scalar_one() == 1


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)
def test_postgres_database_enforces_reference_dedupe_and_account_contracts(
    validate_test_database_url, postgres_schema_url,
):
    with _postgres_outbox_engine(
        validate_test_database_url, postgres_schema_url,
    ) as engine:
        _assert_database_reference_and_dedupe_contracts(engine)


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)
@pytest.mark.parametrize("statement", (
    "TRUNCATE communication_outbox_attempts",
    "TRUNCATE communication_outbox CASCADE",
    "TRUNCATE domain_events CASCADE",
    "TRUNCATE domain_events, communication_outbox, communication_outbox_attempts",
))
def test_postgres_truncate_cannot_remove_phase54_evidence(
    validate_test_database_url, postgres_schema_url, statement,
):
    with _postgres_outbox_engine(
        validate_test_database_url, postgres_schema_url,
    ) as engine:
        with Session(engine, expire_on_commit=False) as session:
            _, messages, _ = record_domain_event(session, _event(), [_delivery()])
            outbox_id = messages[0].id
            session.commit()
            claim_next_outbox_message(
                session, now=datetime.now(timezone.utc), lease_seconds=60,
            )
            session.commit()

        with Session(engine) as session:
            with pytest.raises(sa.exc.DBAPIError) as exc_info:
                session.execute(sa.text(statement))
                session.commit()
            session.rollback()
        assert getattr(exc_info.value.orig, "sqlstate", None) == "23514"
        assert "cannot be truncated" in str(exc_info.value.orig)
        with engine.connect() as connection:
            assert connection.execute(sa.text(
                "SELECT count(*) FROM domain_events"
            )).scalar_one() == 1
            assert connection.execute(sa.text(
                "SELECT count(*) FROM communication_outbox WHERE id = :id"
            ), {"id": outbox_id}).scalar_one() == 1
            assert connection.execute(sa.text(
                "SELECT count(*) FROM communication_outbox_attempts"
            )).scalar_one() == 1


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)
def test_postgres_downgrade_waits_for_concurrent_insert_and_refuses(
    validate_test_database_url, postgres_schema_url,
):
    with _postgres_outbox_engine(
        validate_test_database_url, postgres_schema_url,
    ) as engine:
        writer = engine.connect()
        writer_transaction = writer.begin()
        writer.execute(sa.text("""
            INSERT INTO domain_events (
              id, billing_account_id, event_key, event_type, aggregate_type,
              aggregate_id, occurred_at, reference_ids_json, request_fingerprint
            ) VALUES (
              'downgrade-race', 'account-phase54', 'downgrade:race:v1',
              'refund_recorded', 'refund', 'refund-1', now(), '[]', :fingerprint
            )
        """), {"fingerprint": "a" * 64})
        module = _revision()
        outcome = {}

        def run_downgrade():
            try:
                with _migration_ops(engine) as connection:
                    outcome["pid"] = connection.execute(
                        sa.text("SELECT pg_backend_pid()")
                    ).scalar_one()
                    module.downgrade()
                outcome["result"] = "dropped"
            except module.BillingOutboxNotEmptyError as error:
                outcome["result"] = str(error)
            except Exception as error:  # pragma: no cover - surfaced below
                outcome["error"] = error

        thread = threading.Thread(target=run_downgrade)
        thread.start()
        waited = None
        for _ in range(60):
            time.sleep(0.05)
            if "pid" in outcome:
                with engine.connect() as probe:
                    waited = probe.execute(sa.text(
                        "SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"
                    ), {"pid": outcome["pid"]}).scalar_one_or_none()
                if waited == "Lock":
                    break
        writer_transaction.commit()
        writer.close()
        thread.join(20)

        assert waited == "Lock"
        assert not thread.is_alive()
        assert "error" not in outcome
        assert outcome.get("result") == (
            "cannot downgrade Phase 5.4 while event or outbox evidence exists"
        )
        assert "domain_events" in sa.inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert connection.execute(sa.text(
                "SELECT count(*) FROM domain_events WHERE id = 'downgrade-race'"
            )).scalar_one() == 1
