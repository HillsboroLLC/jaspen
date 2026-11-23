#!/usr/bin/env python3
"""Read-only staging database checks for the deploy wrapper.

Run as the staging application user with the staging virtualenv's Python.
Connects with the protected migration URL file (never printed) and only reads:
the Alembic revision and the D1 copied-user counts. Output is revision ids, counts
and PASS/FAIL; errors print the exception class name only.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys


REVISION_ID = re.compile(r"^[A-Za-z0-9_]+$")


def script_directory(migrations_dir: str):
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config()
    config.set_main_option("script_location", str(Path(migrations_dir).resolve()))
    return ScriptDirectory.from_config(config)


def _ancestors_or_self(script, revisions) -> set[str]:
    found: set[str] = set()
    for revision in revisions:
        found.update(item.revision for item in script.iterate_revisions(revision, "base"))
    return found


def pending_revisions(script, current_revisions: list[str]) -> list[str]:
    """Every revision in the code that the database has not applied yet.

    Computed as ancestors(code heads) minus ancestors-or-self(database
    revisions), walking each head and each current revision separately, so
    branches and multiple heads are counted fully. Raises when the database is
    at a revision this code does not know (the database is newer than the code).
    """
    for revision in current_revisions:
        script.get_revision(revision)  # raises for an unknown revision
    applied = _ancestors_or_self(script, current_revisions)
    ordered: list[str] = []
    for head in script.get_heads():
        for item in script.iterate_revisions(head, "base"):
            if item.revision not in applied and item.revision not in ordered:
                ordered.append(item.revision)
    return ordered


def heads_missing_from_history(current_script, current_revisions: list[str], target_heads: list[str]) -> list[str]:
    """Target heads that are not the database revision or one of its ancestors."""
    history = _ancestors_or_self(current_script, current_revisions)
    return sorted(head for head in target_heads if head not in history)


def _engine(backend_dir: str, url_file: str):
    sys.path.insert(0, str(Path(backend_dir).resolve()))
    from database_secret import load_database_url_secret
    from sqlalchemy import create_engine

    environ: dict[str, str] = {}
    if not load_database_url_secret(environ=environ, path=Path(url_file)):
        raise RuntimeError("database URL file unavailable")
    return create_engine(environ["DATABASE_URL"], connect_args={"connect_timeout": 15})


def _read_only(connection) -> None:
    from sqlalchemy import text

    if connection.dialect.name == "postgresql":
        connection.execute(text("SET TRANSACTION READ ONLY"))


def database_revisions(engine) -> list[str]:
    from sqlalchemy import inspect, text

    with engine.connect() as connection:
        _read_only(connection)
        if not inspect(connection).has_table("alembic_version"):
            return []
        rows = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    revisions = sorted(str(row) for row in rows)
    if not all(REVISION_ID.match(revision) for revision in revisions):
        raise RuntimeError("unexpected revision format")
    return revisions


# A password hash werkzeug's check_password_hash can accept: "method$salt$hash"
# with a scrypt or pbkdf2 method. Copied accounts must have none.
VALID_PASSWORD_HASH_SQL = "(password_hash LIKE :scrypt OR password_hash LIKE :pbkdf2)"
VALID_PASSWORD_HASH_PATTERNS = {"scrypt": "scrypt:%$%$%", "pbkdf2": "pbkdf2:%$%$%"}


def copied_user_counts(engine, created_before: str) -> dict[str, int]:
    """D1 counts for the users copied from production (created before the cutoff)."""
    from sqlalchemy import text

    params = {"cutoff": created_before, **VALID_PASSWORD_HASH_PATTERNS}
    copied = "FROM users WHERE created_at < :cutoff"
    with engine.connect() as connection:
        _read_only(connection)
        counts = {
            "copied": connection.execute(text(f"SELECT count(*) {copied}"), params).scalar_one(),
            "copied_active": connection.execute(
                text(f"SELECT count(*) {copied} AND deactivated_at IS NULL"), params
            ).scalar_one(),
            "copied_valid_password_hashes": connection.execute(
                text(f"SELECT count(*) {copied} AND {VALID_PASSWORD_HASH_SQL}"), params
            ).scalar_one(),
            "active_total": connection.execute(
                text("SELECT count(*) FROM users WHERE deactivated_at IS NULL")
            ).scalar_one(),
        }
    return {name: int(value) for name, value in counts.items()}


def copied_users_pass(counts: dict[str, int], expected_copied: int) -> bool:
    return (
        counts["copied"] == expected_copied
        and counts["copied_active"] == 0
        and counts["copied_valid_password_hashes"] == 0
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backend-dir", required=True)
    parser.add_argument("--url-file", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("current")
    pending_parser = commands.add_parser("pending")
    pending_parser.add_argument("--migrations", required=True)
    history_parser = commands.add_parser("in-history")
    history_parser.add_argument("--target-migrations", required=True)
    history_parser.add_argument("--current-migrations", required=True)
    counts_parser = commands.add_parser("copied-users")
    counts_parser.add_argument("--created-before", required=True)
    counts_parser.add_argument("--expected-copied", type=int, required=True)
    args = parser.parse_args(argv)

    engine = None
    try:
        engine = _engine(args.backend_dir, args.url_file)
        if args.command == "copied-users":
            counts = copied_user_counts(engine, args.created_before)
            passed = copied_users_pass(counts, args.expected_copied)
            print(
                f"{'PASS' if passed else 'FAIL'} d1_copied_users_deactivated "
                f"(copied {counts['copied']}, expected {args.expected_copied}; "
                f"active among copied {counts['copied_active']}; "
                f"valid password hashes among copied {counts['copied_valid_password_hashes']})"
            )
            print(f"INFO active_users_total {counts['active_total']}")
            return 0 if passed else 1

        current = database_revisions(engine)
        if args.command == "current":
            print(" ".join(current) or "none")
            return 0
        if args.command == "pending":
            for revision in pending_revisions(script_directory(args.migrations), current):
                print(revision)
            return 0

        target_heads = list(script_directory(args.target_migrations).get_heads())
        missing = heads_missing_from_history(script_directory(args.current_migrations), current, target_heads)
        if missing:
            print(f"FAIL target_alembic_heads_in_database_history (missing {' '.join(missing)})")
            return 1
        print(f"PASS target_alembic_heads_in_database_history (target {' '.join(target_heads)}; database {' '.join(current)})")
        return 0
    except Exception as exc:
        print(f"FAIL staging_database_{args.command} ({type(exc).__name__})", file=sys.stderr)
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
