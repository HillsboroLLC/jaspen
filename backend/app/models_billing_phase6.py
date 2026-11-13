"""Inactive Phase 6 recurring-credit allocation evidence."""

import uuid

from . import db


class RecurringCreditAllocation(db.Model):
    """Immutable proof binding one recurring period to approved funding facts."""

    __tablename__ = "recurring_credit_allocations"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    billing_account_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "billing_accounts.id",
            name="fk_recurring_credit_allocations_billing_account_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    credit_period_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "credit_periods.id",
            name="fk_recurring_credit_allocations_credit_period_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    entitlement_instance_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "entitlement_instances.id",
            name="fk_recurring_credit_allocations_entitlement_instance_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    entitlement_definition_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "entitlement_definitions.id",
            name="fk_recurring_credit_allocations_entitlement_definition_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    subscription_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "billing_subscriptions.id",
            name="fk_recurring_credit_allocations_subscription_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    financial_line_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "financial_lines.id",
            name="fk_recurring_credit_allocations_financial_line_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    idempotency_registry_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "idempotency_registry.id",
            name="fk_recurring_credit_allocations_idempotency_registry_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    domain_event_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "domain_events.id",
            name="fk_recurring_credit_allocations_domain_event_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    allocation_key = db.Column(db.String(512), nullable=False)
    request_fingerprint = db.Column(db.String(64), nullable=False)
    period_kind = db.Column(db.String(32), nullable=False)
    period_index = db.Column(db.Integer, nullable=False)
    period_starts_at = db.Column(db.DateTime(timezone=True), nullable=False)
    period_ends_at = db.Column(db.DateTime(timezone=True), nullable=False)
    credit_amount = db.Column(db.BigInteger, nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=db.func.now(),
    )

    __table_args__ = (
        db.CheckConstraint(
            "period_kind IN ('free','monthly_subscription','annual_monthly')",
            name="ck_recurring_credit_allocations_kind",
        ),
        db.CheckConstraint(
            "period_index >= 0 AND credit_amount > 0 "
            "AND period_ends_at > period_starts_at",
            name="ck_recurring_credit_allocations_values",
        ),
        db.CheckConstraint(
            "length(trim(allocation_key)) > 0 "
            "AND length(request_fingerprint) = 64 "
            "AND request_fingerprint = lower(request_fingerprint)",
            name="ck_recurring_credit_allocations_identity",
        ),
        db.CheckConstraint(
            "(period_kind = 'free' AND subscription_id IS NULL "
            "AND financial_line_id IS NULL) OR "
            "(period_kind IN ('monthly_subscription','annual_monthly') "
            "AND subscription_id IS NOT NULL AND financial_line_id IS NOT NULL)",
            name="ck_recurring_credit_allocations_evidence_shape",
        ),
        db.UniqueConstraint(
            "credit_period_id", name="uq_recurring_credit_allocations_period_id",
        ),
        db.UniqueConstraint(
            "idempotency_registry_id",
            name="uq_recurring_credit_allocations_idempotency_registry_id",
        ),
        db.UniqueConstraint(
            "domain_event_id",
            name="uq_recurring_credit_allocations_domain_event_id",
        ),
        db.UniqueConstraint(
            "allocation_key", name="uq_recurring_credit_allocations_key",
        ),
        db.Index(
            "ix_recurring_credit_allocations_account_start",
            "billing_account_id", "period_starts_at", "id",
        ),
        db.Index(
            "ix_recurring_credit_allocations_financial_line_id",
            "financial_line_id",
        ),
    )
