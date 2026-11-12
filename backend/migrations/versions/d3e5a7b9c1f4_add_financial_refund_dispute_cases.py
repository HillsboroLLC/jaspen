"""Add inactive refund and dispute case evidence (Phase 5.3).

Revision ID: d3e5a7b9c1f4
Revises: c3e5a7b9d1f4

Cases retain cumulative processor state and immutable versions. They neither
write to the credit ledger nor change entitlements.
"""

from alembic import op
import sqlalchemy as sa


revision = "d3e5a7b9c1f4"
down_revision = "c3e5a7b9d1f4"
branch_labels = None
depends_on = None

CASE_TABLE = "financial_cases"
EVENT_TABLE = "financial_case_events"
LINE_TABLE = "financial_case_event_lines"
LEDGER_LINK_TABLE = "financial_case_event_ledger_entries"
PHASE_5_3_TABLES = (LEDGER_LINK_TABLE, LINE_TABLE, EVENT_TABLE, CASE_TABLE)


class FinancialCasesNotEmptyError(RuntimeError):
    """Raised when downgrade would discard case or attribution evidence."""


def _quoted(values):
    return ", ".join(f"'{value}'" for value in values)


def _create_tables(dialect):
    created_xid_default = (
        sa.text("pg_current_xact_id()::text")
        if dialect == "postgresql" else sa.text("'0'")
    )
    op.create_table(
        CASE_TABLE,
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("billing_account_id", sa.String(36), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("case_type", sa.String(16), nullable=False),
        sa.Column("case_object_id", sa.String(255), nullable=False),
        sa.Column("source_financial_transaction_id", sa.String(36), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("disposition", sa.String(40), nullable=True),
        sa.Column("cumulative_principal_minor", sa.BigInteger(), nullable=False),
        sa.Column("current_external_version", sa.String(255), nullable=False),
        sa.Column("current_event_id", sa.String(36), nullable=False),
        sa.Column("current_effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "case_type IN ('refund', 'dispute')", name="ck_financial_cases_type",
        ),
        sa.CheckConstraint(
            "length(trim(provider)) > 0 AND length(trim(case_object_id)) > 0 "
            "AND length(trim(current_external_version)) > 0",
            name="ck_financial_cases_identity",
        ),
        sa.CheckConstraint(
            "(case_type = 'refund' AND ("
            "(state = 'refund_recorded' AND disposition IS NULL) OR "
            "(state = 'financial_only' AND disposition = 'financial_only') OR "
            "(state IN ('entitlement_reducing_review', 'scheduled', 'applied') "
            "AND disposition = 'entitlement_reducing_review'))) OR "
            "(case_type = 'dispute' AND state IN ('opened', 'pending', 'won', 'lost') "
            "AND disposition IS NULL)",
            name="ck_financial_cases_state_disposition",
        ),
        sa.CheckConstraint(
            "cumulative_principal_minor >= 0",
            name="ck_financial_cases_cumulative_principal",
        ),
        sa.ForeignKeyConstraint(
            ["billing_account_id"], ["billing_accounts.id"],
            name="fk_financial_cases_billing_account_id", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_financial_transaction_id"], ["financial_transactions.id"],
            name="fk_financial_cases_source_transaction_id", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_financial_cases"),
        sa.UniqueConstraint(
            "provider", "case_type", "case_object_id", "source_financial_transaction_id",
            name="uq_financial_cases_provider_object_source",
        ),
    )
    op.create_index(
        "ix_financial_cases_account_state", CASE_TABLE,
        ["billing_account_id", "state", "updated_at"],
    )
    op.create_index(
        "ix_financial_cases_source_transaction", CASE_TABLE,
        ["source_financial_transaction_id"],
    )

    op.create_table(
        EVENT_TABLE,
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("financial_case_id", sa.String(36), nullable=False),
        sa.Column("financial_transaction_id", sa.String(36), nullable=False),
        sa.Column("inbox_event_id", sa.String(36), nullable=False),
        sa.Column("external_version", sa.String(255), nullable=False),
        sa.Column("event_fingerprint", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("disposition", sa.String(40), nullable=True),
        sa.Column("cumulative_principal_minor", sa.BigInteger(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_xid", sa.String(20), nullable=False, server_default=created_xid_default),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "length(trim(external_version)) > 0 AND length(event_fingerprint) = 64 "
            "AND event_fingerprint = lower(event_fingerprint)",
            name="ck_financial_case_events_identity",
        ),
        sa.CheckConstraint(
            "cumulative_principal_minor >= 0",
            name="ck_financial_case_events_cumulative_principal",
        ),
        sa.ForeignKeyConstraint(
            ["financial_case_id"], ["financial_cases.id"],
            name="fk_financial_case_events_case_id", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["financial_transaction_id"], ["financial_transactions.id"],
            name="fk_financial_case_events_transaction_id", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["inbox_event_id"], ["external_event_inbox.id"],
            name="fk_financial_case_events_inbox_event_id", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_financial_case_events"),
        sa.UniqueConstraint(
            "financial_case_id", "external_version",
            name="uq_financial_case_events_case_version",
        ),
    )
    op.create_index(
        "ix_financial_case_events_transaction", EVENT_TABLE,
        ["financial_transaction_id"],
    )
    op.create_index("ix_financial_case_events_inbox_event", EVENT_TABLE, ["inbox_event_id"])

    op.create_table(
        LINE_TABLE,
        sa.Column("financial_case_event_id", sa.String(36), nullable=False),
        sa.Column("financial_line_id", sa.String(36), nullable=False),
        sa.Column("attributed_principal_minor", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "attributed_principal_minor >= 0",
            name="ck_financial_case_event_lines_principal",
        ),
        sa.ForeignKeyConstraint(
            ["financial_case_event_id"], ["financial_case_events.id"],
            name="fk_financial_case_event_lines_event_id", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["financial_line_id"], ["financial_lines.id"],
            name="fk_financial_case_event_lines_financial_line_id", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "financial_case_event_id", "financial_line_id",
            name="pk_financial_case_event_lines",
        ),
    )
    op.create_index(
        "ix_financial_case_event_lines_financial_line", LINE_TABLE, ["financial_line_id"],
    )

    op.create_table(
        LEDGER_LINK_TABLE,
        sa.Column("financial_case_event_id", sa.String(36), nullable=False),
        sa.Column("credit_ledger_entry_id", sa.String(36), nullable=False),
        sa.Column("effect_type", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "effect_type IN ('hold', 'release', 'reversal', 'recovery')",
            name="ck_financial_case_event_ledger_entries_effect_type",
        ),
        sa.ForeignKeyConstraint(
            ["financial_case_event_id"], ["financial_case_events.id"],
            name="fk_financial_case_event_ledger_entries_event_id", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["credit_ledger_entry_id"], ["credit_ledger_entries.id"],
            name="fk_financial_case_event_ledger_entries_ledger_entry_id", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "financial_case_event_id", "credit_ledger_entry_id", "effect_type",
            name="pk_financial_case_event_ledger_entries",
        ),
    )
    op.create_index(
        "ix_financial_case_event_ledger_entries_ledger_entry",
        LEDGER_LINK_TABLE, ["credit_ledger_entry_id"],
    )


def _postgresql_triggers():
    op.execute(sa.text("""
        CREATE FUNCTION phase53_financial_case_guard() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
              MESSAGE = 'financial case projections cannot be deleted';
          END IF;
          IF TG_OP = 'UPDATE' THEN
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.billing_account_id IS DISTINCT FROM OLD.billing_account_id
               OR NEW.provider IS DISTINCT FROM OLD.provider
               OR NEW.case_type IS DISTINCT FROM OLD.case_type
               OR NEW.case_object_id IS DISTINCT FROM OLD.case_object_id
               OR NEW.source_financial_transaction_id IS DISTINCT FROM OLD.source_financial_transaction_id THEN
              RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'financial case identity is immutable';
            END IF;
            IF NEW.current_event_id IS NOT DISTINCT FROM OLD.current_event_id THEN
              RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'financial case updates require a new immutable event';
            END IF;
            IF (NEW.current_effective_at, NEW.current_received_at)
               <= (OLD.current_effective_at, OLD.current_received_at) THEN
              RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'stale financial case events cannot replace the current projection';
            END IF;
            IF OLD.case_type = 'refund' AND NOT (
              NEW.state = OLD.state
              OR (OLD.state = 'refund_recorded'
                  AND NEW.state IN ('financial_only', 'entitlement_reducing_review'))
              OR (OLD.state = 'entitlement_reducing_review' AND NEW.state = 'scheduled')
              OR (OLD.state = 'scheduled' AND NEW.state = 'applied')
            ) THEN
              RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'invalid refund case state transition';
            END IF;
            IF OLD.case_type = 'dispute' AND NOT (
              NEW.state = OLD.state
              OR (OLD.state = 'opened' AND NEW.state IN ('pending', 'won', 'lost'))
              OR (OLD.state = 'pending' AND NEW.state IN ('won', 'lost'))
              OR (OLD.state IN ('won', 'lost') AND NEW.state IN ('opened', 'pending', 'won', 'lost'))
            ) THEN
              RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'invalid dispute case state transition';
            END IF;
            IF OLD.disposition IS NOT NULL AND NEW.disposition IS DISTINCT FROM OLD.disposition THEN
              RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'financial case disposition is immutable once recorded';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_financial_cases_guard
        BEFORE UPDATE OR DELETE ON financial_cases
        FOR EACH ROW EXECUTE FUNCTION phase53_financial_case_guard()
    """))

    op.execute(sa.text("""
        CREATE FUNCTION phase53_financial_case_event_guard() RETURNS trigger AS $$
        DECLARE
          case_row record;
          event_tx record;
          source_tx record;
          inbox_row record;
        BEGIN
          IF TG_OP <> 'INSERT' THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
              MESSAGE = 'financial case events are immutable evidence';
          END IF;
          SELECT * INTO case_row FROM financial_cases
          WHERE id = NEW.financial_case_id;
          SELECT * INTO event_tx FROM financial_transactions
          WHERE id = NEW.financial_transaction_id;
          SELECT * INTO source_tx FROM financial_transactions
          WHERE id = case_row.source_financial_transaction_id;
          SELECT * INTO inbox_row FROM external_event_inbox
          WHERE id = NEW.inbox_event_id FOR UPDATE;
          IF case_row.id IS NULL OR event_tx.id IS NULL OR source_tx.id IS NULL
             OR inbox_row.id IS NULL
             OR event_tx.kind IS DISTINCT FROM case_row.case_type
             OR event_tx.object_type IS DISTINCT FROM case_row.case_type
             OR event_tx.provider IS DISTINCT FROM case_row.provider
             OR event_tx.object_id IS DISTINCT FROM case_row.case_object_id
             OR event_tx.external_version IS DISTINCT FROM NEW.external_version
             OR event_tx.inbox_event_id IS DISTINCT FROM NEW.inbox_event_id
             OR event_tx.billing_account_id IS DISTINCT FROM case_row.billing_account_id
             OR event_tx.currency IS DISTINCT FROM source_tx.currency
             OR source_tx.billing_account_id IS DISTINCT FROM case_row.billing_account_id
             OR source_tx.provider IS DISTINCT FROM case_row.provider
             OR source_tx.kind NOT IN ('invoice', 'payment')
             OR inbox_row.provider IS DISTINCT FROM case_row.provider
             OR inbox_row.object_type IS DISTINCT FROM case_row.case_type
             OR inbox_row.object_id IS DISTINCT FROM case_row.case_object_id
             OR inbox_row.state NOT IN ('processing', 'processed')
             OR inbox_row.received_at IS DISTINCT FROM NEW.received_at
             OR event_tx.effective_at IS DISTINCT FROM NEW.effective_at
             OR EXISTS (
               SELECT 1 FROM external_event_inbox_conflicts AS conflict
               WHERE conflict.inbox_event_id = NEW.inbox_event_id
             ) THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
              MESSAGE = 'financial case event requires compatible unconflicted source evidence';
          END IF;
          IF NEW.state NOT IN (
            'refund_recorded', 'financial_only', 'entitlement_reducing_review',
            'opened', 'pending', 'won', 'lost'
          ) THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
              MESSAGE = 'financial case state is reserved for its owning phase';
          END IF;
          IF NOT (
            (case_row.case_type = 'refund' AND (
              (NEW.state = 'refund_recorded' AND NEW.disposition IS NULL)
              OR (NEW.state = 'financial_only' AND NEW.disposition = 'financial_only')
              OR (NEW.state = 'entitlement_reducing_review'
                  AND NEW.disposition = 'entitlement_reducing_review')
            ))
            OR (case_row.case_type = 'dispute'
                AND NEW.state IN ('opened', 'pending', 'won', 'lost')
                AND NEW.disposition IS NULL)
          ) THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
              MESSAGE = 'financial case event state and disposition do not agree';
          END IF;
          IF NEW.cumulative_principal_minor > abs(source_tx.principal_minor) THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
              MESSAGE = 'financial case principal exceeds its source transaction';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_financial_case_events_guard
        BEFORE INSERT OR UPDATE OR DELETE ON financial_case_events
        FOR EACH ROW EXECUTE FUNCTION phase53_financial_case_event_guard()
    """))

    op.execute(sa.text("""
        CREATE FUNCTION phase53_financial_case_line_guard() RETURNS trigger AS $$
        DECLARE
          case_event record;
          case_row record;
          source_line record;
        BEGIN
          IF TG_OP <> 'INSERT' THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
              MESSAGE = 'financial case line attribution is immutable';
          END IF;
          SELECT * INTO case_event FROM financial_case_events
          WHERE id = NEW.financial_case_event_id;
          SELECT * INTO case_row FROM financial_cases
          WHERE id = case_event.financial_case_id;
          SELECT * INTO source_line FROM financial_lines
          WHERE id = NEW.financial_line_id;
          IF case_event.id IS NULL OR case_row.id IS NULL OR source_line.id IS NULL
             OR source_line.financial_transaction_id IS DISTINCT FROM case_row.source_financial_transaction_id THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
              MESSAGE = 'financial case attribution must reference a source transaction line';
          END IF;
          IF case_event.created_xid <> pg_current_xact_id()::text THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
              MESSAGE = 'financial case attribution must be committed with its event';
          END IF;
          IF source_line.line_kind IN ('tax', 'fee', 'discount')
             OR NEW.attributed_principal_minor >
                greatest(0, source_line.principal_minor + source_line.discount_minor) THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
              MESSAGE = 'financial case attribution exceeds eligible source principal';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_financial_case_event_lines_guard
        BEFORE INSERT OR UPDATE OR DELETE ON financial_case_event_lines
        FOR EACH ROW EXECUTE FUNCTION phase53_financial_case_line_guard()
    """))

    op.execute(sa.text("""
        CREATE FUNCTION phase53_financial_case_ledger_link_guard() RETURNS trigger AS $$
        BEGIN
          IF TG_OP <> 'INSERT' THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
              MESSAGE = 'financial case ledger references are immutable';
          END IF;
          IF NOT EXISTS (
            SELECT 1
            FROM financial_case_events AS case_event
            JOIN financial_cases AS case_row ON case_row.id = case_event.financial_case_id
            JOIN credit_ledger_entries AS ledger_entry
              ON ledger_entry.id = NEW.credit_ledger_entry_id
            WHERE case_event.id = NEW.financial_case_event_id
              AND ledger_entry.billing_account_id = case_row.billing_account_id
              AND (
                (NEW.effect_type = 'hold' AND case_row.case_type = 'dispute'
                 AND ledger_entry.entry_type = 'dispute_hold')
                OR (NEW.effect_type = 'release' AND case_row.case_type = 'dispute'
                    AND ledger_entry.entry_type = 'release')
                OR (NEW.effect_type = 'reversal' AND (
                  (case_row.case_type = 'refund' AND ledger_entry.entry_type = 'refund_reversal')
                  OR (case_row.case_type = 'dispute' AND ledger_entry.entry_type = 'dispute_reversal')
                ))
                OR (NEW.effect_type = 'recovery' AND ledger_entry.entry_type = 'recovery')
              )
          ) THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
              MESSAGE = 'financial case ledger reference must match its case and effect';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_financial_case_event_ledger_entries_guard
        BEFORE INSERT OR UPDATE OR DELETE ON financial_case_event_ledger_entries
        FOR EACH ROW EXECUTE FUNCTION phase53_financial_case_ledger_link_guard()
    """))

    op.execute(sa.text("""
        CREATE FUNCTION phase53_financial_case_reconcile_id(target_event_id text) RETURNS void AS $$
        DECLARE
          expected record;
          actual record;
        BEGIN
          SELECT case_event.cumulative_principal_minor,
                 case_event.disposition,
                 case_row.case_type,
                 case_row.source_financial_transaction_id
          INTO expected
          FROM financial_case_events AS case_event
          JOIN financial_cases AS case_row ON case_row.id = case_event.financial_case_id
          WHERE case_event.id = target_event_id;
          SELECT count(*) AS line_count,
                 COALESCE(sum(attribution.attributed_principal_minor), 0) AS total_minor
          INTO actual
          FROM financial_case_event_lines AS attribution
          WHERE attribution.financial_case_event_id = target_event_id;
          IF expected.cumulative_principal_minor IS NULL
             OR actual.total_minor IS DISTINCT FROM expected.cumulative_principal_minor
             OR (expected.cumulative_principal_minor > 0 AND actual.line_count = 0) THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
              MESSAGE = 'financial case line attribution must reconcile to cumulative principal';
          END IF;
          IF expected.case_type = 'refund' AND expected.disposition IS NULL
             AND EXISTS (
               SELECT 1 FROM financial_case_event_lines AS attribution
               JOIN financial_lines AS source_line ON source_line.id = attribution.financial_line_id
               WHERE attribution.financial_case_event_id = target_event_id
                 AND source_line.line_kind = 'subscription'
             ) THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
              MESSAGE = 'subscription refund evidence requires an explicit disposition';
          END IF;
        END;
        $$ LANGUAGE plpgsql
    """))
    op.execute(sa.text("""
        CREATE FUNCTION phase53_financial_case_event_reconcile() RETURNS trigger AS $$
        DECLARE
          case_row record;
        BEGIN
          PERFORM phase53_financial_case_reconcile_id(NEW.id);
          SELECT * INTO case_row FROM financial_cases
          WHERE id = NEW.financial_case_id;
          IF case_row.current_event_id IS DISTINCT FROM NEW.id
             OR case_row.state IS DISTINCT FROM NEW.state
             OR case_row.disposition IS DISTINCT FROM NEW.disposition
             OR case_row.cumulative_principal_minor IS DISTINCT FROM NEW.cumulative_principal_minor
             OR case_row.current_external_version IS DISTINCT FROM NEW.external_version
             OR case_row.current_effective_at IS DISTINCT FROM NEW.effective_at
             OR case_row.current_received_at IS DISTINCT FROM NEW.received_at THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
              MESSAGE = 'accepted financial case event must become its current projection';
          END IF;
          RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
    """))
    op.execute(sa.text("""
        CREATE FUNCTION phase53_financial_case_line_reconcile() RETURNS trigger AS $$
        BEGIN
          PERFORM phase53_financial_case_reconcile_id(NEW.financial_case_event_id);
          RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
    """))
    op.execute(sa.text("""
        CREATE CONSTRAINT TRIGGER trg_financial_case_events_reconcile
        AFTER INSERT ON financial_case_events
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION phase53_financial_case_event_reconcile()
    """))
    op.execute(sa.text("""
        CREATE CONSTRAINT TRIGGER trg_financial_case_event_lines_reconcile
        AFTER INSERT ON financial_case_event_lines
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION phase53_financial_case_line_reconcile()
    """))

    op.execute(sa.text("""
        CREATE FUNCTION phase53_financial_case_projection_guard() RETURNS trigger AS $$
        DECLARE
          case_event record;
        BEGIN
          SELECT * INTO case_event FROM financial_case_events
          WHERE id = NEW.current_event_id AND financial_case_id = NEW.id;
          IF case_event.id IS NULL
             OR case_event.state IS DISTINCT FROM NEW.state
             OR case_event.disposition IS DISTINCT FROM NEW.disposition
             OR case_event.cumulative_principal_minor IS DISTINCT FROM NEW.cumulative_principal_minor
             OR case_event.external_version IS DISTINCT FROM NEW.current_external_version
             OR case_event.effective_at IS DISTINCT FROM NEW.current_effective_at
             OR case_event.received_at IS DISTINCT FROM NEW.current_received_at THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
              MESSAGE = 'financial case projection must match its current immutable event';
          END IF;
          RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
    """))
    op.execute(sa.text("""
        CREATE CONSTRAINT TRIGGER trg_financial_cases_projection
        AFTER INSERT OR UPDATE ON financial_cases
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION phase53_financial_case_projection_guard()
    """))

    op.execute(sa.text("""
        CREATE FUNCTION phase53_financial_case_reject_truncate() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'financial case evidence cannot be truncated';
        END;
        $$ LANGUAGE plpgsql
    """))
    for table in PHASE_5_3_TABLES:
        op.execute(sa.text(f"""
            CREATE TRIGGER trg_{table}_no_truncate
            BEFORE TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION phase53_financial_case_reject_truncate()
        """))


def _sqlite_triggers():
    statements = (
        """CREATE TRIGGER trg_financial_cases_update BEFORE UPDATE ON financial_cases BEGIN
          SELECT RAISE(ABORT, 'financial case identity is immutable')
          WHERE NEW.id <> OLD.id
             OR NEW.billing_account_id <> OLD.billing_account_id
             OR NEW.provider <> OLD.provider
             OR NEW.case_type <> OLD.case_type
             OR NEW.case_object_id <> OLD.case_object_id
             OR NEW.source_financial_transaction_id <> OLD.source_financial_transaction_id;
          SELECT RAISE(ABORT, 'financial case updates require a new immutable event')
          WHERE NEW.current_event_id = OLD.current_event_id;
          SELECT RAISE(ABORT, 'invalid refund case state transition')
          WHERE OLD.case_type = 'refund' AND NOT (
            NEW.state = OLD.state
            OR (OLD.state = 'refund_recorded'
                AND NEW.state IN ('financial_only', 'entitlement_reducing_review'))
            OR (OLD.state = 'entitlement_reducing_review' AND NEW.state = 'scheduled')
            OR (OLD.state = 'scheduled' AND NEW.state = 'applied'));
          SELECT RAISE(ABORT, 'invalid dispute case state transition')
          WHERE OLD.case_type = 'dispute' AND NOT (
            NEW.state = OLD.state
            OR (OLD.state = 'opened' AND NEW.state IN ('pending', 'won', 'lost'))
            OR (OLD.state = 'pending' AND NEW.state IN ('won', 'lost'))
            OR (OLD.state IN ('won', 'lost') AND NEW.state IN ('opened', 'pending', 'won', 'lost')));
          SELECT RAISE(ABORT, 'financial case disposition cannot be changed')
          WHERE OLD.disposition IS NOT NULL AND NEW.disposition IS NOT OLD.disposition;
          SELECT RAISE(ABORT, 'stale financial case events cannot replace the current projection')
          WHERE NEW.current_effective_at < OLD.current_effective_at
             OR (NEW.current_effective_at = OLD.current_effective_at
                 AND NEW.current_received_at <= OLD.current_received_at);
          SELECT RAISE(ABORT, 'financial case projection must match its current immutable event')
          WHERE NOT EXISTS (
            SELECT 1 FROM financial_case_events AS event
            WHERE event.id = NEW.current_event_id AND event.financial_case_id = NEW.id
              AND event.state = NEW.state
              AND event.disposition IS NEW.disposition
              AND event.cumulative_principal_minor = NEW.cumulative_principal_minor
              AND event.external_version = NEW.current_external_version
              AND event.effective_at = NEW.current_effective_at
              AND event.received_at = NEW.current_received_at);
        END""",
        """CREATE TRIGGER trg_financial_cases_delete BEFORE DELETE ON financial_cases BEGIN
          SELECT RAISE(ABORT, 'financial case projections cannot be deleted');
        END""",
        """CREATE TRIGGER trg_financial_case_events_insert BEFORE INSERT ON financial_case_events BEGIN
          SELECT RAISE(ABORT, 'financial case event requires compatible unconflicted source evidence')
          WHERE NOT EXISTS (
            SELECT 1 FROM financial_cases AS case_row
            JOIN financial_transactions AS event_tx
              ON event_tx.id = NEW.financial_transaction_id
            JOIN financial_transactions AS source_tx
              ON source_tx.id = case_row.source_financial_transaction_id
            JOIN external_event_inbox AS inbox ON inbox.id = NEW.inbox_event_id
            WHERE case_row.id = NEW.financial_case_id
              AND event_tx.kind = case_row.case_type
              AND event_tx.object_type = case_row.case_type
              AND event_tx.provider = case_row.provider
              AND event_tx.object_id = case_row.case_object_id
              AND event_tx.external_version = NEW.external_version
              AND event_tx.inbox_event_id = NEW.inbox_event_id
              AND event_tx.billing_account_id = case_row.billing_account_id
              AND event_tx.currency = source_tx.currency
              AND source_tx.billing_account_id = case_row.billing_account_id
              AND source_tx.provider = case_row.provider
              AND source_tx.kind IN ('invoice', 'payment')
              AND inbox.provider = case_row.provider
              AND inbox.object_type = case_row.case_type
              AND inbox.object_id = case_row.case_object_id
              AND inbox.state IN ('processing', 'processed')
              AND inbox.received_at = NEW.received_at
              AND event_tx.effective_at = NEW.effective_at
              AND (
                (case_row.case_type = 'refund' AND (
                  (NEW.state = 'refund_recorded' AND NEW.disposition IS NULL)
                  OR (NEW.state = 'financial_only' AND NEW.disposition = 'financial_only')
                  OR (NEW.state = 'entitlement_reducing_review'
                      AND NEW.disposition = 'entitlement_reducing_review')
                ))
                OR (case_row.case_type = 'dispute'
                    AND NEW.state IN ('opened', 'pending', 'won', 'lost')
                    AND NEW.disposition IS NULL)
              )
              AND NEW.cumulative_principal_minor <= abs(source_tx.principal_minor)
              AND NOT EXISTS (
                SELECT 1 FROM external_event_inbox_conflicts AS conflict
                WHERE conflict.inbox_event_id = NEW.inbox_event_id));
        END""",
        """CREATE TRIGGER trg_financial_case_events_update BEFORE UPDATE ON financial_case_events BEGIN
          SELECT RAISE(ABORT, 'financial case events are immutable evidence');
        END""",
        """CREATE TRIGGER trg_financial_case_events_delete BEFORE DELETE ON financial_case_events BEGIN
          SELECT RAISE(ABORT, 'financial case events are immutable evidence');
        END""",
        """CREATE TRIGGER trg_financial_case_event_lines_insert BEFORE INSERT ON financial_case_event_lines BEGIN
          SELECT RAISE(ABORT, 'financial case attribution must reference an eligible source line')
          WHERE NOT EXISTS (
            SELECT 1 FROM financial_case_events AS event
            JOIN financial_cases AS case_row ON case_row.id = event.financial_case_id
            JOIN financial_lines AS source_line
              ON source_line.id = NEW.financial_line_id
             AND source_line.financial_transaction_id = case_row.source_financial_transaction_id
            WHERE event.id = NEW.financial_case_event_id
              AND source_line.line_kind NOT IN ('tax', 'fee', 'discount')
              AND NEW.attributed_principal_minor <=
                  max(0, source_line.principal_minor + source_line.discount_minor));
        END""",
        """CREATE TRIGGER trg_financial_case_event_lines_update BEFORE UPDATE ON financial_case_event_lines BEGIN
          SELECT RAISE(ABORT, 'financial case line attribution is immutable');
        END""",
        """CREATE TRIGGER trg_financial_case_event_lines_delete BEFORE DELETE ON financial_case_event_lines BEGIN
          SELECT RAISE(ABORT, 'financial case line attribution is immutable');
        END""",
        """CREATE TRIGGER trg_financial_case_ledger_entries_insert BEFORE INSERT ON financial_case_event_ledger_entries BEGIN
          SELECT RAISE(ABORT, 'financial case ledger reference must match its case and effect')
          WHERE NOT EXISTS (
            SELECT 1 FROM financial_case_events AS case_event
            JOIN financial_cases AS case_row ON case_row.id = case_event.financial_case_id
            JOIN credit_ledger_entries AS ledger_entry
              ON ledger_entry.id = NEW.credit_ledger_entry_id
            WHERE case_event.id = NEW.financial_case_event_id
              AND ledger_entry.billing_account_id = case_row.billing_account_id
              AND (
                (NEW.effect_type = 'hold' AND case_row.case_type = 'dispute'
                 AND ledger_entry.entry_type = 'dispute_hold')
                OR (NEW.effect_type = 'release' AND case_row.case_type = 'dispute'
                    AND ledger_entry.entry_type = 'release')
                OR (NEW.effect_type = 'reversal' AND (
                  (case_row.case_type = 'refund' AND ledger_entry.entry_type = 'refund_reversal')
                  OR (case_row.case_type = 'dispute' AND ledger_entry.entry_type = 'dispute_reversal')
                ))
                OR (NEW.effect_type = 'recovery' AND ledger_entry.entry_type = 'recovery')
              ));
        END""",
        """CREATE TRIGGER trg_financial_case_ledger_entries_update BEFORE UPDATE ON financial_case_event_ledger_entries BEGIN
          SELECT RAISE(ABORT, 'financial case ledger references are immutable');
        END""",
        """CREATE TRIGGER trg_financial_case_ledger_entries_delete BEFORE DELETE ON financial_case_event_ledger_entries BEGIN
          SELECT RAISE(ABORT, 'financial case ledger references are immutable');
        END""",
    )
    for statement in statements:
        op.execute(sa.text(statement))


def upgrade():
    dialect = op.get_bind().dialect.name
    _create_tables(dialect)
    if dialect == "postgresql":
        _postgresql_triggers()
    elif dialect == "sqlite":
        _sqlite_triggers()


def downgrade():
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.execute(sa.text(
            "LOCK TABLE financial_cases, financial_case_events, "
            "financial_case_event_lines, financial_case_event_ledger_entries "
            "IN ACCESS EXCLUSIVE MODE"
        ))
    counts = {
        table: bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
        for table in PHASE_5_3_TABLES
    }
    if any(counts.values()):
        details = ", ".join(f"{table}={count}" for table, count in counts.items())
        raise FinancialCasesNotEmptyError(
            f"Cannot downgrade {revision}: {details}. Phase 5.3 downgrade may remove only empty tables."
        )
    if dialect == "postgresql":
        for table in PHASE_5_3_TABLES:
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_no_truncate ON {table}"))
        op.execute(sa.text(
            "DROP TRIGGER IF EXISTS trg_financial_cases_projection ON financial_cases"
        ))
        op.execute(sa.text(
            "DROP TRIGGER IF EXISTS trg_financial_case_event_lines_reconcile "
            "ON financial_case_event_lines"
        ))
        op.execute(sa.text(
            "DROP TRIGGER IF EXISTS trg_financial_case_events_reconcile "
            "ON financial_case_events"
        ))
        op.execute(sa.text(
            "DROP TRIGGER IF EXISTS trg_financial_case_event_ledger_entries_guard "
            "ON financial_case_event_ledger_entries"
        ))
        op.execute(sa.text(
            "DROP TRIGGER IF EXISTS trg_financial_case_event_lines_guard "
            "ON financial_case_event_lines"
        ))
        op.execute(sa.text(
            "DROP TRIGGER IF EXISTS trg_financial_case_events_guard ON financial_case_events"
        ))
        op.execute(sa.text(
            "DROP TRIGGER IF EXISTS trg_financial_cases_guard ON financial_cases"
        ))
        op.execute(sa.text(
            "DROP FUNCTION IF EXISTS phase53_financial_case_reject_truncate()"
        ))
        op.execute(sa.text(
            "DROP FUNCTION IF EXISTS phase53_financial_case_projection_guard()"
        ))
        op.execute(sa.text(
            "DROP FUNCTION IF EXISTS phase53_financial_case_line_reconcile()"
        ))
        op.execute(sa.text(
            "DROP FUNCTION IF EXISTS phase53_financial_case_event_reconcile()"
        ))
        op.execute(sa.text(
            "DROP FUNCTION IF EXISTS phase53_financial_case_reconcile_id(text)"
        ))
        op.execute(sa.text(
            "DROP FUNCTION IF EXISTS phase53_financial_case_ledger_link_guard()"
        ))
        op.execute(sa.text(
            "DROP FUNCTION IF EXISTS phase53_financial_case_line_guard()"
        ))
        op.execute(sa.text(
            "DROP FUNCTION IF EXISTS phase53_financial_case_event_guard()"
        ))
        op.execute(sa.text(
            "DROP FUNCTION IF EXISTS phase53_financial_case_guard()"
        ))
    elif dialect == "sqlite":
        for trigger in (
            "trg_financial_case_ledger_entries_delete",
            "trg_financial_case_ledger_entries_update",
            "trg_financial_case_ledger_entries_insert",
            "trg_financial_case_event_lines_delete",
            "trg_financial_case_event_lines_update",
            "trg_financial_case_event_lines_insert",
            "trg_financial_case_events_delete",
            "trg_financial_case_events_update",
            "trg_financial_case_events_insert",
            "trg_financial_cases_delete",
            "trg_financial_cases_update",
        ):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger}"))
    op.drop_index(
        "ix_financial_case_event_ledger_entries_ledger_entry",
        table_name=LEDGER_LINK_TABLE,
    )
    op.drop_table(LEDGER_LINK_TABLE)
    op.drop_index(
        "ix_financial_case_event_lines_financial_line", table_name=LINE_TABLE,
    )
    op.drop_table(LINE_TABLE)
    op.drop_index("ix_financial_case_events_inbox_event", table_name=EVENT_TABLE)
    op.drop_index("ix_financial_case_events_transaction", table_name=EVENT_TABLE)
    op.drop_table(EVENT_TABLE)
    op.drop_index("ix_financial_cases_source_transaction", table_name=CASE_TABLE)
    op.drop_index("ix_financial_cases_account_state", table_name=CASE_TABLE)
    op.drop_table(CASE_TABLE)
