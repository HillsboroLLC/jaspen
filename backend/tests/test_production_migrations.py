import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import migrate_production as migration


def credentials(tmp_path):
    paths = []
    for name, user in (("app", "app_user"), ("migration", "owner")):
        path = tmp_path / name
        path.write_text(f"postgresql://{user}:secret@db:25060/production?sslmode=require")
        path.chmod(0o600)
        paths.append(path)
    return {"JASPEN_DATABASE_URL_FILE": str(paths[0]), "JASPEN_MIGRATION_DATABASE_URL_FILE": str(paths[1])}


def test_migration_credential_only_changes_child_environment(tmp_path):
    original = credentials(tmp_path)
    original["DATABASE_URL"] = "stale"
    env, role = migration.migration_environment(original)
    assert original["DATABASE_URL"] == "stale"
    assert role == "app_user"
    assert env["JASPEN_DATABASE_URL_FILE"] == original["JASPEN_MIGRATION_DATABASE_URL_FILE"]
    assert env["DATABASE_URL"] == env["SQLALCHEMY_DATABASE_URI"]
    assert "owner:" in env["DATABASE_URL"]


@pytest.mark.parametrize("failure", ["missing", "insecure", "wrong_database", "same_role"])
def test_unsafe_migration_configuration_stops_before_connecting(tmp_path, failure):
    env = credentials(tmp_path)
    path = Path(env["JASPEN_MIGRATION_DATABASE_URL_FILE"])
    if failure == "missing":
        path.unlink()
    elif failure == "insecure":
        path.chmod(0o644)
    elif failure == "wrong_database":
        path.write_text(path.read_text().replace("/production", "/other"))
    else:
        path.write_text(path.read_text().replace("owner:", "app_user:"))
    with pytest.raises(RuntimeError):
        migration.migration_environment(env)


def test_grant_failure_prevents_migration(tmp_path, monkeypatch):
    monkeypatch.setattr(migration.os, "environ", credentials(tmp_path))
    engine = MagicMock()
    engine.begin.return_value.__enter__.return_value.execute.side_effect = RuntimeError("permission denied")
    monkeypatch.setattr(migration, "create_engine", lambda *a, **kw: engine)
    run = MagicMock()
    monkeypatch.setattr(migration.subprocess, "run", run)
    with pytest.raises(RuntimeError):
        migration.main()
    run.assert_not_called()
    engine.dispose.assert_called_once()
