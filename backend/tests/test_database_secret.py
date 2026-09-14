import os

import pytest

from database_secret import load_database_url_secret


def test_missing_database_secret_is_a_noop(tmp_path):
    environ = {"DATABASE_URL": "sqlite:///existing.db"}
    assert load_database_url_secret(environ=environ, path=tmp_path / "missing") is False
    assert environ["DATABASE_URL"] == "sqlite:///existing.db"


def test_mode_600_database_secret_overrides_both_connection_variables(tmp_path):
    secret = tmp_path / "database_url"
    secret.write_text("postgresql+psycopg://app:secret@example.test:5432/jaspen\n")
    os.chmod(secret, 0o600)
    environ = {"DATABASE_URL": "sqlite:///old.db"}

    assert load_database_url_secret(environ=environ, path=secret) is True
    assert environ["DATABASE_URL"] == "postgresql+psycopg://app:secret@example.test:5432/jaspen"
    assert environ["SQLALCHEMY_DATABASE_URI"] == environ["DATABASE_URL"]


def test_database_secret_rejects_group_or_world_permissions(tmp_path):
    secret = tmp_path / "database_url"
    secret.write_text("postgresql+psycopg://app:secret@example.test:5432/jaspen\n")
    os.chmod(secret, 0o640)

    with pytest.raises(RuntimeError, match="must be mode 600"):
        load_database_url_secret(environ={}, path=secret)


def test_database_secret_rejects_non_postgres_values(tmp_path):
    secret = tmp_path / "database_url"
    secret.write_text("not-a-database-url\n")
    os.chmod(secret, 0o600)

    with pytest.raises(RuntimeError, match="malformed"):
        load_database_url_secret(environ={}, path=secret)
