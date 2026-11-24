#!/usr/bin/env python3
"""Read-only staging database checks for the deploy wrapper.

Run as the staging application user with the staging virtualenv's Python.
Connects with the protected migration URL file (never printed) and only reads:
the Alembic revision, the D1 copied-user counts and the per-table row counts
(``census``). Output is revision ids, counts and PASS/FAIL; errors print the
exception class name only. ``census-compare`` needs no database and runs as
root on the two census files the wrapper keeps in its root-only log directory.
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


def table_counts(engine) -> dict:
    """Row count of every table in the public schema, plus the Alembic revision (read-only)."""
    from sqlalchemy import text

    with engine.connect() as connection:
        _read_only(connection)
        tables = connection.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        )).scalars().all()
        counts = {}
        for table in tables:
            if not REVISION_ID.match(table):
                raise RuntimeError("unexpected table name")
            counts[table] = int(connection.execute(text(f'SELECT count(*) FROM public."{table}"')).scalar_one())
        identity = {
            "database": connection.execute(text("SELECT current_database()")).scalar_one(),
            "system_identifier": str(connection.execute(text(
                "SELECT system_identifier FROM pg_control_system()")).scalar_one()),
            "in_recovery": bool(connection.execute(text("SELECT pg_is_in_recovery()")).scalar_one()),
        }
    return {"tables": counts, "alembic": database_revisions(engine), "identity": identity}


def compare_census(before: dict, after: dict, *, migrations_ran: bool) -> dict:
    """Classify every difference between two censuses.

    Expected migration effects: tables created while migrations ran, still
    empty. Everything else is unexpected and reported by name: a table created
    without a migration or created with rows, a table that disappeared, and any
    pre-existing table whose row count changed (counts only; never row data).
    """
    old, new = before["tables"], after["tables"]
    created = sorted(set(new) - set(old))
    dropped = sorted(set(old) - set(new))
    changed = {t: {"before": old[t], "after": new[t]} for t in sorted(set(old) & set(new)) if old[t] != new[t]}
    expected, unexpected = [], []
    for table in created:
        if migrations_ran and new[table] == 0:
            expected.append({"table": table, "effect": "created_empty_by_migration"})
        else:
            unexpected.append({"table": table, "effect": "created_with_rows" if new[table] else
                               "created_without_migration", "rows": new[table]})
    unexpected += [{"table": t, "effect": "dropped", "rows_before": old[t]} for t in dropped]
    unexpected += [{"table": t, "effect": "row_count_changed", **c} for t, c in changed.items()]
    return {"unchanged_tables": len(set(old) & set(new)) - len(changed), "expected": expected,
            "unexpected": unexpected, "alembic_before": before.get("alembic"), "alembic_after": after.get("alembic"),
            "identity_before": before.get("identity"), "identity_after": after.get("identity")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backend-dir")
    parser.add_argument("--url-file")
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
    commands.add_parser("census")
    compare_parser = commands.add_parser("census-compare")
    compare_parser.add_argument("--before", required=True)
    compare_parser.add_argument("--after", required=True)
    compare_parser.add_argument("--migrations-ran", choices=("true", "false"), required=True)
    args = parser.parse_args(argv)

    if args.command == "census-compare":
        import json

        result = compare_census(json.loads(Path(args.before).read_text(encoding="utf-8")),
                                json.loads(Path(args.after).read_text(encoding="utf-8")),
                                migrations_ran=args.migrations_ran == "true")
        for item in result["expected"]:
            print(f"INFO census expected {item['effect']} {item['table']}")
        for item in result["unexpected"]:
            detail = " ".join(f"{k}={v}" for k, v in item.items() if k not in ("table", "effect"))
            print(f"WARN census unexpected {item['effect']} {item['table']} {detail}".rstrip())
        print(f"INFO census alembic {' '.join(result['alembic_before'] or [])} -> "
              f"{' '.join(result['alembic_after'] or [])}")
        if (result["identity_before"] or {}).get("system_identifier") != (result["identity_after"] or {}).get(
                "system_identifier"):
            print("INFO census system_identifier differs between the two databases")
        status = "PASS" if not result["unexpected"] else "WARN"
        print(f"{status} census_compare unchanged={result['unchanged_tables']} expected={len(result['expected'])} "
              f"unexpected={len(result['unexpected'])}")
        return 0 if not result["unexpected"] else 3
    if not (args.backend_dir and args.url_file):
        parser.error("--backend-dir and --url-file are required for database commands")

    engine = None
    try:
        engine = _engine(args.backend_dir, args.url_file)
        if args.command == "census":
            import json

            print(json.dumps(table_counts(engine), sort_keys=True))
            return 0
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
