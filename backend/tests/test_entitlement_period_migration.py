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


@contextlib.contextmanager
def _postgres_phase4_engine(base_url, postgres_schema_url, prefix):
    schema = f"{prefix}_{uuid.uuid4().hex}"
    admin_engine = sa.create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    engine = sa.create_engine(postgres_schema_url(base_url, schema))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


def _seed_incompatible_instance(connection):
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


def _insert_scheduled_event(connection, suffix, claim):
    connection.execute(sa.text("""
        INSERT INTO entitlement_events
          (id,entitlement_instance_id,transition,from_state,to_state,effective_at,
           actor_type,actor_id,source_type,source_id,idempotency_registry_id,evidence_json)
        VALUES (:event,:instance,'schedule','proposed','scheduled',:now,
          'test','phase4','test','phase4',:claim,'{}')
    """), {
        "event": f"race-event-{suffix}", "instance": f"instance-{suffix}",
        "claim": claim, "now": NOW,
    })


def _seed_annual_period_owner(connection):
    _seed_base(connection)
    connection.execute(sa.text("""
        INSERT INTO billing_subscriptions
          (id,billing_account_id,processor,external_subscription_id,interval,
           anchor_at,term_starts_at,term_ends_at,state,
           current_entitlement_definition_id,origin_evidence_json)
        VALUES ('annual-subscription','account-one','stripe','sub_annual','year',
          :now,:now,:end,'active','definition-one','{}')
    """), {"now": NOW, "end": END})
    connection.execute(sa.text("""
        INSERT INTO entitlement_instances
          (id,billing_account_id,entitlement_definition_id,subscription_id,state,
           starts_at,ends_at,source_type,source_id,approval_evidence_reference)
        VALUES ('annual-instance','account-one','definition-one','annual-subscription',
          'proposed',:now,:end,'subscription','sub_annual','approval:test')
    """), {"now": NOW, "end": END})


def _insert_annual_period(connection, identifier):
    connection.execute(sa.text("""
        INSERT INTO credit_periods
          (id,billing_account_id,entitlement_instance_id,subscription_id,kind,
           period_index,anchor_at,starts_at,ends_at,planned_allocation_amount,state)
        VALUES (:id,'account-one','annual-instance','annual-subscription',
          'annual_monthly',0,:anchor,:start,:end,100,'planned')
    """), {
        "id": identifier, "anchor": NOW, "start": NOW,
        "end": "2026-02-28 15:45:00+00:00",
    })


def test_revision_is_linear_and_schema_is_complete(sqlite_engine):
    script = ScriptDirectory(MIGRATIONS_DIR)
    assert script.get_revision(REVISION).down_revision == PARENT
    assert REVISION in {
        item.revision for item in script.iterate_revisions(script.get_current_head(), "base")
    }
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
    with _postgres_phase4_engine(base_url, postgres_schema_url, "phase_4") as engine:
        # A pre-existing Phase 3 lot and ledger entry must survive the additive
        # Phase 4 migration unchanged.
        _predecessor(engine)
        with engine.begin() as connection:
            connection.execute(sa.text(
                "INSERT INTO billing_accounts (id,account_anchor_at) VALUES ('ledger-account',:now)"
            ), {"now": NOW})
            connection.execute(sa.text(
                "INSERT INTO idempotency_registry (id,state) VALUES ('ledger-claim','completed')"
            ))
            connection.execute(sa.text("""
                INSERT INTO credit_lots
                  (id,billing_account_id,source_type,source_id,original_amount,
                   available_at,expires_at,origin_evidence_json)
                VALUES ('legacy-lot','ledger-account','purchase','legacy-source',10,
                  :now,NULL,'{}')
            """), {"now": NOW})
            connection.execute(sa.text("""
                INSERT INTO credit_ledger_entries
                  (id,billing_account_id,lot_id,entry_type,available_delta,held_delta,
                   idempotency_registry_id,effective_at,actor_type,actor_id,reason_code,evidence_json)
                VALUES ('legacy-entry','ledger-account','legacy-lot','grant',10,0,
                  'ledger-claim',:now,'test','phase3','preserved','{}')
            """), {"now": NOW})
        _upgrade(engine)
        with engine.begin() as connection:
            assert connection.execute(sa.text("""
                SELECT original_amount FROM credit_lots WHERE id='legacy-lot'
            """)).scalar_one() == 10
            assert connection.execute(sa.text("""
                SELECT available_delta,held_delta FROM credit_ledger_entries
                WHERE id='legacy-entry'
            """)).one() == (10, 0)
            _seed_base(connection)
            _event(connection, "one", "proposed", "scheduled", "pg-claim-scheduled")
            assert connection.execute(sa.text(
                "SELECT state FROM entitlement_instances WHERE id='instance-one'"
            )).scalar_one() == "scheduled"
            valid_definition = sa.text("""
                INSERT INTO entitlement_definitions
                  (id,key,version,exclusivity_key,capability_json,funding_policy_json,
                   effective_at,approved_at,approval_evidence_reference)
                VALUES (:id,:key,1,'json-plan',:capabilities,
                  :funding,:now,:now,'approval:test')
            """).bindparams(
                sa.bindparam("capabilities", type_=sa.JSON()),
                sa.bindparam("funding", type_=sa.JSON()),
            )
            connection.execute(valid_definition, {
                "capabilities": {
                    "schema_version": 1,
                    "capabilities": {"nested": [{"finite_limit": 5}]},
                },
                "funding": {
                    "schema_version": 1, "period_kind": "none", "credit_amount": 0,
                },
                "now": NOW, "id": "definition-json", "key": "json-plan",
            })
            with pytest.raises(sa.exc.DBAPIError) as unlimited:
                with connection.begin_nested():
                    connection.execute(valid_definition, {
                        "capabilities": {
                            "schema_version": 1,
                            "capabilities": {"nested": [{"unlimited_access": True}]},
                        },
                        "funding": {
                            "schema_version": 1, "period_kind": "none", "credit_amount": 0,
                        },
                        "now": NOW, "id": "definition-unlimited", "key": "unlimited-plan",
                    })
            assert getattr(unlimited.value.orig, "sqlstate", None) == "23514"
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


ISOLATION_COMBINATIONS = (
    ("READ COMMITTED", "READ COMMITTED"),
    ("REPEATABLE READ", "REPEATABLE READ"),
    ("SERIALIZABLE", "SERIALIZABLE"),
    ("READ COMMITTED", "REPEATABLE READ"),
    ("REPEATABLE READ", "READ COMMITTED"),
    ("READ COMMITTED", "SERIALIZABLE"),
    ("SERIALIZABLE", "READ COMMITTED"),
)


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)
@pytest.mark.parametrize("first_isolation,second_isolation", ISOLATION_COMBINATIONS)
def test_postgres_concurrent_incompatible_entitlements_serialize_on_account(
    validate_test_database_url,
    postgres_schema_url,
    first_isolation,
    second_isolation,
):
    base_url = validate_test_database_url(os.environ["TEST_DATABASE_URL"])
    with _postgres_phase4_engine(base_url, postgres_schema_url, "phase_4_race") as engine:
        _predecessor(engine)
        _upgrade(engine)
        with engine.begin() as connection:
            _seed_base(connection)
            _seed_incompatible_instance(connection)

        with engine.connect().execution_options(isolation_level=second_isolation) as second:
            second_tx = second.begin()
            # Pin the old snapshot before the competing writer commits. Under
            # READ COMMITTED the next statement refreshes; stricter levels must
            # fail with 40001 at the account update fence.
            second.execute(sa.text("SELECT id FROM billing_accounts WHERE id='account-one'"))
            with engine.connect().execution_options(isolation_level=first_isolation) as first:
                with first.begin():
                    _insert_scheduled_event(first, "one", "race-claim-one")
            with pytest.raises(sa.exc.DBAPIError) as rejected:
                _insert_scheduled_event(second, "two", "race-claim-two")
            sqlstate = getattr(rejected.value.orig, "sqlstate", None)
            assert sqlstate == ("23514" if second_isolation == "READ COMMITTED" else "40001")
            second_tx.rollback()

        with engine.connect() as connection:
            assert connection.execute(sa.text("""
                SELECT count(*) FROM entitlement_instances WHERE state='scheduled'
            """)).scalar_one() == 1


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)
@pytest.mark.parametrize("first_isolation,second_isolation", ISOLATION_COMBINATIONS)
def test_postgres_concurrent_annual_period_overlap_uses_account_fence(
    validate_test_database_url,
    postgres_schema_url,
    first_isolation,
    second_isolation,
):
    base_url = validate_test_database_url(os.environ["TEST_DATABASE_URL"])
    with _postgres_phase4_engine(base_url, postgres_schema_url, "phase_4_annual") as engine:
        _predecessor(engine)
        _upgrade(engine)
        with engine.begin() as connection:
            _seed_annual_period_owner(connection)

        with engine.connect().execution_options(isolation_level=second_isolation) as second:
            second_tx = second.begin()
            second.execute(sa.text("SELECT id FROM billing_accounts WHERE id='account-one'"))
            with engine.connect().execution_options(isolation_level=first_isolation) as first:
                with first.begin():
                    _insert_annual_period(first, "annual-period-one")
            with pytest.raises(sa.exc.DBAPIError) as rejected:
                _insert_annual_period(second, "annual-period-two")
            sqlstate = getattr(rejected.value.orig, "sqlstate", None)
            assert sqlstate == ("23514" if second_isolation == "READ COMMITTED" else "40001")
            second_tx.rollback()

        with engine.connect() as connection:
            assert connection.execute(sa.text("""
                SELECT count(*) FROM credit_periods WHERE kind='annual_monthly'
            """)).scalar_one() == 1
