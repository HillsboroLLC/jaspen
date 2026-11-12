"""Add inactive financial transaction and line foundations (Phase 5.2).

Revision ID: c3e5a7b9d1f4
Revises: b2d4f6a8c0e3

The tables record immutable money facts and exact source-attributed line
components. They do not grant entitlements or move credits, and no live route,
webhook, browser confirmation, or job writes them.
"""

from alembic import op
import sqlalchemy as sa


revision = "c3e5a7b9d1f4"
down_revision = "b2d4f6a8c0e3"
branch_labels = None
depends_on = None

TRANSACTION_TABLE = "financial_transactions"
LINE_TABLE = "financial_lines"
PHASE_5_2_TABLES = (LINE_TABLE, TRANSACTION_TABLE)
TRANSACTION_KINDS = ("invoice", "payment", "refund", "dispute", "recovery", "adjustment")
LINE_KINDS = ("subscription", "seat", "credit_pack", "tax", "fee", "discount", "other")


class FinancialFoundationNotEmptyError(RuntimeError):
    """Raised when downgrade would discard immutable financial evidence."""


def _quoted(values):
    return ", ".join(f"'{value}'" for value in values)


def _currency_check(column):
    return (
        f"length({column}) = 3 AND {column} = lower({column}) AND "
        f"substr({column}, 1, 1) BETWEEN 'a' AND 'z' AND "
        f"substr({column}, 2, 1) BETWEEN 'a' AND 'z' AND "
        f"substr({column}, 3, 1) BETWEEN 'a' AND 'z'"
    )


def _create_tables(dialect):
    created_xid_default = (
        sa.text("pg_current_xact_id()::text")
        if dialect == "postgresql" else sa.text("'0'")
    )
    op.create_table(
        TRANSACTION_TABLE,
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("billing_account_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("object_type", sa.String(64), nullable=False),
        sa.Column("object_id", sa.String(255), nullable=False),
        sa.Column("external_version", sa.String(255), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("principal_minor", sa.BigInteger(), nullable=False),
        sa.Column("tax_minor", sa.BigInteger(), nullable=False),
        sa.Column("fee_minor", sa.BigInteger(), nullable=False),
        sa.Column("discount_minor", sa.BigInteger(), nullable=False),
        sa.Column("gross_minor", sa.BigInteger(), nullable=False),
        sa.Column("inbox_event_id", sa.String(36), nullable=True),
        sa.Column(
            "created_xid", sa.String(20), nullable=False,
            server_default=created_xid_default,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            f"kind IN ({_quoted(TRANSACTION_KINDS)})",
            name="ck_financial_transactions_kind",
        ),
        sa.CheckConstraint(
            "length(trim(provider)) > 0 AND length(trim(object_type)) > 0 "
            "AND length(trim(object_id)) > 0 AND length(trim(external_version)) > 0",
            name="ck_financial_transactions_identity",
        ),
        sa.CheckConstraint(_currency_check("currency"), name="ck_financial_transactions_currency"),
        sa.CheckConstraint(
            "gross_minor = principal_minor + tax_minor + fee_minor + discount_minor",
            name="ck_financial_transactions_arithmetic",
        ),
        sa.CheckConstraint(
            "kind = 'adjustment' OR inbox_event_id IS NOT NULL",
            name="ck_financial_transactions_external_evidence",
        ),
        sa.ForeignKeyConstraint(
            ["billing_account_id"], ["billing_accounts.id"],
            name="fk_financial_transactions_billing_account_id", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["inbox_event_id"], ["external_event_inbox.id"],
            name="fk_financial_transactions_inbox_event_id", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_financial_transactions"),
        sa.UniqueConstraint(
            "provider", "object_type", "object_id", "kind", "external_version",
            name="uq_financial_transactions_business_version",
        ),
    )
    op.create_index(
        "ix_financial_transactions_account_effective", TRANSACTION_TABLE,
        ["billing_account_id", "effective_at", "id"],
    )
    op.create_index(
        "ix_financial_transactions_provider_object_effective", TRANSACTION_TABLE,
        ["provider", "object_type", "object_id", "effective_at"],
    )
    op.create_index(
        "ix_financial_transactions_inbox_event_id", TRANSACTION_TABLE, ["inbox_event_id"],
    )

    op.create_table(
        LINE_TABLE,
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("financial_transaction_id", sa.String(36), nullable=False),
        sa.Column("external_line_id", sa.String(255), nullable=False),
        sa.Column("line_kind", sa.String(32), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_id", sa.String(255), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("principal_minor", sa.BigInteger(), nullable=False),
        sa.Column("tax_minor", sa.BigInteger(), nullable=False),
        sa.Column("fee_minor", sa.BigInteger(), nullable=False),
        sa.Column("discount_minor", sa.BigInteger(), nullable=False),
        sa.Column("subscription_id", sa.String(36), nullable=True),
        sa.Column("entitlement_instance_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            f"line_kind IN ({_quoted(LINE_KINDS)})", name="ck_financial_lines_kind",
        ),
        sa.CheckConstraint(
            "length(trim(external_line_id)) > 0 AND length(trim(source_type)) > 0 "
            "AND length(trim(source_id)) > 0",
            name="ck_financial_lines_identity",
        ),
        sa.CheckConstraint("quantity > 0", name="ck_financial_lines_quantity"),
        sa.CheckConstraint(_currency_check("currency"), name="ck_financial_lines_currency"),
        sa.ForeignKeyConstraint(
            ["financial_transaction_id"], ["financial_transactions.id"],
            name="fk_financial_lines_transaction_id", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["billing_subscriptions.id"],
            name="fk_financial_lines_subscription_id", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["entitlement_instance_id"], ["entitlement_instances.id"],
            name="fk_financial_lines_entitlement_instance_id", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_financial_lines"),
        sa.UniqueConstraint(
            "financial_transaction_id", "external_line_id", "line_kind",
            name="uq_financial_lines_transaction_external_kind",
        ),
    )
    op.create_index(
        "ix_financial_lines_source", LINE_TABLE,
        ["source_type", "source_id", "financial_transaction_id"],
    )
    op.create_index("ix_financial_lines_subscription_id", LINE_TABLE, ["subscription_id"])
    op.create_index(
        "ix_financial_lines_entitlement_instance_id", LINE_TABLE, ["entitlement_instance_id"],
    )


def _postgresql_triggers():
    op.execute(sa.text("""
        CREATE FUNCTION phase5_financial_fence_inbox_conflict() RETURNS trigger AS $$
        BEGIN
          UPDATE external_event_inbox AS inbox
          SET state = inbox.state
          WHERE inbox.id = NEW.inbox_event_id
            AND inbox.state = 'processed';
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_financial_fence_inbox_conflict
        AFTER INSERT ON external_event_inbox_conflicts
        FOR EACH ROW EXECUTE FUNCTION phase5_financial_fence_inbox_conflict()
    """))
    op.execute(sa.text("""
        CREATE FUNCTION phase5_financial_transaction_guard() RETURNS trigger AS $$
        DECLARE
          account_currency varchar(3);
          event_provider varchar(32);
          event_state varchar(16);
          event_object_type varchar(64);
          event_object_id varchar(255);
        BEGIN
          IF TG_OP <> 'INSERT' THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
              MESSAGE = 'financial transactions are immutable evidence';
          END IF;
          SELECT account.currency INTO account_currency
          FROM billing_accounts AS account WHERE account.id = NEW.billing_account_id;
          IF account_currency IS NULL OR account_currency IS DISTINCT FROM NEW.currency THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
              MESSAGE = 'financial transaction currency must match its billing account';
          END IF;
          IF NEW.inbox_event_id IS NOT NULL THEN
            SELECT event.provider, event.state, event.object_type, event.object_id
            INTO event_provider, event_state, event_object_type, event_object_id
            FROM external_event_inbox AS event WHERE event.id = NEW.inbox_event_id FOR UPDATE;
            IF event_provider IS NULL OR event_provider IS DISTINCT FROM NEW.provider
               OR event_object_type IS DISTINCT FROM NEW.object_type
               OR event_object_id IS DISTINCT FROM NEW.object_id
               OR event_state NOT IN ('processing', 'processed')
               OR EXISTS (
                 SELECT 1 FROM external_event_inbox_conflicts AS conflict
                 WHERE conflict.inbox_event_id = NEW.inbox_event_id
               ) THEN
              RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'financial transaction requires compatible unconflicted inbox evidence';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_financial_transactions_guard
        BEFORE INSERT OR UPDATE OR DELETE ON financial_transactions
        FOR EACH ROW EXECUTE FUNCTION phase5_financial_transaction_guard()
    """))

    op.execute(sa.text("""
        CREATE FUNCTION phase5_financial_line_guard() RETURNS trigger AS $$
        DECLARE
          transaction_account varchar(36);
          transaction_currency varchar(3);
          transaction_created_here boolean;
          subscription_account varchar(36);
          entitlement_account varchar(36);
          entitlement_subscription varchar(36);
        BEGIN
          IF TG_OP <> 'INSERT' THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
              MESSAGE = 'financial lines are immutable evidence';
          END IF;
          SELECT txn.billing_account_id, txn.currency,
                 txn.created_xid = pg_current_xact_id()::text
          INTO transaction_account, transaction_currency, transaction_created_here
          FROM financial_transactions AS txn
          WHERE txn.id = NEW.financial_transaction_id;
          IF transaction_account IS NULL OR transaction_currency IS DISTINCT FROM NEW.currency THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
              MESSAGE = 'financial line currency must match its transaction';
          END IF;
          IF NOT transaction_created_here THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
              MESSAGE = 'financial lines must be committed atomically with their transaction';
          END IF;
          IF NEW.subscription_id IS NOT NULL THEN
            SELECT subscription.billing_account_id INTO subscription_account
            FROM billing_subscriptions AS subscription WHERE subscription.id = NEW.subscription_id;
            IF subscription_account IS DISTINCT FROM transaction_account THEN
              RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'financial line subscription must belong to the transaction account';
            END IF;
          END IF;
          IF NEW.entitlement_instance_id IS NOT NULL THEN
            SELECT entitlement.billing_account_id, entitlement.subscription_id
            INTO entitlement_account, entitlement_subscription
            FROM entitlement_instances AS entitlement WHERE entitlement.id = NEW.entitlement_instance_id;
            IF entitlement_account IS DISTINCT FROM transaction_account
               OR (NEW.subscription_id IS NOT NULL
                   AND entitlement_subscription IS DISTINCT FROM NEW.subscription_id) THEN
              RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'financial line entitlement must belong to its account and subscription';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_financial_lines_guard
        BEFORE INSERT OR UPDATE OR DELETE ON financial_lines
        FOR EACH ROW EXECUTE FUNCTION phase5_financial_line_guard()
    """))

    op.execute(sa.text("""
        CREATE FUNCTION phase5_financial_reconcile_id(target_transaction_id text) RETURNS void AS $$
        DECLARE
          expected record;
          actual record;
        BEGIN
          SELECT txn.principal_minor, txn.tax_minor,
                 txn.fee_minor, txn.discount_minor
          INTO expected
          FROM financial_transactions AS txn WHERE txn.id = target_transaction_id;
          SELECT count(*) AS line_count,
                 COALESCE(sum(line.principal_minor), 0) AS principal_minor,
                 COALESCE(sum(line.tax_minor), 0) AS tax_minor,
                 COALESCE(sum(line.fee_minor), 0) AS fee_minor,
                 COALESCE(sum(line.discount_minor), 0) AS discount_minor
          INTO actual
          FROM financial_lines AS line
          WHERE line.financial_transaction_id = target_transaction_id;
          IF actual.line_count = 0
             OR actual.principal_minor IS DISTINCT FROM expected.principal_minor
             OR actual.tax_minor IS DISTINCT FROM expected.tax_minor
             OR actual.fee_minor IS DISTINCT FROM expected.fee_minor
             OR actual.discount_minor IS DISTINCT FROM expected.discount_minor THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
              MESSAGE = 'financial transaction totals must exactly reconcile to its lines';
          END IF;
        END;
        $$ LANGUAGE plpgsql
    """))
    op.execute(sa.text("""
        CREATE FUNCTION phase5_financial_transaction_reconcile() RETURNS trigger AS $$
        BEGIN
          PERFORM phase5_financial_reconcile_id(NEW.id);
          RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
    """))
    op.execute(sa.text("""
        CREATE FUNCTION phase5_financial_line_reconcile() RETURNS trigger AS $$
        BEGIN
          PERFORM phase5_financial_reconcile_id(NEW.financial_transaction_id);
          RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
    """))
    op.execute(sa.text("""
        CREATE CONSTRAINT TRIGGER trg_financial_transactions_reconcile
        AFTER INSERT ON financial_transactions
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION phase5_financial_transaction_reconcile()
    """))
    op.execute(sa.text("""
        CREATE CONSTRAINT TRIGGER trg_financial_lines_reconcile
        AFTER INSERT ON financial_lines
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION phase5_financial_line_reconcile()
    """))

    op.execute(sa.text("""
        CREATE FUNCTION phase5_financial_reject_truncate() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'financial evidence cannot be truncated';
        END;
        $$ LANGUAGE plpgsql
    """))
    for table in (TRANSACTION_TABLE, LINE_TABLE):
        op.execute(sa.text(f"""
            CREATE TRIGGER trg_{table}_no_truncate
            BEFORE TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION phase5_financial_reject_truncate()
        """))


def _sqlite_triggers():
    statements = (
        """CREATE TRIGGER trg_financial_transactions_insert BEFORE INSERT ON financial_transactions BEGIN
          SELECT RAISE(ABORT, 'financial transaction currency must match its billing account')
          WHERE NOT EXISTS (SELECT 1 FROM billing_accounts AS account
                            WHERE account.id = NEW.billing_account_id AND account.currency = NEW.currency);
          SELECT RAISE(ABORT, 'financial transaction requires compatible unconflicted inbox evidence')
          WHERE NEW.inbox_event_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM external_event_inbox AS event
            WHERE event.id = NEW.inbox_event_id AND event.provider = NEW.provider
              AND event.object_type = NEW.object_type AND event.object_id = NEW.object_id
              AND event.state IN ('processing', 'processed')
              AND NOT EXISTS (SELECT 1 FROM external_event_inbox_conflicts AS conflict
                              WHERE conflict.inbox_event_id = event.id));
        END""",
        """CREATE TRIGGER trg_financial_transactions_update BEFORE UPDATE ON financial_transactions BEGIN
          SELECT RAISE(ABORT, 'financial transactions are immutable evidence');
        END""",
        """CREATE TRIGGER trg_financial_transactions_delete BEFORE DELETE ON financial_transactions BEGIN
          SELECT RAISE(ABORT, 'financial transactions are immutable evidence');
        END""",
        """CREATE TRIGGER trg_financial_lines_insert BEFORE INSERT ON financial_lines BEGIN
          SELECT RAISE(ABORT, 'financial line currency must match its transaction')
          WHERE NOT EXISTS (SELECT 1 FROM financial_transactions AS txn
                            WHERE txn.id = NEW.financial_transaction_id
                              AND txn.currency = NEW.currency);
          SELECT RAISE(ABORT, 'financial line subscription must belong to the transaction account')
          WHERE NEW.subscription_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM billing_subscriptions AS subscription
            JOIN financial_transactions AS txn ON txn.id = NEW.financial_transaction_id
            WHERE subscription.id = NEW.subscription_id
              AND subscription.billing_account_id = txn.billing_account_id);
          SELECT RAISE(ABORT, 'financial line entitlement must belong to its account and subscription')
          WHERE NEW.entitlement_instance_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM entitlement_instances AS entitlement
            JOIN financial_transactions AS txn ON txn.id = NEW.financial_transaction_id
            WHERE entitlement.id = NEW.entitlement_instance_id
              AND entitlement.billing_account_id = txn.billing_account_id
              AND (NEW.subscription_id IS NULL OR entitlement.subscription_id = NEW.subscription_id));
        END""",
        """CREATE TRIGGER trg_financial_lines_update BEFORE UPDATE ON financial_lines BEGIN
          SELECT RAISE(ABORT, 'financial lines are immutable evidence');
        END""",
        """CREATE TRIGGER trg_financial_lines_delete BEFORE DELETE ON financial_lines BEGIN
          SELECT RAISE(ABORT, 'financial lines are immutable evidence');
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
    """Remove Phase 5.2 only while both financial evidence tables are empty."""
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.execute(sa.text(
            "LOCK TABLE financial_transactions, financial_lines IN ACCESS EXCLUSIVE MODE"
        ))
    counts = {
        table: bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
        for table in (TRANSACTION_TABLE, LINE_TABLE)
    }
    if any(counts.values()):
        details = ", ".join(f"{table}={count}" for table, count in counts.items())
        raise FinancialFoundationNotEmptyError(
            f"Cannot downgrade {revision}: {details}. Phase 5.2 downgrade may remove only empty tables."
        )
    if dialect == "postgresql":
        op.execute(sa.text(
            "DROP TRIGGER IF EXISTS trg_financial_fence_inbox_conflict ON external_event_inbox_conflicts"
        ))
        for table in (TRANSACTION_TABLE, LINE_TABLE):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{table}_no_truncate ON {table}"))
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_financial_lines_reconcile ON financial_lines"))
        op.execute(sa.text(
            "DROP TRIGGER IF EXISTS trg_financial_transactions_reconcile ON financial_transactions"
        ))
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_financial_lines_guard ON financial_lines"))
        op.execute(sa.text(
            "DROP TRIGGER IF EXISTS trg_financial_transactions_guard ON financial_transactions"
        ))
        op.execute(sa.text("DROP FUNCTION IF EXISTS phase5_financial_reject_truncate()"))
        op.execute(sa.text("DROP FUNCTION IF EXISTS phase5_financial_line_reconcile()"))
        op.execute(sa.text(
            "DROP FUNCTION IF EXISTS phase5_financial_transaction_reconcile()"
        ))
        op.execute(sa.text(
            "DROP FUNCTION IF EXISTS phase5_financial_reconcile_id(text)"
        ))
        op.execute(sa.text("DROP FUNCTION IF EXISTS phase5_financial_fence_inbox_conflict()"))
        op.execute(sa.text("DROP FUNCTION IF EXISTS phase5_financial_line_guard()"))
        op.execute(sa.text("DROP FUNCTION IF EXISTS phase5_financial_transaction_guard()"))
    elif dialect == "sqlite":
        for trigger in (
            "trg_financial_lines_delete",
            "trg_financial_lines_update",
            "trg_financial_lines_insert",
            "trg_financial_transactions_delete",
            "trg_financial_transactions_update",
            "trg_financial_transactions_insert",
        ):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger}"))
    op.drop_index("ix_financial_lines_entitlement_instance_id", table_name=LINE_TABLE)
    op.drop_index("ix_financial_lines_subscription_id", table_name=LINE_TABLE)
    op.drop_index("ix_financial_lines_source", table_name=LINE_TABLE)
    op.drop_table(LINE_TABLE)
    op.drop_index("ix_financial_transactions_inbox_event_id", table_name=TRANSACTION_TABLE)
    op.drop_index("ix_financial_transactions_provider_object_effective", table_name=TRANSACTION_TABLE)
    op.drop_index("ix_financial_transactions_account_effective", table_name=TRANSACTION_TABLE)
    op.drop_table(TRANSACTION_TABLE)
