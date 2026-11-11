"""Add the inactive minimal-data external event inbox (Phase 5.1).

Revision ID: b2d4f6a8c0e3
Revises: f9c1a3e5b7d4

Phase 5.1 stores only what idempotency, reconciliation, retries, and audit need:
event identity, the referenced object identity, a digest of the verified raw
payload, and an allowlisted scalar summary. It never stores raw payloads,
payment-card details, billing details, names, emails, addresses, phone numbers,
metadata, or descriptions. Nothing writes to the inbox: no webhook, browser
route, job, or reader is connected.
"""

from alembic import op
import sqlalchemy as sa


revision = "b2d4f6a8c0e3"
down_revision = "f9c1a3e5b7d4"
branch_labels = None
depends_on = None

INBOX_TABLE = "external_event_inbox"
INBOX_STATES = ("received", "processing", "processed", "retryable", "quarantined")
# Must equal app.billing_inbox.SUMMARY_FIELDS and RETENTION_DAYS (tests assert parity).
SUMMARY_FIELDS = (
    "schema_version", "api_version", "status", "currency",
    "amount", "amount_due", "amount_paid", "amount_refunded",
    "customer", "subscription", "invoice", "payment_intent", "charge",
    "refund", "dispute", "checkout_session",
)
RETENTION_DAYS = 400
MAX_SUMMARY_STRING_LENGTH = 255


class ExternalEventInboxNotEmptyError(RuntimeError):
    """Raised when downgrade would discard external event evidence."""


def _quoted(values):
    return ", ".join(f"'{value}'" for value in values)


def _create_table():
    op.create_table(
        INBOX_TABLE,
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("event_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("object_type", sa.String(64), nullable=False),
        sa.Column("object_id", sa.String(255), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("livemode", sa.Boolean(), nullable=False),
        sa.Column("provider_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("state", sa.String(16), nullable=False, server_default="received"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(120), nullable=True),
        sa.Column("digest_conflict_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_conflict_digest", sa.String(64), nullable=True),
        sa.Column("last_conflict_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("provider IN ('stripe')", name="ck_external_event_inbox_provider"),
        sa.CheckConstraint(
            "length(trim(event_id)) > 0 AND length(trim(event_type)) > 0 "
            "AND length(trim(object_type)) > 0 AND length(trim(object_id)) > 0",
            name="ck_external_event_inbox_identity",
        ),
        sa.CheckConstraint(
            "length(payload_digest) = 64 AND payload_digest = lower(payload_digest)",
            name="ck_external_event_inbox_digest",
        ),
        sa.CheckConstraint(f"state IN ({_quoted(INBOX_STATES)})", name="ck_external_event_inbox_state"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_external_event_inbox_attempts"),
        sa.CheckConstraint(
            "(state = 'processed' AND processed_at IS NOT NULL) OR "
            "(state <> 'processed' AND processed_at IS NULL)",
            name="ck_external_event_inbox_processed",
        ),
        sa.CheckConstraint(
            "processed_at IS NULL OR processed_at >= received_at",
            name="ck_external_event_inbox_processed_after_received",
        ),
        sa.CheckConstraint(
            "(state = 'processing' AND lease_expires_at IS NOT NULL) OR "
            "(state <> 'processing' AND lease_expires_at IS NULL)",
            name="ck_external_event_inbox_lease",
        ),
        sa.CheckConstraint(
            "(state = 'retryable' AND next_attempt_at IS NOT NULL AND error_code IS NOT NULL) OR "
            "(state <> 'retryable' AND next_attempt_at IS NULL)",
            name="ck_external_event_inbox_retry",
        ),
        sa.CheckConstraint(
            "state <> 'quarantined' OR error_code IS NOT NULL",
            name="ck_external_event_inbox_quarantine_reason",
        ),
        sa.CheckConstraint(
            "(digest_conflict_count = 0 AND last_conflict_digest IS NULL AND last_conflict_at IS NULL) OR "
            "(digest_conflict_count > 0 AND last_conflict_digest IS NOT NULL AND last_conflict_at IS NOT NULL "
            "AND length(last_conflict_digest) = 64 AND last_conflict_digest <> payload_digest)",
            name="ck_external_event_inbox_conflict",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_external_event_inbox"),
        sa.UniqueConstraint("provider", "event_id", name="uq_external_event_inbox_provider_event"),
    )
    op.create_index(
        "ix_external_event_inbox_state_next_attempt", INBOX_TABLE, ["state", "next_attempt_at"],
    )
    op.create_index(
        "ix_external_event_inbox_provider_object_created", INBOX_TABLE,
        ["provider", "object_id", "provider_created_at"],
    )
    op.create_index(
        "ix_external_event_inbox_state_processed", INBOX_TABLE, ["state", "processed_at"],
    )


def _postgresql_triggers():
    allowed = _quoted(SUMMARY_FIELDS)
    op.execute(sa.text(f"""
        CREATE FUNCTION phase5_inbox_summary_valid(summary jsonb) RETURNS boolean AS $$
          SELECT jsonb_typeof(summary) = 'object' AND NOT EXISTS (
            SELECT 1 FROM jsonb_each(summary) AS summary_entry
            WHERE summary_entry.key NOT IN ({allowed})
               OR jsonb_typeof(summary_entry.value) NOT IN ('string', 'number', 'boolean', 'null')
               OR (jsonb_typeof(summary_entry.value) = 'string'
                   AND length(summary_entry.value #>> '{{}}') > {MAX_SUMMARY_STRING_LENGTH})
          );
        $$ LANGUAGE sql IMMUTABLE
    """))
    op.execute(sa.text(f"""
        CREATE FUNCTION phase5_inbox_guard() RETURNS trigger AS $$
        DECLARE
          allowed_transition boolean;
        BEGIN
          IF TG_OP = 'DELETE' THEN
            IF OLD.state <> 'processed' OR OLD.processed_at IS NULL
               OR OLD.processed_at > now() - interval '{RETENTION_DAYS} days' THEN
              RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'inbox events may be deleted only by retention after processing';
            END IF;
            RETURN OLD;
          END IF;

          IF NOT phase5_inbox_summary_valid(NEW.summary_json::jsonb) THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
              MESSAGE = 'inbox summary must contain only allowlisted scalar fields';
          END IF;

          IF TG_OP = 'INSERT' THEN
            IF NEW.state <> 'received' OR NEW.attempt_count <> 0 OR NEW.next_attempt_at IS NOT NULL
               OR NEW.lease_expires_at IS NOT NULL OR NEW.processed_at IS NOT NULL
               OR NEW.error_code IS NOT NULL OR NEW.digest_conflict_count <> 0 THEN
              RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'inbox events must begin received with no processing history';
            END IF;
            RETURN NEW;
          END IF;

          IF NEW.provider IS DISTINCT FROM OLD.provider OR NEW.event_id IS DISTINCT FROM OLD.event_id
             OR NEW.event_type IS DISTINCT FROM OLD.event_type OR NEW.object_type IS DISTINCT FROM OLD.object_type
             OR NEW.object_id IS DISTINCT FROM OLD.object_id OR NEW.payload_digest IS DISTINCT FROM OLD.payload_digest
             OR NEW.summary_json::jsonb IS DISTINCT FROM OLD.summary_json::jsonb
             OR NEW.livemode IS DISTINCT FROM OLD.livemode
             OR NEW.provider_created_at IS DISTINCT FROM OLD.provider_created_at
             OR NEW.received_at IS DISTINCT FROM OLD.received_at THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
              MESSAGE = 'inbox event identity and evidence are immutable';
          END IF;

          IF OLD.processed_at IS NOT NULL AND NEW.processed_at IS DISTINCT FROM OLD.processed_at THEN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'inbox processing time is immutable';
          END IF;

          IF NEW.digest_conflict_count < OLD.digest_conflict_count
             OR NEW.digest_conflict_count > OLD.digest_conflict_count + 1
             OR (NEW.digest_conflict_count = OLD.digest_conflict_count AND (
                 NEW.last_conflict_digest IS DISTINCT FROM OLD.last_conflict_digest
                 OR NEW.last_conflict_at IS DISTINCT FROM OLD.last_conflict_at)) THEN
            RAISE EXCEPTION USING ERRCODE = '23514',
              MESSAGE = 'inbox digest conflicts are append-only evidence';
          END IF;

          IF NEW.state = 'processing' THEN
            allowed_transition := OLD.state IN ('received', 'retryable')
              OR (OLD.state = 'processing' AND OLD.lease_expires_at <= now());
            IF NOT allowed_transition OR NEW.attempt_count <> OLD.attempt_count + 1 THEN
              RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'inbox claim requires an available event and one new attempt';
            END IF;
          ELSE
            IF NEW.attempt_count <> OLD.attempt_count THEN
              RAISE EXCEPTION USING ERRCODE = '23514',
                MESSAGE = 'inbox attempts change only when an event is claimed';
            END IF;
            IF NEW.state IS DISTINCT FROM OLD.state THEN
              allowed_transition := (OLD.state = 'processing' AND NEW.state IN ('processed', 'retryable', 'quarantined'))
                OR (OLD.state IN ('received', 'retryable') AND NEW.state = 'quarantined')
                OR (OLD.state = 'quarantined' AND NEW.state = 'retryable');
              IF NOT allowed_transition THEN
                RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'invalid inbox state transition';
              END IF;
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_external_event_inbox_guard
        BEFORE INSERT OR UPDATE OR DELETE ON external_event_inbox
        FOR EACH ROW EXECUTE FUNCTION phase5_inbox_guard()
    """))


def _sqlite_triggers():
    allowed = _quoted(SUMMARY_FIELDS)
    summary_invalid = f"""
        json_valid(NEW.summary_json) = 0 OR json_type(NEW.summary_json) <> 'object' OR EXISTS (
          SELECT 1 FROM json_each(NEW.summary_json) AS summary_entry
          WHERE summary_entry.key NOT IN ({allowed})
             OR summary_entry.type IN ('object', 'array')
             OR (summary_entry.type = 'text' AND length(summary_entry.value) > {MAX_SUMMARY_STRING_LENGTH})
        )"""
    statements = (
        f"""CREATE TRIGGER trg_external_event_inbox_insert BEFORE INSERT ON external_event_inbox BEGIN
          SELECT RAISE(ABORT, 'inbox summary must contain only allowlisted scalar fields') WHERE {summary_invalid};
          SELECT RAISE(ABORT, 'inbox events must begin received with no processing history')
          WHERE COALESCE(NEW.state, 'received') <> 'received' OR COALESCE(NEW.attempt_count, 0) <> 0
             OR NEW.next_attempt_at IS NOT NULL OR NEW.lease_expires_at IS NOT NULL
             OR NEW.processed_at IS NOT NULL OR NEW.error_code IS NOT NULL
             OR COALESCE(NEW.digest_conflict_count, 0) <> 0;
        END""",
        f"""CREATE TRIGGER trg_external_event_inbox_update BEFORE UPDATE ON external_event_inbox BEGIN
          SELECT RAISE(ABORT, 'inbox summary must contain only allowlisted scalar fields') WHERE {summary_invalid};
          SELECT RAISE(ABORT, 'inbox event identity and evidence are immutable')
          WHERE NEW.provider IS NOT OLD.provider OR NEW.event_id IS NOT OLD.event_id
             OR NEW.event_type IS NOT OLD.event_type OR NEW.object_type IS NOT OLD.object_type
             OR NEW.object_id IS NOT OLD.object_id OR NEW.payload_digest IS NOT OLD.payload_digest
             OR json(NEW.summary_json) IS NOT json(OLD.summary_json) OR NEW.livemode IS NOT OLD.livemode
             OR NEW.provider_created_at IS NOT OLD.provider_created_at OR NEW.received_at IS NOT OLD.received_at;
          SELECT RAISE(ABORT, 'inbox processing time is immutable')
          WHERE OLD.processed_at IS NOT NULL AND NEW.processed_at IS NOT OLD.processed_at;
          SELECT RAISE(ABORT, 'inbox digest conflicts are append-only evidence')
          WHERE NEW.digest_conflict_count < OLD.digest_conflict_count
             OR NEW.digest_conflict_count > OLD.digest_conflict_count + 1
             OR (NEW.digest_conflict_count = OLD.digest_conflict_count AND (
                 NEW.last_conflict_digest IS NOT OLD.last_conflict_digest
                 OR NEW.last_conflict_at IS NOT OLD.last_conflict_at));
          SELECT RAISE(ABORT, 'inbox claim requires an available event and one new attempt')
          WHERE NEW.state = 'processing' AND (
                NEW.attempt_count <> OLD.attempt_count + 1 OR NOT (
                  OLD.state IN ('received', 'retryable')
                  OR (OLD.state = 'processing' AND julianday(OLD.lease_expires_at) <= julianday('now'))));
          SELECT RAISE(ABORT, 'inbox attempts change only when an event is claimed')
          WHERE NEW.state <> 'processing' AND NEW.attempt_count <> OLD.attempt_count;
          SELECT RAISE(ABORT, 'invalid inbox state transition')
          WHERE NEW.state <> 'processing' AND NEW.state IS NOT OLD.state AND NOT (
                (OLD.state = 'processing' AND NEW.state IN ('processed', 'retryable', 'quarantined'))
                OR (OLD.state IN ('received', 'retryable') AND NEW.state = 'quarantined')
                OR (OLD.state = 'quarantined' AND NEW.state = 'retryable'));
        END""",
        f"""CREATE TRIGGER trg_external_event_inbox_delete BEFORE DELETE ON external_event_inbox BEGIN
          SELECT RAISE(ABORT, 'inbox events may be deleted only by retention after processing')
          WHERE OLD.state <> 'processed' OR OLD.processed_at IS NULL
             OR julianday(OLD.processed_at) > julianday('now', '-{RETENTION_DAYS} days');
        END""",
    )
    for statement in statements:
        op.execute(sa.text(statement))


def upgrade():
    _create_table()
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        _postgresql_triggers()
    elif dialect == "sqlite":
        _sqlite_triggers()


def downgrade():
    """Remove the inbox only while it holds no event evidence."""
    bind = op.get_bind()
    count = bind.execute(sa.text(f"SELECT COUNT(*) FROM {INBOX_TABLE}")).scalar() or 0
    if count:
        raise ExternalEventInboxNotEmptyError(
            f"Cannot downgrade {revision}: {INBOX_TABLE}={count}. Phase 5.1 downgrade may "
            "remove only an empty inbox."
        )
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_external_event_inbox_guard ON external_event_inbox"))
        op.execute(sa.text("DROP FUNCTION IF EXISTS phase5_inbox_guard()"))
        op.execute(sa.text("DROP FUNCTION IF EXISTS phase5_inbox_summary_valid(jsonb)"))
    elif dialect == "sqlite":
        for trigger in (
            "trg_external_event_inbox_delete",
            "trg_external_event_inbox_update",
            "trg_external_event_inbox_insert",
        ):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger}"))
    op.drop_index("ix_external_event_inbox_state_processed", table_name=INBOX_TABLE)
    op.drop_index("ix_external_event_inbox_provider_object_created", table_name=INBOX_TABLE)
    op.drop_index("ix_external_event_inbox_state_next_attempt", table_name=INBOX_TABLE)
    op.drop_table(INBOX_TABLE)
