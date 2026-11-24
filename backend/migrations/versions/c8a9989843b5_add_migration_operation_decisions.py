"""BI-1 (D-1): recorded decisions for legacy operations that never closed (inactive).

Adds one immutable evidence table, ``billing_migration_operation_decisions``:
one reviewer's decision about one legacy AI operation that never reached a
terminal status and that Phase 14 classifies as ``stale_turn_evidence`` (a
P4.0 chat turn killed before it recorded an outcome) or
``outstanding_reservation`` (an unbound runtime operation whose committed
reservation was never settled or released). ``no_compensation_owed`` lets the
backfill proceed; ``compensation_owed`` records an amount and beneficiary and
keeps the account quarantined. No decision moves money.

Database guards, so the table cannot be written around the command:

* append-only: no update, delete, or truncate;
* an explicit, unrevoked ``billing.migration.review`` grant of the reviewer,
  valid at the actual current time (READ COMMITTED), ``decided_at`` equal to
  the transaction time, and the decision's own idempotency claim;
* the operation exists, is still unclosed and unbound, and its user and
  organization equal the ones recorded;
* the reviewer is neither the operation's user nor an owner or member of any
  organization the operation can block (its own, and every organization whose
  Phase 14 candidates include its user: owner, member of any status, Stripe
  customer or payer of its account), nor the bound payer of any of their
  accounts or of the beneficiary account;
* compensation is owed only to the operation's own organization's account;
* a correction is a new row that supersedes the current decision for the
  same operation and evidence: one original decision per evidence, and each
  decision superseded at most once, so the chain never forks.

No row is created by the migration, and no live route, job, or startup path
reads or writes the table. Downgrade refuses while any decision exists.

Revision ID: c8a9989843b5
Revises: f3a5c7e9b1d2
"""

from alembic import op
import sqlalchemy as sa


revision = "c8a9989843b5"
down_revision = "f3a5c7e9b1d2"
branch_labels = None
depends_on = None

TABLE = "billing_migration_operation_decisions"
NAMESPACE = "billing.migration.operation_decision"
REVIEW_PERMISSION = "'billing.migration.review'"
TERMINAL = "('succeeded','degraded','failed')"

# Literal copies of the model CHECK constraints: a revision never reads live models.
CHECKS = (
    ("operation_class IN ('stale_turn_evidence', 'outstanding_reservation') "
     "AND disposition IN ('no_compensation_owed', 'compensation_owed') "
     "AND rule_version = 'jaspen.billing.migration.operation_decision.v1'",
     "ck_billing_migration_operation_decisions_kind"),
    ("(disposition = 'no_compensation_owed' AND amount IS NULL AND beneficiary_billing_account_id IS NULL) "
     "OR (disposition = 'compensation_owed' AND amount IS NOT NULL AND amount > 0 "
     "AND beneficiary_billing_account_id IS NOT NULL)",
     "ck_billing_migration_operation_decisions_amount"),
    ("length(trim(reason)) > 0 AND length(trim(evidence_reference)) > 0 AND "
     "length(evidence_fingerprint) = 64 AND evidence_fingerprint = lower(evidence_fingerprint) AND "
     "length(request_fingerprint) = 64 AND request_fingerprint = lower(request_fingerprint)",
     "ck_billing_migration_operation_decisions_provenance"),
    ("supersedes_decision_id IS NULL OR supersedes_decision_id <> id",
     "ck_billing_migration_operation_decisions_supersedes"),
)

# The organizations an operation can block, by Phase 14's candidate rules: its own, and every one whose
# candidates include its user (owner or member of any status, Stripe customer of its account, or payer of a
# payment on its account).
AFFECTED_SQL = (
    "({o}.id={org} OR {o}.owner_user_id={subject} OR EXISTS (SELECT 1 FROM organization_members sm "
    "WHERE sm.organization_id={o}.id AND sm.user_id={subject}) "
    "OR EXISTS (SELECT 1 FROM billing_accounts sca JOIN users scu ON scu.id={subject} "
    "WHERE sca.organization_id={o}.id AND sca.processor='stripe' AND sca.processor_customer_id IS NOT NULL "
    "AND sca.processor_customer_id=scu.stripe_customer_id) "
    "OR EXISTS (SELECT 1 FROM billing_accounts spa JOIN payments spp ON spp.billing_account_id=spa.id "
    "WHERE spa.organization_id={o}.id AND spp.user_id={subject}))"
)
# The reviewer owns or belongs to an affected organization, or is the bound payer of one of their accounts or of
# the beneficiary account.
CONFLICTED_SQL = (
    "(EXISTS (SELECT 1 FROM organizations ro WHERE ro.owner_user_id={reviewer} AND "
    + AFFECTED_SQL.format(o="ro", org="{org}", subject="{subject}") + ") "
    "OR EXISTS (SELECT 1 FROM organization_members rm JOIN organizations rmo ON rmo.id=rm.organization_id "
    "WHERE rm.user_id={reviewer} AND " + AFFECTED_SQL.format(o="rmo", org="{org}", subject="{subject}") + ") "
    "OR EXISTS (SELECT 1 FROM billing_migration_payer_bindings pb JOIN billing_accounts pba "
    "ON pba.id=pb.billing_account_id JOIN organizations pbo ON pbo.id=pba.organization_id "
    "WHERE pb.payer_user_id={reviewer} AND (pb.billing_account_id={account} OR "
    + AFFECTED_SQL.format(o="pbo", org="{org}", subject="{subject}") + ")))"
)
SUPERSEDE_OK_SQL = (
    "EXISTS (SELECT 1 FROM billing_migration_operation_decisions p WHERE p.id={new}.supersedes_decision_id "
    "AND p.ai_operation_id={new}.ai_operation_id AND p.evidence_fingerprint={new}.evidence_fingerprint)"
)


class OperationDecisionsNotEmptyError(RuntimeError):
    """Downgrade refuses to discard recorded operation decisions."""


def _ref(name, table, constraint, *, nullable=False):
    return sa.Column(name, sa.String(36), sa.ForeignKey(f"{table}.id", name=constraint, ondelete="RESTRICT"),
                     nullable=nullable)


def _create_table():
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("decision_key", sa.String(255), nullable=False),
        _ref("ai_operation_id", "ai_operations", "fk_billing_migration_operation_decisions_operation"),
        _ref("subject_user_id", "users", "fk_billing_migration_operation_decisions_subject", nullable=True),
        _ref("operation_organization_id", "organizations", "fk_billing_migration_operation_decisions_organization",
             nullable=True),
        sa.Column("operation_class", sa.String(40), nullable=False),
        sa.Column("disposition", sa.String(40), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=True),
        _ref("beneficiary_billing_account_id", "billing_accounts",
             "fk_billing_migration_operation_decisions_beneficiary", nullable=True),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("evidence_fingerprint", sa.String(64), nullable=False),
        sa.Column("evidence_reference", sa.String(255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("rule_version", sa.String(64), nullable=False),
        _ref("reviewer_user_id", "users", "fk_billing_migration_operation_decisions_reviewer"),
        _ref("staff_permission_grant_id", "billing_staff_permission_grants",
             "fk_billing_migration_operation_decisions_grant"),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        _ref("idempotency_registry_id", "idempotency_registry", "fk_billing_migration_operation_decisions_registry"),
        _ref("supersedes_decision_id", TABLE, "fk_billing_migration_operation_decisions_supersedes", nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("decision_key", name="uq_billing_migration_operation_decisions_key"),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_billing_migration_operation_decisions_registry"),
        sa.UniqueConstraint("supersedes_decision_id", name="uq_billing_migration_operation_decisions_supersedes"),
        *(sa.CheckConstraint(sql, name=name) for sql, name in CHECKS),
    )
    op.create_index("ix_billing_migration_operation_decisions_operation", TABLE, ["ai_operation_id", "created_at"])
    op.create_index("uq_billing_migration_operation_decisions_evidence", TABLE,
                    ["ai_operation_id", "evidence_fingerprint"], unique=True,
                    postgresql_where=sa.text("supersedes_decision_id IS NULL"),
                    sqlite_where=sa.text("supersedes_decision_id IS NULL"))


PG_GUARD = f"""
CREATE FUNCTION bi1_operation_decision_guard() RETURNS trigger AS $$
DECLARE v_op ai_operations%ROWTYPE; v_org text;
BEGIN
  IF current_setting('transaction_isolation')<>'read committed' THEN
    RAISE EXCEPTION USING ERRCODE='25001', MESSAGE='operation decisions require READ COMMITTED';
  END IF;
  PERFORM 1 FROM billing_staff_permission_grants WHERE id=NEW.staff_permission_grant_id FOR SHARE;
  IF NOT phase14_review_grant_ok(NEW.staff_permission_grant_id, NEW.reviewer_user_id)
     OR NEW.reviewer_user_id IS NOT DISTINCT FROM NEW.subject_user_id OR NEW.decided_at<>now() THEN
    RAISE EXCEPTION USING ERRCODE='23514',
      MESSAGE='an operation decision requires an explicit, unrevoked review grant of someone other than its subject';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM idempotency_registry g WHERE g.id=NEW.idempotency_registry_id
                 AND g.namespace='{NAMESPACE}' AND g.key=NEW.decision_key) THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='an operation decision requires its own idempotency claim';
  END IF;
  SELECT * INTO v_op FROM ai_operations WHERE id=NEW.ai_operation_id FOR SHARE;
  IF NOT FOUND OR (v_op.status IS NOT NULL AND v_op.status IN {TERMINAL}) OR v_op.billing_account_id IS NOT NULL
     OR v_op.user_id IS DISTINCT FROM NEW.subject_user_id
     OR v_op.organization_id IS DISTINCT FROM NEW.operation_organization_id THEN
    RAISE EXCEPTION USING ERRCODE='23514',
      MESSAGE='an operation decision names an unclosed, unbound operation and copies its user and organization';
  END IF;
  IF {CONFLICTED_SQL.format(reviewer='NEW.reviewer_user_id', org='NEW.operation_organization_id',
                            subject='NEW.subject_user_id', account='NEW.beneficiary_billing_account_id')} THEN
    RAISE EXCEPTION USING ERRCODE='23514',
      MESSAGE='a member, owner, or payer of an organization the operation blocks cannot decide it';
  END IF;
  IF NEW.supersedes_decision_id IS NOT NULL AND NOT {SUPERSEDE_OK_SQL.format(new='NEW')} THEN
    RAISE EXCEPTION USING ERRCODE='23514',
      MESSAGE='a correction supersedes a decision for the same operation and evidence';
  END IF;
  IF NEW.beneficiary_billing_account_id IS NOT NULL THEN
    SELECT organization_id INTO v_org FROM billing_accounts WHERE id=NEW.beneficiary_billing_account_id;
    IF v_org IS NULL OR v_org IS DISTINCT FROM NEW.operation_organization_id THEN
      RAISE EXCEPTION USING ERRCODE='23514',
        MESSAGE='compensation is owed only to the operation''s own organization''s billing account';
    END IF;
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql"""

PG_TRIGGERS = (
    ("trg_bi1_operation_decision_guard", f"BEFORE INSERT ON {TABLE} FOR EACH ROW "
                                         "EXECUTE FUNCTION bi1_operation_decision_guard()"),
    (f"trg_phase14_{TABLE}_immutable", f"BEFORE UPDATE OR DELETE ON {TABLE} FOR EACH ROW "
                                       "EXECUTE FUNCTION phase14_reject_row_change()"),
    (f"trg_phase14_{TABLE}_truncate", f"BEFORE TRUNCATE ON {TABLE} FOR EACH STATEMENT "
                                      "EXECUTE FUNCTION phase14_reject_truncate()"),
)

SQLITE_TRIGGERS = {
    "trg_bi1_operation_decision_insert": (
        f"CREATE TRIGGER trg_bi1_operation_decision_insert BEFORE INSERT ON {TABLE} BEGIN "
        "SELECT RAISE(ABORT,'an operation decision requires an explicit, unrevoked review grant of someone other "
        "than its subject') WHERE NEW.reviewer_user_id IS NEW.subject_user_id OR NOT EXISTS ("
        "SELECT 1 FROM billing_staff_permission_grants g WHERE g.id=NEW.staff_permission_grant_id "
        f"AND g.user_id=NEW.reviewer_user_id AND g.permission={REVIEW_PERMISSION} AND g.permission_version=1 "
        "AND julianday(g.starts_at)<=julianday('now') AND (g.ends_at IS NULL OR julianday(g.ends_at)>julianday('now')) "
        "AND NOT EXISTS (SELECT 1 FROM billing_staff_permission_revocations r WHERE r.grant_id=g.id)); "
        "SELECT RAISE(ABORT,'an operation decision requires its own idempotency claim') WHERE NOT EXISTS ("
        "SELECT 1 FROM idempotency_registry g WHERE g.id=NEW.idempotency_registry_id "
        f"AND g.namespace='{NAMESPACE}' AND g.key=NEW.decision_key); "
        "SELECT RAISE(ABORT,'an operation decision names an unclosed, unbound operation and copies its user and "
        "organization') WHERE NOT EXISTS (SELECT 1 FROM ai_operations o WHERE o.id=NEW.ai_operation_id "
        f"AND (o.status IS NULL OR o.status NOT IN {TERMINAL}) AND o.billing_account_id IS NULL "
        "AND o.user_id IS NEW.subject_user_id AND o.organization_id IS NEW.operation_organization_id); "
        "SELECT RAISE(ABORT,'a member, owner, or payer of an organization the operation blocks cannot decide it') "
        "WHERE " + CONFLICTED_SQL.format(reviewer="NEW.reviewer_user_id", org="NEW.operation_organization_id",
                                         subject="NEW.subject_user_id",
                                         account="NEW.beneficiary_billing_account_id") + "; "
        "SELECT RAISE(ABORT,'a correction supersedes a decision for the same operation and evidence') "
        "WHERE NEW.supersedes_decision_id IS NOT NULL AND NOT " + SUPERSEDE_OK_SQL.format(new="NEW") + "; "
        "SELECT RAISE(ABORT,'compensation is owed only to the operation''s own organization''s billing account') "
        "WHERE NEW.beneficiary_billing_account_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM billing_accounts a "
        "WHERE a.id=NEW.beneficiary_billing_account_id AND a.organization_id IS NEW.operation_organization_id); END"
    ),
    **{
        f"trg_bi1_operation_decision_{action}": (
            f"CREATE TRIGGER trg_bi1_operation_decision_{action} BEFORE {action.upper()} ON {TABLE} "
            "BEGIN SELECT RAISE(ABORT,'Phase 14 migration evidence is immutable'); END"
        )
        for action in ("update", "delete")
    },
}


def upgrade():
    _create_table()
    if op.get_bind().dialect.name == "postgresql":
        op.execute(PG_GUARD)
        for name, body in PG_TRIGGERS:
            op.execute(f"CREATE TRIGGER {name} {body}")
    else:
        for statement in SQLITE_TRIGGERS.values():
            op.execute(statement)


def downgrade():
    bind = op.get_bind()
    pg = bind.dialect.name == "postgresql"
    if pg:
        op.execute(sa.text(f"LOCK TABLE {TABLE} IN ACCESS EXCLUSIVE MODE"))
    if bind.execute(sa.text(f"SELECT 1 FROM {TABLE} LIMIT 1")).first() is not None:
        raise OperationDecisionsNotEmptyError("BI-1 downgrade refuses to discard recorded operation decisions")
    if pg:
        for name, _body in PG_TRIGGERS:
            op.execute(f"DROP TRIGGER IF EXISTS {name} ON {TABLE}")
        op.execute("DROP FUNCTION IF EXISTS bi1_operation_decision_guard()")
    else:
        for name in SQLITE_TRIGGERS:
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_index("uq_billing_migration_operation_decisions_evidence", table_name=TABLE)
    op.drop_index("ix_billing_migration_operation_decisions_operation", table_name=TABLE)
    op.drop_table(TABLE)
