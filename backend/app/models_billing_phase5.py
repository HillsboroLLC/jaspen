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
FINANCIAL_CASE_STATES = (
    "refund_recorded", "financial_only", "entitlement_reducing_review",
    "scheduled", "applied", "opened", "pending", "won", "lost",
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
    created_xid = db.Column(db.String(20), nullable=False, server_default="0")
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


class FinancialCase(db.Model):
    """Mutable cumulative projection over immutable refund or dispute evidence."""

    __tablename__ = "financial_cases"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    billing_account_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "billing_accounts.id",
            name="fk_financial_cases_billing_account_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    provider = db.Column(db.String(32), nullable=False)
    case_type = db.Column(db.String(16), nullable=False)
    case_object_id = db.Column(db.String(255), nullable=False)
    source_financial_transaction_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "financial_transactions.id",
            name="fk_financial_cases_source_transaction_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    state = db.Column(db.String(32), nullable=False)
    disposition = db.Column(db.String(40), nullable=True)
    cumulative_principal_minor = db.Column(db.BigInteger, nullable=False)
    current_external_version = db.Column(db.String(255), nullable=False)
    current_event_id = db.Column(db.String(36), nullable=False)
    current_effective_at = db.Column(db.DateTime(timezone=True), nullable=False)
    current_received_at = db.Column(db.DateTime(timezone=True), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())

    __table_args__ = (
        db.CheckConstraint("case_type IN ('refund', 'dispute')", name="ck_financial_cases_type"),
        db.CheckConstraint(
            "length(trim(provider)) > 0 AND length(trim(case_object_id)) > 0 "
            "AND length(trim(current_external_version)) > 0",
            name="ck_financial_cases_identity",
        ),
        db.CheckConstraint(
            "(case_type = 'refund' AND ("
            "(state = 'refund_recorded' AND disposition IS NULL) OR "
            "(state = 'financial_only' AND disposition = 'financial_only') OR "
            "(state IN ('entitlement_reducing_review', 'scheduled', 'applied') "
            "AND disposition = 'entitlement_reducing_review'))) OR "
            "(case_type = 'dispute' AND state IN ('opened', 'pending', 'won', 'lost') "
            "AND disposition IS NULL)",
            name="ck_financial_cases_state_disposition",
        ),
        db.CheckConstraint(
            "cumulative_principal_minor >= 0",
            name="ck_financial_cases_cumulative_principal",
        ),
        db.UniqueConstraint(
            "provider", "case_type", "case_object_id", "source_financial_transaction_id",
            name="uq_financial_cases_provider_object_source",
        ),
        db.Index(
            "ix_financial_cases_account_state",
            "billing_account_id", "state", "updated_at",
        ),
        db.Index(
            "ix_financial_cases_source_transaction",
            "source_financial_transaction_id",
        ),
    )


class FinancialCaseSourceFence(db.Model):
    """Concurrency-only fence serializing case allocations for one source transaction."""

    __tablename__ = "financial_case_source_fences"

    source_financial_transaction_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "financial_transactions.id",
            name="fk_financial_case_source_fences_source_transaction_id",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    fence_bit = db.Column(db.Boolean, nullable=False, server_default=db.false())


class FinancialCaseEvent(db.Model):
    """Append-only accepted version of a refund or dispute case."""

    __tablename__ = "financial_case_events"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    financial_case_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "financial_cases.id",
            name="fk_financial_case_events_case_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    financial_transaction_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "financial_transactions.id",
            name="fk_financial_case_events_transaction_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    inbox_event_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "external_event_inbox.id",
            name="fk_financial_case_events_inbox_event_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    external_version = db.Column(db.String(255), nullable=False)
    event_fingerprint = db.Column(db.String(64), nullable=False)
    state = db.Column(db.String(32), nullable=False)
    disposition = db.Column(db.String(40), nullable=True)
    cumulative_principal_minor = db.Column(db.BigInteger, nullable=False)
    effective_at = db.Column(db.DateTime(timezone=True), nullable=False)
    received_at = db.Column(db.DateTime(timezone=True), nullable=False)
    created_xid = db.Column(db.String(20), nullable=False, server_default="0")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())

    __table_args__ = (
        db.CheckConstraint(
            "length(trim(external_version)) > 0 AND length(event_fingerprint) = 64 "
            "AND event_fingerprint = lower(event_fingerprint)",
            name="ck_financial_case_events_identity",
        ),
        db.CheckConstraint(
            "cumulative_principal_minor >= 0",
            name="ck_financial_case_events_cumulative_principal",
        ),
        db.UniqueConstraint(
            "financial_case_id", "external_version",
            name="uq_financial_case_events_case_version",
        ),
        db.Index(
            "ix_financial_case_events_transaction",
            "financial_transaction_id",
        ),
        db.Index("ix_financial_case_events_inbox_event", "inbox_event_id"),
    )


class FinancialCaseEventLine(db.Model):
    """Exact source-line attribution for one cumulative case version."""

    __tablename__ = "financial_case_event_lines"

    financial_case_event_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "financial_case_events.id",
            name="fk_financial_case_event_lines_event_id",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    financial_line_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "financial_lines.id",
            name="fk_financial_case_event_lines_financial_line_id",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    attributed_principal_minor = db.Column(db.BigInteger, nullable=False)

    __table_args__ = (
        db.CheckConstraint(
            "attributed_principal_minor >= 0",
            name="ck_financial_case_event_lines_principal",
        ),
        db.Index("ix_financial_case_event_lines_financial_line", "financial_line_id"),
    )


class FinancialCaseEventLedgerEntry(db.Model):
    """Append-only links to credit effects owned by the later Phase 9 command."""

    __tablename__ = "financial_case_event_ledger_entries"

    financial_case_event_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "financial_case_events.id",
            name="fk_financial_case_event_ledger_entries_event_id",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    credit_ledger_entry_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "credit_ledger_entries.id",
            name="fk_financial_case_event_ledger_entries_ledger_entry_id",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    effect_type = db.Column(db.String(16), primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())

    __table_args__ = (
        db.CheckConstraint(
            "effect_type IN ('hold', 'release', 'reversal', 'recovery')",
            name="ck_financial_case_event_ledger_entries_effect_type",
        ),
        db.UniqueConstraint(
            "credit_ledger_entry_id",
            name="uq_financial_case_event_ledger_entry_owner",
        ),
        db.Index(
            "ix_financial_case_event_ledger_entries_ledger_entry",
            "credit_ledger_entry_id",
        ),
    )


class DomainEvent(db.Model):
    """Append-only account-scoped business event for later consumers."""

    __tablename__ = "domain_events"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    billing_account_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "billing_accounts.id",
            name="fk_domain_events_billing_account_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    event_key = db.Column(db.String(255), nullable=False)
    event_type = db.Column(db.String(120), nullable=False)
    aggregate_type = db.Column(db.String(80), nullable=False)
    aggregate_id = db.Column(db.String(255), nullable=False)
    occurred_at = db.Column(db.DateTime(timezone=True), nullable=False)
    reference_ids_json = db.Column(
        db.JSON, nullable=False, default=list, server_default=db.text("'[]'"),
    )
    request_fingerprint = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())

    __table_args__ = (
        db.CheckConstraint(
            "length(trim(event_key)) > 0 AND length(trim(event_type)) > 0 "
            "AND length(trim(aggregate_type)) > 0 AND length(trim(aggregate_id)) > 0",
            name="ck_domain_events_identity",
        ),
        db.CheckConstraint(
            "length(request_fingerprint) = 64 "
            "AND request_fingerprint = lower(request_fingerprint)",
            name="ck_domain_events_fingerprint",
        ),
        db.UniqueConstraint("event_key", name="uq_domain_events_event_key"),
        db.UniqueConstraint(
            "id", "billing_account_id",
            name="uq_domain_events_id_account",
        ),
        db.Index(
            "ix_domain_events_account_created",
            "billing_account_id", "created_at",
        ),
    )


class CommunicationOutbox(db.Model):
    """Account-scoped, deduplicated delivery obligation; no transport payload."""

    __tablename__ = "communication_outbox"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    domain_event_id = db.Column(db.String(36), nullable=False)
    billing_account_id = db.Column(db.String(36), nullable=False)
    template_key = db.Column(db.String(120), nullable=False)
    template_version = db.Column(db.String(64), nullable=False)
    channel = db.Column(db.String(40), nullable=False)
    locale = db.Column(db.String(35), nullable=False)
    dedupe_key = db.Column(db.String(512), nullable=False)
    state = db.Column(db.String(16), nullable=False, server_default="pending")
    attempt_count = db.Column(db.Integer, nullable=False, server_default="0")
    next_attempt_at = db.Column(db.DateTime(timezone=True), nullable=True)
    lease_expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    delivered_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())

    __table_args__ = (
        db.ForeignKeyConstraint(
            ["domain_event_id", "billing_account_id"],
            ["domain_events.id", "domain_events.billing_account_id"],
            name="fk_communication_outbox_event_account",
            ondelete="RESTRICT",
        ),
        db.CheckConstraint(
            "length(trim(template_key)) > 0 AND length(trim(template_version)) > 0 "
            "AND length(trim(channel)) > 0 AND length(trim(locale)) > 0 "
            "AND length(trim(dedupe_key)) > 0 "
            "AND template_version NOT LIKE '%:%' AND channel NOT LIKE '%:%'",
            name="ck_communication_outbox_identity",
        ),
        db.CheckConstraint(
            "dedupe_key = 'message:' || domain_event_id || ':' || template_version "
            "|| ':' || billing_account_id || ':' || channel",
            name="ck_communication_outbox_dedupe_key",
        ),
        db.CheckConstraint(
            "state IN ('pending', 'processing', 'retryable', 'delivered')",
            name="ck_communication_outbox_state",
        ),
        db.CheckConstraint(
            "attempt_count >= 0",
            name="ck_communication_outbox_attempt_count",
        ),
        db.CheckConstraint(
            "(state = 'processing' AND lease_expires_at IS NOT NULL) OR "
            "(state <> 'processing' AND lease_expires_at IS NULL)",
            name="ck_communication_outbox_lease",
        ),
        db.CheckConstraint(
            "(state = 'retryable') OR next_attempt_at IS NULL",
            name="ck_communication_outbox_next_attempt",
        ),
        db.CheckConstraint(
            "(state = 'delivered' AND delivered_at IS NOT NULL) OR "
            "(state <> 'delivered' AND delivered_at IS NULL)",
            name="ck_communication_outbox_delivered",
        ),
        db.UniqueConstraint("dedupe_key", name="uq_communication_outbox_dedupe_key"),
        db.UniqueConstraint(
            "domain_event_id", "template_version", "billing_account_id", "channel",
            name="uq_communication_outbox_event_template_recipient_channel",
        ),
        db.Index(
            "ix_communication_outbox_state_next_attempt",
            "state", "next_attempt_at", "created_at",
        ),
        db.Index("ix_communication_outbox_domain_event_id", "domain_event_id"),
    )


class CommunicationOutboxAttempt(db.Model):
    """Auditable delivery attempt with one terminal result at most."""

    __tablename__ = "communication_outbox_attempts"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    outbox_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "communication_outbox.id",
            name="fk_communication_outbox_attempts_outbox_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    attempt_number = db.Column(db.Integer, nullable=False)
    started_at = db.Column(db.DateTime(timezone=True), nullable=False)
    lease_expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    outcome = db.Column(db.String(24), nullable=False, server_default="started")
    provider_message_id = db.Column(db.String(255), nullable=True)
    error_code = db.Column(db.String(120), nullable=True)
    next_attempt_at = db.Column(db.DateTime(timezone=True), nullable=True)
    result_fingerprint = db.Column(db.String(64), nullable=True)

    __table_args__ = (
        db.CheckConstraint("attempt_number > 0", name="ck_communication_outbox_attempt_number"),
        db.CheckConstraint(
            "lease_expires_at > started_at",
            name="ck_communication_outbox_attempt_lease",
        ),
        db.CheckConstraint(
            "(outcome = 'started' AND completed_at IS NULL "
            "AND provider_message_id IS NULL AND error_code IS NULL "
            "AND next_attempt_at IS NULL AND result_fingerprint IS NULL) OR "
            "(outcome = 'delivered' AND completed_at IS NOT NULL "
            "AND error_code IS NULL AND next_attempt_at IS NULL "
            "AND result_fingerprint IS NOT NULL AND length(result_fingerprint) = 64 "
            "AND result_fingerprint = lower(result_fingerprint)) OR "
            "(outcome = 'retryable_failure' AND completed_at IS NOT NULL "
            "AND error_code IS NOT NULL AND length(trim(error_code)) > 0 "
            "AND result_fingerprint IS NOT NULL AND length(result_fingerprint) = 64 "
            "AND result_fingerprint = lower(result_fingerprint))",
            name="ck_communication_outbox_attempt_result",
        ),
        db.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_communication_outbox_attempt_completed_at",
        ),
        db.CheckConstraint(
            "next_attempt_at IS NULL OR next_attempt_at >= completed_at",
            name="ck_communication_outbox_attempt_next_at",
        ),
        db.UniqueConstraint(
            "outbox_id", "attempt_number",
            name="uq_communication_outbox_attempt_number",
        ),
        db.Index(
            "ix_communication_outbox_attempts_outbox_started",
            "outbox_id", "started_at",
        ),
    )
