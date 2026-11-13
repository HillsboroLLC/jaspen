"""Add inactive Phase 7 plan changes and upgrade proration.

Revision ID: a7d9e2f4b6c8
Revises: f5c8d3e0b2a1
"""

from alembic import op
import sqlalchemy as sa


revision = "a7d9e2f4b6c8"
down_revision = "f5c8d3e0b2a1"
branch_labels = None
depends_on = None


TABLES = ("plan_change_events", "upgrade_credit_allocations", "scheduled_plan_changes")


class Phase7EvidenceNotEmptyError(RuntimeError):
    pass


def _create_tables():
    op.create_table(
        "scheduled_plan_changes",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("billing_account_id", sa.String(36), nullable=False),
        sa.Column("subscription_id", sa.String(36), nullable=False),
        sa.Column("target_entitlement_definition_id", sa.String(36), nullable=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("effective_rule", sa.String(32), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("command_key", sa.String(512), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("idempotency_registry_id", sa.String(36), nullable=False),
        sa.Column("domain_event_id", sa.String(36), nullable=False),
        sa.Column("supersedes_change_id", sa.String(36), nullable=True),
        sa.Column("last_event_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('downgrade','cancellation')", name="ck_scheduled_plan_changes_kind"),
        sa.CheckConstraint("effective_rule IN ('next_monthly_renewal','next_annual_renewal','period_end')", name="ck_scheduled_plan_changes_effective_rule"),
        sa.CheckConstraint("state IN ('pending','awaiting_renewal_payment','applied','superseded','cancelled','blocked_terminal_failure')", name="ck_scheduled_plan_changes_state"),
        sa.CheckConstraint("(kind='downgrade' AND target_entitlement_definition_id IS NOT NULL) OR (kind='cancellation' AND target_entitlement_definition_id IS NULL)", name="ck_scheduled_plan_changes_target"),
        sa.CheckConstraint("length(trim(command_key))>0 AND length(request_fingerprint)=64 AND request_fingerprint=lower(request_fingerprint)", name="ck_scheduled_plan_changes_identity"),
        sa.CheckConstraint("supersedes_change_id IS NULL OR supersedes_change_id<>id", name="ck_scheduled_plan_changes_not_self"),
        sa.ForeignKeyConstraint(["billing_account_id"], ["billing_accounts.id"], name="fk_scheduled_plan_changes_account", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["subscription_id"], ["billing_subscriptions.id"], name="fk_scheduled_plan_changes_subscription", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["target_entitlement_definition_id"], ["entitlement_definitions.id"], name="fk_scheduled_plan_changes_target_definition", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["idempotency_registry_id"], ["idempotency_registry.id"], name="fk_scheduled_plan_changes_registry", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["domain_event_id"], ["domain_events.id"], name="fk_scheduled_plan_changes_domain_event", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supersedes_change_id"], ["scheduled_plan_changes.id"], name="fk_scheduled_plan_changes_supersedes", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_scheduled_plan_changes"),
        sa.UniqueConstraint("command_key", name="uq_scheduled_plan_changes_command_key"),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_scheduled_plan_changes_registry"),
        sa.UniqueConstraint("domain_event_id", name="uq_scheduled_plan_changes_domain_event"),
    )
    op.create_table(
        "plan_change_events",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("scheduled_change_id", sa.String(36), nullable=False),
        sa.Column("from_state", sa.String(32), nullable=False),
        sa.Column("to_state", sa.String(32), nullable=False),
        sa.Column("transition", sa.String(64), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("idempotency_registry_id", sa.String(36), nullable=False),
        sa.Column("domain_event_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("from_state<>to_state", name="ck_plan_change_events_transition"),
        sa.CheckConstraint("length(trim(transition))>0 AND length(trim(actor_type))>0 AND length(trim(actor_id))>0", name="ck_plan_change_events_text"),
        sa.ForeignKeyConstraint(["scheduled_change_id"], ["scheduled_plan_changes.id"], name="fk_plan_change_events_change", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["idempotency_registry_id"], ["idempotency_registry.id"], name="fk_plan_change_events_registry", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["domain_event_id"], ["domain_events.id"], name="fk_plan_change_events_domain_event", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_plan_change_events"),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_plan_change_events_registry"),
        sa.UniqueConstraint("domain_event_id", name="uq_plan_change_events_domain_event"),
    )
    op.create_table(
        "upgrade_credit_allocations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("billing_account_id", sa.String(36), nullable=False),
        sa.Column("subscription_id", sa.String(36), nullable=False),
        sa.Column("prior_entitlement_instance_id", sa.String(36), nullable=False),
        sa.Column("target_entitlement_instance_id", sa.String(36), nullable=False),
        sa.Column("financial_line_id", sa.String(36), nullable=False),
        sa.Column("idempotency_registry_id", sa.String(36), nullable=False),
        sa.Column("domain_event_id", sa.String(36), nullable=False),
        sa.Column("funded_lot_id", sa.String(36), nullable=True),
        sa.Column("grant_entry_id", sa.String(36), nullable=True),
        sa.Column("allocation_key", sa.String(512), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("old_period_amount", sa.BigInteger(), nullable=False),
        sa.Column("new_period_amount", sa.BigInteger(), nullable=False),
        sa.Column("period_starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("credit_amount", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("old_period_amount>=0 AND new_period_amount>old_period_amount AND credit_amount>=0 AND period_ends_at>period_starts_at AND paid_at>=period_starts_at AND paid_at<=period_ends_at", name="ck_upgrade_allocations_values"),
        sa.CheckConstraint("(credit_amount=0 AND funded_lot_id IS NULL AND grant_entry_id IS NULL) OR (credit_amount>0 AND funded_lot_id IS NOT NULL AND grant_entry_id IS NOT NULL)", name="ck_upgrade_allocations_funding_shape"),
        sa.CheckConstraint("length(trim(allocation_key))>0 AND length(request_fingerprint)=64 AND request_fingerprint=lower(request_fingerprint)", name="ck_upgrade_allocations_identity"),
        sa.CheckConstraint("prior_entitlement_instance_id<>target_entitlement_instance_id", name="ck_upgrade_allocations_instances"),
        sa.ForeignKeyConstraint(["billing_account_id"], ["billing_accounts.id"], name="fk_upgrade_allocations_account", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["subscription_id"], ["billing_subscriptions.id"], name="fk_upgrade_allocations_subscription", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["prior_entitlement_instance_id"], ["entitlement_instances.id"], name="fk_upgrade_allocations_prior_instance", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["target_entitlement_instance_id"], ["entitlement_instances.id"], name="fk_upgrade_allocations_target_instance", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["financial_line_id"], ["financial_lines.id"], name="fk_upgrade_allocations_financial_line", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["idempotency_registry_id"], ["idempotency_registry.id"], name="fk_upgrade_allocations_registry", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["domain_event_id"], ["domain_events.id"], name="fk_upgrade_allocations_domain_event", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["funded_lot_id"], ["credit_lots.id"], name="fk_upgrade_allocations_lot", ondelete="RESTRICT", deferrable=True, initially="DEFERRED"),
        sa.ForeignKeyConstraint(["grant_entry_id"], ["credit_ledger_entries.id"], name="fk_upgrade_allocations_grant", ondelete="RESTRICT", deferrable=True, initially="DEFERRED"),
        sa.PrimaryKeyConstraint("id", name="pk_upgrade_credit_allocations"),
        sa.UniqueConstraint("allocation_key", name="uq_upgrade_allocations_key"),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_upgrade_allocations_registry"),
        sa.UniqueConstraint("domain_event_id", name="uq_upgrade_allocations_domain_event"),
        sa.UniqueConstraint("funded_lot_id", name="uq_upgrade_allocations_lot"),
        sa.UniqueConstraint("grant_entry_id", name="uq_upgrade_allocations_grant"),
    )
    op.create_index("ix_scheduled_plan_changes_subscription_state", "scheduled_plan_changes", ["subscription_id", "state", "effective_at"])
    op.create_index("ix_plan_change_events_change_created", "plan_change_events", ["scheduled_change_id", "created_at", "id"])
    op.create_index("ix_upgrade_allocations_subscription_paid", "upgrade_credit_allocations", ["subscription_id", "paid_at", "id"])
    op.create_index(
        "uq_scheduled_plan_changes_one_active", "scheduled_plan_changes", ["subscription_id"],
        unique=True, postgresql_where=sa.text("state IN ('pending','awaiting_renewal_payment')"),
        sqlite_where=sa.text("state IN ('pending','awaiting_renewal_payment')"),
    )


def _postgresql_guards():
    op.execute("""
    CREATE FUNCTION phase7_schedule_guard() RETURNS trigger AS $$
    DECLARE subscription_row billing_subscriptions%ROWTYPE; event_row domain_events%ROWTYPE;
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='scheduled plan changes are historical records'; END IF;
      IF TG_OP='INSERT' THEN
        SELECT * INTO subscription_row FROM billing_subscriptions WHERE id=NEW.subscription_id FOR SHARE;
        SELECT * INTO event_row FROM domain_events WHERE id=NEW.domain_event_id;
        IF NEW.state<>'pending' OR NEW.last_event_id IS NOT NULL
          OR subscription_row.id IS NULL OR subscription_row.billing_account_id<>NEW.billing_account_id
          OR (NEW.kind='downgrade' AND NOT EXISTS (SELECT 1 FROM entitlement_definitions d WHERE d.id=NEW.target_entitlement_definition_id AND d.approved_at IS NOT NULL))
          OR NOT EXISTS (SELECT 1 FROM idempotency_registry r WHERE r.id=NEW.idempotency_registry_id AND r.namespace='plan_change_schedule' AND r.key=NEW.command_key AND r.request_fingerprint=NEW.request_fingerprint AND r.state='claimed')
          OR event_row.billing_account_id<>NEW.billing_account_id OR event_row.event_type<>'plan_change_scheduled'
          OR event_row.aggregate_type<>'scheduled_plan_change' OR event_row.aggregate_id<>NEW.id
          OR NOT EXISTS (SELECT 1 FROM communication_outbox o WHERE o.domain_event_id=event_row.id AND o.billing_account_id=NEW.billing_account_id)
        THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='scheduled change lacks matching authority or communication evidence'; END IF;
      ELSE
        IF NEW.billing_account_id IS DISTINCT FROM OLD.billing_account_id OR NEW.subscription_id IS DISTINCT FROM OLD.subscription_id
          OR NEW.target_entitlement_definition_id IS DISTINCT FROM OLD.target_entitlement_definition_id OR NEW.kind IS DISTINCT FROM OLD.kind
          OR NEW.effective_rule IS DISTINCT FROM OLD.effective_rule OR NEW.effective_at IS DISTINCT FROM OLD.effective_at
          OR NEW.command_key IS DISTINCT FROM OLD.command_key OR NEW.request_fingerprint IS DISTINCT FROM OLD.request_fingerprint
          OR NEW.idempotency_registry_id IS DISTINCT FROM OLD.idempotency_registry_id OR NEW.domain_event_id IS DISTINCT FROM OLD.domain_event_id
          OR NEW.supersedes_change_id IS DISTINCT FROM OLD.supersedes_change_id OR NEW.created_at IS DISTINCT FROM OLD.created_at
        THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='scheduled change identity and evidence are immutable'; END IF;
        IF NEW.state IS DISTINCT FROM OLD.state OR NEW.last_event_id IS DISTINCT FROM OLD.last_event_id THEN
          IF NEW.last_event_id IS NULL OR NEW.last_event_id IS NOT DISTINCT FROM OLD.last_event_id OR NOT EXISTS (
            SELECT 1 FROM plan_change_events e WHERE e.id=NEW.last_event_id AND e.scheduled_change_id=NEW.id AND e.from_state=OLD.state AND e.to_state=NEW.state
          ) THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='scheduled change state requires an append-only event'; END IF;
        END IF;
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_phase7_schedule_guard BEFORE INSERT OR UPDATE OR DELETE ON scheduled_plan_changes FOR EACH ROW EXECUTE FUNCTION phase7_schedule_guard();

    CREATE FUNCTION phase7_plan_event_before() RETURNS trigger AS $$
    DECLARE change_row scheduled_plan_changes%ROWTYPE; allowed boolean; event_row domain_events%ROWTYPE;
    BEGIN
      SELECT * INTO change_row FROM scheduled_plan_changes WHERE id=NEW.scheduled_change_id FOR UPDATE;
      SELECT * INTO event_row FROM domain_events WHERE id=NEW.domain_event_id;
      allowed := CASE change_row.state
        WHEN 'pending' THEN NEW.to_state IN ('awaiting_renewal_payment','applied','superseded','cancelled','blocked_terminal_failure')
        WHEN 'awaiting_renewal_payment' THEN NEW.to_state IN ('applied','superseded','cancelled','blocked_terminal_failure') ELSE false END;
      IF change_row.id IS NULL OR NEW.from_state<>change_row.state OR NOT allowed
        OR NOT EXISTS (SELECT 1 FROM idempotency_registry r WHERE r.id=NEW.idempotency_registry_id AND r.namespace='plan_change_transition' AND r.state='claimed')
        OR event_row.billing_account_id<>change_row.billing_account_id OR event_row.aggregate_type<>'scheduled_plan_change' OR event_row.aggregate_id<>change_row.id
        OR event_row.event_type NOT IN ('plan_change_scheduled','plan_change_applied','plan_change_superseded')
        OR NOT EXISTS (SELECT 1 FROM communication_outbox o WHERE o.domain_event_id=event_row.id AND o.billing_account_id=change_row.billing_account_id)
        OR (NEW.to_state='applied' AND change_row.kind='downgrade' AND NOT EXISTS (
          SELECT 1 FROM billing_subscriptions s
          JOIN entitlement_instances target ON target.subscription_id=s.id
            AND target.entitlement_definition_id=change_row.target_entitlement_definition_id
            AND target.state='active'
          JOIN entitlement_events target_event ON target_event.entitlement_instance_id=target.id
            AND target_event.source_type='phase7_plan_change' AND target_event.source_id=change_row.id
            AND target_event.transition='scheduled_downgrade_activated'
          JOIN recurring_credit_allocations a ON a.subscription_id=s.id
            AND a.entitlement_instance_id=target.id AND a.period_starts_at=NEW.effective_at
          JOIN financial_lines l ON l.id=a.financial_line_id AND l.subscription_id=s.id
            AND l.entitlement_instance_id=target.id AND l.line_kind='subscription' AND l.principal_minor>0
          JOIN financial_transactions f ON f.id=l.financial_transaction_id
            AND f.billing_account_id=s.billing_account_id AND f.kind='payment'
            AND f.principal_minor>0 AND f.effective_at=NEW.effective_at
          WHERE s.id=change_row.subscription_id AND s.billing_account_id=change_row.billing_account_id
            AND s.current_entitlement_definition_id=change_row.target_entitlement_definition_id
            AND EXISTS (
              SELECT 1 FROM entitlement_instances prior
              JOIN entitlement_events prior_event ON prior_event.entitlement_instance_id=prior.id
                AND prior_event.source_type='phase7_plan_change' AND prior_event.source_id=change_row.id
                AND prior_event.transition='scheduled_downgrade_replaced'
              WHERE prior.subscription_id=s.id AND prior.state='expired'
                AND prior.entitlement_definition_id<>change_row.target_entitlement_definition_id
            )
        ))
      THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='plan change event violates transition or communication contract'; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_phase7_plan_event_before BEFORE INSERT ON plan_change_events FOR EACH ROW EXECUTE FUNCTION phase7_plan_event_before();
    CREATE FUNCTION phase7_plan_event_after() RETURNS trigger AS $$
    BEGIN UPDATE scheduled_plan_changes SET state=NEW.to_state,last_event_id=NEW.id WHERE id=NEW.scheduled_change_id; RETURN NEW; END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_phase7_plan_event_after AFTER INSERT ON plan_change_events FOR EACH ROW EXECUTE FUNCTION phase7_plan_event_after();
    CREATE FUNCTION phase7_reject_row_change() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Phase 7 evidence is immutable'; END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_phase7_plan_event_immutable BEFORE UPDATE OR DELETE ON plan_change_events FOR EACH ROW EXECUTE FUNCTION phase7_reject_row_change();

    CREATE FUNCTION phase7_upgrade_guard() RETURNS trigger AS $$
    DECLARE s billing_subscriptions%ROWTYPE; p entitlement_instances%ROWTYPE; t entitlement_instances%ROWTYPE;
      old_definition entitlement_definitions%ROWTYPE; new_definition entitlement_definitions%ROWTYPE;
      l financial_lines%ROWTYPE; f financial_transactions%ROWTYPE; expected bigint;
      expected_old bigint; expected_new bigint; expected_exact numeric; month_index integer;
    BEGIN
      IF TG_OP<>'INSERT' THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='upgrade allocation evidence is immutable'; END IF;
      SELECT * INTO s FROM billing_subscriptions WHERE id=NEW.subscription_id;
      SELECT * INTO p FROM entitlement_instances WHERE id=NEW.prior_entitlement_instance_id;
      SELECT * INTO t FROM entitlement_instances WHERE id=NEW.target_entitlement_instance_id;
      SELECT * INTO old_definition FROM entitlement_definitions WHERE id=p.entitlement_definition_id;
      SELECT * INTO new_definition FROM entitlement_definitions WHERE id=t.entitlement_definition_id;
      SELECT * INTO l FROM financial_lines WHERE id=NEW.financial_line_id;
      SELECT * INTO f FROM financial_transactions WHERE id=l.financial_transaction_id;
      expected_old := (old_definition.funding_policy_json->>'credit_amount')::bigint;
      expected_new := (new_definition.funding_policy_json->>'credit_amount')::bigint;
      month_index := (extract(year FROM NEW.period_starts_at)::integer-extract(year FROM s.anchor_at)::integer)*12
        + extract(month FROM NEW.period_starts_at)::integer-extract(month FROM s.anchor_at)::integer;
      -- Exact arithmetic: (new-old) * remaining seconds can exceed bigint even
      -- when the floored result fits, so compute in numeric. div() is the
      -- exact integer quotient (numeric "/" rounds to a chosen scale, which
      -- can round up at this magnitude); on these nonnegative operands it is
      -- the approved floor, identical to the command's //. Range-check before
      -- converting.
      expected_exact := div(
        (expected_new::numeric - expected_old::numeric)
          * GREATEST(0, floor(extract(epoch FROM (NEW.period_ends_at-NEW.paid_at))))::numeric,
        floor(extract(epoch FROM (NEW.period_ends_at-NEW.period_starts_at)))::numeric
      );
      IF expected_exact IS NULL OR expected_exact < 0 OR expected_exact > 9223372036854775807 THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='upgrade proration amount is outside the supported credit range';
      END IF;
      expected := expected_exact::bigint;
      IF s.billing_account_id<>NEW.billing_account_id OR s.current_entitlement_definition_id<>t.entitlement_definition_id
        OR p.billing_account_id<>NEW.billing_account_id OR t.billing_account_id<>NEW.billing_account_id
        OR p.subscription_id<>s.id OR t.subscription_id<>s.id OR p.state<>'expired' OR t.state<>'active'
        OR old_definition.id IS NULL OR new_definition.id IS NULL OR new_definition.approved_at IS NULL
        OR NEW.old_period_amount<>expected_old OR NEW.new_period_amount<>expected_new
        OR month_index<0 OR NEW.period_starts_at<>phase4_add_months(s.anchor_at,month_index)
        OR NEW.period_ends_at<>phase4_add_months(s.anchor_at,month_index+1)
        OR l.subscription_id<>s.id OR l.entitlement_instance_id<>t.id OR l.line_kind<>'subscription' OR l.principal_minor<=0
        OR f.billing_account_id<>NEW.billing_account_id OR f.kind<>'payment' OR f.principal_minor<=0 OR f.effective_at<>NEW.paid_at
        OR expected<>NEW.credit_amount
        OR NOT EXISTS (SELECT 1 FROM idempotency_registry r WHERE r.id=NEW.idempotency_registry_id AND r.namespace='upgrade_proration' AND r.key=NEW.allocation_key AND r.request_fingerprint=NEW.request_fingerprint AND r.state='completed' AND r.result_type='upgrade_credit_allocation' AND r.result_id=NEW.id)
        OR NOT EXISTS (SELECT 1 FROM domain_events e JOIN communication_outbox o ON o.domain_event_id=e.id WHERE e.id=NEW.domain_event_id AND e.billing_account_id=NEW.billing_account_id AND e.event_type='plan_change_applied' AND e.aggregate_type='upgrade_credit_allocation' AND e.aggregate_id=NEW.id AND o.billing_account_id=NEW.billing_account_id)
      THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='upgrade allocation lacks matching paid, entitlement, or communication evidence'; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE CONSTRAINT TRIGGER trg_phase7_upgrade_guard AFTER INSERT ON upgrade_credit_allocations
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION phase7_upgrade_guard();
    CREATE TRIGGER trg_phase7_upgrade_immutable BEFORE UPDATE OR DELETE ON upgrade_credit_allocations
      FOR EACH ROW EXECUTE FUNCTION phase7_reject_row_change();

    CREATE FUNCTION phase7_upgrade_final() RETURNS trigger AS $$
    DECLARE a upgrade_credit_allocations%ROWTYPE; lot credit_lots%ROWTYPE; entry credit_ledger_entries%ROWTYPE;
    BEGIN
      IF TG_TABLE_NAME='upgrade_credit_allocations' THEN a:=NEW;
      ELSE SELECT * INTO a FROM upgrade_credit_allocations WHERE id=NEW.source_id; END IF;
      IF a.id IS NULL THEN RETURN NEW; END IF;
      IF a.credit_amount=0 THEN RETURN NEW; END IF;
      SELECT * INTO lot FROM credit_lots WHERE id=a.funded_lot_id;
      SELECT * INTO entry FROM credit_ledger_entries WHERE id=a.grant_entry_id;
      IF lot.id IS NULL OR lot.source_type<>'subscription_recurring' OR lot.source_id<>a.id OR lot.billing_account_id<>a.billing_account_id
        OR lot.original_amount<>a.credit_amount OR lot.available_at<>a.paid_at OR lot.expires_at<>a.period_ends_at
        OR entry.id IS NULL OR entry.lot_id<>lot.id OR entry.billing_account_id<>a.billing_account_id OR entry.entry_type<>'grant'
        OR entry.available_delta<>a.credit_amount OR entry.held_delta<>0
      THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='upgrade proration transaction is incomplete'; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE CONSTRAINT TRIGGER trg_phase7_upgrade_final AFTER INSERT ON upgrade_credit_allocations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION phase7_upgrade_final();

    CREATE FUNCTION phase7_subscription_definition_final() RETURNS trigger AS $$
    BEGIN
      IF NEW.current_entitlement_definition_id IS NOT DISTINCT FROM OLD.current_entitlement_definition_id THEN
        RETURN NEW;
      END IF;
      IF EXISTS (
          SELECT 1 FROM upgrade_credit_allocations a
          JOIN entitlement_instances p ON p.id=a.prior_entitlement_instance_id
          JOIN entitlement_instances t ON t.id=a.target_entitlement_instance_id
          WHERE a.subscription_id=NEW.id AND a.billing_account_id=NEW.billing_account_id
            AND p.entitlement_definition_id=OLD.current_entitlement_definition_id
            AND t.entitlement_definition_id=NEW.current_entitlement_definition_id
        ) OR EXISTS (
          SELECT 1 FROM scheduled_plan_changes c
          JOIN plan_change_events e ON e.scheduled_change_id=c.id AND e.to_state='applied'
          JOIN entitlement_instances target ON target.subscription_id=NEW.id
            AND target.entitlement_definition_id=NEW.current_entitlement_definition_id AND target.state='active'
          JOIN entitlement_events target_event ON target_event.entitlement_instance_id=target.id
            AND target_event.source_type='phase7_plan_change' AND target_event.source_id=c.id
            AND target_event.transition='scheduled_downgrade_activated'
          JOIN recurring_credit_allocations a ON a.subscription_id=NEW.id
            AND a.entitlement_instance_id=target.id AND a.period_starts_at=e.effective_at
          JOIN financial_lines l ON l.id=a.financial_line_id AND l.subscription_id=NEW.id
            AND l.entitlement_instance_id=target.id AND l.line_kind='subscription' AND l.principal_minor>0
          JOIN financial_transactions f ON f.id=l.financial_transaction_id
            AND f.billing_account_id=NEW.billing_account_id AND f.kind='payment'
            AND f.principal_minor>0 AND f.effective_at=e.effective_at
          WHERE c.subscription_id=NEW.id AND c.billing_account_id=NEW.billing_account_id
            AND c.kind='downgrade' AND c.target_entitlement_definition_id=NEW.current_entitlement_definition_id
            AND c.state='applied'
            AND EXISTS (
              SELECT 1 FROM entitlement_instances prior
              JOIN entitlement_events prior_event ON prior_event.entitlement_instance_id=prior.id
                AND prior_event.source_type='phase7_plan_change' AND prior_event.source_id=c.id
                AND prior_event.transition='scheduled_downgrade_replaced'
              WHERE prior.subscription_id=NEW.id AND prior.state='expired'
                AND prior.entitlement_definition_id=OLD.current_entitlement_definition_id
            )
        ) OR EXISTS (
          SELECT 1 FROM domain_events d
          JOIN communication_outbox o ON o.domain_event_id=d.id
          JOIN entitlement_events ee ON ee.source_type='phase7_plan_change' AND ee.source_id=d.id
          JOIN entitlement_instances t ON t.id=ee.entitlement_instance_id
          JOIN financial_lines l ON l.subscription_id=NEW.id AND l.entitlement_instance_id=t.id
          JOIN financial_transactions f ON f.id=l.financial_transaction_id
          WHERE d.billing_account_id=NEW.billing_account_id
            AND d.event_type='plan_change_applied' AND d.aggregate_type='billing_subscription'
            AND d.aggregate_id=NEW.id AND o.billing_account_id=NEW.billing_account_id
            AND t.entitlement_definition_id=NEW.current_entitlement_definition_id
            AND t.state='active' AND l.line_kind='subscription' AND l.principal_minor>0
            AND f.kind='payment' AND f.principal_minor>0 AND f.billing_account_id=NEW.billing_account_id
        ) THEN
        RETURN NEW;
      END IF;
      RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='subscription definition change requires Phase 7 authority evidence';
    END; $$ LANGUAGE plpgsql;
    CREATE CONSTRAINT TRIGGER trg_phase7_subscription_definition_final
      AFTER UPDATE OF current_entitlement_definition_id ON billing_subscriptions
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION phase7_subscription_definition_final();

    CREATE OR REPLACE FUNCTION phase6_recurring_lot_guard() RETURNS trigger AS $$
    BEGIN
      IF NEW.source_type NOT IN ('free_recurring','subscription_recurring') THEN RETURN NEW; END IF;
      IF EXISTS (SELECT 1 FROM upgrade_credit_allocations a WHERE a.id=NEW.source_id AND a.billing_account_id=NEW.billing_account_id AND a.funded_lot_id=NEW.id AND a.credit_amount=NEW.original_amount AND a.paid_at=NEW.available_at AND a.period_ends_at=NEW.expires_at) THEN RETURN NEW; END IF;
      IF NOT EXISTS (SELECT 1 FROM credit_periods p JOIN recurring_credit_allocations a ON a.credit_period_id=p.id JOIN domain_events e ON e.id=a.domain_event_id WHERE p.id=NEW.source_id AND p.state='planned' AND p.billing_account_id=NEW.billing_account_id AND p.planned_allocation_amount=NEW.original_amount AND p.starts_at=NEW.available_at AND p.ends_at=NEW.expires_at AND ((p.kind='free' AND NEW.source_type='free_recurring') OR (p.kind IN ('monthly_subscription','annual_monthly') AND NEW.source_type='subscription_recurring')) AND EXISTS (SELECT 1 FROM communication_outbox o WHERE o.domain_event_id=e.id AND o.billing_account_id=NEW.billing_account_id))
      THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='recurring lot requires allocation and communication evidence'; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;

    CREATE OR REPLACE FUNCTION phase6_recurring_entry_guard() RETURNS trigger AS $$
    DECLARE lot_row credit_lots%ROWTYPE;
    BEGIN
      SELECT * INTO lot_row FROM credit_lots WHERE id=NEW.lot_id;
      IF lot_row.source_type NOT IN ('free_recurring','subscription_recurring') THEN RETURN NEW; END IF;
      IF NEW.entry_type='grant' AND EXISTS (SELECT 1 FROM upgrade_credit_allocations a WHERE a.id=lot_row.source_id AND a.grant_entry_id=NEW.id AND a.billing_account_id=NEW.billing_account_id AND a.idempotency_registry_id=NEW.idempotency_registry_id) THEN RETURN NEW; END IF;
      IF NEW.entry_type='grant' AND NOT EXISTS (SELECT 1 FROM credit_periods p JOIN recurring_credit_allocations a ON a.credit_period_id=p.id JOIN domain_events e ON e.id=a.domain_event_id WHERE p.id=lot_row.source_id AND p.billing_account_id=NEW.billing_account_id AND a.idempotency_registry_id=NEW.idempotency_registry_id AND e.event_type='credit_period_funded' AND EXISTS (SELECT 1 FROM communication_outbox o WHERE o.domain_event_id=e.id AND o.billing_account_id=NEW.billing_account_id)) THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='recurring grant requires allocation and communication evidence'; END IF;
      IF NEW.entry_type='expiration' AND NOT EXISTS (SELECT 1 FROM domain_events e WHERE e.billing_account_id=NEW.billing_account_id AND e.event_key='credits_expired:'||lot_row.source_id AND e.event_type='credits_expired' AND EXISTS (SELECT 1 FROM communication_outbox o WHERE o.domain_event_id=e.id AND o.billing_account_id=NEW.billing_account_id)) THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='recurring expiration requires communication evidence'; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;

    CREATE OR REPLACE FUNCTION phase6_recurring_effect_final_guard() RETURNS trigger AS $$
    DECLARE lot_row credit_lots%ROWTYPE; p credit_periods%ROWTYPE; a upgrade_credit_allocations%ROWTYPE; available_total bigint; held_total bigint;
    BEGIN
      IF TG_TABLE_NAME='credit_lots' THEN lot_row:=NEW; ELSE SELECT * INTO lot_row FROM credit_lots WHERE id=NEW.lot_id; END IF;
      IF lot_row.source_type NOT IN ('free_recurring','subscription_recurring') THEN RETURN NEW; END IF;
      SELECT * INTO a FROM upgrade_credit_allocations WHERE id=lot_row.source_id;
      IF a.id IS NOT NULL THEN
        IF a.funded_lot_id<>lot_row.id OR a.credit_amount<>lot_row.original_amount
          OR a.billing_account_id<>lot_row.billing_account_id THEN
          RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='upgrade proration transaction is incomplete';
        END IF;
        RETURN NEW;
      END IF;
      SELECT * INTO p FROM credit_periods WHERE id=lot_row.source_id;
      IF TG_TABLE_NAME='credit_lots' THEN
        IF p.state<>'funded' OR p.funded_lot_id<>lot_row.id OR NOT EXISTS (SELECT 1 FROM credit_ledger_entries e JOIN recurring_credit_allocations r ON r.credit_period_id=p.id WHERE e.lot_id=lot_row.id AND e.entry_type='grant' AND e.idempotency_registry_id=r.idempotency_registry_id) THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='recurring funding transaction is incomplete'; END IF;
      ELSIF NEW.entry_type='expiration' THEN
        SELECT COALESCE(sum(available_delta),0),COALESCE(sum(held_delta),0) INTO available_total,held_total FROM credit_ledger_entries WHERE lot_id=lot_row.id;
        IF p.state<>'expired' OR available_total<>0 OR held_total<>0 THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='recurring expiration transaction is incomplete'; END IF;
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;

    CREATE FUNCTION phase7_reject_truncate() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Phase 7 evidence cannot be truncated'; END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_phase7_schedule_no_truncate BEFORE TRUNCATE ON scheduled_plan_changes FOR EACH STATEMENT EXECUTE FUNCTION phase7_reject_truncate();
    CREATE TRIGGER trg_phase7_event_no_truncate BEFORE TRUNCATE ON plan_change_events FOR EACH STATEMENT EXECUTE FUNCTION phase7_reject_truncate();
    CREATE TRIGGER trg_phase7_upgrade_no_truncate BEFORE TRUNCATE ON upgrade_credit_allocations FOR EACH STATEMENT EXECUTE FUNCTION phase7_reject_truncate();
    """)


def _sqlite_guards():
    op.execute("""CREATE TRIGGER trg_phase7_schedule_delete BEFORE DELETE ON scheduled_plan_changes BEGIN SELECT RAISE(ABORT,'scheduled plan changes are historical records'); END""")
    op.execute("""CREATE TRIGGER trg_phase7_plan_event_update BEFORE UPDATE ON plan_change_events BEGIN SELECT RAISE(ABORT,'Phase 7 evidence is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_phase7_plan_event_delete BEFORE DELETE ON plan_change_events BEGIN SELECT RAISE(ABORT,'Phase 7 evidence is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_phase7_upgrade_update BEFORE UPDATE ON upgrade_credit_allocations BEGIN SELECT RAISE(ABORT,'upgrade allocation evidence is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_phase7_upgrade_delete BEFORE DELETE ON upgrade_credit_allocations BEGIN SELECT RAISE(ABORT,'upgrade allocation evidence is immutable'); END""")
    op.execute("""CREATE TRIGGER trg_phase7_plan_event_after AFTER INSERT ON plan_change_events BEGIN UPDATE scheduled_plan_changes SET state=NEW.to_state,last_event_id=NEW.id WHERE id=NEW.scheduled_change_id; END""")


def upgrade():
    _create_tables()
    if op.get_bind().dialect.name == "postgresql":
        _postgresql_guards()
    else:
        _sqlite_guards()


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in TABLES:
            op.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
    for table in TABLES:
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first() is not None:
            raise Phase7EvidenceNotEmptyError("Phase 7 downgrade refuses to discard evidence")
    if bind.dialect.name == "postgresql":
        for trigger, table in (
            ("trg_phase7_schedule_no_truncate", "scheduled_plan_changes"),
            ("trg_phase7_event_no_truncate", "plan_change_events"),
            ("trg_phase7_upgrade_no_truncate", "upgrade_credit_allocations"),
            ("trg_phase7_upgrade_final", "upgrade_credit_allocations"),
            ("trg_phase7_subscription_definition_final", "billing_subscriptions"),
            ("trg_phase7_upgrade_guard", "upgrade_credit_allocations"),
            ("trg_phase7_upgrade_immutable", "upgrade_credit_allocations"),
            ("trg_phase7_plan_event_immutable", "plan_change_events"),
            ("trg_phase7_plan_event_after", "plan_change_events"),
            ("trg_phase7_plan_event_before", "plan_change_events"),
            ("trg_phase7_schedule_guard", "scheduled_plan_changes"),
        ):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger} ON {table}"))
        for function in (
            "phase7_reject_truncate", "phase7_subscription_definition_final",
            "phase7_upgrade_final", "phase7_upgrade_guard",
            "phase7_reject_row_change", "phase7_plan_event_after", "phase7_plan_event_before",
            "phase7_schedule_guard",
        ):
            op.execute(sa.text(f"DROP FUNCTION IF EXISTS {function}()"))
        # Restore the accepted Phase 6 functions by re-running its definitions is
        # intentionally required before table removal.
        from importlib import import_module
        phase6 = import_module("migrations.versions.f5c8d3e0b2a1_add_recurring_credit_allocations")
        for trigger, table in (
            ("trg_phase6_allocation_guard", "recurring_credit_allocations"),
            ("trg_phase6_period_guard", "credit_periods"),
            ("trg_phase6_recurring_lot_guard", "credit_lots"),
            ("trg_phase6_recurring_entry_guard", "credit_ledger_entries"),
            ("trg_phase6_recurring_lot_final", "credit_lots"),
            ("trg_phase6_recurring_expiration_final", "credit_ledger_entries"),
            ("trg_phase6_allocation_no_truncate", "recurring_credit_allocations"),
        ):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger} ON {table}"))
        for fn in (
            "phase6_allocation_guard", "phase6_period_guard", "phase6_recurring_lot_guard",
            "phase6_recurring_entry_guard", "phase6_recurring_effect_final_guard",
            "phase6_reject_truncate",
        ):
            op.execute(sa.text(f"DROP FUNCTION IF EXISTS {fn}()"))
        phase6._postgresql_triggers()
    op.drop_index("uq_scheduled_plan_changes_one_active", table_name="scheduled_plan_changes")
    op.drop_index("ix_upgrade_allocations_subscription_paid", table_name="upgrade_credit_allocations")
    op.drop_index("ix_plan_change_events_change_created", table_name="plan_change_events")
    op.drop_index("ix_scheduled_plan_changes_subscription_state", table_name="scheduled_plan_changes")
    op.drop_table("upgrade_credit_allocations")
    op.drop_table("plan_change_events")
    op.drop_table("scheduled_plan_changes")
