"""K/L: the migration path itself, exercised through Alembic.

The rest of the suite builds its schema with `_db.create_all()` (conftest.py),
which never runs a migration. A revision can therefore be broken while every
other test passes. These tests upgrade a real database through Alembic, and
one of them does it against a realistic PRE-Phase-1 schema so a migration that
cannot apply to production data fails here rather than in production.
"""
import contextlib
import os
import sqlite3

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRATIONS_DIR = os.path.join(BACKEND_DIR, "migrations")

PHASE_1_REVISION = "c4a1f7e93b28"
PREVIOUS_HEAD = "b7e2d91a4c03"

NEW_COLUMNS = {"revision", "last_edited_by_user_id", "hidden_for_user_ids"}


@contextlib.contextmanager
def _migration_ops(db_path):
    """Bind alembic's `op` to a scratch database.

    `migrations/env.py` rewrites `sqlalchemy.url` from `current_app` (line 40),
    so `alembic upgrade` cannot be pointed at a throwaway file. Driving the
    revision's own upgrade()/downgrade() through a MigrationContext runs the
    real migration code against a realistic pre-Phase-1 schema, which is the
    thing `create_all()` never exercises. Chain integrity is covered
    structurally by the revision-graph tests above.
    """
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            yield
        connection.commit()
    engine.dispose()


def _load_revision():
    script = ScriptDirectory(MIGRATIONS_DIR)
    return script.get_revision(PHASE_1_REVISION).module


def _upgrade(db_path):
    with _migration_ops(db_path):
        _load_revision().upgrade()


def _downgrade(db_path):
    with _migration_ops(db_path):
        _load_revision().downgrade()


def _columns(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def _indexes(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA index_list({table})")}
    finally:
        conn.close()


# --- the revision graph ------------------------------------------------------

def test_migration_graph_has_exactly_one_head():
    """A second head silently splits the schema. Keep the history linear."""
    script = ScriptDirectory(MIGRATIONS_DIR)
    heads = script.get_heads()
    assert len(heads) == 1, f"expected a single head, found {heads}"
    assert heads[0] == PHASE_1_REVISION


def test_phase_1_revision_follows_the_previous_head():
    script = ScriptDirectory(MIGRATIONS_DIR)
    rev = script.get_revision(PHASE_1_REVISION)
    assert rev.down_revision == PREVIOUS_HEAD


# --- K. the migration actually runs -----------------------------------------

def _seed_pre_phase_1_schema(db_path):
    """A realistic pre-Phase-1 database.

    Only the tables the Phase 1 revision touches, at the shape they had before
    it: `user_sessions` WITHOUT revision / last_edited_by_user_id /
    hidden_for_user_ids, and `users` with active_organization_id so the
    organization backfill has something to read.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript("""
            CREATE TABLE users (
                id VARCHAR(36) PRIMARY KEY,
                email VARCHAR(255),
                active_organization_id VARCHAR(36)
            );
            CREATE TABLE organizations (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(255)
            );
            CREATE TABLE user_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id VARCHAR(36) NOT NULL,
                session_id VARCHAR(255) NOT NULL,
                name VARCHAR(255),
                document_type VARCHAR(100),
                status VARCHAR(50),
                organization_id VARCHAR(36),
                created_by_user_id VARCHAR(36),
                visibility VARCHAR(32) NOT NULL DEFAULT 'private',
                shared_with_user_ids JSON,
                payload JSON NOT NULL,
                scenarios_json JSON,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                archived_at DATETIME,
                purge_after DATETIME,
                CONSTRAINT uq_user_sessions_user_id_session_id
                    UNIQUE (user_id, session_id)
            );

            INSERT INTO organizations (id, name) VALUES ('org-1', 'Acme');
            INSERT INTO users (id, email, active_organization_id)
                VALUES ('u-owner', 'owner@acme.test', 'org-1'),
                       ('u-editor', 'editor@acme.test', 'org-1'),
                       ('u-orphan', 'orphan@nowhere.test', NULL);

            -- already bound to an organization
            INSERT INTO user_sessions
                (user_id, session_id, organization_id, created_by_user_id,
                 visibility, payload, created_at, updated_at)
            VALUES ('u-owner', 'bound', 'org-1', 'u-owner', 'team', '{}',
                    '2026-01-01 00:00:00', '2026-01-01 00:00:00');

            -- saved through POST /sessions without organization_id: must backfill
            INSERT INTO user_sessions
                (user_id, session_id, organization_id, created_by_user_id,
                 visibility, payload, created_at, updated_at)
            VALUES ('u-owner', 'detached', NULL, 'u-owner', 'private', '{}',
                    '2026-01-02 00:00:00', '2026-01-02 00:00:00');

            -- attributed user has no organization: must stay NULL, not be guessed
            INSERT INTO user_sessions
                (user_id, session_id, organization_id, created_by_user_id,
                 visibility, payload, created_at, updated_at)
            VALUES ('u-orphan', 'orphaned', NULL, 'u-orphan', 'private', '{}',
                    '2026-01-03 00:00:00', '2026-01-03 00:00:00');

            -- the memory sentinel, one per member, wrongly carrying an org
            INSERT INTO user_sessions
                (user_id, session_id, organization_id, created_by_user_id,
                 visibility, payload, created_at, updated_at)
            VALUES ('u-owner', '__user_memory__', 'org-1', 'u-owner', 'private', '{}',
                    '2026-01-04 00:00:00', '2026-01-04 00:00:00'),
                   ('u-editor', '__user_memory__', 'org-1', 'u-editor', 'private', '{}',
                    '2026-01-04 00:00:00', '2026-01-04 00:00:00');
        """)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def pre_phase_1_db(tmp_path):
    db_path = tmp_path / "pre_phase_1.sqlite"
    _seed_pre_phase_1_schema(str(db_path))

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute("INSERT INTO alembic_version (version_num) VALUES (?)",
                     (PREVIOUS_HEAD,))
        conn.commit()
    finally:
        conn.close()
    return str(db_path)


def test_upgrade_applies_to_a_realistic_pre_phase_1_database(pre_phase_1_db):
    _upgrade(pre_phase_1_db)

    columns = _columns(pre_phase_1_db, "user_sessions")
    assert NEW_COLUMNS.issubset(columns), f"missing {NEW_COLUMNS - columns}"
    assert "ix_user_sessions_org_session" in _indexes(pre_phase_1_db, "user_sessions")


def test_upgrade_backfills_organization_ownership(pre_phase_1_db):
    _upgrade(pre_phase_1_db)

    conn = sqlite3.connect(pre_phase_1_db)
    try:
        rows = dict(conn.execute("""
            SELECT session_id || ':' || user_id, COALESCE(organization_id, '')
            FROM user_sessions
        """).fetchall())
    finally:
        conn.close()

    assert rows["bound:u-owner"] == "org-1"
    # backfilled from the attributed user's active organization
    assert rows["detached:u-owner"] == "org-1"
    # quarantined, not guessed
    assert rows["orphaned:u-orphan"] == ""


def test_upgrade_strips_the_organization_from_the_memory_sentinel(pre_phase_1_db):
    """`__user_memory__` must never become organization-owned.

    Two members' sentinels share a session_id, so an org binding would both
    leak one member's memory to another and make any future
    UNIQUE(organization_id, session_id) unsatisfiable.
    """
    _upgrade(pre_phase_1_db)

    conn = sqlite3.connect(pre_phase_1_db)
    try:
        orgs = [r[0] for r in conn.execute(
            "SELECT organization_id FROM user_sessions WHERE session_id = '__user_memory__'"
        )]
    finally:
        conn.close()

    assert orgs == [None, None]


def test_existing_rows_receive_revision_one(pre_phase_1_db):
    _upgrade(pre_phase_1_db)

    conn = sqlite3.connect(pre_phase_1_db)
    try:
        revisions = {r[0] for r in conn.execute("SELECT revision FROM user_sessions")}
    finally:
        conn.close()

    assert revisions == {1}


# --- L. historical duplicates are detected, never discarded ------------------

def test_upgrade_detects_historical_forks_without_deleting_them(pre_phase_1_db, caplog):
    conn = sqlite3.connect(pre_phase_1_db)
    try:
        # A fork created under the old (user_id, session_id) ownership model.
        conn.execute("""
            INSERT INTO user_sessions
                (user_id, session_id, organization_id, created_by_user_id,
                 visibility, payload, created_at, updated_at)
            VALUES ('u-editor', 'bound', 'org-1', 'u-owner', 'team', '{}',
                    '2026-02-01 00:00:00', '2026-02-01 00:00:00')
        """)
        conn.commit()
    finally:
        conn.close()

    with caplog.at_level("WARNING"):
        _upgrade(pre_phase_1_db)

    assert "forked" in caplog.text.lower()

    conn = sqlite3.connect(pre_phase_1_db)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM user_sessions WHERE session_id = 'bound'"
        ).fetchone()[0]
    finally:
        conn.close()

    assert count == 2, "the migration discarded a forked row instead of reporting it"


def test_downgrade_removes_the_new_columns(pre_phase_1_db):
    _upgrade(pre_phase_1_db)
    _downgrade(pre_phase_1_db)

    columns = _columns(pre_phase_1_db, "user_sessions")
    assert not (NEW_COLUMNS & columns), f"left behind {NEW_COLUMNS & columns}"
