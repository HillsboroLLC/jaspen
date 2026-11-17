"""Inactive Phase 12 AI reservation, capacity, and settlement evidence.

Lifecycle specification D06 (operation reservation and settlement; absorbed
provider usage evidence), D21 (pricing binding), D22 (short-term capacity),
and D23 (interruption and resume), under the founder-approved delivery-based
billability policy of 2026-11-11 as amended on 2026-11-16 (verified delivered
usage stays billable after the original deadline while the operation's
reservation lease is live; every member has an individual fair-use allowance).

The Phase 3 ledger stays the only balance authority: these tables record the
binding of one ``AIOperation`` to an effective pricing and capacity version,
the capacity decision, every provider call's usage, the Jaspen-absorbed usage
evidence, and the completed steps of a resumable operation. Nothing in live
routes, the AI runtime, webhooks, jobs, or readers writes to or reads from
these tables. Evidence rows are immutable; the operation's state is
forward-only and finalized once.

Operational history stays in ``AIProviderAttempt`` (durations, status codes,
stop reasons, lineage, routing metadata). ``AIProviderCallUsage`` holds only
the immutable financial facts D06 requires, linked to it by the shared
``ai_operations.id`` and the provider request identifier; it never copies the
operational fields.
"""

import uuid
from datetime import datetime, timezone

from . import db


CAPACITY_RULES_SCHEMA = "jaspen.capacity.v1"
CONVERSION_KEY = "credits_per_provider_usd"
# "expired" is a final financial outcome: the reservation lease lapsed (the
# worker stopped renewing it), the hold was released, and nothing is charged.
# Its delivery starts "unsettled" and the runtime may record once what became
# of the response (delivered, undelivered, no billable usage), never a charge.
OPERATION_STATES = ("authorized", "capacity_denied", "finalized", "expired")
DELIVERY_STATUSES = ("delivered", "undelivered", "no_billable_usage", "unsettled")
USAGE_LABELS = ("reported", "estimated", "unknown")
CALL_COMPONENTS = ("primary", "retry", "fallback", "tool_iteration", "context_expansion")
CALL_OUTCOMES = ("succeeded", "failed", "timeout", "refused", "cancelled")
CAPACITY_OUTCOMES = ("authorized", "denied")
CAPACITY_DENIAL_REASONS = (
    "account_restricted",
    "organization_window",
    "member_window",
    "organization_concurrency",
    "member_concurrency",
    "provider_pressure",
)
ABSORBED_REASONS = (
    "undelivered",
    "not_delivering_attempt",
    "above_reservation_cap",
    "uncertain_usage",
    "reservation_expired",
    "step_already_settled",
)
DISPUTE_STATUSES = ("none", "open", "resolved")
# USD per 1M-token rates carry 10 decimal places, so a call's exact cost needs 16.
COST_USD = (30, 16)


def _quoted(values):
    return ",".join(f"'{value}'" for value in values)


def _now():
    return datetime.now(timezone.utc)


def _fk(table, name, *, nullable=False, column="id"):
    return db.Column(
        db.String(36),
        db.ForeignKey(f"{table}.{column}", name=name, ondelete="RESTRICT"),
        nullable=nullable,
    )


class AIBillingOperation(db.Model):
    """One AIOperation bound to the authoritative ledger (one per operation)."""

    __tablename__ = "ai_billing_operations"

    operation_id = db.Column(
        db.String(36),
        db.ForeignKey("ai_operations.id", name="fk_ai_billing_operations_operation_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    billing_account_id = _fk("billing_accounts", "fk_ai_billing_operations_billing_account_id")
    organization_id = _fk("organizations", "fk_ai_billing_operations_organization_id")
    actor_user_id = _fk("users", "fk_ai_billing_operations_actor_user_id")
    pricing_policy_version_id = _fk(
        "pricing_policy_versions", "fk_ai_billing_operations_pricing_policy_version_id",
    )
    capacity_policy_version_id = _fk(
        "capacity_policy_versions", "fk_ai_billing_operations_capacity_policy_version_id",
    )
    root_operation_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "ai_billing_operations.operation_id",
            name="fk_ai_billing_operations_root_operation_id",
        ),
        nullable=True,
    )
    resumed_from_operation_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "ai_billing_operations.operation_id",
            name="fk_ai_billing_operations_resumed_from_operation_id",
        ),
        nullable=True,
    )
    step_key = db.Column(db.String(160), nullable=False)
    idempotency_registry_id = _fk("idempotency_registry", "fk_ai_billing_operations_idempotency_registry_id")
    request_fingerprint = db.Column(db.String(64), nullable=False)
    candidates_json = db.Column(db.JSON, nullable=False)
    tier_key = db.Column(db.String(80), nullable=False)
    priority = db.Column(db.Integer, nullable=False)
    max_provider_attempts = db.Column(db.Integer, nullable=False)
    max_tool_iterations = db.Column(db.Integer, nullable=False)
    max_call_input_tokens = db.Column(db.BigInteger, nullable=False)
    max_call_output_tokens = db.Column(db.BigInteger, nullable=False)
    max_operation_tokens = db.Column(db.BigInteger, nullable=False)
    lease_seconds = db.Column(db.Integer, nullable=False)
    initial_hold_credits = db.Column(db.BigInteger, nullable=False)
    reservation_ceiling_credits = db.Column(db.BigInteger, nullable=False)
    state = db.Column(db.String(24), nullable=False)
    delivery_status = db.Column(db.String(24), nullable=True)
    delivered_attempt_number = db.Column(db.Integer, nullable=True)
    charged_credits = db.Column(db.BigInteger, nullable=True)
    absorbed_credits = db.Column(db.BigInteger, nullable=True)
    available_again_at = db.Column(db.DateTime(timezone=True), nullable=True)
    authorized_at = db.Column(db.DateTime(timezone=True), nullable=False)
    # No provider call may start at or after the execution deadline (D22 runaway duration).
    execution_deadline_at = db.Column(db.DateTime(timezone=True), nullable=False)
    # Reservation lease: renewed while the worker is alive, never past
    # execution_deadline_at + lease_seconds; only a lapsed lease can expire.
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    finalized_at = db.Column(db.DateTime(timezone=True), nullable=True)
    finalization_evidence_json = db.Column(db.JSON, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("idempotency_registry_id", name="uq_ai_billing_operations_idempotency_registry_id"),
        db.CheckConstraint(f"state IN ({_quoted(OPERATION_STATES)})", name="ck_ai_billing_operations_state"),
        db.CheckConstraint(
            f"delivery_status IS NULL OR delivery_status IN ({_quoted(DELIVERY_STATUSES)})",
            name="ck_ai_billing_operations_delivery_status",
        ),
        db.CheckConstraint(
            "length(request_fingerprint) = 64 AND request_fingerprint = lower(request_fingerprint)",
            name="ck_ai_billing_operations_fingerprint",
        ),
        db.CheckConstraint(
            "length(trim(step_key)) > 0 AND length(trim(tier_key)) > 0",
            name="ck_ai_billing_operations_identity_text",
        ),
        db.CheckConstraint(
            "max_provider_attempts > 0 AND max_tool_iterations >= 0 AND initial_hold_credits > 0 "
            "AND reservation_ceiling_credits >= initial_hold_credits AND max_call_input_tokens > 0 "
            "AND max_call_output_tokens > 0 AND max_operation_tokens > 0 AND lease_seconds > 0",
            name="ck_ai_billing_operations_bounds",
        ),
        db.CheckConstraint(
            "(root_operation_id IS NULL AND resumed_from_operation_id IS NULL) OR "
            "(root_operation_id IS NOT NULL AND resumed_from_operation_id IS NOT NULL "
            "AND root_operation_id != operation_id AND resumed_from_operation_id != operation_id)",
            name="ck_ai_billing_operations_lineage",
        ),
        db.CheckConstraint(
            "expires_at > authorized_at AND execution_deadline_at > authorized_at",
            name="ck_ai_billing_operations_expiry",
        ),
        db.CheckConstraint(
            "(state = 'authorized' AND finalized_at IS NULL) OR "
            "(state != 'authorized' AND finalized_at IS NOT NULL)",
            name="ck_ai_billing_operations_finalization",
        ),
        db.CheckConstraint(
            "state = 'capacity_denied' OR available_again_at IS NULL",
            name="ck_ai_billing_operations_denial_time",
        ),
        db.CheckConstraint(
            "(state = 'finalized' AND delivery_status IS NOT NULL AND delivery_status != 'unsettled' "
            "AND charged_credits IS NOT NULL "
            "AND absorbed_credits IS NOT NULL) OR "
            "(state = 'expired' AND delivery_status IS NOT NULL AND charged_credits = 0 "
            "AND absorbed_credits IS NOT NULL) OR "
            "(state IN ('authorized', 'capacity_denied') AND delivery_status IS NULL "
            "AND charged_credits IS NULL)",
            name="ck_ai_billing_operations_outcome",
        ),
        db.CheckConstraint(
            "charged_credits IS NULL OR (charged_credits >= 0 AND absorbed_credits >= 0)",
            name="ck_ai_billing_operations_amounts",
        ),
        db.CheckConstraint(
            "(delivery_status = 'delivered' AND delivered_attempt_number IS NOT NULL) OR "
            "((delivery_status IS NULL OR delivery_status != 'delivered') "
            "AND delivered_attempt_number IS NULL)",
            name="ck_ai_billing_operations_delivered_attempt",
        ),
        db.Index("ix_ai_billing_operations_account_state_expiry", "billing_account_id", "state", "expires_at"),
        db.Index("ix_ai_billing_operations_org_member_state", "organization_id", "actor_user_id", "state"),
        db.Index("ix_ai_billing_operations_root_operation_id", "root_operation_id"),
        db.Index("ix_ai_billing_operations_pricing_policy_version_id", "pricing_policy_version_id"),
        db.Index("ix_ai_billing_operations_capacity_policy_version_id", "capacity_policy_version_id"),
    )


class AICapacityDecision(db.Model):
    """Capacity authorization outcome: audit evidence, never a ledger entry."""

    __tablename__ = "ai_capacity_decisions"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    operation_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "ai_billing_operations.operation_id",
            name="fk_ai_capacity_decisions_operation_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    capacity_policy_version_id = _fk(
        "capacity_policy_versions", "fk_ai_capacity_decisions_capacity_policy_version_id",
    )
    organization_id = _fk("organizations", "fk_ai_capacity_decisions_organization_id")
    member_user_id = _fk("users", "fk_ai_capacity_decisions_member_user_id")
    window_key = db.Column(db.String(160), nullable=False)
    tier_key = db.Column(db.String(80), nullable=False)
    outcome = db.Column(db.String(16), nullable=False)
    reason_code = db.Column(db.String(40), nullable=True)
    available_again_at = db.Column(db.DateTime(timezone=True), nullable=True)
    decided_at = db.Column(db.DateTime(timezone=True), nullable=False)
    evidence_json = db.Column(db.JSON, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "capacity_policy_version_id", "operation_id", "window_key",
            name="uq_ai_capacity_decisions_policy_operation_window",
        ),
        db.UniqueConstraint("operation_id", name="uq_ai_capacity_decisions_operation_id"),
        db.CheckConstraint(f"outcome IN ({_quoted(CAPACITY_OUTCOMES)})", name="ck_ai_capacity_decisions_outcome"),
        db.CheckConstraint(
            f"(outcome = 'authorized' AND reason_code IS NULL AND available_again_at IS NULL) OR "
            f"(outcome = 'denied' AND reason_code IN ({_quoted(CAPACITY_DENIAL_REASONS)}))",
            name="ck_ai_capacity_decisions_reason",
        ),
        db.Index("ix_ai_capacity_decisions_org_outcome_decided", "organization_id", "outcome", "decided_at"),
        db.Index("ix_ai_capacity_decisions_member_outcome_decided", "member_user_id", "outcome", "decided_at"),
    )


class AIProviderCallUsage(db.Model):
    """One provider call's usage under the operation's bound pricing version."""

    __tablename__ = "ai_provider_call_usage"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    operation_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "ai_billing_operations.operation_id",
            name="fk_ai_provider_call_usage_operation_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    attempt_number = db.Column(db.Integer, nullable=False)
    call_index = db.Column(db.Integer, nullable=False)
    component = db.Column(db.String(24), nullable=False)
    provider = db.Column(db.String(32), nullable=False)
    model = db.Column(db.String(255), nullable=False)
    provider_rate_entry_id = _fk("provider_rate_entries", "fk_ai_provider_call_usage_provider_rate_entry_id")
    outcome = db.Column(db.String(16), nullable=False)
    error_category = db.Column(db.String(80), nullable=True)
    usage_label = db.Column(db.String(16), nullable=False)
    input_tokens = db.Column(db.BigInteger, nullable=True)
    output_tokens = db.Column(db.BigInteger, nullable=True)
    provider_reported_cost_usd = db.Column(db.Numeric(*COST_USD), nullable=True)
    computed_cost_usd = db.Column(db.Numeric(*COST_USD), nullable=True)
    provider_request_id = db.Column(db.String(255), nullable=True)
    requested_at = db.Column(db.DateTime(timezone=True), nullable=False)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True)
    recorded_at = db.Column(db.DateTime(timezone=True), nullable=False)
    request_fingerprint = db.Column(db.String(64), nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "operation_id", "attempt_number", "call_index",
            name="uq_ai_provider_call_usage_operation_attempt_call",
        ),
        db.CheckConstraint("attempt_number > 0 AND call_index >= 0", name="ck_ai_provider_call_usage_sequence"),
        db.CheckConstraint(f"component IN ({_quoted(CALL_COMPONENTS)})", name="ck_ai_provider_call_usage_component"),
        db.CheckConstraint(f"outcome IN ({_quoted(CALL_OUTCOMES)})", name="ck_ai_provider_call_usage_outcome"),
        db.CheckConstraint(f"usage_label IN ({_quoted(USAGE_LABELS)})", name="ck_ai_provider_call_usage_label"),
        db.CheckConstraint(
            "(usage_label = 'unknown' AND input_tokens IS NULL AND output_tokens IS NULL "
            "AND computed_cost_usd IS NULL) OR "
            "(usage_label != 'unknown' AND input_tokens >= 0 AND output_tokens >= 0 "
            "AND computed_cost_usd >= 0)",
            name="ck_ai_provider_call_usage_tokens",
        ),
        db.CheckConstraint(
            "provider_reported_cost_usd IS NULL OR provider_reported_cost_usd >= 0",
            name="ck_ai_provider_call_usage_reported_cost",
        ),
        db.CheckConstraint(
            "outcome = 'succeeded' OR error_category IS NOT NULL",
            name="ck_ai_provider_call_usage_error",
        ),
        db.CheckConstraint(
            "finished_at IS NULL OR finished_at >= requested_at",
            name="ck_ai_provider_call_usage_times",
        ),
        db.CheckConstraint(
            "length(request_fingerprint) = 64 AND request_fingerprint = lower(request_fingerprint)",
            name="ck_ai_provider_call_usage_fingerprint",
        ),
    )


class AIAbsorbedUsage(db.Model):
    """Provider usage Jaspen absorbs; never charged to the customer (D06)."""

    __tablename__ = "ai_absorbed_usage"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    operation_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "ai_billing_operations.operation_id",
            name="fk_ai_absorbed_usage_operation_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    billing_account_id = _fk("billing_accounts", "fk_ai_absorbed_usage_billing_account_id")
    attempt_number = db.Column(db.Integer, nullable=True)
    provider = db.Column(db.String(32), nullable=True)
    model = db.Column(db.String(255), nullable=True)
    provider_call_ids_json = db.Column(db.JSON, nullable=False)
    provider_request_ids_json = db.Column(db.JSON, nullable=False)
    usage_label = db.Column(db.String(16), nullable=False)
    input_tokens = db.Column(db.BigInteger, nullable=True)
    output_tokens = db.Column(db.BigInteger, nullable=True)
    provider_reported_cost_usd = db.Column(db.Numeric(*COST_USD), nullable=True)
    # Exact provider cost of these calls under the bound rates, and the part of it
    # not recovered from the customer (less than the whole when a capped charge covers some).
    computed_cost_usd = db.Column(db.Numeric(*COST_USD), nullable=True)
    absorbed_cost_usd = db.Column(db.Numeric(*COST_USD), nullable=True)
    absorbed_credits = db.Column(db.BigInteger, nullable=True)
    reason = db.Column(db.String(32), nullable=False)
    delivery_status = db.Column(db.String(24), nullable=False)
    error_category = db.Column(db.String(80), nullable=True)
    fallback_attempted = db.Column(db.Boolean, nullable=False)
    fallback_outcome = db.Column(db.String(24), nullable=True)
    requested_at = db.Column(db.DateTime(timezone=True), nullable=True)
    failed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    recorded_at = db.Column(db.DateTime(timezone=True), nullable=False)
    provider_dispute_status = db.Column(db.String(16), nullable=False, default="none", server_default="none")
    provider_dispute_resolution = db.Column(db.String(500), nullable=True)

    __table_args__ = (
        db.CheckConstraint(f"reason IN ({_quoted(ABSORBED_REASONS)})", name="ck_ai_absorbed_usage_reason"),
        db.CheckConstraint(f"usage_label IN ({_quoted(USAGE_LABELS)})", name="ck_ai_absorbed_usage_label"),
        db.CheckConstraint(
            f"delivery_status IN ({_quoted(DELIVERY_STATUSES)})", name="ck_ai_absorbed_usage_delivery_status",
        ),
        db.CheckConstraint(
            f"provider_dispute_status IN ({_quoted(DISPUTE_STATUSES)})", name="ck_ai_absorbed_usage_dispute_status",
        ),
        db.CheckConstraint(
            "(absorbed_cost_usd IS NULL OR absorbed_cost_usd >= 0) AND "
            "(absorbed_credits IS NULL OR absorbed_credits >= 0) AND "
            "(absorbed_cost_usd IS NULL OR absorbed_cost_usd <= computed_cost_usd)",
            name="ck_ai_absorbed_usage_amounts",
        ),
        db.CheckConstraint(
            "provider_dispute_status = 'resolved' OR provider_dispute_resolution IS NULL",
            name="ck_ai_absorbed_usage_dispute_resolution",
        ),
        db.Index("ix_ai_absorbed_usage_operation_id", "operation_id"),
        db.Index("ix_ai_absorbed_usage_account_recorded", "billing_account_id", "recorded_at"),
    )


class AIOperationCheckpoint(db.Model):
    """A completed, settled step; a resumed operation can never repeat it."""

    __tablename__ = "ai_operation_checkpoints"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    root_operation_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "ai_billing_operations.operation_id",
            name="fk_ai_operation_checkpoints_root_operation_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    step_key = db.Column(db.String(160), nullable=False)
    operation_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "ai_billing_operations.operation_id",
            name="fk_ai_operation_checkpoints_operation_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    charged_credits = db.Column(db.BigInteger, nullable=False)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=False)

    __table_args__ = (
        db.UniqueConstraint("root_operation_id", "step_key", name="uq_ai_operation_checkpoints_root_step"),
        db.UniqueConstraint("operation_id", name="uq_ai_operation_checkpoints_operation_id"),
        db.CheckConstraint("charged_credits >= 0", name="ck_ai_operation_checkpoints_charged"),
    )
