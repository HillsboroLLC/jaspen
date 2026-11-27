"""I2 (D18 row 17): D5 allocation basis on case versions, and Phase 9 effect reconciliation (F4).

Adds one column, ``financial_case_events.allocation_basis``. The Phase 5.3 recorder
classifies each accepted case version from its recorded evidence, never from caller input:

* ``none``: nothing is attributed (cumulative zero);
* ``full``: every eligible source line is attributed at its full net principal;
* ``single_line``: the source has one line, with no tax or fee;
* ``derived``: anything else. That is a partial multi-line split the processor did not
  allocate, so founder decision D5 sends it to manual review.

Existing rows default to ``derived``, so evidence recorded before this column existed
is never treated as authoritative.

Database guards:
* PostgreSQL: a deferred check recomputes the basis from the version's lines at commit,
  so a stored basis cannot be forged.
* PostgreSQL and SQLite: Phase 9 refuses to evaluate credits for a ``derived`` version.
* PostgreSQL: a deferred check reconciles every lot evaluation's hold, release,
  reversal and recovery amounts with the sum of its credit effects (Phase 9 audit F4).
  The service checks the same on SQLite.

The downgrade refuses while any case version exists.

Revision ID: e7b9d1f3a5c6
Revises: a1f3c5e7b9d0
"""

from alembic import op
import sqlalchemy as sa


revision = "e7b9d1f3a5c6"
down_revision = "a1f3c5e7b9d0"
branch_labels = None
depends_on = None

TABLE = "financial_case_events"
COLUMN = "allocation_basis"
BASES = ("none", "full", "single_line", "derived")
AUTHORITATIVE = ("none", "full", "single_line")
CHECK_NAME = "ck_financial_case_events_allocation_basis"
BASIS_MESSAGE = "case allocation basis does not match its recorded evidence"
DERIVED_MESSAGE = "D5: a derived case allocation needs manual review before credit effects"
RECONCILE_MESSAGE = "case lot evaluation amounts do not reconcile with its credit effects"
INVALID_MESSAGE = "case allocation basis is invalid"


class CaseEvidenceNotEmptyError(RuntimeError):
    """Downgrade refuses to discard the allocation basis of recorded case versions."""


def _quoted(values):
    return ",".join(f"'{value}'" for value in values)


PG_FUNCTIONS = (
    ("i2_case_allocation_basis_final", f"""
CREATE FUNCTION i2_case_allocation_basis_final() RETURNS trigger AS $$
DECLARE
  v_source varchar(36);
  source_tax bigint;
  source_fee bigint;
  line_count integer;
  allocation_count integer;
  eligible_count integer;
  eligible_matched integer;
  expected varchar(16);
BEGIN
  SELECT c.source_financial_transaction_id INTO v_source FROM financial_cases c WHERE c.id=NEW.financial_case_id;
  SELECT t.tax_minor, t.fee_minor INTO source_tax, source_fee FROM financial_transactions t WHERE t.id=v_source;
  SELECT count(*) INTO line_count FROM financial_lines l WHERE l.financial_transaction_id=v_source;
  SELECT count(*) INTO allocation_count FROM financial_case_event_lines a WHERE a.financial_case_event_id=NEW.id;
  SELECT count(*) INTO eligible_count FROM financial_lines l
    WHERE l.financial_transaction_id=v_source AND l.line_kind NOT IN ('tax','fee','discount')
      AND l.principal_minor + l.discount_minor > 0;
  SELECT count(*) INTO eligible_matched FROM financial_lines l
    JOIN financial_case_event_lines a ON a.financial_line_id=l.id AND a.financial_case_event_id=NEW.id
    WHERE l.financial_transaction_id=v_source AND l.line_kind NOT IN ('tax','fee','discount')
      AND l.principal_minor + l.discount_minor > 0
      AND a.attributed_principal_minor = l.principal_minor + l.discount_minor;
  IF allocation_count = 0 AND NEW.cumulative_principal_minor = 0 THEN
    expected := 'none';
  ELSIF eligible_count > 0 AND allocation_count = eligible_count AND eligible_matched = eligible_count THEN
    expected := 'full';
  ELSIF line_count = 1 AND allocation_count = 1 AND source_tax = 0 AND source_fee = 0 THEN
    expected := 'single_line';
  ELSE
    expected := 'derived';
  END IF;
  IF NEW.{COLUMN} <> expected THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='{BASIS_MESSAGE}';
  END IF;
  RETURN NULL;
END; $$ LANGUAGE plpgsql"""),
    ("i2_case_evaluation_basis_guard", f"""
CREATE FUNCTION i2_case_evaluation_basis_guard() RETURNS trigger AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM {TABLE} e WHERE e.id=NEW.financial_case_event_id
             AND e.{COLUMN} NOT IN ({_quoted(AUTHORITATIVE)})) THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='{DERIVED_MESSAGE}';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql"""),
    ("i2_case_evaluation_reconcile_final", f"""
CREATE FUNCTION i2_case_evaluation_reconcile_final() RETURNS trigger AS $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM financial_case_lot_evaluations v
    WHERE v.id=NEW.id AND (
      v.hold_amount <> COALESCE((SELECT sum(f.amount) FROM financial_case_credit_effects f
                                 WHERE f.evaluation_id=v.id AND f.effect_type='hold'), 0)
      OR v.release_amount <> COALESCE((SELECT sum(f.amount) FROM financial_case_credit_effects f
                                       WHERE f.evaluation_id=v.id AND f.effect_type='release'), 0)
      OR v.reversal_amount <> COALESCE((SELECT sum(f.amount) FROM financial_case_credit_effects f
                                        WHERE f.evaluation_id=v.id AND f.effect_type='reversal'), 0)
      OR v.recovery_amount <> COALESCE((SELECT sum(f.amount) FROM financial_case_credit_effects f
                                        WHERE f.evaluation_id=v.id AND f.effect_type='recovery'), 0))
  ) THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='{RECONCILE_MESSAGE}';
  END IF;
  RETURN NULL;
END; $$ LANGUAGE plpgsql"""),
)

PG_TRIGGERS = (
    ("trg_i2_case_allocation_basis_final", TABLE,
     "CREATE CONSTRAINT TRIGGER {name} AFTER INSERT ON {table} DEFERRABLE INITIALLY DEFERRED "
     "FOR EACH ROW EXECUTE FUNCTION i2_case_allocation_basis_final()"),
    ("trg_i2_case_evaluation_basis_guard", "financial_case_lot_evaluations",
     "CREATE TRIGGER {name} BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION i2_case_evaluation_basis_guard()"),
    ("trg_i2_case_evaluation_reconcile_final", "financial_case_lot_evaluations",
     "CREATE CONSTRAINT TRIGGER {name} AFTER INSERT ON {table} DEFERRABLE INITIALLY DEFERRED "
     "FOR EACH ROW EXECUTE FUNCTION i2_case_evaluation_reconcile_final()"),
)

SQLITE_TRIGGERS = {
    "trg_i2_case_allocation_basis_insert": (
        f"CREATE TRIGGER trg_i2_case_allocation_basis_insert BEFORE INSERT ON {TABLE} "
        f"WHEN NEW.{COLUMN} NOT IN ({_quoted(BASES)}) BEGIN SELECT RAISE(ABORT,'{INVALID_MESSAGE}'); END"
    ),
    "trg_i2_case_evaluation_basis_insert": (
        "CREATE TRIGGER trg_i2_case_evaluation_basis_insert BEFORE INSERT ON financial_case_lot_evaluations "
        f"WHEN EXISTS (SELECT 1 FROM {TABLE} e WHERE e.id=NEW.financial_case_event_id "
        f"AND e.{COLUMN} NOT IN ({_quoted(AUTHORITATIVE)})) "
        f"BEGIN SELECT RAISE(ABORT,'{DERIVED_MESSAGE}'); END"
    ),
}


def add_allocation_basis_column():
    """The column and its value check (also used by Phase 5.3 tests that build that revision alone)."""
    op.add_column(TABLE, sa.Column(COLUMN, sa.String(16), nullable=False, server_default="derived"))
    if op.get_bind().dialect.name == "postgresql":
        op.create_check_constraint(CHECK_NAME, TABLE, f"{COLUMN} IN ({_quoted(BASES)})")
    else:
        op.execute(SQLITE_TRIGGERS["trg_i2_case_allocation_basis_insert"])


def upgrade():
    bind = op.get_bind()
    add_allocation_basis_column()
    if bind.dialect.name == "postgresql":
        for _name, body in PG_FUNCTIONS:
            op.execute(body)
        for name, table, body in PG_TRIGGERS:
            op.execute(body.format(name=name, table=table))
    else:
        op.execute(SQLITE_TRIGGERS["trg_i2_case_evaluation_basis_insert"])


def downgrade():
    bind = op.get_bind()
    pg = bind.dialect.name == "postgresql"
    if pg:
        op.execute(sa.text(f"LOCK TABLE {TABLE} IN ACCESS EXCLUSIVE MODE"))
    if bind.execute(sa.text(f"SELECT 1 FROM {TABLE} LIMIT 1")).first() is not None:
        raise CaseEvidenceNotEmptyError("I2 downgrade refuses to discard recorded case allocation bases")
    if pg:
        for name, table, _body in PG_TRIGGERS:
            op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
        for name, _body in PG_FUNCTIONS:
            op.execute(f"DROP FUNCTION IF EXISTS {name}()")
        op.drop_constraint(CHECK_NAME, TABLE, type_="check")
    else:
        for name in SQLITE_TRIGGERS:
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_column(TABLE, COLUMN)
