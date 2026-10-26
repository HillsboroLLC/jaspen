"""Run production migrations with a separate owner credential, never the app role."""
import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from database_secret import load_database_url_secret


APP_TARGET_SETTINGS = (
    "JASPEN_APP_DB_ROLE",
    "JASPEN_APP_DB_HOST",
    "JASPEN_APP_DB_PORT",
    "JASPEN_APP_DB_NAME",
)


def _configured_app_target(env, migration_url):
    values = {name: str(env.get(name) or "").strip() for name in APP_TARGET_SETTINGS}
    if not any(values.values()):
        return None
    if not all(values.values()):
        raise RuntimeError("Complete application database target settings are required")

    try:
        app_port = int(values["JASPEN_APP_DB_PORT"])
    except ValueError as exc:
        raise RuntimeError("Application database port must be numeric") from exc
    if not 1 <= app_port <= 65535:
        raise RuntimeError("Application database port is outside the valid range")

    app_target = (
        values["JASPEN_APP_DB_HOST"].casefold(),
        app_port,
        values["JASPEN_APP_DB_NAME"],
    )
    migration_target = (
        str(migration_url.host or "").casefold(),
        migration_url.port,
        migration_url.database,
    )
    if app_target != migration_target:
        raise RuntimeError("App and migration credentials must target the same database")

    app_role = values["JASPEN_APP_DB_ROLE"]
    if not migration_url.username or app_role == migration_url.username:
        raise RuntimeError("Migration login must be separate from the app login")
    return app_role


def migration_environment(environ):
    env = dict(environ)
    app_path = Path(env.get("JASPEN_DATABASE_URL_FILE", "~/.config/jaspen/database_url")).expanduser()
    migration_path = Path(env.get("JASPEN_MIGRATION_DATABASE_URL_FILE", "~/.config/jaspen/migration_database_url")).expanduser()
    migration_env = {}
    if not load_database_url_secret(environ=migration_env, path=migration_path):
        raise RuntimeError("Required migration database credential is unavailable")
    migration_url = make_url(migration_env["DATABASE_URL"])
    app_role = _configured_app_target(env, migration_url)

    if app_role is None:
        app_env = {}
        if not load_database_url_secret(environ=app_env, path=app_path):
            raise RuntimeError("Required application database credential is unavailable")
        app_url = make_url(app_env["DATABASE_URL"])
        if (app_url.host, app_url.port, app_url.database) != (
            migration_url.host,
            migration_url.port,
            migration_url.database,
        ):
            raise RuntimeError("App and migration credentials must target the same database")
        if not app_url.username or app_url.username == migration_url.username:
            raise RuntimeError("Migration login must be separate from the app login")
        app_role = app_url.username

    env.update(migration_env)
    env["JASPEN_DATABASE_URL_FILE"] = str(migration_path)
    env["FLASK_APP"] = "wsgi.py"
    return env, app_role


def grant_future_app_access(connection, app_role):
    # Quote role identifiers, rather than interpolating untrusted SQL.
    role = connection.dialect.identifier_preparer.quote_identifier(app_role)
    connection.execute(text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role}"))
    connection.execute(text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {role}"))


def main():
    env, app_role = migration_environment(os.environ)
    engine = create_engine(env["DATABASE_URL"], connect_args={"connect_timeout": 15})
    try:
        with engine.begin() as connection:
            grant_future_app_access(connection, app_role)
        subprocess.run(
            [sys.executable, "-m", "flask", "db", "upgrade"],
            cwd=Path(__file__).resolve().parent,
            env=env,
            check=True,
        )
    finally:
        engine.dispose()
    print("Production migrations complete; runtime database credential unchanged.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Connection exceptions can contain credentials. Keep deploy output safe.
        print(f"Production migration failed ({type(exc).__name__}); application was not restarted.", file=sys.stderr)
        sys.exit(1)
