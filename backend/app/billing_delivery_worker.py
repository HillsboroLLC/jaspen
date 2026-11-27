"""I3: the durable reliable-delivery worker for Phase 12-bound AI turns (inactive).

Closes the Phase 12 activation-gate criteria the Phase 17 boundary could not:
the provider work, response persistence and settlement run in a worker that is
independent of the client connection (1); a heartbeat renews the reservation
independently of the provider call (3); and retries, replays, late responses,
cancellations, restarts and concurrent workers never charge twice (5).
The interface for the AI runtime is ``docs/specs/billing/reliable-delivery-worker-interface.md``.

Authorities are unchanged: Phase 3 holds balances, Phase 12 decides every
financial outcome, and this module reaches Phase 12 only through the Phase 17
boundary (``billing_reliable_delivery``), whose ``settle_persisted_response`` is
the only settlement path (M2). Nothing in a route, job or startup imports this
module; the AI-reservation family runtime (I4) and the operator CLI
``scripts/billing_delivery_worker.py`` are its only callers.

Each step is its own short transaction, so every fact is committed before the
next step depends on it: claim, attempt start, pre-call marker, call record,
stream chunks, persistence, then settlement.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging
import threading
import time
import uuid

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy import exc as sa_exc
from sqlalchemy.orm import Session

from . import billing_reliable_delivery as rd
from .models_billing_delivery import AIDeliveryJob, AIDeliveryStreamChunk, AIDeliveryWorkerState


log = logging.getLogger(__name__)

DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 15
DEFAULT_MAX_CLAIMS = 3
STREAM_POLL_SECONDS = 0.25
STREAM_FLUSH_SECONDS = 0.25
STREAM_FLUSH_CHARS = 2048
READ_CHUNK_LIMIT = 500
PERSIST_ATTEMPTS = 3
SETTLE_ATTEMPTS = 5
RETRY_BACKOFF_SECONDS = 0.05
RECOVERY_STATE_KEY = "phase17_recovery"
# The executor rebuilds the turn from the payload (history plus attachment
# references), so the bound is generous; above it, submission is refused.
MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
LOST_CALL_ERROR = "worker_lost"


# ---------------------------------------------------------------------------
# Errors and results
# ---------------------------------------------------------------------------

class DeliveryError(rd.ReliableDeliveryError):
    pass


class DeliveryConflictError(DeliveryError):
    pass


DeliveryTimingError = rd.ReliableDeliveryTimingError


class LeaseLostError(DeliveryError):
    """Another worker owns the job now; this worker stops without closing it."""


class DeliveryFailed(Exception):
    """Raised by an executor: no usable response. ``code`` is operational, never customer wording."""

    def __init__(self, code):
        super().__init__(code)
        self.code = str(code)[:80]


@dataclass(frozen=True)
class DeliveryResult:
    delivered_attempt_number: int
    response: object
    on_persist: object = None  # callable(session, response); runs inside the persistence transaction


@dataclass(frozen=True)
class NoBillableUsage:
    pass


@dataclass(frozen=True)
class Chunk:
    attempt_number: int
    seq: int
    content: str
    restart: bool = False


@dataclass(frozen=True)
class DeliveryView:
    operation_id: str
    state: str
    outcome: str | None
    chunks: list
    cursor: tuple | None
    response: object
    persisted: bool
    finished: bool
    cancel_requested: bool
    billing_state: str | None = None       # Phase 12 state
    delivery_status: str | None = None     # Phase 12 delivery outcome, once recorded
    charged_credits: int | None = None     # once Phase 12 recorded an outcome
    absorbed_credits: int | None = None


# ---------------------------------------------------------------------------
# Executor registry
# ---------------------------------------------------------------------------

_EXECUTORS = {}


def executor(name):
    """Register the function that performs a job's provider work (I4 owns the function)."""
    if not isinstance(name, str) or not name.strip() or len(name) > 64:
        raise DeliveryError("an executor needs a short name")

    def register(fn):
        existing = _EXECUTORS.get(name)
        if existing is not None and existing is not fn:
            raise DeliveryConflictError(f"executor {name!r} is already registered")
        _EXECUTORS[name] = fn
        return fn
    return register


def registered_executors():
    return tuple(sorted(_EXECUTORS))


def unregister_executor(name):
    """For tests: forget one registration."""
    _EXECUTORS.pop(name, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clock(session):
    return rd._clock(session)


def _utc(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _positive(value, name):
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise DeliveryTimingError(f"{name} must be a positive whole number of seconds") from exc
    if value <= 0:
        raise DeliveryTimingError(f"{name} must be a positive whole number of seconds")
    return value


def _job_update():
    """Job updates are compare-and-set statements; never evaluate them against loaded objects."""
    return update(AIDeliveryJob).execution_options(synchronize_session=False)


def _job(session, operation_id, *, lock=False):
    query = select(AIDeliveryJob).where(AIDeliveryJob.operation_id == operation_id)
    if lock:
        query = query.with_for_update()
    job = session.execute(query).scalar_one_or_none()
    if job is not None:
        session.refresh(job)
    return job


def _lock_job(session, operation_id):
    """Lock the job row first: every worker transaction takes job, then account, then operation."""
    return _job(session, operation_id, lock=True)


def _job_for(session, operation_id, organization_id, actor_user_id):
    job = _job(session, operation_id)
    if job is None:
        raise DeliveryError("the operation has no delivery job")
    if job.organization_id != organization_id or job.actor_user_id != actor_user_id:
        raise rd.AIBillingIsolationError("the delivery belongs to another organization or member")
    return job


def _transient(exc):
    if isinstance(exc, rd.AIBillingRetryError):
        return True
    if isinstance(exc, sa_exc.OperationalError):
        return getattr(exc.orig, "pgcode", None) in rd.TRANSIENT_PGCODES or exc.connection_invalidated
    return False


def default_session_factory(engine=None):
    """A factory of independent sessions (one connection each), READ COMMITTED on PostgreSQL."""
    if engine is None:
        from . import db
        engine = db.engine
    if engine.dialect.name == "postgresql":
        engine = engine.execution_options(isolation_level="READ COMMITTED")

    def factory():
        return Session(engine, expire_on_commit=False)
    return factory


# ---------------------------------------------------------------------------
# Request-side commands (the AI runtime calls these inside its own transaction)
# ---------------------------------------------------------------------------

def submit_delivery(session, *, operation_id, organization_id, actor_user_id, executor, payload,
                    provider_timeout_seconds, heartbeat_interval_seconds=None, job_lease_seconds=None,
                    max_claims=None):
    """Hand an authorized operation's provider work to the worker. Writes only the job row.

    Fails closed before any write unless the operation is Phase 12-bound,
    ``authorized``, unsaved and owned by this identity, and the bound lease
    exceeds the provider timeout plus the heartbeat interval (criterion 3).
    Idempotent: the same payload returns the same job; a different one conflicts.
    """
    if not isinstance(executor, str) or not executor.strip() or len(executor) > 64:
        raise DeliveryError("a delivery needs its executor name")
    provider_timeout_seconds = _positive(provider_timeout_seconds, "provider_timeout_seconds")
    heartbeat_interval_seconds = _positive(
        heartbeat_interval_seconds or DEFAULT_HEARTBEAT_INTERVAL_SECONDS, "heartbeat_interval_seconds",
    )
    job_lease_seconds = _positive(job_lease_seconds or 3 * heartbeat_interval_seconds, "job_lease_seconds")
    max_claims = int(max_claims or DEFAULT_MAX_CLAIMS)
    if max_claims < 1:
        raise DeliveryError("max_claims must be at least 1")
    if len(rd._canonical(payload).encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise DeliveryError(f"the delivery payload exceeds {MAX_PAYLOAD_BYTES // (1024 * 1024)} MB")
    digest = rd._digest(payload)

    existing = _job(session, operation_id)
    if existing is not None:
        if (existing.organization_id, existing.actor_user_id, existing.executor, existing.payload_sha256) != (
                organization_id, actor_user_id, executor, digest):
            raise DeliveryConflictError("the operation already has a different delivery job")
        return existing

    facts = rd.delivery_billing_state(
        session, operation_id=operation_id, organization_id=organization_id, actor_user_id=actor_user_id,
    )
    if facts["state"] != "authorized" or facts["persisted"]:
        raise rd.AIBillingStateError("only an authorized, unanswered operation can be delivered")
    timing = rd.assert_delivery_timing(
        session, operation_id=operation_id, provider_timeout_seconds=provider_timeout_seconds,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
    )
    if not heartbeat_interval_seconds < job_lease_seconds < timing["lease_seconds"]:
        raise DeliveryTimingError(
            "the job lease must exceed the heartbeat interval and stay shorter than the reservation lease"
        )
    job = AIDeliveryJob(
        operation_id=operation_id, organization_id=organization_id, actor_user_id=actor_user_id,
        executor=executor, payload_json=payload, payload_sha256=digest, state="queued", max_claims=max_claims,
        provider_timeout_seconds=provider_timeout_seconds, heartbeat_interval_seconds=heartbeat_interval_seconds,
        job_lease_seconds=job_lease_seconds,
    )
    session.add(job)
    session.flush()
    return job


def release_unsubmitted_operation(session, *, operation_id, organization_id, actor_user_id):
    """Release a reservation that was never handed to the worker (for example, a timing refusal)."""
    if _job(session, operation_id) is not None:
        raise DeliveryError("the worker owns this operation; it is closed by the worker")
    return rd.close_delivery_without_usage(
        session, operation_id=operation_id, organization_id=organization_id, actor_user_id=actor_user_id,
    )


def request_cancellation(session, *, operation_id, organization_id, actor_user_id):
    """The customer stopped the turn (not a disconnect). Returns whether this call recorded it."""
    rd.delivery_view(session, operation_id=operation_id, organization_id=organization_id,
                     actor_user_id=actor_user_id)  # active member of the durable organization
    _job_for(session, operation_id, organization_id, actor_user_id)
    result = session.execute(_job_update().where(
        AIDeliveryJob.operation_id == operation_id,
        AIDeliveryJob.cancel_requested_at.is_(None),
        AIDeliveryJob.state.in_(("queued", "running")),  # a kept response can no longer be stopped
    ).values(cancel_requested_at=_clock(session)))
    session.flush()
    return result.rowcount == 1


def read_delivery(session, *, operation_id, organization_id, actor_user_id, after=None, include_chunks=True):
    """Pure read for the streaming route and for recovery after a disconnect.

    ``after`` is the previous view's ``cursor``. Chunks are display progress; the
    saved response, once present, is the result. When a newer attempt started,
    its chunks come from the beginning and the first has ``restart=True``.
    """
    view = rd.delivery_view(session, operation_id=operation_id, organization_id=organization_id,
                            actor_user_id=actor_user_id)
    job = _job_for(session, operation_id, organization_id, actor_user_id)
    latest = session.execute(select(func.max(AIDeliveryStreamChunk.attempt_number)).where(
        AIDeliveryStreamChunk.operation_id == operation_id,
    )).scalar_one()
    chunks = []
    cursor = tuple(after) if after else None
    if latest is not None and include_chunks:
        restart = cursor is not None and int(cursor[0]) < int(latest)
        from_seq = 0 if cursor is None or int(cursor[0]) < int(latest) else int(cursor[1])
        rows = session.execute(select(AIDeliveryStreamChunk).where(
            AIDeliveryStreamChunk.operation_id == operation_id,
            AIDeliveryStreamChunk.attempt_number == latest,
            AIDeliveryStreamChunk.seq > from_seq,
        ).order_by(AIDeliveryStreamChunk.seq).limit(READ_CHUNK_LIMIT)).scalars().all()
        for index, row in enumerate(rows):
            chunks.append(Chunk(row.attempt_number, row.seq, row.content, restart=restart and index == 0))
        if rows:
            cursor = (int(latest), int(rows[-1].seq))
    return DeliveryView(
        operation_id=operation_id, state=job.state, outcome=job.outcome, chunks=chunks, cursor=cursor,
        response=view["response"], persisted=view["persisted"], finished=job.state == "finished",
        cancel_requested=job.cancel_requested_at is not None,
        billing_state=view["billing_state"], delivery_status=view["delivery_status"],
        charged_credits=view["charged_credits"], absorbed_credits=view["absorbed_credits"],
    )


def delivery_outcome(session, *, operation_id, organization_id, actor_user_id):
    """Read-only: the job and Phase 12 outcome (charged credits once settled), for JSON callers."""
    view = read_delivery(session, operation_id=operation_id, organization_id=organization_id,
                         actor_user_id=actor_user_id, include_chunks=False)
    return {
        "operation_id": operation_id, "state": view.state, "outcome": view.outcome, "finished": view.finished,
        "persisted": view.persisted, "billing_state": view.billing_state,
        "delivery_status": view.delivery_status, "charged_credits": view.charged_credits,
        "absorbed_credits": view.absorbed_credits,
    }


# ---------------------------------------------------------------------------
# Executor context
# ---------------------------------------------------------------------------

@dataclass
class _Claim:
    operation_id: str
    organization_id: str
    actor_user_id: str
    executor: str
    payload: object
    token: str
    claims: int
    max_claims: int
    provider_timeout_seconds: int
    heartbeat_interval_seconds: int
    job_lease_seconds: int
    inflight: object
    cancel_requested: bool
    attempts_started: int


@dataclass
class _Signals:
    stop: threading.Event = field(default_factory=threading.Event)
    lease_lost: threading.Event = field(default_factory=threading.Event)
    cancelled: threading.Event = field(default_factory=threading.Event)
    lapsed: threading.Event = field(default_factory=threading.Event)
    persisted_elsewhere: threading.Event = field(default_factory=threading.Event)


class DeliveryContext:
    """What an executor may do. Every method commits its own short transaction."""

    def __init__(self, worker, claim, signals):
        self._worker = worker
        self._claim = claim
        self._signals = signals
        self._buffer = []
        self._buffer_attempt = None
        self._buffer_chars = 0
        self._last_flush = time.monotonic()
        self._seq = {}

    operation_id = property(lambda self: self._claim.operation_id)
    organization_id = property(lambda self: self._claim.organization_id)
    actor_user_id = property(lambda self: self._claim.actor_user_id)
    payload = property(lambda self: self._claim.payload)
    provider_timeout_seconds = property(lambda self: self._claim.provider_timeout_seconds)

    @staticmethod
    def now():
        return datetime.now(timezone.utc)

    def _identity(self):
        return {"operation_id": self.operation_id, "organization_id": self.organization_id,
                "actor_user_id": self.actor_user_id}

    def _owned(self):
        return and_(AIDeliveryJob.operation_id == self.operation_id,
                    AIDeliveryJob.lease_token == self._claim.token,
                    AIDeliveryJob.state == "running")

    def refresh(self, session=None):
        """Read the job's cancel request and lease ownership now (the heartbeat also does, each tick)."""
        if session is None:
            with self._worker._session() as own:
                return self.refresh(own)
        row = session.execute(select(AIDeliveryJob.cancel_requested_at, AIDeliveryJob.lease_token).where(
            AIDeliveryJob.operation_id == self.operation_id)).one()
        if row[0] is not None:
            self._signals.cancelled.set()
        if row[1] != self._claim.token:
            self._signals.lease_lost.set()

    def cancelled(self):
        return self._signals.cancelled.is_set()

    def lease_lost(self):
        return self._signals.lease_lost.is_set()

    def should_stop(self):
        signals = self._signals
        return signals.cancelled.is_set() or signals.lease_lost.is_set() or signals.persisted_elsewhere.is_set()

    def begin_attempt(self):
        """Allocate the next provider attempt number durably; refuses once this worker lost the job."""
        if self.should_stop():
            raise LeaseLostError("the job lease was lost") if self.lease_lost() else DeliveryFailed("stopped")
        self.flush()
        with self._worker._session() as session:
            changed = session.execute(_job_update().where(self._owned()).values(
                attempts_started=AIDeliveryJob.attempts_started + 1,
            )).rowcount
            if changed != 1:
                session.rollback()
                self._signals.lease_lost.set()
                raise LeaseLostError("the job lease was lost")
            number = int(session.execute(select(AIDeliveryJob.attempts_started).where(
                AIDeliveryJob.operation_id == self.operation_id,
            )).scalar_one())
            session.commit()
        return number

    def check_call(self, *, attempt_number, call_index, provider, model, max_input_tokens, max_output_tokens,
                   component=None):
        """Phase 12's pre-call check, then the durable in-flight marker for this call."""
        self.flush()
        if self.should_stop():
            raise LeaseLostError("the job lease was lost") if self.lease_lost() else DeliveryFailed("stopped")
        with self._worker._session() as session:
            self.refresh(session)
            if self.should_stop():
                raise LeaseLostError("the job lease was lost") if self.lease_lost() else DeliveryFailed("stopped")
            result = rd.check_delivery_call(
                session, **self._identity(), attempt_number=attempt_number, call_index=call_index,
                provider=provider, model=model, max_input_tokens=max_input_tokens,
                max_output_tokens=max_output_tokens,
            )
            marker = {
                "attempt_number": int(attempt_number), "call_index": int(call_index), "provider": provider,
                "model": model, "component": component or _component(attempt_number, call_index),
                "requested_at": _clock(session).isoformat(),
            }
            if session.execute(_job_update().where(self._owned()).values(
                    inflight_call_json=marker)).rowcount != 1:
                session.rollback()
                self._signals.lease_lost.set()
                raise LeaseLostError("the job lease was lost")
            session.commit()
        return result

    def record_call(self, *, attempt_number, call_index, provider, model, outcome, usage_label,
                    requested_at, finished_at=None, component=None, input_tokens=None, output_tokens=None,
                    error_category=None, provider_request_id=None, provider_reported_cost_usd=None,
                    duration_ms=None, status_code=None, operational_metadata=None):
        """Record a provider call's usage (Phase 12) and operational attempt (Phase 17) whatever its outcome."""
        self.flush()
        facts = dict(
            attempt_number=attempt_number, call_index=call_index,
            component=component or _component(attempt_number, call_index), provider=provider, model=model,
            outcome=outcome, usage_label=usage_label, input_tokens=input_tokens, output_tokens=output_tokens,
            requested_at=requested_at, finished_at=finished_at, error_category=error_category,
            provider_request_id=provider_request_id, provider_reported_cost_usd=provider_reported_cost_usd,
            duration_ms=duration_ms, status_code=status_code, operational_metadata=operational_metadata,
        )
        for attempt in range(SETTLE_ATTEMPTS):  # the record is fingerprint-idempotent, so a retry is safe
            try:
                with self._worker._session() as session:
                    _lock_job(session, self.operation_id)  # lock order everywhere: job, then account, then op
                    rd.record_delivery_call(session, **self._identity(), **facts)
                    session.execute(_job_update().where(self._owned()).values(inflight_call_json=None))
                    session.commit()
                return
            except Exception as exc:
                if not (_transient(exc) and attempt + 1 < SETTLE_ATTEMPTS):
                    raise
                time.sleep(RETRY_BACKOFF_SECONDS * (2 ** attempt))

    def emit(self, attempt_number, text):
        """Buffer streamed text for the browser; written in small batches."""
        if not text:
            return
        attempt_number = int(attempt_number)
        if self._buffer_attempt not in (None, attempt_number):
            self.flush()
        self._buffer_attempt = attempt_number
        self._buffer.append(str(text))
        self._buffer_chars += len(text)
        if self._buffer_chars >= STREAM_FLUSH_CHARS or time.monotonic() - self._last_flush >= STREAM_FLUSH_SECONDS:
            self.flush()

    def flush(self):
        if not self._buffer:
            return
        attempt = self._buffer_attempt
        content = "".join(self._buffer)
        self._buffer, self._buffer_chars, self._last_flush = [], 0, time.monotonic()
        with self._worker._session() as session:
            seq = self._seq.get(attempt)
            if seq is None:
                seq = int(session.execute(select(func.coalesce(func.max(AIDeliveryStreamChunk.seq), 0)).where(
                    AIDeliveryStreamChunk.operation_id == self.operation_id,
                    AIDeliveryStreamChunk.attempt_number == attempt,
                )).scalar_one())
            seq += 1
            session.add(AIDeliveryStreamChunk(operation_id=self.operation_id, attempt_number=attempt, seq=seq,
                                              content=content))
            self.refresh(session)
            session.commit()
            self._seq[attempt] = seq


def _component(attempt_number, call_index):
    if int(call_index) > 0:
        return "tool_iteration"
    return "primary" if int(attempt_number) == 1 else "fallback"


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------

class _Heartbeat(threading.Thread):
    """Renews the job lease and the Phase 12 reservation on its own session and thread.

    The provider call runs on the worker thread and never blocks this one.
    """

    def __init__(self, worker, claim, signals):
        super().__init__(name=f"delivery-heartbeat-{claim.operation_id[:8]}", daemon=True)
        self._worker, self._claim, self._signals = worker, claim, signals

    def run(self):
        interval = self._claim.heartbeat_interval_seconds
        while not self._signals.stop.wait(interval):
            try:
                if not self.tick():
                    return
            except Exception:  # a failed tick is retried next interval; the lease absorbs one miss
                log.warning("delivery heartbeat tick failed for %s", self._claim.operation_id, exc_info=True)

    def tick(self):
        """One heartbeat transaction; returns False once this worker no longer owns the job."""
        claim, signals = self._claim, self._signals
        with self._worker._heartbeat_session() as session:
            now = _clock(session)
            renewed = session.execute(_job_update().where(
                AIDeliveryJob.operation_id == claim.operation_id,
                AIDeliveryJob.lease_token == claim.token,
                AIDeliveryJob.state == "running",
            ).values(lease_expires_at=now + timedelta(seconds=claim.job_lease_seconds), heartbeat_at=now))
            if renewed.rowcount != 1:
                session.rollback()
                signals.lease_lost.set()
                return False
            job = _job(session, claim.operation_id)
            if job.cancel_requested_at is not None:
                signals.cancelled.set()
            facts = rd.delivery_billing_state(
                session, operation_id=claim.operation_id, organization_id=claim.organization_id,
                actor_user_id=claim.actor_user_id,
            )
            if facts["persisted"]:
                signals.persisted_elsewhere.set()
            if facts["state"] == "authorized" and not signals.lapsed.is_set():
                try:
                    with session.begin_nested():
                        rd.heartbeat_reliable_delivery(
                            session, operation_id=claim.operation_id, organization_id=claim.organization_id,
                            actor_user_id=claim.actor_user_id,
                            provider_timeout_seconds=claim.provider_timeout_seconds,
                            heartbeat_interval_seconds=claim.heartbeat_interval_seconds,
                        )
                except rd.ReservationLapsedError:
                    signals.lapsed.set()  # never revived; a late response is delivered without a charge
                except Exception as exc:  # the job lease renewal above still commits
                    if not (isinstance(exc, rd.AIBillingError) or _transient(exc)):
                        raise
                    log.warning("reservation renewal failed for %s; retried next tick", claim.operation_id,
                                exc_info=True)
            session.commit()
        return True


# ---------------------------------------------------------------------------
# The worker
# ---------------------------------------------------------------------------

class DeliveryWorker:
    """Runs jobs. Two session modes:

    * ``app`` and no ``session_factory`` (the runtime and the CLI): each step runs
      in its own pushed app context on that context's Flask-SQLAlchemy
      ``db.session``, so ``on_persist`` writes through the conversation store's
      own session in the persistence transaction; the heartbeat uses a separate
      session on its own connection.
    * an explicit ``session_factory`` (tests, tools): every step and the
      heartbeat get a new session from it.
    """

    def __init__(self, session_factory=None, *, owner=None, app=None, heartbeat_session_factory=None,
                 executors=None):
        self.owner = owner or f"delivery-worker-{uuid.uuid4().hex[:12]}"
        self._executors = None if executors is None else tuple(executors)  # None: every registered executor
        self._app = app
        self._scoped = session_factory is None and app is not None
        if self._scoped:
            from . import db
            with app.app_context():
                separate = default_session_factory(db.engine)
            self._session_factory = None
        else:
            self._session_factory = session_factory or default_session_factory()
            separate = self._session_factory
        self._heartbeat_factory = heartbeat_session_factory or separate

    @contextlib.contextmanager
    def _session(self):
        if self._scoped:
            from . import db
            with self._app.app_context():  # its own scoped db.session, removed when the context ends
                session = db.session
                try:
                    yield session
                except BaseException:
                    session.rollback()
                    raise
            return
        session = self._session_factory()
        try:
            yield session
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    @contextlib.contextmanager
    def _heartbeat_session(self):
        session = self._heartbeat_factory()
        try:
            yield session
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    @contextlib.contextmanager
    def _app_context(self):
        if self._app is None:
            yield
        else:
            with self._app.app_context():
                yield

    # -- claiming ---------------------------------------------------------

    def _claimable(self, now, executors):
        return and_(
            AIDeliveryJob.executor.in_(executors),
            AIDeliveryJob.state.in_(("queued", "running")),
            or_(AIDeliveryJob.lease_expires_at.is_(None), AIDeliveryJob.lease_expires_at <= now),
        )

    def claim(self, operation_id=None, *, executors=None):
        """Claim one job (a specific one, or the oldest available) by compare-and-set; None if none."""
        if executors is None:  # this worker's own work: what it can run
            executors = tuple(name for name in (self._executors or registered_executors()) if name in _EXECUTORS)
        executors = tuple(executors)
        if not executors:
            return None
        with self._session() as session:
            now = _clock(session)
            query = select(AIDeliveryJob).where(self._claimable(now, executors))
            if operation_id is not None:
                query = query.where(AIDeliveryJob.operation_id == operation_id)
            candidates = session.execute(query.order_by(AIDeliveryJob.created_at, AIDeliveryJob.operation_id)
                                         .limit(5).with_for_update(skip_locked=True)).scalars().all()
            for job in candidates:
                token = str(uuid.uuid4())
                changed = session.execute(_job_update().where(
                    AIDeliveryJob.operation_id == job.operation_id,
                    (AIDeliveryJob.lease_token.is_(None) if job.lease_token is None
                     else AIDeliveryJob.lease_token == job.lease_token),
                    self._claimable(now, executors),
                ).values(
                    state="running", lease_owner=self.owner, lease_token=token, claims=AIDeliveryJob.claims + 1,
                    lease_expires_at=now + timedelta(seconds=int(job.job_lease_seconds)), heartbeat_at=now,
                )).rowcount
                if changed == 1:
                    session.commit()
                    job = _job(session, job.operation_id)
                    return _Claim(
                        operation_id=job.operation_id, organization_id=job.organization_id,
                        actor_user_id=job.actor_user_id, executor=job.executor, payload=job.payload_json,
                        token=token, claims=int(job.claims), max_claims=int(job.max_claims),
                        provider_timeout_seconds=int(job.provider_timeout_seconds),
                        heartbeat_interval_seconds=int(job.heartbeat_interval_seconds),
                        job_lease_seconds=int(job.job_lease_seconds), inflight=job.inflight_call_json,
                        cancel_requested=job.cancel_requested_at is not None,
                        attempts_started=int(job.attempts_started),
                    )
            session.rollback()
        return None

    # -- running ----------------------------------------------------------

    def run_job(self, operation_id):
        """Claim and run one specific job to an outcome. Returns the job outcome, or None if not claimed."""
        claim = self.claim(operation_id)
        return None if claim is None else self._execute(claim)

    def run_once(self, *, max_jobs=1):
        """Claim and run up to ``max_jobs`` available jobs. Returns their outcomes."""
        outcomes = []
        for _ in range(max(1, int(max_jobs))):
            claim = self.claim()
            if claim is None:
                break
            outcomes.append((claim.operation_id, self._execute(claim)))
        return outcomes

    def _execute(self, claim):
        with self._app_context():
            return self._execute_claimed(claim)

    def _execute_claimed(self, claim):
        self._record_lost_call(claim)
        settled = self._finish_if_decided(claim)
        if settled is not _UNDECIDED:
            if settled is None:
                self._release_claim(claim)
            return settled
        fn = _EXECUTORS.get(claim.executor)
        signals = _Signals()
        if claim.cancel_requested:
            signals.cancelled.set()
        heartbeat = _Heartbeat(self, claim, signals)
        context = DeliveryContext(self, claim, signals)
        heartbeat.start()
        try:
            try:
                result = fn(context)
                context.flush()
            except LeaseLostError:
                return None
            except DeliveryFailed as failure:
                return self._close(claim, "undelivered", error_code=failure.code)
            except Exception as exc:  # the executor failed; the customer is never charged for it
                if signals.lease_lost.is_set():
                    return None
                log.warning("delivery executor failed for %s", claim.operation_id, exc_info=True)
                return self._close(claim, "undelivered", error_code=_error_code(exc))
            if isinstance(result, NoBillableUsage):
                return self._close(claim, "no_billable_usage")
            if not isinstance(result, DeliveryResult):
                return self._close(claim, "undelivered", error_code="executor_returned_no_result")
            context.refresh()
            if signals.lease_lost.is_set() and not signals.persisted_elsewhere.is_set():
                return None
            if signals.cancelled.is_set() and not signals.persisted_elsewhere.is_set():
                return self._close(claim, "undelivered", error_code="cancelled")
            persisted = self._persist(claim, result)
            if persisted == "cancelled":
                return self._close(claim, "undelivered", error_code="cancelled")
            if not persisted:
                if signals.lease_lost.is_set():
                    return None
                return self._close(claim, "undelivered", error_code="persist_failed")
        finally:
            signals.stop.set()
            heartbeat.join()
        return self.settle_saved_response(claim.operation_id)

    def _record_lost_call(self, claim):
        """A previous worker died during a provider call: record it as failed with unknown usage (absorbed)."""
        marker = claim.inflight
        if not isinstance(marker, dict):
            return
        with self._session() as session:
            try:
                with session.begin_nested():
                    rd.record_delivery_call(
                        session, operation_id=claim.operation_id, organization_id=claim.organization_id,
                        actor_user_id=claim.actor_user_id, attempt_number=int(marker["attempt_number"]),
                        call_index=int(marker["call_index"]), component=marker["component"],
                        provider=marker["provider"], model=marker["model"], outcome="failed",
                        usage_label="unknown", requested_at=datetime.fromisoformat(marker["requested_at"]),
                        error_category=LOST_CALL_ERROR, operational_metadata={"recovered_by": self.owner},
                    )
            except rd.AIBillingError:
                pass  # closed, or the dying worker recorded the call after all; never blocks recovery
            session.execute(_job_update().where(
                AIDeliveryJob.operation_id == claim.operation_id, AIDeliveryJob.lease_token == claim.token,
            ).values(inflight_call_json=None))
            session.commit()

    def _finish_if_decided(self, claim):
        """Before any provider work: settle a saved response, or close what can no longer run."""
        with self._session() as session:
            facts = rd.delivery_billing_state(
                session, operation_id=claim.operation_id, organization_id=claim.organization_id,
                actor_user_id=claim.actor_user_id,
            )
            now = _clock(session)
        if facts["persisted"]:
            self._mark_persisted(claim.operation_id)
            return self.settle_saved_response(claim.operation_id)
        if facts["state"] != "authorized":
            if facts["delivery_status"] in (None, "unsettled"):
                return self._close(claim, "undelivered", error_code="reservation_closed")
            return self._finish_job(claim.operation_id, facts["delivery_status"], token=claim.token)
        if claim.cancel_requested:
            return self._close(claim, "no_billable_usage" if claim.attempts_started == 0 else "undelivered",
                               error_code="cancelled")
        if claim.claims > claim.max_claims:
            return self._close(claim, "undelivered", error_code="claims_exhausted")
        if now >= _utc(facts["expires_at"]):
            return self._close(claim, "undelivered", error_code="reservation_lapsed")
        if claim.executor not in _EXECUTORS:
            return None
        return _UNDECIDED

    def _persist(self, claim, result):
        """Commit the saved response (and the runtime's own record of it) before settlement."""
        for attempt in range(PERSIST_ATTEMPTS):
            try:
                with self._session() as session:
                    job = _lock_job(session, claim.operation_id)
                    if job.cancel_requested_at is not None and job.state == "running":
                        session.rollback()
                        return "cancelled"  # the stop was recorded before this response was kept
                    _envelope, replay = rd.persist_successful_response(
                        session, operation_id=claim.operation_id, organization_id=claim.organization_id,
                        actor_user_id=claim.actor_user_id,
                        delivered_attempt_number=int(result.delivered_attempt_number),
                        response_json=result.response,
                    )
                    if not replay and result.on_persist is not None:
                        result.on_persist(session, result.response)
                    _set_persisted(session, claim.operation_id)
                    session.commit()
                return True
            except rd.ReliableDeliveryConflictError:
                # Another worker saved a different response first; that one is delivered.
                if self._mark_persisted(claim.operation_id):
                    return True
                return False
            except rd.AIBillingStateError:
                return False
            except Exception as exc:
                if attempt + 1 < PERSIST_ATTEMPTS and (_transient(exc) or not isinstance(exc, rd.AIBillingError)):
                    log.warning("delivery persistence retry for %s", claim.operation_id, exc_info=True)
                    time.sleep(RETRY_BACKOFF_SECONDS * (2 ** attempt))
                    continue
                log.warning("delivery persistence failed for %s", claim.operation_id, exc_info=True)
                return False
        return False

    def _mark_persisted(self, operation_id):
        with self._session() as session:
            operation_state = session.execute(select(AIDeliveryJob.organization_id, AIDeliveryJob.actor_user_id)
                                              .where(AIDeliveryJob.operation_id == operation_id)).one()
            facts = rd.delivery_billing_state(session, operation_id=operation_id,
                                              organization_id=operation_state[0],
                                              actor_user_id=operation_state[1])
            if not facts["persisted"]:
                return False
            _set_persisted(session, operation_id)
            session.commit()
        return True

    def settle_saved_response(self, operation_id):
        """Settle a saved response through ``settle_persisted_response`` only (M2), with bounded retries.

        Returns the outcome, or None when settlement must wait for recovery.
        """
        for attempt in range(SETTLE_ATTEMPTS):
            try:
                with self._session() as session:
                    job = _job(session, operation_id, lock=True)
                    if job is None:
                        raise DeliveryError("the operation has no delivery job")
                    if job.state == "finished":
                        session.rollback()
                        return job.outcome
                    result = rd.settle_persisted_response(
                        session, operation_id=operation_id, organization_id=job.organization_id,
                        actor_user_id=job.actor_user_id,
                    )
                    _finish(session, job, result.delivery_status)
                    session.commit()
                return result.delivery_status
            except Exception as exc:
                if _transient(exc) and attempt + 1 < SETTLE_ATTEMPTS:
                    time.sleep(RETRY_BACKOFF_SECONDS * (2 ** attempt))
                    continue
                log.warning("delivery settlement deferred to recovery for %s", operation_id, exc_info=True)
                return None
        return None

    def _close(self, claim, outcome, *, error_code=None):
        """Close without a charge (Phase 12 release/absorb) and finish the job in one transaction."""
        with self._session() as session:
            job = _job(session, claim.operation_id, lock=True)
            if job.state == "finished":
                session.rollback()
                return job.outcome
            if job.lease_token != claim.token:
                session.rollback()
                return None  # another worker owns it now
            identity = {"operation_id": claim.operation_id, "organization_id": claim.organization_id,
                        "actor_user_id": claim.actor_user_id}
            facts = rd.delivery_billing_state(session, **identity)
            if facts["persisted"]:
                session.rollback()
                self._mark_persisted(claim.operation_id)
                return self.settle_saved_response(claim.operation_id)
            delivery_status = None
            if outcome == "no_billable_usage":
                try:
                    with session.begin_nested():
                        delivery_status = rd.close_delivery_without_usage(session, **identity).delivery_status
                except rd.AIBillingStateError:
                    pass  # usage was recorded after all: close it as undelivered
            if delivery_status is None:
                try:
                    with session.begin_nested():
                        delivery_status = rd.close_delivery_undelivered(session, **identity).delivery_status
                except rd.AIBillingStateError:
                    # Phase 12 already holds another outcome; the job reports it.
                    delivery_status = rd.delivery_billing_state(session, **identity)["delivery_status"]
                    if delivery_status in (None, "unsettled"):
                        raise
            _finish(session, job, delivery_status, error_code=error_code)
            session.commit()
        return delivery_status

    def _finish_job(self, operation_id, outcome, *, token):
        with self._session() as session:
            job = _job(session, operation_id, lock=True)
            if job.state != "finished" and job.lease_token == token:
                _finish(session, job, outcome)
                session.commit()
            return job.outcome

    # -- recovery ---------------------------------------------------------

    def recover(self, *, limit=100, scan_limit=1000):
        """One bounded recovery round. Raises on a systemic error (the caller alerts and exits non-zero).

        1. settle saved responses of ``persisted`` jobs;
        2. the Phase 17 sweep over Phase 12 rows (settle saved responses, expire
           lapsed leases), resuming from its durable cursors;
        3. close jobs nobody runs any more whose reservation has closed or lapsed.
        """
        report = {"jobs_settled": [], "jobs_closed": [], "settled": [], "expired": [], "blocked": []}
        cursors = self._recovery_cursors()

        persisted, cursors["jobs_persisted"] = self._job_page(
            lambda now: AIDeliveryJob.state == "persisted", cursors.get("jobs_persisted"), limit)
        for operation_id in persisted:
            outcome = self.settle_saved_response(operation_id)  # never raises; None waits for a later round
            if outcome is not None:
                report["jobs_settled"].append({"operation_id": operation_id, "outcome": outcome})

        with self._session() as session:
            state = session.get(AIDeliveryWorkerState, RECOVERY_STATE_KEY, with_for_update=True)
            sweep = rd.recover_reliable_deliveries(
                session, limit=limit, scan_limit=scan_limit,
                cursors={key: cursors.get(key) for key in ("settle", "expire")},
            )
            cursors.update(sweep["cursors"])
            state.cursor_json = dict(cursors)
            session.commit()
        for key in ("settled", "expired", "blocked"):
            report[key] = list(sweep[key])

        abandoned, cursors["jobs_abandoned"] = self._job_page(
            lambda now: and_(
                AIDeliveryJob.state.in_(("queued", "running")),
                or_(AIDeliveryJob.lease_expires_at.is_(None), AIDeliveryJob.lease_expires_at <= now),
                rd.closed_or_lapsed_filter(AIDeliveryJob.operation_id, at=now),
            ), cursors.get("jobs_abandoned"), limit)
        for operation_id in abandoned:
            claim = self.claim(operation_id, executors=self._all_executors(operation_id))
            if claim is None:
                continue
            try:
                self._record_lost_call(claim)
                outcome = self._finish_if_decided(claim)
            except Exception as exc:  # one row never stops recovery of the others (S2); systemic errors do
                self._release_claim(claim)
                reason = rd._row_error(exc)
                if reason is None:
                    raise
                report["blocked"].append({"operation_id": operation_id, "reason": reason})
                continue
            if outcome is not _UNDECIDED and outcome is not None:
                report["jobs_closed"].append({"operation_id": operation_id, "outcome": outcome})
            else:
                self._release_claim(claim)
        # A settle pass can finish a persisted job whose Phase 12 row the sweep settled.
        for row in report["settled"]:
            with self._session() as session:
                job = _job(session, row["operation_id"])
            if job is not None and job.state == "persisted":
                self.settle_saved_response(row["operation_id"])
        with self._session() as session:
            state = session.get(AIDeliveryWorkerState, RECOVERY_STATE_KEY, with_for_update=True)
            state.cursor_json = dict(cursors)
            session.commit()
        report["cursors"] = cursors
        return report

    def _recovery_cursors(self):
        """The durable cursors, creating the state row once even when two workers start together (N1)."""
        with self._session() as session:
            try:
                with session.begin_nested():
                    session.add(AIDeliveryWorkerState(key=RECOVERY_STATE_KEY, cursor_json={}))
                    session.flush()
            except sa_exc.IntegrityError:
                pass
            session.commit()
            state = session.get(AIDeliveryWorkerState, RECOVERY_STATE_KEY)
            return dict(state.cursor_json or {})

    def _job_page(self, condition, cursor, limit):
        """Up to ``limit`` matching jobs from ``cursor`` by (created_at, operation_id), wrapping once.

        Returns the ids and the cursor for the next round (None after a full cycle), so
        jobs that keep failing never starve the ones behind them.
        """
        start = None if not cursor else (datetime.fromisoformat(cursor["created_at"]), cursor["operation_id"])
        key = (AIDeliveryJob.created_at, AIDeliveryJob.operation_id)
        found = []
        with self._session() as session:
            where = condition(_clock(session))
            for after, until in ([(start, None)] if start is None else [(start, None), (None, start)]):
                query = select(*key).where(where)
                if after is not None:
                    query = query.where(or_(key[0] > after[0], and_(key[0] == after[0], key[1] > after[1])))
                if until is not None:
                    query = query.where(or_(key[0] < until[0], and_(key[0] == until[0], key[1] <= until[1])))
                found += session.execute(query.order_by(*key).limit(limit - len(found))).all()
                if len(found) >= limit:
                    last = found[-1]
                    return [row[1] for row in found], {"created_at": _utc(last[0]).isoformat(),
                                                       "operation_id": last[1]}
        return [row[1] for row in found], None

    def _all_executors(self, operation_id):
        with self._session() as session:
            return (session.execute(select(AIDeliveryJob.executor).where(
                AIDeliveryJob.operation_id == operation_id)).scalar_one(),)

    def _release_claim(self, claim):
        with self._session() as session:
            session.execute(_job_update().where(
                AIDeliveryJob.operation_id == claim.operation_id, AIDeliveryJob.lease_token == claim.token,
            ).values(lease_token=None, lease_owner=None, lease_expires_at=None))
            session.commit()


_UNDECIDED = object()


def _set_persisted(session, operation_id):
    session.execute(_job_update().where(
        AIDeliveryJob.operation_id == operation_id,
        AIDeliveryJob.state.in_(("queued", "running")),
    ).values(state="persisted", persisted_at=_clock(session)))


def _finish(session, job, outcome, *, error_code=None):
    job.state, job.outcome, job.finished_at = "finished", outcome, _clock(session)
    job.lease_token = job.lease_owner = job.lease_expires_at = None
    job.inflight_call_json = None
    if error_code:
        job.error_code = error_code[:80]
    session.flush()


def _error_code(exc):
    if isinstance(exc, rd.RunawayLimitError):
        return f"runaway:{getattr(exc, 'limit', 'bound')}"[:80]
    if isinstance(exc, rd.ReservationLapsedError):
        return "reservation_lapsed"
    return f"executor_error:{type(exc).__name__}"[:80]


# ---------------------------------------------------------------------------
# In-process start (optional, low latency; the standalone worker is the guarantee)
# ---------------------------------------------------------------------------

def start_in_process(operation_id, *, worker=None):
    """Run ``run_job`` on a daemon thread of this process, with the Flask app context pushed.

    Same claim and lease as any worker, so it never becomes a second runner. The
    standalone worker remains the reliability path (recovery after a crash).
    """
    if worker is None:
        from flask import current_app
        worker = DeliveryWorker(app=current_app._get_current_object())
    thread = threading.Thread(target=worker.run_job, args=(operation_id,),
                              name=f"delivery-{operation_id[:8]}", daemon=True)
    thread.start()
    return thread
