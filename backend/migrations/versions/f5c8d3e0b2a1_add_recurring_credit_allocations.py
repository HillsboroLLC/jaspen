"""Add inactive Phase 6 free and subscription recurring allocations.

Revision ID: f5c8d3e0b2a1
Revises: e4b7c2d9a1f0
"""

from alembic import op
import sqlalchemy as sa


revision = "f5c8d3e0b2a1"
down_revision = "e4b7c2d9a1f0"
branch_labels = None
depends_on = None


class RecurringAllocationsNotEmptyError(RuntimeError):
    """Raised when downgrade would discard Phase 6 allocation evidence."""


def _create_table():
    op.create_table(
        "recurring_credit_allocations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("billing_account_id", sa.String(36), nullable=False),
        sa.Column("credit_period_id", sa.String(36), nullable=False),
        sa.Column("entitlement_instance_id", sa.String(36), nullable=False),
        sa.Column("entitlement_definition_id", sa.String(36), nullable=False),
        sa.Column("subscription_id", sa.String(36), nullable=True),
        sa.Column("financial_line_id", sa.String(36), nullable=True),
        sa.Column("idempotency_registry_id", sa.String(36), nullable=False),
        sa.Column("domain_event_id", sa.String(36), nullable=False),
        sa.Column("allocation_key", sa.String(512), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("period_kind", sa.String(32), nullable=False),
        sa.Column("period_index", sa.Integer(), nullable=False),
        sa.Column("period_starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("credit_amount", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "period_kind IN ('free','monthly_subscription','annual_monthly')",
            name="ck_recurring_credit_allocations_kind",
        ),
        sa.CheckConstraint(
            "period_index >= 0 AND credit_amount > 0 "
            "AND period_ends_at > period_starts_at",
            name="ck_recurring_credit_allocations_values",
        ),
        sa.CheckConstraint(
            "length(trim(allocation_key)) > 0 "
            "AND length(request_fingerprint) = 64 "
            "AND request_fingerprint = lower(request_fingerprint)",
            name="ck_recurring_credit_allocations_identity",
        ),
        sa.CheckConstraint(
            "(period_kind = 'free' AND subscription_id IS NULL "
            "AND financial_line_id IS NULL) OR "
            "(period_kind IN ('monthly_subscription','annual_monthly') "
            "AND subscription_id IS NOT NULL AND financial_line_id IS NOT NULL)",
            name="ck_recurring_credit_allocations_evidence_shape",
        ),
        sa.ForeignKeyConstraint(
            ["billing_account_id"], ["billing_accounts.id"],
            name="fk_recurring_credit_allocations_billing_account_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["credit_period_id"], ["credit_periods.id"],
            name="fk_recurring_credit_allocations_credit_period_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["entitlement_instance_id"], ["entitlement_instances.id"],
            name="fk_recurring_credit_allocations_entitlement_instance_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["entitlement_definition_id"], ["entitlement_definitions.id"],
            name="fk_recurring_credit_allocations_entitlement_definition_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["billing_subscriptions.id"],
            name="fk_recurring_credit_allocations_subscription_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["financial_line_id"], ["financial_lines.id"],
            name="fk_recurring_credit_allocations_financial_line_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["idempotency_registry_id"], ["idempotency_registry.id"],
            name="fk_recurring_credit_allocations_idempotency_registry_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["domain_event_id"], ["domain_events.id"],
            name="fk_recurring_credit_allocations_domain_event_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_recurring_credit_allocations"),
        sa.UniqueConstraint(
            "credit_period_id", name="uq_recurring_credit_allocations_period_id",
        ),
        sa.UniqueConstraint(
            "idempotency_registry_id",
            name="uq_recurring_credit_allocations_idempotency_registry_id",
        ),
        sa.UniqueConstraint(
            "domain_event_id",
            name="uq_recurring_credit_allocations_domain_event_id",
        ),
        sa.UniqueConstraint(
            "allocation_key", name="uq_recurring_credit_allocations_key",
        ),
    )
    op.create_index(
        "ix_recurring_credit_allocations_account_start",
        "recurring_credit_allocations",
        ["billing_account_id", "period_starts_at", "id"],
    )
    op.create_index(
        "ix_recurring_credit_allocations_financial_line_id",
        "recurring_credit_allocations", ["financial_line_id"],
    )


def _postgresql_triggers():
    op.execute("""
    CREATE FUNCTION phase6_allocation_guard() RETURNS trigger AS $$
    DECLARE
      expected_key text;
      period_row credit_periods%ROWTYPE;
      instance_row entitlement_instances%ROWTYPE;
      definition_row entitlement_definitions%ROWTYPE;
      subscription_row billing_subscriptions%ROWTYPE;
      financial_line_row financial_lines%ROWTYPE;
      financial_row financial_transactions%ROWTYPE;
      domain_event_row domain_events%ROWTYPE;
    BEGIN
      IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'recurring credit allocation evidence is immutable';
      END IF;
      SELECT * INTO period_row FROM credit_periods WHERE id=NEW.credit_period_id;
      SELECT * INTO instance_row FROM entitlement_instances
        WHERE id=NEW.entitlement_instance_id;
      SELECT * INTO definition_row FROM entitlement_definitions
        WHERE id=NEW.entitlement_definition_id;
      SELECT * INTO domain_event_row FROM domain_events
        WHERE id=NEW.domain_event_id;
      IF period_row.id IS NULL OR instance_row.id IS NULL OR definition_row.id IS NULL
        OR period_row.state <> 'planned'
        OR period_row.billing_account_id <> NEW.billing_account_id
        OR period_row.entitlement_instance_id <> NEW.entitlement_instance_id
        OR period_row.subscription_id IS DISTINCT FROM NEW.subscription_id
        OR period_row.kind <> NEW.period_kind
        OR period_row.period_index <> NEW.period_index
        OR period_row.starts_at <> NEW.period_starts_at
        OR period_row.ends_at <> NEW.period_ends_at
        OR period_row.planned_allocation_amount <> NEW.credit_amount
        OR instance_row.billing_account_id <> NEW.billing_account_id
        OR instance_row.entitlement_definition_id <> NEW.entitlement_definition_id
        OR instance_row.subscription_id IS DISTINCT FROM NEW.subscription_id
        OR instance_row.state <> 'active'
        OR instance_row.starts_at > NEW.period_starts_at
        OR (instance_row.ends_at IS NOT NULL AND instance_row.ends_at < NEW.period_ends_at)
        OR definition_row.approved_at IS NULL
        OR definition_row.approval_evidence_reference IS NULL
        OR definition_row.effective_at IS NULL
        OR definition_row.effective_at > NEW.period_starts_at
        OR (definition_row.retired_at IS NOT NULL
            AND definition_row.retired_at <= NEW.period_starts_at)
        OR (definition_row.funding_policy_json::jsonb->>'credit_amount')::bigint <> NEW.credit_amount
        OR definition_row.funding_policy_json::jsonb->>'period_kind' <> NEW.period_kind
        OR NOT EXISTS (
          SELECT 1 FROM idempotency_registry registry
          WHERE registry.id=NEW.idempotency_registry_id
            AND registry.namespace='recurring_credit_allocation'
            AND registry.key=NEW.allocation_key
            AND registry.request_fingerprint=NEW.request_fingerprint
            AND registry.state='claimed'
        )
        OR domain_event_row.id IS NULL
        OR domain_event_row.billing_account_id <> NEW.billing_account_id
        OR domain_event_row.event_key <> 'credit_period_funded:' || NEW.credit_period_id
        OR domain_event_row.event_type <> 'credit_period_funded'
        OR domain_event_row.aggregate_type <> 'credit_period'
        OR domain_event_row.aggregate_id <> NEW.credit_period_id
        OR NOT (domain_event_row.reference_ids_json::jsonb @> jsonb_build_array(NEW.id))
        OR NOT (domain_event_row.reference_ids_json::jsonb @> jsonb_build_array(NEW.credit_period_id))
        OR NOT EXISTS (
          SELECT 1 FROM communication_outbox message
          WHERE message.domain_event_id=domain_event_row.id
            AND message.billing_account_id=NEW.billing_account_id
        ) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
          MESSAGE='recurring allocation does not match its period, entitlement, or claim';
      END IF;
      IF NEW.period_kind='free' THEN
        expected_key := 'period:free:' || NEW.billing_account_id || ':' ||
          to_char(NEW.period_starts_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS"Z"');
        IF instance_row.source_type <> 'free'
          OR NEW.subscription_id IS NOT NULL OR NEW.financial_line_id IS NOT NULL
          OR NOT EXISTS (
            SELECT 1 FROM billing_accounts account
            WHERE account.id=NEW.billing_account_id
              AND account.account_anchor_at=period_row.anchor_at
          ) THEN
          RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='free allocation does not match its organization anchor';
        END IF;
      ELSE
        SELECT * INTO subscription_row FROM billing_subscriptions
          WHERE id=NEW.subscription_id;
        SELECT * INTO financial_line_row FROM financial_lines
          WHERE id=NEW.financial_line_id;
        SELECT * INTO financial_row FROM financial_transactions
          WHERE id=financial_line_row.financial_transaction_id;
        IF subscription_row.id IS NULL OR financial_line_row.id IS NULL
          OR financial_row.id IS NULL
          OR instance_row.source_type <> 'subscription'
          OR subscription_row.billing_account_id <> NEW.billing_account_id
          OR subscription_row.current_entitlement_definition_id <> NEW.entitlement_definition_id
          OR subscription_row.anchor_at <> period_row.anchor_at
          OR subscription_row.term_starts_at > NEW.period_starts_at
          OR subscription_row.term_ends_at < NEW.period_ends_at
          OR (NEW.period_kind='monthly_subscription' AND subscription_row.interval <> 'month')
          OR (NEW.period_kind='annual_monthly' AND subscription_row.interval <> 'year')
          OR financial_row.billing_account_id <> NEW.billing_account_id
          OR financial_row.kind <> 'payment'
          OR financial_row.currency <> (SELECT currency FROM billing_accounts WHERE id=NEW.billing_account_id)
          OR financial_row.principal_minor <= 0
          OR financial_line_row.line_kind <> 'subscription'
          OR financial_line_row.principal_minor <= 0
          OR financial_line_row.currency <> financial_row.currency
          OR financial_line_row.subscription_id <> NEW.subscription_id
          OR financial_line_row.entitlement_instance_id <> NEW.entitlement_instance_id
          OR (NEW.period_kind='monthly_subscription' AND NOT (
            financial_row.effective_at >= NEW.period_starts_at
            AND financial_row.effective_at < NEW.period_ends_at))
          OR (NEW.period_kind='annual_monthly' AND NOT (
            financial_row.effective_at >= subscription_row.term_starts_at
            AND financial_row.effective_at < subscription_row.term_ends_at)) THEN
          RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='subscription allocation lacks matching paid line evidence';
        END IF;
        IF NEW.period_kind='annual_monthly' THEN
          expected_key := 'period:annual:' || NEW.subscription_id || ':' ||
            NEW.period_index::text || ':' ||
            to_char(NEW.period_starts_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS"Z"');
        ELSE
          expected_key := 'period:subscription:' || NEW.subscription_id || ':' ||
            to_char(NEW.period_starts_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS"Z"') || ':' ||
            definition_row.key || '@' || definition_row.version::text;
        END IF;
      END IF;
      IF NEW.allocation_key <> expected_key THEN
        RAISE EXCEPTION USING ERRCODE='23514',
          MESSAGE='recurring allocation key is not canonical';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """)
    op.execute("""
    CREATE TRIGGER trg_phase6_allocation_guard
    BEFORE INSERT OR UPDATE OR DELETE ON recurring_credit_allocations
    FOR EACH ROW EXECUTE FUNCTION phase6_allocation_guard()
    """)
    op.execute("""
    CREATE FUNCTION phase6_period_guard() RETURNS trigger AS $$
    DECLARE
      available_total bigint;
      held_total bigint;
    BEGIN
      IF NEW.state='funded' AND OLD.state <> 'funded'
        AND NEW.kind IN ('free','monthly_subscription','annual_monthly')
        AND NOT EXISTS (
          SELECT 1 FROM recurring_credit_allocations allocation
          WHERE allocation.credit_period_id=NEW.id
            AND allocation.idempotency_registry_id=NEW.funding_idempotency_registry_id
        ) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
          MESSAGE='recurring period funding requires immutable Phase 6 allocation evidence';
      END IF;
      IF NEW.state='expired' AND OLD.state='funded'
        AND EXISTS (
          SELECT 1 FROM recurring_credit_allocations allocation
          WHERE allocation.credit_period_id=NEW.id
        ) THEN
        IF CURRENT_TIMESTAMP < OLD.ends_at THEN
          RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='recurring period cannot expire before its end';
        END IF;
        SELECT COALESCE(sum(available_delta),0), COALESCE(sum(held_delta),0)
          INTO available_total, held_total
          FROM credit_ledger_entries WHERE lot_id=OLD.funded_lot_id;
        IF available_total <> 0 OR held_total <> 0 THEN
          RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='recurring period cannot expire with ledger value remaining';
        END IF;
        IF NOT EXISTS (
          SELECT 1 FROM domain_events event
          WHERE event.billing_account_id=NEW.billing_account_id
            AND event.event_key='credits_expired:' || NEW.id
            AND event.event_type='credits_expired'
            AND event.aggregate_type='credit_period'
            AND event.aggregate_id=NEW.id
            AND event.reference_ids_json::jsonb @> jsonb_build_array(NEW.id)
            AND event.reference_ids_json::jsonb @> jsonb_build_array(OLD.funded_lot_id)
            AND EXISTS (
              SELECT 1 FROM recurring_credit_allocations allocation
              WHERE allocation.credit_period_id=NEW.id
                AND event.reference_ids_json::jsonb @> jsonb_build_array(allocation.id)
            )
            AND EXISTS (
              SELECT 1 FROM communication_outbox message
              WHERE message.domain_event_id=event.id
                AND message.billing_account_id=NEW.billing_account_id
            )
        ) THEN
          RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='recurring period expiration requires atomic event obligations';
        END IF;
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """)
    op.execute("""
    CREATE TRIGGER trg_phase6_period_guard
    BEFORE UPDATE ON credit_periods
    FOR EACH ROW EXECUTE FUNCTION phase6_period_guard()
    """)
    op.execute("""
    CREATE FUNCTION phase6_recurring_lot_guard() RETURNS trigger AS $$
    BEGIN
      IF NEW.source_type NOT IN ('free_recurring','subscription_recurring') THEN
        RETURN NEW;
      END IF;
      IF NOT EXISTS (
        SELECT 1 FROM credit_periods period
        JOIN recurring_credit_allocations allocation
          ON allocation.credit_period_id=period.id
        JOIN domain_events event ON event.id=allocation.domain_event_id
        WHERE period.id=NEW.source_id
          AND period.state='planned'
          AND period.billing_account_id=NEW.billing_account_id
          AND period.planned_allocation_amount=NEW.original_amount
          AND period.starts_at=NEW.available_at
          AND period.ends_at=NEW.expires_at
          AND ((period.kind='free' AND NEW.source_type='free_recurring') OR
               (period.kind IN ('monthly_subscription','annual_monthly')
                AND NEW.source_type='subscription_recurring'))
          AND event.billing_account_id=NEW.billing_account_id
          AND event.event_type='credit_period_funded'
          AND event.aggregate_type='credit_period'
          AND event.aggregate_id=period.id
          AND EXISTS (
            SELECT 1 FROM communication_outbox message
            WHERE message.domain_event_id=event.id
              AND message.billing_account_id=NEW.billing_account_id
          )
      ) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
          MESSAGE='recurring lot requires Phase 6 allocation and communication evidence';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """)
    op.execute("""
    CREATE TRIGGER trg_phase6_recurring_lot_guard
    BEFORE INSERT ON credit_lots
    FOR EACH ROW EXECUTE FUNCTION phase6_recurring_lot_guard()
    """)
    op.execute("""
    CREATE FUNCTION phase6_recurring_entry_guard() RETURNS trigger AS $$
    DECLARE
      lot_row credit_lots%ROWTYPE;
    BEGIN
      SELECT * INTO lot_row FROM credit_lots WHERE id=NEW.lot_id;
      IF lot_row.source_type NOT IN ('free_recurring','subscription_recurring') THEN
        RETURN NEW;
      END IF;
      IF NEW.entry_type='grant' AND NOT EXISTS (
        SELECT 1 FROM credit_periods period
        JOIN recurring_credit_allocations allocation
          ON allocation.credit_period_id=period.id
        JOIN domain_events event ON event.id=allocation.domain_event_id
        WHERE period.id=lot_row.source_id
          AND period.billing_account_id=NEW.billing_account_id
          AND allocation.idempotency_registry_id=NEW.idempotency_registry_id
          AND event.event_type='credit_period_funded'
          AND event.aggregate_id=period.id
          AND EXISTS (
            SELECT 1 FROM communication_outbox message
            WHERE message.domain_event_id=event.id
              AND message.billing_account_id=NEW.billing_account_id
          )
      ) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
          MESSAGE='recurring grant requires Phase 6 allocation and communication evidence';
      END IF;
      IF NEW.entry_type='expiration' AND NOT EXISTS (
        SELECT 1 FROM domain_events event
        WHERE event.billing_account_id=NEW.billing_account_id
          AND event.event_key='credits_expired:' || lot_row.source_id
          AND event.event_type='credits_expired'
          AND event.aggregate_type='credit_period'
          AND event.aggregate_id=lot_row.source_id
          AND EXISTS (
            SELECT 1 FROM communication_outbox message
            WHERE message.domain_event_id=event.id
              AND message.billing_account_id=NEW.billing_account_id
          )
      ) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
          MESSAGE='recurring expiration requires Phase 6 communication evidence';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """)
    op.execute("""
    CREATE TRIGGER trg_phase6_recurring_entry_guard
    BEFORE INSERT ON credit_ledger_entries
    FOR EACH ROW EXECUTE FUNCTION phase6_recurring_entry_guard()
    """)
    op.execute("""
    CREATE FUNCTION phase6_recurring_effect_final_guard() RETURNS trigger AS $$
    DECLARE
      lot_row credit_lots%ROWTYPE;
      period_row credit_periods%ROWTYPE;
      available_total bigint;
      held_total bigint;
    BEGIN
      IF TG_TABLE_NAME='credit_lots' THEN
        lot_row := NEW;
      ELSE
        SELECT * INTO lot_row FROM credit_lots WHERE id=NEW.lot_id;
      END IF;
      IF lot_row.source_type NOT IN ('free_recurring','subscription_recurring') THEN
        RETURN NEW;
      END IF;
      SELECT * INTO period_row FROM credit_periods WHERE id=lot_row.source_id;
      IF TG_TABLE_NAME='credit_lots' THEN
        IF period_row.state <> 'funded'
          OR period_row.funded_lot_id <> lot_row.id
          OR NOT EXISTS (
            SELECT 1 FROM credit_ledger_entries entry
            JOIN recurring_credit_allocations allocation
              ON allocation.credit_period_id=period_row.id
            WHERE entry.lot_id=lot_row.id AND entry.entry_type='grant'
              AND entry.idempotency_registry_id=allocation.idempotency_registry_id
          ) THEN
          RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='recurring funding transaction is incomplete';
        END IF;
      ELSIF NEW.entry_type='expiration' THEN
        SELECT COALESCE(sum(available_delta),0), COALESCE(sum(held_delta),0)
          INTO available_total, held_total
          FROM credit_ledger_entries WHERE lot_id=lot_row.id;
        IF period_row.state <> 'expired'
          OR available_total <> 0 OR held_total <> 0 THEN
          RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='recurring expiration transaction is incomplete';
        END IF;
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """)
    op.execute("""
    CREATE CONSTRAINT TRIGGER trg_phase6_recurring_lot_final
    AFTER INSERT ON credit_lots
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION phase6_recurring_effect_final_guard()
    """)
    op.execute("""
    CREATE CONSTRAINT TRIGGER trg_phase6_recurring_expiration_final
    AFTER INSERT ON credit_ledger_entries
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW WHEN (NEW.entry_type='expiration')
    EXECUTE FUNCTION phase6_recurring_effect_final_guard()
    """)
    op.execute("""
    CREATE FUNCTION phase6_reject_truncate() RETURNS trigger AS $$
    BEGIN
      RAISE EXCEPTION USING ERRCODE='23514',
        MESSAGE='Phase 6 recurring allocation evidence cannot be truncated';
    END;
    $$ LANGUAGE plpgsql
    """)
    op.execute("""
    CREATE TRIGGER trg_phase6_allocation_no_truncate
    BEFORE TRUNCATE ON recurring_credit_allocations
    FOR EACH STATEMENT EXECUTE FUNCTION phase6_reject_truncate()
    """)


def _sqlite_triggers():
    op.execute("""
    CREATE TRIGGER trg_phase6_allocation_insert
    BEFORE INSERT ON recurring_credit_allocations
    BEGIN
      SELECT RAISE(ABORT,'recurring allocation does not match its period, entitlement, or claim')
      WHERE NOT EXISTS (
        SELECT 1 FROM credit_periods period
        JOIN entitlement_instances instance ON instance.id=NEW.entitlement_instance_id
        JOIN entitlement_definitions definition ON definition.id=NEW.entitlement_definition_id
        JOIN idempotency_registry registry ON registry.id=NEW.idempotency_registry_id
        JOIN domain_events event ON event.id=NEW.domain_event_id
        WHERE period.id=NEW.credit_period_id AND period.state='planned'
          AND period.billing_account_id=NEW.billing_account_id
          AND period.entitlement_instance_id=NEW.entitlement_instance_id
          AND period.subscription_id IS NEW.subscription_id
          AND period.kind=NEW.period_kind AND period.period_index=NEW.period_index
          AND julianday(period.starts_at)=julianday(NEW.period_starts_at)
          AND julianday(period.ends_at)=julianday(NEW.period_ends_at)
          AND period.planned_allocation_amount=NEW.credit_amount
          AND instance.billing_account_id=NEW.billing_account_id
          AND instance.entitlement_definition_id=NEW.entitlement_definition_id
          AND instance.subscription_id IS NEW.subscription_id AND instance.state='active'
          AND julianday(instance.starts_at)<=julianday(NEW.period_starts_at)
          AND (instance.ends_at IS NULL
            OR julianday(instance.ends_at)>=julianday(NEW.period_ends_at))
          AND definition.approved_at IS NOT NULL
          AND definition.approval_evidence_reference IS NOT NULL
          AND definition.effective_at IS NOT NULL
          AND julianday(definition.effective_at)<=julianday(NEW.period_starts_at)
          AND (definition.retired_at IS NULL
            OR julianday(definition.retired_at)>julianday(NEW.period_starts_at))
          AND json_extract(definition.funding_policy_json,'$.credit_amount')=NEW.credit_amount
          AND json_extract(definition.funding_policy_json,'$.period_kind')=NEW.period_kind
          AND registry.namespace='recurring_credit_allocation'
          AND registry.key=NEW.allocation_key
          AND registry.request_fingerprint=NEW.request_fingerprint
          AND registry.state='claimed'
          AND event.billing_account_id=NEW.billing_account_id
          AND event.event_key='credit_period_funded:' || NEW.credit_period_id
          AND event.event_type='credit_period_funded'
          AND event.aggregate_type='credit_period'
          AND event.aggregate_id=NEW.credit_period_id
          AND EXISTS (
            SELECT 1 FROM json_each(event.reference_ids_json)
            WHERE value=NEW.id
          )
          AND EXISTS (
            SELECT 1 FROM json_each(event.reference_ids_json)
            WHERE value=NEW.credit_period_id
          )
          AND EXISTS (
            SELECT 1 FROM communication_outbox message
            WHERE message.domain_event_id=event.id
              AND message.billing_account_id=NEW.billing_account_id
          )
      );
      SELECT RAISE(ABORT,'free allocation does not match its organization anchor')
      WHERE NEW.period_kind='free' AND NOT EXISTS (
        SELECT 1 FROM credit_periods period
        JOIN entitlement_instances instance ON instance.id=NEW.entitlement_instance_id
        JOIN billing_accounts account ON account.id=NEW.billing_account_id
        WHERE period.id=NEW.credit_period_id AND instance.source_type='free'
          AND NEW.subscription_id IS NULL AND NEW.financial_line_id IS NULL
          AND julianday(account.account_anchor_at)=julianday(period.anchor_at)
          AND NEW.allocation_key='period:free:' || NEW.billing_account_id || ':' ||
            strftime('%Y-%m-%dT%H:%M:%SZ',NEW.period_starts_at)
      );
      SELECT RAISE(ABORT,'subscription allocation lacks matching paid line evidence')
      WHERE NEW.period_kind IN ('monthly_subscription','annual_monthly') AND NOT EXISTS (
        SELECT 1 FROM credit_periods period
        JOIN entitlement_instances instance ON instance.id=NEW.entitlement_instance_id
        JOIN entitlement_definitions definition ON definition.id=NEW.entitlement_definition_id
        JOIN billing_subscriptions subscription ON subscription.id=NEW.subscription_id
        JOIN financial_lines line ON line.id=NEW.financial_line_id
        JOIN financial_transactions financial ON financial.id=line.financial_transaction_id
        JOIN billing_accounts account ON account.id=NEW.billing_account_id
        WHERE period.id=NEW.credit_period_id AND instance.source_type='subscription'
          AND subscription.billing_account_id=NEW.billing_account_id
          AND subscription.current_entitlement_definition_id=NEW.entitlement_definition_id
          AND julianday(subscription.anchor_at)=julianday(period.anchor_at)
          AND julianday(subscription.term_starts_at)<=julianday(NEW.period_starts_at)
          AND julianday(subscription.term_ends_at)>=julianday(NEW.period_ends_at)
          AND ((NEW.period_kind='monthly_subscription' AND subscription.interval='month')
            OR (NEW.period_kind='annual_monthly' AND subscription.interval='year'))
          AND financial.billing_account_id=NEW.billing_account_id
          AND financial.kind='payment' AND financial.currency=account.currency
          AND financial.principal_minor>0 AND line.line_kind='subscription'
          AND line.principal_minor>0 AND line.currency=financial.currency
          AND line.subscription_id=NEW.subscription_id
          AND line.entitlement_instance_id=NEW.entitlement_instance_id
          AND ((NEW.period_kind='monthly_subscription'
              AND julianday(financial.effective_at)>=julianday(NEW.period_starts_at)
              AND julianday(financial.effective_at)<julianday(NEW.period_ends_at))
            OR (NEW.period_kind='annual_monthly'
              AND julianday(financial.effective_at)>=julianday(subscription.term_starts_at)
              AND julianday(financial.effective_at)<julianday(subscription.term_ends_at)))
          AND NEW.allocation_key=CASE WHEN NEW.period_kind='annual_monthly' THEN
            'period:annual:' || NEW.subscription_id || ':' || NEW.period_index || ':' ||
              strftime('%Y-%m-%dT%H:%M:%SZ',NEW.period_starts_at)
            ELSE 'period:subscription:' || NEW.subscription_id || ':' ||
              strftime('%Y-%m-%dT%H:%M:%SZ',NEW.period_starts_at) || ':' ||
              definition.key || '@' || definition.version END
      );
    END
    """)
    op.execute("""
    CREATE TRIGGER trg_phase6_allocation_update
    BEFORE UPDATE ON recurring_credit_allocations
    BEGIN SELECT RAISE(ABORT,'recurring credit allocation evidence is immutable'); END
    """)
    op.execute("""
    CREATE TRIGGER trg_phase6_allocation_delete
    BEFORE DELETE ON recurring_credit_allocations
    BEGIN SELECT RAISE(ABORT,'recurring credit allocation evidence is immutable'); END
    """)
    op.execute("""
    CREATE TRIGGER trg_phase6_recurring_lot_insert
    BEFORE INSERT ON credit_lots
    WHEN NEW.source_type IN ('free_recurring','subscription_recurring')
    BEGIN
      SELECT RAISE(ABORT,'recurring lot requires Phase 6 allocation and communication evidence')
      WHERE NOT EXISTS (
        SELECT 1 FROM credit_periods period
        JOIN recurring_credit_allocations allocation
          ON allocation.credit_period_id=period.id
        JOIN domain_events event ON event.id=allocation.domain_event_id
        WHERE period.id=NEW.source_id AND period.state='planned'
          AND period.billing_account_id=NEW.billing_account_id
          AND period.planned_allocation_amount=NEW.original_amount
          AND julianday(period.starts_at)=julianday(NEW.available_at)
          AND julianday(period.ends_at)=julianday(NEW.expires_at)
          AND ((period.kind='free' AND NEW.source_type='free_recurring') OR
               (period.kind IN ('monthly_subscription','annual_monthly')
                AND NEW.source_type='subscription_recurring'))
          AND event.billing_account_id=NEW.billing_account_id
          AND event.event_type='credit_period_funded'
          AND event.aggregate_id=period.id
          AND EXISTS (
            SELECT 1 FROM communication_outbox message
            WHERE message.domain_event_id=event.id
              AND message.billing_account_id=NEW.billing_account_id
          )
      );
    END
    """)
    op.execute("""
    CREATE TRIGGER trg_phase6_recurring_entry_insert
    BEFORE INSERT ON credit_ledger_entries
    WHEN (SELECT source_type FROM credit_lots WHERE id=NEW.lot_id)
      IN ('free_recurring','subscription_recurring')
    BEGIN
      SELECT RAISE(ABORT,'recurring grant requires Phase 6 allocation and communication evidence')
      WHERE NEW.entry_type='grant' AND NOT EXISTS (
        SELECT 1 FROM credit_lots lot
        JOIN credit_periods period ON period.id=lot.source_id
        JOIN recurring_credit_allocations allocation
          ON allocation.credit_period_id=period.id
        JOIN domain_events event ON event.id=allocation.domain_event_id
        WHERE lot.id=NEW.lot_id
          AND period.billing_account_id=NEW.billing_account_id
          AND allocation.idempotency_registry_id=NEW.idempotency_registry_id
          AND event.event_type='credit_period_funded'
          AND event.aggregate_id=period.id
          AND EXISTS (
            SELECT 1 FROM communication_outbox message
            WHERE message.domain_event_id=event.id
              AND message.billing_account_id=NEW.billing_account_id
          )
      );
      SELECT RAISE(ABORT,'recurring expiration requires Phase 6 communication evidence')
      WHERE NEW.entry_type='expiration' AND NOT EXISTS (
        SELECT 1 FROM credit_lots lot
        JOIN domain_events event
          ON event.event_key='credits_expired:' || lot.source_id
        WHERE lot.id=NEW.lot_id
          AND event.billing_account_id=NEW.billing_account_id
          AND event.event_type='credits_expired'
          AND event.aggregate_type='credit_period'
          AND event.aggregate_id=lot.source_id
          AND EXISTS (
            SELECT 1 FROM communication_outbox message
            WHERE message.domain_event_id=event.id
              AND message.billing_account_id=NEW.billing_account_id
          )
      );
    END
    """)
    op.execute("""
    CREATE TRIGGER trg_phase6_period_update
    BEFORE UPDATE ON credit_periods
    BEGIN
      SELECT RAISE(ABORT,'recurring period funding requires immutable Phase 6 allocation evidence')
      WHERE NEW.state='funded' AND OLD.state<>'funded'
        AND NEW.kind IN ('free','monthly_subscription','annual_monthly')
        AND NOT EXISTS (
          SELECT 1 FROM recurring_credit_allocations allocation
          WHERE allocation.credit_period_id=NEW.id
            AND allocation.idempotency_registry_id=NEW.funding_idempotency_registry_id
        );
      SELECT RAISE(ABORT,'recurring period cannot expire before its end')
      WHERE NEW.state='expired' AND OLD.state='funded'
        AND EXISTS (SELECT 1 FROM recurring_credit_allocations WHERE credit_period_id=NEW.id)
        AND julianday(CURRENT_TIMESTAMP)<julianday(OLD.ends_at);
      SELECT RAISE(ABORT,'recurring period cannot expire with ledger value remaining')
      WHERE NEW.state='expired' AND OLD.state='funded'
        AND EXISTS (SELECT 1 FROM recurring_credit_allocations WHERE credit_period_id=NEW.id)
        AND EXISTS (
          SELECT 1 FROM credit_ledger_entries entry WHERE entry.lot_id=OLD.funded_lot_id
          GROUP BY entry.lot_id
          HAVING COALESCE(sum(entry.available_delta),0)<>0
             OR COALESCE(sum(entry.held_delta),0)<>0
        );
      SELECT RAISE(ABORT,'recurring period expiration requires atomic event obligations')
      WHERE NEW.state='expired' AND OLD.state='funded'
        AND EXISTS (SELECT 1 FROM recurring_credit_allocations WHERE credit_period_id=NEW.id)
        AND NOT EXISTS (
          SELECT 1 FROM domain_events event
          WHERE event.billing_account_id=NEW.billing_account_id
            AND event.event_key='credits_expired:' || NEW.id
            AND event.event_type='credits_expired'
            AND event.aggregate_type='credit_period'
            AND event.aggregate_id=NEW.id
            AND EXISTS (
              SELECT 1 FROM json_each(event.reference_ids_json)
              WHERE value=NEW.id
            )
            AND EXISTS (
              SELECT 1 FROM json_each(event.reference_ids_json)
              WHERE value=OLD.funded_lot_id
            )
            AND EXISTS (
              SELECT 1 FROM recurring_credit_allocations allocation
              WHERE allocation.credit_period_id=NEW.id
                AND EXISTS (
                  SELECT 1 FROM json_each(event.reference_ids_json)
                  WHERE value=allocation.id
                )
            )
            AND EXISTS (
              SELECT 1 FROM communication_outbox message
              WHERE message.domain_event_id=event.id
                AND message.billing_account_id=NEW.billing_account_id
            )
        );
    END
    """)


def upgrade():
    _create_table()
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        _postgresql_triggers()
    elif dialect == "sqlite":
        _sqlite_triggers()
    else:
        raise RuntimeError(f"unsupported migration dialect: {dialect}")


def downgrade():
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute(
            "LOCK TABLE credit_ledger_entries, credit_lots, credit_periods, "
            "recurring_credit_allocations "
            "IN ACCESS EXCLUSIVE MODE"
        )
    if connection.execute(sa.text(
        "SELECT count(*) FROM recurring_credit_allocations"
    )).scalar_one():
        raise RecurringAllocationsNotEmptyError(
            "cannot downgrade Phase 6 while recurring allocation evidence exists"
        )
    if connection.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER trg_phase6_allocation_no_truncate "
            "ON recurring_credit_allocations"
        )
        op.execute(
            "DROP TRIGGER trg_phase6_recurring_expiration_final "
            "ON credit_ledger_entries"
        )
        op.execute(
            "DROP TRIGGER trg_phase6_recurring_lot_final ON credit_lots"
        )
        op.execute(
            "DROP TRIGGER trg_phase6_recurring_entry_guard "
            "ON credit_ledger_entries"
        )
        op.execute(
            "DROP TRIGGER trg_phase6_recurring_lot_guard ON credit_lots"
        )
        op.execute("DROP TRIGGER trg_phase6_period_guard ON credit_periods")
        op.execute(
            "DROP TRIGGER trg_phase6_allocation_guard "
            "ON recurring_credit_allocations"
        )
        op.execute("DROP FUNCTION phase6_reject_truncate()")
        op.execute("DROP FUNCTION phase6_recurring_effect_final_guard()")
        op.execute("DROP FUNCTION phase6_recurring_entry_guard()")
        op.execute("DROP FUNCTION phase6_recurring_lot_guard()")
        op.execute("DROP FUNCTION phase6_period_guard()")
        op.execute("DROP FUNCTION phase6_allocation_guard()")
    else:
        for trigger in (
            "trg_phase6_period_update",
            "trg_phase6_recurring_entry_insert",
            "trg_phase6_recurring_lot_insert",
            "trg_phase6_allocation_delete",
            "trg_phase6_allocation_update",
            "trg_phase6_allocation_insert",
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    op.drop_index(
        "ix_recurring_credit_allocations_financial_line_id",
        table_name="recurring_credit_allocations",
    )
    op.drop_index(
        "ix_recurring_credit_allocations_account_start",
        table_name="recurring_credit_allocations",
    )
    op.drop_table("recurring_credit_allocations")
