"""Migration and database-enforcement coverage for Phase 2.2."""

import contextlib
from datetime import datetime, timedelta, timezone
import os
import uuid

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRATIONS_DIR = os.path.join(BACKEND_DIR, "migrations")
PARENT_REVISION = "b5e7c9a1d3f2"
PHASE_2_1_REVISION = "b5e7c9a1d3f2"
MIGRATION_REVISION = "c6f8d0b2e4a1"
NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
FUTURE = NOW + timedelta(days=30)
TABLES = {
    "idempotency_registry",
    "pricing_policy_versions",
    "provider_rate_entries",
    "capacity_policy_versions",
}


def _revision_module():
    return ScriptDirectory(MIGRATIONS_DIR).get_revision(MIGRATION_REVISION).module


def _phase_2_1_revision_module():
    return ScriptDirectory(MIGRATIONS_DIR).get_revision(PHASE_2_1_REVISION).module


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
    with engine.begin() as connection:
        connection.execute(sa.text(
            "INSERT INTO users (id) VALUES ('legacy-user')"
        ))


def _custom_indexes(inspector, table):
    return {
        index["name"]: index
        for index in inspector.get_indexes(table)
        if not index.get("duplicates_constraint")
    }


def _assert_schema(engine):
    inspector = sa.inspect(engine)
    assert TABLES.issubset(inspector.get_table_names())
    assert {column["name"] for column in inspector.get_columns("idempotency_registry")} == {
        "id", "namespace", "key", "request_fingerprint", "state",
        "result_type", "result_id", "claimed_at", "completed_at",
        "last_error_code",
    }
    assert {column["name"] for column in inspector.get_columns("pricing_policy_versions")} == {
        "id", "version", "state", "effective_at", "approved_at",
        "announced_at", "superseded_at", "approved_by_user_id",
        "supersedes_id", "credit_conversion_version", "rounding_rule",
        "conversion_json", "customer_credit_impact", "notice_required",
        "notice_evidence_reference",
    }
    assert {column["name"] for column in inspector.get_columns("provider_rate_entries")} == {
        "id", "pricing_policy_version_id", "provider", "model", "currency",
        "unit_basis", "input_rate", "output_rate", "cache_tool_rate_json",
        "source_reference", "source_observed_at",
    }
    rate_columns = {
        column["name"]: column for column in inspector.get_columns("provider_rate_entries")
    }
    assert rate_columns["input_rate"]["type"].precision == 20
    assert rate_columns["input_rate"]["type"].scale == 10
    assert rate_columns["output_rate"]["type"].precision == 20
    assert rate_columns["output_rate"]["type"].scale == 10
    assert {column["name"] for column in inspector.get_columns("capacity_policy_versions")} == {
        "id", "version", "state", "effective_at", "approved_at",
        "approved_by_user_id", "approval_evidence_reference", "superseded_at",
        "supersedes_id", "rules_json",
    }

    assert set(_custom_indexes(inspector, "idempotency_registry")) == {
        "ix_idempotency_registry_result_reference",
        "ix_idempotency_registry_state_claimed_at",
    }
    assert set(_custom_indexes(inspector, "pricing_policy_versions")) == {
        "ix_pricing_policy_versions_approved_by_user_id",
        "ix_pricing_policy_versions_state_effective_at",
        "ix_pricing_policy_versions_supersedes_id",
        "uq_pricing_policy_versions_single_effective",
    }
    assert set(_custom_indexes(inspector, "capacity_policy_versions")) == {
        "ix_capacity_policy_versions_approved_by_user_id",
        "ix_capacity_policy_versions_state_effective_at",
        "ix_capacity_policy_versions_supersedes_id",
        "uq_capacity_policy_versions_single_effective",
    }
    assert _custom_indexes(
        inspector, "pricing_policy_versions"
    )["uq_pricing_policy_versions_single_effective"]["unique"]
    assert _custom_indexes(
        inspector, "capacity_policy_versions"
    )["uq_capacity_policy_versions_single_effective"]["unique"]

    pricing_fks = {
        item["name"]: item
        for item in inspector.get_foreign_keys("pricing_policy_versions")
    }
    assert pricing_fks["fk_pricing_policy_versions_approved_by_user_id"]["options"]["ondelete"] == "SET NULL"
    assert pricing_fks["fk_pricing_policy_versions_supersedes_id"]["options"]["ondelete"] == "RESTRICT"
    rate_fks = {
        item["name"]: item
        for item in inspector.get_foreign_keys("provider_rate_entries")
    }
    assert rate_fks["fk_provider_rate_entries_pricing_policy_version_id"]["options"]["ondelete"] == "RESTRICT"
    capacity_fks = {
        item["name"]: item
        for item in inspector.get_foreign_keys("capacity_policy_versions")
    }
    assert capacity_fks["fk_capacity_policy_versions_approved_by_user_id"]["options"]["ondelete"] == "SET NULL"
    assert capacity_fks["fk_capacity_policy_versions_supersedes_id"]["options"]["ondelete"] == "RESTRICT"

    idempotency_checks = {
        item["name"] for item in inspector.get_check_constraints("idempotency_registry")
    }
    assert idempotency_checks == {
        "ck_idempotency_registry_completed_state",
        "ck_idempotency_registry_completion_state",
        "ck_idempotency_registry_completion_time",
        "ck_idempotency_registry_failure_error",
        "ck_idempotency_registry_fingerprint",
        "ck_idempotency_registry_result_reference",
        "ck_idempotency_registry_result_state",
        "ck_idempotency_registry_state",
    }
    assert {
        item["name"] for item in inspector.get_unique_constraints("idempotency_registry")
    } == {"uq_idempotency_registry_namespace_key"}
    assert {
        item["name"] for item in inspector.get_unique_constraints("pricing_policy_versions")
    } == {"uq_pricing_policy_versions_version"}
    assert {
        item["name"] for item in inspector.get_unique_constraints("provider_rate_entries")
    } == {"uq_provider_rate_entries_policy_provider_model"}
    assert {
        item["name"] for item in inspector.get_unique_constraints("capacity_policy_versions")
    } == {"uq_capacity_policy_versions_version"}


def _assert_triggers(engine):
    with engine.connect() as connection:
        if engine.dialect.name == "sqlite":
            names = set(connection.execute(sa.text("""
                SELECT name FROM sqlite_master
                WHERE type = 'trigger' AND name LIKE 'trg_%'
            """)).scalars())
            assert names == {
                "trg_capacity_policy_versions_delete",
                "trg_capacity_policy_versions_immutable",
                "trg_capacity_policy_versions_transition",
                "trg_idempotency_registry_fingerprint_insert",
                "trg_idempotency_registry_fingerprint_update",
                "trg_idempotency_registry_identity_delete",
                "trg_idempotency_registry_identity_update",
                "trg_idempotency_registry_lifecycle",
                "trg_pricing_policy_versions_delete",
                "trg_pricing_policy_versions_immutable",
                "trg_pricing_policy_versions_transition",
                "trg_provider_rate_entries_delete",
                "trg_provider_rate_entries_finite_insert",
                "trg_provider_rate_entries_finite_update",
                "trg_provider_rate_entries_insert",
                "trg_provider_rate_entries_update",
            }
        else:
            names = set(connection.execute(sa.text("""
                SELECT tgname FROM pg_trigger
                WHERE NOT tgisinternal AND tgname LIKE 'trg_%'
            """)).scalars())
            assert names == {
                "trg_capacity_policy_versions_lifecycle",
                "trg_idempotency_registry_identity",
                "trg_pricing_policy_versions_lifecycle",
                "trg_provider_rate_entries_immutable",
            }


def _assert_empty(engine):
    with engine.connect() as connection:
        for table in TABLES:
            assert connection.execute(sa.text(
                f"SELECT COUNT(*) FROM {table}"
            )).scalar_one() == 0


def _assert_rejected(
    engine,
    sql,
    parameters=None,
    expected_exception=sa.exc.IntegrityError,
):
    with pytest.raises(expected_exception):
        with engine.begin() as connection:
            connection.execute(sa.text(sql), parameters or {})


def _insert_pricing_draft(connection, identifier):
    statement = sa.text("""
        INSERT INTO pricing_policy_versions (
            id, version, state, effective_at, credit_conversion_version,
            rounding_rule, conversion_json, customer_credit_impact,
            notice_required
        ) VALUES (
            :id, :version, 'draft', :effective_at, :conversion_version,
            'ceil_whole_credit', :conversion_json, false, false
        )
    """).bindparams(sa.bindparam("conversion_json", type_=sa.JSON()))
    connection.execute(statement, {
        "id": identifier,
        "version": identifier,
        "effective_at": FUTURE,
        "conversion_version": "test-only-conversion",
        "conversion_json": {"test_only": True},
    })


def _insert_rate(connection, identifier, policy_id):
    connection.execute(sa.text("""
        INSERT INTO provider_rate_entries (
            id, pricing_policy_version_id, provider, model, currency,
            unit_basis, input_rate, output_rate, source_reference,
            source_observed_at
        ) VALUES (
            :id, :policy_id, :provider, :model, 'usd', 'per_1m_tokens',
            0, 0, 'test-only-source', :observed_at
        )
    """), {
        "id": identifier,
        "policy_id": policy_id,
        "provider": f"provider-{identifier}",
        "model": f"model-{identifier}",
        "observed_at": NOW,
    })


def _insert_capacity_draft(connection, identifier):
    statement = sa.text("""
        INSERT INTO capacity_policy_versions (
            id, version, state, effective_at, rules_json
        ) VALUES (:id, :version, 'draft', :effective_at, :rules_json)
    """).bindparams(sa.bindparam("rules_json", type_=sa.JSON()))
    connection.execute(statement, {
        "id": identifier,
        "version": identifier,
        "effective_at": FUTURE,
        "rules_json": {"test_only": True},
    })


def _populate_foundation(connection, populated_table):
    if populated_table == "idempotency_registry":
        connection.execute(sa.text("""
            INSERT INTO idempotency_registry (
                id, namespace, key, request_fingerprint, state, claimed_at
            ) VALUES (
                'retained-claim', 'test', 'retained', :fingerprint,
                'claimed', :claimed_at
            )
        """), {"fingerprint": "a" * 64, "claimed_at": NOW})
    elif populated_table == "pricing_policy_versions":
        _insert_pricing_draft(connection, "retained-pricing")
    elif populated_table == "provider_rate_entries":
        _insert_pricing_draft(connection, "retained-pricing")
        _insert_rate(connection, "retained-rate", "retained-pricing")
    else:
        _insert_capacity_draft(connection, "retained-capacity")


def _exercise_database_enforcement(engine):
    with engine.begin() as connection:
        connection.execute(sa.text("""
            INSERT INTO idempotency_registry (
                id, namespace, key, request_fingerprint, state, claimed_at
            ) VALUES (
                'claim-original', 'billing-test', 'stable-key', :fingerprint,
                'claimed', :claimed_at
            )
        """), {"fingerprint": "a" * 64, "claimed_at": NOW})

    _assert_rejected(engine, """
        INSERT INTO idempotency_registry (
            id, namespace, key, request_fingerprint, state, claimed_at
        ) VALUES (
            'claim-conflict', 'billing-test', 'stable-key', :fingerprint,
            'claimed', :claimed_at
        )
    """, {"fingerprint": "b" * 64, "claimed_at": NOW})
    _assert_rejected(engine, """
        INSERT INTO idempotency_registry (
            id, namespace, key, request_fingerprint, state, claimed_at
        ) VALUES (
            'claim-invalid-digest', 'billing-test', 'invalid-digest',
            :fingerprint, 'claimed', :claimed_at
        )
    """, {"fingerprint": "g" * 64, "claimed_at": NOW})
    _assert_rejected(engine, """
        UPDATE idempotency_registry SET request_fingerprint = :fingerprint
        WHERE id = 'claim-original'
    """, {"fingerprint": "b" * 64})
    _assert_rejected(engine, """
        UPDATE idempotency_registry SET namespace = 'changed'
        WHERE id = 'claim-original'
    """)
    _assert_rejected(engine, """
        UPDATE idempotency_registry SET key = 'changed'
        WHERE id = 'claim-original'
    """)
    _assert_rejected(engine, """
        DELETE FROM idempotency_registry WHERE id = 'claim-original'
    """)
    with engine.connect() as connection:
        assert connection.execute(sa.text("""
            SELECT request_fingerprint FROM idempotency_registry
            WHERE id = 'claim-original'
        """)).scalar_one() == "a" * 64

    with engine.begin() as connection:
        connection.execute(sa.text("""
            UPDATE idempotency_registry
            SET state = 'failed_retryable', last_error_code = 'provider_timeout'
            WHERE id = 'claim-original'
        """))
        connection.execute(sa.text("""
            UPDATE idempotency_registry SET state = 'claimed'
            WHERE id = 'claim-original'
        """))
        connection.execute(sa.text("""
            UPDATE idempotency_registry
            SET state = 'completed', completed_at = :completed_at,
                result_type = 'financial_transaction', result_id = 'result-one'
            WHERE id = 'claim-original'
        """), {"completed_at": NOW + timedelta(seconds=1)})
    _assert_rejected(engine, """
        UPDATE idempotency_registry SET state = 'claimed'
        WHERE id = 'claim-original'
    """)
    _assert_rejected(engine, """
        UPDATE idempotency_registry SET result_id = 'result-two'
        WHERE id = 'claim-original'
    """)
    _assert_rejected(engine, """
        UPDATE idempotency_registry SET result_type = NULL, result_id = NULL
        WHERE id = 'claim-original'
    """)
    _assert_rejected(engine, """
        UPDATE idempotency_registry SET completed_at = :completed_at
        WHERE id = 'claim-original'
    """, {"completed_at": NOW + timedelta(seconds=2)})
    with engine.connect() as connection:
        retained_result = connection.execute(sa.text("""
            SELECT state, result_type, result_id FROM idempotency_registry
            WHERE id = 'claim-original'
        """)).one()
        assert retained_result == (
            "completed", "financial_transaction", "result-one",
        )

    with engine.begin() as connection:
        _insert_pricing_draft(connection, "pricing-one")
        _insert_rate(connection, "rate-one", "pricing-one")

    _assert_rejected(engine, """
        INSERT INTO provider_rate_entries (
            id, pricing_policy_version_id, provider, model, currency,
            unit_basis, input_rate, output_rate, source_reference,
            source_observed_at
        ) VALUES (
            'rate-invalid-unit', 'pricing-one', 'invalid-unit', 'test-model',
            'usd', 'per_token', 0, 0, 'test-only-source', :observed_at
        )
    """, {"observed_at": NOW})
    _assert_rejected(engine, """
        INSERT INTO provider_rate_entries (
            id, pricing_policy_version_id, provider, model, currency,
            unit_basis, input_rate, output_rate, source_reference,
            source_observed_at
        ) VALUES (
            'rate-negative', 'pricing-one', 'negative-rate', 'test-model',
            'usd', 'per_1m_tokens', -0.0000000001, 0,
            'test-only-source', :observed_at
        )
    """, {"observed_at": NOW})
    _assert_rejected(engine, """
        INSERT INTO provider_rate_entries (
            id, pricing_policy_version_id, provider, model, currency,
            unit_basis, input_rate, output_rate, source_reference,
            source_observed_at
        )
        SELECT 'rate-duplicate', pricing_policy_version_id, provider, model,
               currency, unit_basis, input_rate, output_rate,
               source_reference, source_observed_at
        FROM provider_rate_entries WHERE id = 'rate-one'
    """)
    for label, value, input_rate, output_rate in (
        ("nan-input", float("nan"), ":value", "0"),
        ("infinity-input", float("inf"), ":value", "0"),
        ("infinity-output", float("inf"), "0", ":value"),
    ):
        expected_exception = (
            sa.exc.DataError
            if engine.dialect.name == "postgresql" and label.startswith("infinity-")
            else sa.exc.IntegrityError
        )
        _assert_rejected(engine, f"""
            INSERT INTO provider_rate_entries (
                id, pricing_policy_version_id, provider, model, currency,
                unit_basis, input_rate, output_rate, source_reference,
                source_observed_at
            ) VALUES (
                'rate-{label}', 'pricing-one', 'provider-{label}',
                'model-{label}', 'usd', 'per_1m_tokens',
                {input_rate}, {output_rate}, 'test-only-source', :observed_at
            )
        """, {"value": value, "observed_at": NOW}, expected_exception)

    with engine.begin() as connection:
        connection.execute(sa.text("""
            UPDATE pricing_policy_versions
            SET state = 'approved', approved_at = :approved_at,
                approved_by_user_id = 'legacy-user'
            WHERE id = 'pricing-one'
        """), {"approved_at": NOW})

    _assert_rejected(engine, """
        UPDATE pricing_policy_versions
        SET conversion_json = :conversion_json WHERE id = 'pricing-one'
    """, {"conversion_json": '{"changed":true}'})
    _assert_rejected(engine, """
        UPDATE pricing_policy_versions SET state = 'draft'
        WHERE id = 'pricing-one'
    """)
    _assert_rejected(engine, """
        UPDATE provider_rate_entries SET input_rate = 1
        WHERE id = 'rate-one'
    """)
    _assert_rejected(engine, """
        INSERT INTO provider_rate_entries (
            id, pricing_policy_version_id, provider, model, currency,
            unit_basis, input_rate, output_rate, source_reference,
            source_observed_at
        ) VALUES (
            'rate-late', 'pricing-one', 'late-provider', 'late-model', 'usd',
            'per_1m_tokens', 0, 0, 'test-only-source', :observed_at
        )
    """, {"observed_at": NOW})
    _assert_rejected(engine, "DELETE FROM provider_rate_entries WHERE id = 'rate-one'")
    _assert_rejected(engine, "DELETE FROM pricing_policy_versions WHERE id = 'pricing-one'")
    with engine.begin() as connection:
        connection.execute(sa.text("DELETE FROM users WHERE id = 'legacy-user'"))
    with engine.connect() as connection:
        approved_by = connection.execute(sa.text("""
            SELECT approved_by_user_id FROM pricing_policy_versions
            WHERE id = 'pricing-one'
        """)).scalar_one()
        assert approved_by is None
    _assert_rejected(engine, """
        UPDATE pricing_policy_versions
        SET approved_by_user_id = 'replacement-user'
        WHERE id = 'pricing-one'
    """)

    with engine.begin() as connection:
        _insert_pricing_draft(connection, "pricing-notice")
        _insert_rate(connection, "rate-notice", "pricing-notice")
        connection.execute(sa.text("""
            UPDATE pricing_policy_versions
            SET customer_credit_impact = true, notice_required = true
            WHERE id = 'pricing-notice'
        """))
        connection.execute(sa.text("""
            UPDATE pricing_policy_versions
            SET state = 'approved', approved_at = :approved_at
            WHERE id = 'pricing-notice'
        """), {"approved_at": NOW})
    _assert_rejected(engine, """
        UPDATE pricing_policy_versions
        SET state = 'effective'
        WHERE id = 'pricing-notice'
    """)
    with engine.begin() as connection:
        connection.execute(sa.text("""
            UPDATE pricing_policy_versions
            SET notice_evidence_reference = 'test-only-notice'
            WHERE id = 'pricing-notice'
        """))
    _assert_rejected(engine, """
        UPDATE pricing_policy_versions
        SET notice_evidence_reference = 'replacement-notice'
        WHERE id = 'pricing-notice'
    """)
    _assert_rejected(engine, """
        UPDATE pricing_policy_versions
        SET notice_evidence_reference = NULL
        WHERE id = 'pricing-notice'
    """)
    _assert_rejected(engine, """
        INSERT INTO pricing_policy_versions (
            id, version, state, effective_at, approved_at, announced_at,
            credit_conversion_version, rounding_rule, conversion_json,
            customer_credit_impact, notice_required, notice_evidence_reference
        ) VALUES (
            'pricing-no-advance', 'pricing-no-advance', 'effective',
            :effective_at, :approved_at, :announced_at,
            'test-only-conversion', 'ceil_whole_credit', CAST(:conversion_json AS JSON),
            true, true, 'test-only-notice'
        )
    """, {
        "effective_at": FUTURE,
        "approved_at": NOW,
        "announced_at": FUTURE,
        "conversion_json": '{"test_only":true}',
    })
    with engine.begin() as connection:
        connection.execute(sa.text("""
            UPDATE pricing_policy_versions
            SET state = 'announced', announced_at = :announced_at
            WHERE id = 'pricing-notice'
        """), {"announced_at": NOW})
    _assert_rejected(engine, """
        UPDATE pricing_policy_versions
        SET notice_evidence_reference = 'changed'
        WHERE id = 'pricing-notice'
    """)
    with engine.begin() as connection:
        connection.execute(sa.text("""
            UPDATE pricing_policy_versions SET state = 'effective'
            WHERE id = 'pricing-notice'
        """))
        connection.execute(sa.text("""
            UPDATE pricing_policy_versions
            SET state = 'superseded', superseded_at = :superseded_at
            WHERE id = 'pricing-notice'
        """), {"superseded_at": FUTURE + timedelta(days=1)})

    with engine.begin() as connection:
        connection.execute(sa.text("""
            UPDATE pricing_policy_versions SET state = 'effective'
            WHERE id = 'pricing-one'
        """))
        _insert_pricing_draft(connection, "pricing-two")
        _insert_rate(connection, "rate-two", "pricing-two")
        connection.execute(sa.text("""
            UPDATE pricing_policy_versions
            SET state = 'approved', approved_at = :approved_at
            WHERE id = 'pricing-two'
        """), {"approved_at": NOW})
    _assert_rejected(engine, """
        UPDATE pricing_policy_versions SET state = 'effective'
        WHERE id = 'pricing-two'
    """)

    with engine.begin() as connection:
        _insert_capacity_draft(connection, "capacity-one")
        connection.execute(sa.text("""
            UPDATE capacity_policy_versions
            SET state = 'approved', approved_at = :approved_at,
                approval_evidence_reference = 'test-only-approval'
            WHERE id = 'capacity-one'
        """), {"approved_at": NOW})
    _assert_rejected(engine, """
        UPDATE capacity_policy_versions SET rules_json = :rules_json
        WHERE id = 'capacity-one'
    """, {"rules_json": '{"changed":true}'})
    _assert_rejected(engine, """
        UPDATE capacity_policy_versions SET state = 'draft'
        WHERE id = 'capacity-one'
    """)
    _assert_rejected(engine, "DELETE FROM capacity_policy_versions WHERE id = 'capacity-one'")
    with engine.begin() as connection:
        connection.execute(sa.text("""
            UPDATE capacity_policy_versions SET state = 'effective'
            WHERE id = 'capacity-one'
        """))
        _insert_capacity_draft(connection, "capacity-two")
        connection.execute(sa.text("""
            UPDATE capacity_policy_versions
            SET state = 'approved', approved_at = :approved_at,
                approval_evidence_reference = 'test-only-approval'
            WHERE id = 'capacity-two'
        """), {"approved_at": NOW})
    _assert_rejected(engine, """
        UPDATE capacity_policy_versions SET state = 'effective'
        WHERE id = 'capacity-two'
    """)


def test_revision_extends_the_accepted_phase_2_1_head():
    script = ScriptDirectory(MIGRATIONS_DIR)
    revision = script.get_revision(MIGRATION_REVISION)

    assert revision.down_revision == PARENT_REVISION
    assert revision.revision in {item.revision for item in script.walk_revisions()}


def test_sqlite_empty_upgrade_and_downgrade_preserve_legacy_data(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'phase_2_2_empty.sqlite'}")
    _create_predecessor_tables(engine)
    revision_module = _revision_module()

    with _migration_ops(engine):
        revision_module.upgrade()
    _assert_schema(engine)
    _assert_triggers(engine)
    _assert_empty(engine)

    with _migration_ops(engine):
        revision_module.downgrade()
    assert TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT id FROM users")).scalar_one() == "legacy-user"
    engine.dispose()


def test_sqlite_constraints_lifecycle_and_immutability(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'phase_2_2_enforcement.sqlite'}")
    _create_predecessor_tables(engine)
    with _migration_ops(engine):
        _revision_module().upgrade()

    _assert_triggers(engine)
    _exercise_database_enforcement(engine)
    engine.dispose()


@pytest.mark.parametrize(
    "populated_table",
    [
        "idempotency_registry",
        "pricing_policy_versions",
        "provider_rate_entries",
        "capacity_policy_versions",
    ],
)
def test_guarded_downgrade_refuses_every_populated_foundation(
    tmp_path,
    populated_table,
):
    engine = sa.create_engine(
        f"sqlite:///{tmp_path / f'phase_2_2_guard_{populated_table}.sqlite'}"
    )
    revision_module = _revision_module()
    _create_predecessor_tables(engine)
    with _migration_ops(engine):
        revision_module.upgrade()

    with engine.begin() as connection:
        _populate_foundation(connection, populated_table)

    with pytest.raises(
        revision_module.PolicyFoundationNotEmptyError,
        match=f"{populated_table}=1",
    ):
        with _migration_ops(engine):
            revision_module.downgrade()

    assert TABLES.issubset(sa.inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.execute(sa.text(
            f"SELECT COUNT(*) FROM {populated_table}"
        )).scalar_one() == 1
        assert connection.execute(sa.text("SELECT id FROM users")).scalar_one() == "legacy-user"
    engine.dispose()


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)
def test_postgres_phase_2_2_complete_verification(
    validate_test_database_url,
    postgres_schema_url,
):
    base_url = validate_test_database_url(os.environ["TEST_DATABASE_URL"])
    schema = f"phase_2_2_{uuid.uuid4().hex}"
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
        _assert_triggers(engine)
        _assert_empty(engine)

        with _migration_ops(engine):
            revision_module.downgrade()
        assert TABLES.isdisjoint(sa.inspect(engine).get_table_names())
        with engine.connect() as connection:
            assert connection.execute(sa.text(
                "SELECT id FROM users"
            )).scalar_one() == "legacy-user"

        with _migration_ops(engine):
            revision_module.upgrade()
        _exercise_database_enforcement(engine)

        with pytest.raises(revision_module.PolicyFoundationNotEmptyError):
            with _migration_ops(engine):
                revision_module.downgrade()
        assert TABLES.issubset(sa.inspect(engine).get_table_names())
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
def test_postgres_rejects_nan_and_infinite_provider_rates(
    validate_test_database_url,
    postgres_schema_url,
):
    base_url = validate_test_database_url(os.environ["TEST_DATABASE_URL"])
    schema = f"phase_2_2_rates_{uuid.uuid4().hex}"
    admin_engine = sa.create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))

    engine = sa.create_engine(postgres_schema_url(base_url, schema))
    try:
        _create_predecessor_tables(engine)
        with _migration_ops(engine):
            _revision_module().upgrade()
        with engine.begin() as connection:
            _insert_pricing_draft(connection, "pricing-nonfinite")

        for column in ("input_rate", "output_rate"):
            other_column = "output_rate" if column == "input_rate" else "input_rate"
            for label, literal, expected_exception in (
                ("nan", "NaN", sa.exc.IntegrityError),
                ("pos-inf", "Infinity", sa.exc.DataError),
                ("neg-inf", "-Infinity", sa.exc.DataError),
            ):
                _assert_rejected(engine, f"""
                    INSERT INTO provider_rate_entries (
                        id, pricing_policy_version_id, provider, model, currency,
                        unit_basis, {column}, {other_column}, source_reference,
                        source_observed_at
                    ) VALUES (
                        'rate-{column}-{label}', 'pricing-nonfinite',
                        'p-{column}-{label}', 'm-{column}-{label}',
                        'usd', 'per_1m_tokens', CAST('{literal}' AS NUMERIC), 0,
                        'test-only-source', :observed_at
                    )
                """, {"observed_at": NOW}, expected_exception)
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
def test_postgres_phase_2_1_rows_survive_phase_2_2_upgrade_and_downgrade(
    validate_test_database_url,
    postgres_schema_url,
):
    base_url = validate_test_database_url(os.environ["TEST_DATABASE_URL"])
    schema = f"phase_2_1_preservation_{uuid.uuid4().hex}"
    admin_engine = sa.create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))

    engine = sa.create_engine(postgres_schema_url(base_url, schema))
    phase_2_2_module = _revision_module()
    try:
        _create_predecessor_tables(engine)
        with _migration_ops(engine):
            _phase_2_1_revision_module().upgrade()
        with engine.begin() as connection:
            connection.execute(sa.text(
                "INSERT INTO organizations (id) VALUES ('retained-org')"
            ))
            connection.execute(sa.text("""
                INSERT INTO billing_accounts (
                    id, organization_id, currency, account_anchor_at
                ) VALUES (
                    'retained-account', 'retained-org', 'usd', :anchor_at
                )
            """), {"anchor_at": NOW})
            connection.execute(sa.text("""
                INSERT INTO billing_role_grants (
                    id, billing_account_id, user_id, role, starts_at,
                    origin_type, origin_id
                ) VALUES (
                    'retained-role', 'retained-account', 'legacy-user',
                    'billing_owner', :starts_at, 'test-only', 'phase-2-1-proof'
                )
            """), {"starts_at": NOW})

        with _migration_ops(engine):
            phase_2_2_module.upgrade()
        _assert_empty(engine)
        with engine.connect() as connection:
            assert connection.execute(sa.text("""
                SELECT organization_id, currency FROM billing_accounts
                WHERE id = 'retained-account'
            """)).one() == ("retained-org", "usd")
            assert connection.execute(sa.text("""
                SELECT billing_account_id, user_id, role, origin_id
                FROM billing_role_grants WHERE id = 'retained-role'
            """)).one() == (
                "retained-account", "legacy-user", "billing_owner",
                "phase-2-1-proof",
            )

        with _migration_ops(engine):
            phase_2_2_module.downgrade()
        with engine.connect() as connection:
            assert connection.execute(sa.text(
                "SELECT COUNT(*) FROM billing_accounts"
            )).scalar_one() == 1
            assert connection.execute(sa.text(
                "SELECT COUNT(*) FROM billing_role_grants"
            )).scalar_one() == 1
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
@pytest.mark.parametrize(
    "populated_table",
    [
        "idempotency_registry",
        "pricing_policy_versions",
        "provider_rate_entries",
        "capacity_policy_versions",
    ],
)
def test_postgres_guarded_downgrade_refuses_each_populated_foundation(
    validate_test_database_url,
    postgres_schema_url,
    populated_table,
):
    base_url = validate_test_database_url(os.environ["TEST_DATABASE_URL"])
    schema = f"phase_2_2_guard_{uuid.uuid4().hex}"
    admin_engine = sa.create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))

    engine = sa.create_engine(postgres_schema_url(base_url, schema))
    revision_module = _revision_module()
    try:
        _create_predecessor_tables(engine)
        with _migration_ops(engine):
            revision_module.upgrade()
        with engine.begin() as connection:
            _populate_foundation(connection, populated_table)

        with pytest.raises(
            revision_module.PolicyFoundationNotEmptyError,
            match=f"{populated_table}=1",
        ):
            with _migration_ops(engine):
                revision_module.downgrade()
        assert TABLES.issubset(sa.inspect(engine).get_table_names())
        with engine.connect() as connection:
            assert connection.execute(sa.text(
                f"SELECT COUNT(*) FROM {populated_table}"
            )).scalar_one() == 1
    finally:
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()
