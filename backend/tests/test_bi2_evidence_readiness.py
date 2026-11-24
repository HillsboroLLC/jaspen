"""BI-2: readiness for the staging billing evidence run.

1. The operator command line connects the way the server does (wsgi.py's credential file), exercised as a real
   subprocess, not an injected application.
2. The staging database role policy: the runtime role cannot write migration evidence, the billing migrator
   can run every Phase 14-16 command and decision with least privilege, and the policy verifies and rolls back.
3. The restore-copy authorization (review N4): founder approval, restore provenance, database identity and
   expiry, failing closed on anything missing, expired, mismatched or production.
4. The deploy data census: per-table counts before and after, expected migration effects told apart from
   unexpected changes.

PostgreSQL tests run on the fully migrated local test database (TEST_DATABASE_URL); roles they create are
NOLOGIN and dropped afterwards.
"""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

import app.billing_rehearsal as br
import app.billing_restore_copy as rc
from tests.test_billing_migration import PG, _migrated_engine, migrated, naive, now, user

BACKEND = Path(__file__).resolve().parents[1]
STAGING = BACKEND.parent / "deploy" / "staging"


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


roles = _module("staging_db_roles", STAGING / "staging_db_roles.py")
staging_database = _module("staging_database", STAGING / "staging_database.py")


# ---------------------------------------------------------------------------
# 1. The command line uses the server's credential path
# ---------------------------------------------------------------------------

def _cli_env(tmp_path, url=None, mode=0o600):
    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "SQLALCHEMY_DATABASE_URI",
                                                            "TEST_DATABASE_URL", "JASPEN_DATABASE_URL_FILE")}
    env.update(PYTHONPATH=str(BACKEND), APP_ENV="test", SECRET_KEY="bi2-cli-test", JWT_SECRET_KEY="bi2-cli-test",
               STRIPE_SECRET_KEY="sk_test_dummy_bi2_cli", HOME=str(tmp_path))
    if url is not None:
        secret = tmp_path / "database_url"
        secret.write_text(url + "\n", encoding="utf-8")
        secret.chmod(mode)
        env["JASPEN_DATABASE_URL_FILE"] = str(secret)
    return env


def _run_cli(env, *argv):
    return subprocess.run([sys.executable, "scripts/billing_migration_evidence.py", *argv], cwd=BACKEND, env=env,
                          capture_output=True, text=True, timeout=180)


def test_the_command_line_refuses_without_a_database_url_file(tmp_path):
    result = _run_cli(_cli_env(tmp_path), "operation-review")
    assert result.returncode == 2
    assert "JASPEN_DATABASE_URL_FILE" in json.loads(result.stdout)["error"]


def test_the_command_line_refuses_an_unprotected_url_file(tmp_path):
    result = _run_cli(_cli_env(tmp_path, "postgresql+psycopg://user@localhost/none_test", mode=0o644),
                      "operation-review")
    assert result.returncode != 0 and "must be mode 600" in result.stderr


@PG
def test_the_command_line_reads_the_url_file_like_wsgi_and_reviews_read_only(tmp_path):
    engine = _migrated_engine()
    try:
        url = engine.url.render_as_string(hide_password=False)
        with migrated(engine) as session:
            before = session.execute(sa.text("SELECT count(*) FROM billing_migration_operation_decisions")).scalar()
        result = _run_cli(_cli_env(tmp_path, url), "operation-review")
        assert result.returncode == 0, result.stderr[-2000:]
        review = json.loads(result.stdout)
        assert review["max_turn_seconds"] is None  # unset: every unclosed operation blocks
        assert all(o["code"] == "legacy_operation_in_flight" for o in review["operations"])
        with migrated(engine) as session:
            assert session.execute(sa.text("SELECT count(*) FROM billing_migration_operation_decisions")
                                   ).scalar() == before
        refused = _run_cli({**_cli_env(tmp_path, url), "APP_ENV": "production"}, "operation-review")
        assert refused.returncode == 2 and "production runtime" in json.loads(refused.stdout)["error"]
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# 2. Database role policy
# ---------------------------------------------------------------------------

def test_the_policy_covers_exactly_the_phase14_evidence_tables():
    assert set(roles.MIGRATION_TABLES) == set(br.PHASE14_TABLES)
    assert not set(roles.MIGRATOR_LOCK_ONLY) & set(roles.MIGRATION_TABLES)


def test_rollback_refuses_identifiers_it_cannot_quote_safely():
    recorded = {"roles": {"rt_role": {"relations": {}, "columns": {}}, "mig_role": {"relations": {}, "columns": {}}},
                "relations_present": {'users"; DROP TABLE users; --': "r"}, "triggers": [], "functions": []}
    with pytest.raises(SystemExit):
        roles.rollback_sql(recorded, runtime_role="rt_role", migrator_role="mig_role")


def test_the_policy_sql_is_fixed_and_validates_role_names():
    statements = roles.policy_sql(runtime_role="rt_role", migrator_role="mig_role")
    revoke = next(st for st in statements if st.startswith("DO $$"))
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE, TRIGGER ON public.%I FROM %I" in revoke
    assert "left(tablename, 18) = 'billing_migration_'" in revoke and "'billing_migration_runs'" in revoke
    assert not any(re.search(r"GRANT [A-Z ,]*\b(DELETE|TRUNCATE)\b", s) for s in statements)
    for bad in ("x; DROP TABLE users", "Robert'", "", "1abc"):
        with pytest.raises(SystemExit):
            roles.policy_sql(runtime_role=bad, migrator_role="mig_role")
    with pytest.raises(SystemExit):
        roles.policy_sql(runtime_role="same", migrator_role="same")


@pytest.fixture
def pg_roles():
    engine = _migrated_engine()
    suffix = uuid.uuid4().hex[:8]
    names = {"runtime": f"bi2_rt_{suffix}", "migrator": f"bi2_mig_{suffix}"}
    with engine.begin() as connection:
        for name in names.values():
            connection.execute(sa.text(f"CREATE ROLE {name} NOLOGIN"))
        # The runtime starts with more than staging's does today (every table privilege, a sequence), so the
        # tests see the policy remove exactly the evidence writes and rollback restore everything else.
        connection.execute(sa.text(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {names['runtime']}"))
        connection.execute(sa.text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {names['runtime']}"))
    try:
        yield engine, names
    finally:
        with engine.begin() as connection:
            for table in roles.MIGRATOR_LOCK_ONLY:
                connection.execute(sa.text(f"DROP TRIGGER IF EXISTS {roles.LOCK_ONLY_TRIGGER} ON {table}"))
            for table in roles.WRITE_GUARDED:
                connection.execute(sa.text(f"DROP TRIGGER IF EXISTS {roles.WRITE_GUARD_TRIGGER} ON {table}"))
            for function in (roles.LOCK_ONLY_FUNCTION, roles.WRITE_GUARD_FUNCTION):
                connection.execute(sa.text(f"DROP FUNCTION IF EXISTS {function}()"))
            for name in names.values():
                connection.execute(sa.text(f"DROP OWNED BY {name}"))
                connection.execute(sa.text(f"DROP ROLE {name}"))
        engine.dispose()


def _apply(engine, statements):
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(sa.text(statement))


def _as(engine, role):
    return sa.create_engine(engine.url, connect_args={"options": f"-c role={role}"})


@PG
def test_postgres_the_migrator_runs_every_evidence_command_and_the_runtime_cannot_write_evidence(
        pg_roles, monkeypatch):
    import app.billing_migration as bm
    import app.billing_shadow as bs
    from app.billing_offers import record_staff_billing_permission
    from app.models import AIOperation
    from tests.test_billing_rehearsal import rehearse, world

    engine, names = pg_roles
    monkeypatch.setattr(bm, "migration_max_turn_seconds", lambda config=None: 1800)
    _apply(engine, roles.policy_sql(runtime_role=names["runtime"], migrator_role=names["migrator"]))
    with engine.connect() as connection:
        ok, findings = roles.verify(connection, runtime_role=names["runtime"], migrator_role=names["migrator"])
    assert ok, findings
    with migrated(engine) as session:
        w = world(session)
        staff = user(session, "reviewer")  # p14-reviewer-*: the reviewer ids the Phase 14 suite allows
        record_staff_billing_permission(
            session, grant_command_id=f"bi2-{uuid.uuid4().hex[:8]}", user_id=staff.id,
            permission="billing.migration.review", starts_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            ends_at=None, approval_evidence_reference="bi2-fixture", justification="BI-2 fixture",
            actor_type="system", actor_id="bi2-provisioning")
        operation = AIOperation(id=str(uuid.uuid4()), user_id=w.free.user, organization_id=w.free.org,
                                status="started", operation_type="score_batch", router_version="t",
                                policy_version="t", metadata_json={"idempotency_protected": True},
                                created_at=naive(now(session) - timedelta(days=40)),
                                updated_at=naive(now(session) - timedelta(days=40)))
        session.add(operation)
        session.commit()
        staff_id, operation_id = staff.id, operation.id
    migrator = _as(engine, names["migrator"])
    try:
        with Session(migrator.execution_options(isolation_level="READ COMMITTED"), expire_on_commit=False) as s:
            assert s.execute(sa.text("SELECT current_user")).scalar() == names["migrator"]
            decision, state = bm.record_operation_decision(
                s, decision_command_id=f"bi2-{uuid.uuid4().hex[:8]}", ai_operation_id=operation_id,
                disposition="no_compensation_owed", evidence_reference="bi2", reason="bi2 fixture",
                reviewer_user_id=staff_id)
            s.commit()
            assert state == "inserted"
            result = rehearse(s, w)
            assert result["legacy_unchanged"] and result["census_delta"]["billing_migration_openings"] == 5
            report = bs.shadow_reconciliation(s, organization_ids=w.orgs, at=now(s), test_activity_attestation=None)
            assert report["accounts"]
            # Restore-copy role checks of the rehearsal pass as this role.
            pre = br.rehearsal_preconditions(s, environment="restore_copy", runtime_role=names["runtime"],
                                             writer_freeze_reference="bi2-fixture")
            found = {f["check"]: f["status"] for f in pre["findings"]}
            assert found["migration_role_least_privilege"] == "pass"
            assert found["runtime_role_cannot_write_phase14"] == "pass"
            s.rollback()
        with migrator.begin() as connection:  # it may lock legacy rows, never change them
            with pytest.raises(sa.exc.DBAPIError, match="may lock users rows but never change them"):
                connection.execute(sa.text("UPDATE users SET id = id WHERE id = :u"), {"u": staff_id})
        for statement in ("UPDATE users SET credits_remaining = 0", "DELETE FROM billing_migration_runs",
                          "UPDATE billing_migration_runs SET run_key = run_key",
                          "UPDATE billing_staff_permission_grants SET justification = 'x'",
                          "TRUNCATE billing_migration_operation_decisions"):
            with migrator.begin() as connection, pytest.raises(sa.exc.DBAPIError, match="permission denied"):
                connection.execute(sa.text(statement))
        # The target-table writes are limited to exactly what Phase 14 writes (staging-only guard triggers).
        with migrated(engine) as session:
            from tests.test_billing_migration import organization
            paid = organization(session, user(session, "bi2-payer"), customer=f"cus_{uuid.uuid4().hex[:12]}")
            session.commit()
        for statement, match in (
            ("INSERT INTO credit_ledger_entries (id, billing_account_id, entry_type, available_delta, held_delta) "
             "VALUES ('bi2-forged', :a, 'admin_adjustment', -900, 0)", "only migration_opening entries"),
            ("INSERT INTO idempotency_registry (id, namespace, key, request_fingerprint, state) "
             "VALUES ('bi2-forged', 'billing.offers.redemption', 'k', repeat('a', 64), 'claimed')",
             "only billing.migration claims"),
            ("UPDATE billing_accounts SET processor_customer_id = 'cus_moved' WHERE id = :a",
             "only binds a processor customer to an account that has none"),
            ("INSERT INTO credit_lots (id, billing_account_id, source_type, source_id, original_amount, available_at,"
             " origin_evidence_json) VALUES ('bi2-forged', :a, 'promotional', 'x', 5, now(), '{}')",
             "only lots named by a migration opening"),
        ):
            with migrator.begin() as connection, pytest.raises(sa.exc.DBAPIError, match=match):
                connection.execute(sa.text(statement), {"a": paid.account})
    finally:
        migrator.dispose()
    runtime = _as(engine, names["runtime"])
    try:
        for table in roles.MIGRATION_TABLES:
            with runtime.begin() as connection, pytest.raises(sa.exc.DBAPIError, match="permission denied"):
                connection.execute(sa.text(f"DELETE FROM {table} WHERE false"))
        with runtime.begin() as connection:  # everything else the runtime had is kept
            connection.execute(sa.text("UPDATE users SET credits_remaining = credits_remaining WHERE false"))
            connection.execute(sa.text("SELECT count(*) FROM billing_migration_runs"))
    finally:
        runtime.dispose()


@PG
def test_postgres_verify_reports_drift_and_rollback_restores_the_snapshot_exactly(pg_roles):
    engine, names = pg_roles
    with engine.connect() as connection:
        before = roles.snapshot(connection, runtime_role=names["runtime"], migrator_role=names["migrator"])
        ok, findings = roles.verify(connection, runtime_role=names["runtime"], migrator_role=names["migrator"])
    assert not ok and any(f.get("problem") == "runtime can write" for f in findings)
    _apply(engine, roles.policy_sql(runtime_role=names["runtime"], migrator_role=names["migrator"]))
    _apply(engine, roles.policy_sql(runtime_role=names["runtime"], migrator_role=names["migrator"]))  # idempotent
    with engine.connect() as connection:
        assert roles.verify(connection, runtime_role=names["runtime"], migrator_role=names["migrator"])[0]
    # Drift the audit found verify() missing, each on its own; every one must fail verify.
    drifts = {
        "runtime_insert": ([f"GRANT INSERT ON billing_migration_operation_decisions TO {names['runtime']}"],
                           ("billing_migration_operation_decisions", "runtime can write")),
        "runtime_column_insert": ([f"GRANT INSERT (id, decision_key) ON billing_migration_operation_decisions "
                                   f"TO {names['runtime']}"],
                                  ("billing_migration_operation_decisions", "runtime can write")),
        "runtime_trigger": ([f"GRANT TRIGGER ON billing_migration_runs TO {names['runtime']}"],
                            ("billing_migration_runs", "runtime can write")),
        "migrator_extra_column": ([f"GRANT UPDATE (charged_credits) ON ai_operations TO {names['migrator']}"],
                                  ("ai_operations", "UPDATE columns differ")),
        "lock_trigger_dropped": ([f"DROP TRIGGER {roles.LOCK_ONLY_TRIGGER} ON payments"],
                                 ("payments", "lock-only trigger missing or not enforced")),
        "write_guard_dropped": ([f"DROP TRIGGER {roles.WRITE_GUARD_TRIGGER} ON credit_ledger_entries"],
                                ("credit_ledger_entries", "write guard trigger missing or not enforced")),
        "function_replaced": ([f"CREATE OR REPLACE FUNCTION {roles.LOCK_ONLY_FUNCTION}() RETURNS trigger "
                               "LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$"],
                              (None, "guard function missing or changed")),
        "membership": ([f"GRANT {names['runtime']} TO {names['migrator']}"], (None, "role membership")),
        "sequence": ([f"GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO {names['migrator']}"],
                     (None, "migrator holds a sequence privilege")),
        "new_evidence_table": ([f"CREATE TABLE billing_migration_bi2_future (id text PRIMARY KEY)",
                                f"GRANT ALL ON billing_migration_bi2_future TO {names['runtime']}"],
                               ("billing_migration_bi2_future", "runtime can write")),
    }
    for name, (statements, (table, problem)) in drifts.items():
        with engine.connect() as connection:
            transaction = connection.begin()
            for statement in statements:
                connection.execute(sa.text(statement))
            ok, findings = roles.verify(connection, runtime_role=names["runtime"], migrator_role=names["migrator"])
            transaction.rollback()
        assert not ok and any(f["problem"] == problem and f.get("table") == table for f in findings), (name, findings)
    # A future evidence table is covered by apply too.
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE billing_migration_bi2_future (id text PRIMARY KEY)"))
        connection.execute(sa.text(f"GRANT ALL ON billing_migration_bi2_future TO {names['runtime']}"))
    try:
        _apply(engine, roles.policy_sql(runtime_role=names["runtime"], migrator_role=names["migrator"]))
        with engine.connect() as connection:
            assert roles.verify(connection, runtime_role=names["runtime"], migrator_role=names["migrator"])[0]
    finally:
        with engine.begin() as connection:
            connection.execute(sa.text("DROP TABLE billing_migration_bi2_future"))
    # A table a later migration creates after the snapshot (the owner's default privileges grant the runtime
    # access) keeps that access through a rollback.
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE bi2_created_after_snapshot (id text PRIMARY KEY)"))
        connection.execute(sa.text(f"GRANT SELECT, INSERT ON bi2_created_after_snapshot TO {names['runtime']}"))
    _apply(engine, roles.rollback_sql(before, runtime_role=names["runtime"], migrator_role=names["migrator"]))
    with engine.connect() as connection:
        kept = roles._table_privileges(connection, names["runtime"], "bi2_created_after_snapshot")
    with engine.begin() as connection:
        connection.execute(sa.text("DROP TABLE bi2_created_after_snapshot"))
    assert kept == {"SELECT", "INSERT"}
    with engine.connect() as connection:
        after = roles.snapshot(connection, runtime_role=names["runtime"], migrator_role=names["migrator"])
        # The raw ACL entries (table, column and sequence level) are exactly as before, and no policy object stays.
        assert after == before
        assert after["triggers"] == [] and after["functions"] == []
        assert set(before["roles"][names["runtime"]]["relations"]["users"]["privileges"]) == set("arwdDxtm")


# ---------------------------------------------------------------------------
# 3. Restore-copy authorization
# ---------------------------------------------------------------------------

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)


def _authorization(**overrides):
    value = {
        "approval_reference": "founder-approval:2026-11-25:staging-evidence-run",
        "approved_by": "founder", "approved_at": "2026-11-25T10:00:00Z", "expires_at": "2026-12-02T10:00:00Z",
        "database": {"host": "private-staging-copy.example.invalid", "name": "defaultdb",
                     "system_identifier": "1234567890123456789"},
        "restore_provenance": {"source_cluster": "production-cluster", "restore_cluster": "staging-cluster",
                               "method": "provider point-in-time restore", "restored_from_utc": "2026-11-22T18:00:00Z"},
    }
    for key, item in overrides.items():
        if item is None:
            value.pop(key)
        elif isinstance(item, dict) and isinstance(value.get(key), dict):
            value[key] = {**value[key], **item}
        else:
            value[key] = item
    return value


def _config(authorization=None, hosts="db-production.example.invalid", roles_list=None):
    config = {rc.PRODUCTION_HOSTS_KEY: hosts}
    if authorization is not None:
        config[rc.AUTHORIZATION_KEY] = json.dumps(authorization) if isinstance(authorization, dict) else authorization
    if roles_list is not None:
        config[rc.PRODUCTION_LOGIN_ROLES_KEY] = roles_list
    return config


def test_a_complete_founder_authorization_is_accepted():
    parsed = rc.check_authorization_configuration(_config(_authorization()), now=NOW)
    assert parsed["approval_reference"].startswith("founder-approval:")
    assert parsed["database"]["system_identifier"] == "1234567890123456789"
    assert parsed["production_login_roles"] == ["jaspen_app_prod"]


@pytest.mark.parametrize("config,match", [
    (_config(None), "no restore-copy authorization"),
    (_config("{not json"), "not valid JSON"),
    (_config(_authorization(approved_by="operator")), "only by the founder"),
    (_config(_authorization(approval_reference=" ")), "approval_reference"),
    (_config(_authorization(expires_at="2026-11-25T11:00:00Z")), "has expired"),
    (_config(_authorization(expires_at="2026-12-31T10:00:00Z")), "within 14 days"),
    (_config(_authorization(approved_at="2026-11-26T10:00:00Z", expires_at="2026-11-27T10:00:00Z")), "future"),
    (_config(_authorization(expires_at="2026-12-02T10:00:00")), "UTC"),
    (_config(_authorization(database={"system_identifier": "abc"})), "decimal"),
    (_config(_authorization(restore_provenance={"restored_from_utc": "2026-11-25T11:00:00Z"})),
     "restored before it was authorized"),
    (_config(_authorization(restore_provenance=None)), "names exactly"),
    (_config(_authorization(), hosts=""), "must name the production database hosts"),
    (_config(_authorization(database={"host": "db-production.example.invalid"})), "is a production database host"),
    (_config(_authorization(restore_provenance={"restore_cluster": "db-production.example.invalid"})),
     "restore cluster is a production cluster"),
    (_config(_authorization(restore_provenance={"restore_cluster": "db-production"})),
     "restore cluster is a production cluster"),
    (_config(_authorization(), roles_list="bad name"), "invalid role name"),
])
def test_every_missing_or_wrong_authorization_fact_is_refused(config, match):
    with pytest.raises(rc.RestoreCopyAuthorizationError, match=match):
        rc.check_authorization_configuration(config, now=NOW)


@pytest.mark.parametrize("variable,value", [("APP_ENV", "production"), ("STRIPE_SECRET_KEY", "sk_live_example")])
def test_a_production_runtime_is_refused(monkeypatch, variable, value):
    monkeypatch.setenv(variable, value)
    with pytest.raises(rc.RestoreCopyAuthorizationError, match="production runtime"):
        rc.check_authorization_configuration(_config(_authorization()), now=NOW)


def _live_authorization(connection, url, **database):
    identity = {"host": url.host, "name": connection.execute(sa.text("SELECT current_database()")).scalar(),
                "system_identifier": str(connection.execute(sa.text(
                    "SELECT system_identifier FROM pg_control_system()")).scalar())}
    approved = datetime.now(timezone.utc) - timedelta(hours=1)
    value = _authorization(approved_at=approved.strftime("%Y-%m-%dT%H:%M:%SZ"),
                           expires_at=(approved + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                           database={**identity, **database},
                           restore_provenance={"restored_from_utc": (approved - timedelta(days=1)).strftime(
                               "%Y-%m-%dT%H:%M:%SZ")})
    return value


@PG
def test_postgres_the_live_database_identity_must_match_and_never_be_production():
    engine = _migrated_engine()
    try:
        with engine.connect() as connection:
            good = _live_authorization(connection, engine.url)
            parsed = rc.check_authorization_configuration(_config(good))
            facts = rc.verify_restore_copy_database(connection, parsed, host=engine.url.host)
            assert facts["identity_verified"] and facts["approval_reference"] == good["approval_reference"]
            for database, match in (({"system_identifier": "1"}, "not the authorized restore copy"),
                                    ({"name": "another_database"}, "not the authorized restore copy")):
                bad = rc.check_authorization_configuration(_config(_live_authorization(connection, engine.url,
                                                                                         **database)))
                with pytest.raises(rc.RestoreCopyAuthorizationError, match=match):
                    rc.verify_restore_copy_database(connection, bad, host=engine.url.host)
            with pytest.raises(rc.RestoreCopyAuthorizationError, match="not the authorized restore copy"):
                rc.verify_restore_copy_database(connection, parsed, host="other-host.example.invalid")
            with pytest.raises(rc.RestoreCopyAuthorizationError, match="production database host"):
                rc.verify_restore_copy_database(connection, {**parsed, "production_hosts": [engine.url.host]},
                                                host=engine.url.host)
        # A production login role on the connected database marks it as production.
        role = f"bi2_prod_{uuid.uuid4().hex[:8]}"
        with engine.begin() as connection:
            connection.execute(sa.text(f"CREATE ROLE {role} LOGIN"))
        try:
            with engine.connect() as connection:
                marked = rc.check_authorization_configuration(_config(good, roles_list=role))
                with pytest.raises(rc.RestoreCopyAuthorizationError, match="production login role"):
                    rc.verify_restore_copy_database(connection, marked, host=engine.url.host)
        finally:
            with engine.begin() as connection:
                connection.execute(sa.text(f"DROP ROLE {role}"))
    finally:
        engine.dispose()


@PG
def test_postgres_an_authorized_restore_copy_runs_the_shadow_comparison_read_only(monkeypatch):
    import app.billing_shadow as bs
    from tests.test_billing_rehearsal import world

    engine = _migrated_engine()
    try:
        with migrated(engine) as session:
            w = world(session)
        with engine.connect() as connection:
            config = _config(_live_authorization(connection, engine.url))
        monkeypatch.setattr(bs, "restore_copy_config", lambda: config)
        result = bs.run_shadow_reconciliation(engine, organization_ids=w.orgs, environment="restore_copy",
                                              test_activity_attestation=None)
        assert result["census_unchanged"] and result["restore_copy_authorization"]["identity_verified"]
        expired = json.loads(config[rc.AUTHORIZATION_KEY])
        expired["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        monkeypatch.setattr(bs, "restore_copy_config", lambda: {**config, rc.AUTHORIZATION_KEY: json.dumps(expired)})

        class NoConnect:
            def connect(self):
                raise AssertionError("an expired authorization opened a database connection")

        with pytest.raises(bs.ShadowError, match="has expired"):
            bs.run_shadow_reconciliation(NoConnect(), organization_ids=w.orgs, environment="restore_copy",
                                         test_activity_attestation=None)
    finally:
        engine.dispose()


@PG
def test_postgres_the_rehearsal_restore_copy_precondition_needs_the_authorization(monkeypatch):
    engine = _migrated_engine()
    try:
        with migrated(engine) as session:
            refused = br.rehearsal_preconditions(session, environment="restore_copy")
            found = next(f for f in refused["findings"] if f["check"] == "restore_copy_authorized")
            assert found["status"] == "fail" and "no restore-copy authorization" in found["detail"]
            assert not refused["ready"]
            config = _config(_live_authorization(session.connection(), engine.url))
            monkeypatch.setattr(br, "restore_copy_config", lambda: config)
            allowed = br.rehearsal_preconditions(session, environment="restore_copy")
            found = next(f for f in allowed["findings"] if f["check"] == "restore_copy_authorized")
            assert found["status"] == "pass" and found["detail"]["identity_verified"]
            session.rollback()
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# 4. Deploy data census
# ---------------------------------------------------------------------------

def _census(**tables):
    return {"tables": tables, "alembic": ["f3a5c7e9b1d2"]}


def test_census_compare_tells_expected_migration_effects_from_unexpected_changes():
    before = _census(users=26, payments=0, billing_migration_runs=0)
    same = staging_database.compare_census(before, _census(users=26, payments=0, billing_migration_runs=0),
                                           migrations_ran=False)
    assert same["unexpected"] == [] and same["expected"] == [] and same["unchanged_tables"] == 3
    migrated_ok = staging_database.compare_census(
        before, _census(users=26, payments=0, billing_migration_runs=0, new_table=0), migrations_ran=True)
    assert migrated_ok["expected"] == [{"table": "new_table", "effect": "created_empty_by_migration"}]
    assert migrated_ok["unexpected"] == []
    bad = staging_database.compare_census(before, _census(users=25, billing_migration_runs=0, new_table=3,
                                                          other=0), migrations_ran=False)
    assert {(u["table"], u["effect"]) for u in bad["unexpected"]} == {
        ("users", "row_count_changed"), ("payments", "dropped"), ("new_table", "created_with_rows"),
        ("other", "created_without_migration")}


def test_census_compare_command_exit_codes(tmp_path):
    before, after = tmp_path / "before.json", tmp_path / "after.json"
    before.write_text(json.dumps(_census(users=1)))
    after.write_text(json.dumps(_census(users=1, created=0)))
    script = str(STAGING / "staging_database.py")
    ok = subprocess.run([sys.executable, "-I", script, "census-compare", "--before", str(before), "--after",
                         str(after), "--migrations-ran", "true"], capture_output=True, text=True)
    assert ok.returncode == 0 and "PASS census_compare unchanged=1 expected=1 unexpected=0" in ok.stdout
    warn = subprocess.run([sys.executable, "-I", script, "census-compare", "--before", str(before), "--after",
                           str(after), "--migrations-ran", "false"], capture_output=True, text=True)
    assert warn.returncode == 3 and "WARN census unexpected created_without_migration created" in warn.stdout


@PG
def test_postgres_the_census_counts_every_table_read_only():
    engine = _migrated_engine()
    try:
        census = staging_database.table_counts(engine)
        assert "billing_migration_operation_decisions" in census["tables"] and census["alembic"]
        assert all(isinstance(n, int) and n >= 0 for n in census["tables"].values())
    finally:
        engine.dispose()


def test_the_wrapper_takes_the_census_before_any_change_and_compares_after_health():
    body = (STAGING / "jaspen-staging-deploy").read_text()
    deploy = body[body.index("deploy_or_rollback() {"):body.index("show_status() {")]
    assert deploy.index('census_to "${CENSUS_BEFORE}"') < deploy.index("CHECKED_OUT=\"true\"")
    assert deploy.index("wait_for_health") < deploy.index('compare_census "${CENSUS_BEFORE}"') \
        < deploy.index('write_record "deployed"')
    assert 'fail "census before the ${MODE} (nothing changed)"' in deploy
    # The role policy is verified in the preflight and re-applied only after migrations, only when enforced.
    assert body.count("roles_helper apply --confirm") == 1
    migrations = deploy[deploy.index('MIGRATIONS_RAN="true"'):deploy.index('PASS G4 migrations applied"') + 200]
    assert 'roles_helper apply --confirm' in migrations and '[[ "${ROLE_POLICY}" == "enforce" ]]' in migrations
