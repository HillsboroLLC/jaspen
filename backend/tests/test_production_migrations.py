from pathlib import Path
import subprocess
import sys
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


def make_unsafe(env, failure):
    path = Path(env["JASPEN_MIGRATION_DATABASE_URL_FILE"])
    if failure == "missing":
        path.unlink()
    elif failure == "insecure":
        path.chmod(0o644)
    elif failure == "wrong_database":
        path.write_text(path.read_text().replace("/production", "/other"))
    else:
        path.write_text(path.read_text().replace("owner:", "app_user:"))


def test_migration_credential_only_changes_child_environment(tmp_path):
    original = credentials(tmp_path)
    original["DATABASE_URL"] = "stale"
    original["SQLALCHEMY_DATABASE_URI"] = "also-stale"
    before = dict(original)
    env, role = migration.migration_environment(original)
    assert original == before
    assert role == "app_user"
    assert env["JASPEN_DATABASE_URL_FILE"] == original["JASPEN_MIGRATION_DATABASE_URL_FILE"]
    assert env["DATABASE_URL"] == env["SQLALCHEMY_DATABASE_URI"]
    assert "owner:" in env["DATABASE_URL"]
    assert env is not original


@pytest.mark.parametrize("failure", ["missing", "insecure", "wrong_database", "same_role"])
def test_unsafe_migration_configuration_stops_before_connecting(tmp_path, failure):
    env = credentials(tmp_path)
    make_unsafe(env, failure)
    with pytest.raises(RuntimeError):
        migration.migration_environment(env)


@pytest.mark.parametrize("failure", ["missing", "insecure", "wrong_database", "same_role"])
def test_unsafe_migration_configuration_stops_main_before_connecting(
    tmp_path,
    monkeypatch,
    failure,
):
    env = credentials(tmp_path)
    make_unsafe(env, failure)
    monkeypatch.setattr(migration.os, "environ", env)
    create_engine = MagicMock()
    monkeypatch.setattr(migration, "create_engine", create_engine)

    with pytest.raises(RuntimeError):
        migration.main()

    create_engine.assert_not_called()


@pytest.mark.parametrize("credential", ["app", "migration"])
def test_missing_credential_stops_main_before_database_connection(tmp_path, monkeypatch, credential):
    env = credentials(tmp_path)
    path_key = (
        "JASPEN_DATABASE_URL_FILE"
        if credential == "app"
        else "JASPEN_MIGRATION_DATABASE_URL_FILE"
    )
    Path(env[path_key]).unlink()
    monkeypatch.setattr(migration.os, "environ", env)
    create_engine = MagicMock()
    monkeypatch.setattr(migration, "create_engine", create_engine)

    with pytest.raises(RuntimeError):
        migration.main()

    create_engine.assert_not_called()


def test_successful_migration_confines_owner_credential_to_child_environment(tmp_path, monkeypatch):
    original = credentials(tmp_path)
    runtime_url = Path(original["JASPEN_DATABASE_URL_FILE"]).read_text().strip()
    owner_url = Path(original["JASPEN_MIGRATION_DATABASE_URL_FILE"]).read_text().strip()
    original["DATABASE_URL"] = runtime_url
    original["SQLALCHEMY_DATABASE_URI"] = runtime_url
    before = dict(original)
    monkeypatch.setattr(migration.os, "environ", original)

    engine = MagicMock()
    monkeypatch.setattr(migration, "create_engine", MagicMock(return_value=engine))
    run = MagicMock()
    monkeypatch.setattr(migration.subprocess, "run", run)

    migration.main()

    assert original == before
    assert migration.create_engine.call_args.args[0] == owner_url
    child_env = run.call_args.kwargs["env"]
    assert child_env["DATABASE_URL"] == owner_url
    assert child_env["SQLALCHEMY_DATABASE_URI"] == owner_url
    assert child_env["JASPEN_DATABASE_URL_FILE"] == original["JASPEN_MIGRATION_DATABASE_URL_FILE"]
    assert original["DATABASE_URL"] == runtime_url
    assert original["SQLALCHEMY_DATABASE_URI"] == runtime_url
    engine.dispose.assert_called_once()


def test_migration_subprocess_failure_restores_runtime_environment_and_disposes_engine(tmp_path, monkeypatch):
    original = credentials(tmp_path)
    runtime_url = Path(original["JASPEN_DATABASE_URL_FILE"]).read_text().strip()
    original["DATABASE_URL"] = runtime_url
    original["SQLALCHEMY_DATABASE_URI"] = runtime_url
    before = dict(original)
    monkeypatch.setattr(migration.os, "environ", original)

    engine = MagicMock()
    monkeypatch.setattr(migration, "create_engine", MagicMock(return_value=engine))
    monkeypatch.setattr(
        migration.subprocess,
        "run",
        MagicMock(side_effect=subprocess.CalledProcessError(1, ["flask", "db", "upgrade"])),
    )

    with pytest.raises(subprocess.CalledProcessError):
        migration.main()

    assert original == before
    engine.dispose.assert_called_once()


def test_command_line_failure_does_not_print_credential_or_secret_path(tmp_path):
    missing_app_path = tmp_path / "runtime-secret-does-not-exist"
    missing_migration_path = tmp_path / "migration-secret-does-not-exist"
    env = {
        "JASPEN_DATABASE_URL_FILE": str(missing_app_path),
        "JASPEN_MIGRATION_DATABASE_URL_FILE": str(missing_migration_path),
        "PYTHONDONTWRITEBYTECODE": "1",
    }

    result = subprocess.run(
        [sys.executable, str(Path(migration.__file__).resolve())],
        cwd=Path(migration.__file__).resolve().parent,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.strip() == "Production migration failed (RuntimeError); application was not restarted."
    assert str(missing_app_path) not in result.stderr
    assert str(missing_migration_path) not in result.stderr


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
