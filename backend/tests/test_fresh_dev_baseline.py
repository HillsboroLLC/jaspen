"""A fresh local baseline must never adopt or modify an existing database."""
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
import pytest

from scripts.init_dev_db import reserve_fresh_database


BACKEND = Path(__file__).resolve().parents[1]


def test_existing_database_is_refused_without_changes(tmp_path):
    path = tmp_path / "valuable.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE preserved (value TEXT)")
        connection.execute("INSERT INTO preserved VALUES ('keep')")
    before = hashlib.sha256(path.read_bytes()).digest()
    engine = create_engine(f"sqlite:///{path}")
    try:
        with pytest.raises(SystemExit, match="refuses an existing"):
            reserve_fresh_database(engine)
    finally:
        engine.dispose()
    assert hashlib.sha256(path.read_bytes()).digest() == before


def test_memory_database_cannot_be_stamped_as_a_file_baseline():
    engine = create_engine("sqlite:///:memory:")
    try:
        with pytest.raises(SystemExit, match="new local SQLite file"):
            reserve_fresh_database(engine)
    finally:
        engine.dispose()


def test_fresh_initializer_records_head_and_seeds_current_schema(tmp_path):
    path = tmp_path / "fresh.db"
    env = dict(os.environ)
    env.update(DATABASE_URL=f"sqlite:///{path}", APP_ENV="test",
               SECRET_KEY="test-only", JWT_SECRET_KEY="test-only",
               STRIPE_SECRET_KEY="sk_test_placeholder", RATELIMIT_STORAGE_URI="memory://",
               ANTHROPIC_API_KEY="", CLAUDE_API_KEY="", GEMINI_API_KEY="", OPENAI_API_KEY="")
    result = subprocess.run([sys.executable, "scripts/init_dev_db.py", "--fresh-baseline"],
                            cwd=BACKEND, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == ScriptDirectory(str(BACKEND / "migrations")).get_current_head()
        for table in ("account_sharing_controls", "shared_artifacts", "shared_artifact_reports"):
            assert connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    before = hashlib.sha256(path.read_bytes()).digest()
    again = subprocess.run([sys.executable, "scripts/init_dev_db.py", "--fresh-baseline"],
                           cwd=BACKEND, env=env, capture_output=True, text=True)
    assert again.returncode != 0
    assert hashlib.sha256(path.read_bytes()).digest() == before
