"""Production-shape rehearsal for a4d7c9e2f105.

PostgreSQL starts from an empty schema and Alembic upgrades it to the exact
production revision before synthetic legacy rows are inserted.  Historical
SQLite migrations cannot reach that revision (an older migration uses ALTER
CONSTRAINT, which SQLite does not support), so SQLite builds the current model
schema, removes later empty additive foundations, applies the real
a4d7c9e2f105 downgrade to obtain its predecessor shape, and stamps that
database at f1a2b3c4d5e6.  From that point onward both
dialects run the same seed, upgrade, assertions, no-op upgrade, and downgrade.

The one-step downgrade is intentionally schema-only: it drops decision_signals
and the four option-decision columns.  It does not undo backfilled option rows,
first-scored provenance, option-registry provenance, or plan JSON rewrites.
Those retained changes are asserted below so rollback behavior stays explicit.
"""

import contextlib
import copy
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory


BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = BACKEND_DIR / "migrations"
PRODUCTION_REVISION = "f1a2b3c4d5e6"
MIGRATION_REVISION = "a4d7c9e2f105"
ACCOUNT_FOUNDATION_REVISION = "b5e7c9a1d3f2"
CURRENT_ADDITIVE_REVISION = "c6f8d0b2e4a1"
COMPATIBILITY_LINKS_REVISION = "d7a9e1c3f5b2"
FIXED_TIME = datetime(2026, 10, 1, 12, 0, 0)
SCORE_TIME = datetime(2026, 9, 20, 9, 30, 0)


def _alembic(database_url, command, revision):
    env = os.environ.copy()
    env.update({
        "DATABASE_URL": database_url,
        "APP_ENV": "test",
        "JWT_SECRET_KEY": "migration-rehearsal-jwt",
        "SECRET_KEY": "migration-rehearsal-secret",
        "STRIPE_SECRET_KEY": "sk_test_migration_rehearsal",
        "PYTHONPATH": ".",
    })
    env.pop("TEST_DATABASE_URL", None)
    for key in ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY", "GEMINI_API_KEY"):
        env.pop(key, None)
    completed = subprocess.run(
        [sys.executable, "-m", "flask", "--app", "wsgi:app", "db", command, revision],
        cwd=BACKEND_DIR,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def _revision_module():
    return ScriptDirectory(str(MIGRATIONS_DIR)).get_revision(MIGRATION_REVISION).module


def _current_additive_revision_module():
    return ScriptDirectory(str(MIGRATIONS_DIR)).get_revision(CURRENT_ADDITIVE_REVISION).module


def _compatibility_links_revision_module():
    return ScriptDirectory(str(MIGRATIONS_DIR)).get_revision(
        COMPATIBILITY_LINKS_REVISION
    ).module


def _account_foundation_revision_module():
    return ScriptDirectory(str(MIGRATIONS_DIR)).get_revision(ACCOUNT_FOUNDATION_REVISION).module


def _prepare_sqlite_at_production_revision(database_url):
    """Create f1a2b3c4d5e6 shape without replaying SQLite-incompatible history."""
    from app import db
    import app.models_decision_baseline  # noqa: F401
    import app.models_decision_record  # noqa: F401
    import app.models_pm_sync  # noqa: F401
    import app.models_studio  # noqa: F401

    engine = sa.create_engine(database_url)
    db.metadata.create_all(engine)
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            _compatibility_links_revision_module().downgrade()
            _current_additive_revision_module().downgrade()
            _account_foundation_revision_module().downgrade()
            _revision_module().downgrade()
        connection.execute(sa.text(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        ))
        connection.execute(
            sa.text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
            {"revision": PRODUCTION_REVISION},
        )
    engine.dispose()


def _json_value(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value
    return value


def _stable(value):
    """Canonical bytes for exact before/after comparisons across both drivers."""
    value = _json_value(value)
    if isinstance(value, datetime):
        value = value.isoformat()
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()


def _reflect(engine):
    metadata = sa.MetaData()
    metadata.reflect(engine, only=[
        "users", "user_sessions", "scorecards", "decision_records",
        "decision_option_decisions", "alembic_version",
    ])
    return metadata.tables


def _insert_user(connection, users):
    values = {
        "id": "user-migration",
        "email": "migration-rehearsal@example.test",
        "name": "Migration Rehearsal",
        "password_hash": "not-a-real-password-hash",
        "subscription_plan": "free",
        "seat_limit": 1,
        "max_seats": 1,
        "unlimited_analysis": False,
        "credits_remaining": 100,
        "failed_login_attempts": 0,
        "mfa_enabled": False,
        "auth_token_version": 0,
        "email_verified": True,
        "password_reset_version": 0,
        "access_approval_status": "approved",
        "referral_code": "migration-rehearsal-referral",
        "referrals_earned": 0,
        "feedback_earned": 0,
        "created_at": FIXED_TIME,
        "updated_at": FIXED_TIME,
    }
    connection.execute(users.insert().values(**{
        key: value for key, value in values.items() if key in users.c
    }))


def _record_values(record_id, thread_id, payload):
    return {
        "id": record_id,
        "user_id": "user-migration",
        "organization_id": None,
        "thread_id": thread_id,
        "title": f"Synthetic {record_id}",
        "decision_statement": "Synthetic migration rehearsal",
        "status": "recorded",
        "decision_type": "synthetic",
        "altitude": "team",
        "library_consent": "none",
        "library_consented_at": None,
        "internal_corpus_eligible": False,
        "schema_version": 3,
        "record": payload,
        "final_decision": None,
        "outcomes": [{"summary": "unchanged outcome"}],
        "lessons_learned": [{"lesson": "unchanged lesson"}],
        "accepted_exposures": [{"exposure": "unchanged exposure"}],
        "tags": ["migration", "unchanged"],
        "created_at": FIXED_TIME,
        "updated_at": FIXED_TIME,
        "decided_at": None,
        "outcome_recorded_at": None,
    }


def _session_values(session_id, payload, scenarios, revision):
    return {
        "user_id": "user-migration",
        "session_id": session_id,
        "name": f"Synthetic {session_id}",
        "document_type": "strategy",
        "status": "in_progress",
        "organization_id": None,
        "created_by_user_id": "user-migration",
        "visibility": "private",
        "shared_with_user_ids": ["unchanged-share"],
        "payload": payload,
        "scenarios_json": scenarios,
        "created_at": FIXED_TIME,
        "updated_at": FIXED_TIME,
        "revision": revision,
        "last_edited_by_user_id": None,
        "hidden_for_user_ids": ["unchanged-hidden"],
    }


def _option_values(option_id, option_key, option_name, final_decision, source,
                   kit_verdict=None, capture_metadata=None):
    return {
        "id": option_id,
        "decision_record_id": "record-main",
        "option_key": option_key,
        "option_name": option_name,
        "final_decision": final_decision,
        "rationale": f"unchanged rationale {option_id}",
        "source": source,
        "kit_verdict": kit_verdict,
        "override_info": {"unchanged": option_id},
        "decided_by_user_id": "user-migration",
        "decided_by_name": "Unchanged Human",
        "supersedes_id": None,
        "superseded_at": None,
        "outcomes": [{"summary": f"unchanged {option_id}"}],
        "lessons_learned": [{"lesson": f"unchanged {option_id}"}],
        "decided_at": FIXED_TIME,
        "created_at": FIXED_TIME,
        "updated_at": FIXED_TIME,
        **({"capture_metadata": capture_metadata} if capture_metadata is not None else {}),
    }


def _seed_legacy_rows(engine):
    tables = _reflect(engine)
    users = tables["users"]
    records = tables["decision_records"]
    sessions = tables["user_sessions"]
    scorecards = tables["scorecards"]
    options = tables["decision_option_decisions"]

    main_payload = {
        "unchanged_top": {"ordered": [3, 2, 1]},
        "scorecards": [
            {"id": "card-score", "option_key": "opt-score", "name": "Score Match", "unchanged": "score"},
            {"id": "card-generated", "option_key": "opt-generated", "name": "Generated", "generated_at": "2026-09-21T10:00:00Z", "unchanged": "generated"},
            {"id": "card-created", "option_key": "opt-created", "name": "Created", "createdAt": "2026-09-22T11:00:00+00:00", "unchanged": "created"},
            {"id": "card-record", "option_key": "opt-record", "name": "Record Fallback", "unchanged": "record"},
            {"id": "card-existing-time", "option_key": "opt-existing-time", "name": "Existing Time", "first_scored_at": "2026-01-01T00:00:00", "first_scored_source": "already.present", "unchanged": "existing"},
            "malformed-card-entry",
        ],
    }
    legacy_payload = {
        "unchanged_top": "legacy",
        "scorecards": [{
            "id": "legacy-card", "option_key": "opt-legacy", "name": "Legacy Plan",
            "generated_at": "2026-09-23T12:00:00Z", "unchanged": "legacy-card",
        }],
    }
    keyed_payload = {
        "unchanged_top": "keyed",
        "scorecards": [{
            "id": "keyed-card", "option_key": "opt-keyed", "name": "Keyed Plan",
            "createdAt": "2026-09-24T13:00:00Z", "unchanged": "keyed-card",
        }],
    }
    orphan_payload = {
        "unchanged_top": "orphan",
        "scorecards": [{
            "id": "orphan-card", "option_key": "opt-orphan", "name": "No Session",
            "generated_at": "2026-09-25T14:00:00Z", "unchanged": "orphan-card",
        }],
    }

    with engine.begin() as connection:
        _insert_user(connection, users)
        connection.execute(records.insert(), [
            _record_values("record-main", "thread-main", main_payload),
            _record_values("record-legacy", "thread-legacy", legacy_payload),
            _record_values("record-keyed", "thread-keyed", keyed_payload),
            _record_values("record-orphan", "thread-orphan", orphan_payload),
            _record_values("record-malformed", "thread-malformed", "{malformed-json"),
            _record_values("record-empty", "thread-empty", {}),
        ])
        connection.execute(scorecards.insert(), [{
            "id": "persisted-score",
            "user_id": "user-migration",
            "organization_id": None,
            "thread_id": "thread-main",
            "session_id": "thread-main",
            "decision_record_id": "record-main",
            "project_name": "Score Match",
            "rubric": {"unchanged": True},
            "evidence": [{"unchanged": True}],
            "score": 81.5,
            "assumptions": [],
            "recommendation": {"unchanged": True},
            "execution_plan_ref": None,
            "data": {"option_key": "opt-score", "unchanged": "score-data"},
            "search_metadata": {"unchanged": True},
            "source": "native",
            "created_at": SCORE_TIME,
            "updated_at": SCORE_TIME,
            "archived_at": None,
        }])

        connection.execute(sessions.insert(), [
            _session_values(
                "thread-main",
                {
                    "unchanged_payload": {"keep": [1, 2, 3]},
                    "option_registry": {
                        "opt-score": {"name": "Score Match", "unchanged": "registry-score"},
                        "opt-generated": {"name": "Generated", "unchanged": "registry-generated"},
                        "opt-existing-time": {"name": "Existing", "first_scored_at": "2026-01-01T00:00:00", "first_scored_source": "already.present"},
                        "malformed-entry": "not-an-object",
                    },
                },
                {
                    "unchanged_scenarios": {"keep": ["yes"]},
                    "active_execution_scorecard_id": "card-score",
                    "wbs_by_scorecard": {
                        "card-score": {"scorecard_id": "card-score", "created_at": "2026-09-26T15:00:00Z", "tasks": [{"id": "task-score", "due_date": "2026-12-01"}], "unchanged": "score-plan"},
                        "card-generated": {"scorecard_id": "card-generated", "decision_basis": {"already": "present"}, "tasks": [], "unchanged": "generated-plan"},
                        "card-created": {"scorecard_id": "card-created", "tasks": [], "unchanged": "existing-decision-plan"},
                    },
                },
                41,
            ),
            _session_values(
                "thread-legacy",
                {"unchanged_payload": "legacy", "option_registry": {"opt-legacy": {"name": "Legacy Plan"}}},
                {
                    "unchanged_scenarios": "legacy",
                    "active_execution_scorecard_id": "legacy-card",
                    "project_wbs": {"scorecard_id": "legacy-card", "created_at": "2026-09-27T16:00:00Z", "tasks": [{"id": "legacy-task", "due_date": "2027-01-01"}], "unchanged": "legacy-plan"},
                },
                42,
            ),
            _session_values(
                "thread-keyed",
                {"unchanged_payload": "keyed", "option_registry": {}},
                {"unchanged_scenarios": "keyed", "wbs_by_scorecard": {"keyed-card": {"scorecard_id": "keyed-card", "tasks": [], "unchanged": "keyed-plan"}}},
                43,
            ),
            _session_values("thread-malformed", "{malformed-payload", "{malformed-scenarios", 44),
            _session_values("thread-empty", {}, {}, 45),
        ])

        option_rows = []
        verdicts = {
            "verdict-advance": ("advance", "pursue"),
            "verdict-conditions": ("advance_with_conditions", "pursue"),
            "verdict-decline": ("decline", "not_pursue"),
            "verdict-deferred": ("deferred", "still_evaluating"),
        }
        for option_id, (verdict, _) in verdicts.items():
            option_rows.append(_option_values(
                option_id, option_id, option_id, "Unmatched final decision", "manual",
                {"verdict_key": verdict, "unchanged": option_id},
            ))
        for source in ("build_execution_plan", "plan_created", "legacy_plan"):
            option_rows.append(_option_values(
                f"source-{source}", f"source-{source}", source,
                "Unmatched final decision", source, "{malformed-kit-verdict",
            ))
        canned = [
            ("canned-forward", "Alpha", "Moving forward with Alpha.", "pursue"),
            ("canned-built", "Beta", "Moving forward with Beta — execution plan built.", "pursue"),
            ("canned-declined", "Gamma", "Declined Gamma.", "not_pursue"),
            ("canned-deferred", "Delta", "Deferred Delta.", "still_evaluating"),
        ]
        for option_id, name, final_decision, _ in canned:
            option_rows.append(_option_values(
                option_id, option_id, name, final_decision, "manual", {},
            ))
        option_rows.extend([
            _option_values(
                "matching-none", "matching-none", "None", "A human wrote something else.",
                "manual", {},
            ),
            _option_values(
                "existing-plan-decision", "opt-created", "Created",
                "Existing option decision must suppress a generated duplicate.", "manual", {},
            ),
        ])
        connection.execute(options.insert(), option_rows)


def _rows_by_id(connection, table_name, id_column="id"):
    rows = connection.execute(sa.text(f"SELECT * FROM {table_name}")).mappings().all()
    return {str(row[id_column]): dict(row) for row in rows}


def _snapshot_unrelated(engine):
    with engine.connect() as connection:
        options = _rows_by_id(connection, "decision_option_decisions")
        records = _rows_by_id(connection, "decision_records")
        sessions = _rows_by_id(connection, "user_sessions")
    option_excluded = {"disposition", "user_quote", "basis_snapshot", "capture_metadata"}
    record_excluded = {"record"}
    session_excluded = {"payload", "scenarios_json"}
    return {
        "options": {
            key: {name: _stable(value) for name, value in row.items() if name not in option_excluded}
            for key, row in options.items()
        },
        "records": {
            key: {name: _stable(value) for name, value in row.items() if name not in record_excluded}
            for key, row in records.items()
        },
        "sessions": {
            key: {name: _stable(value) for name, value in row.items() if name not in session_excluded}
            for key, row in sessions.items()
        },
    }


def _database_snapshot(engine):
    with engine.connect() as connection:
        snapshot = {}
        for table, order_by in (
            ("decision_option_decisions", "id"),
            ("decision_records", "id"),
            ("user_sessions", "id"),
            ("decision_signals", "id"),
        ):
            rows = connection.execute(sa.text(
                f"SELECT * FROM {table} ORDER BY {order_by}"
            )).mappings().all()
            snapshot[table] = [
                {key: _stable(value) for key, value in row.items()} for row in rows
            ]
        snapshot["revision"] = connection.execute(
            sa.text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    return snapshot


def _assert_upgraded(engine, before):
    inspector = sa.inspect(engine)
    assert {column["name"] for column in inspector.get_columns("decision_option_decisions")} >= {
        "disposition", "user_quote", "basis_snapshot", "capture_metadata",
    }
    assert "decision_signals" in inspector.get_table_names()

    with engine.connect() as connection:
        options = _rows_by_id(connection, "decision_option_decisions")
        records = _rows_by_id(connection, "decision_records")
        sessions = _rows_by_id(connection, "user_sessions")
        version = connection.execute(sa.text(
            "SELECT version_num FROM alembic_version"
        )).scalar_one()
    assert version == COMPATIBILITY_LINKS_REVISION

    expected_dispositions = {
        "verdict-advance": "pursue",
        "verdict-conditions": "pursue",
        "verdict-decline": "not_pursue",
        "verdict-deferred": "still_evaluating",
        "source-build_execution_plan": "pursue",
        "source-plan_created": "pursue",
        "source-legacy_plan": "pursue",
        "canned-forward": "pursue",
        "canned-built": "pursue",
        "canned-declined": "not_pursue",
        "canned-deferred": "still_evaluating",
        "matching-none": None,
        "existing-plan-decision": None,
    }
    for option_id, disposition in expected_dispositions.items():
        assert options[option_id]["disposition"] == disposition
        assert options[option_id]["source"] == before["option_sources"][option_id]
    assert _json_value(options["verdict-deferred"]["capture_metadata"])["deferred"] is True
    assert _json_value(options["canned-deferred"]["capture_metadata"])["deferred"] is True
    assert _json_value(options["matching-none"]["capture_metadata"]) == {}

    main_record = _json_value(records["record-main"]["record"])
    cards = {card["id"]: card for card in main_record["scorecards"] if isinstance(card, dict)}
    assert cards["card-score"]["first_scored_at"] == SCORE_TIME.isoformat()
    assert cards["card-score"]["first_scored_source"] == "scorecard.created_at"
    assert cards["card-generated"]["first_scored_at"] == "2026-09-21T10:00:00"
    assert cards["card-generated"]["first_scored_source"] == "scorecard.generated_at"
    assert cards["card-created"]["first_scored_at"] == "2026-09-22T11:00:00"
    assert cards["card-created"]["first_scored_source"] == "scorecard.createdAt"
    assert cards["card-record"]["first_scored_at"] == FIXED_TIME.isoformat()
    assert cards["card-record"]["first_scored_source"] == "decision_record.created_at"
    assert cards["card-existing-time"]["first_scored_at"] == "2026-01-01T00:00:00"
    assert cards["card-existing-time"]["first_scored_source"] == "already.present"
    assert main_record["unchanged_top"] == {"ordered": [3, 2, 1]}
    assert main_record["scorecards"][-1] == "malformed-card-entry"

    orphan_record = _json_value(records["record-orphan"]["record"])
    assert orphan_record["scorecards"][0]["first_scored_source"] == "scorecard.generated_at"
    assert _json_value(records["record-malformed"]["record"]) == "{malformed-json"
    assert _json_value(records["record-empty"]["record"]) == {}

    sessions_by_thread = {row["session_id"]: row for row in sessions.values()}
    main_session = sessions_by_thread["thread-main"]
    main_payload = _json_value(main_session["payload"])
    assert main_payload["option_registry"]["opt-score"]["first_scored_at"] == SCORE_TIME.isoformat()
    assert main_payload["option_registry"]["opt-score"]["first_scored_source"] == "scorecard.created_at"
    assert main_payload["option_registry"]["opt-generated"]["first_scored_at"] == "2026-09-21T10:00:00"
    assert main_payload["option_registry"]["opt-generated"]["first_scored_source"] == "scorecard.generated_at"
    assert main_payload["option_registry"]["opt-existing-time"]["first_scored_source"] == "already.present"
    assert main_payload["option_registry"]["malformed-entry"] == "not-an-object"
    assert main_payload["unchanged_payload"] == {"keep": [1, 2, 3]}

    main_scenarios = _json_value(main_session["scenarios_json"])
    main_plans = main_scenarios["wbs_by_scorecard"]
    assert main_plans["card-score"]["decision_basis"] is None
    assert main_plans["card-score"]["decision_basis_reason"] == "created_before_snapshot"
    assert main_plans["card-generated"]["decision_basis"] == {"already": "present"}
    assert "decision_basis_reason" not in main_plans["card-generated"]
    assert main_scenarios["unchanged_scenarios"] == {"keep": ["yes"]}

    legacy_session = sessions_by_thread["thread-legacy"]
    legacy_scenarios = _json_value(legacy_session["scenarios_json"])
    assert legacy_scenarios["wbs_by_scorecard"]["legacy-card"] == legacy_scenarios["project_wbs"]
    assert legacy_scenarios["project_wbs"]["decision_basis"] is None
    assert legacy_scenarios["project_wbs"]["decision_basis_reason"] == "created_before_snapshot"

    keyed_scenarios = _json_value(sessions_by_thread["thread-keyed"]["scenarios_json"])
    assert keyed_scenarios["wbs_by_scorecard"]["keyed-card"]["decision_basis"] is None
    assert keyed_scenarios["wbs_by_scorecard"]["keyed-card"]["decision_basis_reason"] == "created_before_snapshot"
    assert _json_value(sessions_by_thread["thread-malformed"]["payload"]) == "{malformed-payload"
    assert _json_value(sessions_by_thread["thread-malformed"]["scenarios_json"]) == "{malformed-scenarios"
    assert _json_value(sessions_by_thread["thread-empty"]["payload"]) == {}
    assert _json_value(sessions_by_thread["thread-empty"]["scenarios_json"]) == {}

    assert {thread: sessions_by_thread[thread]["revision"] for thread in sessions_by_thread} == before["revisions"]

    generated = [
        row for row in options.values()
        if row["source"] == "legacy_plan" and row["id"] != "source-legacy_plan"
    ]
    generated_by_key = {row["option_key"]: row for row in generated}
    assert set(generated_by_key) == {"opt-score", "opt-generated", "opt-legacy", "opt-keyed"}
    assert generated_by_key["opt-score"]["final_decision"] == "Moving forward with Score Match — legacy execution plan."
    assert generated_by_key["opt-legacy"]["decided_by_user_id"] == "user-migration"
    assert not [row for row in options.values() if row["option_key"] == "opt-orphan"]
    assert len([row for row in options.values() if row["option_key"] == "opt-created"]) == 1

    # Every non-target column is identical, including all human-owned fields.
    after = _snapshot_unrelated(engine)
    for table in ("options", "records", "sessions"):
        for row_id, expected in before["unrelated"][table].items():
            assert after[table][row_id] == expected


def _assert_downgraded(engine, upgraded_snapshot):
    inspector = sa.inspect(engine)
    assert "decision_signals" not in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("decision_option_decisions")}
    assert not ({"disposition", "user_quote", "basis_snapshot", "capture_metadata"} & columns)

    with engine.connect() as connection:
        version = connection.execute(sa.text(
            "SELECT version_num FROM alembic_version"
        )).scalar_one()
        options = _rows_by_id(connection, "decision_option_decisions")
        records = _rows_by_id(connection, "decision_records")
        sessions = _rows_by_id(connection, "user_sessions")
    assert version == PRODUCTION_REVISION
    assert len(options) == len(upgraded_snapshot["decision_option_decisions"])
    assert options["source-build_execution_plan"]["source"] == "build_execution_plan"

    main_record = _json_value(records["record-main"]["record"])
    cards = {card["id"]: card for card in main_record["scorecards"] if isinstance(card, dict)}
    assert cards["card-score"]["first_scored_at"] == SCORE_TIME.isoformat()
    sessions_by_thread = {row["session_id"]: row for row in sessions.values()}
    assert _json_value(sessions_by_thread["thread-main"]["payload"])["option_registry"]["opt-score"]["first_scored_source"] == "scorecard.created_at"
    assert _json_value(sessions_by_thread["thread-legacy"]["scenarios_json"])["wbs_by_scorecard"]["legacy-card"]["decision_basis_reason"] == "created_before_snapshot"
    assert {thread: row["revision"] for thread, row in sessions_by_thread.items()} == {
        "thread-main": 41,
        "thread-legacy": 42,
        "thread-keyed": 43,
        "thread-malformed": 44,
        "thread-empty": 45,
    }


def _run_rehearsal(database_url):
    engine = sa.create_engine(database_url)
    _seed_legacy_rows(engine)
    unrelated = _snapshot_unrelated(engine)
    with engine.connect() as connection:
        option_rows = _rows_by_id(connection, "decision_option_decisions")
        session_rows = _rows_by_id(connection, "user_sessions")
    before = {
        "unrelated": unrelated,
        "option_sources": {key: row["source"] for key, row in option_rows.items()},
        "revisions": {row["session_id"]: row["revision"] for row in session_rows.values()},
    }

    _alembic(database_url, "upgrade", "head")
    engine.dispose()
    engine = sa.create_engine(database_url)
    _assert_upgraded(engine, before)
    first_snapshot = _database_snapshot(engine)

    _alembic(database_url, "upgrade", "head")
    engine.dispose()
    engine = sa.create_engine(database_url)
    assert _database_snapshot(engine) == first_snapshot

    _alembic(database_url, "downgrade", "f1a2b3c4d5e6")
    engine.dispose()
    engine = sa.create_engine(database_url)
    _assert_downgraded(engine, first_snapshot)
    engine.dispose()


def test_decision_intelligence_migration_rehearsal_sqlite(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'decision-intelligence-rehearsal.sqlite'}"
    _prepare_sqlite_at_production_revision(database_url)
    _run_rehearsal(database_url)


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="PostgreSQL rehearsal requires TEST_DATABASE_URL",
)
def test_decision_intelligence_migration_rehearsal_postgres(
    validate_test_database_url, postgres_schema_url,
):
    base_url = validate_test_database_url(os.environ["TEST_DATABASE_URL"])
    schema = f"jaspen_a4_rehearsal_{uuid.uuid4().hex}"
    admin_engine = sa.create_engine(base_url, isolation_level="AUTOCOMMIT")
    schema_url = postgres_schema_url(base_url, schema)
    database_url = schema_url.render_as_string(hide_password=False)
    try:
        with admin_engine.connect() as connection:
            connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        _alembic(database_url, "upgrade", PRODUCTION_REVISION)
        _run_rehearsal(database_url)
    finally:
        with contextlib.suppress(Exception):
            with admin_engine.connect() as connection:
                connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()
