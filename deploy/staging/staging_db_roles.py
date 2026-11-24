#!/usr/bin/env python3
"""Staging database role policy for the billing migration evidence run (BI-2).

Three roles, each with one job:

* the owner (the managed database's admin user) runs Alembic migrations and
  this script; it is never used by the application or the evidence commands;
* the runtime role (``RUNTIME_DB_ROLE`` in deploy.conf) keeps every privilege
  it has today except any write or trigger privilege, table or column level,
  on the migration evidence tables (every ``billing_migration_*`` table),
  which no runtime code writes;
* the billing migrator role (``MIGRATOR_DB_ROLE``) runs the Phase 14-16
  evidence commands (``scripts/billing_migration_evidence.py``). It reads
  every table and may INSERT the evidence tables. Its only other writes are
  the four target tables those commands maintain, and staging-only guard
  triggers limit each one to exactly what Phase 14 writes:
  * ``credit_ledger_entries``: ``migration_opening`` entries only;
  * ``credit_lots``: lots named by a migration opening of the same account;
  * ``idempotency_registry``: ``billing.migration.*`` claims only;
  * ``billing_accounts``: new ``proposed`` accounts without a processor
    customer, and binding the processor customer of an account that has
    none (the ledger's no-op ``SET id = id`` locks pass).
  On the tables the commands only lock (FOR SHARE / FOR UPDATE need an
  UPDATE privilege on some column), it holds UPDATE on ``id`` alone, and a
  trigger rejects any change it attempts.

The guards fire when either ``current_user`` or ``session_user`` is the
migrator, and ``verify`` refuses any role membership between the two roles
or into the migrator (so neither can SET ROLE into the other).

The owner's default privileges grant the runtime role write access on every
new table, so a migration that adds a migration table re-opens it. ``apply``
is idempotent and covers every ``billing_migration_*`` table present; it is
re-run after each deploy that ran migrations. ``verify`` (read-only) is part
of the deploy preflight when the policy is enforced.

Commands (PostgreSQL only; the URL comes from a mode-600 file, never argv):

  plan      print the SQL ``apply`` would run (no connection)
  verify    read-only: exit 0 only if the live state matches the policy
  snapshot  read-only: print both roles' exact ACL entries (JSON), the input
            for ``rollback``
  apply     run the policy SQL in one transaction (needs --confirm)
  rollback  restore a snapshot's ACL entries exactly and remove the policy's
            triggers and functions it did not have (needs --confirm)

The migrator login itself is created by DigitalOcean (``doctl databases user
create``) so its password is never typed or stored here; this script only
grants, revokes and installs the staging-only guard triggers.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

# Written only by the billing migration commands (Phase 14, BI-1). Every table named billing_migration_* is
# treated the same, so a future evidence table is covered; these must exist. A test asserts they equal
# app.billing_rehearsal.PHASE14_TABLES.
MIGRATION_TABLES = (
    "billing_migration_runs", "billing_migration_establishments", "billing_migration_payer_bindings",
    "billing_migration_payment_attributions", "billing_migration_account_results", "billing_migration_reviews",
    "billing_migration_openings", "billing_migration_payment_archives", "billing_migration_plan_mappings",
    "billing_migration_operation_decisions",
)
MIGRATION_TABLE_PREFIX = "billing_migration_"

# The target tables the migrator writes besides INSERT on the evidence tables, each with the minimum the
# Phase 14-16 commands need (derived from a run as this role; see the tests). Each is also guarded below.
MIGRATOR_WRITE_PRIVILEGES = {
    "idempotency_registry": ("INSERT", "UPDATE"),
    # Establishment binds the payer's processor customer to the account it created (D16 step 1); the Phase 3
    # ledger triggers serialize on the account with ``UPDATE billing_accounts SET id = id``.
    "billing_accounts": ("INSERT", "UPDATE (id, processor, processor_customer_id, updated_at)"),
    "credit_lots": ("INSERT",),
    "credit_ledger_entries": ("INSERT",),
}

# Tables the commands only lock to hold a consistent snapshot: UPDATE on ``id`` only, and any change refused.
MIGRATOR_LOCK_ONLY = (
    "ai_operations", "billing_staff_permission_grants", "credit_lots", "organizations", "payments",
    "persistent_credit_grants", "users",
)
LOCK_ONLY_FUNCTION = "bi2_billing_migrator_lock_only"
LOCK_ONLY_TRIGGER = "trg_bi2_billing_migrator_lock_only"
WRITE_GUARD_FUNCTION = "bi2_billing_migrator_write_guard"
WRITE_GUARD_TRIGGER = "trg_bi2_billing_migrator_write_guard"
WRITE_GUARDED = ("billing_accounts", "credit_ledger_entries", "credit_lots", "idempotency_registry")

LOCK_ONLY_BODY = (" BEGIN RAISE EXCEPTION USING ERRCODE='42501', MESSAGE='the billing migrator may lock ' "
                  "|| TG_TABLE_NAME || ' rows but never change them'; END ")
WRITE_GUARD_BODY = """
BEGIN
  IF TG_TABLE_NAME = 'credit_ledger_entries' THEN
    IF NEW.entry_type IS DISTINCT FROM 'migration_opening' THEN
      RAISE EXCEPTION USING ERRCODE='42501', MESSAGE='the billing migrator writes only migration_opening entries';
    END IF;
  ELSIF TG_TABLE_NAME = 'credit_lots' THEN
    IF NOT EXISTS (SELECT 1 FROM billing_migration_openings m
                   WHERE m.lot_id = NEW.id AND m.billing_account_id = NEW.billing_account_id) THEN
      RAISE EXCEPTION USING ERRCODE='42501', MESSAGE='the billing migrator writes only lots named by a migration opening';
    END IF;
  ELSIF TG_TABLE_NAME = 'idempotency_registry' THEN
    IF NEW.namespace NOT LIKE 'billing.migration.%'
       OR (TG_OP = 'UPDATE' AND OLD.namespace NOT LIKE 'billing.migration.%') THEN
      RAISE EXCEPTION USING ERRCODE='42501', MESSAGE='the billing migrator writes only billing.migration claims';
    END IF;
  ELSIF TG_TABLE_NAME = 'billing_accounts' THEN
    IF TG_OP = 'INSERT' THEN
      IF NEW.status IS DISTINCT FROM 'proposed' OR NEW.processor_customer_id IS NOT NULL THEN
        RAISE EXCEPTION USING ERRCODE='42501',
          MESSAGE='the billing migrator creates only proposed accounts without a processor customer';
      END IF;
    ELSIF to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD) THEN
      IF OLD.processor_customer_id IS NOT NULL OR OLD.processor IS NOT NULL
         OR (to_jsonb(NEW) - 'processor' - 'processor_customer_id' - 'updated_at')
            IS DISTINCT FROM (to_jsonb(OLD) - 'processor' - 'processor_customer_id' - 'updated_at') THEN
        RAISE EXCEPTION USING ERRCODE='42501',
          MESSAGE='the billing migrator only binds a processor customer to an account that has none';
      END IF;
    END IF;
  END IF;
  RETURN NEW;
END
"""

TABLE_PRIVILEGE_LETTERS = {"r": "SELECT", "a": "INSERT", "w": "UPDATE", "d": "DELETE", "D": "TRUNCATE",
                           "x": "REFERENCES", "t": "TRIGGER", "m": "MAINTAIN"}
SEQUENCE_PRIVILEGE_LETTERS = {"r": "SELECT", "w": "UPDATE", "U": "USAGE"}
RUNTIME_FORBIDDEN = ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "TRIGGER")


def _role(name):
    if not isinstance(name, str) or not ROLE_NAME.match(name):
        raise SystemExit(f"invalid role name: {name!r}")
    return name


def _split(grant):
    """``"UPDATE (a, b)"`` -> ("UPDATE", ("a", "b")); ``"INSERT"`` -> ("INSERT", None)."""
    if "(" not in grant:
        return grant, None
    name, columns = grant.split("(", 1)
    return name.strip(), tuple(c.strip() for c in columns.rstrip(")").split(","))


def migrator_column_updates(table):
    """The exact columns the migrator may UPDATE on ``table`` (None: table-level UPDATE)."""
    columns = set()
    for grant in MIGRATOR_WRITE_PRIVILEGES.get(table, ()):
        name, cols = _split(grant)
        if name == "UPDATE":
            if cols is None:
                return None
            columns |= set(cols)
    if table in MIGRATOR_LOCK_ONLY:
        columns.add("id")
    return columns


def migrator_table_privileges(table, *, migration_table):
    """The table-level privileges the migrator holds on ``table``."""
    held = {"SELECT"}
    if migration_table:
        held.add("INSERT")
    for grant in MIGRATOR_WRITE_PRIVILEGES.get(table, ()):
        name, cols = _split(grant)
        if cols is None:
            held.add(name)
    return held


def _when(migrator):
    return f"WHEN (current_user = '{migrator}' OR session_user = '{migrator}')"


def policy_sql(*, runtime_role, migrator_role):
    """The idempotent SQL that brings both roles to the policy (one transaction)."""
    runtime, migrator = _role(runtime_role), _role(migrator_role)
    if runtime == migrator:
        raise SystemExit("the runtime and migrator roles must differ")
    listed = ", ".join(f"'{t}'" for t in MIGRATION_TABLES)
    statements = [
        f"GRANT USAGE ON SCHEMA public TO {migrator}",
        f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {migrator}",
        f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {migrator}",
        f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {migrator}",
        # Every evidence table, listed or named billing_migration_*: no runtime write or trigger privilege at
        # table or column level; INSERT for the migrator.
        "DO $$ DECLARE t text; c text; BEGIN "
        "FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
        f"AND (left(tablename, {len(MIGRATION_TABLE_PREFIX)}) = '{MIGRATION_TABLE_PREFIX}' OR tablename IN ({listed})) "
        "LOOP "
        f"EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE, TRIGGER ON public.%I FROM %I', t, '{runtime}'); "
        "FOR c IN SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' "
        "AND table_name = t LOOP "
        f"EXECUTE format('REVOKE INSERT (%I), UPDATE (%I) ON public.%I FROM %I', c, c, t, '{runtime}'); "
        "END LOOP; "
        f"EXECUTE format('GRANT INSERT ON public.%I TO %I', t, '{migrator}'); "
        "END LOOP; END $$",
    ]
    for table, grants in sorted(MIGRATOR_WRITE_PRIVILEGES.items()):
        statements.append(f"GRANT {', '.join(grants)} ON {table} TO {migrator}")
    statements.append(f"CREATE OR REPLACE FUNCTION {LOCK_ONLY_FUNCTION}() RETURNS trigger LANGUAGE plpgsql "
                      f"AS $${LOCK_ONLY_BODY}$$")
    statements.append(f"CREATE OR REPLACE FUNCTION {WRITE_GUARD_FUNCTION}() RETURNS trigger LANGUAGE plpgsql "
                      f"AS $${WRITE_GUARD_BODY}$$")
    for table in MIGRATOR_LOCK_ONLY:
        statements.append(f"GRANT UPDATE (id) ON {table} TO {migrator}")
        statements.append(f"DROP TRIGGER IF EXISTS {LOCK_ONLY_TRIGGER} ON {table}")
        statements.append(f"CREATE TRIGGER {LOCK_ONLY_TRIGGER} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW "
                          f"{_when(migrator)} EXECUTE FUNCTION {LOCK_ONLY_FUNCTION}()")
    for table in WRITE_GUARDED:
        statements.append(f"DROP TRIGGER IF EXISTS {WRITE_GUARD_TRIGGER} ON {table}")
        statements.append(f"CREATE TRIGGER {WRITE_GUARD_TRIGGER} BEFORE INSERT OR UPDATE ON {table} FOR EACH ROW "
                          f"{_when(migrator)} EXECUTE FUNCTION {WRITE_GUARD_FUNCTION}()")
    return statements


# ---------------------------------------------------------------------------
# Live checks (read-only)
# ---------------------------------------------------------------------------

def _q(connection, sql, **params):
    from sqlalchemy import text
    return connection.execute(text(sql), params)


def _tables(connection):
    return sorted(_q(connection, "SELECT tablename FROM pg_tables WHERE schemaname='public'").scalars())


def _evidence_tables(connection):
    return sorted(t for t in _tables(connection) if t.startswith(MIGRATION_TABLE_PREFIX) or t in MIGRATION_TABLES)


def _supported_table_privileges(connection):
    version = int(_q(connection, "SHOW server_version_num").scalar())
    return [p for p in TABLE_PRIVILEGE_LETTERS.values() if p != "MAINTAIN" or version >= 170000]


def _table_privileges(connection, role, table, privileges=("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")):
    return {p for p in privileges if _q(connection, "SELECT has_table_privilege(:r, :t, :p)",
                                         r=role, t=f"public.{table}", p=p).scalar()}


def _column_privileges(connection, role, table, privilege):
    return set(_q(connection, "SELECT a.attname FROM pg_attribute a WHERE a.attrelid = CAST(:t AS regclass) "
                              "AND a.attnum > 0 AND NOT a.attisdropped "
                              "AND has_column_privilege(:r, a.attrelid, a.attnum, :p)",
                  r=role, t=f"public.{table}", p=privilege).scalars())


def _trigger_ok(connection, table, name, function, events, migrator):
    row = _q(connection, "SELECT t.tgenabled, pg_get_triggerdef(t.oid) FROM pg_trigger t "
                         "WHERE t.tgrelid = CAST(:t AS regclass) AND t.tgname = :n",
             t=f"public.{table}", n=name).first()
    # PostgreSQL renders "BEFORE DELETE OR UPDATE ... WHEN ((CURRENT_USER = 'r'::name) OR (SESSION_USER = ...".
    return bool(row and row[0] == "O" and events in row[1]
                and f"(CURRENT_USER = '{migrator}'::name)" in row[1]
                and f"(SESSION_USER = '{migrator}'::name)" in row[1]
                and f"EXECUTE FUNCTION {function}()" in row[1])


def _function_ok(connection, name, body):
    src = _q(connection, "SELECT prosrc FROM pg_proc WHERE proname = :n AND pronamespace = 'public'::regnamespace",
             n=name).scalars().all()
    return len(src) == 1 and src[0].strip() == body.strip()


def verify(connection, *, runtime_role, migrator_role):
    """Read-only. Returns (ok, findings): every difference from the policy is a finding."""
    findings = []
    present = set(_tables(connection))
    roles = dict(_q(connection, "SELECT rolname, rolsuper OR rolbypassrls FROM pg_roles "
                                "WHERE rolname IN (:a, :b)", a=runtime_role, b=migrator_role).all())
    for role in (runtime_role, migrator_role):
        if role not in roles:
            findings.append({"role": role, "problem": "role does not exist"})
        elif roles[role]:
            findings.append({"role": role, "problem": "superuser or bypasses row security"})
    if findings:
        return False, findings
    # No path from one role into the other (SET ROLE or inheritance), and nothing granted into the migrator.
    memberships = _q(connection, "SELECT r.rolname, m.rolname FROM pg_auth_members am "
                                 "JOIN pg_roles r ON r.oid = am.roleid JOIN pg_roles m ON m.oid = am.member "
                                 "WHERE m.rolname IN (:a, :b) OR r.rolname IN (:a, :b)",
                     a=runtime_role, b=migrator_role).all()
    for granted, member in memberships:
        if {granted, member} == {runtime_role, migrator_role} or member == migrator_role:
            findings.append({"role": member, "problem": "role membership", "member_of": granted})
    for table in MIGRATION_TABLES:
        if table not in present:
            findings.append({"table": table, "problem": "migration table missing"})
    evidence = _evidence_tables(connection)
    for table in evidence:
        held = _table_privileges(connection, runtime_role, table, RUNTIME_FORBIDDEN)
        for privilege in ("INSERT", "UPDATE"):
            if _column_privileges(connection, runtime_role, table, privilege):
                held.add(f"{privilege} (columns)")
        if held:
            findings.append({"role": runtime_role, "table": table, "problem": "runtime can write",
                             "privileges": sorted(held)})
    supported = _supported_table_privileges(connection)
    for table in sorted(present):
        held = _table_privileges(connection, migrator_role, table, supported)
        expected = migrator_table_privileges(table, migration_table=table in evidence)
        if held != expected:
            findings.append({"role": migrator_role, "table": table, "problem": "table privileges differ",
                             "held": sorted(held), "expected": sorted(expected)})
        columns = migrator_column_updates(table)
        if columns is not None:
            got = _column_privileges(connection, migrator_role, table, "UPDATE")
            if got != columns:
                findings.append({"role": migrator_role, "table": table, "problem": "UPDATE columns differ",
                                 "held": sorted(got), "expected": sorted(columns)})
        for privilege in ("INSERT", "REFERENCES"):
            if privilege not in held and _column_privileges(connection, migrator_role, table, privilege):
                findings.append({"role": migrator_role, "table": table, "problem": f"{privilege} column grant"})
        if table in MIGRATOR_LOCK_ONLY and not _trigger_ok(connection, table, LOCK_ONLY_TRIGGER, LOCK_ONLY_FUNCTION,
                                                           "BEFORE DELETE OR UPDATE", migrator_role):
            findings.append({"table": table, "problem": "lock-only trigger missing or not enforced"})
        if table in WRITE_GUARDED and not _trigger_ok(connection, table, WRITE_GUARD_TRIGGER, WRITE_GUARD_FUNCTION,
                                                      "BEFORE INSERT OR UPDATE", migrator_role):
            findings.append({"table": table, "problem": "write guard trigger missing or not enforced"})
    sequences = _q(connection, "SELECT c.relname FROM pg_class c WHERE c.relkind = 'S' "
                               "AND c.relnamespace = 'public'::regnamespace AND (has_sequence_privilege(:r, c.oid, "
                               "'USAGE') OR has_sequence_privilege(:r, c.oid, 'UPDATE'))",
                   r=migrator_role).scalars().all()
    for sequence in sequences:
        findings.append({"role": migrator_role, "sequence": sequence, "problem": "migrator holds a sequence privilege"})
    for name, body in ((LOCK_ONLY_FUNCTION, LOCK_ONLY_BODY), (WRITE_GUARD_FUNCTION, WRITE_GUARD_BODY)):
        if not _function_ok(connection, name, body):
            findings.append({"function": name, "problem": "guard function missing or changed"})
    return not findings, findings


def _merge(left, right):
    """Union of two ACL privilege strings, keeping each privilege's grant option if either has it."""
    letters = {}
    for text_ in (left, right):
        for i, letter in enumerate(text_):
            if letter != "*":
                letters[letter] = letters.get(letter, False) or text_[i + 1:i + 2] == "*"
    return "".join(f"{k}{'*' if v else ''}" for k, v in sorted(letters.items()))


def _grantee(item):
    return item.split("=", 1)[0].strip('"')


def _acl_entries(connection, role):
    """The role's exact ACL entries: relation -> {kind, privilege letters}, "relation.column" -> letters."""
    relations, columns = {}, {}
    for name, kind, acl in _q(connection, "SELECT c.relname, c.relkind, c.relacl::text[] FROM pg_class c "
                                          "WHERE c.relnamespace = 'public'::regnamespace "
                                          "AND c.relkind IN ('r', 'p', 'S') AND c.relacl IS NOT NULL").all():
        for item in acl:
            if _grantee(item) == role:
                # Grants from several grantors are merged (rollback re-grants them as the owner).
                previous = relations.get(name, {"privileges": ""})["privileges"]
                relations[name] = {"kind": kind,
                                   "privileges": _merge(previous, item.split("=", 1)[1].split("/", 1)[0])}
    for relation, column, acl in _q(connection, "SELECT c.relname, a.attname, a.attacl::text[] FROM pg_attribute a "
                                                "JOIN pg_class c ON c.oid = a.attrelid "
                                                "WHERE c.relnamespace = 'public'::regnamespace "
                                                "AND a.attacl IS NOT NULL AND a.attnum > 0").all():
        for item in acl:
            if _grantee(item) == role:
                key = f"{relation}.{column}"
                columns[key] = _merge(columns.get(key, ""), item.split("=", 1)[1].split("/", 1)[0])
    return {"relations": relations, "columns": columns}


def _policy_objects(connection):
    triggers = sorted(f"{r}:{n}" for r, n in _q(connection, "SELECT c.relname, t.tgname FROM pg_trigger t "
                                                            "JOIN pg_class c ON c.oid = t.tgrelid "
                                                            "WHERE t.tgname IN (:a, :b)",
                                                 a=LOCK_ONLY_TRIGGER, b=WRITE_GUARD_TRIGGER).all())
    functions = sorted(_q(connection, "SELECT proname FROM pg_proc WHERE proname IN (:a, :b)",
                          a=LOCK_ONLY_FUNCTION, b=WRITE_GUARD_FUNCTION).scalars())
    return triggers, functions


def snapshot(connection, *, runtime_role, migrator_role):
    """Read-only, exact record of both roles' ACL entries and of the policy's triggers, for rollback."""
    triggers, functions = _policy_objects(connection)
    relations = dict(_q(connection, "SELECT relname, relkind FROM pg_class WHERE relnamespace = 'public'::regnamespace "
                                    "AND relkind IN ('r', 'p', 'S') ORDER BY relname").all())
    return {"roles": {runtime_role: _acl_entries(connection, runtime_role),
                      migrator_role: _acl_entries(connection, migrator_role)},
            "relations_present": relations, "triggers": triggers, "functions": functions}


def _grants(letters, mapping):
    """Privilege letters ("arw*") -> (without grant option, with grant option)."""
    plain, starred = [], []
    for i, letter in enumerate(letters):
        if letter in mapping:
            (starred if letters[i + 1:i + 2] == "*" else plain).append(mapping[letter])
    return plain, starred


def rollback_sql(recorded, *, runtime_role, migrator_role):
    """SQL that restores ``recorded`` exactly: both roles' ACL entries, and only the triggers it had."""
    runtime, migrator = _role(runtime_role), _role(migrator_role)
    statements = []
    for table in MIGRATOR_LOCK_ONLY:
        if f"{table}:{LOCK_ONLY_TRIGGER}" not in recorded.get("triggers", ()):
            statements.append(f"DROP TRIGGER IF EXISTS {LOCK_ONLY_TRIGGER} ON {table}")
    for table in WRITE_GUARDED:
        if f"{table}:{WRITE_GUARD_TRIGGER}" not in recorded.get("triggers", ()):
            statements.append(f"DROP TRIGGER IF EXISTS {WRITE_GUARD_TRIGGER} ON {table}")
    for function in (LOCK_ONLY_FUNCTION, WRITE_GUARD_FUNCTION):
        if function not in recorded.get("functions", ()):
            statements.append(f"DROP FUNCTION IF EXISTS {function}()")
    present = recorded["relations_present"]
    for name in present:
        _identifier(name)
    for role in (runtime, migrator):
        entries = recorded["roles"][role]
        if role == migrator:
            # The migrator held nothing beyond the snapshot: clear it everywhere.
            statements.append(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}")
            statements.append(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {role}")
        else:
            # The runtime only on relations the snapshot saw: a table created after it (by a later migration,
            # granted through the owner's default privileges) keeps its access. Evidence tables created after the
            # snapshot keep the policy's revocation (their earlier state was never recorded).
            for relation, kind in sorted(present.items()):
                keyword = "SEQUENCE " if kind == "S" else ""
                statements.append(f"REVOKE ALL ON {keyword}public.\"{relation}\" FROM {role}")
        # Revoking a table privilege also revokes it on every column, so this clears column grants too.
        for relation, item in sorted(entries["relations"].items()):
            sequence = item["kind"] == "S"
            plain, starred = _grants(item["privileges"], SEQUENCE_PRIVILEGE_LETTERS if sequence
                                     else TABLE_PRIVILEGE_LETTERS)
            target = f"SEQUENCE public.\"{_identifier(relation)}\"" if sequence else f"public.\"{_identifier(relation)}\""
            if plain:
                statements.append(f"GRANT {', '.join(plain)} ON {target} TO {role}")
            if starred:
                statements.append(f"GRANT {', '.join(starred)} ON {target} TO {role} WITH GRANT OPTION")
        for column, letters in sorted(entries["columns"].items()):
            relation, name = column.split(".", 1)
            plain, starred = _grants(letters, TABLE_PRIVILEGE_LETTERS)
            cols = f'"{_identifier(name)}"'
            table = f'public."{_identifier(relation)}"'
            if plain:
                statements.append(f"GRANT {', '.join(f'{p} ({cols})' for p in plain)} ON {table} TO {role}")
            if starred:
                statements.append(f"GRANT {', '.join(f'{p} ({cols})' for p in starred)} ON {table} TO {role} "
                                  "WITH GRANT OPTION")
    return statements


IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _identifier(name):
    if not isinstance(name, str) or not IDENTIFIER.match(name):
        raise SystemExit(f"invalid identifier in snapshot: {name!r}")
    return name


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def _engine(backend_dir, url_file):
    sys.path.insert(0, str(Path(backend_dir).resolve()))
    from database_secret import load_database_url_secret
    from sqlalchemy import create_engine

    environ = {}
    if not load_database_url_secret(environ=environ, path=Path(url_file)):
        raise SystemExit("database URL file unavailable")
    return create_engine(environ["DATABASE_URL"], connect_args={"connect_timeout": 15})


def main(argv=None):
    parser = argparse.ArgumentParser(description="staging database role policy (BI-2)")
    parser.add_argument("command", choices=("plan", "verify", "snapshot", "apply", "rollback"))
    parser.add_argument("--runtime-role", required=True)
    parser.add_argument("--migrator-role", required=True)
    parser.add_argument("--backend-dir")
    parser.add_argument("--url-file", help="mode-600 URL file of the owner role")
    parser.add_argument("--snapshot-file", help="for rollback: a JSON file written by snapshot")
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args(argv)
    runtime, migrator = _role(args.runtime_role), _role(args.migrator_role)
    if args.command == "plan":
        print("\n".join(s + ";" for s in policy_sql(runtime_role=runtime, migrator_role=migrator)))
        return 0
    if not (args.backend_dir and args.url_file):
        raise SystemExit("--backend-dir and --url-file are required")
    engine = _engine(args.backend_dir, args.url_file)
    from sqlalchemy import text
    if args.command in ("verify", "snapshot"):
        with engine.connect() as connection:
            if connection.dialect.name == "postgresql":
                connection.execute(text("SET TRANSACTION READ ONLY"))
            if args.command == "snapshot":
                print(json.dumps(snapshot(connection, runtime_role=runtime, migrator_role=migrator), sort_keys=True))
                return 0
            ok, findings = verify(connection, runtime_role=runtime, migrator_role=migrator)
        for finding in findings:
            print("FAIL role_policy " + json.dumps(finding, sort_keys=True))
        print(("PASS" if ok else "FAIL") + " role_policy runtime cannot write migration tables; migrator least privilege")
        return 0 if ok else 1
    if not args.confirm:
        raise SystemExit(f"{args.command} changes database privileges; pass --confirm")
    if args.command == "apply":
        statements = policy_sql(runtime_role=runtime, migrator_role=migrator)
    else:
        if not args.snapshot_file:
            raise SystemExit("rollback needs --snapshot-file")
        statements = rollback_sql(json.loads(Path(args.snapshot_file).read_text()), runtime_role=runtime,
                                  migrator_role=migrator)
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
    print(f"{args.command}: {len(statements)} statements applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
