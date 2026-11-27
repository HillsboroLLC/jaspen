"""I3: durable state of the reliable-delivery worker (inactive).

Operational state only. Financial facts stay in Phase 12 and the Phase 3
ledger; the saved response stays in the Phase 17 envelope on
``ai_operations.result_json``.

* ``ai_delivery_jobs``: one job per Phase 12-bound operation. Its identity,
  executor and request payload are immutable; the lease (owner, token, expiry)
  is the only thing that decides which worker runs it.
* ``ai_delivery_stream_chunks``: append-only display progress the route
  streams to the browser. It is never the result.
* ``ai_delivery_worker_state``: the recovery sweep's durable cursors.
"""

from datetime import datetime, timezone

from . import db


JOB_STATES = ("queued", "running", "persisted", "finished")
JOB_OUTCOMES = ("delivered", "undelivered", "no_billable_usage", "unsettled")


def _now():
    return datetime.now(timezone.utc)


def _quoted(values):
    return ", ".join(f"'{value}'" for value in values)


class AIDeliveryJob(db.Model):
    __tablename__ = "ai_delivery_jobs"

    operation_id = db.Column(
        db.String(36),
        db.ForeignKey("ai_billing_operations.operation_id", name="fk_ai_delivery_jobs_operation",
                      ondelete="RESTRICT"),
        primary_key=True,
    )
    organization_id = db.Column(
        db.String(36),
        db.ForeignKey("organizations.id", name="fk_ai_delivery_jobs_organization", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", name="fk_ai_delivery_jobs_actor", ondelete="RESTRICT"),
        nullable=False,
    )
    executor = db.Column(db.String(64), nullable=False)
    payload_json = db.Column(db.JSON, nullable=False)
    payload_sha256 = db.Column(db.String(64), nullable=False)
    state = db.Column(db.String(16), nullable=False, default="queued", server_default="queued")
    outcome = db.Column(db.String(24), nullable=True)
    lease_owner = db.Column(db.String(255), nullable=True)
    lease_token = db.Column(db.String(36), nullable=True)
    lease_expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    claims = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    max_claims = db.Column(db.Integer, nullable=False)
    attempts_started = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    # The provider call a worker is about to make or is making: set after the
    # Phase 12 pre-call check, cleared when the call is recorded. A reclaiming
    # worker records a marker it finds as a lost call (unknown usage, absorbed).
    inflight_call_json = db.Column(db.JSON, nullable=True)
    provider_timeout_seconds = db.Column(db.Integer, nullable=False)
    heartbeat_interval_seconds = db.Column(db.Integer, nullable=False)
    job_lease_seconds = db.Column(db.Integer, nullable=False)
    cancel_requested_at = db.Column(db.DateTime(timezone=True), nullable=True)
    heartbeat_at = db.Column(db.DateTime(timezone=True), nullable=True)
    persisted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True)
    error_code = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    __table_args__ = (
        db.CheckConstraint(f"state IN ({_quoted(JOB_STATES)})", name="ck_ai_delivery_jobs_state"),
        db.CheckConstraint(f"outcome IS NULL OR outcome IN ({_quoted(JOB_OUTCOMES)})",
                           name="ck_ai_delivery_jobs_outcome"),
        db.CheckConstraint("(state = 'finished') = (outcome IS NOT NULL)", name="ck_ai_delivery_jobs_finished"),
        db.CheckConstraint(
            "claims >= 0 AND max_claims >= 1 AND attempts_started >= 0 AND provider_timeout_seconds > 0 "
            "AND heartbeat_interval_seconds > 0 AND job_lease_seconds > heartbeat_interval_seconds",
            name="ck_ai_delivery_jobs_bounds",
        ),
        db.CheckConstraint("length(payload_sha256) = 64 AND length(trim(executor)) > 0",
                           name="ck_ai_delivery_jobs_payload"),
        db.Index("ix_ai_delivery_jobs_state_lease", "state", "lease_expires_at"),
    )


class AIDeliveryStreamChunk(db.Model):
    __tablename__ = "ai_delivery_stream_chunks"

    operation_id = db.Column(
        db.String(36),
        db.ForeignKey("ai_delivery_jobs.operation_id", name="fk_ai_delivery_stream_chunks_job",
                      ondelete="RESTRICT"),
        primary_key=True,
    )
    attempt_number = db.Column(db.Integer, primary_key=True, autoincrement=False)
    seq = db.Column(db.Integer, primary_key=True, autoincrement=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        db.CheckConstraint("attempt_number >= 1 AND seq >= 1", name="ck_ai_delivery_stream_chunks_order"),
    )


class AIDeliveryWorkerState(db.Model):
    __tablename__ = "ai_delivery_worker_state"

    key = db.Column(db.String(64), primary_key=True)
    cursor_json = db.Column(db.JSON, nullable=True)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
