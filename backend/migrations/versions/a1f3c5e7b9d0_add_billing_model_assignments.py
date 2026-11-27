"""I1 (D18 row 17, identity family): which billing model owns an organization (inactive).

Adds one immutable table, ``billing_model_assignments``: one row per
organization that the modernized billing model owns. An organization without a
row stays on legacy billing. The row is written only by
``app.billing_cutover.establish_modern_billing_identity``, with the
organization's billing account and ``billing_owner`` role, under its own
idempotency claim.

Database guards, so the table cannot be written around the command:

* append-only: no update, delete, or truncate;
* the command's own idempotency claim (namespace and key);
* the billing account belongs to the organization and is active;
* the actor is the organization's owner;
* ``assigned_at`` equals the transaction time (PostgreSQL);
* the organization has no Phase 14 migration establishment: a legacy
  organization reaches the modern model only through D18 rows 14-16.

And the reverse, on ``billing_migration_establishments``: Phase 14 cannot
establish (or record as unchanged) an organization the modern model owns. It
can still record the quarantine.

No row is created by the migration. Downgrade refuses while any assignment
exists.

Revision ID: a1f3c5e7b9d0
Revises: c8a9989843b5
"""

from alembic import op
import sqlalchemy as sa


revision = "a1f3c5e7b9d0"
down_revision = "c8a9989843b5"
branch_labels = None
depends_on = None

TABLE = "billing_model_assignments"
NAMESPACE = "billing.identity.model_assignment"

# Literal copies of the model CHECK constraints: a revision never reads live models.
CHECKS = (
    ("model = 'modern' AND rule_version = 'jaspen.billing.model_assignment.v1'",
     "ck_billing_model_assignments_model"),
    ("length(trim(origin_type)) > 0 AND length(trim(origin_id)) > 0 AND "
     "length(request_fingerprint) = 64 AND request_fingerprint = lower(request_fingerprint)",
     "ck_billing_model_assignments_provenance"),
)


class ModelAssignmentsNotEmptyError(RuntimeError):
    """Downgrade refuses to discard recorded billing model assignments."""


def _ref(name, table, constraint):
    return sa.Column(name, sa.String(36), sa.ForeignKey(f"{table}.id", name=constraint, ondelete="RESTRICT"),
                     nullable=False)


def _create_table():
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        _ref("organization_id", "organizations", "fk_billing_model_assignments_organization"),
        _ref("billing_account_id", "billing_accounts", "fk_billing_model_assignments_account"),
        sa.Column("model", sa.String(16), nullable=False),
        sa.Column("rule_version", sa.String(64), nullable=False),
        _ref("assigned_by_user_id", "users", "fk_billing_model_assignments_actor"),
        sa.Column("origin_type", sa.String(40), nullable=False),
        sa.Column("origin_id", sa.String(255), nullable=False),
        sa.Column("footprint_json", sa.JSON(), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        _ref("idempotency_registry_id", "idempotency_registry", "fk_billing_model_assignments_registry"),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", name="uq_billing_model_assignments_organization"),
        sa.UniqueConstraint("billing_account_id", name="uq_billing_model_assignments_account"),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_billing_model_assignments_registry"),
        *(sa.CheckConstraint(sql, name=name) for sql, name in CHECKS),
    )


GUARD_MESSAGES = {
    "claim": "a billing model assignment requires its own idempotency claim",
    "account": "a billing model assignment names an active billing account of the same organization",
    "owner": "only the organization owner can assign its billing model",
    "establishment": "a legacy organization reaches the modern billing model only through the D18 migration",
    "time": "a billing model assignment is recorded at the transaction time",
}
CLAIM_SQL = (f"EXISTS (SELECT 1 FROM idempotency_registry g WHERE g.id={{new}}.idempotency_registry_id "
             f"AND g.namespace='{NAMESPACE}' AND g.key='organization:' || {{new}}.organization_id)")
ACCOUNT_SQL = ("EXISTS (SELECT 1 FROM billing_accounts a WHERE a.id={new}.billing_account_id "
               "AND a.organization_id={new}.organization_id AND a.status='active')")
OWNER_SQL = ("EXISTS (SELECT 1 FROM organizations o WHERE o.id={new}.organization_id "
             "AND o.owner_user_id={new}.assigned_by_user_id)")
NO_ESTABLISHMENT_SQL = ("NOT EXISTS (SELECT 1 FROM billing_migration_establishments e "
                        "WHERE e.organization_id={new}.organization_id)")
MODERN_SQL = f"EXISTS (SELECT 1 FROM {TABLE} m WHERE m.organization_id={{new}}.organization_id)"
ESTABLISHMENT_MESSAGE = "Phase 14 cannot establish an organization the modern billing model owns"
IMMUTABLE_MESSAGE = "billing model assignments are immutable"

PG_FUNCTIONS = (
    ("billing_model_assignment_guard", f"""
CREATE FUNCTION billing_model_assignment_guard() RETURNS trigger AS $$
BEGIN
  PERFORM 1 FROM organizations WHERE id=NEW.organization_id FOR SHARE;
  IF NOT {CLAIM_SQL.format(new='NEW')} THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='{GUARD_MESSAGES["claim"]}';
  END IF;
  IF NOT {ACCOUNT_SQL.format(new='NEW')} THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='{GUARD_MESSAGES["account"]}';
  END IF;
  IF NOT {OWNER_SQL.format(new='NEW')} THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='{GUARD_MESSAGES["owner"]}';
  END IF;
  IF NOT {NO_ESTABLISHMENT_SQL.format(new='NEW')} THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='{GUARD_MESSAGES["establishment"]}';
  END IF;
  IF NEW.assigned_at<>now() THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='{GUARD_MESSAGES["time"]}';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql"""),
    ("billing_model_establishment_guard", f"""
CREATE FUNCTION billing_model_establishment_guard() RETURNS trigger AS $$
BEGIN
  IF NEW.outcome<>'quarantined' AND {MODERN_SQL.format(new='NEW')} THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='{ESTABLISHMENT_MESSAGE}';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql"""),
    ("billing_model_assignment_reject_change", f"""
CREATE FUNCTION billing_model_assignment_reject_change() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='{IMMUTABLE_MESSAGE}'; END;
$$ LANGUAGE plpgsql"""),
)

PG_TRIGGERS = (
    ("trg_billing_model_assignment_guard", TABLE,
     "BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION billing_model_assignment_guard()"),
    ("trg_billing_model_assignment_immutable", TABLE,
     "BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION billing_model_assignment_reject_change()"),
    ("trg_billing_model_assignment_truncate", TABLE,
     "BEFORE TRUNCATE ON {table} FOR EACH STATEMENT EXECUTE FUNCTION billing_model_assignment_reject_change()"),
    ("trg_billing_model_establishment_guard", "billing_migration_establishments",
     "BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION billing_model_establishment_guard()"),
)


def _sqlite_raise(message, condition):
    return f"SELECT RAISE(ABORT,'{message}') WHERE {condition}; "


SQLITE_TRIGGERS = {
    "trg_billing_model_assignment_insert": (
        f"CREATE TRIGGER trg_billing_model_assignment_insert BEFORE INSERT ON {TABLE} BEGIN "
        + _sqlite_raise(GUARD_MESSAGES["claim"], "NOT " + CLAIM_SQL.format(new="NEW"))
        + _sqlite_raise(GUARD_MESSAGES["account"], "NOT " + ACCOUNT_SQL.format(new="NEW"))
        + _sqlite_raise(GUARD_MESSAGES["owner"], "NOT " + OWNER_SQL.format(new="NEW"))
        + _sqlite_raise(GUARD_MESSAGES["establishment"], "NOT " + NO_ESTABLISHMENT_SQL.format(new="NEW"))
        + "END"
    ),
    **{
        f"trg_billing_model_assignment_{action}": (
            f"CREATE TRIGGER trg_billing_model_assignment_{action} BEFORE {action.upper()} ON {TABLE} "
            f"BEGIN SELECT RAISE(ABORT,'{IMMUTABLE_MESSAGE}'); END"
        )
        for action in ("update", "delete")
    },
    "trg_billing_model_establishment_insert": (
        "CREATE TRIGGER trg_billing_model_establishment_insert BEFORE INSERT ON billing_migration_establishments "
        "BEGIN " + _sqlite_raise(ESTABLISHMENT_MESSAGE, "NEW.outcome<>'quarantined' AND " + MODERN_SQL.format(new="NEW"))
        + "END"
    ),
}


def upgrade():
    _create_table()
    if op.get_bind().dialect.name == "postgresql":
        for _name, body in PG_FUNCTIONS:
            op.execute(body)
        for name, table, body in PG_TRIGGERS:
            op.execute(f"CREATE TRIGGER {name} {body.format(table=table)}")
    else:
        for statement in SQLITE_TRIGGERS.values():
            op.execute(statement)


def downgrade():
    bind = op.get_bind()
    pg = bind.dialect.name == "postgresql"
    if pg:
        op.execute(sa.text(f"LOCK TABLE {TABLE} IN ACCESS EXCLUSIVE MODE"))
    if bind.execute(sa.text(f"SELECT 1 FROM {TABLE} LIMIT 1")).first() is not None:
        raise ModelAssignmentsNotEmptyError("I1 downgrade refuses to discard recorded billing model assignments")
    if pg:
        for name, table, _body in PG_TRIGGERS:
            op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
        for name, _body in PG_FUNCTIONS:
            op.execute(f"DROP FUNCTION IF EXISTS {name}()")
    else:
        for name in SQLITE_TRIGGERS:
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_table(TABLE)
