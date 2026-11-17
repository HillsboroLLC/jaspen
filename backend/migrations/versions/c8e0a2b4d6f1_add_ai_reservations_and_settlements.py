"""Phase 12: AI reservations, capacity authorization, and delivery-based settlement.

Adds five inactive evidence tables (lifecycle specification D06, D21, D22,
D23; founder-approved delivery-based billability of 2026-11-11 as amended
2026-11-16) and database guards that make Phase 12 the only path to an AI
reservation or settlement:

* a credit reservation needs an authorized Phase 12 operation bound to the same
  pricing and capacity versions (``capacity_policy_version_id`` is therefore
  always set for new reservations);
* a reservation or settlement ledger entry needs an authorized Phase 12
  operation whose reservation lease is live at the actual database time;
* a settlement names its delivering attempt, every call of that attempt must
  be provider-reported and the last one successful (an undelivered or
  uncertain response is never charged), and the operation's settlements can
  never exceed that attempt's usage priced under the bound version;
* the lease is renewed only forward, only while live, and never past the
  execution deadline plus one lease period; an operation is charged (finalized
  as delivered) only while its lease is live and expires only after it lapsed;
  an expired operation's delivery answer names an attempt that ended in a
  successful call;
* the binding requires the effective pricing and capacity versions at the
  actual database time, and an active member of the billing organization;
* capacity decisions, provider call usage, and checkpoints are immutable;
  absorbed usage changes only its provider-dispute status, forward; an
  operation's binding and bounds are immutable and it is finalized by exactly
  one update (an expired operation then only adds late absorbed evidence and
  records, once, what became of its "unsettled" response, never a charge).

No earlier guard is replaced. Downgrade refuses while any Phase 12 row exists.
No rate, conversion, or capacity number is seeded.

Revision ID: c8e0a2b4d6f1
Revises: b4d6f8a0c2e5
"""

from alembic import op
import sqlalchemy as sa


revision = "c8e0a2b4d6f1"
down_revision = "b4d6f8a0c2e5"
branch_labels = None
depends_on = None


TABLES = (
    "ai_operation_checkpoints", "ai_absorbed_usage", "ai_provider_call_usage",
    "ai_capacity_decisions", "ai_billing_operations",
)
IMMUTABLE_TABLES = ("ai_capacity_decisions", "ai_provider_call_usage", "ai_operation_checkpoints")


class Phase12EvidenceNotEmptyError(RuntimeError):
    """Downgrade refuses to discard AI billing evidence."""


def _create_tables():
    op.create_table(
        'ai_billing_operations',
        sa.Column('operation_id', sa.String(36), primary_key=True),
        sa.Column('billing_account_id', sa.String(36), nullable=False),
        sa.Column('organization_id', sa.String(36), nullable=False),
        sa.Column('actor_user_id', sa.String(36), nullable=False),
        sa.Column('pricing_policy_version_id', sa.String(36), nullable=False),
        sa.Column('capacity_policy_version_id', sa.String(36), nullable=False),
        sa.Column('root_operation_id', sa.String(36), nullable=True),
        sa.Column('resumed_from_operation_id', sa.String(36), nullable=True),
        sa.Column('step_key', sa.String(160), nullable=False),
        sa.Column('idempotency_registry_id', sa.String(36), nullable=False),
        sa.Column('request_fingerprint', sa.String(64), nullable=False),
        sa.Column('candidates_json', sa.JSON(), nullable=False),
        sa.Column('tier_key', sa.String(80), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('max_provider_attempts', sa.Integer(), nullable=False),
        sa.Column('max_tool_iterations', sa.Integer(), nullable=False),
        sa.Column('max_call_input_tokens', sa.BigInteger(), nullable=False),
        sa.Column('max_call_output_tokens', sa.BigInteger(), nullable=False),
        sa.Column('max_operation_tokens', sa.BigInteger(), nullable=False),
        sa.Column('lease_seconds', sa.Integer(), nullable=False),
        sa.Column('initial_hold_credits', sa.BigInteger(), nullable=False),
        sa.Column('reservation_ceiling_credits', sa.BigInteger(), nullable=False),
        sa.Column('state', sa.String(24), nullable=False),
        sa.Column('delivery_status', sa.String(24), nullable=True),
        sa.Column('delivered_attempt_number', sa.Integer(), nullable=True),
        sa.Column('charged_credits', sa.BigInteger(), nullable=True),
        sa.Column('absorbed_credits', sa.BigInteger(), nullable=True),
        sa.Column('available_again_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('authorized_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('execution_deadline_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finalized_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finalization_evidence_json', sa.JSON(), nullable=True),
        sa.CheckConstraint('charged_credits IS NULL OR (charged_credits >= 0 AND absorbed_credits >= 0)', name='ck_ai_billing_operations_amounts'),
        sa.CheckConstraint('max_provider_attempts > 0 AND max_tool_iterations >= 0 AND initial_hold_credits > 0 AND reservation_ceiling_credits >= initial_hold_credits AND max_call_input_tokens > 0 AND max_call_output_tokens > 0 AND max_operation_tokens > 0 AND lease_seconds > 0', name='ck_ai_billing_operations_bounds'),
        sa.CheckConstraint("(delivery_status = 'delivered' AND delivered_attempt_number IS NOT NULL) OR ((delivery_status IS NULL OR delivery_status != 'delivered') AND delivered_attempt_number IS NULL)", name='ck_ai_billing_operations_delivered_attempt'),
        sa.CheckConstraint("delivery_status IS NULL OR delivery_status IN ('delivered','undelivered','no_billable_usage','unsettled')", name='ck_ai_billing_operations_delivery_status'),
        sa.CheckConstraint("state = 'capacity_denied' OR available_again_at IS NULL", name='ck_ai_billing_operations_denial_time'),
        sa.CheckConstraint('expires_at > authorized_at AND execution_deadline_at > authorized_at', name='ck_ai_billing_operations_expiry'),
        sa.CheckConstraint("(state = 'authorized' AND finalized_at IS NULL) OR (state != 'authorized' AND finalized_at IS NOT NULL)", name='ck_ai_billing_operations_finalization'),
        sa.CheckConstraint('length(request_fingerprint) = 64 AND request_fingerprint = lower(request_fingerprint)', name='ck_ai_billing_operations_fingerprint'),
        sa.CheckConstraint('length(trim(step_key)) > 0 AND length(trim(tier_key)) > 0', name='ck_ai_billing_operations_identity_text'),
        sa.CheckConstraint('(root_operation_id IS NULL AND resumed_from_operation_id IS NULL) OR (root_operation_id IS NOT NULL AND resumed_from_operation_id IS NOT NULL AND root_operation_id != operation_id AND resumed_from_operation_id != operation_id)', name='ck_ai_billing_operations_lineage'),
        sa.CheckConstraint("(state = 'finalized' AND delivery_status IS NOT NULL AND delivery_status != 'unsettled' AND charged_credits IS NOT NULL AND absorbed_credits IS NOT NULL) OR (state = 'expired' AND delivery_status IS NOT NULL AND charged_credits = 0 AND absorbed_credits IS NOT NULL) OR (state IN ('authorized', 'capacity_denied') AND delivery_status IS NULL AND charged_credits IS NULL)", name='ck_ai_billing_operations_outcome'),
        sa.CheckConstraint("state IN ('authorized','capacity_denied','finalized','expired')", name='ck_ai_billing_operations_state'),
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], name='fk_ai_billing_operations_actor_user_id', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['billing_account_id'], ['billing_accounts.id'], name='fk_ai_billing_operations_billing_account_id', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['capacity_policy_version_id'], ['capacity_policy_versions.id'], name='fk_ai_billing_operations_capacity_policy_version_id', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['idempotency_registry_id'], ['idempotency_registry.id'], name='fk_ai_billing_operations_idempotency_registry_id', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['operation_id'], ['ai_operations.id'], name='fk_ai_billing_operations_operation_id', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name='fk_ai_billing_operations_organization_id', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['pricing_policy_version_id'], ['pricing_policy_versions.id'], name='fk_ai_billing_operations_pricing_policy_version_id', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['resumed_from_operation_id'], ['ai_billing_operations.operation_id'], name='fk_ai_billing_operations_resumed_from_operation_id'),
        sa.ForeignKeyConstraint(['root_operation_id'], ['ai_billing_operations.operation_id'], name='fk_ai_billing_operations_root_operation_id'),
        sa.UniqueConstraint('idempotency_registry_id', name='uq_ai_billing_operations_idempotency_registry_id'),
    )
    op.create_index('ix_ai_billing_operations_account_state_expiry', 'ai_billing_operations', ['billing_account_id', 'state', 'expires_at'])
    op.create_index('ix_ai_billing_operations_capacity_policy_version_id', 'ai_billing_operations', ['capacity_policy_version_id'])
    op.create_index('ix_ai_billing_operations_org_member_state', 'ai_billing_operations', ['organization_id', 'actor_user_id', 'state'])
    op.create_index('ix_ai_billing_operations_pricing_policy_version_id', 'ai_billing_operations', ['pricing_policy_version_id'])
    op.create_index('ix_ai_billing_operations_root_operation_id', 'ai_billing_operations', ['root_operation_id'])
    op.create_table(
        'ai_capacity_decisions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('operation_id', sa.String(36), nullable=False),
        sa.Column('capacity_policy_version_id', sa.String(36), nullable=False),
        sa.Column('organization_id', sa.String(36), nullable=False),
        sa.Column('member_user_id', sa.String(36), nullable=False),
        sa.Column('window_key', sa.String(160), nullable=False),
        sa.Column('tier_key', sa.String(80), nullable=False),
        sa.Column('outcome', sa.String(16), nullable=False),
        sa.Column('reason_code', sa.String(40), nullable=True),
        sa.Column('available_again_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('evidence_json', sa.JSON(), nullable=False),
        sa.CheckConstraint("outcome IN ('authorized','denied')", name='ck_ai_capacity_decisions_outcome'),
        sa.CheckConstraint("(outcome = 'authorized' AND reason_code IS NULL AND available_again_at IS NULL) OR (outcome = 'denied' AND reason_code IN ('account_restricted','organization_window','member_window','organization_concurrency','member_concurrency','provider_pressure'))", name='ck_ai_capacity_decisions_reason'),
        sa.ForeignKeyConstraint(['capacity_policy_version_id'], ['capacity_policy_versions.id'], name='fk_ai_capacity_decisions_capacity_policy_version_id', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['member_user_id'], ['users.id'], name='fk_ai_capacity_decisions_member_user_id', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['operation_id'], ['ai_billing_operations.operation_id'], name='fk_ai_capacity_decisions_operation_id', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name='fk_ai_capacity_decisions_organization_id', ondelete='RESTRICT'),
        sa.UniqueConstraint('operation_id', name='uq_ai_capacity_decisions_operation_id'),
        sa.UniqueConstraint('capacity_policy_version_id', 'operation_id', 'window_key', name='uq_ai_capacity_decisions_policy_operation_window'),
    )
    op.create_index('ix_ai_capacity_decisions_member_outcome_decided', 'ai_capacity_decisions', ['member_user_id', 'outcome', 'decided_at'])
    op.create_index('ix_ai_capacity_decisions_org_outcome_decided', 'ai_capacity_decisions', ['organization_id', 'outcome', 'decided_at'])
    op.create_table(
        'ai_provider_call_usage',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('operation_id', sa.String(36), nullable=False),
        sa.Column('attempt_number', sa.Integer(), nullable=False),
        sa.Column('call_index', sa.Integer(), nullable=False),
        sa.Column('component', sa.String(24), nullable=False),
        sa.Column('provider', sa.String(32), nullable=False),
        sa.Column('model', sa.String(255), nullable=False),
        sa.Column('provider_rate_entry_id', sa.String(36), nullable=False),
        sa.Column('outcome', sa.String(16), nullable=False),
        sa.Column('error_category', sa.String(80), nullable=True),
        sa.Column('usage_label', sa.String(16), nullable=False),
        sa.Column('input_tokens', sa.BigInteger(), nullable=True),
        sa.Column('output_tokens', sa.BigInteger(), nullable=True),
        sa.Column('provider_reported_cost_usd', sa.Numeric(30, 16), nullable=True),
        sa.Column('computed_cost_usd', sa.Numeric(30, 16), nullable=True),
        sa.Column('provider_request_id', sa.String(255), nullable=True),
        sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('request_fingerprint', sa.String(64), nullable=False),
        sa.CheckConstraint("component IN ('primary','retry','fallback','tool_iteration','context_expansion')", name='ck_ai_provider_call_usage_component'),
        sa.CheckConstraint("outcome = 'succeeded' OR error_category IS NOT NULL", name='ck_ai_provider_call_usage_error'),
        sa.CheckConstraint('length(request_fingerprint) = 64 AND request_fingerprint = lower(request_fingerprint)', name='ck_ai_provider_call_usage_fingerprint'),
        sa.CheckConstraint("usage_label IN ('reported','estimated','unknown')", name='ck_ai_provider_call_usage_label'),
        sa.CheckConstraint("outcome IN ('succeeded','failed','timeout','refused','cancelled')", name='ck_ai_provider_call_usage_outcome'),
        sa.CheckConstraint('provider_reported_cost_usd IS NULL OR provider_reported_cost_usd >= 0', name='ck_ai_provider_call_usage_reported_cost'),
        sa.CheckConstraint('attempt_number > 0 AND call_index >= 0', name='ck_ai_provider_call_usage_sequence'),
        sa.CheckConstraint('finished_at IS NULL OR finished_at >= requested_at', name='ck_ai_provider_call_usage_times'),
        sa.CheckConstraint("(usage_label = 'unknown' AND input_tokens IS NULL AND output_tokens IS NULL AND computed_cost_usd IS NULL) OR (usage_label != 'unknown' AND input_tokens >= 0 AND output_tokens >= 0 AND computed_cost_usd >= 0)", name='ck_ai_provider_call_usage_tokens'),
        sa.ForeignKeyConstraint(['operation_id'], ['ai_billing_operations.operation_id'], name='fk_ai_provider_call_usage_operation_id', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['provider_rate_entry_id'], ['provider_rate_entries.id'], name='fk_ai_provider_call_usage_provider_rate_entry_id', ondelete='RESTRICT'),
        sa.UniqueConstraint('operation_id', 'attempt_number', 'call_index', name='uq_ai_provider_call_usage_operation_attempt_call'),
    )
    op.create_table(
        'ai_absorbed_usage',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('operation_id', sa.String(36), nullable=False),
        sa.Column('billing_account_id', sa.String(36), nullable=False),
        sa.Column('attempt_number', sa.Integer(), nullable=True),
        sa.Column('provider', sa.String(32), nullable=True),
        sa.Column('model', sa.String(255), nullable=True),
        sa.Column('provider_call_ids_json', sa.JSON(), nullable=False),
        sa.Column('provider_request_ids_json', sa.JSON(), nullable=False),
        sa.Column('usage_label', sa.String(16), nullable=False),
        sa.Column('input_tokens', sa.BigInteger(), nullable=True),
        sa.Column('output_tokens', sa.BigInteger(), nullable=True),
        sa.Column('provider_reported_cost_usd', sa.Numeric(30, 16), nullable=True),
        sa.Column('computed_cost_usd', sa.Numeric(30, 16), nullable=True),
        sa.Column('absorbed_cost_usd', sa.Numeric(30, 16), nullable=True),
        sa.Column('absorbed_credits', sa.BigInteger(), nullable=True),
        sa.Column('reason', sa.String(32), nullable=False),
        sa.Column('delivery_status', sa.String(24), nullable=False),
        sa.Column('error_category', sa.String(80), nullable=True),
        sa.Column('fallback_attempted', sa.Boolean(), nullable=False),
        sa.Column('fallback_outcome', sa.String(24), nullable=True),
        sa.Column('requested_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('failed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('provider_dispute_status', sa.String(16), nullable=False, server_default='none'),
        sa.Column('provider_dispute_resolution', sa.String(500), nullable=True),
        sa.CheckConstraint('(absorbed_cost_usd IS NULL OR absorbed_cost_usd >= 0) AND (absorbed_credits IS NULL OR absorbed_credits >= 0) AND (absorbed_cost_usd IS NULL OR absorbed_cost_usd <= computed_cost_usd)', name='ck_ai_absorbed_usage_amounts'),
        sa.CheckConstraint("delivery_status IN ('delivered','undelivered','no_billable_usage','unsettled')", name='ck_ai_absorbed_usage_delivery_status'),
        sa.CheckConstraint("provider_dispute_status = 'resolved' OR provider_dispute_resolution IS NULL", name='ck_ai_absorbed_usage_dispute_resolution'),
        sa.CheckConstraint("provider_dispute_status IN ('none','open','resolved')", name='ck_ai_absorbed_usage_dispute_status'),
        sa.CheckConstraint("usage_label IN ('reported','estimated','unknown')", name='ck_ai_absorbed_usage_label'),
        sa.CheckConstraint("reason IN ('undelivered','not_delivering_attempt','above_reservation_cap','uncertain_usage','reservation_expired','step_already_settled')", name='ck_ai_absorbed_usage_reason'),
        sa.ForeignKeyConstraint(['billing_account_id'], ['billing_accounts.id'], name='fk_ai_absorbed_usage_billing_account_id', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['operation_id'], ['ai_billing_operations.operation_id'], name='fk_ai_absorbed_usage_operation_id', ondelete='RESTRICT'),
    )
    op.create_index('ix_ai_absorbed_usage_account_recorded', 'ai_absorbed_usage', ['billing_account_id', 'recorded_at'])
    op.create_index('ix_ai_absorbed_usage_operation_id', 'ai_absorbed_usage', ['operation_id'])
    op.create_table(
        'ai_operation_checkpoints',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('root_operation_id', sa.String(36), nullable=False),
        sa.Column('step_key', sa.String(160), nullable=False),
        sa.Column('operation_id', sa.String(36), nullable=False),
        sa.Column('charged_credits', sa.BigInteger(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('charged_credits >= 0', name='ck_ai_operation_checkpoints_charged'),
        sa.ForeignKeyConstraint(['operation_id'], ['ai_billing_operations.operation_id'], name='fk_ai_operation_checkpoints_operation_id', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['root_operation_id'], ['ai_billing_operations.operation_id'], name='fk_ai_operation_checkpoints_root_operation_id', ondelete='RESTRICT'),
        sa.UniqueConstraint('operation_id', name='uq_ai_operation_checkpoints_operation_id'),
        sa.UniqueConstraint('root_operation_id', 'step_key', name='uq_ai_operation_checkpoints_root_step'),
    )


IDENTITY_COLUMNS = (
    "billing_account_id", "organization_id", "actor_user_id", "pricing_policy_version_id",
    "capacity_policy_version_id", "root_operation_id", "resumed_from_operation_id", "step_key",
    "idempotency_registry_id", "request_fingerprint", "tier_key", "priority", "max_provider_attempts",
    "max_tool_iterations", "max_call_input_tokens", "max_call_output_tokens", "max_operation_tokens",
    "lease_seconds", "initial_hold_credits", "reservation_ceiling_credits", "authorized_at",
    "execution_deadline_at",
)


def _pg_guards():
    identity = " OR ".join(f"NEW.{c} IS DISTINCT FROM OLD.{c}" for c in IDENTITY_COLUMNS)
    yield """
        CREATE FUNCTION phase12_operation_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION USING ERRCODE = '55000',
                    MESSAGE = 'Phase 12 operations are immutable history';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.state <> 'authorized'
                   OR NEW.expires_at > NEW.execution_deadline_at + make_interval(secs => NEW.lease_seconds) THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'a Phase 12 operation starts authorized within its lease bound';
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pricing_policy_versions
                               WHERE id = NEW.pricing_policy_version_id AND state = 'effective'
                                 AND effective_at <= clock_timestamp()) THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'Phase 12 binding requires the effective pricing policy';
                END IF;
                IF NOT EXISTS (SELECT 1 FROM capacity_policy_versions
                               WHERE id = NEW.capacity_policy_version_id AND state = 'effective'
                                 AND effective_at <= clock_timestamp()) THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'Phase 12 binding requires the effective capacity policy';
                END IF;
                IF NOT EXISTS (SELECT 1 FROM billing_accounts
                               WHERE id = NEW.billing_account_id AND organization_id = NEW.organization_id)
                   OR NOT EXISTS (SELECT 1 FROM ai_operations
                                  WHERE id = NEW.operation_id AND organization_id = NEW.organization_id
                                    AND user_id = NEW.actor_user_id)
                   OR NOT EXISTS (SELECT 1 FROM organization_members
                                  WHERE organization_id = NEW.organization_id AND user_id = NEW.actor_user_id
                                    AND status = 'active') THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'Phase 12 binding must match the operation, its organization, and an active member';
                END IF;
                RETURN NEW;
            END IF;
            IF NEW.operation_id IS DISTINCT FROM OLD.operation_id OR """ + identity + """
               OR NEW.candidates_json::text IS DISTINCT FROM OLD.candidates_json::text THEN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    MESSAGE = 'Phase 12 operation binding and identity are immutable';
            END IF;
            IF OLD.state IN ('finalized', 'capacity_denied') THEN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    MESSAGE = 'a finalized Phase 12 operation is immutable';
            END IF;
            IF OLD.state = 'expired' AND (
                NEW.state <> 'expired' OR NEW.finalized_at IS DISTINCT FROM OLD.finalized_at
                OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
                OR (NEW.delivery_status IS DISTINCT FROM OLD.delivery_status AND OLD.delivery_status <> 'unsettled')
                OR (NEW.delivered_attempt_number IS DISTINCT FROM OLD.delivered_attempt_number
                    AND OLD.delivery_status <> 'unsettled')
                OR NEW.charged_credits IS DISTINCT FROM OLD.charged_credits
                OR NEW.absorbed_credits < OLD.absorbed_credits
                OR NEW.available_again_at IS DISTINCT FROM OLD.available_again_at
                OR NEW.finalization_evidence_json::text IS DISTINCT FROM OLD.finalization_evidence_json::text
            ) THEN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    MESSAGE = 'an expired (finalized) Phase 12 operation only records late evidence and is never charged';
            END IF;
            IF OLD.state = 'expired' AND NEW.delivery_status = 'delivered'
               AND NEW.delivery_status IS DISTINCT FROM OLD.delivery_status AND NOT EXISTS (
                   SELECT 1 FROM ai_provider_call_usage u
                   WHERE u.operation_id = NEW.operation_id AND u.attempt_number = NEW.delivered_attempt_number
                     AND u.outcome = 'succeeded'
                     AND u.call_index = (SELECT max(v.call_index) FROM ai_provider_call_usage v
                                         WHERE v.operation_id = NEW.operation_id
                                           AND v.attempt_number = NEW.delivered_attempt_number)) THEN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    MESSAGE = 'a delivery after a lapsed lease names an attempt that ended in a successful call';
            END IF;
            IF OLD.state = 'authorized' THEN
                IF NEW.expires_at IS DISTINCT FROM OLD.expires_at AND NOT (
                    NEW.state = 'authorized' AND NEW.expires_at > OLD.expires_at
                    AND NEW.expires_at <= OLD.execution_deadline_at + make_interval(secs => OLD.lease_seconds)
                    AND clock_timestamp() < OLD.expires_at
                ) THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'a reservation lease is renewed only forward, while live, within its bound';
                END IF;
                IF NEW.state = 'finalized' AND NEW.delivery_status = 'delivered'
                   AND clock_timestamp() >= OLD.expires_at THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'a lapsed reservation lease cannot settle as delivered';
                END IF;
                IF NEW.state = 'expired' AND clock_timestamp() < OLD.expires_at THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'an operation expires only after its reservation lease lapsed';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """
    yield """
        CREATE TRIGGER trg_phase12_operation_guard
        BEFORE INSERT OR UPDATE OR DELETE ON ai_billing_operations
        FOR EACH ROW EXECUTE FUNCTION phase12_operation_guard()
    """
    yield """
        CREATE FUNCTION phase12_reservation_guard() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM ai_billing_operations b
                JOIN ai_operations o ON o.id = b.operation_id
                WHERE b.operation_id = NEW.operation_id AND b.state = 'authorized'
                  AND b.billing_account_id = NEW.billing_account_id
                  AND b.pricing_policy_version_id = NEW.pricing_policy_version_id
                  AND b.capacity_policy_version_id IS NOT DISTINCT FROM NEW.capacity_policy_version_id
                  AND o.pricing_policy_version_id = NEW.pricing_policy_version_id
                  AND o.capacity_policy_version_id IS NOT DISTINCT FROM NEW.capacity_policy_version_id
            ) THEN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    MESSAGE = 'credit reservations require a Phase 12 operation binding';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """
    yield """
        CREATE TRIGGER trg_phase12_reservation_guard
        BEFORE INSERT ON credit_reservations
        FOR EACH ROW EXECUTE FUNCTION phase12_reservation_guard()
    """
    yield """
        CREATE FUNCTION phase12_ledger_guard() RETURNS trigger AS $$
        DECLARE
            bound_state VARCHAR(24);
            bound_expires TIMESTAMPTZ;
            bound_pricing VARCHAR(36);
            attempt INTEGER;
            conversion NUMERIC;
            priced NUMERIC;
            settled NUMERIC;
        BEGIN
            SELECT state, expires_at, pricing_policy_version_id
            INTO bound_state, bound_expires, bound_pricing
            FROM ai_billing_operations WHERE operation_id = NEW.operation_id;
            IF bound_state IS DISTINCT FROM 'authorized' OR clock_timestamp() >= bound_expires THEN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    MESSAGE = 'AI reservations and settlements require an authorized Phase 12 operation with a live lease';
            END IF;
            IF NEW.entry_type = 'settlement' THEN
                attempt := CASE WHEN (NEW.evidence_json->>'delivered_attempt_number') ~ '^[0-9]+$'
                                THEN (NEW.evidence_json->>'delivered_attempt_number')::integer END;
                IF attempt IS NULL OR EXISTS (
                    SELECT 1 FROM ai_provider_call_usage
                    WHERE operation_id = NEW.operation_id AND attempt_number = attempt AND usage_label <> 'reported'
                ) OR NOT EXISTS (
                    SELECT 1 FROM ai_provider_call_usage u
                    WHERE u.operation_id = NEW.operation_id AND u.attempt_number = attempt
                      AND u.outcome = 'succeeded'
                      AND u.call_index = (SELECT max(call_index) FROM ai_provider_call_usage
                                          WHERE operation_id = NEW.operation_id AND attempt_number = attempt)
                ) THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'a settlement requires reported usage of the delivered attempt';
                END IF;
                -- Exact: credits <= ceil(priced / 1e6) <=> (credits - 1) * 1e6 < priced.
                SELECT (conversion_json->>'credits_per_provider_usd')::numeric INTO conversion
                FROM pricing_policy_versions WHERE id = bound_pricing;
                SELECT SUM(u.input_tokens * r.input_rate + u.output_tokens * r.output_rate) * conversion
                INTO priced
                FROM ai_provider_call_usage u
                JOIN provider_rate_entries r ON r.id = u.provider_rate_entry_id
                WHERE u.operation_id = NEW.operation_id AND u.attempt_number = attempt
                  AND r.pricing_policy_version_id = bound_pricing;
                SELECT COALESCE(-SUM(held_delta), 0) - NEW.held_delta INTO settled
                FROM credit_ledger_entries
                WHERE operation_id = NEW.operation_id AND entry_type = 'settlement';
                IF priced IS NULL OR (settled - 1) * 1000000 >= priced THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'a settlement cannot exceed the delivered attempt''s priced usage';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """
    yield """
        CREATE TRIGGER trg_phase12_ledger_guard
        BEFORE INSERT ON credit_ledger_entries
        FOR EACH ROW WHEN (NEW.entry_type IN ('reservation', 'settlement'))
        EXECUTE FUNCTION phase12_ledger_guard()
    """
    yield """
        CREATE FUNCTION phase12_reject_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION USING ERRCODE = '55000', MESSAGE = 'Phase 12 evidence is immutable';
        END;
        $$ LANGUAGE plpgsql
    """
    for table in IMMUTABLE_TABLES:
        yield f"""
        CREATE TRIGGER trg_phase12_{table}_immutable
        BEFORE UPDATE OR DELETE ON {table}
        FOR EACH ROW EXECUTE FUNCTION phase12_reject_mutation()
    """
    yield """
        CREATE FUNCTION phase12_absorbed_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' OR (to_jsonb(NEW) - 'provider_dispute_status' - 'provider_dispute_resolution')
                   IS DISTINCT FROM (to_jsonb(OLD) - 'provider_dispute_status' - 'provider_dispute_resolution')
               OR OLD.provider_dispute_status = 'resolved'
               OR (OLD.provider_dispute_status = 'open' AND NEW.provider_dispute_status = 'none') THEN
                RAISE EXCEPTION USING ERRCODE = '55000',
                    MESSAGE = 'absorbed usage evidence is immutable; only its provider dispute status moves forward';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """
    yield """
        CREATE TRIGGER trg_phase12_absorbed_guard
        BEFORE UPDATE OR DELETE ON ai_absorbed_usage
        FOR EACH ROW EXECUTE FUNCTION phase12_absorbed_guard()
    """


PG_FUNCTIONS = (
    "phase12_operation_guard", "phase12_reservation_guard", "phase12_ledger_guard",
    "phase12_reject_mutation", "phase12_absorbed_guard",
)
PG_TRIGGERS = (
    ("trg_phase12_operation_guard", "ai_billing_operations"),
    ("trg_phase12_reservation_guard", "credit_reservations"),
    ("trg_phase12_ledger_guard", "credit_ledger_entries"),
    ("trg_phase12_absorbed_guard", "ai_absorbed_usage"),
) + tuple((f"trg_phase12_{table}_immutable", table) for table in IMMUTABLE_TABLES)


def _sqlite_guards():
    """SQLite parity for immutability and the reservation/settlement paths.

    SQLite has no exact numeric or trustworthy clock comparison here, so the
    lease-time checks and the priced-usage cap are PostgreSQL-only; the
    service enforces both on every dialect.
    """
    identity = " OR ".join(f"NEW.{c} IS NOT OLD.{c}" for c in IDENTITY_COLUMNS)
    statements = {}
    for table in IMMUTABLE_TABLES:
        for action in ("update", "delete"):
            name = {"ai_capacity_decisions": "decisions", "ai_provider_call_usage": "usage",
                    "ai_operation_checkpoints": "checkpoints"}[table]
            statements[f"trg_phase12_{name}_{action}"] = (
                f"CREATE TRIGGER trg_phase12_{name}_{action} BEFORE {action.upper()} ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'Phase 12 evidence is immutable'); END"
            )
    statements["trg_phase12_absorbed_update"] = (
        "CREATE TRIGGER trg_phase12_absorbed_update BEFORE UPDATE ON ai_absorbed_usage "
        "WHEN NEW.operation_id IS NOT OLD.operation_id OR NEW.absorbed_credits IS NOT OLD.absorbed_credits "
        "OR NEW.absorbed_cost_usd IS NOT OLD.absorbed_cost_usd OR NEW.reason IS NOT OLD.reason "
        "OR NEW.usage_label IS NOT OLD.usage_label OR NEW.provider_call_ids_json IS NOT OLD.provider_call_ids_json "
        "OR NEW.recorded_at IS NOT OLD.recorded_at OR OLD.provider_dispute_status = 'resolved' "
        "OR (OLD.provider_dispute_status = 'open' AND NEW.provider_dispute_status = 'none') "
        "BEGIN SELECT RAISE(ABORT, 'absorbed usage evidence is immutable'); END"
    )
    statements["trg_phase12_absorbed_delete"] = (
        "CREATE TRIGGER trg_phase12_absorbed_delete BEFORE DELETE ON ai_absorbed_usage "
        "BEGIN SELECT RAISE(ABORT, 'absorbed usage evidence is immutable'); END"
    )
    statements["trg_phase12_operation_update"] = (
        "CREATE TRIGGER trg_phase12_operation_update BEFORE UPDATE ON ai_billing_operations "
        f"WHEN NEW.operation_id IS NOT OLD.operation_id OR {identity} "
        "OR OLD.state IN ('finalized', 'capacity_denied') "
        "OR (OLD.state = 'expired' AND (NEW.state IS NOT 'expired' "
        "OR (NEW.delivery_status IS NOT OLD.delivery_status AND OLD.delivery_status <> 'unsettled') "
        "OR (NEW.delivered_attempt_number IS NOT OLD.delivered_attempt_number AND OLD.delivery_status <> 'unsettled') "
        "OR NEW.charged_credits IS NOT OLD.charged_credits OR NEW.expires_at IS NOT OLD.expires_at "
        "OR NEW.absorbed_credits < OLD.absorbed_credits)) "
        "OR (NEW.expires_at IS NOT OLD.expires_at AND (NEW.state IS NOT 'authorized' "
        "OR NEW.expires_at < OLD.expires_at)) "
        "BEGIN SELECT RAISE(ABORT, 'Phase 12 operation binding is immutable and it is finalized once'); END"
    )
    statements["trg_phase12_operation_delete"] = (
        "CREATE TRIGGER trg_phase12_operation_delete BEFORE DELETE ON ai_billing_operations "
        "BEGIN SELECT RAISE(ABORT, 'Phase 12 operations are immutable history'); END"
    )
    statements["trg_phase12_reservation_insert"] = (
        "CREATE TRIGGER trg_phase12_reservation_insert BEFORE INSERT ON credit_reservations "
        "WHEN NOT EXISTS (SELECT 1 FROM ai_billing_operations b WHERE b.operation_id = NEW.operation_id "
        "AND b.state = 'authorized' AND b.billing_account_id = NEW.billing_account_id "
        "AND b.pricing_policy_version_id = NEW.pricing_policy_version_id "
        "AND b.capacity_policy_version_id IS NEW.capacity_policy_version_id) "
        "BEGIN SELECT RAISE(ABORT, 'credit reservations require a Phase 12 operation binding'); END"
    )
    statements["trg_phase12_ledger_insert"] = (
        "CREATE TRIGGER trg_phase12_ledger_insert BEFORE INSERT ON credit_ledger_entries "
        "WHEN NEW.entry_type IN ('reservation', 'settlement') AND (NOT EXISTS ("
        "SELECT 1 FROM ai_billing_operations WHERE operation_id = NEW.operation_id AND state = 'authorized') "
        "OR (NEW.entry_type = 'settlement' AND (EXISTS (SELECT 1 FROM ai_provider_call_usage "
        "WHERE operation_id = NEW.operation_id "
        "AND attempt_number = json_extract(NEW.evidence_json, '$.delivered_attempt_number') "
        "AND usage_label <> 'reported') OR NOT EXISTS (SELECT 1 FROM ai_provider_call_usage "
        "WHERE operation_id = NEW.operation_id "
        "AND attempt_number = json_extract(NEW.evidence_json, '$.delivered_attempt_number') "
        "AND outcome = 'succeeded' AND usage_label = 'reported')))) "
        "BEGIN SELECT RAISE(ABORT, 'a settlement requires reported usage of the delivered attempt "
        "by an authorized Phase 12 operation'); END"
    )
    return statements


SQLITE_TRIGGERS = tuple(_sqlite_guards())


def upgrade():
    _create_tables()
    if op.get_bind().dialect.name == "postgresql":
        for statement in _pg_guards():
            op.execute(statement)
    else:
        for statement in _sqlite_guards().values():
            op.execute(statement)


def downgrade():
    bind = op.get_bind()
    pg = bind.dialect.name == "postgresql"
    if pg:
        for table in TABLES:
            op.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
    for table in TABLES:
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first() is not None:
            raise Phase12EvidenceNotEmptyError("Phase 12 downgrade refuses to discard AI billing evidence")
    if pg:
        for name, table in PG_TRIGGERS:
            op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
        for name in PG_FUNCTIONS:
            op.execute(f"DROP FUNCTION IF EXISTS {name}()")
    else:
        for name in SQLITE_TRIGGERS:
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    for table in TABLES:
        op.drop_table(table)
