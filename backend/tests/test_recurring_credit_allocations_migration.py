"""Database-boundary coverage for the additive Phase 6 migration."""

import contextlib
from datetime import datetime, timezone
import json
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

from app.models import RecurringCreditAllocation


BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = str(BACKEND_DIR / "migrations")
REVISION = "f5c8d3e0b2a1"
PARENT = "e4b7c2d9a1f0"
START = "2026-01-31 15:45:00+00:00"
END = "2026-02-28 15:45:00+00:00"
START_DT = datetime(2026, 1, 31, 15, 45, tzinfo=timezone.utc)
END_DT = datetime(2026, 2, 28, 15, 45, tzinfo=timezone.utc)
KEY = "period:free:account-one:2026-01-31T15:45:00Z"
_REVISION_MODULE = None


def _revision():
    global _REVISION_MODULE
    if _REVISION_MODULE is None:
        _REVISION_MODULE = ScriptDirectory(MIGRATIONS_DIR).get_revision(REVISION).module
    return _REVISION_MODULE


@contextlib.contextmanager
def _ops(engine):
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            yield connection
        connection.commit()


def _predecessor(engine):
    timestamp = "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "DATETIME"
    json_type = "JSON" if engine.dialect.name == "postgresql" else "TEXT"
    statements = (
        f"CREATE TABLE billing_accounts (id VARCHAR(36) PRIMARY KEY, currency VARCHAR(3) NOT NULL, account_anchor_at {timestamp} NOT NULL)",
        f"CREATE TABLE idempotency_registry (id VARCHAR(36) PRIMARY KEY, namespace VARCHAR(64) NOT NULL, key VARCHAR(255) NOT NULL, request_fingerprint VARCHAR(64) NOT NULL, state VARCHAR(24) NOT NULL, result_type VARCHAR(64), result_id VARCHAR(255), claimed_at {timestamp} NOT NULL, completed_at {timestamp}, last_error_code VARCHAR(120), UNIQUE(namespace,key))",
        f"CREATE TABLE entitlement_definitions (id VARCHAR(36) PRIMARY KEY, key VARCHAR(80) NOT NULL, version INTEGER NOT NULL, funding_policy_json {json_type} NOT NULL, effective_at {timestamp}, retired_at {timestamp}, approved_at {timestamp}, approval_evidence_reference VARCHAR(255))",
        f"CREATE TABLE billing_subscriptions (id VARCHAR(36) PRIMARY KEY, billing_account_id VARCHAR(36) NOT NULL, interval VARCHAR(16) NOT NULL, anchor_at {timestamp} NOT NULL, term_starts_at {timestamp} NOT NULL, term_ends_at {timestamp} NOT NULL, state VARCHAR(32) NOT NULL, current_entitlement_definition_id VARCHAR(36) NOT NULL)",
        f"CREATE TABLE entitlement_instances (id VARCHAR(36) PRIMARY KEY, billing_account_id VARCHAR(36) NOT NULL, entitlement_definition_id VARCHAR(36) NOT NULL, subscription_id VARCHAR(36), state VARCHAR(24) NOT NULL, starts_at {timestamp} NOT NULL, ends_at {timestamp}, source_type VARCHAR(40) NOT NULL)",
        f"CREATE TABLE credit_periods (id VARCHAR(36) PRIMARY KEY, billing_account_id VARCHAR(36) NOT NULL, entitlement_instance_id VARCHAR(36) NOT NULL, subscription_id VARCHAR(36), kind VARCHAR(32) NOT NULL, period_index INTEGER NOT NULL, anchor_at {timestamp} NOT NULL, starts_at {timestamp} NOT NULL, ends_at {timestamp} NOT NULL, planned_allocation_amount BIGINT NOT NULL, state VARCHAR(16) NOT NULL, funding_idempotency_registry_id VARCHAR(36), funded_lot_id VARCHAR(36))",
        f"CREATE TABLE credit_lots (id VARCHAR(36) PRIMARY KEY, billing_account_id VARCHAR(36) NOT NULL, source_type VARCHAR(40) NOT NULL, source_id VARCHAR(255) NOT NULL, original_amount BIGINT NOT NULL, available_at {timestamp} NOT NULL, expires_at {timestamp})",
        f"CREATE TABLE credit_ledger_entries (id VARCHAR(36) PRIMARY KEY, billing_account_id VARCHAR(36) NOT NULL, lot_id VARCHAR(36) NOT NULL, entry_type VARCHAR(32) NOT NULL, available_delta BIGINT NOT NULL, held_delta BIGINT NOT NULL, related_entry_id VARCHAR(36), idempotency_registry_id VARCHAR(36) NOT NULL, effective_at {timestamp} NOT NULL)",
        f"CREATE TABLE financial_transactions (id VARCHAR(36) PRIMARY KEY, billing_account_id VARCHAR(36) NOT NULL, kind VARCHAR(24) NOT NULL, currency VARCHAR(3) NOT NULL, principal_minor BIGINT NOT NULL, effective_at {timestamp} NOT NULL)",
        "CREATE TABLE financial_lines (id VARCHAR(36) PRIMARY KEY, financial_transaction_id VARCHAR(36) NOT NULL, line_kind VARCHAR(32) NOT NULL, principal_minor BIGINT NOT NULL, currency VARCHAR(3) NOT NULL, subscription_id VARCHAR(36), entitlement_instance_id VARCHAR(36))",
        f"CREATE TABLE domain_events (id VARCHAR(36) PRIMARY KEY, billing_account_id VARCHAR(36) NOT NULL, event_key VARCHAR(255) NOT NULL UNIQUE, event_type VARCHAR(120) NOT NULL, aggregate_type VARCHAR(80) NOT NULL, aggregate_id VARCHAR(255) NOT NULL, occurred_at {timestamp} NOT NULL, reference_ids_json {json_type} NOT NULL, request_fingerprint VARCHAR(64) NOT NULL)",
        "CREATE TABLE communication_outbox (id VARCHAR(36) PRIMARY KEY, domain_event_id VARCHAR(36) NOT NULL, billing_account_id VARCHAR(36) NOT NULL)",
    )
    with engine.begin() as connection:
        if engine.dialect.name == "sqlite":
            connection.execute(sa.text("PRAGMA foreign_keys=ON"))
        for statement in statements:
            connection.execute(sa.text(statement))


def _upgrade(engine):
    with _ops(engine):
        _revision().upgrade()


def _seed_free_predecessor(engine):
    funding = json.dumps({
        "schema_version": 1, "period_kind": "free", "credit_amount": 120,
    })
    with engine.begin() as connection:
        connection.execute(sa.text(
            "INSERT INTO billing_accounts VALUES ('account-one','usd',:start),"
            "('account-other','usd',:start)"
        ), {"start": START})
        connection.execute(sa.text("""
            INSERT INTO entitlement_definitions
              (id,key,version,funding_policy_json,effective_at,approved_at,
               approval_evidence_reference)
            VALUES ('definition-one','free',3,:funding,:start,:start,'approval:phase6')
        """), {"funding": funding, "start": START})
        connection.execute(sa.text("""
            INSERT INTO entitlement_instances
              (id,billing_account_id,entitlement_definition_id,subscription_id,
               state,starts_at,ends_at,source_type)
            VALUES ('instance-one','account-one','definition-one',NULL,
              'active',:start,'2027-01-31 15:45:00+00:00','free')
        """), {"start": START})
        connection.execute(sa.text("""
            INSERT INTO credit_periods
              (id,billing_account_id,entitlement_instance_id,subscription_id,
               kind,period_index,anchor_at,starts_at,ends_at,
               planned_allocation_amount,state)
            VALUES ('period-one','account-one','instance-one',NULL,'free',0,
              :start,:start,:end,120,'planned')
        """), {"start": START, "end": END})
        connection.execute(sa.text("""
            INSERT INTO idempotency_registry
              (id,namespace,key,request_fingerprint,state,claimed_at)
            VALUES ('registry-one','recurring_credit_allocation',:key,:fingerprint,
              'claimed',:start)
        """), {"key": KEY, "fingerprint": "a" * 64, "start": START})
        connection.execute(sa.text("""
            INSERT INTO domain_events
              (id,billing_account_id,event_key,event_type,aggregate_type,
               aggregate_id,occurred_at,reference_ids_json,request_fingerprint)
            VALUES ('event-one','account-one','credit_period_funded:period-one',
              'credit_period_funded','credit_period','period-one',:start,
              :references,:fingerprint)
        """), {
            "start": START, "references": json.dumps(["allocation-one", "period-one"]),
            "fingerprint": "e" * 64,
        })
        connection.execute(sa.text("""
            INSERT INTO communication_outbox
              (id,domain_event_id,billing_account_id)
            VALUES ('message-one','event-one','account-one')
        """))


def _allocation_insert(account="account-one", identifier="allocation-one"):
    return sa.text("""
        INSERT INTO recurring_credit_allocations (
          id,billing_account_id,credit_period_id,entitlement_instance_id,
          entitlement_definition_id,subscription_id,financial_line_id,
          idempotency_registry_id,domain_event_id,allocation_key,request_fingerprint,
          period_kind,period_index,period_starts_at,period_ends_at,credit_amount
        ) VALUES (
          :id,:account,'period-one','instance-one','definition-one',NULL,NULL,
          'registry-one','event-one',:key,:fingerprint,'free',0,:start,:end,120
        )
    """).bindparams(
        sa.bindparam("id", value=identifier),
        sa.bindparam("account", value=account),
        sa.bindparam("key", value=KEY),
        sa.bindparam("fingerprint", value="a" * 64),
        sa.bindparam("start", value=START_DT, type_=sa.DateTime(timezone=True)),
        sa.bindparam("end", value=END_DT, type_=sa.DateTime(timezone=True)),
    )


def _seed_monthly_predecessor(engine, *, financial_effective=START):
    funding = json.dumps({
        "schema_version": 1, "period_kind": "monthly_subscription",
        "credit_amount": 500,
    })
    key = "period:subscription:subscription-monthly:2026-01-31T15:45:00Z:pro@7"
    with engine.begin() as connection:
        connection.execute(sa.text(
            "INSERT INTO billing_accounts VALUES ('account-monthly','usd',:start)"
        ), {"start": START})
        connection.execute(sa.text("""
            INSERT INTO entitlement_definitions
              (id,key,version,funding_policy_json,effective_at,approved_at,
               approval_evidence_reference)
            VALUES ('definition-monthly','pro',7,:funding,:start,:start,
              'approval:phase6')
        """), {"funding": funding, "start": START})
        connection.execute(sa.text("""
            INSERT INTO billing_subscriptions
              (id,billing_account_id,interval,anchor_at,term_starts_at,
               term_ends_at,state,current_entitlement_definition_id)
            VALUES ('subscription-monthly','account-monthly','month',:start,
              :start,'2026-03-31 15:45:00+00:00','active','definition-monthly')
        """), {"start": START})
        connection.execute(sa.text("""
            INSERT INTO entitlement_instances
              (id,billing_account_id,entitlement_definition_id,subscription_id,
               state,starts_at,ends_at,source_type)
            VALUES ('instance-monthly','account-monthly','definition-monthly',
              'subscription-monthly','active',:start,
              '2026-03-31 15:45:00+00:00','subscription')
        """), {"start": START})
        connection.execute(sa.text("""
            INSERT INTO credit_periods
              (id,billing_account_id,entitlement_instance_id,subscription_id,
               kind,period_index,anchor_at,starts_at,ends_at,
               planned_allocation_amount,state)
            VALUES ('period-monthly','account-monthly','instance-monthly',
              'subscription-monthly','monthly_subscription',0,:start,:start,
              :end,500,'planned')
        """), {"start": START, "end": END})
        connection.execute(sa.text("""
            INSERT INTO financial_transactions
              (id,billing_account_id,kind,currency,principal_minor,effective_at)
            VALUES ('payment-monthly','account-monthly','payment','usd',10000,
              :effective)
        """), {"effective": financial_effective})
        connection.execute(sa.text("""
            INSERT INTO financial_lines
              (id,financial_transaction_id,line_kind,principal_minor,currency,
               subscription_id,entitlement_instance_id)
            VALUES ('line-monthly','payment-monthly','subscription',10000,'usd',
              'subscription-monthly','instance-monthly')
        """))
        connection.execute(sa.text("""
            INSERT INTO idempotency_registry
              (id,namespace,key,request_fingerprint,state,claimed_at)
            VALUES ('registry-monthly','recurring_credit_allocation',:key,
              :fingerprint,'claimed',:start)
        """), {"key": key, "fingerprint": "b" * 64, "start": START})
        connection.execute(sa.text("""
            INSERT INTO domain_events
              (id,billing_account_id,event_key,event_type,aggregate_type,
               aggregate_id,occurred_at,reference_ids_json,request_fingerprint)
            VALUES ('event-monthly','account-monthly',
              'credit_period_funded:period-monthly','credit_period_funded',
              'credit_period','period-monthly',:start,:references,:fingerprint)
        """), {
            "start": START,
            "references": json.dumps(["allocation-monthly", "period-monthly"]),
            "fingerprint": "f" * 64,
        })
        connection.execute(sa.text("""
            INSERT INTO communication_outbox
              (id,domain_event_id,billing_account_id)
            VALUES ('message-monthly','event-monthly','account-monthly')
        """))


def _monthly_allocation_insert():
    return sa.text("""
        INSERT INTO recurring_credit_allocations (
          id,billing_account_id,credit_period_id,entitlement_instance_id,
          entitlement_definition_id,subscription_id,financial_line_id,
          idempotency_registry_id,domain_event_id,allocation_key,request_fingerprint,
          period_kind,period_index,period_starts_at,period_ends_at,credit_amount
        ) VALUES (
          'allocation-monthly','account-monthly','period-monthly','instance-monthly',
          'definition-monthly','subscription-monthly','line-monthly',
          'registry-monthly','event-monthly',:key,:fingerprint,'monthly_subscription',0,
          :start,:end,500
        )
    """).bindparams(
        sa.bindparam(
            "key", value=(
                "period:subscription:subscription-monthly:"
                "2026-01-31T15:45:00Z:pro@7"
            ),
        ),
        sa.bindparam("fingerprint", value="b" * 64),
        sa.bindparam("start", value=START_DT, type_=sa.DateTime(timezone=True)),
        sa.bindparam("end", value=END_DT, type_=sa.DateTime(timezone=True)),
    )


@pytest.fixture
def sqlite_engine(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'phase6.sqlite'}")

    @sa.event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    _predecessor(engine)
    _upgrade(engine)
    yield engine
    engine.dispose()


@contextlib.contextmanager
def _postgres_engine(validate_test_database_url, postgres_schema_url):
    base_url = validate_test_database_url(os.environ["TEST_DATABASE_URL"])
    schema = f"phase6_{uuid.uuid4().hex}"
    admin = sa.create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    engine = sa.create_engine(postgres_schema_url(base_url, schema), pool_size=4)
    try:
        _predecessor(engine)
        _upgrade(engine)
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


def test_revision_extends_phase54_and_model_matches_schema(sqlite_engine):
    script = ScriptDirectory(MIGRATIONS_DIR)
    assert script.get_revision(REVISION).down_revision == PARENT
    assert script.get_heads() == ["d2f4a6c8e0b3"]  # Phase 14 extends Phase 12
    inspector = sa.inspect(sqlite_engine)
    assert {
        column.name for column in RecurringCreditAllocation.__table__.columns
    } == {
        column["name"] for column in inspector.get_columns(
            "recurring_credit_allocations"
        )
    }
    assert {
        constraint.name
        for constraint in RecurringCreditAllocation.__table__.constraints
        if constraint.name
    } == {
        constraint["name"]
        for constraint in (
            inspector.get_check_constraints("recurring_credit_allocations")
            + inspector.get_foreign_keys("recurring_credit_allocations")
            + inspector.get_unique_constraints("recurring_credit_allocations")
        )
        if constraint.get("name")
    }


def test_database_rejects_cross_account_and_mutable_allocation_evidence(sqlite_engine):
    _seed_free_predecessor(sqlite_engine)
    with pytest.raises(sa.exc.IntegrityError):
        with sqlite_engine.begin() as connection:
            connection.execute(_allocation_insert(account="account-other"))
    with sqlite_engine.begin() as connection:
        connection.execute(_allocation_insert())
    for statement in (
        "UPDATE recurring_credit_allocations SET credit_amount=121",
        "DELETE FROM recurring_credit_allocations",
    ):
        with pytest.raises(sa.exc.IntegrityError):
            with sqlite_engine.begin() as connection:
                connection.execute(sa.text(statement))


def test_database_enforces_monthly_payment_period(sqlite_engine):
    _seed_monthly_predecessor(
        sqlite_engine, financial_effective="2026-01-30 15:45:00+00:00",
    )
    with pytest.raises(sa.exc.IntegrityError):
        with sqlite_engine.begin() as connection:
            connection.execute(_monthly_allocation_insert())


def test_database_accepts_payment_at_monthly_period_boundary(sqlite_engine):
    _seed_monthly_predecessor(sqlite_engine, financial_effective=START)
    with sqlite_engine.begin() as connection:
        connection.execute(_monthly_allocation_insert())
    with sqlite_engine.connect() as connection:
        assert connection.execute(sa.text(
            "SELECT financial_line_id FROM recurring_credit_allocations "
            "WHERE id='allocation-monthly'"
        )).scalar_one() == "line-monthly"


def test_database_requires_funded_event_delivery_obligation(sqlite_engine):
    _seed_free_predecessor(sqlite_engine)
    with sqlite_engine.begin() as connection:
        connection.execute(sa.text("DELETE FROM communication_outbox"))
    with pytest.raises(sa.exc.IntegrityError):
        with sqlite_engine.begin() as connection:
            connection.execute(_allocation_insert())


def test_database_requires_expiration_event_delivery_obligation(sqlite_engine):
    _seed_free_predecessor(sqlite_engine)
    with sqlite_engine.begin() as connection:
        connection.execute(_allocation_insert())
        connection.execute(sa.text("""
            INSERT INTO credit_lots
              (id,billing_account_id,source_type,source_id,original_amount,
               available_at,expires_at)
            VALUES ('lot-one','account-one','free_recurring','period-one',120,
              :start,:end)
        """), {"start": START, "end": END})
        connection.execute(sa.text("""
            INSERT INTO credit_ledger_entries
              (id,billing_account_id,lot_id,entry_type,available_delta,
               held_delta,related_entry_id,idempotency_registry_id,effective_at)
            VALUES ('grant-one','account-one','lot-one','grant',120,0,NULL,
              'registry-one',:start)
        """), {"start": START})
        connection.execute(sa.text("""
            UPDATE credit_periods SET state='funded',
              funding_idempotency_registry_id='registry-one',funded_lot_id='lot-one'
            WHERE id='period-one'
        """))
    with pytest.raises(sa.exc.IntegrityError):
        with sqlite_engine.begin() as connection:
            connection.execute(sa.text("""
                INSERT INTO credit_ledger_entries
                  (id,billing_account_id,lot_id,entry_type,available_delta,
                   held_delta,related_entry_id,idempotency_registry_id,effective_at)
                VALUES ('expiration-one','account-one','lot-one','expiration',
                  -120,0,NULL,'registry-expiration',:end)
            """), {"end": END})

    with sqlite_engine.begin() as connection:
        connection.execute(sa.text("""
            INSERT INTO domain_events
              (id,billing_account_id,event_key,event_type,aggregate_type,
               aggregate_id,occurred_at,reference_ids_json,request_fingerprint)
            VALUES ('event-expired','account-one','credits_expired:period-one',
              'credits_expired','credit_period','period-one',:end,
              :references,:fingerprint)
        """), {
            "end": END,
            "references": json.dumps(["allocation-one", "period-one", "lot-one"]),
            "fingerprint": "1" * 64,
        })
        connection.execute(sa.text("""
            INSERT INTO communication_outbox
              (id,domain_event_id,billing_account_id)
            VALUES ('message-expired','event-expired','account-one')
        """))
        connection.execute(sa.text("""
            INSERT INTO idempotency_registry
              (id,namespace,key,request_fingerprint,state,claimed_at)
            VALUES ('registry-expiration','recurring_credit_expiration',
              'period:free:account-one:2026-01-31T15:45:00Z',:fingerprint,
              'claimed',:end)
        """), {"fingerprint": "2" * 64, "end": END})
        connection.execute(sa.text("""
            INSERT INTO credit_ledger_entries
              (id,billing_account_id,lot_id,entry_type,available_delta,
               held_delta,related_entry_id,idempotency_registry_id,effective_at)
            VALUES ('expiration-one','account-one','lot-one','expiration',
              -120,0,NULL,'registry-expiration',:end)
        """), {"end": END})
        connection.execute(sa.text(
            "UPDATE credit_periods SET state='expired' WHERE id='period-one'"
        ))


def test_empty_downgrade_removes_only_phase6_table(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'phase6-empty.sqlite'}")
    _predecessor(engine)
    _upgrade(engine)
    with _ops(engine):
        _revision().downgrade()
    tables = set(sa.inspect(engine).get_table_names())
    assert "recurring_credit_allocations" not in tables
    assert "credit_periods" in tables
    engine.dispose()


def test_downgrade_refuses_allocation_evidence(sqlite_engine):
    _seed_free_predecessor(sqlite_engine)
    with sqlite_engine.begin() as connection:
        connection.execute(_allocation_insert())
    with pytest.raises(_revision().RecurringAllocationsNotEmptyError):
        with _ops(sqlite_engine):
            _revision().downgrade()
    assert "recurring_credit_allocations" in sa.inspect(sqlite_engine).get_table_names()


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)
def test_postgres_constraints_truncate_and_downgrade_race(
    validate_test_database_url, postgres_schema_url,
):
    with _postgres_engine(validate_test_database_url, postgres_schema_url) as engine:
        _seed_free_predecessor(engine)
        with pytest.raises(sa.exc.IntegrityError):
            with engine.begin() as connection:
                connection.execute(_allocation_insert(account="account-other"))
        with engine.begin() as connection:
            connection.execute(sa.text("DELETE FROM communication_outbox"))
        with pytest.raises(sa.exc.IntegrityError):
            with engine.begin() as connection:
                connection.execute(_allocation_insert())
        with engine.begin() as connection:
            connection.execute(sa.text("""
                INSERT INTO communication_outbox
                  (id,domain_event_id,billing_account_id)
                VALUES ('message-one','event-one','account-one')
            """))

        writer = engine.connect()
        transaction = writer.begin()
        writer.execute(_allocation_insert())
        outcome = {}

        def downgrade():
            try:
                with _ops(engine) as connection:
                    outcome["pid"] = connection.execute(
                        sa.text("SELECT pg_backend_pid()")
                    ).scalar_one()
                    _revision().downgrade()
                outcome["result"] = "dropped"
            except _revision().RecurringAllocationsNotEmptyError as error:
                outcome["result"] = str(error)
            except Exception as error:  # pragma: no cover - surfaced below
                outcome["error"] = error

        thread = threading.Thread(target=downgrade)
        thread.start()
        waited = None
        for _ in range(100):
            time.sleep(0.05)
            if "pid" in outcome:
                with engine.connect() as probe:
                    waited = probe.execute(sa.text(
                        "SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid"
                    ), {"pid": outcome["pid"]}).scalar_one_or_none()
                if waited == "Lock":
                    break
        transaction.commit()
        writer.close()
        thread.join(20)
        assert waited == "Lock"
        assert not thread.is_alive()
        assert "error" not in outcome
        assert outcome.get("result") == (
            "cannot downgrade Phase 6 while recurring allocation evidence exists"
        )

        with pytest.raises(sa.exc.DBAPIError) as truncate_error:
            with engine.begin() as connection:
                connection.execute(sa.text("TRUNCATE recurring_credit_allocations"))
        assert getattr(truncate_error.value.orig, "sqlstate", None) == "23514"
        with engine.connect() as connection:
            assert connection.execute(sa.text(
                "SELECT count(*) FROM recurring_credit_allocations"
            )).scalar_one() == 1


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)
def test_postgres_blocks_direct_recurring_ledger_bypass(
    validate_test_database_url, postgres_schema_url,
):
    with _postgres_engine(validate_test_database_url, postgres_schema_url) as engine:
        _seed_free_predecessor(engine)

        with pytest.raises(sa.exc.DBAPIError) as missing_allocation:
            with engine.begin() as connection:
                connection.execute(sa.text("""
                    INSERT INTO credit_lots
                      (id,billing_account_id,source_type,source_id,original_amount,
                       available_at,expires_at)
                    VALUES ('lot-bypass','account-one','free_recurring',
                      'period-one',120,:start,:end)
                """), {"start": START, "end": END})
        assert getattr(missing_allocation.value.orig, "sqlstate", None) == "23514"

        with engine.begin() as connection:
            connection.execute(sa.text("""
                INSERT INTO credit_lots
                  (id,billing_account_id,source_type,source_id,original_amount,
                   available_at,expires_at)
                VALUES ('lot-pack','account-one','credit_pack_purchase',
                  'purchase-one',10,:start,NULL)
            """), {"start": START})
            connection.execute(_allocation_insert())
            connection.execute(sa.text("""
                INSERT INTO idempotency_registry
                  (id,namespace,key,request_fingerprint,state,claimed_at)
                VALUES ('registry-wrong','test','wrong',:fingerprint,
                  'completed',:start)
            """), {"fingerprint": "9" * 64, "start": START})

        with pytest.raises(sa.exc.DBAPIError) as wrong_claim:
            with engine.begin() as connection:
                connection.execute(sa.text("""
                    INSERT INTO credit_lots
                      (id,billing_account_id,source_type,source_id,original_amount,
                       available_at,expires_at)
                    VALUES ('lot-one','account-one','free_recurring',
                      'period-one',120,:start,:end)
                """), {"start": START, "end": END})
                connection.execute(sa.text("""
                    INSERT INTO credit_ledger_entries
                      (id,billing_account_id,lot_id,entry_type,available_delta,
                       held_delta,related_entry_id,idempotency_registry_id,effective_at)
                    VALUES ('grant-wrong','account-one','lot-one','grant',120,0,
                      NULL,'registry-wrong',:start)
                """), {"start": START})
        assert getattr(wrong_claim.value.orig, "sqlstate", None) == "23514"

        with engine.begin() as connection:
            connection.execute(sa.text("""
                INSERT INTO credit_lots
                  (id,billing_account_id,source_type,source_id,original_amount,
                   available_at,expires_at)
                VALUES ('lot-one','account-one','free_recurring',
                  'period-one',120,:start,:end)
            """), {"start": START, "end": END})
            connection.execute(sa.text("""
                INSERT INTO credit_ledger_entries
                  (id,billing_account_id,lot_id,entry_type,available_delta,
                   held_delta,related_entry_id,idempotency_registry_id,effective_at)
                VALUES ('grant-one','account-one','lot-one','grant',120,0,NULL,
                  'registry-one',:start)
            """), {"start": START})
            connection.execute(sa.text("""
                UPDATE credit_periods SET state='funded',
                  funding_idempotency_registry_id='registry-one',
                  funded_lot_id='lot-one' WHERE id='period-one'
            """))

        with pytest.raises(sa.exc.DBAPIError) as missing_expiration_event:
            with engine.begin() as connection:
                connection.execute(sa.text("""
                    INSERT INTO credit_ledger_entries
                      (id,billing_account_id,lot_id,entry_type,available_delta,
                       held_delta,related_entry_id,idempotency_registry_id,effective_at)
                    VALUES ('expiration-bypass','account-one','lot-one',
                      'expiration',-120,0,NULL,'registry-wrong',:end)
                """), {"end": END})
        assert getattr(
            missing_expiration_event.value.orig, "sqlstate", None,
        ) == "23514"

        with engine.begin() as connection:
            connection.execute(sa.text("""
                INSERT INTO domain_events
                  (id,billing_account_id,event_key,event_type,aggregate_type,
                   aggregate_id,occurred_at,reference_ids_json,request_fingerprint)
                VALUES ('event-expired','account-one',
                  'credits_expired:period-one','credits_expired','credit_period',
                  'period-one',:end,:references,:fingerprint)
            """), {
                "end": END,
                "references": json.dumps([
                    "allocation-one", "period-one", "lot-one",
                ]),
                "fingerprint": "1" * 64,
            })
            connection.execute(sa.text("""
                INSERT INTO communication_outbox
                  (id,domain_event_id,billing_account_id)
                VALUES ('message-expired','event-expired','account-one')
            """))
            connection.execute(sa.text("""
                INSERT INTO idempotency_registry
                  (id,namespace,key,request_fingerprint,state,claimed_at)
                VALUES ('registry-expiration','recurring_credit_expiration',
                  :key,:fingerprint,'claimed',:end)
            """), {
                "key": KEY, "fingerprint": "2" * 64, "end": END,
            })

        with pytest.raises(sa.exc.DBAPIError) as incomplete_expiration:
            with engine.begin() as connection:
                connection.execute(sa.text("""
                    INSERT INTO credit_ledger_entries
                      (id,billing_account_id,lot_id,entry_type,available_delta,
                       held_delta,related_entry_id,idempotency_registry_id,effective_at)
                    VALUES ('expiration-short','account-one','lot-one',
                      'expiration',-119,0,NULL,'registry-expiration',:end)
                """), {"end": END})
                connection.execute(sa.text(
                    "UPDATE credit_periods SET state='expired' WHERE id='period-one'"
                ))
        assert getattr(incomplete_expiration.value.orig, "sqlstate", None) == "23514"

        with engine.begin() as connection:
            connection.execute(sa.text("""
                INSERT INTO credit_ledger_entries
                  (id,billing_account_id,lot_id,entry_type,available_delta,
                   held_delta,related_entry_id,idempotency_registry_id,effective_at)
                VALUES ('expiration-one','account-one','lot-one','expiration',
                  -120,0,NULL,'registry-expiration',:end)
            """), {"end": END})
            connection.execute(sa.text(
                "UPDATE credit_periods SET state='expired' WHERE id='period-one'"
            ))
        with engine.connect() as connection:
            assert connection.execute(sa.text(
                "SELECT state FROM credit_periods WHERE id='period-one'"
            )).scalar_one() == "expired"


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)
@pytest.mark.parametrize("effective_at,accepted", (
    ("2026-01-30 15:45:00+00:00", False),
    (START, True),
))
def test_postgres_enforces_monthly_payment_period(
    validate_test_database_url, postgres_schema_url, effective_at, accepted,
):
    with _postgres_engine(validate_test_database_url, postgres_schema_url) as engine:
        _seed_monthly_predecessor(engine, financial_effective=effective_at)
        if accepted:
            with engine.begin() as connection:
                connection.execute(_monthly_allocation_insert())
        else:
            with pytest.raises(sa.exc.IntegrityError):
                with engine.begin() as connection:
                    connection.execute(_monthly_allocation_insert())
