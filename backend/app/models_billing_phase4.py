"""Inactive Phase 4 entitlement and recurring-credit-period models."""

import uuid
from datetime import datetime, timezone

from . import db


ENTITLEMENT_STATES = (
    "proposed", "scheduled", "active", "reducing", "expired", "superseded", "cancelled",
)
SUBSCRIPTION_STATES = (
    "proposed", "incomplete", "active", "past_due", "unpaid", "paused",
    "cancel_at_period_end", "cancelled", "expired",
)
ENTITLEMENT_SOURCE_TYPES = (
    "free", "subscription", "trial", "promotion", "comp", "enterprise_contract", "internal",
)
CREDIT_PERIOD_STATES = ("planned", "funded", "unfunded", "expired")
CREDIT_PERIOD_KINDS = ("free", "monthly_subscription", "annual_monthly", "enterprise")


class EntitlementDefinition(db.Model):
    __tablename__ = "entitlement_definitions"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    key = db.Column(db.String(80), nullable=False)
    version = db.Column(db.Integer, nullable=False)
    exclusivity_key = db.Column(db.String(80), nullable=False)
    capability_json = db.Column(db.JSON, nullable=False)
    funding_policy_json = db.Column(db.JSON, nullable=False)
    effective_at = db.Column(db.DateTime(timezone=True), nullable=True)
    retired_at = db.Column(db.DateTime(timezone=True), nullable=True)
    approved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    approved_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", name="fk_entitlement_definitions_approved_by_user_id", ondelete="SET NULL"),
        nullable=True,
    )
    approval_evidence_reference = db.Column(db.String(255), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=db.func.now(),
    )

    __table_args__ = (
        db.UniqueConstraint("key", "version", name="uq_entitlement_definitions_key_version"),
        db.CheckConstraint("version > 0", name="ck_entitlement_definitions_version"),
        db.CheckConstraint(
            "length(trim(key)) > 0 AND length(trim(exclusivity_key)) > 0",
            name="ck_entitlement_definitions_identity",
        ),
        db.CheckConstraint(
            "retired_at IS NULL OR (effective_at IS NOT NULL AND retired_at > effective_at)",
            name="ck_entitlement_definitions_interval",
        ),
        db.CheckConstraint(
            "((approved_at IS NULL AND approved_by_user_id IS NULL AND approval_evidence_reference IS NULL) OR "
            "(approved_at IS NOT NULL AND approval_evidence_reference IS NOT NULL "
            "AND length(trim(approval_evidence_reference)) > 0))",
            name="ck_entitlement_definitions_approval",
        ),
        db.Index("ix_entitlement_definitions_key_effective", "key", "effective_at", "retired_at"),
        db.Index("ix_entitlement_definitions_exclusivity_key", "exclusivity_key"),
    )


class BillingSubscription(db.Model):
    __tablename__ = "billing_subscriptions"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    billing_account_id = db.Column(
        db.String(36),
        db.ForeignKey("billing_accounts.id", name="fk_billing_subscriptions_billing_account_id", ondelete="RESTRICT"),
        nullable=False,
    )
    processor = db.Column(db.String(32), nullable=False)
    external_subscription_id = db.Column(db.String(255), nullable=False)
    interval = db.Column(db.String(16), nullable=False)
    anchor_at = db.Column(db.DateTime(timezone=True), nullable=False)
    term_starts_at = db.Column(db.DateTime(timezone=True), nullable=False)
    term_ends_at = db.Column(db.DateTime(timezone=True), nullable=False)
    state = db.Column(db.String(32), nullable=False)
    current_entitlement_definition_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "entitlement_definitions.id",
            name="fk_billing_subscriptions_current_entitlement_definition_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    origin_evidence_json = db.Column(db.JSON, nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=db.func.now(),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc),
        server_default=db.func.now(),
    )

    __table_args__ = (
        db.UniqueConstraint(
            "processor", "external_subscription_id",
            name="uq_billing_subscriptions_processor_external",
        ),
        db.CheckConstraint("interval IN ('month','year','custom')", name="ck_billing_subscriptions_interval"),
        db.CheckConstraint(
            "state IN ('proposed','incomplete','active','past_due','unpaid','paused',"
            "'cancel_at_period_end','cancelled','expired')",
            name="ck_billing_subscriptions_state",
        ),
        db.CheckConstraint("term_ends_at > term_starts_at", name="ck_billing_subscriptions_term"),
        db.CheckConstraint(
            "length(trim(processor)) > 0 AND length(trim(external_subscription_id)) > 0",
            name="ck_billing_subscriptions_external_identity",
        ),
        db.Index("ix_billing_subscriptions_account_state_term", "billing_account_id", "state", "term_ends_at"),
        db.Index("ix_billing_subscriptions_current_definition", "current_entitlement_definition_id"),
    )


class EntitlementInstance(db.Model):
    __tablename__ = "entitlement_instances"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    billing_account_id = db.Column(
        db.String(36),
        db.ForeignKey("billing_accounts.id", name="fk_entitlement_instances_billing_account_id", ondelete="RESTRICT"),
        nullable=False,
    )
    entitlement_definition_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "entitlement_definitions.id",
            name="fk_entitlement_instances_entitlement_definition_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    subscription_id = db.Column(
        db.String(36),
        db.ForeignKey("billing_subscriptions.id", name="fk_entitlement_instances_subscription_id", ondelete="RESTRICT"),
        nullable=True,
    )
    state = db.Column(db.String(24), nullable=False, default="proposed", server_default="proposed")
    last_event_id = db.Column(db.String(36), nullable=True)
    starts_at = db.Column(db.DateTime(timezone=True), nullable=False)
    ends_at = db.Column(db.DateTime(timezone=True), nullable=True)
    source_type = db.Column(db.String(40), nullable=False)
    source_id = db.Column(db.String(255), nullable=False)
    approval_evidence_reference = db.Column(db.String(255), nullable=True)
    supersedes_instance_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "entitlement_instances.id",
            name="fk_entitlement_instances_supersedes_instance_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=db.func.now(),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc),
        server_default=db.func.now(),
    )

    __table_args__ = (
        db.UniqueConstraint(
            "billing_account_id", "source_type", "source_id",
            name="uq_entitlement_instances_account_origin",
        ),
        db.CheckConstraint(
            "state IN ('proposed','scheduled','active','reducing','expired','superseded','cancelled')",
            name="ck_entitlement_instances_state",
        ),
        db.CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="ck_entitlement_instances_interval"),
        db.CheckConstraint(
            "source_type IN ('free','subscription','trial','promotion','comp','enterprise_contract','internal')",
            name="ck_entitlement_instances_source_type",
        ),
        db.CheckConstraint(
            "((source_type = 'subscription' AND subscription_id IS NOT NULL) OR "
            "(source_type != 'subscription' AND subscription_id IS NULL))",
            name="ck_entitlement_instances_source_reference",
        ),
        db.CheckConstraint(
            "state = 'proposed' OR (approval_evidence_reference IS NOT NULL "
            "AND length(trim(approval_evidence_reference)) > 0)",
            name="ck_entitlement_instances_approval",
        ),
        db.CheckConstraint(
            "source_type NOT IN ('trial','promotion','comp','enterprise_contract') "
            "OR state IN ('proposed','cancelled')",
            name="ck_entitlement_instances_later_authority_gate",
        ),
        db.CheckConstraint(
            "supersedes_instance_id IS NULL OR supersedes_instance_id != id",
            name="ck_entitlement_instances_not_self_superseding",
        ),
        db.Index(
            "ix_entitlement_instances_account_state_interval",
            "billing_account_id", "state", "starts_at", "ends_at",
        ),
        db.Index("ix_entitlement_instances_definition_id", "entitlement_definition_id"),
        db.Index("ix_entitlement_instances_subscription_id", "subscription_id"),
        db.Index("ix_entitlement_instances_supersedes_id", "supersedes_instance_id"),
    )


class CreditPeriod(db.Model):
    __tablename__ = "credit_periods"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    billing_account_id = db.Column(
        db.String(36),
        db.ForeignKey("billing_accounts.id", name="fk_credit_periods_billing_account_id", ondelete="RESTRICT"),
        nullable=False,
    )
    entitlement_instance_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "entitlement_instances.id", name="fk_credit_periods_entitlement_instance_id", ondelete="RESTRICT",
        ),
        nullable=False,
    )
    subscription_id = db.Column(
        db.String(36),
        db.ForeignKey("billing_subscriptions.id", name="fk_credit_periods_subscription_id", ondelete="RESTRICT"),
        nullable=True,
    )
    kind = db.Column(db.String(32), nullable=False)
    period_index = db.Column(db.Integer, nullable=False)
    anchor_at = db.Column(db.DateTime(timezone=True), nullable=False)
    starts_at = db.Column(db.DateTime(timezone=True), nullable=False)
    ends_at = db.Column(db.DateTime(timezone=True), nullable=False)
    planned_allocation_amount = db.Column(db.BigInteger, nullable=False)
    state = db.Column(db.String(16), nullable=False, default="planned", server_default="planned")
    funding_idempotency_registry_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "idempotency_registry.id",
            name="fk_credit_periods_funding_idempotency_registry_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    funded_lot_id = db.Column(
        db.String(36),
        db.ForeignKey("credit_lots.id", name="fk_credit_periods_funded_lot_id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=db.func.now(),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc),
        server_default=db.func.now(),
    )

    __table_args__ = (
        db.UniqueConstraint(
            "billing_account_id", "kind", "starts_at",
            name="uq_credit_periods_account_kind_start",
        ),
        db.UniqueConstraint(
            "billing_account_id", "kind", "anchor_at", "period_index",
            name="uq_credit_periods_account_kind_anchor_index",
        ),
        db.UniqueConstraint(
            "funding_idempotency_registry_id",
            name="uq_credit_periods_funding_idempotency_registry_id",
        ),
        db.UniqueConstraint("funded_lot_id", name="uq_credit_periods_funded_lot_id"),
        db.CheckConstraint(
            "kind IN ('free','monthly_subscription','annual_monthly','enterprise')",
            name="ck_credit_periods_kind",
        ),
        db.CheckConstraint(
            "state IN ('planned','funded','unfunded','expired')",
            name="ck_credit_periods_state",
        ),
        db.CheckConstraint("period_index >= 0", name="ck_credit_periods_period_index"),
        db.CheckConstraint("ends_at > starts_at", name="ck_credit_periods_interval"),
        db.CheckConstraint("planned_allocation_amount > 0", name="ck_credit_periods_allocation"),
        db.CheckConstraint(
            "((kind = 'free' AND subscription_id IS NULL) OR "
            "(kind IN ('monthly_subscription','annual_monthly') AND subscription_id IS NOT NULL) OR "
            "kind = 'enterprise')",
            name="ck_credit_periods_subscription_reference",
        ),
        db.CheckConstraint(
            "((state = 'funded' AND funding_idempotency_registry_id IS NOT NULL AND funded_lot_id IS NOT NULL) OR "
            "(state IN ('planned','unfunded') AND funded_lot_id IS NULL) OR state = 'expired')",
            name="ck_credit_periods_funding_shape",
        ),
        db.Index("ix_credit_periods_account_state_end", "billing_account_id", "state", "ends_at"),
        db.Index("ix_credit_periods_entitlement_instance_id", "entitlement_instance_id"),
        db.Index("ix_credit_periods_subscription_id", "subscription_id"),
    )


class EntitlementEvent(db.Model):
    __tablename__ = "entitlement_events"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    entitlement_instance_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "entitlement_instances.id", name="fk_entitlement_events_entitlement_instance_id", ondelete="RESTRICT",
        ),
        nullable=False,
    )
    transition = db.Column(db.String(64), nullable=False)
    from_state = db.Column(db.String(24), nullable=False)
    to_state = db.Column(db.String(24), nullable=False)
    effective_at = db.Column(db.DateTime(timezone=True), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc), server_default=db.func.now(),
    )
    actor_type = db.Column(db.String(40), nullable=False)
    actor_id = db.Column(db.String(255), nullable=False)
    source_type = db.Column(db.String(40), nullable=False)
    source_id = db.Column(db.String(255), nullable=False)
    idempotency_registry_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "idempotency_registry.id", name="fk_entitlement_events_idempotency_registry_id", ondelete="RESTRICT",
        ),
        nullable=False,
    )
    evidence_json = db.Column(db.JSON, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "idempotency_registry_id", name="uq_entitlement_events_idempotency_registry_id",
        ),
        db.CheckConstraint(
            "from_state IN ('proposed','scheduled','active','reducing','expired','superseded','cancelled') "
            "AND to_state IN ('proposed','scheduled','active','reducing','expired','superseded','cancelled')",
            name="ck_entitlement_events_states",
        ),
        db.CheckConstraint(
            "length(trim(transition)) > 0 AND length(trim(actor_type)) > 0 "
            "AND length(trim(actor_id)) > 0 AND length(trim(source_type)) > 0 "
            "AND length(trim(source_id)) > 0",
            name="ck_entitlement_events_provenance",
        ),
        db.Index(
            "ix_entitlement_events_instance_effective",
            "entitlement_instance_id", "effective_at", "id",
        ),
    )
