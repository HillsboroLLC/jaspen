"""Migration and database-invariant coverage for Phase 4."""

import contextlib
from datetime import datetime, timezone
from functools import lru_cache
import os
import uuid

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRATIONS_DIR = os.path.join(BACKEND_DIR, "migrations")
REVISION = "f9c1a3e5b7d4"
PARENT = "e8b0f2d4a6c3"
NOW = "2026-01-31 15:45:00+00:00"
END = "2027-01-31 15:45:00+00:00"


@lru_cache(maxsize=1)
def _revision():
    return ScriptDirectory(MIGRATIONS_DIR).get_revision(REVISION).module


@contextlib.contextmanager
def _ops(engine):
    with engine.connect() as connection:
        if connection.dialect.name == "sqlite":
            connection.execute(sa.text("PRAGMA foreign_keys=ON"))
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            yield connection
        connection.commit()


def _predecessor(engine):
    timestamp_type = "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "DATETIME"
    statements = (
        "CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)",
        f"CREATE TABLE billing_accounts (id VARCHAR(36) PRIMARY KEY, account_anchor_at {timestamp_type} NOT NULL)",
        f"""CREATE TABLE idempotency_registry (
            id VARCHAR(36) PRIMARY KEY, state VARCHAR(24), result_type VARCHAR(64),
            result_id VARCHAR(255), completed_at {timestamp_type}, last_error_code VARCHAR(120))""",
        """CREATE TABLE credit_lots (
            id VARCHAR(36) PRIMARY KEY, billing_account_id VARCHAR(36) NOT NULL,
            source_type VARCHAR(40) NOT NULL, source_id VARCHAR(255) NOT NULL,
            original_amount BIGINT NOT NULL, available_at {timestamp_type} NOT NULL,
            expires_at {timestamp_type}, origin_evidence_json JSON NOT NULL,
            UNIQUE (billing_account_id, source_type, source_id))""",
        """CREATE TABLE credit_ledger_entries (
            id VARCHAR(36) PRIMARY KEY, billing_account_id VARCHAR(36) NOT NULL,
            lot_id VARCHAR(36) NOT NULL, entry_type VARCHAR(32) NOT NULL,
            available_delta BIGINT NOT NULL, held_delta BIGINT NOT NULL,
            idempotency_registry_id VARCHAR(36) NOT NULL UNIQUE,
            effective_at {timestamp_type} NOT NULL, actor_type VARCHAR(40) NOT NULL,
            actor_id VARCHAR(255) NOT NULL, reason_code VARCHAR(120) NOT NULL,
            evidence_json JSON NOT NULL)""",
        "CREATE TABLE legacy_sentinel (id INTEGER PRIMARY KEY, value VARCHAR(40))",
    )
    statements = tuple(statement.format(timestamp_type=timestamp_type) for statement in statements)
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(sa.text(statement))
        connection.execute(sa.text("INSERT INTO legacy_sentinel VALUES (1,'preserved')"))


def _upgrade(engine):
    with _ops(engine):
        _revision().upgrade()


def _downgrade(engine):
    with _ops(engine):
        _revision().downgrade()


@pytest.fixture
def sqlite_engine(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'phase4.sqlite'}")
    _predecessor(engine)
    yield engine
    engine.dispose()


def _seed_base(connection, suffix="one", exclusivity="base-plan"):
    connection.execute(sa.text(
        "INSERT INTO billing_accounts (id,account_anchor_at) VALUES (:account,:anchor)"
    ), {"account": f"account-{suffix}", "anchor": NOW})
    definition_insert = sa.text("""
        INSERT INTO entitlement_definitions
          (id,key,version,exclusivity_key,capability_json,funding_policy_json,
           effective_at,approved_at,approval_evidence_reference)
        VALUES (:id,:key,1,:exclusive,:capabilities,:funding,
          :now,:now,'approval:test')
    """).bindparams(
        sa.bindparam("capabilities", type_=sa.JSON()),
        sa.bindparam("funding", type_=sa.JSON()),
    )
    connection.execute(definition_insert, {
        "id": f"definition-{suffix}", "key": f"plan-{suffix}",
        "exclusive": exclusivity, "now": NOW,
        "capabilities": {"schema_version": 1, "capabilities": {"analysis": True}},
        "funding": {"schema_version": 1, "period_kind": "free", "credit_amount": 100},
    })
    instance_insert = sa.text("""
        INSERT INTO entitlement_instances
          (id,billing_account_id,entitlement_definition_id,state,starts_at,ends_at,
           source_type,source_id,approval_evidence_reference)
        VALUES (:id,:account,:definition,'proposed',:now,:end,'free',:source,'approval:test')
    """)
    connection.execute(instance_insert, {
        "id": f"instance-{suffix}", "account": f"account-{suffix}",
        "definition": f"definition-{suffix}", "now": NOW, "end": END,
        "source": f"source-{suffix}",
    })


def _claim(connection, identifier):
    connection.execute(sa.text(
        "INSERT INTO idempotency_registry (id,state) VALUES (:id,'claimed')"
    ), {"id": identifier})


def _event(connection, suffix, from_state, to_state, claim):
    _claim(connection, claim)
    event_insert = sa.text("""
        INSERT INTO entitlement_events
          (id,entitlement_instance_id,transition,from_state,to_state,effective_at,
           actor_type,actor_id,source_type,source_id,idempotency_registry_id,evidence_json)
        VALUES (:id,:instance,:transition,:from_state,:to_state,:now,
          'test','phase4','test','phase4',:claim,:evidence)
    """).bindparams(sa.bindparam("evidence", type_=sa.JSON()))
    connection.execute(event_insert, {
        "id": f"event-{claim}", "instance": f"instance-{suffix}",
        "transition": f"{from_state}_to_{to_state}", "from_state": from_state,
        "to_state": to_state, "now": NOW, "claim": claim,
        "evidence": {"test_only": True},
    })


def test_revision_is_linear_and_schema_is_complete(sqlite_engine):
    script = ScriptDirectory(MIGRATIONS_DIR)
    assert script.get_revision(REVISION).down_revision == PARENT
    assert script.get_heads() == [REVISION]
    _upgrade(sqlite_engine)
    inspector = sa.inspect(sqlite_engine)
    assert set(_revision().PHASE_4_TABLES).issubset(inspector.get_table_names())
    assert {column["name"] for column in inspector.get_columns("credit_periods")} >= {
        "billing_account_id", "entitlement_instance_id", "period_index",
        "funding_idempotency_registry_id", "funded_lot_id",
    }
    assert {index["name"] for index in inspector.get_indexes("entitlement_instances")} >= {
        "ix_entitlement_instances_account_state_interval",
    }
    with sqlite_engine.connect() as connection:
        assert connection.execute(sa.text("SELECT value FROM legacy_sentinel")).scalar_one() == "preserved"


def test_event_is_authoritative_and_direct_state_changes_are_rejected(sqlite_engine):
    _upgrade(sqlite_engine)
    with sqlite_engine.begin() as connection:
        _seed_base(connection)
        _event(connection, "one", "proposed", "scheduled", "claim-scheduled")
        assert connection.execute(sa.text(
            "SELECT state,last_event_id FROM entitlement_instances WHERE id='instance-one'"
        )).one() == ("scheduled", "event-claim-scheduled")
        with pytest.raises(sa.exc.IntegrityError, match="authoritative event"):
            connection.execute(sa.text(
                "UPDATE entitlement_instances SET state='active' WHERE id='instance-one'"
            ))
        _event(connection, "one", "scheduled", "active", "claim-active")
        assert connection.execute(sa.text(
            "SELECT state FROM entitlement_instances WHERE id='instance-one'"
        )).scalar_one() == "active"
        with pytest.raises(sa.exc.IntegrityError, match="append-only"):
            connection.execute(sa.text(
                "DELETE FROM entitlement_events WHERE id='event-claim-active'"
            ))


def test_exclusivity_and_later_authority_sources_are_enforced(sqlite_engine):
    _upgrade(sqlite_engine)
    with sqlite_engine.begin() as connection:
        _seed_base(connection, "one", "base-plan")
        _event(connection, "one", "proposed", "scheduled", "claim-one")
        connection.execute(sa.text("""
            INSERT INTO entitlement_definitions
              (id,key,version,exclusivity_key,capability_json,funding_policy_json,
               effective_at,approved_at,approval_evidence_reference)
            SELECT 'definition-two','plan-two',1,'base-plan',capability_json,
              funding_policy_json,effective_at,approved_at,approval_evidence_reference
            FROM entitlement_definitions WHERE id='definition-one'
        """))
        connection.execute(sa.text("""
            INSERT INTO entitlement_instances
              (id,billing_account_id,entitlement_definition_id,state,starts_at,ends_at,
               source_type,source_id,approval_evidence_reference)
            VALUES ('instance-two','account-one','definition-two','proposed',:now,:end,
              'free','source-two','approval:test')
        """), {"now": NOW, "end": END})
        with pytest.raises(sa.exc.IntegrityError, match="overlap"):
            _event(connection, "two", "proposed", "scheduled", "claim-two")
        connection.execute(sa.text("""
            INSERT INTO entitlement_instances
              (id,billing_account_id,entitlement_definition_id,state,starts_at,ends_at,
               source_type,source_id,approval_evidence_reference)
            VALUES ('future-offer','account-one','definition-one','proposed',:now,:end,
              'promotion','offer-not-yet-authoritative','approval:test')
        """), {"now": NOW, "end": END})
        _claim(connection, "claim-offer")
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(sa.text("""
                INSERT INTO entitlement_events
                  (id,entitlement_instance_id,transition,from_state,to_state,effective_at,
                   actor_type,actor_id,source_type,source_id,idempotency_registry_id,evidence_json)
                VALUES ('event-offer','future-offer','schedule','proposed','scheduled',:now,
                  'test','phase4','test','phase4','claim-offer','{}')
            """), {"now": NOW})


def test_subscription_dunning_cancellation_and_expiration_do_not_change_entitlement(sqlite_engine):
    _upgrade(sqlite_engine)
    with sqlite_engine.begin() as connection:
        _seed_base(connection)
        subscription_insert = sa.text("""
            INSERT INTO billing_subscriptions
              (id,billing_account_id,processor,external_subscription_id,interval,
               anchor_at,term_starts_at,term_ends_at,state,
               current_entitlement_definition_id,origin_evidence_json)
            VALUES ('subscription','account-one','stripe','sub_test','month',
              :now,:now,:end,'active','definition-one',:evidence)
        """).bindparams(sa.bindparam("evidence", type_=sa.JSON()))
        connection.execute(subscription_insert, {
            "now": NOW, "end": END, "evidence": {"test_only": True},
        })
        for state in ("past_due", "unpaid", "active", "cancel_at_period_end", "expired"):
            connection.execute(sa.text(
                "UPDATE billing_subscriptions SET state=:state WHERE id='subscription'"
            ), {"state": state})
            assert connection.execute(sa.text(
                "SELECT state FROM entitlement_instances WHERE id='instance-one'"
            )).scalar_one() == "proposed"
        with pytest.raises(sa.exc.IntegrityError, match="invalid subscription transition"):
            connection.execute(sa.text(
                "UPDATE billing_subscriptions SET state='active' WHERE id='subscription'"
            ))


def test_period_anchor_interval_and_funded_lot_provenance(sqlite_engine):
    _upgrade(sqlite_engine)
    with sqlite_engine.begin() as connection:
        _seed_base(connection)
        connection.execute(sa.text("""
            INSERT INTO credit_periods
              (id,billing_account_id,entitlement_instance_id,kind,period_index,
               anchor_at,starts_at,ends_at,planned_allocation_amount,state)
            VALUES ('period-one','account-one','instance-one','free',0,
              :anchor,:start,:end,100,'planned')
        """), {"anchor": NOW, "start": NOW, "end": "2026-02-28 15:45:00+00:00"})
        with pytest.raises(sa.exc.IntegrityError, match="boundaries"):
            connection.execute(sa.text("""
                INSERT INTO credit_periods
                  (id,billing_account_id,entitlement_instance_id,kind,period_index,
                   anchor_at,starts_at,ends_at,planned_allocation_amount,state)
                VALUES ('period-bad','account-one','instance-one','free',1,
                  :anchor,'2026-02-27 15:45:00+00:00','2026-03-31 15:45:00+00:00',100,'planned')
            """), {"anchor": NOW})
        _claim(connection, "claim-fund")
        lot_insert = sa.text("""
            INSERT INTO credit_lots
              (id,billing_account_id,source_type,source_id,original_amount,
               available_at,expires_at,origin_evidence_json)
            VALUES ('lot-one','account-one','free_recurring','period-one',100,
              :start,:end,:evidence)
        """).bindparams(sa.bindparam("evidence", type_=sa.JSON()))
        connection.execute(lot_insert, {
            "start": NOW, "end": "2026-02-28 15:45:00+00:00",
            "evidence": {"test_only": True},
        })
        connection.execute(sa.text("""
            INSERT INTO credit_ledger_entries
              (id,billing_account_id,lot_id,entry_type,available_delta,held_delta,
               idempotency_registry_id,effective_at,actor_type,actor_id,reason_code,evidence_json)
            VALUES ('grant-one','account-one','lot-one','grant',100,0,'claim-fund',
              :now,'test','phase4','credit_period_funded','{}')
        """), {"now": NOW})
        connection.execute(sa.text("""
            UPDATE credit_periods SET state='funded',
              funding_idempotency_registry_id='claim-fund',funded_lot_id='lot-one'
            WHERE id='period-one'
        """))
        assert connection.execute(sa.text(
            "SELECT state,funded_lot_id FROM credit_periods WHERE id='period-one'"
        )).one() == ("funded", "lot-one")
        with pytest.raises(sa.exc.IntegrityError, match="historical"):
            connection.execute(sa.text("DELETE FROM credit_periods WHERE id='period-one'"))


def test_empty_downgrade_and_each_table_guard(sqlite_engine, tmp_path):
    _upgrade(sqlite_engine)
    _downgrade(sqlite_engine)
    assert not set(_revision().PHASE_4_TABLES) & set(sa.inspect(sqlite_engine).get_table_names())

    for table in _revision().PHASE_4_TABLES:
        engine = sa.create_engine(f"sqlite:///{tmp_path / (table + '.sqlite')}")
        _predecessor(engine)
        _upgrade(engine)
        with engine.begin() as connection:
            _seed_base(connection)
            if table == "entitlement_events":
                _event(connection, "one", "proposed", "cancelled", "claim-event")
            elif table == "credit_periods":
                connection.execute(sa.text("""
                    INSERT INTO credit_periods
                      (id,billing_account_id,entitlement_instance_id,kind,period_index,
                       anchor_at,starts_at,ends_at,planned_allocation_amount,state)
                    VALUES ('period','account-one','instance-one','free',0,:anchor,:start,:end,1,'planned')
                """), {"anchor": NOW, "start": NOW, "end": "2026-02-28 15:45:00+00:00"})
            # Base seeding already populates definition and instance. A subscription
            # requires its own row; all guards are checked independently by a fresh DB.
            elif table == "billing_subscriptions":
                connection.execute(sa.text("""
                    INSERT INTO billing_subscriptions
                      (id,billing_account_id,processor,external_subscription_id,interval,
                       anchor_at,term_starts_at,term_ends_at,state,
                       current_entitlement_definition_id,origin_evidence_json)
                    VALUES ('subscription','account-one','stripe','sub_test','month',
                      :now,:now,:end,'proposed','definition-one','{}')
                """), {"now": NOW, "end": END})
        with pytest.raises(_revision().EntitlementFoundationNotEmptyError, match="refusing"):
            _downgrade(engine)
        engine.dispose()


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)
def test_postgres_phase_4_event_projection_overlap_and_period_guards(
    validate_test_database_url,
    postgres_schema_url,
):
    base_url = validate_test_database_url(os.environ["TEST_DATABASE_URL"])
    schema = f"phase_4_{uuid.uuid4().hex}"
    admin_engine = sa.create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    engine = sa.create_engine(postgres_schema_url(base_url, schema))
    try:
        _predecessor(engine)
        _upgrade(engine)
        with engine.begin() as connection:
            _seed_base(connection)
            _event(connection, "one", "proposed", "scheduled", "pg-claim-scheduled")
            assert connection.execute(sa.text(
                "SELECT state FROM entitlement_instances WHERE id='instance-one'"
            )).scalar_one() == "scheduled"
        with pytest.raises(sa.exc.DBAPIError) as direct_change:
            with engine.begin() as connection:
                connection.execute(sa.text(
                    "UPDATE entitlement_instances SET state='active' WHERE id='instance-one'"
                ))
        assert getattr(direct_change.value.orig, "sqlstate", None) == "23514"
        with engine.begin() as connection:
            connection.execute(sa.text("""
                INSERT INTO credit_periods
                  (id,billing_account_id,entitlement_instance_id,kind,period_index,
                   anchor_at,starts_at,ends_at,planned_allocation_amount,state)
                VALUES ('pg-period','account-one','instance-one','free',0,
                  :anchor,:start,:end,100,'planned')
            """), {"anchor": NOW, "start": NOW, "end": "2026-02-28 15:45:00+00:00"})
        with pytest.raises(_revision().EntitlementFoundationNotEmptyError):
            _downgrade(engine)
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
def test_postgres_concurrent_incompatible_entitlements_serialize_on_account(
    validate_test_database_url,
    postgres_schema_url,
):
    base_url = validate_test_database_url(os.environ["TEST_DATABASE_URL"])
    schema = f"phase_4_race_{uuid.uuid4().hex}"
    admin_engine = sa.create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    engine = sa.create_engine(postgres_schema_url(base_url, schema))
    first = second = None
    try:
        _predecessor(engine)
        _upgrade(engine)
        with engine.begin() as connection:
            _seed_base(connection)
            connection.execute(sa.text("""
                INSERT INTO entitlement_definitions
                  (id,key,version,exclusivity_key,capability_json,funding_policy_json,
                   effective_at,approved_at,approval_evidence_reference)
                SELECT 'definition-two','plan-two',1,'base-plan',capability_json,
                  funding_policy_json,effective_at,approved_at,approval_evidence_reference
                FROM entitlement_definitions WHERE id='definition-one'
            """))
            connection.execute(sa.text("""
                INSERT INTO entitlement_instances
                  (id,billing_account_id,entitlement_definition_id,state,starts_at,ends_at,
                   source_type,source_id,approval_evidence_reference)
                VALUES ('instance-two','account-one','definition-two','proposed',:now,:end,
                  'free','source-two','approval:test')
            """), {"now": NOW, "end": END})
            _claim(connection, "race-claim-one")
            _claim(connection, "race-claim-two")

        first = engine.connect()
        first_tx = first.begin()
        first.execute(sa.text("""
            INSERT INTO entitlement_events
              (id,entitlement_instance_id,transition,from_state,to_state,effective_at,
               actor_type,actor_id,source_type,source_id,idempotency_registry_id,evidence_json)
            VALUES ('race-event-one','instance-one','schedule','proposed','scheduled',:now,
              'test','phase4','test','phase4','race-claim-one','{}')
        """), {"now": NOW})

        second = engine.connect()
        second_tx = second.begin()
        second.execute(sa.text("SET LOCAL lock_timeout = '250ms'"))
        with pytest.raises(sa.exc.DBAPIError) as waiting:
            second.execute(sa.text("""
                INSERT INTO entitlement_events
                  (id,entitlement_instance_id,transition,from_state,to_state,effective_at,
                   actor_type,actor_id,source_type,source_id,idempotency_registry_id,evidence_json)
                VALUES ('race-event-two','instance-two','schedule','proposed','scheduled',:now,
                  'test','phase4','test','phase4','race-claim-two','{}')
            """), {"now": NOW})
        assert getattr(waiting.value.orig, "sqlstate", None) == "55P03"
        second_tx.rollback()
        first_tx.commit()

        with pytest.raises(sa.exc.DBAPIError) as overlap:
            with engine.begin() as connection:
                connection.execute(sa.text("""
                    INSERT INTO entitlement_events
                      (id,entitlement_instance_id,transition,from_state,to_state,effective_at,
                       actor_type,actor_id,source_type,source_id,idempotency_registry_id,evidence_json)
                    VALUES ('race-event-two','instance-two','schedule','proposed','scheduled',:now,
                      'test','phase4','test','phase4','race-claim-two','{}')
                """), {"now": NOW})
        assert getattr(overlap.value.orig, "sqlstate", None) == "23514"
    finally:
        if first is not None:
            first.close()
        if second is not None:
            second.close()
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()
