"""Inactive Phase 7 subscription-change and upgrade-proration evidence."""

import uuid

from . import db


class ScheduledPlanChange(db.Model):
    """Organization-owned, historically retained subscription-change command."""

    __tablename__ = "scheduled_plan_changes"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    billing_account_id = db.Column(
        db.String(36),
        db.ForeignKey("billing_accounts.id", name="fk_scheduled_plan_changes_account", ondelete="RESTRICT"),
        nullable=False,
    )
    subscription_id = db.Column(
        db.String(36),
        db.ForeignKey("billing_subscriptions.id", name="fk_scheduled_plan_changes_subscription", ondelete="RESTRICT"),
        nullable=False,
    )
    target_entitlement_definition_id = db.Column(
        db.String(36),
        db.ForeignKey("entitlement_definitions.id", name="fk_scheduled_plan_changes_target_definition", ondelete="RESTRICT"),
        nullable=True,
    )
    kind = db.Column(db.String(24), nullable=False)
    effective_rule = db.Column(db.String(32), nullable=False)
    effective_at = db.Column(db.DateTime(timezone=True), nullable=False)
    state = db.Column(db.String(32), nullable=False, default="pending", server_default="pending")
    command_key = db.Column(db.String(512), nullable=False)
    request_fingerprint = db.Column(db.String(64), nullable=False)
    idempotency_registry_id = db.Column(
        db.String(36),
        db.ForeignKey("idempotency_registry.id", name="fk_scheduled_plan_changes_registry", ondelete="RESTRICT"),
        nullable=False,
    )
    domain_event_id = db.Column(
        db.String(36),
        db.ForeignKey("domain_events.id", name="fk_scheduled_plan_changes_domain_event", ondelete="RESTRICT"),
        nullable=False,
    )
    supersedes_change_id = db.Column(
        db.String(36),
        db.ForeignKey("scheduled_plan_changes.id", name="fk_scheduled_plan_changes_supersedes", ondelete="RESTRICT"),
        nullable=True,
    )
    last_event_id = db.Column(db.String(36), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())

    __table_args__ = (
        db.CheckConstraint("kind IN ('downgrade','cancellation')", name="ck_scheduled_plan_changes_kind"),
        db.CheckConstraint(
            "effective_rule IN ('next_monthly_renewal','next_annual_renewal','period_end')",
            name="ck_scheduled_plan_changes_effective_rule",
        ),
        db.CheckConstraint(
            "state IN ('pending','awaiting_renewal_payment','applied','superseded','cancelled','blocked_terminal_failure')",
            name="ck_scheduled_plan_changes_state",
        ),
        db.CheckConstraint(
            "(kind='downgrade' AND target_entitlement_definition_id IS NOT NULL) OR "
            "(kind='cancellation' AND target_entitlement_definition_id IS NULL)",
            name="ck_scheduled_plan_changes_target",
        ),
        db.CheckConstraint(
            "length(trim(command_key)) > 0 AND length(request_fingerprint)=64 "
            "AND request_fingerprint=lower(request_fingerprint)",
            name="ck_scheduled_plan_changes_identity",
        ),
        db.CheckConstraint("supersedes_change_id IS NULL OR supersedes_change_id<>id", name="ck_scheduled_plan_changes_not_self"),
        db.UniqueConstraint("command_key", name="uq_scheduled_plan_changes_command_key"),
        db.UniqueConstraint("idempotency_registry_id", name="uq_scheduled_plan_changes_registry"),
        db.UniqueConstraint("domain_event_id", name="uq_scheduled_plan_changes_domain_event"),
        db.Index("ix_scheduled_plan_changes_subscription_state", "subscription_id", "state", "effective_at"),
        db.Index(
            "uq_scheduled_plan_changes_one_active",
            "subscription_id",
            unique=True,
            postgresql_where=db.text("state IN ('pending','awaiting_renewal_payment')"),
            sqlite_where=db.text("state IN ('pending','awaiting_renewal_payment')"),
        ),
    )


class PlanChangeEvent(db.Model):
    """Append-only state transition for a scheduled plan change."""

    __tablename__ = "plan_change_events"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    scheduled_change_id = db.Column(
        db.String(36),
        db.ForeignKey("scheduled_plan_changes.id", name="fk_plan_change_events_change", ondelete="RESTRICT"),
        nullable=False,
    )
    from_state = db.Column(db.String(32), nullable=False)
    to_state = db.Column(db.String(32), nullable=False)
    transition = db.Column(db.String(64), nullable=False)
    effective_at = db.Column(db.DateTime(timezone=True), nullable=False)
    actor_type = db.Column(db.String(32), nullable=False)
    actor_id = db.Column(db.String(255), nullable=False)
    evidence_json = db.Column(db.JSON, nullable=False)
    idempotency_registry_id = db.Column(
        db.String(36),
        db.ForeignKey("idempotency_registry.id", name="fk_plan_change_events_registry", ondelete="RESTRICT"),
        nullable=False,
    )
    domain_event_id = db.Column(
        db.String(36),
        db.ForeignKey("domain_events.id", name="fk_plan_change_events_domain_event", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())

    __table_args__ = (
        db.CheckConstraint("from_state<>to_state", name="ck_plan_change_events_transition"),
        db.CheckConstraint(
            "length(trim(transition))>0 AND length(trim(actor_type))>0 AND length(trim(actor_id))>0",
            name="ck_plan_change_events_text",
        ),
        db.UniqueConstraint("idempotency_registry_id", name="uq_plan_change_events_registry"),
        db.UniqueConstraint("domain_event_id", name="uq_plan_change_events_domain_event"),
        db.Index("ix_plan_change_events_change_created", "scheduled_change_id", "created_at", "id"),
    )


class UpgradeCreditAllocation(db.Model):
    """Immutable evidence for a paid-to-paid, integer-floored proration lot."""

    __tablename__ = "upgrade_credit_allocations"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    billing_account_id = db.Column(db.String(36), db.ForeignKey("billing_accounts.id", name="fk_upgrade_allocations_account", ondelete="RESTRICT"), nullable=False)
    subscription_id = db.Column(db.String(36), db.ForeignKey("billing_subscriptions.id", name="fk_upgrade_allocations_subscription", ondelete="RESTRICT"), nullable=False)
    prior_entitlement_instance_id = db.Column(db.String(36), db.ForeignKey("entitlement_instances.id", name="fk_upgrade_allocations_prior_instance", ondelete="RESTRICT"), nullable=False)
    target_entitlement_instance_id = db.Column(db.String(36), db.ForeignKey("entitlement_instances.id", name="fk_upgrade_allocations_target_instance", ondelete="RESTRICT"), nullable=False)
    financial_line_id = db.Column(db.String(36), db.ForeignKey("financial_lines.id", name="fk_upgrade_allocations_financial_line", ondelete="RESTRICT"), nullable=False)
    idempotency_registry_id = db.Column(db.String(36), db.ForeignKey("idempotency_registry.id", name="fk_upgrade_allocations_registry", ondelete="RESTRICT"), nullable=False)
    domain_event_id = db.Column(db.String(36), db.ForeignKey("domain_events.id", name="fk_upgrade_allocations_domain_event", ondelete="RESTRICT"), nullable=False)
    funded_lot_id = db.Column(db.String(36), db.ForeignKey("credit_lots.id", name="fk_upgrade_allocations_lot", ondelete="RESTRICT", deferrable=True, initially="DEFERRED"), nullable=True)
    grant_entry_id = db.Column(db.String(36), db.ForeignKey("credit_ledger_entries.id", name="fk_upgrade_allocations_grant", ondelete="RESTRICT", deferrable=True, initially="DEFERRED"), nullable=True)
    allocation_key = db.Column(db.String(512), nullable=False)
    request_fingerprint = db.Column(db.String(64), nullable=False)
    old_period_amount = db.Column(db.BigInteger, nullable=False)
    new_period_amount = db.Column(db.BigInteger, nullable=False)
    period_starts_at = db.Column(db.DateTime(timezone=True), nullable=False)
    period_ends_at = db.Column(db.DateTime(timezone=True), nullable=False)
    paid_at = db.Column(db.DateTime(timezone=True), nullable=False)
    credit_amount = db.Column(db.BigInteger, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())

    __table_args__ = (
        db.CheckConstraint(
            "old_period_amount>=0 AND new_period_amount>old_period_amount AND credit_amount>=0 "
            "AND period_ends_at>period_starts_at AND paid_at>=period_starts_at AND paid_at<=period_ends_at",
            name="ck_upgrade_allocations_values",
        ),
        db.CheckConstraint(
            "(credit_amount=0 AND funded_lot_id IS NULL AND grant_entry_id IS NULL) OR "
            "(credit_amount>0 AND funded_lot_id IS NOT NULL AND grant_entry_id IS NOT NULL)",
            name="ck_upgrade_allocations_funding_shape",
        ),
        db.CheckConstraint(
            "length(trim(allocation_key))>0 AND length(request_fingerprint)=64 "
            "AND request_fingerprint=lower(request_fingerprint)",
            name="ck_upgrade_allocations_identity",
        ),
        db.CheckConstraint("prior_entitlement_instance_id<>target_entitlement_instance_id", name="ck_upgrade_allocations_instances"),
        db.UniqueConstraint("allocation_key", name="uq_upgrade_allocations_key"),
        db.UniqueConstraint("idempotency_registry_id", name="uq_upgrade_allocations_registry"),
        db.UniqueConstraint("domain_event_id", name="uq_upgrade_allocations_domain_event"),
        db.UniqueConstraint("funded_lot_id", name="uq_upgrade_allocations_lot"),
        db.UniqueConstraint("grant_entry_id", name="uq_upgrade_allocations_grant"),
        db.Index("ix_upgrade_allocations_subscription_paid", "subscription_id", "paid_at", "id"),
    )
