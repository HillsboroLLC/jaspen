"""Add inactive entitlement and recurring-credit-period foundations.

Revision ID: f9c1a3e5b7d4
Revises: e8b0f2d4a6c3
"""

from alembic import op
import sqlalchemy as sa


revision = "f9c1a3e5b7d4"
down_revision = "e8b0f2d4a6c3"
branch_labels = None
depends_on = None

PHASE_4_TABLES = (
    "entitlement_definitions", "billing_subscriptions", "entitlement_instances",
    "credit_periods", "entitlement_events",
)


class EntitlementFoundationNotEmptyError(RuntimeError):
    pass


def _create_tables():
    op.create_table(
        "entitlement_definitions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("key", sa.String(80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("exclusivity_key", sa.String(80), nullable=False),
        sa.Column("capability_json", sa.JSON(), nullable=False),
        sa.Column("funding_policy_json", sa.JSON(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_user_id", sa.String(36), nullable=True),
        sa.Column("approval_evidence_reference", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("version > 0", name="ck_entitlement_definitions_version"),
        sa.CheckConstraint("length(trim(key)) > 0 AND length(trim(exclusivity_key)) > 0", name="ck_entitlement_definitions_identity"),
        sa.CheckConstraint("retired_at IS NULL OR (effective_at IS NOT NULL AND retired_at > effective_at)", name="ck_entitlement_definitions_interval"),
        sa.CheckConstraint(
            "((approved_at IS NULL AND approved_by_user_id IS NULL AND approval_evidence_reference IS NULL) OR "
            "(approved_at IS NOT NULL AND approval_evidence_reference IS NOT NULL "
            "AND length(trim(approval_evidence_reference)) > 0))",
            name="ck_entitlement_definitions_approval",
        ),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], name="fk_entitlement_definitions_approved_by_user_id", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_entitlement_definitions"),
        sa.UniqueConstraint("key", "version", name="uq_entitlement_definitions_key_version"),
    )
    op.create_index("ix_entitlement_definitions_key_effective", "entitlement_definitions", ["key", "effective_at", "retired_at"])
    op.create_index("ix_entitlement_definitions_exclusivity_key", "entitlement_definitions", ["exclusivity_key"])

    op.create_table(
        "billing_subscriptions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("billing_account_id", sa.String(36), nullable=False),
        sa.Column("processor", sa.String(32), nullable=False),
        sa.Column("external_subscription_id", sa.String(255), nullable=False),
        sa.Column("interval", sa.String(16), nullable=False),
        sa.Column("anchor_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("term_starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("term_ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("current_entitlement_definition_id", sa.String(36), nullable=False),
        sa.Column("origin_evidence_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("interval IN ('month','year','custom')", name="ck_billing_subscriptions_interval"),
        sa.CheckConstraint(
            "state IN ('proposed','incomplete','active','past_due','unpaid','paused',"
            "'cancel_at_period_end','cancelled','expired')",
            name="ck_billing_subscriptions_state",
        ),
        sa.CheckConstraint("term_ends_at > term_starts_at", name="ck_billing_subscriptions_term"),
        sa.CheckConstraint("length(trim(processor)) > 0 AND length(trim(external_subscription_id)) > 0", name="ck_billing_subscriptions_external_identity"),
        sa.ForeignKeyConstraint(["billing_account_id"], ["billing_accounts.id"], name="fk_billing_subscriptions_billing_account_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["current_entitlement_definition_id"], ["entitlement_definitions.id"], name="fk_billing_subscriptions_current_entitlement_definition_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_billing_subscriptions"),
        sa.UniqueConstraint("processor", "external_subscription_id", name="uq_billing_subscriptions_processor_external"),
    )
    op.create_index("ix_billing_subscriptions_account_state_term", "billing_subscriptions", ["billing_account_id", "state", "term_ends_at"])
    op.create_index("ix_billing_subscriptions_current_definition", "billing_subscriptions", ["current_entitlement_definition_id"])

    op.create_table(
        "entitlement_instances",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("billing_account_id", sa.String(36), nullable=False),
        sa.Column("entitlement_definition_id", sa.String(36), nullable=False),
        sa.Column("subscription_id", sa.String(36), nullable=True),
        sa.Column("state", sa.String(24), nullable=False, server_default="proposed"),
        sa.Column("last_event_id", sa.String(36), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_id", sa.String(255), nullable=False),
        sa.Column("approval_evidence_reference", sa.String(255), nullable=True),
        sa.Column("supersedes_instance_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("state IN ('proposed','scheduled','active','reducing','expired','superseded','cancelled')", name="ck_entitlement_instances_state"),
        sa.CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="ck_entitlement_instances_interval"),
        sa.CheckConstraint("source_type IN ('free','subscription','trial','promotion','comp','enterprise_contract','internal')", name="ck_entitlement_instances_source_type"),
        sa.CheckConstraint("((source_type = 'subscription' AND subscription_id IS NOT NULL) OR (source_type != 'subscription' AND subscription_id IS NULL))", name="ck_entitlement_instances_source_reference"),
        sa.CheckConstraint("state = 'proposed' OR (approval_evidence_reference IS NOT NULL AND length(trim(approval_evidence_reference)) > 0)", name="ck_entitlement_instances_approval"),
        sa.CheckConstraint("source_type NOT IN ('trial','promotion','comp','enterprise_contract') OR state IN ('proposed','cancelled')", name="ck_entitlement_instances_later_authority_gate"),
        sa.CheckConstraint("supersedes_instance_id IS NULL OR supersedes_instance_id != id", name="ck_entitlement_instances_not_self_superseding"),
        sa.ForeignKeyConstraint(["billing_account_id"], ["billing_accounts.id"], name="fk_entitlement_instances_billing_account_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["entitlement_definition_id"], ["entitlement_definitions.id"], name="fk_entitlement_instances_entitlement_definition_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["subscription_id"], ["billing_subscriptions.id"], name="fk_entitlement_instances_subscription_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supersedes_instance_id"], ["entitlement_instances.id"], name="fk_entitlement_instances_supersedes_instance_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_entitlement_instances"),
        sa.UniqueConstraint("billing_account_id", "source_type", "source_id", name="uq_entitlement_instances_account_origin"),
    )
    op.create_index("ix_entitlement_instances_account_state_interval", "entitlement_instances", ["billing_account_id", "state", "starts_at", "ends_at"])
    op.create_index("ix_entitlement_instances_definition_id", "entitlement_instances", ["entitlement_definition_id"])
    op.create_index("ix_entitlement_instances_subscription_id", "entitlement_instances", ["subscription_id"])
    op.create_index("ix_entitlement_instances_supersedes_id", "entitlement_instances", ["supersedes_instance_id"])

    op.create_table(
        "credit_periods",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("billing_account_id", sa.String(36), nullable=False),
        sa.Column("entitlement_instance_id", sa.String(36), nullable=False),
        sa.Column("subscription_id", sa.String(36), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("period_index", sa.Integer(), nullable=False),
        sa.Column("anchor_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("planned_allocation_amount", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="planned"),
        sa.Column("funding_idempotency_registry_id", sa.String(36), nullable=True),
        sa.Column("funded_lot_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('free','monthly_subscription','annual_monthly','enterprise')", name="ck_credit_periods_kind"),
        sa.CheckConstraint("state IN ('planned','funded','unfunded','expired')", name="ck_credit_periods_state"),
        sa.CheckConstraint("period_index >= 0", name="ck_credit_periods_period_index"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_credit_periods_interval"),
        sa.CheckConstraint("planned_allocation_amount > 0", name="ck_credit_periods_allocation"),
        sa.CheckConstraint("((kind = 'free' AND subscription_id IS NULL) OR (kind IN ('monthly_subscription','annual_monthly') AND subscription_id IS NOT NULL) OR kind = 'enterprise')", name="ck_credit_periods_subscription_reference"),
        sa.CheckConstraint("((state = 'funded' AND funding_idempotency_registry_id IS NOT NULL AND funded_lot_id IS NOT NULL) OR (state IN ('planned','unfunded') AND funded_lot_id IS NULL) OR state = 'expired')", name="ck_credit_periods_funding_shape"),
        sa.ForeignKeyConstraint(["billing_account_id"], ["billing_accounts.id"], name="fk_credit_periods_billing_account_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["entitlement_instance_id"], ["entitlement_instances.id"], name="fk_credit_periods_entitlement_instance_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["subscription_id"], ["billing_subscriptions.id"], name="fk_credit_periods_subscription_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["funding_idempotency_registry_id"], ["idempotency_registry.id"], name="fk_credit_periods_funding_idempotency_registry_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["funded_lot_id"], ["credit_lots.id"], name="fk_credit_periods_funded_lot_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_credit_periods"),
        sa.UniqueConstraint("billing_account_id", "kind", "starts_at", name="uq_credit_periods_account_kind_start"),
        sa.UniqueConstraint("billing_account_id", "kind", "anchor_at", "period_index", name="uq_credit_periods_account_kind_anchor_index"),
        sa.UniqueConstraint("funding_idempotency_registry_id", name="uq_credit_periods_funding_idempotency_registry_id"),
        sa.UniqueConstraint("funded_lot_id", name="uq_credit_periods_funded_lot_id"),
    )
    op.create_index("ix_credit_periods_account_state_end", "credit_periods", ["billing_account_id", "state", "ends_at"])
    op.create_index("ix_credit_periods_entitlement_instance_id", "credit_periods", ["entitlement_instance_id"])
    op.create_index("ix_credit_periods_subscription_id", "credit_periods", ["subscription_id"])

    op.create_table(
        "entitlement_events",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("entitlement_instance_id", sa.String(36), nullable=False),
        sa.Column("transition", sa.String(64), nullable=False),
        sa.Column("from_state", sa.String(24), nullable=False),
        sa.Column("to_state", sa.String(24), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("actor_type", sa.String(40), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_id", sa.String(255), nullable=False),
        sa.Column("idempotency_registry_id", sa.String(36), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.CheckConstraint("from_state IN ('proposed','scheduled','active','reducing','expired','superseded','cancelled') AND to_state IN ('proposed','scheduled','active','reducing','expired','superseded','cancelled')", name="ck_entitlement_events_states"),
        sa.CheckConstraint("length(trim(transition)) > 0 AND length(trim(actor_type)) > 0 AND length(trim(actor_id)) > 0 AND length(trim(source_type)) > 0 AND length(trim(source_id)) > 0", name="ck_entitlement_events_provenance"),
        sa.ForeignKeyConstraint(["entitlement_instance_id"], ["entitlement_instances.id"], name="fk_entitlement_events_entitlement_instance_id", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["idempotency_registry_id"], ["idempotency_registry.id"], name="fk_entitlement_events_idempotency_registry_id", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_entitlement_events"),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_entitlement_events_idempotency_registry_id"),
    )
    op.create_index("ix_entitlement_events_instance_effective", "entitlement_events", ["entitlement_instance_id", "effective_at", "id"])


def _postgresql_triggers():
    op.execute(sa.text("""
    CREATE OR REPLACE FUNCTION phase4_add_months(anchor_value timestamptz, month_count integer)
    RETURNS timestamptz AS $$
      SELECT ((anchor_value AT TIME ZONE 'UTC') + make_interval(months => month_count)) AT TIME ZONE 'UTC';
    $$ LANGUAGE sql IMMUTABLE;

    CREATE OR REPLACE FUNCTION phase4_json_has_unlimited(value jsonb)
    RETURNS boolean AS $$
    DECLARE item record;
    BEGIN
      IF jsonb_typeof(value) = 'object' THEN
        FOR item IN SELECT key, value AS child FROM jsonb_each(value) LOOP
          IF (lower(item.key) LIKE '%unlimited%' AND item.child NOT IN ('false'::jsonb,'0'::jsonb,'null'::jsonb))
             OR phase4_json_has_unlimited(item.child) THEN RETURN true; END IF;
        END LOOP;
      ELSIF jsonb_typeof(value) = 'array' THEN
        FOR item IN SELECT value AS child FROM jsonb_array_elements(value) LOOP
          IF phase4_json_has_unlimited(item.child) THEN RETURN true; END IF;
        END LOOP;
      END IF;
      RETURN false;
    END;
    $$ LANGUAGE plpgsql IMMUTABLE;

    CREATE OR REPLACE FUNCTION phase4_definition_guard() RETURNS trigger AS $$
    DECLARE amount_text text;
    BEGIN
      IF TG_OP = 'DELETE' THEN
        IF OLD.approved_at IS NOT NULL THEN
          RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='approved entitlement definition cannot be deleted';
        END IF;
        RETURN OLD;
      END IF;
      IF jsonb_typeof(NEW.capability_json::jsonb) IS DISTINCT FROM 'object' OR
         jsonb_typeof(NEW.funding_policy_json::jsonb) IS DISTINCT FROM 'object' OR
         NEW.capability_json::jsonb->>'schema_version' IS DISTINCT FROM '1' OR
         jsonb_typeof(NEW.capability_json::jsonb->'capabilities') IS DISTINCT FROM 'object' OR
         NEW.funding_policy_json::jsonb->>'schema_version' IS DISTINCT FROM '1' OR
         NEW.funding_policy_json::jsonb->>'period_kind' IS NULL OR
         NEW.funding_policy_json::jsonb->>'period_kind' NOT IN ('none','free','monthly_subscription','annual_monthly','enterprise') THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='invalid entitlement definition payload contract';
      END IF;
      amount_text := NEW.funding_policy_json::jsonb->>'credit_amount';
      IF amount_text IS NULL OR amount_text !~ '^[0-9]+$' OR amount_text::numeric > 9223372036854775807 THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='credit_amount must be a finite nonnegative integer';
      END IF;
      IF phase4_json_has_unlimited(NEW.capability_json::jsonb) OR
         phase4_json_has_unlimited(NEW.funding_policy_json::jsonb) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='unlimited benefits are not permitted';
      END IF;
      IF TG_OP = 'UPDATE' AND OLD.approved_at IS NOT NULL AND (
         NEW.key IS DISTINCT FROM OLD.key OR NEW.version IS DISTINCT FROM OLD.version OR
         NEW.exclusivity_key IS DISTINCT FROM OLD.exclusivity_key OR
         NEW.capability_json::text IS DISTINCT FROM OLD.capability_json::text OR
         NEW.funding_policy_json::text IS DISTINCT FROM OLD.funding_policy_json::text OR
         NEW.effective_at IS DISTINCT FROM OLD.effective_at OR
         NEW.approved_at IS DISTINCT FROM OLD.approved_at OR
         (NEW.approved_by_user_id IS DISTINCT FROM OLD.approved_by_user_id AND NOT (
           OLD.approved_by_user_id IS NOT NULL AND NEW.approved_by_user_id IS NULL)) OR
         NEW.approval_evidence_reference IS DISTINCT FROM OLD.approval_evidence_reference OR
         (OLD.retired_at IS NOT NULL AND NEW.retired_at IS DISTINCT FROM OLD.retired_at)) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='approved entitlement definition is immutable';
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_phase4_definition_guard BEFORE INSERT OR UPDATE OR DELETE ON entitlement_definitions
      FOR EACH ROW EXECUTE FUNCTION phase4_definition_guard();

    CREATE OR REPLACE FUNCTION phase4_subscription_guard() RETURNS trigger AS $$
    DECLARE allowed boolean;
    BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='billing subscriptions are historical records';
      END IF;
      IF NEW.billing_account_id IS DISTINCT FROM OLD.billing_account_id OR NEW.processor IS DISTINCT FROM OLD.processor OR
         NEW.external_subscription_id IS DISTINCT FROM OLD.external_subscription_id OR NEW.anchor_at IS DISTINCT FROM OLD.anchor_at OR
         NEW.origin_evidence_json::text IS DISTINCT FROM OLD.origin_evidence_json::text THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='subscription identity, anchor, and origin evidence are immutable';
      END IF;
      IF NEW.state IS DISTINCT FROM OLD.state THEN
        allowed := CASE OLD.state
          WHEN 'proposed' THEN NEW.state IN ('incomplete','active','cancelled')
          WHEN 'incomplete' THEN NEW.state IN ('active','cancelled','expired')
          WHEN 'active' THEN NEW.state IN ('past_due','paused','cancel_at_period_end','cancelled','expired')
          WHEN 'past_due' THEN NEW.state IN ('active','unpaid','paused','cancel_at_period_end','cancelled','expired')
          WHEN 'unpaid' THEN NEW.state IN ('active','cancelled','expired')
          WHEN 'paused' THEN NEW.state IN ('active','cancel_at_period_end','cancelled','expired')
          WHEN 'cancel_at_period_end' THEN NEW.state IN ('active','past_due','cancelled','expired') ELSE false END;
        IF NOT allowed THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='invalid subscription transition'; END IF;
      END IF;
      IF NEW.state <> 'proposed' AND NOT EXISTS (
        SELECT 1 FROM entitlement_definitions d WHERE d.id=NEW.current_entitlement_definition_id AND d.approved_at IS NOT NULL
      ) THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='subscription target definition must be approved'; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_phase4_subscription_guard BEFORE UPDATE OR DELETE ON billing_subscriptions
      FOR EACH ROW EXECUTE FUNCTION phase4_subscription_guard();
    CREATE OR REPLACE FUNCTION phase4_subscription_insert_guard() RETURNS trigger AS $$
    BEGIN
      IF NEW.state <> 'proposed' AND NOT EXISTS (
        SELECT 1 FROM entitlement_definitions d WHERE d.id=NEW.current_entitlement_definition_id AND d.approved_at IS NOT NULL
      ) THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='subscription target definition must be approved'; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_phase4_subscription_insert_guard BEFORE INSERT ON billing_subscriptions
      FOR EACH ROW EXECUTE FUNCTION phase4_subscription_insert_guard();

    CREATE OR REPLACE FUNCTION phase4_instance_guard() RETURNS trigger AS $$
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='entitlement instances are historical records'; END IF;
      IF TG_OP='INSERT' THEN
        PERFORM 1 FROM billing_accounts WHERE id=NEW.billing_account_id FOR UPDATE;
        IF NEW.state <> 'proposed' OR NEW.last_event_id IS NOT NULL THEN
          RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='entitlement instance must begin proposed';
        END IF;
      ELSE
        IF NEW.billing_account_id IS DISTINCT FROM OLD.billing_account_id OR
           NEW.entitlement_definition_id IS DISTINCT FROM OLD.entitlement_definition_id OR
           NEW.subscription_id IS DISTINCT FROM OLD.subscription_id OR NEW.starts_at IS DISTINCT FROM OLD.starts_at OR
           NEW.ends_at IS DISTINCT FROM OLD.ends_at OR NEW.source_type IS DISTINCT FROM OLD.source_type OR
           NEW.source_id IS DISTINCT FROM OLD.source_id OR NEW.approval_evidence_reference IS DISTINCT FROM OLD.approval_evidence_reference OR
           NEW.supersedes_instance_id IS DISTINCT FROM OLD.supersedes_instance_id THEN
          RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='entitlement identity and evidence are immutable';
        END IF;
        IF NEW.state IS DISTINCT FROM OLD.state OR NEW.last_event_id IS DISTINCT FROM OLD.last_event_id THEN
          IF NEW.last_event_id IS NULL OR NEW.last_event_id IS NOT DISTINCT FROM OLD.last_event_id OR NOT EXISTS (
            SELECT 1 FROM entitlement_events e WHERE e.id=NEW.last_event_id AND e.entitlement_instance_id=NEW.id
              AND e.from_state=OLD.state AND e.to_state=NEW.state
          ) THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='entitlement state changes require a new authoritative event'; END IF;
        END IF;
      END IF;
      IF NEW.subscription_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM billing_subscriptions s WHERE s.id=NEW.subscription_id AND s.billing_account_id=NEW.billing_account_id
      ) THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='entitlement subscription/account mismatch'; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_phase4_instance_guard BEFORE INSERT OR UPDATE OR DELETE ON entitlement_instances
      FOR EACH ROW EXECUTE FUNCTION phase4_instance_guard();

    CREATE OR REPLACE FUNCTION phase4_event_before() RETURNS trigger AS $$
    DECLARE current_instance entitlement_instances%ROWTYPE; allowed boolean; exclusivity varchar(80); account_id varchar(36);
    BEGIN
      SELECT i.billing_account_id INTO account_id FROM entitlement_instances i WHERE i.id=NEW.entitlement_instance_id;
      PERFORM 1 FROM billing_accounts WHERE id=account_id FOR UPDATE;
      SELECT i.* INTO current_instance FROM entitlement_instances i WHERE i.id=NEW.entitlement_instance_id FOR UPDATE;
      IF current_instance.id IS NULL OR NEW.from_state <> current_instance.state THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='entitlement event does not match current state';
      END IF;
      allowed := CASE current_instance.state
        WHEN 'proposed' THEN NEW.to_state IN ('scheduled','cancelled')
        WHEN 'scheduled' THEN NEW.to_state IN ('active','superseded','cancelled')
        WHEN 'active' THEN NEW.to_state IN ('reducing','expired')
        WHEN 'reducing' THEN NEW.to_state IN ('expired','superseded') ELSE false END;
      IF NOT allowed THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='invalid entitlement transition'; END IF;
      IF NEW.to_state <> 'cancelled' AND (
        current_instance.approval_evidence_reference IS NULL OR NOT EXISTS (
          SELECT 1 FROM entitlement_definitions d WHERE d.id=current_instance.entitlement_definition_id AND d.approved_at IS NOT NULL
        )) THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='entitlement transition requires approved evidence'; END IF;
      SELECT d.exclusivity_key INTO exclusivity FROM entitlement_definitions d WHERE d.id=current_instance.entitlement_definition_id;
      IF NEW.to_state IN ('scheduled','active','reducing') AND EXISTS (
        SELECT 1 FROM entitlement_instances other JOIN entitlement_definitions d ON d.id=other.entitlement_definition_id
        WHERE other.id<>current_instance.id AND other.billing_account_id=current_instance.billing_account_id
          AND other.state IN ('scheduled','active','reducing') AND d.exclusivity_key=exclusivity
          AND other.starts_at < COALESCE(current_instance.ends_at,'infinity'::timestamptz)
          AND current_instance.starts_at < COALESCE(other.ends_at,'infinity'::timestamptz)
      ) THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='incompatible entitlement intervals overlap'; END IF;
      UPDATE idempotency_registry SET state='completed',completed_at=now(),
        result_type='entitlement_event',result_id=NEW.id,last_error_code=NULL
      WHERE id=NEW.idempotency_registry_id AND state='claimed';
      IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='entitlement event requires a claimed idempotency key'; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_phase4_event_before BEFORE INSERT ON entitlement_events
      FOR EACH ROW EXECUTE FUNCTION phase4_event_before();

    CREATE OR REPLACE FUNCTION phase4_event_after() RETURNS trigger AS $$
    BEGIN UPDATE entitlement_instances SET state=NEW.to_state,last_event_id=NEW.id,updated_at=now()
      WHERE id=NEW.entitlement_instance_id; RETURN NEW; END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_phase4_event_after AFTER INSERT ON entitlement_events
      FOR EACH ROW EXECUTE FUNCTION phase4_event_after();

    CREATE OR REPLACE FUNCTION phase4_event_immutable() RETURNS trigger AS $$
    BEGIN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='entitlement events are append-only'; END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_phase4_event_immutable BEFORE UPDATE OR DELETE ON entitlement_events
      FOR EACH ROW EXECUTE FUNCTION phase4_event_immutable();

    CREATE OR REPLACE FUNCTION phase4_period_guard() RETURNS trigger AS $$
    DECLARE account_anchor timestamptz; instance_row entitlement_instances%ROWTYPE;
      subscription_row billing_subscriptions%ROWTYPE; lot_row credit_lots%ROWTYPE; allowed boolean;
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='credit periods are historical records'; END IF;
      SELECT account_anchor_at INTO account_anchor FROM billing_accounts WHERE id=NEW.billing_account_id FOR UPDATE;
      IF TG_OP='INSERT' AND (NEW.state<>'planned' OR NEW.funding_idempotency_registry_id IS NOT NULL OR NEW.funded_lot_id IS NOT NULL) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='credit period must begin planned and unfunded'; END IF;
      SELECT * INTO instance_row FROM entitlement_instances WHERE id=NEW.entitlement_instance_id;
      IF instance_row.billing_account_id IS DISTINCT FROM NEW.billing_account_id THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='credit period entitlement/account mismatch'; END IF;
      IF NEW.starts_at < instance_row.starts_at OR (instance_row.ends_at IS NOT NULL AND NEW.ends_at > instance_row.ends_at) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='credit period exceeds entitlement interval'; END IF;
      IF NEW.subscription_id IS NOT NULL THEN
        SELECT * INTO subscription_row FROM billing_subscriptions WHERE id=NEW.subscription_id;
        IF subscription_row.billing_account_id IS DISTINCT FROM NEW.billing_account_id OR
           NEW.starts_at < subscription_row.term_starts_at OR NEW.ends_at > subscription_row.term_ends_at THEN
          RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='credit period exceeds subscription ownership or term'; END IF;
      END IF;
      IF (NEW.kind='free' AND NEW.anchor_at IS DISTINCT FROM account_anchor) OR
         (NEW.kind IN ('monthly_subscription','annual_monthly') AND NEW.anchor_at IS DISTINCT FROM subscription_row.anchor_at) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='credit period uses the wrong immutable anchor'; END IF;
      IF NEW.starts_at IS DISTINCT FROM phase4_add_months(NEW.anchor_at,NEW.period_index) OR
         NEW.ends_at IS DISTINCT FROM phase4_add_months(NEW.anchor_at,NEW.period_index+1) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='credit period boundaries do not match the anchor'; END IF;
      IF TG_OP='UPDATE' THEN
        IF NEW.billing_account_id IS DISTINCT FROM OLD.billing_account_id OR NEW.entitlement_instance_id IS DISTINCT FROM OLD.entitlement_instance_id OR
           NEW.subscription_id IS DISTINCT FROM OLD.subscription_id OR NEW.kind IS DISTINCT FROM OLD.kind OR
           NEW.period_index IS DISTINCT FROM OLD.period_index OR NEW.anchor_at IS DISTINCT FROM OLD.anchor_at OR
           NEW.starts_at IS DISTINCT FROM OLD.starts_at OR NEW.ends_at IS DISTINCT FROM OLD.ends_at OR
           NEW.planned_allocation_amount IS DISTINCT FROM OLD.planned_allocation_amount OR
           (OLD.funding_idempotency_registry_id IS NOT NULL AND NEW.funding_idempotency_registry_id IS DISTINCT FROM OLD.funding_idempotency_registry_id) OR
           (OLD.funded_lot_id IS NOT NULL AND NEW.funded_lot_id IS DISTINCT FROM OLD.funded_lot_id) THEN
          RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='credit period identity and funding result are immutable'; END IF;
        IF NEW.state IS DISTINCT FROM OLD.state THEN
          allowed := CASE OLD.state WHEN 'planned' THEN NEW.state IN ('funded','unfunded','expired')
            WHEN 'unfunded' THEN NEW.state IN ('funded','expired') WHEN 'funded' THEN NEW.state='expired' ELSE false END;
          IF NOT allowed THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='invalid credit period transition'; END IF;
        END IF;
      END IF;
      IF NEW.kind='annual_monthly' AND EXISTS (
        SELECT 1 FROM credit_periods p WHERE p.id<>NEW.id AND p.subscription_id=NEW.subscription_id
          AND p.kind='annual_monthly' AND p.state<>'expired' AND p.starts_at<NEW.ends_at AND NEW.starts_at<p.ends_at
      ) THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='annual monthly periods cannot overlap'; END IF;
      IF NEW.state='funded' THEN
        SELECT * INTO lot_row FROM credit_lots WHERE id=NEW.funded_lot_id;
        IF lot_row.id IS NULL OR lot_row.billing_account_id<>NEW.billing_account_id OR lot_row.source_id<>NEW.id OR
           lot_row.original_amount<>NEW.planned_allocation_amount OR lot_row.available_at<>NEW.starts_at OR lot_row.expires_at<>NEW.ends_at OR
           lot_row.source_type<>CASE NEW.kind WHEN 'free' THEN 'free_recurring' WHEN 'enterprise' THEN 'enterprise_recurring' ELSE 'subscription_recurring' END OR
           NOT EXISTS (SELECT 1 FROM credit_ledger_entries e WHERE e.lot_id=NEW.funded_lot_id AND e.entry_type='grant'
             AND e.available_delta=NEW.planned_allocation_amount AND e.held_delta=0 AND e.idempotency_registry_id=NEW.funding_idempotency_registry_id) THEN
          RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='funded period does not match its authoritative lot and grant'; END IF;
        UPDATE idempotency_registry SET state='completed',completed_at=now(),
          result_type='credit_period',result_id=NEW.id,last_error_code=NULL
        WHERE id=NEW.funding_idempotency_registry_id AND state='claimed';
        IF NOT FOUND THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='period funding requires a claimed idempotency key'; END IF;
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_phase4_period_guard BEFORE INSERT OR UPDATE OR DELETE ON credit_periods
      FOR EACH ROW EXECUTE FUNCTION phase4_period_guard();
    """))


def _sqlite_triggers():
    statements = (
        """CREATE TRIGGER trg_phase4_definition_insert BEFORE INSERT ON entitlement_definitions BEGIN
          SELECT RAISE(ABORT,'invalid entitlement definition payload contract') WHERE
            json_type(NEW.capability_json) IS NOT 'object' OR json_extract(NEW.capability_json,'$.schema_version') IS NOT 1 OR
            json_type(NEW.capability_json,'$.capabilities') IS NOT 'object' OR json_type(NEW.funding_policy_json) IS NOT 'object' OR
            json_extract(NEW.funding_policy_json,'$.schema_version') IS NOT 1 OR
            json_extract(NEW.funding_policy_json,'$.period_kind') IS NULL OR
            json_extract(NEW.funding_policy_json,'$.period_kind') NOT IN ('none','free','monthly_subscription','annual_monthly','enterprise') OR
            json_type(NEW.funding_policy_json,'$.credit_amount') IS NOT 'integer' OR json_extract(NEW.funding_policy_json,'$.credit_amount')<0;
          SELECT RAISE(ABORT,'unlimited benefits are not permitted') WHERE EXISTS (
            SELECT 1 FROM json_tree(NEW.capability_json)
            WHERE lower(COALESCE(key,'')) LIKE '%unlimited%' AND value NOT IN (0,'false') AND value IS NOT NULL
          ) OR EXISTS (
            SELECT 1 FROM json_tree(NEW.funding_policy_json)
            WHERE lower(COALESCE(key,'')) LIKE '%unlimited%' AND value NOT IN (0,'false') AND value IS NOT NULL
          );
        END""",
        """CREATE TRIGGER trg_phase4_definition_update BEFORE UPDATE ON entitlement_definitions BEGIN
          SELECT RAISE(ABORT,'invalid entitlement definition payload contract') WHERE
            json_type(NEW.capability_json) IS NOT 'object' OR json_extract(NEW.capability_json,'$.schema_version') IS NOT 1 OR
            json_type(NEW.capability_json,'$.capabilities') IS NOT 'object' OR json_type(NEW.funding_policy_json) IS NOT 'object' OR
            json_extract(NEW.funding_policy_json,'$.schema_version') IS NOT 1 OR
            json_extract(NEW.funding_policy_json,'$.period_kind') IS NULL OR
            json_extract(NEW.funding_policy_json,'$.period_kind') NOT IN ('none','free','monthly_subscription','annual_monthly','enterprise') OR
            json_type(NEW.funding_policy_json,'$.credit_amount') IS NOT 'integer' OR json_extract(NEW.funding_policy_json,'$.credit_amount')<0;
          SELECT RAISE(ABORT,'unlimited benefits are not permitted') WHERE EXISTS (
            SELECT 1 FROM json_tree(NEW.capability_json)
            WHERE lower(COALESCE(key,'')) LIKE '%unlimited%' AND value NOT IN (0,'false') AND value IS NOT NULL
          ) OR EXISTS (
            SELECT 1 FROM json_tree(NEW.funding_policy_json)
            WHERE lower(COALESCE(key,'')) LIKE '%unlimited%' AND value NOT IN (0,'false') AND value IS NOT NULL
          );
          SELECT RAISE(ABORT,'approved entitlement definition is immutable') WHERE OLD.approved_at IS NOT NULL AND (
            NEW.key IS NOT OLD.key OR NEW.version IS NOT OLD.version OR NEW.exclusivity_key IS NOT OLD.exclusivity_key OR
            NEW.capability_json IS NOT OLD.capability_json OR NEW.funding_policy_json IS NOT OLD.funding_policy_json OR
            NEW.effective_at IS NOT OLD.effective_at OR NEW.approved_at IS NOT OLD.approved_at OR
            (NEW.approved_by_user_id IS NOT OLD.approved_by_user_id AND NOT (
              OLD.approved_by_user_id IS NOT NULL AND NEW.approved_by_user_id IS NULL)) OR
            NEW.approval_evidence_reference IS NOT OLD.approval_evidence_reference OR
            (OLD.retired_at IS NOT NULL AND NEW.retired_at IS NOT OLD.retired_at));
        END""",
        """CREATE TRIGGER trg_phase4_definition_delete BEFORE DELETE ON entitlement_definitions WHEN OLD.approved_at IS NOT NULL
          BEGIN SELECT RAISE(ABORT,'approved entitlement definition cannot be deleted'); END""",
        """CREATE TRIGGER trg_phase4_subscription_update BEFORE UPDATE ON billing_subscriptions BEGIN
          SELECT RAISE(ABORT,'subscription identity, anchor, and origin evidence are immutable') WHERE
            NEW.billing_account_id IS NOT OLD.billing_account_id OR NEW.processor IS NOT OLD.processor OR
            NEW.external_subscription_id IS NOT OLD.external_subscription_id OR NEW.anchor_at IS NOT OLD.anchor_at OR
            NEW.origin_evidence_json IS NOT OLD.origin_evidence_json;
          SELECT RAISE(ABORT,'invalid subscription transition') WHERE NEW.state IS NOT OLD.state AND NOT (
            (OLD.state='proposed' AND NEW.state IN ('incomplete','active','cancelled')) OR
            (OLD.state='incomplete' AND NEW.state IN ('active','cancelled','expired')) OR
            (OLD.state='active' AND NEW.state IN ('past_due','paused','cancel_at_period_end','cancelled','expired')) OR
            (OLD.state='past_due' AND NEW.state IN ('active','unpaid','paused','cancel_at_period_end','cancelled','expired')) OR
            (OLD.state='unpaid' AND NEW.state IN ('active','cancelled','expired')) OR
            (OLD.state='paused' AND NEW.state IN ('active','cancel_at_period_end','cancelled','expired')) OR
            (OLD.state='cancel_at_period_end' AND NEW.state IN ('active','past_due','cancelled','expired')));
          SELECT RAISE(ABORT,'subscription target definition must be approved') WHERE NEW.state<>'proposed' AND NOT EXISTS (
            SELECT 1 FROM entitlement_definitions d WHERE d.id=NEW.current_entitlement_definition_id AND d.approved_at IS NOT NULL);
        END""",
        """CREATE TRIGGER trg_phase4_subscription_insert BEFORE INSERT ON billing_subscriptions BEGIN
          SELECT RAISE(ABORT,'subscription target definition must be approved') WHERE NEW.state<>'proposed' AND NOT EXISTS (
            SELECT 1 FROM entitlement_definitions d WHERE d.id=NEW.current_entitlement_definition_id AND d.approved_at IS NOT NULL);
        END""",
        """CREATE TRIGGER trg_phase4_subscription_delete BEFORE DELETE ON billing_subscriptions
          BEGIN SELECT RAISE(ABORT,'billing subscriptions are historical records'); END""",
        """CREATE TRIGGER trg_phase4_instance_insert BEFORE INSERT ON entitlement_instances BEGIN
          SELECT RAISE(ABORT,'entitlement instance must begin proposed') WHERE NEW.state<>'proposed' OR NEW.last_event_id IS NOT NULL;
          SELECT RAISE(ABORT,'entitlement subscription/account mismatch') WHERE NEW.subscription_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM billing_subscriptions s WHERE s.id=NEW.subscription_id AND s.billing_account_id=NEW.billing_account_id);
        END""",
        """CREATE TRIGGER trg_phase4_instance_update BEFORE UPDATE ON entitlement_instances BEGIN
          SELECT RAISE(ABORT,'entitlement identity and evidence are immutable') WHERE
            NEW.billing_account_id IS NOT OLD.billing_account_id OR NEW.entitlement_definition_id IS NOT OLD.entitlement_definition_id OR
            NEW.subscription_id IS NOT OLD.subscription_id OR NEW.starts_at IS NOT OLD.starts_at OR NEW.ends_at IS NOT OLD.ends_at OR
            NEW.source_type IS NOT OLD.source_type OR NEW.source_id IS NOT OLD.source_id OR
            NEW.approval_evidence_reference IS NOT OLD.approval_evidence_reference OR
            NEW.supersedes_instance_id IS NOT OLD.supersedes_instance_id;
          SELECT RAISE(ABORT,'entitlement state changes require a new authoritative event')
          WHERE (NEW.state IS NOT OLD.state OR NEW.last_event_id IS NOT OLD.last_event_id) AND (
            NEW.last_event_id IS NULL OR NEW.last_event_id IS OLD.last_event_id OR NOT EXISTS (
              SELECT 1 FROM entitlement_events e WHERE e.id=NEW.last_event_id AND e.entitlement_instance_id=NEW.id
                AND e.from_state=OLD.state AND e.to_state=NEW.state));
        END""",
        """CREATE TRIGGER trg_phase4_instance_delete BEFORE DELETE ON entitlement_instances
          BEGIN SELECT RAISE(ABORT,'entitlement instances are historical records'); END""",
        """CREATE TRIGGER trg_phase4_event_before BEFORE INSERT ON entitlement_events BEGIN
          SELECT RAISE(ABORT,'entitlement event requires a claimed idempotency key') WHERE NOT EXISTS (
            SELECT 1 FROM idempotency_registry r WHERE r.id=NEW.idempotency_registry_id AND r.state='claimed');
          SELECT RAISE(ABORT,'entitlement event does not match current state') WHERE NOT EXISTS (
            SELECT 1 FROM entitlement_instances i WHERE i.id=NEW.entitlement_instance_id AND i.state=NEW.from_state);
          SELECT RAISE(ABORT,'invalid entitlement transition') WHERE NOT (
            (NEW.from_state='proposed' AND NEW.to_state IN ('scheduled','cancelled')) OR
            (NEW.from_state='scheduled' AND NEW.to_state IN ('active','superseded','cancelled')) OR
            (NEW.from_state='active' AND NEW.to_state IN ('reducing','expired')) OR
            (NEW.from_state='reducing' AND NEW.to_state IN ('expired','superseded')));
          SELECT RAISE(ABORT,'entitlement transition requires approved evidence') WHERE NEW.to_state<>'cancelled' AND NOT EXISTS (
            SELECT 1 FROM entitlement_instances i JOIN entitlement_definitions d ON d.id=i.entitlement_definition_id
            WHERE i.id=NEW.entitlement_instance_id AND i.approval_evidence_reference IS NOT NULL AND d.approved_at IS NOT NULL);
          SELECT RAISE(ABORT,'incompatible entitlement intervals overlap') WHERE NEW.to_state IN ('scheduled','active','reducing') AND EXISTS (
            SELECT 1 FROM entitlement_instances current_i JOIN entitlement_definitions current_d ON current_d.id=current_i.entitlement_definition_id
            JOIN entitlement_instances other ON other.billing_account_id=current_i.billing_account_id AND other.id<>current_i.id
            JOIN entitlement_definitions other_d ON other_d.id=other.entitlement_definition_id
            WHERE current_i.id=NEW.entitlement_instance_id AND other.state IN ('scheduled','active','reducing')
              AND other_d.exclusivity_key=current_d.exclusivity_key
              AND other.starts_at<COALESCE(current_i.ends_at,'9999-12-31 23:59:59')
              AND current_i.starts_at<COALESCE(other.ends_at,'9999-12-31 23:59:59'));
        END""",
        """CREATE TRIGGER trg_phase4_event_after AFTER INSERT ON entitlement_events BEGIN
          UPDATE entitlement_instances SET state=NEW.to_state,last_event_id=NEW.id,updated_at=CURRENT_TIMESTAMP
          WHERE id=NEW.entitlement_instance_id;
          UPDATE idempotency_registry SET state='completed',completed_at=CURRENT_TIMESTAMP,
            result_type='entitlement_event',result_id=NEW.id,last_error_code=NULL
          WHERE id=NEW.idempotency_registry_id;
        END""",
        """CREATE TRIGGER trg_phase4_event_update BEFORE UPDATE ON entitlement_events
          BEGIN SELECT RAISE(ABORT,'entitlement events are append-only'); END""",
        """CREATE TRIGGER trg_phase4_event_delete BEFORE DELETE ON entitlement_events
          BEGIN SELECT RAISE(ABORT,'entitlement events are append-only'); END""",
        """CREATE TRIGGER trg_phase4_period_insert BEFORE INSERT ON credit_periods BEGIN
          SELECT RAISE(ABORT,'credit period must begin planned and unfunded') WHERE
            NEW.state<>'planned' OR NEW.funding_idempotency_registry_id IS NOT NULL OR NEW.funded_lot_id IS NOT NULL;
          SELECT RAISE(ABORT,'credit period entitlement/account mismatch') WHERE NOT EXISTS (
            SELECT 1 FROM entitlement_instances i WHERE i.id=NEW.entitlement_instance_id AND i.billing_account_id=NEW.billing_account_id
              AND NEW.starts_at>=i.starts_at AND (i.ends_at IS NULL OR NEW.ends_at<=i.ends_at));
          SELECT RAISE(ABORT,'credit period exceeds subscription ownership or term') WHERE NEW.subscription_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM billing_subscriptions s WHERE s.id=NEW.subscription_id AND s.billing_account_id=NEW.billing_account_id
              AND NEW.starts_at>=s.term_starts_at AND NEW.ends_at<=s.term_ends_at);
          SELECT RAISE(ABORT,'credit period uses the wrong immutable anchor') WHERE
            (NEW.kind='free' AND julianday(NEW.anchor_at)<>(SELECT julianday(account_anchor_at) FROM billing_accounts WHERE id=NEW.billing_account_id)) OR
            (NEW.kind IN ('monthly_subscription','annual_monthly') AND julianday(NEW.anchor_at)<>(SELECT julianday(anchor_at) FROM billing_subscriptions WHERE id=NEW.subscription_id));
          SELECT RAISE(ABORT,'credit period boundaries do not match the anchor') WHERE
            julianday(NEW.starts_at)<>julianday(datetime(date(NEW.anchor_at,'start of month',printf('+%d months',NEW.period_index),
              printf('+%d days',min(CAST(strftime('%d',NEW.anchor_at) AS integer)-1,
                CAST(strftime('%d',date(NEW.anchor_at,'start of month',printf('+%d months',NEW.period_index+1),'-1 day')) AS integer)-1))),time(NEW.anchor_at))) OR
            julianday(NEW.ends_at)<>julianday(datetime(date(NEW.anchor_at,'start of month',printf('+%d months',NEW.period_index+1),
              printf('+%d days',min(CAST(strftime('%d',NEW.anchor_at) AS integer)-1,
                CAST(strftime('%d',date(NEW.anchor_at,'start of month',printf('+%d months',NEW.period_index+2),'-1 day')) AS integer)-1))),time(NEW.anchor_at)));
          SELECT RAISE(ABORT,'annual monthly periods cannot overlap') WHERE NEW.kind='annual_monthly' AND EXISTS (
            SELECT 1 FROM credit_periods p WHERE p.subscription_id=NEW.subscription_id AND p.kind='annual_monthly' AND p.state<>'expired'
              AND p.starts_at<NEW.ends_at AND NEW.starts_at<p.ends_at);
        END""",
        """CREATE TRIGGER trg_phase4_period_update BEFORE UPDATE ON credit_periods BEGIN
          SELECT RAISE(ABORT,'credit period identity and funding result are immutable') WHERE
            NEW.billing_account_id IS NOT OLD.billing_account_id OR NEW.entitlement_instance_id IS NOT OLD.entitlement_instance_id OR
            NEW.subscription_id IS NOT OLD.subscription_id OR NEW.kind IS NOT OLD.kind OR NEW.period_index IS NOT OLD.period_index OR
            NEW.anchor_at IS NOT OLD.anchor_at OR NEW.starts_at IS NOT OLD.starts_at OR NEW.ends_at IS NOT OLD.ends_at OR
            NEW.planned_allocation_amount IS NOT OLD.planned_allocation_amount OR
            (OLD.funding_idempotency_registry_id IS NOT NULL AND NEW.funding_idempotency_registry_id IS NOT OLD.funding_idempotency_registry_id) OR
            (OLD.funded_lot_id IS NOT NULL AND NEW.funded_lot_id IS NOT OLD.funded_lot_id);
          SELECT RAISE(ABORT,'invalid credit period transition') WHERE NEW.state IS NOT OLD.state AND NOT (
            (OLD.state='planned' AND NEW.state IN ('funded','unfunded','expired')) OR
            (OLD.state='unfunded' AND NEW.state IN ('funded','expired')) OR (OLD.state='funded' AND NEW.state='expired'));
          SELECT RAISE(ABORT,'funded period does not match its authoritative lot and grant') WHERE NEW.state='funded' AND NOT EXISTS (
            SELECT 1 FROM credit_lots lot JOIN credit_ledger_entries entry ON entry.lot_id=lot.id
            WHERE lot.id=NEW.funded_lot_id AND lot.billing_account_id=NEW.billing_account_id AND lot.source_id=NEW.id
              AND lot.original_amount=NEW.planned_allocation_amount AND julianday(lot.available_at)=julianday(NEW.starts_at)
              AND julianday(lot.expires_at)=julianday(NEW.ends_at) AND entry.entry_type='grant'
              AND entry.available_delta=NEW.planned_allocation_amount AND entry.held_delta=0
              AND entry.idempotency_registry_id=NEW.funding_idempotency_registry_id);
          SELECT RAISE(ABORT,'period funding requires a claimed idempotency key') WHERE NEW.state='funded' AND NOT EXISTS (
            SELECT 1 FROM idempotency_registry r WHERE r.id=NEW.funding_idempotency_registry_id AND r.state='claimed');
          UPDATE idempotency_registry SET state='completed',completed_at=CURRENT_TIMESTAMP,
            result_type='credit_period',result_id=NEW.id,last_error_code=NULL
          WHERE NEW.state='funded' AND id=NEW.funding_idempotency_registry_id;
        END""",
        """CREATE TRIGGER trg_phase4_period_delete BEFORE DELETE ON credit_periods
          BEGIN SELECT RAISE(ABORT,'credit periods are historical records'); END""",
    )
    for statement in statements:
        op.execute(sa.text(statement))


def upgrade():
    _create_tables()
    if op.get_bind().dialect.name == "postgresql":
        _postgresql_triggers()
    elif op.get_bind().dialect.name == "sqlite":
        _sqlite_triggers()


def _guard_empty():
    bind = op.get_bind()
    populated = [table for table in PHASE_4_TABLES if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first()]
    if populated:
        raise EntitlementFoundationNotEmptyError(
            "refusing to remove nonempty Phase 4 tables: " + ", ".join(populated)
        )


def downgrade():
    _guard_empty()
    if op.get_bind().dialect.name == "postgresql":
        for trigger, table in (
            ("trg_phase4_period_guard", "credit_periods"),
            ("trg_phase4_event_immutable", "entitlement_events"),
            ("trg_phase4_event_after", "entitlement_events"),
            ("trg_phase4_event_before", "entitlement_events"),
            ("trg_phase4_instance_guard", "entitlement_instances"),
            ("trg_phase4_subscription_guard", "billing_subscriptions"),
            ("trg_phase4_subscription_insert_guard", "billing_subscriptions"),
            ("trg_phase4_definition_guard", "entitlement_definitions"),
        ):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger} ON {table}"))
        for function in (
            "phase4_period_guard", "phase4_event_immutable", "phase4_event_after",
            "phase4_event_before", "phase4_instance_guard", "phase4_subscription_guard",
            "phase4_subscription_insert_guard", "phase4_definition_guard",
        ):
            op.execute(sa.text(f"DROP FUNCTION IF EXISTS {function}()"))
        op.execute(sa.text("DROP FUNCTION IF EXISTS phase4_add_months(timestamptz, integer)"))
        op.execute(sa.text("DROP FUNCTION IF EXISTS phase4_json_has_unlimited(jsonb)"))
    op.drop_table("entitlement_events")
    op.drop_table("credit_periods")
    op.drop_table("entitlement_instances")
    op.drop_table("billing_subscriptions")
    op.drop_table("entitlement_definitions")
