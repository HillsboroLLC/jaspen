"""I3: durable state of the reliable-delivery worker (inactive).

Adds three operational tables; no row is created:

* ``ai_delivery_jobs``: one job per Phase 12-bound operation (the primary key
  references ``ai_billing_operations``). Its identity, executor and payload are
  immutable and must equal the operation's Phase 12 binding (criterion 8). A
  finished job is immutable. Jobs are never deleted.
* ``ai_delivery_stream_chunks``: append-only streamed display progress.
* ``ai_delivery_worker_state``: the recovery sweep's cursors.

And one guard on Phase 12 (M2, persist before settle): for an operation that
has a delivery job, ``ai_billing_operations`` may record ``delivered`` only when
the operation's Phase 17 envelope (``ai_operations.result_json.reliable_delivery``)
exists and names the same delivered attempt. Operations without a job are not
affected.

And one guard on ``ai_operations`` (M3) for Phase 12-bound rows: the durable
identity (``organization_id``, ``user_id``, ``billing_account_id``) is never
rewritten to another value (only a first binding from NULL, or the foreign keys'
``ON DELETE SET NULL``, which recovery reports as blocked and fails closed); and
once a Phase 17 envelope is saved it cannot be removed or changed, except that its
``settlement`` is recorded once.

Downgrade refuses while any delivery job exists.

Revision ID: d7e9b1c3a5f8
Revises: a1f3c5e7b9d0
"""

from alembic import op
import sqlalchemy as sa


revision = "d7e9b1c3a5f8"
down_revision = "a1f3c5e7b9d0"
branch_labels = None
depends_on = None

ENVELOPE_SCHEMA = "jaspen.reliable-delivery.v1"

# Literal copies of the model CHECK constraints: a revision never reads live models.
JOB_CHECKS = (
    ("state IN ('queued', 'running', 'persisted', 'finished')", "ck_ai_delivery_jobs_state"),
    ("outcome IS NULL OR outcome IN ('delivered', 'undelivered', 'no_billable_usage', 'unsettled')",
     "ck_ai_delivery_jobs_outcome"),
    ("(state = 'finished') = (outcome IS NOT NULL)", "ck_ai_delivery_jobs_finished"),
    ("claims >= 0 AND max_claims >= 1 AND attempts_started >= 0 AND provider_timeout_seconds > 0 "
     "AND heartbeat_interval_seconds > 0 AND job_lease_seconds > heartbeat_interval_seconds",
     "ck_ai_delivery_jobs_bounds"),
    ("length(payload_sha256) = 64 AND length(trim(executor)) > 0", "ck_ai_delivery_jobs_payload"),
)

PG_FUNCTIONS = ("i3_delivery_job_guard", "i3_delivery_chunk_guard", "i3_delivered_requires_envelope",
                "i3_bound_operation_guard")


class DeliveryJobsNotEmptyError(RuntimeError):
    """Downgrade refuses to discard delivery jobs."""


def _fk(name, table, column, constraint):
    return sa.Column(name, sa.String(36), sa.ForeignKey(f"{table}.{column}", name=constraint, ondelete="RESTRICT"),
                     nullable=False)


def _tables():
    op.create_table(
        "ai_delivery_jobs",
        sa.Column("operation_id", sa.String(36),
                  sa.ForeignKey("ai_billing_operations.operation_id", name="fk_ai_delivery_jobs_operation",
                                ondelete="RESTRICT"),
                  primary_key=True),
        _fk("organization_id", "organizations", "id", "fk_ai_delivery_jobs_organization"),
        _fk("actor_user_id", "users", "id", "fk_ai_delivery_jobs_actor"),
        sa.Column("executor", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("outcome", sa.String(24), nullable=True),
        sa.Column("lease_owner", sa.String(255), nullable=True),
        sa.Column("lease_token", sa.String(36), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claims", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_claims", sa.Integer(), nullable=False),
        sa.Column("attempts_started", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("inflight_call_json", sa.JSON(), nullable=True),
        sa.Column("provider_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("heartbeat_interval_seconds", sa.Integer(), nullable=False),
        sa.Column("job_lease_seconds", sa.Integer(), nullable=False),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("persisted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        *(sa.CheckConstraint(condition, name=name) for condition, name in JOB_CHECKS),
    )
    op.create_index("ix_ai_delivery_jobs_state_lease", "ai_delivery_jobs", ["state", "lease_expires_at"])
    op.create_table(
        "ai_delivery_stream_chunks",
        sa.Column("operation_id", sa.String(36),
                  sa.ForeignKey("ai_delivery_jobs.operation_id", name="fk_ai_delivery_stream_chunks_job",
                                ondelete="RESTRICT"),
                  primary_key=True),
        sa.Column("attempt_number", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempt_number >= 1 AND seq >= 1", name="ck_ai_delivery_stream_chunks_order"),
    )
    op.create_table(
        "ai_delivery_worker_state",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("cursor_json", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def _postgres_guards():
    yield """
        CREATE FUNCTION i3_delivery_job_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'delivery jobs are never deleted';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NOT EXISTS (
                    SELECT 1 FROM ai_billing_operations billing
                    WHERE billing.operation_id = NEW.operation_id
                      AND billing.organization_id = NEW.organization_id
                      AND billing.actor_user_id = NEW.actor_user_id
                ) THEN
                    RAISE EXCEPTION USING ERRCODE = '23514',
                        MESSAGE = 'a delivery job must match its operation''s Phase 12 identity';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.state = 'finished' THEN
                RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'a finished delivery job is immutable';
            END IF;
            IF NEW.operation_id IS DISTINCT FROM OLD.operation_id
               OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
               OR NEW.actor_user_id IS DISTINCT FROM OLD.actor_user_id
               OR NEW.executor IS DISTINCT FROM OLD.executor
               OR NEW.payload_sha256 IS DISTINCT FROM OLD.payload_sha256
               OR NEW.payload_json::text IS DISTINCT FROM OLD.payload_json::text
               OR NEW.created_at IS DISTINCT FROM OLD.created_at
               OR NEW.max_claims IS DISTINCT FROM OLD.max_claims
               OR NEW.provider_timeout_seconds IS DISTINCT FROM OLD.provider_timeout_seconds
               OR NEW.heartbeat_interval_seconds IS DISTINCT FROM OLD.heartbeat_interval_seconds
               OR NEW.job_lease_seconds IS DISTINCT FROM OLD.job_lease_seconds
               OR NEW.claims < OLD.claims
               OR NEW.attempts_started < OLD.attempts_started
               OR (OLD.cancel_requested_at IS NOT NULL
                   AND NEW.cancel_requested_at IS DISTINCT FROM OLD.cancel_requested_at)
               OR (OLD.state = 'persisted' AND NEW.state NOT IN ('persisted', 'finished')) THEN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    MESSAGE = 'a delivery job''s identity, payload and history are immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """
    yield """
        CREATE TRIGGER trg_i3_delivery_job_guard
        BEFORE INSERT OR UPDATE OR DELETE ON ai_delivery_jobs
        FOR EACH ROW EXECUTE FUNCTION i3_delivery_job_guard()
    """
    yield """
        CREATE FUNCTION i3_delivery_chunk_guard() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'delivery stream chunks are append-only';
        END;
        $$ LANGUAGE plpgsql
    """
    yield """
        CREATE TRIGGER trg_i3_delivery_chunk_guard
        BEFORE UPDATE OR DELETE ON ai_delivery_stream_chunks
        FOR EACH ROW EXECUTE FUNCTION i3_delivery_chunk_guard()
    """
    yield f"""
        CREATE FUNCTION i3_delivered_requires_envelope() RETURNS trigger AS $$
        BEGIN
            IF NEW.delivery_status = 'delivered'
               AND OLD.delivery_status IS DISTINCT FROM 'delivered'
               AND EXISTS (SELECT 1 FROM ai_delivery_jobs job WHERE job.operation_id = NEW.operation_id)
               AND NOT EXISTS (
                   SELECT 1 FROM ai_operations operation
                   WHERE operation.id = NEW.operation_id
                     AND operation.result_json::jsonb #>> '{{reliable_delivery,schema}}' = '{ENVELOPE_SCHEMA}'
                     AND (operation.result_json::jsonb #>> '{{reliable_delivery,delivered_attempt_number}}')
                         = NEW.delivered_attempt_number::text
               ) THEN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    MESSAGE = 'a worker-delivered operation settles only after its response is persisted';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """
    yield """
        CREATE TRIGGER trg_i3_delivered_requires_envelope
        BEFORE UPDATE ON ai_billing_operations
        FOR EACH ROW EXECUTE FUNCTION i3_delivered_requires_envelope()
    """
    yield """
        CREATE FUNCTION i3_bound_operation_guard() RETURNS trigger AS $$
        DECLARE
            before_envelope jsonb := OLD.result_json::jsonb -> 'reliable_delivery';
            after_envelope jsonb := NEW.result_json::jsonb -> 'reliable_delivery';
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM ai_billing_operations WHERE operation_id = OLD.id) THEN
                RETURN NEW;
            END IF;
            IF (OLD.organization_id IS NOT NULL AND NEW.organization_id IS NOT NULL
                    AND NEW.organization_id <> OLD.organization_id)
               OR (OLD.user_id IS NOT NULL AND NEW.user_id IS NOT NULL AND NEW.user_id <> OLD.user_id)
               OR (OLD.billing_account_id IS NOT NULL
                   AND NEW.billing_account_id IS DISTINCT FROM OLD.billing_account_id) THEN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    MESSAGE = 'a Phase 12-bound operation''s identity is immutable';
            END IF;
            IF before_envelope IS NOT NULL AND (
                after_envelope IS NULL
                OR (before_envelope - 'settlement') IS DISTINCT FROM (after_envelope - 'settlement')
                OR (before_envelope -> 'settlement' <> 'null'::jsonb
                    AND (before_envelope -> 'settlement') IS DISTINCT FROM (after_envelope -> 'settlement'))
            ) THEN
                RAISE EXCEPTION USING ERRCODE = '23514',
                    MESSAGE = 'a saved reliable-delivery response is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """
    yield """
        CREATE TRIGGER trg_i3_bound_operation_guard
        BEFORE UPDATE ON ai_operations
        FOR EACH ROW EXECUTE FUNCTION i3_bound_operation_guard()
    """


def _sqlite_raise(message, condition):
    return f"WHEN {condition} BEGIN SELECT RAISE(ABORT, '{message}'); END"


def _sqlite_guards():
    yield ("CREATE TRIGGER trg_i3_delivery_job_insert BEFORE INSERT ON ai_delivery_jobs FOR EACH ROW "
           + _sqlite_raise(
               "a delivery job must match its operation Phase 12 identity",
               "NOT EXISTS (SELECT 1 FROM ai_billing_operations billing WHERE billing.operation_id = NEW.operation_id "
               "AND billing.organization_id = NEW.organization_id AND billing.actor_user_id = NEW.actor_user_id)",
           ))
    yield ("CREATE TRIGGER trg_i3_delivery_job_update BEFORE UPDATE ON ai_delivery_jobs FOR EACH ROW "
           + _sqlite_raise(
               "a delivery job identity, payload and history are immutable",
               "OLD.state = 'finished' OR NEW.operation_id IS NOT OLD.operation_id "
               "OR NEW.organization_id IS NOT OLD.organization_id OR NEW.actor_user_id IS NOT OLD.actor_user_id "
               "OR NEW.executor IS NOT OLD.executor OR NEW.payload_sha256 IS NOT OLD.payload_sha256 "
               "OR NEW.payload_json IS NOT OLD.payload_json OR NEW.created_at IS NOT OLD.created_at "
               "OR NEW.max_claims IS NOT OLD.max_claims "
               "OR NEW.provider_timeout_seconds IS NOT OLD.provider_timeout_seconds "
               "OR NEW.heartbeat_interval_seconds IS NOT OLD.heartbeat_interval_seconds "
               "OR NEW.job_lease_seconds IS NOT OLD.job_lease_seconds "
               "OR NEW.claims < OLD.claims OR NEW.attempts_started < OLD.attempts_started "
               "OR (OLD.cancel_requested_at IS NOT NULL AND NEW.cancel_requested_at IS NOT OLD.cancel_requested_at) "
               "OR (OLD.state = 'persisted' AND NEW.state NOT IN ('persisted', 'finished'))",
           ))
    yield ("CREATE TRIGGER trg_i3_delivery_job_delete BEFORE DELETE ON ai_delivery_jobs FOR EACH ROW "
           "BEGIN SELECT RAISE(ABORT, 'delivery jobs are never deleted'); END")
    for action in ("update", "delete"):
        yield (f"CREATE TRIGGER trg_i3_delivery_chunk_{action} BEFORE {action.upper()} ON ai_delivery_stream_chunks "
               "FOR EACH ROW BEGIN SELECT RAISE(ABORT, 'delivery stream chunks are append-only'); END")
    yield ("CREATE TRIGGER trg_i3_delivered_requires_envelope BEFORE UPDATE ON ai_billing_operations FOR EACH ROW "
           + _sqlite_raise(
               "a worker-delivered operation settles only after its response is persisted",
               "NEW.delivery_status = 'delivered' AND OLD.delivery_status IS NOT 'delivered' "
               "AND EXISTS (SELECT 1 FROM ai_delivery_jobs job WHERE job.operation_id = NEW.operation_id) "
               "AND NOT EXISTS (SELECT 1 FROM ai_operations operation WHERE operation.id = NEW.operation_id "
               f"AND json_extract(operation.result_json, '$.reliable_delivery.schema') = '{ENVELOPE_SCHEMA}' "
               "AND json_extract(operation.result_json, '$.reliable_delivery.delivered_attempt_number') "
               "= NEW.delivered_attempt_number)",
           ))
    bound = "EXISTS (SELECT 1 FROM ai_billing_operations WHERE operation_id = OLD.id)"
    yield ("CREATE TRIGGER trg_i3_bound_operation_identity BEFORE UPDATE ON ai_operations FOR EACH ROW "
           + _sqlite_raise(
               "a Phase 12-bound operation identity is immutable",
               f"{bound} AND ((OLD.organization_id IS NOT NULL AND NEW.organization_id IS NOT NULL "
               "AND NEW.organization_id <> OLD.organization_id) "
               "OR (OLD.user_id IS NOT NULL AND NEW.user_id IS NOT NULL AND NEW.user_id <> OLD.user_id) "
               "OR (OLD.billing_account_id IS NOT NULL AND NEW.billing_account_id IS NOT OLD.billing_account_id))",
           ))
    before = "json_extract(OLD.result_json, '$.reliable_delivery')"
    after = "json_extract(NEW.result_json, '$.reliable_delivery')"
    yield ("CREATE TRIGGER trg_i3_bound_operation_envelope BEFORE UPDATE ON ai_operations FOR EACH ROW "
           + _sqlite_raise(
               "a saved reliable-delivery response is immutable",
               f"{bound} AND {before} IS NOT NULL AND ({after} IS NULL "
               f"OR json_remove({before}, '$.settlement') IS NOT json_remove({after}, '$.settlement') "
               "OR (json_extract(OLD.result_json, '$.reliable_delivery.settlement') IS NOT NULL "
               "AND json(json_extract(OLD.result_json, '$.reliable_delivery.settlement')) IS NOT "
               "json(json_extract(NEW.result_json, '$.reliable_delivery.settlement'))))",
           ))


SQLITE_TRIGGERS = (
    "trg_i3_delivery_job_insert", "trg_i3_delivery_job_update", "trg_i3_delivery_job_delete",
    "trg_i3_delivery_chunk_update", "trg_i3_delivery_chunk_delete", "trg_i3_delivered_requires_envelope",
    "trg_i3_bound_operation_identity", "trg_i3_bound_operation_envelope",
)


def upgrade():
    _tables()
    guards = _postgres_guards() if op.get_bind().dialect.name == "postgresql" else _sqlite_guards()
    for statement in guards:
        op.execute(sa.text(statement))


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM ai_delivery_jobs LIMIT 1")).first() is not None:
        raise DeliveryJobsNotEmptyError("cannot remove the delivery worker tables while delivery jobs exist")
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_i3_bound_operation_guard ON ai_operations"))
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_i3_delivered_requires_envelope ON ai_billing_operations"))
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_i3_delivery_chunk_guard ON ai_delivery_stream_chunks"))
        op.execute(sa.text("DROP TRIGGER IF EXISTS trg_i3_delivery_job_guard ON ai_delivery_jobs"))
        for name in PG_FUNCTIONS:
            op.execute(sa.text(f"DROP FUNCTION IF EXISTS {name}()"))
    else:
        for name in SQLITE_TRIGGERS:
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {name}"))
    op.drop_table("ai_delivery_worker_state")
    op.drop_table("ai_delivery_stream_chunks")
    op.drop_index("ix_ai_delivery_jobs_state_lease", table_name="ai_delivery_jobs")
    op.drop_table("ai_delivery_jobs")
