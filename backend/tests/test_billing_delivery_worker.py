"""I3: the reliable-delivery worker (Phase 12 activation gate criteria 1, 3 and 5).

The provider is a fake executor: no paid AI call is made anywhere in this file.
PostgreSQL journeys run real worker threads (claim, heartbeat thread, persist,
settle, recovery) against the migrated schema in ``TEST_DATABASE_URL``.
"""

from concurrent.futures import ThreadPoolExecutor
import contextlib
from datetime import timedelta
import os
from pathlib import Path
import threading
import time
from unittest import mock
import uuid

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.orm import Session

from app import billing_delivery_worker as bdw
from app import billing_reliable_delivery as rd
from app import db as flask_db
from app.billing_ai_operations import AIBillingIsolationError, AIBillingIsolationLevelError, settle_delivered_operation
from app.models import AIOperation, CreditLedgerEntry, OrganizationMember
from app.models_billing_delivery import AIDeliveryJob, AIDeliveryStreamChunk
from app.models_billing_phase12 import AIAbsorbedUsage, AIBillingOperation, AIProviderCallUsage
from tests.test_billing_ai_operations import (
    CLAUDE,
    GEMINI,
    _migrated_engine,
    _pg_world,
    authorize,
    call,
    charged,
    migrated_session,
    sums,
    world,
)


BACKEND = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = str(BACKEND / "migrations")
REVISION = "d7e9b1c3a5f8"
PG = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="local disposable PostgreSQL is not configured")
FAMILIES = "identity,financial_events,credit_funding,ai_reservation"


# ---------------------------------------------------------------------------
# The fake provider (an executor, exactly as I4 will write one)
# ---------------------------------------------------------------------------

HOOKS = {}  # operation_id -> {"entered": Event, "release": Event}
RUNS = {}   # operation_id -> number of executor invocations


class SimulatedCrash(BaseException):
    """A worker process dying mid-call: nothing in the worker catches it."""


def _hook(operation_id):
    return HOOKS.setdefault(operation_id, {"entered": threading.Event(), "release": threading.Event()})


@bdw.executor("i3-fake-provider")
def fake_provider(ctx):
    """payload: {"attempts": ["fail" | "ok" | "block" | "crash" | "stream_until_cancel" | "none", ...]}"""
    RUNS[ctx.operation_id] = RUNS.get(ctx.operation_id, 0) + 1
    plan = list(ctx.payload["attempts"])
    if RUNS[ctx.operation_id] > 1 and ctx.payload.get("after_restart"):
        plan = list(ctx.payload["after_restart"])
    for step in plan:
        if step == "none":
            return bdw.NoBillableUsage()
        attempt = ctx.begin_attempt()
        model = CLAUDE if attempt == 1 else GEMINI
        ctx.check_call(attempt_number=attempt, call_index=0, provider=model[0], model=model[1],
                       max_input_tokens=1000, max_output_tokens=1000)
        started = ctx.now()
        if step == "crash":
            raise SimulatedCrash()
        if step in ("block", "block_then_ok"):
            hook = _hook(ctx.operation_id)
            hook["entered"].set()
            assert hook["release"].wait(30)
        if step == "fail":
            ctx.record_call(attempt_number=attempt, call_index=0, provider=model[0], model=model[1],
                            outcome="failed", usage_label="reported", input_tokens=100, output_tokens=0,
                            requested_at=started, finished_at=ctx.now(), error_category="provider_error",
                            provider_request_id=f"fake-{attempt}", duration_ms=5, status_code=500)
            continue
        if step == "stream_until_cancel":
            _hook(ctx.operation_id)["entered"].set()
            while not ctx.should_stop():
                ctx.emit(attempt, "partial ")
                ctx.flush()
                time.sleep(0.05)
            ctx.record_call(attempt_number=attempt, call_index=0, provider=model[0], model=model[1],
                            outcome="cancelled", usage_label="reported", input_tokens=1000, output_tokens=200,
                            requested_at=started, finished_at=ctx.now(), error_category="cancelled",
                            provider_request_id=f"fake-{attempt}")
            raise bdw.DeliveryFailed("cancelled")
        for text in ("Hel", "lo"):
            ctx.emit(attempt, text)
        ctx.record_call(attempt_number=attempt, call_index=0, provider=model[0], model=model[1],
                        outcome="succeeded", usage_label="reported", input_tokens=1000, output_tokens=1000,
                        requested_at=started, finished_at=ctx.now(), provider_request_id=f"fake-{attempt}",
                        duration_ms=10, status_code=200)
        return bdw.DeliveryResult(delivered_attempt_number=attempt,
                                  response={"text": "Hello", "attempt": attempt})
    raise bdw.DeliveryFailed("provider_failed")


def _factory(engine):
    if engine.dialect.name == "postgresql":
        engine = engine.execution_options(isolation_level="READ COMMITTED")
    return lambda: Session(engine, expire_on_commit=False)


def _submit(session, ns, *, attempts=("ok",), after_restart=None, heartbeat=60, job_lease=90, timeout=30,
            max_claims=None, step=None, user=None):
    authorization = authorize(session, ns, user=user, step=step or f"step-{uuid.uuid4().hex[:8]}")
    payload = {"attempts": list(attempts)}
    if after_restart:
        payload["after_restart"] = list(after_restart)
    bdw.submit_delivery(
        session, operation_id=authorization.operation_id, organization_id=ns.org,
        actor_user_id=user or ns.owner, executor="i3-fake-provider", payload=payload,
        provider_timeout_seconds=timeout, heartbeat_interval_seconds=heartbeat, job_lease_seconds=job_lease,
        max_claims=max_claims,
    )
    return authorization.operation_id


def _job(session, operation_id):
    session.expire_all()
    return session.get(AIDeliveryJob, operation_id)


def _billing(session, operation_id):
    session.expire_all()
    return session.get(AIBillingOperation, operation_id)


def _expire_job_lease(session, operation_id):
    session.execute(sa.update(AIDeliveryJob).where(AIDeliveryJob.operation_id == operation_id).values(
        lease_expires_at=rd._clock(session) - timedelta(seconds=1)).execution_options(synchronize_session=False))
    session.commit()


def _mismatched_job(session, ns, actor_user_id):
    """Write a job around the command: its actor is not the operation's Phase 12 actor."""
    operation_id = authorize(session, ns, step=f"step-{uuid.uuid4().hex[:8]}").operation_id
    session.add(AIDeliveryJob(operation_id=operation_id, organization_id=ns.org, actor_user_id=actor_user_id,
                              executor="i3-fake-provider", payload_json={}, payload_sha256="0" * 64,
                              max_claims=3, provider_timeout_seconds=30, heartbeat_interval_seconds=15,
                              job_lease_seconds=45))
    session.flush()


def _reconciled(session, operation_id):
    return rd.provider_cost_reconciliation(session, operation_id=operation_id)["reconciled"]


# ---------------------------------------------------------------------------
# Static guards: M2 caller guard, inactive module, migration chain
# ---------------------------------------------------------------------------

def _sources():
    for root in ("app", "scripts"):
        for path in (BACKEND / root).rglob("*.py"):
            yield path


def test_m2_only_the_phase17_boundary_calls_phase12_settlement():
    """The AI runtime settles only through ``settle_persisted_response`` (M2)."""
    callers = sorted(str(path.relative_to(BACKEND)) for path in _sources()
                     if "settle_delivered_operation" in path.read_text())
    assert callers == ["app/billing_ai_operations.py", "app/billing_reliable_delivery.py"]


def test_the_worker_has_no_live_caller():
    """Inactive: only the operator CLI names the worker. I4's family-gated runtime
    (``app/billing_runtime_ai.py``, family ``ai_reservation``) is the one planned addition."""
    callers = sorted(str(path.relative_to(BACKEND)) for path in _sources()
                     if str(path.relative_to(BACKEND)) not in {"app/billing_delivery_worker.py",
                                                               "app/models_billing_delivery.py"}
                     and ("billing_delivery_worker" in path.read_text() or "models_billing_delivery" in path.read_text()))
    assert callers == ["scripts/billing_delivery_worker.py"]


def test_worker_migration_follows_i1_and_is_the_single_head():
    script = ScriptDirectory(MIGRATIONS_DIR)
    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == "e7b9d1f3a5c6"  # I3 follows I2 at integration


# ---------------------------------------------------------------------------
# SQLite: lifecycle logic in one process
# ---------------------------------------------------------------------------

@pytest.fixture
def sqlite_worker(db):
    worker = bdw.DeliveryWorker(_factory(db.engine), owner="sqlite-worker")
    yield worker


def test_submit_fails_closed_on_timing_and_is_idempotent(db):
    session = db.session
    ns = world(session)
    authorization = authorize(session, ns)
    with pytest.raises(bdw.DeliveryTimingError, match="must exceed"):
        bdw.submit_delivery(session, operation_id=authorization.operation_id, organization_id=ns.org,
                            actor_user_id=ns.owner, executor="i3-fake-provider", payload={"attempts": ["ok"]},
                            provider_timeout_seconds=100, heartbeat_interval_seconds=30)
    with pytest.raises(bdw.DeliveryTimingError, match="job lease"):
        bdw.submit_delivery(session, operation_id=authorization.operation_id, organization_id=ns.org,
                            actor_user_id=ns.owner, executor="i3-fake-provider", payload={"attempts": ["ok"]},
                            provider_timeout_seconds=30, heartbeat_interval_seconds=30, job_lease_seconds=200)
    assert session.get(AIDeliveryJob, authorization.operation_id) is None
    first = bdw.submit_delivery(session, operation_id=authorization.operation_id, organization_id=ns.org,
                                actor_user_id=ns.owner, executor="i3-fake-provider",
                                payload={"attempts": ["ok"]}, provider_timeout_seconds=30,
                                heartbeat_interval_seconds=15)
    again = bdw.submit_delivery(session, operation_id=authorization.operation_id, organization_id=ns.org,
                                actor_user_id=ns.owner, executor="i3-fake-provider",
                                payload={"attempts": ["ok"]}, provider_timeout_seconds=30,
                                heartbeat_interval_seconds=15)
    assert first is again and first.job_lease_seconds == 45
    with pytest.raises(bdw.DeliveryConflictError):
        bdw.submit_delivery(session, operation_id=authorization.operation_id, organization_id=ns.org,
                            actor_user_id=ns.owner, executor="i3-fake-provider",
                            payload={"attempts": ["fail"]}, provider_timeout_seconds=30)
    with pytest.raises(AIBillingIsolationError):
        bdw.submit_delivery(session, operation_id=authorize(session, ns).operation_id, organization_id=ns.org,
                            actor_user_id=world(session).owner, executor="i3-fake-provider",
                            payload={}, provider_timeout_seconds=30)
    with pytest.raises(bdw.DeliveryError, match="worker owns"):
        bdw.release_unsubmitted_operation(session, operation_id=authorization.operation_id,
                                          organization_id=ns.org, actor_user_id=ns.owner)


def test_a_timing_refusal_releases_the_unsubmitted_reservation(db):
    session = db.session
    ns = world(session)
    authorization = authorize(session, ns)
    result = bdw.release_unsubmitted_operation(session, operation_id=authorization.operation_id,
                                               organization_id=ns.org, actor_user_id=ns.owner)
    assert result.delivery_status == "no_billable_usage"
    assert sums(session, ns.account) == (500, 0)


def test_worker_persists_then_settles_once_and_the_route_streams_saved_output(db, sqlite_worker):
    session = db.session
    ns = world(session)
    operation_id = _submit(session, ns)
    session.commit()

    assert sqlite_worker.run_job(operation_id) == "delivered"
    session.expire_all()
    view = bdw.read_delivery(session, operation_id=operation_id, organization_id=ns.org, actor_user_id=ns.owner)
    assert view.finished and view.persisted and view.response == {"text": "Hello", "attempt": 1}
    assert "".join(chunk.content for chunk in view.chunks) == "Hello"
    later = bdw.read_delivery(session, operation_id=operation_id, organization_id=ns.org, actor_user_id=ns.owner,
                              after=view.cursor)
    assert later.chunks == []
    assert charged(session, operation_id) == 18
    assert sums(session, ns.account) == (500 - 18, 0)
    assert _reconciled(session, operation_id)
    assert _job(session, operation_id).outcome == "delivered"
    # Replays: the job is finished, so nothing claims or charges it again.
    assert sqlite_worker.run_job(operation_id) is None
    assert sqlite_worker.settle_saved_response(operation_id) == "delivered"
    sqlite_worker.recover()
    assert charged(session, operation_id) == 18


def test_fallback_charges_only_the_delivering_attempt(db, sqlite_worker):
    session = db.session
    ns = world(session)
    operation_id = _submit(session, ns, attempts=("fail", "ok"))
    session.commit()
    assert sqlite_worker.run_job(operation_id) == "delivered"
    session.expire_all()
    billing = _billing(session, operation_id)
    assert billing.delivered_attempt_number == 2
    assert charged(session, operation_id) == 6  # Gemini: 1000*1/1e6 + 1000*5/1e6 USD -> 6 credits
    assert len(session.execute(sa.select(AIAbsorbedUsage).where(
        AIAbsorbedUsage.operation_id == operation_id)).scalars().all()) == 1
    assert _reconciled(session, operation_id)


def test_provider_failure_closes_undelivered_and_charges_nothing(db, sqlite_worker):
    session = db.session
    ns = world(session)
    operation_id = _submit(session, ns, attempts=("fail",))
    session.commit()
    assert sqlite_worker.run_job(operation_id) == "undelivered"
    session.expire_all()
    assert charged(session, operation_id) == 0 and sums(session, ns.account) == (500, 0)
    assert _job(session, operation_id).error_code == "provider_failed"
    assert _reconciled(session, operation_id)


def test_no_billable_usage_releases_the_exact_reservation(db, sqlite_worker):
    session = db.session
    ns = world(session)
    operation_id = _submit(session, ns, attempts=("none",))
    session.commit()
    assert sqlite_worker.run_job(operation_id) == "no_billable_usage"
    session.expire_all()
    assert sums(session, ns.account) == (500, 0)


def test_cancel_before_any_call_releases_without_usage(db, sqlite_worker):
    session = db.session
    ns = world(session)
    operation_id = _submit(session, ns)
    session.commit()
    assert bdw.request_cancellation(session, operation_id=operation_id, organization_id=ns.org,
                                    actor_user_id=ns.owner)
    assert not bdw.request_cancellation(session, operation_id=operation_id, organization_id=ns.org,
                                        actor_user_id=ns.owner)
    session.commit()
    assert sqlite_worker.run_job(operation_id) == "no_billable_usage"
    session.expire_all()
    assert RUNS.get(operation_id) is None  # the provider was never called
    assert sums(session, ns.account) == (500, 0)


def test_restart_before_persistence_records_the_lost_call_and_reruns(db, sqlite_worker):
    session = db.session
    ns = world(session)
    operation_id = _submit(session, ns, attempts=("crash",), after_restart=("ok",))
    session.commit()
    with pytest.raises(SimulatedCrash):
        sqlite_worker.run_job(operation_id)
    job = _job(session, operation_id)
    assert job.state == "running" and job.inflight_call_json["attempt_number"] == 1
    assert sqlite_worker.run_job(operation_id) is None  # its job lease is still live
    _expire_job_lease(session, operation_id)

    restarted = bdw.DeliveryWorker(_factory(db.engine), owner="restarted")
    assert restarted.run_once() == [(operation_id, "delivered")]
    session.expire_all()
    billing = _billing(session, operation_id)
    assert billing.delivered_attempt_number == 2 and charged(session, operation_id) == 6
    lost = session.execute(sa.select(AIProviderCallUsage).where(
        AIProviderCallUsage.operation_id == operation_id, AIProviderCallUsage.attempt_number == 1)).scalar_one()
    assert (lost.outcome, lost.usage_label, lost.error_category) == ("failed", "unknown", "worker_lost")
    assert _reconciled(session, operation_id)
    assert _job(session, operation_id).claims == 2


def test_claims_are_bounded(db, sqlite_worker):
    session = db.session
    ns = world(session)
    operation_id = _submit(session, ns, attempts=("crash",), max_claims=1)
    session.commit()
    with pytest.raises(SimulatedCrash):
        sqlite_worker.run_job(operation_id)
    _expire_job_lease(session, operation_id)
    assert sqlite_worker.run_job(operation_id) == "undelivered"
    session.expire_all()
    assert _job(session, operation_id).error_code == "claims_exhausted"
    assert sums(session, ns.account) == (500, 0) and RUNS[operation_id] == 1
    assert _reconciled(session, operation_id)


def test_restart_after_persistence_is_settled_by_recovery(db, sqlite_worker, monkeypatch):
    session = db.session
    ns = world(session)
    operation_id = _submit(session, ns)
    session.commit()
    real = rd.settle_persisted_response
    monkeypatch.setattr(rd, "settle_persisted_response", mock.Mock(side_effect=RuntimeError("worker died")))
    assert sqlite_worker.run_job(operation_id) is None
    session.expire_all()
    assert _job(session, operation_id).state == "persisted" and charged(session, operation_id) == 0
    assert bdw.read_delivery(session, operation_id=operation_id, organization_id=ns.org,
                             actor_user_id=ns.owner).response == {"text": "Hello", "attempt": 1}
    monkeypatch.setattr(rd, "settle_persisted_response", real)
    report = sqlite_worker.recover()
    assert report["jobs_settled"] == [{"operation_id": operation_id, "outcome": "delivered"}]
    again = sqlite_worker.recover()
    assert again["jobs_settled"] == [] and again["settled"] == []
    session.expire_all()
    assert charged(session, operation_id) == 18


def test_the_route_read_enforces_durable_identity_and_active_membership(db, sqlite_worker):
    session = db.session
    ns = world(session, members=2)
    operation_id = _submit(session, ns)
    session.commit()
    sqlite_worker.run_job(operation_id)
    other = world(session)
    teammate = session.execute(sa.select(OrganizationMember).where(
        OrganizationMember.organization_id == ns.org, OrganizationMember.user_id != ns.owner)).scalars().first()
    for org, actor in ((other.org, ns.owner), (ns.org, teammate.user_id), (ns.org, other.owner)):
        with pytest.raises(AIBillingIsolationError):
            bdw.read_delivery(session, operation_id=operation_id, organization_id=org, actor_user_id=actor)
        with pytest.raises(AIBillingIsolationError):
            bdw.request_cancellation(session, operation_id=operation_id, organization_id=org, actor_user_id=actor)
    owner = session.execute(sa.select(OrganizationMember).where(
        OrganizationMember.organization_id == ns.org, OrganizationMember.user_id == ns.owner)).scalar_one()
    owner.status = "removed"
    session.flush()
    with pytest.raises(AIBillingIsolationError, match="no longer active"):
        bdw.read_delivery(session, operation_id=operation_id, organization_id=ns.org, actor_user_id=ns.owner)


def test_a_newer_attempt_restarts_the_stream(db):
    session = db.session
    ns = world(session)
    operation_id = _submit(session, ns)
    for attempt, seq, text in ((1, 1, "first"), (1, 2, " try"), (2, 1, "second")):
        session.add(AIDeliveryStreamChunk(operation_id=operation_id, attempt_number=attempt, seq=seq, content=text))
    session.flush()
    read = bdw.read_delivery(session, operation_id=operation_id, organization_id=ns.org, actor_user_id=ns.owner,
                             after=(1, 2))
    assert [(chunk.content, chunk.restart) for chunk in read.chunks] == [("second", True)]
    fresh = bdw.read_delivery(session, operation_id=operation_id, organization_id=ns.org, actor_user_id=ns.owner)
    assert [(chunk.content, chunk.restart) for chunk in fresh.chunks] == [("second", False)]


def test_recovery_closes_an_abandoned_job_after_its_reservation_lapsed(db, monkeypatch):
    session = db.session
    ns = world(session)
    operation_id = _submit(session, ns)
    session.commit()
    billing = _billing(session, operation_id)
    after_lapse = rd._clock(session) + timedelta(seconds=int(billing.lease_seconds) + 5)
    monkeypatch.setattr("app.billing_ai_operations._clock", lambda _session: after_lapse)
    monkeypatch.setattr("app.billing_reliable_delivery._clock", lambda _session: after_lapse)
    # A recovery-only worker: no executor for this job is registered in its process.
    with mock.patch.dict(bdw._EXECUTORS, {}, clear=True):
        report = bdw.DeliveryWorker(_factory(db.engine), owner="recovery-only").recover()
    assert [row["operation_id"] for row in report["expired"]] == [operation_id]
    assert report["jobs_closed"] == [{"operation_id": operation_id, "outcome": "undelivered"}]
    session.expire_all()
    assert _job(session, operation_id).outcome == "undelivered" and sums(session, ns.account) == (500, 0)


# ---------------------------------------------------------------------------
# The bounded sweep: B2 starvation, O1 and O2
# ---------------------------------------------------------------------------

def _saved(session, ns, *, step):
    authorization = authorize(session, ns, step=step)
    call(session, authorization.operation_id)
    usage = session.execute(sa.select(AIProviderCallUsage).where(
        AIProviderCallUsage.operation_id == authorization.operation_id)).scalar_one()
    rd.append_provider_attempt(session, operation_id=authorization.operation_id, organization_id=ns.org,
                               actor_user_id=ns.owner, provider_call_usage_id=usage.id)
    rd.persist_successful_response(session, operation_id=authorization.operation_id, organization_id=ns.org,
                                   actor_user_id=ns.owner, delivered_attempt_number=1, response_json={"m": step})
    return authorization.operation_id


def test_permanently_blocked_rows_never_starve_a_saved_response(db):
    session = db.session
    ns = world(session, credits=100_000, member={"max_concurrent": 50}, organization={"max_concurrent": 50})
    poisoned = [_saved(session, ns, step=f"poisoned-{index}") for index in range(5)]
    for operation_id in poisoned:
        session.get(AIOperation, operation_id).user_id = None  # identity disagrees with the binding
    session.flush()
    saved = _saved(session, ns, step="saved-last")
    # Make the saved response sort after every poisoned row.
    session.get(AIBillingOperation, saved).expires_at += timedelta(seconds=1)
    session.flush()

    cursors, settled, sweeps = None, [], 0
    while not settled:
        sweeps += 1
        assert sweeps <= 6, "the saved response was starved"
        report = rd.recover_reliable_deliveries(session, limit=2, scan_limit=2, cursors=cursors)
        assert len(report["blocked"]) + len(report["settled"]) <= 2
        cursors, settled = report["cursors"], report["settled"]
    assert [row["operation_id"] for row in settled] == [saved]
    assert charged(session, saved) == 18
    for operation_id in poisoned:
        assert charged(session, operation_id) == 0  # fail closed: blocked, never guessed


def test_scanning_is_bounded_and_resumes_from_its_cursor(db):
    session = db.session
    ns = world(session, credits=100_000, member={"max_concurrent": 50}, organization={"max_concurrent": 50})
    for index in range(4):  # legacy results that are not reliable-delivery envelopes
        operation_id = authorize(session, ns, step=f"legacy-{index}").operation_id
        session.get(AIOperation, operation_id).result_json = {"legacy": True}
    session.flush()
    saved = _saved(session, ns, step="saved")
    session.get(AIBillingOperation, saved).expires_at += timedelta(seconds=1)
    session.flush()
    first = rd.recover_reliable_deliveries(session, limit=2, scan_limit=3)
    assert first["settled"] == [] and first["cursors"]["settle"] is not None
    second = rd.recover_reliable_deliveries(session, limit=2, scan_limit=3, cursors=first["cursors"])
    assert [row["operation_id"] for row in second["settled"]] == [saved]


def test_o2_a_row_level_database_refusal_is_isolated(db, monkeypatch):
    session = db.session
    ns = world(session, member={"max_concurrent": 20}, organization={"max_concurrent": 20})
    refused, good = _saved(session, ns, step="refused"), _saved(session, ns, step="good")
    real = rd.settle_persisted_response

    def settle(session_, *, operation_id, **kwargs):
        if operation_id == refused:
            raise sa.exc.IntegrityError("UPDATE", {}, Exception("guard"))
        return real(session_, operation_id=operation_id, **kwargs)

    monkeypatch.setattr(rd, "settle_persisted_response", settle)
    report = rd.recover_reliable_deliveries(session)
    assert [row["operation_id"] for row in report["blocked"]] == [refused]
    assert [row["operation_id"] for row in report["settled"]] == [good]

    def lost(*_args, **_kwargs):
        raise sa.exc.OperationalError("SELECT", {}, Exception("server closed the connection"))

    monkeypatch.setattr(rd, "settle_persisted_response", lost)
    with pytest.raises(sa.exc.OperationalError):
        rd.recover_reliable_deliveries(session)


def test_o1_a_systemic_billing_error_stops_the_sweep(db, monkeypatch):
    session = db.session
    ns = world(session)
    _saved(session, ns, step="saved")

    def systemic(*_args, **_kwargs):
        raise AIBillingIsolationLevelError("AI billing commands must run in a READ COMMITTED transaction")

    monkeypatch.setattr(rd, "settle_persisted_response", systemic)
    with pytest.raises(rd.RecoverySystemicError):
        rd.recover_reliable_deliveries(session)


# ---------------------------------------------------------------------------
# The CLI
# ---------------------------------------------------------------------------

def _cli():
    import importlib.util
    spec = importlib.util.spec_from_file_location("billing_delivery_worker_cli",
                                                  BACKEND / "scripts" / "billing_delivery_worker.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_refuses_production_and_a_disabled_family(app, monkeypatch, capsys):
    cli = _cli()
    monkeypatch.setenv("BILLING_MODERN_FAMILIES", FAMILIES)
    monkeypatch.setenv("APP_ENV", "production")
    assert cli.run(["recover"], app=app) == 2
    assert "production runtime" in capsys.readouterr().out
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("BILLING_MODERN_FAMILIES", "identity,financial_events,credit_funding")
    assert cli.run(["recover"], app=app) == 2
    assert "not enabled" in capsys.readouterr().out


def test_cli_runs_jobs_and_recovery_and_alerts_on_blocked_rows(db, app, monkeypatch, capsys):
    cli = _cli()
    monkeypatch.setenv("BILLING_MODERN_FAMILIES", FAMILIES)
    session = db.session
    ns = world(session)
    operation_id = _submit(session, ns)
    session.commit()
    factory = _factory(db.engine)
    # The fake provider is already registered in this process; any importable module will do.
    assert cli.run(["run", "--once", "--executor-module", "app.billing_delivery_worker"],
                   app=app, session_factory=factory) == 0
    session.expire_all()
    assert _job(session, operation_id).outcome == "delivered" and charged(session, operation_id) == 18

    poisoned = _saved(session, world(session), step="poisoned")
    session.get(AIOperation, poisoned).user_id = None
    session.commit()
    assert cli.run(["recover"], app=app, session_factory=factory) == 3
    assert poisoned in capsys.readouterr().out


# ---------------------------------------------------------------------------
# SQLite migration: guards and downgrade
# ---------------------------------------------------------------------------

def test_sqlite_migration_guards_jobs_chunks_and_persist_before_settle(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'i3.sqlite'}")
    mine = {"ai_delivery_jobs", "ai_delivery_stream_chunks", "ai_delivery_worker_state"}
    flask_db.metadata.create_all(engine, tables=[t for t in flask_db.metadata.sorted_tables if t.name not in mine])
    module = ScriptDirectory(MIGRATIONS_DIR).get_revision(REVISION).module
    with engine.begin() as connection:
        with mock.patch.object(module, "op", Operations(MigrationContext.configure(connection))):
            module.upgrade()
    try:
        with Session(engine) as session:
            ns = world(session)
            from tests.test_billing_enterprise_contracts import _user
            stranger = _user(session, "stranger")
            with pytest.raises(sa.exc.IntegrityError, match="Phase 12 identity"):
                with session.begin_nested():
                    _mismatched_job(session, ns, stranger)
            operation_id = _submit(session, ns)
            session.commit()
            for statement, message in (
                (sa.update(AIDeliveryJob).values(executor="other"), "immutable"),
                (sa.update(AIDeliveryJob).values(payload_json={"attempts": []}), "immutable"),
                (sa.delete(AIDeliveryJob), "never deleted"),
            ):
                with pytest.raises(sa.exc.IntegrityError, match=message):
                    with session.begin_nested():
                        session.execute(statement.where(AIDeliveryJob.operation_id == operation_id))
            session.execute(sa.update(AIDeliveryJob).where(AIDeliveryJob.operation_id == operation_id).values(
                lease_owner="ok"))  # operational columns stay writable
            session.add(AIDeliveryStreamChunk(operation_id=operation_id, attempt_number=1, seq=1, content="x"))
            session.commit()
            with pytest.raises(sa.exc.IntegrityError, match="append-only"):
                with session.begin_nested():
                    session.execute(sa.update(AIDeliveryStreamChunk).values(content="y"))
            # M2: a worker-managed operation cannot be settled delivered without its saved response.
            call(session, operation_id)
            with pytest.raises(sa.exc.IntegrityError, match="persisted"):
                with session.begin_nested():
                    settle_delivered_operation(session, operation_id=operation_id, delivered_attempt_number=1)
            # Without a job, Phase 12 behaves exactly as before.
            plain = authorize(session, ns, step="no-job")
            call(session, plain.operation_id)
            assert settle_delivered_operation(session, operation_id=plain.operation_id,
                                              delivered_attempt_number=1).charged_credits == 18
            session.commit()
        with engine.begin() as connection:
            with mock.patch.object(module, "op", Operations(MigrationContext.configure(connection))):
                with pytest.raises(module.DeliveryJobsNotEmptyError):
                    module.downgrade()
    finally:
        engine.dispose()


def test_sqlite_migration_downgrades_cleanly_when_empty(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'i3-empty.sqlite'}")
    mine = {"ai_delivery_jobs", "ai_delivery_stream_chunks", "ai_delivery_worker_state"}
    flask_db.metadata.create_all(engine, tables=[t for t in flask_db.metadata.sorted_tables if t.name not in mine])
    module = ScriptDirectory(MIGRATIONS_DIR).get_revision(REVISION).module
    try:
        with engine.begin() as connection:
            with mock.patch.object(module, "op", Operations(MigrationContext.configure(connection))):
                module.upgrade()
                module.downgrade()
        names = set(sa.inspect(engine).get_table_names())
        assert not names & mine
        with engine.connect() as connection:
            assert connection.execute(sa.text(
                "SELECT count(*) FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'trg_i3_%'")).scalar_one() == 0
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# PostgreSQL 18: real-worker journeys (criteria 1, 3, 5)
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def pg():
    engine = _migrated_engine()
    with engine.connect() as connection:
        revision = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
    if revision != REVISION:
        engine.dispose()
        pytest.fail(f"I3 journeys require Alembic head {REVISION}; found {revision!r}")
    try:
        yield engine
    finally:
        engine.dispose()


def _pg_submit(engine, ns, **kwargs):
    with migrated_session(engine) as session:
        operation_id = _submit(session, ns, **kwargs)
        session.commit()
    return operation_id


def _wait(predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


@PG
def test_postgres_a_disconnect_never_stops_delivery_and_the_heartbeat_renews_during_the_call():
    with pg() as engine:
        ns = _pg_world(engine)
        operation_id = _pg_submit(engine, ns, attempts=("block_then_ok",), heartbeat=1, job_lease=3, timeout=5)
        worker = bdw.DeliveryWorker(_factory(engine), owner="pg-worker")
        thread = threading.Thread(target=worker.run_job, args=(operation_id,))
        thread.start()
        hook = _hook(operation_id)
        assert hook["entered"].wait(10)
        with migrated_session(engine) as session:
            before = (_billing(session, operation_id).expires_at, _job(session, operation_id).lease_expires_at)
            # The browser streams once, then disconnects: the route simply stops reading.
            view = bdw.read_delivery(session, operation_id=operation_id, organization_id=ns.org,
                                     actor_user_id=ns.owner)
            assert view.state == "running" and view.response is None
        time.sleep(2.5)  # the provider call is still blocked; only the heartbeat thread runs
        with migrated_session(engine) as session:
            after = (_billing(session, operation_id).expires_at, _job(session, operation_id).lease_expires_at)
        assert after[0] > before[0] and after[1] > before[1]
        hook["release"].set()
        thread.join(20)
        with migrated_session(engine) as session:
            view = bdw.read_delivery(session, operation_id=operation_id, organization_id=ns.org,
                                     actor_user_id=ns.owner)
            assert view.finished and view.response == {"text": "Hello", "attempt": 1}
            assert charged(session, operation_id) == 18 and _reconciled(session, operation_id)


@PG
def test_postgres_concurrent_workers_run_each_job_exactly_once():
    with pg() as engine:
        ns = _pg_world(engine, credits=5000, member={"max_concurrent": 20}, organization={"max_concurrent": 20})
        operations = [_pg_submit(engine, ns) for _ in range(6)]
        barrier = threading.Barrier(4)

        def run(index):
            worker = bdw.DeliveryWorker(_factory(engine), owner=f"pg-concurrent-{index}")
            barrier.wait()
            done = []
            while True:
                outcomes = worker.run_once()
                if not outcomes:
                    return done
                done.extend(outcomes)

        with ThreadPoolExecutor(4) as pool:
            results = [row for rows in pool.map(run, range(4)) for row in rows]
        assert sorted(operation_id for operation_id, _ in results) == sorted(operations)
        assert {outcome for _, outcome in results} == {"delivered"}
        with migrated_session(engine) as session:
            for operation_id in operations:
                assert RUNS[operation_id] == 1 and charged(session, operation_id) == 18
                assert _job(session, operation_id).claims == 1
            assert sums(session, ns.account) == (5000 - 6 * 18, 0)


@PG
def test_postgres_restart_lost_lease_race_and_late_original_worker_charge_once(monkeypatch):
    with pg() as engine:
        ns = _pg_world(engine)
        operation_id = _pg_submit(engine, ns, attempts=("block_then_ok",), after_restart=("ok",),
                                  heartbeat=1, job_lease=3, timeout=5)
        # Worker A stalls inside the provider call and its heartbeat stops (a frozen process).
        monkeypatch.setattr(bdw._Heartbeat, "run", lambda self: None)
        stalled = bdw.DeliveryWorker(_factory(engine), owner="pg-stalled")
        thread = threading.Thread(target=stalled.run_job, args=(operation_id,))
        thread.start()
        hook = _hook(operation_id)
        assert hook["entered"].wait(10)
        with migrated_session(engine) as session:
            _expire_job_lease(session, operation_id)
        monkeypatch.undo()
        # Worker B reclaims, records A's call as lost, runs a new attempt and delivers.
        replacement = bdw.DeliveryWorker(_factory(engine), owner="pg-replacement")
        assert replacement.run_job(operation_id) == "delivered"
        hook["release"].set()  # A's provider finally answers
        thread.join(20)
        with migrated_session(engine) as session:
            billing = _billing(session, operation_id)
            assert billing.delivered_attempt_number == 2
            assert charged(session, operation_id) == 6 and _reconciled(session, operation_id)
            assert _job(session, operation_id).outcome == "delivered"
            assert sums(session, ns.account) == (500 - 6, 0)
            calls = session.execute(sa.select(AIProviderCallUsage).where(
                AIProviderCallUsage.operation_id == operation_id)).scalars().all()
            assert sorted((c.attempt_number, c.error_category) for c in calls) == [(1, "worker_lost"), (2, None)]


@PG
def test_postgres_a_crashed_worker_is_recovered_by_another_process():
    with pg() as engine:
        ns = _pg_world(engine)
        operation_id = _pg_submit(engine, ns, attempts=("crash",), after_restart=("ok",), heartbeat=1,
                                  job_lease=3, timeout=5)
        with pytest.raises(SimulatedCrash):
            bdw.DeliveryWorker(_factory(engine), owner="pg-crashing").run_job(operation_id)
        restarted = bdw.DeliveryWorker(_factory(engine), owner="pg-restarted")
        assert restarted.run_once() == []  # the dead worker's job lease has not lapsed yet
        assert _wait(lambda: restarted.run_once() == [(operation_id, "delivered")], timeout=10)
        with migrated_session(engine) as session:
            assert charged(session, operation_id) == 6 and _reconciled(session, operation_id)


@PG
def test_postgres_cancellation_during_streaming_is_undelivered_and_never_charged():
    with pg() as engine:
        ns = _pg_world(engine)
        operation_id = _pg_submit(engine, ns, attempts=("stream_until_cancel",), heartbeat=1, job_lease=3,
                                  timeout=5)
        worker = bdw.DeliveryWorker(_factory(engine), owner="pg-cancel")
        thread = threading.Thread(target=worker.run_job, args=(operation_id,))
        thread.start()
        assert _hook(operation_id)["entered"].wait(10)
        with migrated_session(engine) as session:
            assert _wait(lambda: bdw.read_delivery(session, operation_id=operation_id, organization_id=ns.org,
                                                   actor_user_id=ns.owner).chunks)
            assert bdw.request_cancellation(session, operation_id=operation_id, organization_id=ns.org,
                                            actor_user_id=ns.owner)
            session.commit()
        thread.join(20)
        with migrated_session(engine) as session:
            job = _job(session, operation_id)
            assert (job.outcome, job.error_code) == ("undelivered", "cancelled")
            assert charged(session, operation_id) == 0 and sums(session, ns.account) == (500, 0)
            assert _reconciled(session, operation_id)


@PG
def test_postgres_a_late_response_after_the_lease_lapsed_is_delivered_never_charged():
    with pg() as engine:
        ns = _pg_world(engine, runaway={"reservation_lease_seconds": 3, "max_operation_seconds": 1})
        operation_id = _pg_submit(engine, ns, attempts=("block_then_ok",), heartbeat=1, job_lease=2, timeout=1)
        worker = bdw.DeliveryWorker(_factory(engine), owner="pg-late")
        thread = threading.Thread(target=worker.run_job, args=(operation_id,))
        thread.start()
        hook = _hook(operation_id)
        assert hook["entered"].wait(10)
        sweeper = bdw.DeliveryWorker(_factory(engine), owner="pg-sweeper")

        def lapsed():
            with migrated_session(engine) as session:
                return _billing(session, operation_id).state == "expired" or bool(
                    sweeper.recover()["expired"])
        assert _wait(lapsed, timeout=15)  # renewal is capped at the deadline plus one lease
        hook["release"].set()
        thread.join(20)
        with migrated_session(engine) as session:
            billing = _billing(session, operation_id)
            assert (billing.state, billing.delivery_status) == ("expired", "delivered")
            assert charged(session, operation_id) == 0 and sums(session, ns.account) == (500, 0)
            assert bdw.read_delivery(session, operation_id=operation_id, organization_id=ns.org,
                                     actor_user_id=ns.owner).response == {"text": "Hello", "attempt": 1}
            assert _job(session, operation_id).outcome == "delivered" and _reconciled(session, operation_id)


@PG
def test_postgres_recovery_retries_settlement_and_concurrent_sweeps_charge_once(monkeypatch):
    with pg() as engine:
        ns = _pg_world(engine, credits=5000, member={"max_concurrent": 20}, organization={"max_concurrent": 20})
        operations = [_pg_submit(engine, ns) for _ in range(4)]
        monkeypatch.setattr(bdw.DeliveryWorker, "settle_saved_response", lambda self, operation_id: None)  # dies after persisting
        for operation_id in operations:
            bdw.DeliveryWorker(_factory(engine)).run_job(operation_id)
        monkeypatch.undo()
        barrier = threading.Barrier(3)

        def sweep(index):
            worker = bdw.DeliveryWorker(_factory(engine), owner=f"pg-sweep-{index}")
            barrier.wait()
            return worker.recover()

        with ThreadPoolExecutor(3) as pool:
            reports = list(pool.map(sweep, range(3)))
        assert all(report["blocked"] == [] for report in reports)
        with migrated_session(engine) as session:
            for operation_id in operations:
                assert charged(session, operation_id) == 18 and _job(session, operation_id).outcome == "delivered"
            assert sums(session, ns.account) == (5000 - 4 * 18, 0)
        assert bdw.DeliveryWorker(_factory(engine)).recover()["jobs_settled"] == []


@PG
def test_postgres_o1_the_wrong_isolation_level_stops_recovery():
    with pg() as engine:
        worker = bdw.DeliveryWorker(lambda: Session(engine.execution_options(isolation_level="REPEATABLE READ")))
        with pytest.raises(AIBillingIsolationLevelError):
            worker.recover()


@PG
def test_postgres_migrated_guards_protect_jobs_chunks_and_persist_before_settle():
    with pg() as engine:
        ns = _pg_world(engine)
        with migrated_session(engine) as session:
            from tests.test_billing_enterprise_contracts import seed_org
            other = seed_org(session)  # an unrelated organization; the capacity policy stays ns's
            session.commit()
        with migrated_session(engine) as session:
            with pytest.raises(sa.exc.IntegrityError, match="Phase 12 identity"):
                _mismatched_job(session, ns, other.owner)
            session.rollback()
        operation_id = _pg_submit(engine, ns)
        with migrated_session(engine) as session:
            for statement, message in (
                (sa.update(AIDeliveryJob).values(organization_id=other.org), "immutable"),
                (sa.update(AIDeliveryJob).values(payload_sha256="0" * 64), "immutable"),
                (sa.update(AIDeliveryJob).values(attempts_started=-0, claims=0, max_claims=9), "immutable"),
                (sa.delete(AIDeliveryJob), "never deleted"),
            ):
                with pytest.raises(sa.exc.IntegrityError, match=message):
                    session.execute(statement.where(AIDeliveryJob.operation_id == operation_id))
                session.rollback()
            session.add(AIDeliveryStreamChunk(operation_id=operation_id, attempt_number=1, seq=1, content="x"))
            session.commit()
            with pytest.raises(sa.exc.IntegrityError, match="append-only"):
                session.execute(sa.delete(AIDeliveryStreamChunk).where(
                    AIDeliveryStreamChunk.operation_id == operation_id))
            session.rollback()
            call(session, operation_id)
            session.commit()
            with pytest.raises(sa.exc.IntegrityError, match="persisted"):
                settle_delivered_operation(session, operation_id=operation_id, delivered_attempt_number=1)
            session.rollback()
            assert charged(session, operation_id) == 0


# ---------------------------------------------------------------------------
# I4 integration shape: app context, db.session persistence, closure registry
# ---------------------------------------------------------------------------

CLOSURES = {}  # the process-local registry I4 keeps: operation_id -> (generate, on_persist)


@bdw.executor("i3-in-process")
def in_process(ctx):
    """I4's single executor: the in-memory closure, or not resumable after a reclaim."""
    from flask import current_app
    assert current_app.config["TESTING"]  # provider clients read config
    entry = CLOSURES.get(ctx.operation_id)
    if entry is None:
        raise bdw.DeliveryFailed("not_resumable")
    generate, on_persist = entry
    return generate(ctx, on_persist)


def _closure_turn(*, crash=False, text="from the closure"):
    def generate(ctx, on_persist):
        attempt = ctx.begin_attempt()
        ctx.check_call(attempt_number=attempt, call_index=0, provider=CLAUDE[0], model=CLAUDE[1],
                       max_input_tokens=1000, max_output_tokens=1000)
        started = ctx.now()
        if crash:
            raise SimulatedCrash()
        ctx.emit(attempt, text)
        ctx.record_call(attempt_number=attempt, call_index=0, provider=CLAUDE[0], model=CLAUDE[1],
                        outcome="succeeded", usage_label="reported", input_tokens=1000, output_tokens=1000,
                        requested_at=started, finished_at=ctx.now(), provider_request_id="closure-1")
        return bdw.DeliveryResult(delivered_attempt_number=attempt, response={"text": text}, on_persist=on_persist)
    return generate


def _in_process_submit(session, ns, **kwargs):
    authorization = authorize(session, ns, step=f"step-{uuid.uuid4().hex[:8]}")
    bdw.submit_delivery(session, operation_id=authorization.operation_id, organization_id=ns.org,
                        actor_user_id=ns.owner, executor="i3-in-process",
                        payload={"operation_type": "conversation", "route": "test"},
                        provider_timeout_seconds=30, heartbeat_interval_seconds=60, job_lease_seconds=90, **kwargs)
    return authorization.operation_id


def _store_write(session, response):
    """Stands in for the conversation store: it writes through Flask-SQLAlchemy's db.session."""
    from app.models import AppSetting
    assert session is flask_db.session  # the same thread-scoped session as the persistence
    flask_db.session.add(AppSetting(key=f"i3-store-{uuid.uuid4().hex[:8]}", value=response["text"]))


def _store_rows(session):
    from app.models import AppSetting
    session.expire_all()
    return session.execute(sa.select(AppSetting).where(AppSetting.key.like("i3-store-%"))).scalars().all()


def test_in_process_start_has_the_app_context_and_persists_on_the_threads_db_session(db, app):
    session = db.session
    ns = world(session)
    operation_id = _in_process_submit(session, ns)
    session.commit()
    CLOSURES[operation_id] = (_closure_turn(), _store_write)
    with app.app_context():
        thread = bdw.start_in_process(operation_id)
    thread.join(20)
    outcome = bdw.delivery_outcome(session, operation_id=operation_id, organization_id=ns.org,
                                   actor_user_id=ns.owner)
    assert outcome["outcome"] == "delivered" and outcome["charged_credits"] == 18
    assert outcome["billing_state"] == "finalized" and outcome["delivery_status"] == "delivered"
    assert [row.value for row in _store_rows(session)] == ["from the closure"]


def test_the_store_write_and_the_envelope_roll_back_together(db, app):
    session = db.session
    ns = world(session)
    operation_id = _in_process_submit(session, ns)
    session.commit()

    def failing_store(session_, response):
        _store_write(session_, response)
        flask_db.session.flush()
        raise RuntimeError("store refused the write")

    CLOSURES[operation_id] = (_closure_turn(), failing_store)
    assert bdw.DeliveryWorker(app=app).run_job(operation_id) == "undelivered"
    session.expire_all()
    assert _store_rows(session) == []
    assert session.get(AIOperation, operation_id).result_json is None  # no envelope either
    assert _job(session, operation_id).error_code == "persist_failed"
    assert charged(session, operation_id) == 0 and sums(session, ns.account) == (500, 0)


def test_a_reclaim_without_the_closure_is_not_resumable_and_never_loops(db, app):
    session = db.session
    ns = world(session)
    operation_id = _in_process_submit(session, ns, max_claims=5)
    session.commit()
    CLOSURES[operation_id] = (_closure_turn(crash=True), None)
    with pytest.raises(SimulatedCrash):
        bdw.DeliveryWorker(app=app).run_job(operation_id)
    CLOSURES.pop(operation_id)  # another process, or after a restart: the closure is gone
    _expire_job_lease(session, operation_id)
    other = bdw.DeliveryWorker(app=app, owner="other-process")
    assert other.run_once() == [(operation_id, "undelivered")]
    assert other.run_once() == []  # finished: never claimed again
    session.expire_all()
    job = _job(session, operation_id)
    assert (job.claims, job.error_code) == (2, "not_resumable")
    lost = session.execute(sa.select(AIProviderCallUsage).where(
        AIProviderCallUsage.operation_id == operation_id)).scalar_one()
    assert (lost.usage_label, lost.error_category) == ("unknown", "worker_lost")
    assert sums(session, ns.account) == (500, 0) and _reconciled(session, operation_id)


def test_the_payload_bound_is_refused_cleanly(db, monkeypatch):
    session = db.session
    ns = world(session)
    authorization = authorize(session, ns)
    assert bdw.MAX_PAYLOAD_BYTES == 8 * 1024 * 1024
    monkeypatch.setattr(bdw, "MAX_PAYLOAD_BYTES", 1024 * 1024)
    with pytest.raises(bdw.DeliveryError, match="exceeds 1 MB"):
        bdw.submit_delivery(session, operation_id=authorization.operation_id, organization_id=ns.org,
                            actor_user_id=ns.owner, executor="i3-in-process",
                            payload={"history": "x" * (1024 * 1024)}, provider_timeout_seconds=30)
    assert session.get(AIDeliveryJob, authorization.operation_id) is None
