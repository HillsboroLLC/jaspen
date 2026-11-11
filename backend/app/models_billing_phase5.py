"""Inactive Phase 5 financial-evidence models.

Phase 5.1 adds only the minimal-data external event inbox. Nothing in live
routes, webhooks, jobs, or readers writes to or reads from it.
"""

import uuid

from . import db


INBOX_STATES = ("received", "processing", "processed", "retryable", "quarantined")


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
    digest_conflict_count = db.Column(db.Integer, nullable=False, server_default="0")
    last_conflict_digest = db.Column(db.String(64), nullable=True)
    last_conflict_at = db.Column(db.DateTime(timezone=True), nullable=True)

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
        db.CheckConstraint(
            "(digest_conflict_count = 0 AND last_conflict_digest IS NULL AND last_conflict_at IS NULL) OR "
            "(digest_conflict_count > 0 AND last_conflict_digest IS NOT NULL AND last_conflict_at IS NOT NULL "
            "AND length(last_conflict_digest) = 64 AND last_conflict_digest <> payload_digest)",
            name="ck_external_event_inbox_conflict",
        ),
        db.UniqueConstraint("provider", "event_id", name="uq_external_event_inbox_provider_event"),
        db.Index("ix_external_event_inbox_state_next_attempt", "state", "next_attempt_at"),
        db.Index(
            "ix_external_event_inbox_provider_object_created",
            "provider", "object_id", "provider_created_at",
        ),
        db.Index("ix_external_event_inbox_state_processed", "state", "processed_at"),
    )
