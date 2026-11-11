"""Inactive Phase 5 financial-evidence models.

Phase 5.1 adds only the minimal-data external event inbox and its append-only
digest-conflict evidence. Nothing in live routes, webhooks, jobs, or readers
writes to or reads from them.
"""

import uuid

from . import db


INBOX_STATES = ("received", "processing", "processed", "retryable", "quarantined")
FINANCIAL_TRANSACTION_KINDS = (
    "invoice", "payment", "refund", "dispute", "recovery", "adjustment",
)
FINANCIAL_LINE_KINDS = (
    "subscription", "seat", "credit_pack", "tax", "fee", "discount", "other",
)


def _quoted(values):
    return ", ".join(f"'{value}'" for value in values)


class ExternalEventInbox(db.Model):
    __tablename__ = "external_event_inbox"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    provider = db.Column(db.String(32), nullable=False)
    event_id = db.Column(db.String(255), nullable=False)
    event_type = db.Column(db.String(120), nullable=False)
    object_type = db.Column(db.String(64), nullable=False)
    object_id = db.Column(db.String(255), nullable=False)
    payload_digest = db.Column(db.String(64), nullable=False)
    summary_json = db.Column(db.JSON, nullable=False)
    livemode = db.Column(db.Boolean, nullable=False)
    provider_created_at = db.Column(db.DateTime(timezone=True), nullable=False)
    received_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())
    state = db.Column(db.String(16), nullable=False, server_default="received")
    attempt_count = db.Column(db.Integer, nullable=False, server_default="0")
    next_attempt_at = db.Column(db.DateTime(timezone=True), nullable=True)
    lease_expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    processed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    error_code = db.Column(db.String(120), nullable=True)

    __table_args__ = (
        db.CheckConstraint("provider IN ('stripe')", name="ck_external_event_inbox_provider"),
        db.CheckConstraint(
            "length(trim(event_id)) > 0 AND length(trim(event_type)) > 0 "
            "AND length(trim(object_type)) > 0 AND length(trim(object_id)) > 0",
            name="ck_external_event_inbox_identity",
        ),
        db.CheckConstraint(
            "length(payload_digest) = 64 AND payload_digest = lower(payload_digest)",
            name="ck_external_event_inbox_digest",
        ),
        db.CheckConstraint(f"state IN ({_quoted(INBOX_STATES)})", name="ck_external_event_inbox_state"),
        db.CheckConstraint("attempt_count >= 0", name="ck_external_event_inbox_attempts"),
        db.CheckConstraint(
            "(state = 'processed' AND processed_at IS NOT NULL) OR "
            "(state <> 'processed' AND processed_at IS NULL)",
            name="ck_external_event_inbox_processed",
        ),
        db.CheckConstraint(
            "processed_at IS NULL OR processed_at >= received_at",
            name="ck_external_event_inbox_processed_after_received",
        ),
        db.CheckConstraint(
            "(state = 'processing' AND lease_expires_at IS NOT NULL) OR "
            "(state <> 'processing' AND lease_expires_at IS NULL)",
            name="ck_external_event_inbox_lease",
        ),
        db.CheckConstraint(
            "(state = 'retryable' AND next_attempt_at IS NOT NULL AND error_code IS NOT NULL) OR "
            "(state <> 'retryable' AND next_attempt_at IS NULL)",
            name="ck_external_event_inbox_retry",
        ),
        db.CheckConstraint(
            "state <> 'quarantined' OR error_code IS NOT NULL",
            name="ck_external_event_inbox_quarantine_reason",
        ),
        db.UniqueConstraint("provider", "event_id", name="uq_external_event_inbox_provider_event"),
        db.Index("ix_external_event_inbox_state_next_attempt", "state", "next_attempt_at"),
        db.Index(
            "ix_external_event_inbox_provider_object_created",
            "provider", "object_id", "provider_created_at",
        ),
        db.Index("ix_external_event_inbox_state_processed", "state", "processed_at"),
    )


class ExternalEventInboxConflict(db.Model):
    """Append-only evidence of a same-ID event received with a different digest."""

    __tablename__ = "external_event_inbox_conflicts"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    inbox_event_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "external_event_inbox.id",
            name="fk_external_event_inbox_conflicts_inbox_event_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    conflicting_digest = db.Column(db.String(64), nullable=False)
    state_at_detection = db.Column(db.String(16), nullable=False)
    detected_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())

    __table_args__ = (
        db.CheckConstraint(
            "length(conflicting_digest) = 64 AND conflicting_digest = lower(conflicting_digest)",
            name="ck_external_event_inbox_conflicts_digest",
        ),
        db.CheckConstraint(
            f"state_at_detection IN ({_quoted(INBOX_STATES)})",
            name="ck_external_event_inbox_conflicts_state",
        ),
        db.UniqueConstraint(
            "inbox_event_id", "conflicting_digest",
            name="uq_external_event_inbox_conflicts_event_digest",
        ),
    )


class FinancialTransaction(db.Model):
    """Immutable processor/internal money fact; never a credit balance."""

    __tablename__ = "financial_transactions"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    billing_account_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "billing_accounts.id",
            name="fk_financial_transactions_billing_account_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    kind = db.Column(db.String(24), nullable=False)
    provider = db.Column(db.String(32), nullable=False)
    object_type = db.Column(db.String(64), nullable=False)
    object_id = db.Column(db.String(255), nullable=False)
    external_version = db.Column(db.String(255), nullable=False)
    effective_at = db.Column(db.DateTime(timezone=True), nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    principal_minor = db.Column(db.BigInteger, nullable=False)
    tax_minor = db.Column(db.BigInteger, nullable=False)
    fee_minor = db.Column(db.BigInteger, nullable=False)
    discount_minor = db.Column(db.BigInteger, nullable=False)
    gross_minor = db.Column(db.BigInteger, nullable=False)
    inbox_event_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "external_event_inbox.id",
            name="fk_financial_transactions_inbox_event_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())

    __table_args__ = (
        db.CheckConstraint(
            f"kind IN ({_quoted(FINANCIAL_TRANSACTION_KINDS)})",
            name="ck_financial_transactions_kind",
        ),
        db.CheckConstraint(
            "length(trim(provider)) > 0 AND length(trim(object_type)) > 0 "
            "AND length(trim(object_id)) > 0 AND length(trim(external_version)) > 0",
            name="ck_financial_transactions_identity",
        ),
        db.CheckConstraint(
            "length(currency) = 3 AND currency = lower(currency) AND "
            "substr(currency, 1, 1) BETWEEN 'a' AND 'z' AND "
            "substr(currency, 2, 1) BETWEEN 'a' AND 'z' AND "
            "substr(currency, 3, 1) BETWEEN 'a' AND 'z'",
            name="ck_financial_transactions_currency",
        ),
        db.CheckConstraint(
            "gross_minor = principal_minor + tax_minor + fee_minor + discount_minor",
            name="ck_financial_transactions_arithmetic",
        ),
        db.CheckConstraint(
            "kind = 'adjustment' OR inbox_event_id IS NOT NULL",
            name="ck_financial_transactions_external_evidence",
        ),
        db.UniqueConstraint(
            "provider", "object_type", "object_id", "kind", "external_version",
            name="uq_financial_transactions_business_version",
        ),
        db.Index(
            "ix_financial_transactions_account_effective",
            "billing_account_id", "effective_at", "id",
        ),
        db.Index(
            "ix_financial_transactions_provider_object_effective",
            "provider", "object_type", "object_id", "effective_at",
        ),
        db.Index("ix_financial_transactions_inbox_event_id", "inbox_event_id"),
    )


class FinancialLine(db.Model):
    """Immutable, source-attributed component of one financial transaction."""

    __tablename__ = "financial_lines"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    financial_transaction_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "financial_transactions.id",
            name="fk_financial_lines_transaction_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    external_line_id = db.Column(db.String(255), nullable=False)
    line_kind = db.Column(db.String(32), nullable=False)
    source_type = db.Column(db.String(40), nullable=False)
    source_id = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.BigInteger, nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    principal_minor = db.Column(db.BigInteger, nullable=False)
    tax_minor = db.Column(db.BigInteger, nullable=False)
    fee_minor = db.Column(db.BigInteger, nullable=False)
    discount_minor = db.Column(db.BigInteger, nullable=False)
    subscription_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "billing_subscriptions.id",
            name="fk_financial_lines_subscription_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    entitlement_instance_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "entitlement_instances.id",
            name="fk_financial_lines_entitlement_instance_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())

    __table_args__ = (
        db.CheckConstraint(
            f"line_kind IN ({_quoted(FINANCIAL_LINE_KINDS)})",
            name="ck_financial_lines_kind",
        ),
        db.CheckConstraint(
            "length(trim(external_line_id)) > 0 AND length(trim(source_type)) > 0 "
            "AND length(trim(source_id)) > 0",
            name="ck_financial_lines_identity",
        ),
        db.CheckConstraint("quantity > 0", name="ck_financial_lines_quantity"),
        db.CheckConstraint(
            "length(currency) = 3 AND currency = lower(currency) AND "
            "substr(currency, 1, 1) BETWEEN 'a' AND 'z' AND "
            "substr(currency, 2, 1) BETWEEN 'a' AND 'z' AND "
            "substr(currency, 3, 1) BETWEEN 'a' AND 'z'",
            name="ck_financial_lines_currency",
        ),
        db.UniqueConstraint(
            "financial_transaction_id", "external_line_id", "line_kind",
            name="uq_financial_lines_transaction_external_kind",
        ),
        db.Index(
            "ix_financial_lines_source",
            "source_type", "source_id", "financial_transaction_id",
        ),
        db.Index("ix_financial_lines_subscription_id", "subscription_id"),
        db.Index("ix_financial_lines_entitlement_instance_id", "entitlement_instance_id"),
    )
