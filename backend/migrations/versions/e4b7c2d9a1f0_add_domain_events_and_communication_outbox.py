"""Add inactive Phase 5.4 domain-event and communication-outbox foundations.

Revision ID: e4b7c2d9a1f0
Revises: d3e5a7b9c1f4
"""

from alembic import op
import sqlalchemy as sa


revision = "e4b7c2d9a1f0"
down_revision = "d3e5a7b9c1f4"
branch_labels = None
depends_on = None


class BillingOutboxNotEmptyError(RuntimeError):
    """Raised when downgrade would discard domain-event or delivery evidence."""


def _create_tables():
    op.create_table(
        "domain_events",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("billing_account_id", sa.String(36), nullable=False),
        sa.Column("event_key", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("aggregate_type", sa.String(80), nullable=False),
        sa.Column("aggregate_id", sa.String(255), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "reference_ids_json", sa.JSON(), nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "length(trim(event_key)) > 0 AND length(trim(event_type)) > 0 "
            "AND length(trim(aggregate_type)) > 0 AND length(trim(aggregate_id)) > 0",
            name="ck_domain_events_identity",
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64 "
            "AND request_fingerprint = lower(request_fingerprint)",
            name="ck_domain_events_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["billing_account_id"], ["billing_accounts.id"],
            name="fk_domain_events_billing_account_id", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_domain_events"),
        sa.UniqueConstraint("event_key", name="uq_domain_events_event_key"),
        sa.UniqueConstraint("id", "billing_account_id", name="uq_domain_events_id_account"),
    )
    op.create_index(
        "ix_domain_events_account_created", "domain_events",
        ["billing_account_id", "created_at"],
    )

    op.create_table(
        "communication_outbox",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("domain_event_id", sa.String(36), nullable=False),
        sa.Column("billing_account_id", sa.String(36), nullable=False),
        sa.Column("template_key", sa.String(120), nullable=False),
        sa.Column("template_version", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(40), nullable=False),
        sa.Column("locale", sa.String(35), nullable=False),
        sa.Column("dedupe_key", sa.String(512), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "length(trim(template_key)) > 0 AND length(trim(template_version)) > 0 "
            "AND length(trim(channel)) > 0 AND length(trim(locale)) > 0 "
            "AND length(trim(dedupe_key)) > 0 "
            "AND template_version NOT LIKE '%:%' AND channel NOT LIKE '%:%'",
            name="ck_communication_outbox_identity",
        ),
        sa.CheckConstraint(
            "dedupe_key = 'message:' || domain_event_id || ':' || template_version "
            "|| ':' || billing_account_id || ':' || channel",
            name="ck_communication_outbox_dedupe_key",
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'processing', 'retryable', 'delivered')",
            name="ck_communication_outbox_state",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_communication_outbox_attempt_count"),
        sa.CheckConstraint(
            "(state = 'processing' AND lease_expires_at IS NOT NULL) OR "
            "(state <> 'processing' AND lease_expires_at IS NULL)",
            name="ck_communication_outbox_lease",
        ),
        sa.CheckConstraint(
            "(state = 'retryable') OR next_attempt_at IS NULL",
            name="ck_communication_outbox_next_attempt",
        ),
        sa.CheckConstraint(
            "(state = 'delivered' AND delivered_at IS NOT NULL) OR "
            "(state <> 'delivered' AND delivered_at IS NULL)",
            name="ck_communication_outbox_delivered",
        ),
        sa.ForeignKeyConstraint(
            ["domain_event_id", "billing_account_id"],
            ["domain_events.id", "domain_events.billing_account_id"],
            name="fk_communication_outbox_event_account", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_communication_outbox"),
        sa.UniqueConstraint("dedupe_key", name="uq_communication_outbox_dedupe_key"),
        sa.UniqueConstraint(
            "domain_event_id", "template_version", "billing_account_id", "channel",
            name="uq_communication_outbox_event_template_recipient_channel",
        ),
    )
    op.create_index(
        "ix_communication_outbox_state_next_attempt", "communication_outbox",
        ["state", "next_attempt_at", "created_at"],
    )
    op.create_index(
        "ix_communication_outbox_domain_event_id", "communication_outbox",
        ["domain_event_id"],
    )

    op.create_table(
        "communication_outbox_attempts",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("outbox_id", sa.String(36), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(24), nullable=False, server_default="started"),
        sa.Column("provider_message_id", sa.String(255), nullable=True),
        sa.Column("error_code", sa.String(120), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_fingerprint", sa.String(64), nullable=True),
        sa.CheckConstraint("attempt_number > 0", name="ck_communication_outbox_attempt_number"),
        sa.CheckConstraint(
            "lease_expires_at > started_at",
            name="ck_communication_outbox_attempt_lease",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_communication_outbox_attempt_completed_at",
        ),
        sa.CheckConstraint(
            "next_attempt_at IS NULL OR next_attempt_at >= completed_at",
            name="ck_communication_outbox_attempt_next_at",
        ),
        sa.ForeignKeyConstraint(
            ["outbox_id"], ["communication_outbox.id"],
            name="fk_communication_outbox_attempts_outbox_id", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_communication_outbox_attempts"),
        sa.UniqueConstraint(
            "outbox_id", "attempt_number",
            name="uq_communication_outbox_attempt_number",
        ),
    )
    op.create_index(
        "ix_communication_outbox_attempts_outbox_started",
        "communication_outbox_attempts", ["outbox_id", "started_at"],
    )


def _create_sqlite_triggers():
    op.execute("""
    CREATE TRIGGER phase54_domain_events_insert_guard
    BEFORE INSERT ON domain_events
    BEGIN
      SELECT CASE WHEN json_valid(NEW.reference_ids_json) = 0
        OR json_type(NEW.reference_ids_json) <> 'array'
        OR EXISTS (
          SELECT 1 FROM json_each(NEW.reference_ids_json)
          WHERE type <> 'text' OR length(trim(value)) = 0
        )
        OR EXISTS (
          SELECT value FROM json_each(NEW.reference_ids_json)
          GROUP BY value HAVING count(*) > 1
        )
      THEN RAISE(ABORT, 'domain event references must be unique nonempty strings') END;
    END
    """)
    op.execute("""
    CREATE TRIGGER phase54_domain_events_no_update
    BEFORE UPDATE ON domain_events
    BEGIN SELECT RAISE(ABORT, 'domain event records are immutable'); END
    """)
    op.execute("""
    CREATE TRIGGER phase54_domain_events_no_delete
    BEFORE DELETE ON domain_events
    BEGIN SELECT RAISE(ABORT, 'domain event records are immutable'); END
    """)
    op.execute("""
    CREATE TRIGGER phase54_outbox_insert_guard
    BEFORE INSERT ON communication_outbox
    BEGIN
      SELECT CASE WHEN NEW.state <> 'pending'
        OR NEW.attempt_count <> 0
        OR NEW.next_attempt_at IS NOT NULL
        OR NEW.lease_expires_at IS NOT NULL
        OR NEW.delivered_at IS NOT NULL
      THEN RAISE(ABORT, 'outbox records must start pending') END;
    END
    """)
    op.execute("""
    CREATE TRIGGER phase54_outbox_no_delete
    BEFORE DELETE ON communication_outbox
    BEGIN SELECT RAISE(ABORT, 'outbox records are immutable'); END
    """)
    op.execute("""
    CREATE TRIGGER phase54_outbox_update_guard
    BEFORE UPDATE ON communication_outbox
    BEGIN
      SELECT CASE WHEN
        NEW.id <> OLD.id
        OR NEW.domain_event_id <> OLD.domain_event_id
        OR NEW.billing_account_id <> OLD.billing_account_id
        OR NEW.template_key <> OLD.template_key
        OR NEW.template_version <> OLD.template_version
        OR NEW.channel <> OLD.channel
        OR NEW.locale <> OLD.locale
        OR NEW.dedupe_key <> OLD.dedupe_key
        OR NEW.created_at <> OLD.created_at
      THEN RAISE(ABORT, 'outbox identity is immutable') END;
      SELECT CASE WHEN NOT (
        (OLD.state IN ('pending', 'retryable')
          AND NEW.state = 'processing'
          AND NEW.attempt_count = OLD.attempt_count + 1
          AND NEW.lease_expires_at IS NOT NULL
          AND NEW.next_attempt_at IS NULL
          AND NEW.delivered_at IS NULL
          AND EXISTS (
            SELECT 1 FROM communication_outbox_attempts attempt
            WHERE attempt.outbox_id = OLD.id
              AND attempt.attempt_number = NEW.attempt_count
              AND attempt.outcome = 'started'
              AND attempt.lease_expires_at = NEW.lease_expires_at
          ))
        OR
        (OLD.state = 'processing'
          AND NEW.state = 'delivered'
          AND NEW.attempt_count = OLD.attempt_count
          AND NEW.lease_expires_at IS NULL
          AND NEW.next_attempt_at IS NULL
          AND NEW.delivered_at IS NOT NULL
          AND EXISTS (
            SELECT 1 FROM communication_outbox_attempts attempt
            WHERE attempt.outbox_id = OLD.id
              AND attempt.attempt_number = OLD.attempt_count
              AND attempt.outcome = 'delivered'
              AND attempt.completed_at = NEW.delivered_at
          ))
        OR
        (OLD.state = 'processing'
          AND NEW.state = 'retryable'
          AND NEW.attempt_count = OLD.attempt_count
          AND NEW.lease_expires_at IS NULL
          AND NEW.delivered_at IS NULL
          AND EXISTS (
            SELECT 1 FROM communication_outbox_attempts attempt
            WHERE attempt.outbox_id = OLD.id
              AND attempt.attempt_number = OLD.attempt_count
              AND attempt.outcome = 'retryable_failure'
              AND attempt.next_attempt_at IS NEW.next_attempt_at
          ))
      ) THEN RAISE(ABORT, 'invalid outbox state transition') END;
    END
    """)
    op.execute("""
    CREATE TRIGGER phase54_attempt_no_delete
    BEFORE DELETE ON communication_outbox_attempts
    BEGIN SELECT RAISE(ABORT, 'outbox attempts are immutable'); END
    """)
    op.execute("""
    CREATE TRIGGER phase54_attempt_insert_guard
    BEFORE INSERT ON communication_outbox_attempts
    BEGIN
      SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM communication_outbox outbox
        WHERE outbox.id = NEW.outbox_id
          AND outbox.attempt_count + 1 = NEW.attempt_number
          AND outbox.state IN ('pending', 'retryable')
          AND (outbox.next_attempt_at IS NULL OR outbox.next_attempt_at <= NEW.started_at)
      ) THEN RAISE(ABORT, 'outbox is not eligible for a new attempt') END;
    END
    """)
    op.execute("""
    CREATE TRIGGER phase54_attempt_update_guard
    BEFORE UPDATE ON communication_outbox_attempts
    BEGIN
      SELECT CASE WHEN
        NEW.id <> OLD.id
        OR NEW.outbox_id <> OLD.outbox_id
        OR NEW.attempt_number <> OLD.attempt_number
        OR NEW.started_at <> OLD.started_at
        OR NEW.lease_expires_at <> OLD.lease_expires_at
        OR OLD.outcome <> 'started'
        OR NEW.outcome NOT IN ('delivered', 'retryable_failure')
        OR NOT EXISTS (
          SELECT 1 FROM communication_outbox outbox
          WHERE outbox.id = OLD.outbox_id
            AND outbox.state = 'processing'
            AND outbox.attempt_count = OLD.attempt_number
        )
        OR (NEW.outcome = 'delivered' AND NEW.completed_at >= OLD.lease_expires_at)
        OR (NEW.outcome = 'retryable_failure'
            AND NEW.error_code = 'delivery_lease_expired'
            AND NEW.completed_at < OLD.lease_expires_at)
        OR (NEW.outcome = 'retryable_failure'
            AND NEW.error_code <> 'delivery_lease_expired'
            AND NEW.completed_at >= OLD.lease_expires_at)
      THEN RAISE(ABORT, 'invalid outbox attempt transition') END;
    END
    """)
    op.execute("""
    CREATE TRIGGER phase54_attempt_after_insert
    AFTER INSERT ON communication_outbox_attempts
    BEGIN
      UPDATE communication_outbox
      SET state = 'processing',
          attempt_count = NEW.attempt_number,
          next_attempt_at = NULL,
          lease_expires_at = NEW.lease_expires_at,
          delivered_at = NULL,
          updated_at = NEW.started_at
      WHERE id = NEW.outbox_id;
    END
    """)
    op.execute("""
    CREATE TRIGGER phase54_attempt_after_update
    AFTER UPDATE ON communication_outbox_attempts
    BEGIN
      UPDATE communication_outbox
      SET state = CASE
            WHEN NEW.outcome = 'delivered' THEN 'delivered'
            ELSE 'retryable'
          END,
          next_attempt_at = NEW.next_attempt_at,
          lease_expires_at = NULL,
          delivered_at = CASE
            WHEN NEW.outcome = 'delivered' THEN NEW.completed_at
            ELSE NULL
          END,
          updated_at = NEW.completed_at
      WHERE id = NEW.outbox_id;
    END
    """)


def _create_postgresql_triggers():
    op.execute("""
    CREATE FUNCTION phase54_domain_event_immutable() RETURNS trigger AS $$
    BEGIN
      IF TG_OP = 'INSERT' THEN
        IF json_typeof(NEW.reference_ids_json) <> 'array' THEN
          RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'domain event references must be a JSON array';
        END IF;
        IF EXISTS (
          SELECT 1
          FROM json_array_elements(NEW.reference_ids_json) AS elements(item)
          WHERE json_typeof(item) <> 'string'
             OR length(trim(item #>> '{}')) = 0
        ) OR EXISTS (
          SELECT item #>> '{}'
          FROM json_array_elements(NEW.reference_ids_json) AS elements(item)
          GROUP BY item #>> '{}'
          HAVING count(*) > 1
        ) THEN
          RAISE EXCEPTION USING ERRCODE = '23514',
            MESSAGE = 'domain event references must be unique nonempty strings';
        END IF;
        RETURN NEW;
      END IF;
      RAISE EXCEPTION 'domain event records are immutable';
    END;
    $$ LANGUAGE plpgsql
    """)
    op.execute("""
    CREATE TRIGGER phase54_domain_events_immutable
    BEFORE INSERT OR UPDATE OR DELETE ON domain_events
    FOR EACH ROW EXECUTE FUNCTION phase54_domain_event_immutable()
    """)
    op.execute("""
    CREATE FUNCTION phase54_outbox_guard() RETURNS trigger AS $$
    BEGIN
      IF TG_OP = 'INSERT' THEN
        IF NEW.state <> 'pending'
          OR NEW.attempt_count <> 0
          OR NEW.next_attempt_at IS NOT NULL
          OR NEW.lease_expires_at IS NOT NULL
          OR NEW.delivered_at IS NOT NULL THEN
          RAISE EXCEPTION 'outbox records must start pending';
        END IF;
        RETURN NEW;
      END IF;
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'outbox records are immutable';
      END IF;
      IF NEW.id IS DISTINCT FROM OLD.id
        OR NEW.domain_event_id IS DISTINCT FROM OLD.domain_event_id
        OR NEW.billing_account_id IS DISTINCT FROM OLD.billing_account_id
        OR NEW.template_key IS DISTINCT FROM OLD.template_key
        OR NEW.template_version IS DISTINCT FROM OLD.template_version
        OR NEW.channel IS DISTINCT FROM OLD.channel
        OR NEW.locale IS DISTINCT FROM OLD.locale
        OR NEW.dedupe_key IS DISTINCT FROM OLD.dedupe_key
        OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'outbox identity is immutable';
      END IF;
      IF OLD.state IN ('pending', 'retryable')
        AND NEW.state = 'processing'
        AND NEW.attempt_count = OLD.attempt_count + 1
        AND NEW.lease_expires_at IS NOT NULL
        AND NEW.next_attempt_at IS NULL
        AND NEW.delivered_at IS NULL
        AND EXISTS (
          SELECT 1 FROM communication_outbox_attempts attempt
          WHERE attempt.outbox_id = OLD.id
            AND attempt.attempt_number = NEW.attempt_count
            AND attempt.outcome = 'started'
            AND attempt.lease_expires_at = NEW.lease_expires_at
        ) THEN
        RETURN NEW;
      END IF;
      IF OLD.state = 'processing'
        AND NEW.state = 'delivered'
        AND NEW.attempt_count = OLD.attempt_count
        AND NEW.lease_expires_at IS NULL
        AND NEW.next_attempt_at IS NULL
        AND NEW.delivered_at IS NOT NULL
        AND EXISTS (
          SELECT 1 FROM communication_outbox_attempts attempt
          WHERE attempt.outbox_id = OLD.id
            AND attempt.attempt_number = OLD.attempt_count
            AND attempt.outcome = 'delivered'
            AND attempt.completed_at = NEW.delivered_at
        ) THEN
        RETURN NEW;
      END IF;
      IF OLD.state = 'processing'
        AND NEW.state = 'retryable'
        AND NEW.attempt_count = OLD.attempt_count
        AND NEW.lease_expires_at IS NULL
        AND NEW.delivered_at IS NULL
        AND EXISTS (
          SELECT 1 FROM communication_outbox_attempts attempt
          WHERE attempt.outbox_id = OLD.id
            AND attempt.attempt_number = OLD.attempt_count
            AND attempt.outcome = 'retryable_failure'
            AND attempt.next_attempt_at IS NOT DISTINCT FROM NEW.next_attempt_at
        ) THEN
        RETURN NEW;
      END IF;
      RAISE EXCEPTION 'invalid outbox state transition';
    END;
    $$ LANGUAGE plpgsql
    """)
    op.execute("""
    CREATE TRIGGER phase54_outbox_update_guard
    BEFORE INSERT OR UPDATE OR DELETE ON communication_outbox
    FOR EACH ROW EXECUTE FUNCTION phase54_outbox_guard()
    """)
    op.execute("""
    CREATE FUNCTION phase54_attempt_guard() RETURNS trigger AS $$
    DECLARE
      parent_state text;
      parent_attempt_count integer;
      parent_next_attempt timestamptz;
    BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'outbox attempts are immutable';
      END IF;
      IF TG_OP = 'INSERT' THEN
        SELECT state, attempt_count, next_attempt_at
          INTO parent_state, parent_attempt_count, parent_next_attempt
          FROM communication_outbox WHERE id = NEW.outbox_id FOR UPDATE;
        IF NOT FOUND OR parent_state NOT IN ('pending', 'retryable')
          OR NEW.attempt_number <> parent_attempt_count + 1
          OR (parent_next_attempt IS NOT NULL AND parent_next_attempt > NEW.started_at) THEN
          RAISE EXCEPTION 'outbox is not eligible for a new attempt';
        END IF;
        RETURN NEW;
      END IF;
      IF NEW.id IS DISTINCT FROM OLD.id
        OR NEW.outbox_id IS DISTINCT FROM OLD.outbox_id
        OR NEW.attempt_number IS DISTINCT FROM OLD.attempt_number
        OR NEW.started_at IS DISTINCT FROM OLD.started_at
        OR NEW.lease_expires_at IS DISTINCT FROM OLD.lease_expires_at
        OR OLD.outcome <> 'started'
        OR NEW.outcome NOT IN ('delivered', 'retryable_failure') THEN
        RAISE EXCEPTION 'invalid outbox attempt transition';
      END IF;
      SELECT state, attempt_count
        INTO parent_state, parent_attempt_count
        FROM communication_outbox WHERE id = OLD.outbox_id FOR UPDATE;
      IF NOT FOUND OR parent_state <> 'processing'
        OR parent_attempt_count <> OLD.attempt_number THEN
        RAISE EXCEPTION 'outbox attempt claim is stale';
      END IF;
      IF NEW.outcome = 'delivered' AND NEW.completed_at >= OLD.lease_expires_at THEN
        RAISE EXCEPTION 'outbox attempt lease expired';
      END IF;
      IF NEW.outcome = 'retryable_failure'
        AND NEW.error_code = 'delivery_lease_expired'
        AND NEW.completed_at < OLD.lease_expires_at THEN
        RAISE EXCEPTION 'outbox lease has not expired';
      END IF;
      IF NEW.outcome = 'retryable_failure'
        AND NEW.error_code <> 'delivery_lease_expired'
        AND NEW.completed_at >= OLD.lease_expires_at THEN
        RAISE EXCEPTION 'outbox attempt lease expired';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """)
    op.execute("""
    CREATE TRIGGER phase54_attempt_guard
    BEFORE INSERT OR UPDATE OR DELETE ON communication_outbox_attempts
    FOR EACH ROW EXECUTE FUNCTION phase54_attempt_guard()
    """)
    op.execute("""
    CREATE FUNCTION phase54_attempt_project_outbox() RETURNS trigger AS $$
    BEGIN
      IF TG_OP = 'INSERT' THEN
        UPDATE communication_outbox
        SET state = 'processing',
            attempt_count = NEW.attempt_number,
            next_attempt_at = NULL,
            lease_expires_at = NEW.lease_expires_at,
            delivered_at = NULL,
            updated_at = NEW.started_at
        WHERE id = NEW.outbox_id;
        RETURN NEW;
      END IF;
      UPDATE communication_outbox
      SET state = CASE WHEN NEW.outcome = 'delivered' THEN 'delivered' ELSE 'retryable' END,
          next_attempt_at = NEW.next_attempt_at,
          lease_expires_at = NULL,
          delivered_at = CASE WHEN NEW.outcome = 'delivered' THEN NEW.completed_at ELSE NULL END,
          updated_at = NEW.completed_at
      WHERE id = NEW.outbox_id;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """)
    op.execute("""
    CREATE TRIGGER phase54_attempt_project_outbox
    AFTER INSERT OR UPDATE ON communication_outbox_attempts
    FOR EACH ROW EXECUTE FUNCTION phase54_attempt_project_outbox()
    """)
    op.execute("""
    CREATE FUNCTION phase54_reject_truncate() RETURNS trigger AS $$
    BEGIN
      RAISE EXCEPTION USING ERRCODE = '23514',
        MESSAGE = 'Phase 5.4 event and outbox evidence cannot be truncated';
    END;
    $$ LANGUAGE plpgsql
    """)
    for table in (
        "domain_events", "communication_outbox", "communication_outbox_attempts",
    ):
        op.execute(f"""
        CREATE TRIGGER phase54_{table}_no_truncate
        BEFORE TRUNCATE ON {table}
        FOR EACH STATEMENT EXECUTE FUNCTION phase54_reject_truncate()
        """)


def upgrade():
    dialect = op.get_bind().dialect.name
    _create_tables()
    if dialect == "postgresql":
        _create_postgresql_triggers()
    elif dialect == "sqlite":
        _create_sqlite_triggers()
    else:
        raise RuntimeError(f"unsupported migration dialect: {dialect}")


def downgrade():
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute(
            "LOCK TABLE domain_events, communication_outbox, "
            "communication_outbox_attempts IN ACCESS EXCLUSIVE MODE"
        )
    counts = {
        table: connection.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
        for table in (
            "communication_outbox_attempts",
            "communication_outbox",
            "domain_events",
        )
    }
    if any(counts.values()):
        raise BillingOutboxNotEmptyError(
            "cannot downgrade Phase 5.4 while event or outbox evidence exists"
        )

    if connection.dialect.name == "postgresql":
        for table in (
            "communication_outbox_attempts", "communication_outbox", "domain_events",
        ):
            op.execute(f"DROP TRIGGER phase54_{table}_no_truncate ON {table}")
        op.execute("DROP TRIGGER phase54_attempt_project_outbox ON communication_outbox_attempts")
        op.execute("DROP TRIGGER phase54_attempt_guard ON communication_outbox_attempts")
        op.execute("DROP TRIGGER phase54_outbox_update_guard ON communication_outbox")
        op.execute("DROP TRIGGER phase54_domain_events_immutable ON domain_events")
        op.execute("DROP FUNCTION phase54_attempt_project_outbox()")
        op.execute("DROP FUNCTION phase54_attempt_guard()")
        op.execute("DROP FUNCTION phase54_outbox_guard()")
        op.execute("DROP FUNCTION phase54_domain_event_immutable()")
        op.execute("DROP FUNCTION phase54_reject_truncate()")
    else:
        for trigger in (
            "phase54_attempt_after_update",
            "phase54_attempt_after_insert",
            "phase54_attempt_update_guard",
            "phase54_attempt_insert_guard",
            "phase54_attempt_no_delete",
            "phase54_outbox_update_guard",
            "phase54_outbox_insert_guard",
            "phase54_outbox_no_delete",
            "phase54_domain_events_insert_guard",
            "phase54_domain_events_no_delete",
            "phase54_domain_events_no_update",
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {trigger}")

    op.drop_index(
        "ix_communication_outbox_attempts_outbox_started",
        table_name="communication_outbox_attempts",
    )
    op.drop_table("communication_outbox_attempts")
    op.drop_index(
        "ix_communication_outbox_domain_event_id", table_name="communication_outbox",
    )
    op.drop_index(
        "ix_communication_outbox_state_next_attempt", table_name="communication_outbox",
    )
    op.drop_table("communication_outbox")
    op.drop_index("ix_domain_events_account_created", table_name="domain_events")
    op.drop_table("domain_events")
