"""Add the inactive authoritative credit ledger foundation.

Revision ID: e8b0f2d4a6c3
Revises: d7a9e1c3f5b2

Phase 3 creates empty append-only ledger primitives and database invariants.
It does not backfill balances or connect any current billing or AI writer.
"""

from alembic import op
import sqlalchemy as sa


revision = "e8b0f2d4a6c3"
down_revision = "d7a9e1c3f5b2"
branch_labels = None
depends_on = None


LEDGER_TABLES = (
    "credit_lots",
    "credit_reservations",
    "credit_ledger_entries",
)


class CreditLedgerNotEmptyError(RuntimeError):
    """Raised when downgrade would discard authoritative ledger evidence."""


ENTRY_TYPES = (
    "'grant', 'reservation', 'settlement', 'release', 'expiration', "
    "'refund_reversal', 'dispute_hold', 'dispute_reversal', 'recovery', "
    "'admin_adjustment', 'migration_opening'"
)


def _create_tables():
    op.create_table(
        "credit_lots",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("billing_account_id", sa.String(36), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_id", sa.String(255), nullable=False),
        sa.Column("member_attribution_id", sa.String(36), nullable=True),
        sa.Column("eligibility_scope", sa.JSON(), nullable=True),
        sa.Column("original_amount", sa.BigInteger(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("origin_evidence_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "source_type IN ('free_recurring', 'subscription_recurring', "
            "'enterprise_recurring', 'credit_pack_purchase', 'promotional', "
            "'trial', 'comp', 'internal', 'legacy_unattributed')",
            name="ck_credit_lots_source_type",
        ),
        sa.CheckConstraint(
            "original_amount > 0",
            name="ck_credit_lots_original_amount",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > available_at",
            name="ck_credit_lots_expiry",
        ),
        sa.ForeignKeyConstraint(
            ["billing_account_id"],
            ["billing_accounts.id"],
            name="fk_credit_lots_billing_account_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["member_attribution_id"],
            ["users.id"],
            name="fk_credit_lots_member_attribution_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_credit_lots"),
        sa.UniqueConstraint(
            "billing_account_id",
            "source_type",
            "source_id",
            name="uq_credit_lots_account_source",
        ),
    )
    op.create_index(
        "ix_credit_lots_account_allocation_order",
        "credit_lots",
        ["billing_account_id", "expires_at", "source_type", "available_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_credit_lots_member_attribution_id",
        "credit_lots",
        ["member_attribution_id"],
        unique=False,
    )

    op.create_table(
        "credit_reservations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("billing_account_id", sa.String(36), nullable=False),
        sa.Column("operation_id", sa.String(36), nullable=False),
        sa.Column("pricing_policy_version_id", sa.String(36), nullable=False),
        sa.Column("capacity_policy_version_id", sa.String(36), nullable=True),
        sa.Column("idempotency_registry_id", sa.String(36), nullable=False),
        sa.Column("requested_amount", sa.BigInteger(), nullable=False),
        sa.Column("authorized_amount", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "requested_amount > 0 AND authorized_amount > 0 "
            "AND authorized_amount <= requested_amount",
            name="ck_credit_reservations_amounts",
        ),
        sa.CheckConstraint(
            "state IN ('reserved', 'partially_settled', 'settled', 'released', "
            "'expired')",
            name="ck_credit_reservations_state",
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64 AND "
            "request_fingerprint = lower(request_fingerprint)",
            name="ck_credit_reservations_fingerprint",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_credit_reservations_expiry",
        ),
        sa.CheckConstraint(
            "((state IN ('settled', 'released', 'expired') AND finalized_at IS NOT NULL) "
            "OR (state IN ('reserved', 'partially_settled') AND finalized_at IS NULL))",
            name="ck_credit_reservations_finalization",
        ),
        sa.ForeignKeyConstraint(
            ["billing_account_id"],
            ["billing_accounts.id"],
            name="fk_credit_reservations_billing_account_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["ai_operations.id"],
            name="fk_credit_reservations_operation_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["pricing_policy_version_id"],
            ["pricing_policy_versions.id"],
            name="fk_credit_reservations_pricing_policy_version_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["capacity_policy_version_id"],
            ["capacity_policy_versions.id"],
            name="fk_credit_reservations_capacity_policy_version_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["idempotency_registry_id"],
            ["idempotency_registry.id"],
            name="fk_credit_reservations_idempotency_registry_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_credit_reservations"),
        sa.UniqueConstraint(
            "operation_id",
            name="uq_credit_reservations_operation_id",
        ),
        sa.UniqueConstraint(
            "idempotency_registry_id",
            name="uq_credit_reservations_idempotency_registry_id",
        ),
    )
    op.create_index(
        "ix_credit_reservations_account_state_expiry",
        "credit_reservations",
        ["billing_account_id", "state", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_credit_reservations_pricing_policy_version_id",
        "credit_reservations",
        ["pricing_policy_version_id"],
        unique=False,
    )
    op.create_index(
        "ix_credit_reservations_capacity_policy_version_id",
        "credit_reservations",
        ["capacity_policy_version_id"],
        unique=False,
    )

    op.create_table(
        "credit_ledger_entries",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("billing_account_id", sa.String(36), nullable=False),
        sa.Column("lot_id", sa.String(36), nullable=False),
        sa.Column("entry_type", sa.String(32), nullable=False),
        sa.Column("available_delta", sa.BigInteger(), nullable=False),
        sa.Column("held_delta", sa.BigInteger(), nullable=False),
        sa.Column("reservation_id", sa.String(36), nullable=True),
        sa.Column("operation_id", sa.String(36), nullable=True),
        sa.Column("related_entry_id", sa.String(36), nullable=True),
        sa.Column("idempotency_registry_id", sa.String(36), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("actor_type", sa.String(40), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("reason_code", sa.String(120), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            f"entry_type IN ({ENTRY_TYPES})",
            name="ck_credit_ledger_entries_type",
        ),
        sa.CheckConstraint(
            "available_delta != 0 OR held_delta != 0",
            name="ck_credit_ledger_entries_nonzero",
        ),
        sa.CheckConstraint(
            "((entry_type IN ('grant', 'recovery', 'migration_opening') "
            "AND available_delta > 0 AND held_delta = 0) OR "
            "(entry_type IN ('reservation', 'dispute_hold') "
            "AND available_delta < 0 AND held_delta > 0 "
            "AND available_delta + held_delta = 0) OR "
            "(entry_type = 'release' AND available_delta > 0 AND held_delta < 0 "
            "AND available_delta + held_delta = 0) OR "
            "(entry_type IN ('settlement', 'dispute_reversal') "
            "AND available_delta = 0 AND held_delta < 0) OR "
            "(entry_type = 'expiration' AND available_delta <= 0 "
            "AND held_delta <= 0 AND (available_delta < 0 OR held_delta < 0)) OR "
            "(entry_type = 'refund_reversal' "
            "AND available_delta < 0 AND held_delta = 0) OR "
            "(entry_type = 'admin_adjustment' AND available_delta != 0 "
            "AND held_delta = 0))",
            name="ck_credit_ledger_entries_shape",
        ),
        sa.CheckConstraint(
            "((entry_type IN ('reservation', 'settlement', 'release') "
            "AND reservation_id IS NOT NULL AND operation_id IS NOT NULL) OR "
            "(entry_type NOT IN ('reservation', 'settlement', 'release') "
            "AND reservation_id IS NULL AND operation_id IS NULL))",
            name="ck_credit_ledger_entries_operation_reference",
        ),
        sa.CheckConstraint(
            "((entry_type IN ('settlement', 'release', 'refund_reversal', "
            "'dispute_reversal', 'recovery') AND related_entry_id IS NOT NULL) "
            "OR entry_type = 'expiration' "
            "OR (entry_type NOT IN ('settlement', 'release', 'expiration', "
            "'refund_reversal', 'dispute_reversal', 'recovery') "
            "AND related_entry_id IS NULL))",
            name="ck_credit_ledger_entries_related_reference",
        ),
        sa.CheckConstraint(
            "related_entry_id IS NULL OR related_entry_id != id",
            name="ck_credit_ledger_entries_not_self_related",
        ),
        sa.CheckConstraint(
            "length(trim(actor_type)) > 0 AND length(trim(actor_id)) > 0 "
            "AND length(trim(reason_code)) > 0",
            name="ck_credit_ledger_entries_provenance",
        ),
        sa.ForeignKeyConstraint(
            ["billing_account_id"],
            ["billing_accounts.id"],
            name="fk_credit_ledger_entries_billing_account_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lot_id"],
            ["credit_lots.id"],
            name="fk_credit_ledger_entries_lot_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reservation_id"],
            ["credit_reservations.id"],
            name="fk_credit_ledger_entries_reservation_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["ai_operations.id"],
            name="fk_credit_ledger_entries_operation_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["related_entry_id"],
            ["credit_ledger_entries.id"],
            name="fk_credit_ledger_entries_related_entry_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["idempotency_registry_id"],
            ["idempotency_registry.id"],
            name="fk_credit_ledger_entries_idempotency_registry_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_credit_ledger_entries"),
        sa.UniqueConstraint(
            "idempotency_registry_id",
            name="uq_credit_ledger_entries_idempotency_registry_id",
        ),
    )
    op.create_index(
        "ix_credit_ledger_entries_account_effective",
        "credit_ledger_entries",
        ["billing_account_id", "effective_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_credit_ledger_entries_lot_effective",
        "credit_ledger_entries",
        ["lot_id", "effective_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_credit_ledger_entries_reservation_id",
        "credit_ledger_entries",
        ["reservation_id"],
        unique=False,
    )
    op.create_index(
        "ix_credit_ledger_entries_operation_id",
        "credit_ledger_entries",
        ["operation_id"],
        unique=False,
    )
    op.create_index(
        "ix_credit_ledger_entries_related_entry_id",
        "credit_ledger_entries",
        ["related_entry_id"],
        unique=False,
    )
    op.create_index(
        "uq_credit_ledger_entries_lot_opening",
        "credit_ledger_entries",
        ["lot_id"],
        unique=True,
        postgresql_where=sa.text(
            "entry_type IN ('grant', 'migration_opening')"
        ),
        sqlite_where=sa.text(
            "entry_type IN ('grant', 'migration_opening')"
        ),
    )


def _create_postgresql_triggers():
    op.execute(sa.text("""
        CREATE FUNCTION enforce_credit_lot_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION USING
                ERRCODE = '55000',
                MESSAGE = 'credit lots are immutable; append ledger corrections';
        END;
        $$ LANGUAGE plpgsql
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_credit_lots_immutable
        BEFORE UPDATE OR DELETE ON credit_lots
        FOR EACH ROW EXECUTE FUNCTION enforce_credit_lot_immutable()
    """))

    op.execute(sa.text("""
        CREATE FUNCTION enforce_credit_reservation_identity() RETURNS trigger AS $$
        DECLARE
            operation_account VARCHAR(36);
            pricing_state VARCHAR(20);
            registry_fingerprint VARCHAR(64);
        BEGIN
            IF TG_OP = 'INSERT' THEN
                SELECT billing_account_id INTO operation_account
                FROM ai_operations WHERE id = NEW.operation_id;
                IF operation_account IS DISTINCT FROM NEW.billing_account_id THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'reservation operation/account mismatch';
                END IF;

                SELECT state INTO pricing_state
                FROM pricing_policy_versions WHERE id = NEW.pricing_policy_version_id;
                IF pricing_state NOT IN ('approved', 'announced', 'effective') THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'reservation requires an approved pricing policy';
                END IF;

                SELECT request_fingerprint INTO registry_fingerprint
                FROM idempotency_registry WHERE id = NEW.idempotency_registry_id;
                IF registry_fingerprint IS DISTINCT FROM NEW.request_fingerprint THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'reservation/idempotency fingerprint mismatch';
                END IF;
            ELSIF (
                NEW.billing_account_id IS DISTINCT FROM OLD.billing_account_id OR
                NEW.operation_id IS DISTINCT FROM OLD.operation_id OR
                NEW.pricing_policy_version_id IS DISTINCT FROM OLD.pricing_policy_version_id OR
                NEW.capacity_policy_version_id IS DISTINCT FROM OLD.capacity_policy_version_id OR
                NEW.idempotency_registry_id IS DISTINCT FROM OLD.idempotency_registry_id OR
                NEW.request_fingerprint IS DISTINCT FROM OLD.request_fingerprint OR
                NEW.requested_amount IS DISTINCT FROM OLD.requested_amount OR
                NEW.authorized_amount IS DISTINCT FROM OLD.authorized_amount OR
                NEW.created_at IS DISTINCT FROM OLD.created_at
            ) THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'reservation identity and authorization are immutable';
            ELSIF OLD.state IN ('settled', 'released', 'expired') AND
                  NEW.state IS DISTINCT FROM OLD.state THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'terminal reservation state cannot be reopened';
            ELSIF OLD.state = 'partially_settled' AND NEW.state = 'reserved' THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'reservation state transitions are forward-only';
            ELSIF OLD.finalized_at IS NOT NULL AND
                  NEW.finalized_at IS DISTINCT FROM OLD.finalized_at THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'reservation finalization is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_credit_reservations_identity
        BEFORE INSERT OR UPDATE ON credit_reservations
        FOR EACH ROW EXECUTE FUNCTION enforce_credit_reservation_identity()
    """))

    op.execute(sa.text("""
        CREATE FUNCTION enforce_credit_ledger_insert() RETURNS trigger AS $$
        DECLARE
            lot_account VARCHAR(36);
            lot_original BIGINT;
            reservation_account VARCHAR(36);
            reservation_operation VARCHAR(36);
            operation_account VARCHAR(36);
            related_account VARCHAR(36);
            related_lot VARCHAR(36);
            related_type VARCHAR(32);
            related_reservation VARCHAR(36);
            related_operation VARCHAR(36);
            related_held BIGINT;
            reservation_authorized BIGINT;
            reservation_allocated BIGINT;
            allocation_consumed BIGINT;
            allocation_required BOOLEAN;
            allocation_reference_valid BOOLEAN;
            available_total BIGINT;
            held_total BIGINT;
        BEGIN
            -- A no-op row update is the serialization fence. READ COMMITTED
            -- writers wait and then see the committed ledger. Transactions
            -- with an older REPEATABLE READ/SERIALIZABLE snapshot receive
            -- PostgreSQL's 40001 serialization failure instead of committing
            -- a balance calculated from stale rows.
            UPDATE billing_accounts SET id = id
            WHERE id = NEW.billing_account_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23503',
                    MESSAGE = 'ledger billing account does not exist';
            END IF;

            SELECT billing_account_id, original_amount
            INTO lot_account, lot_original
            FROM credit_lots WHERE id = NEW.lot_id FOR UPDATE;
            IF lot_account IS DISTINCT FROM NEW.billing_account_id THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'ledger lot/account mismatch';
            END IF;

            IF NEW.reservation_id IS NOT NULL THEN
                SELECT billing_account_id, operation_id, authorized_amount
                INTO reservation_account, reservation_operation, reservation_authorized
                FROM credit_reservations WHERE id = NEW.reservation_id FOR UPDATE;
                IF reservation_account IS DISTINCT FROM NEW.billing_account_id OR
                   reservation_operation IS DISTINCT FROM NEW.operation_id THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'ledger reservation/account/operation mismatch';
                END IF;
            END IF;

            IF NEW.entry_type = 'reservation' THEN
                SELECT COALESCE(SUM(held_delta), 0)
                INTO reservation_allocated
                FROM credit_ledger_entries
                WHERE reservation_id = NEW.reservation_id
                  AND entry_type = 'reservation';
                IF reservation_allocated + NEW.held_delta > reservation_authorized THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'reservation entries exceed authorized allocation';
                END IF;
            END IF;

            IF NEW.operation_id IS NOT NULL THEN
                SELECT billing_account_id INTO operation_account
                FROM ai_operations WHERE id = NEW.operation_id;
                IF operation_account IS DISTINCT FROM NEW.billing_account_id THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'ledger operation/account mismatch';
                END IF;
            END IF;

            IF NEW.related_entry_id IS NOT NULL THEN
                SELECT billing_account_id, lot_id, entry_type, reservation_id,
                       operation_id, held_delta
                INTO related_account, related_lot, related_type,
                     related_reservation, related_operation, related_held
                FROM credit_ledger_entries
                WHERE id = NEW.related_entry_id FOR UPDATE;
                IF related_account IS DISTINCT FROM NEW.billing_account_id OR
                   related_lot IS DISTINCT FROM NEW.lot_id THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'related ledger entry must share account and lot';
                END IF;
            END IF;

            -- Every movement that reduces held credit uses this single
            -- allocation path. The CASE expression is the transaction policy:
            -- it states which producer entry is eligible without creating a
            -- second balance or provenance rule.
            allocation_required := NEW.held_delta < 0 AND NEW.entry_type IN (
                'settlement', 'release', 'expiration', 'dispute_reversal'
            );
            allocation_reference_valid := CASE
                WHEN NEW.entry_type IN ('settlement', 'release') THEN
                    related_type = 'reservation' AND
                    related_reservation = NEW.reservation_id AND
                    related_operation = NEW.operation_id
                WHEN NEW.entry_type = 'expiration' AND NEW.held_delta < 0 THEN
                    related_type IN ('reservation', 'dispute_hold')
                WHEN NEW.entry_type = 'dispute_reversal' THEN
                    related_type = 'dispute_hold'
                ELSE TRUE
            END;
            IF allocation_required AND
               NOT COALESCE(allocation_reference_valid, FALSE) THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'held movement must reference an eligible allocation';
            END IF;

            IF allocation_required THEN
                SELECT COALESCE(-SUM(held_delta), 0)
                INTO allocation_consumed
                FROM credit_ledger_entries
                WHERE related_entry_id = NEW.related_entry_id
                  AND entry_type IN (
                      'settlement', 'release', 'expiration', 'dispute_reversal'
                  );
                IF allocation_consumed + (-NEW.held_delta) > related_held THEN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'held movement exceeds referenced allocation';
                END IF;
            END IF;

            SELECT COALESCE(SUM(available_delta), 0), COALESCE(SUM(held_delta), 0)
            INTO available_total, held_total
            FROM credit_ledger_entries WHERE lot_id = NEW.lot_id;
            available_total := available_total + NEW.available_delta;
            held_total := held_total + NEW.held_delta;
            IF available_total < 0 OR held_total < 0 THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'credit ledger zero-floor violation';
            END IF;
            IF available_total + held_total > lot_original THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    MESSAGE = 'credit ledger exceeds original lot amount';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_credit_ledger_entries_insert
        BEFORE INSERT ON credit_ledger_entries
        FOR EACH ROW EXECUTE FUNCTION enforce_credit_ledger_insert()
    """))
    op.execute(sa.text("""
        CREATE FUNCTION reject_credit_ledger_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION USING
                ERRCODE = '55000',
                MESSAGE = 'credit ledger entries are append-only';
        END;
        $$ LANGUAGE plpgsql
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_credit_ledger_entries_immutable
        BEFORE UPDATE OR DELETE ON credit_ledger_entries
        FOR EACH ROW EXECUTE FUNCTION reject_credit_ledger_mutation()
    """))


def _create_sqlite_triggers():
    op.execute(sa.text("""
        CREATE TRIGGER trg_credit_lots_update
        BEFORE UPDATE ON credit_lots
        BEGIN
            SELECT RAISE(ABORT, 'credit lots are immutable');
        END
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_credit_lots_delete
        BEFORE DELETE ON credit_lots
        BEGIN
            SELECT RAISE(ABORT, 'credit lots are immutable');
        END
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_credit_reservations_identity_insert
        BEFORE INSERT ON credit_reservations
        BEGIN
            SELECT RAISE(ABORT, 'reservation operation/account mismatch')
            WHERE (SELECT billing_account_id FROM ai_operations WHERE id = NEW.operation_id)
                  IS NOT NEW.billing_account_id;
            SELECT RAISE(ABORT, 'reservation requires an approved pricing policy')
            WHERE COALESCE((SELECT state FROM pricing_policy_versions
                            WHERE id = NEW.pricing_policy_version_id), 'missing')
                  NOT IN ('approved', 'announced', 'effective');
            SELECT RAISE(ABORT, 'reservation/idempotency fingerprint mismatch')
            WHERE (SELECT request_fingerprint FROM idempotency_registry
                   WHERE id = NEW.idempotency_registry_id)
                  IS NOT NEW.request_fingerprint;
        END
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_credit_reservations_identity_update
        BEFORE UPDATE ON credit_reservations
        BEGIN
            SELECT RAISE(ABORT, 'reservation identity and authorization are immutable')
            WHERE NEW.billing_account_id IS NOT OLD.billing_account_id
               OR NEW.operation_id IS NOT OLD.operation_id
               OR NEW.pricing_policy_version_id IS NOT OLD.pricing_policy_version_id
               OR NEW.capacity_policy_version_id IS NOT OLD.capacity_policy_version_id
               OR NEW.idempotency_registry_id IS NOT OLD.idempotency_registry_id
               OR NEW.request_fingerprint IS NOT OLD.request_fingerprint
               OR NEW.requested_amount IS NOT OLD.requested_amount
               OR NEW.authorized_amount IS NOT OLD.authorized_amount
               OR NEW.created_at IS NOT OLD.created_at;
            SELECT RAISE(ABORT, 'terminal reservation state cannot be reopened')
            WHERE OLD.state IN ('settled', 'released', 'expired')
              AND NEW.state IS NOT OLD.state;
            SELECT RAISE(ABORT, 'reservation state transitions are forward-only')
            WHERE OLD.state = 'partially_settled' AND NEW.state = 'reserved';
            SELECT RAISE(ABORT, 'reservation finalization is immutable')
            WHERE OLD.finalized_at IS NOT NULL
              AND NEW.finalized_at IS NOT OLD.finalized_at;
        END
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_credit_ledger_entries_insert
        BEFORE INSERT ON credit_ledger_entries
        BEGIN
            SELECT RAISE(ABORT, 'ledger lot/account mismatch')
            WHERE (SELECT billing_account_id FROM credit_lots WHERE id = NEW.lot_id)
                  IS NOT NEW.billing_account_id;
            SELECT RAISE(ABORT, 'ledger reservation/account/operation mismatch')
            WHERE NEW.reservation_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM credit_reservations
                WHERE id = NEW.reservation_id
                  AND billing_account_id = NEW.billing_account_id
                  AND operation_id = NEW.operation_id
            );
            SELECT RAISE(ABORT, 'reservation entries exceed authorized allocation')
            WHERE NEW.entry_type = 'reservation'
              AND COALESCE((
                    SELECT SUM(held_delta) FROM credit_ledger_entries
                    WHERE reservation_id = NEW.reservation_id
                      AND entry_type = 'reservation'
                  ), 0) + NEW.held_delta > (
                    SELECT authorized_amount FROM credit_reservations
                    WHERE id = NEW.reservation_id
                  );
            SELECT RAISE(ABORT, 'ledger operation/account mismatch')
            WHERE NEW.operation_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM ai_operations
                WHERE id = NEW.operation_id
                  AND billing_account_id = NEW.billing_account_id
            );
            SELECT RAISE(ABORT, 'related ledger entry must share account and lot')
            WHERE NEW.related_entry_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM credit_ledger_entries
                WHERE id = NEW.related_entry_id
                  AND billing_account_id = NEW.billing_account_id
                  AND lot_id = NEW.lot_id
            );
            -- One eligibility map and one cumulative cap govern every held
            -- movement. Transaction types differ only in which allocation
            -- producer they may reference.
            SELECT RAISE(ABORT, 'held movement must reference an eligible allocation')
            WHERE NEW.held_delta < 0
              AND NEW.entry_type IN (
                  'settlement', 'release', 'expiration', 'dispute_reversal'
              )
              AND NOT EXISTS (
                SELECT 1 FROM credit_ledger_entries
                WHERE id = NEW.related_entry_id
                  AND (
                    (NEW.entry_type IN ('settlement', 'release')
                     AND entry_type = 'reservation'
                     AND reservation_id = NEW.reservation_id
                     AND operation_id = NEW.operation_id)
                    OR (NEW.entry_type = 'expiration'
                        AND entry_type IN ('reservation', 'dispute_hold'))
                    OR (NEW.entry_type = 'dispute_reversal'
                        AND entry_type = 'dispute_hold')
                  )
            );
            SELECT RAISE(ABORT, 'held movement exceeds referenced allocation')
            WHERE NEW.held_delta < 0
              AND NEW.entry_type IN (
                  'settlement', 'release', 'expiration', 'dispute_reversal'
              )
              AND COALESCE((
                    SELECT -SUM(held_delta) FROM credit_ledger_entries
                    WHERE related_entry_id = NEW.related_entry_id
                      AND entry_type IN (
                          'settlement', 'release', 'expiration', 'dispute_reversal'
                      )
                  ), 0) + (-NEW.held_delta) > (
                    SELECT held_delta FROM credit_ledger_entries
                    WHERE id = NEW.related_entry_id
                  );
            SELECT RAISE(ABORT, 'credit ledger zero-floor violation')
            WHERE COALESCE((SELECT SUM(available_delta) FROM credit_ledger_entries
                            WHERE lot_id = NEW.lot_id), 0) + NEW.available_delta < 0
               OR COALESCE((SELECT SUM(held_delta) FROM credit_ledger_entries
                            WHERE lot_id = NEW.lot_id), 0) + NEW.held_delta < 0;
            SELECT RAISE(ABORT, 'credit ledger exceeds original lot amount')
            WHERE COALESCE((SELECT SUM(available_delta + held_delta)
                            FROM credit_ledger_entries WHERE lot_id = NEW.lot_id), 0)
                  + NEW.available_delta + NEW.held_delta
                  > (SELECT original_amount FROM credit_lots WHERE id = NEW.lot_id);
        END
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_credit_ledger_entries_update
        BEFORE UPDATE ON credit_ledger_entries
        BEGIN
            SELECT RAISE(ABORT, 'credit ledger entries are append-only');
        END
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_credit_ledger_entries_delete
        BEFORE DELETE ON credit_ledger_entries
        BEGIN
            SELECT RAISE(ABORT, 'credit ledger entries are append-only');
        END
    """))


def upgrade():
    _create_tables()
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        _create_postgresql_triggers()
    elif dialect == "sqlite":
        _create_sqlite_triggers()


def _drop_triggers(dialect):
    if dialect == "postgresql":
        op.execute(sa.text(
            "DROP TRIGGER IF EXISTS trg_credit_ledger_entries_immutable "
            "ON credit_ledger_entries"
        ))
        op.execute(sa.text(
            "DROP TRIGGER IF EXISTS trg_credit_ledger_entries_insert "
            "ON credit_ledger_entries"
        ))
        op.execute(sa.text(
            "DROP TRIGGER IF EXISTS trg_credit_reservations_identity "
            "ON credit_reservations"
        ))
        op.execute(sa.text(
            "DROP TRIGGER IF EXISTS trg_credit_lots_immutable ON credit_lots"
        ))
        op.execute(sa.text("DROP FUNCTION IF EXISTS reject_credit_ledger_mutation()"))
        op.execute(sa.text("DROP FUNCTION IF EXISTS enforce_credit_ledger_insert()"))
        op.execute(sa.text("DROP FUNCTION IF EXISTS enforce_credit_reservation_identity()"))
        op.execute(sa.text("DROP FUNCTION IF EXISTS enforce_credit_lot_immutable()"))
    elif dialect == "sqlite":
        for trigger in (
            "trg_credit_ledger_entries_delete",
            "trg_credit_ledger_entries_update",
            "trg_credit_ledger_entries_insert",
            "trg_credit_reservations_identity_update",
            "trg_credit_reservations_identity_insert",
            "trg_credit_lots_delete",
            "trg_credit_lots_update",
        ):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger}"))


def downgrade():
    """Drop the Phase 3 foundation only while every new table is empty."""
    bind = op.get_bind()
    counts = {
        table: bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
        for table in LEDGER_TABLES
    }
    if any(counts.values()):
        details = ", ".join(f"{table}={count}" for table, count in counts.items())
        raise CreditLedgerNotEmptyError(
            f"Cannot downgrade {revision}: {details}. Phase 3 downgrade may "
            "remove only empty ledger tables."
        )

    _drop_triggers(bind.dialect.name)
    op.drop_table("credit_ledger_entries")

    op.drop_index(
        "ix_credit_reservations_capacity_policy_version_id",
        table_name="credit_reservations",
    )
    op.drop_index(
        "ix_credit_reservations_pricing_policy_version_id",
        table_name="credit_reservations",
    )
    op.drop_index(
        "ix_credit_reservations_account_state_expiry",
        table_name="credit_reservations",
    )
    op.drop_table("credit_reservations")

    op.drop_index(
        "ix_credit_lots_member_attribution_id",
        table_name="credit_lots",
    )
    op.drop_index(
        "ix_credit_lots_account_allocation_order",
        table_name="credit_lots",
    )
    op.drop_table("credit_lots")
