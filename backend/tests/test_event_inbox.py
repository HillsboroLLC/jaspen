"""Phase 5.1 minimal-data external event inbox: migration, policy, and concurrency."""

import contextlib
import hashlib
import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.orm import Session

from app import billing_inbox as inbox
from app.models_billing_phase5 import ExternalEventInbox


BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = str(BACKEND_DIR / "migrations")
REVISION = "b2d4f6a8c0e3"
PARENT = "f9c1a3e5b7d4"
NOW = datetime.now(timezone.utc)

# Synthetic test data only: no real Stripe identifiers, customers, or cards.
SENSITIVE_VALUES = (
    "4242", "Synthetic Person", "person@example.test", "1 Test Street", "Testville",
    "+15555550100", "fp_synthetic", "synthetic description", "metadata-secret",
    "visa", "pm_synthetic",
)


def _revision():
    return ScriptDirectory(MIGRATIONS_DIR).get_revision(REVISION).module


@contextlib.contextmanager
def _ops(engine):
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            yield connection


def _upgrade(engine):
    with _ops(engine):
        _revision().upgrade()


def _downgrade(engine):
    with _ops(engine):
        _revision().downgrade()


def _charge_event(event_id="evt_synthetic001", amount=2500, created=None):
    """A realistic Stripe charge event carrying data the inbox must never keep."""
    event = {
        "id": event_id,
        "object": "event",
        "api_version": "2024-06-20",
        "created": int((created or NOW).timestamp()),
        "livemode": False,
        "type": "charge.succeeded",
        "data": {"object": {
            "id": "ch_synthetic001",
            "object": "charge",
            "amount": amount,
            "amount_refunded": 0,
            "currency": "usd",
            "status": "succeeded",
            "customer": "cus_synthetic001",
            "invoice": {"id": "in_synthetic001", "object": "invoice", "customer_email": "person@example.test"},
            "payment_intent": "pi_synthetic001",
            "payment_method": "pm_synthetic",
            "description": "synthetic description",
            "receipt_email": "person@example.test",
            "metadata": {"internal": "metadata-secret"},
            "billing_details": {
                "name": "Synthetic Person", "email": "person@example.test", "phone": "+15555550100",
                "address": {"line1": "1 Test Street", "city": "Testville", "postal_code": "00000"},
            },
            "payment_method_details": {"type": "card", "card": {
                "brand": "visa", "last4": "4242", "exp_month": 12, "exp_year": 2030,
                "fingerprint": "fp_synthetic", "country": "US",
            }},
        }},
    }
    raw = json.dumps(event, sort_keys=True).encode()
    return raw, event


def _row_text(connection):
    rows = connection.execute(sa.text("SELECT * FROM external_event_inbox")).mappings().all()
    return json.dumps([{k: str(v) for k, v in row.items()} for row in rows])


# --------------------------------------------------------------------------- engines

@pytest.fixture
def sqlite_engine(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'inbox.sqlite'}")
    _upgrade(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def postgres_engine(validate_test_database_url, postgres_schema_url):
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("local disposable PostgreSQL is not configured")
    base_url = validate_test_database_url(os.environ["TEST_DATABASE_URL"])
    schema = f"phase_5_1_{uuid.uuid4().hex}"
    admin = sa.create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    engine = sa.create_engine(postgres_schema_url(base_url, schema), pool_size=6)
    try:
        _upgrade(engine)
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


ENGINES = ["sqlite_engine", pytest.param("postgres_engine", marks=pytest.mark.postgres)]


@pytest.fixture(params=ENGINES)
def engine(request):
    return request.getfixturevalue(request.param)


def _session(engine):
    return Session(engine, expire_on_commit=False)


def _record(engine, raw, event, now=None):
    with _session(engine) as session:
        row, outcome = inbox.record_event(session, raw, event, now=now or NOW)
        session.commit()
        return row.id, outcome


def _rejected(engine, sql, params=None):
    with pytest.raises(sa.exc.DBAPIError):
        with engine.begin() as connection:
            connection.execute(sa.text(sql), params or {})


# --------------------------------------------------------------------------- schema

def test_revision_is_linear_and_constants_match_library():
    script = ScriptDirectory(MIGRATIONS_DIR)
    assert script.get_revision(REVISION).down_revision == PARENT
    assert script.get_heads() == [REVISION]
    module = _revision()
    assert module.SUMMARY_FIELDS == inbox.SUMMARY_FIELDS
    assert module.RETENTION_DAYS == inbox.RETENTION_DAYS
    assert tuple(module.INBOX_STATES) == ("received", "processing", "processed", "retryable", "quarantined")


def test_inbox_has_no_live_runtime_importers():
    app_dir = BACKEND_DIR / "app"
    importers = []
    for path in app_dir.rglob("*.py"):
        if path.name in {"billing_inbox.py", "models_billing_phase5.py", "models.py"}:
            continue
        text = path.read_text()
        if "billing_inbox" in text or "models_billing_phase5" in text or "ExternalEventInbox" in text:
            importers.append(str(path.relative_to(BACKEND_DIR)))
    assert importers == []
    models_text = (app_dir / "models.py").read_text()
    assert "from .models_billing_phase5 import ExternalEventInbox" in models_text


def test_upgrade_creates_empty_inbox_with_indexes(engine):
    inspector = sa.inspect(engine)
    assert "external_event_inbox" in inspector.get_table_names()
    indexes = {index["name"] for index in inspector.get_indexes("external_event_inbox")}
    assert {
        "ix_external_event_inbox_state_next_attempt",
        "ix_external_event_inbox_provider_object_created",
        "ix_external_event_inbox_state_processed",
    }.issubset(indexes)
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT COUNT(*) FROM external_event_inbox")).scalar() == 0


# --------------------------------------------------------------------------- minimization

def test_only_allowlisted_minimal_data_is_stored(engine):
    raw, event = _charge_event()
    _record(engine, raw, event)
    with engine.connect() as connection:
        row = connection.execute(sa.text("SELECT * FROM external_event_inbox")).mappings().one()
        stored = _row_text(connection)
    summary = row["summary_json"] if isinstance(row["summary_json"], dict) else json.loads(row["summary_json"])
    assert set(summary).issubset(set(inbox.SUMMARY_FIELDS))
    assert summary == {
        "schema_version": 1, "api_version": "2024-06-20", "status": "succeeded", "currency": "usd",
        "amount": 2500, "amount_refunded": 0, "customer": "cus_synthetic001",
        "invoice": "in_synthetic001", "payment_intent": "pi_synthetic001", "charge": "ch_synthetic001",
    }
    assert row["payload_digest"] == hashlib.sha256(raw).hexdigest()
    assert (row["event_id"], row["event_type"], row["object_type"], row["object_id"]) == (
        "evt_synthetic001", "charge.succeeded", "charge", "ch_synthetic001",
    )
    for value in SENSITIVE_VALUES:
        assert value not in stored, value


def test_minimizer_rejects_malformed_events():
    raw, event = _charge_event()
    for broken in (
        {**event, "id": "not-an-event"},
        {**event, "type": "Bad Type!"},
        {**event, "created": "yesterday"},
        {**event, "livemode": "false"},
        {**event, "data": {}},
    ):
        with pytest.raises(inbox.InboxInvariantError):
            inbox.minimize_stripe_event(raw, broken)
    with pytest.raises(inbox.InboxInvariantError):
        inbox.minimize_stripe_event(b"", event)


@pytest.mark.parametrize("summary", [
    {"schema_version": 1, "email": "person@example.test"},
    {"schema_version": 1, "card": "4242"},
    {"schema_version": 1, "customer": {"id": "cus_x", "name": "Synthetic Person"}},
    {"schema_version": 1, "status": ["succeeded"]},
    {"schema_version": 1, "status": "x" * 256},
])
def test_database_rejects_non_minimal_summaries(engine, summary):
    _rejected(engine, """
        INSERT INTO external_event_inbox (id, provider, event_id, event_type, object_type, object_id,
          payload_digest, summary_json, livemode, provider_created_at, received_at, state, attempt_count,
          digest_conflict_count)
        VALUES ('direct-1', 'stripe', 'evt_direct1', 'charge.succeeded', 'charge', 'ch_direct1',
          :digest, :summary, false, :now, :now, 'received', 0, 0)
    """, {"digest": "a" * 64, "summary": json.dumps(summary), "now": NOW})


def test_database_rejects_events_that_skip_received(engine):
    _rejected(engine, """
        INSERT INTO external_event_inbox (id, provider, event_id, event_type, object_type, object_id,
          payload_digest, summary_json, livemode, provider_created_at, received_at, state, attempt_count,
          processed_at, digest_conflict_count)
        VALUES ('direct-2', 'stripe', 'evt_direct2', 'charge.succeeded', 'charge', 'ch_direct2',
          :digest, '{"schema_version": 1}', false, :now, :now, 'processed', 0, :now, 0)
    """, {"digest": "b" * 64, "now": NOW})


# --------------------------------------------------------------------------- idempotency

def test_duplicates_converge_and_digest_conflicts_quarantine(engine):
    raw, event = _charge_event()
    first_id, first = _record(engine, raw, event)
    second_id, second = _record(engine, raw, event)
    assert (first, second) == ("inserted", "duplicate")
    assert first_id == second_id
    altered_raw = raw.replace(b'"amount": 2500', b'"amount": 9999')
    altered_event = json.loads(altered_raw)
    conflict_id, outcome = _record(engine, altered_raw, altered_event)
    assert (conflict_id, outcome) == (first_id, "digest_conflict")
    with engine.connect() as connection:
        row = connection.execute(sa.text("SELECT * FROM external_event_inbox")).mappings().one()
    assert row["state"] == "quarantined" and row["error_code"] == "digest_conflict"
    assert row["digest_conflict_count"] == 1
    assert row["last_conflict_digest"] == hashlib.sha256(altered_raw).hexdigest()
    assert row["payload_digest"] == hashlib.sha256(raw).hexdigest()


def test_conflict_after_processing_keeps_processed_state_with_evidence(engine):
    raw, event = _charge_event("evt_processedconflict")
    _record(engine, raw, event)
    with _session(engine) as session:
        inbox.mark_processed(session, inbox.claim_next_event(session))
        session.commit()
    altered_raw = raw + b" "
    _, outcome = _record(engine, altered_raw, json.loads(altered_raw))
    assert outcome == "digest_conflict"
    with engine.connect() as connection:
        row = connection.execute(sa.text("SELECT state, digest_conflict_count FROM external_event_inbox")).one()
    assert tuple(row) == ("processed", 1)


# --------------------------------------------------------------------------- lifecycle

def test_claim_retry_backoff_and_processing_lifecycle(engine):
    raw, event = _charge_event("evt_lifecycle")
    _record(engine, raw, event)
    with _session(engine) as session:
        row = inbox.claim_next_event(session, now=NOW)
        assert row.state == "processing" and row.attempt_count == 1
        inbox.mark_retryable(session, row, "downstream_unavailable", now=NOW)
        session.commit()
        assert row.next_attempt_at.replace(tzinfo=timezone.utc) == NOW + timedelta(seconds=60)
    with _session(engine) as session:
        assert inbox.claim_next_event(session, now=NOW + timedelta(seconds=30)) is None
        row = inbox.claim_next_event(session, now=NOW + timedelta(seconds=61))
        assert row is not None and row.attempt_count == 2
        inbox.mark_processed(session, row, now=NOW + timedelta(seconds=62))
        session.commit()
    with _session(engine) as session:
        assert inbox.claim_next_event(session, now=NOW + timedelta(days=1)) is None
    assert [inbox.retry_delay_seconds(n) for n in (1, 2, 3, 20)] == [60, 120, 240, inbox.MAX_RETRY_SECONDS]


def test_retry_exhaustion_quarantines_and_operator_requeue(engine):
    raw, event = _charge_event("evt_exhaust")
    _record(engine, raw, event)
    moment = NOW
    for _ in range(inbox.MAX_ATTEMPTS):
        with _session(engine) as session:
            row = inbox.claim_next_event(session, now=moment)
            inbox.mark_retryable(session, row, "still_failing", now=moment)
            session.commit()
            moment = moment + timedelta(days=1)
    with engine.connect() as connection:
        state = connection.execute(sa.text("SELECT state, error_code, attempt_count FROM external_event_inbox")).one()
    assert tuple(state) == ("quarantined", "retry_exhausted", inbox.MAX_ATTEMPTS)
    with _session(engine) as session:
        assert inbox.claim_next_event(session, now=moment) is None
        row = session.execute(sa.select(ExternalEventInbox)).scalar_one()
        inbox.requeue_quarantined(session, row, now=moment)
        session.commit()
    with _session(engine) as session:
        assert inbox.claim_next_event(session, now=moment).attempt_count == inbox.MAX_ATTEMPTS + 1


def test_expired_lease_can_be_reclaimed_but_live_lease_cannot(engine):
    raw, event = _charge_event("evt_lease")
    row_id, _ = _record(engine, raw, event)
    with _session(engine) as session:
        inbox.claim_next_event(session, lease_seconds=600)
        session.commit()
    _rejected(engine, """
        UPDATE external_event_inbox SET attempt_count = attempt_count + 1,
          lease_expires_at = :later WHERE id = :id
    """, {"id": row_id, "later": NOW + timedelta(hours=1)})
    raw2, event2 = _charge_event("evt_leaseexpired")
    _record(engine, raw2, event2)
    with _session(engine) as session:
        first = inbox.claim_next_event(session, now=NOW - timedelta(hours=2), lease_seconds=60)
        assert first.event_id == "evt_leaseexpired"
        session.commit()
    with _session(engine) as session:
        reclaimed = inbox.claim_next_event(session, now=NOW)
        assert reclaimed.event_id == "evt_leaseexpired" and reclaimed.attempt_count == 2
        session.commit()


@pytest.mark.parametrize("sql", [
    "UPDATE external_event_inbox SET event_id = 'evt_rewritten'",
    "UPDATE external_event_inbox SET payload_digest = :other",
    "UPDATE external_event_inbox SET summary_json = '{\"schema_version\": 1, \"amount\": 1}'",
    "UPDATE external_event_inbox SET state = 'processing'",
    "UPDATE external_event_inbox SET attempt_count = attempt_count + 1",
    "UPDATE external_event_inbox SET processed_at = :now",
    "UPDATE external_event_inbox SET digest_conflict_count = 0, last_conflict_digest = NULL, last_conflict_at = NULL",
])
def test_processed_events_and_evidence_are_immutable(engine, sql):
    raw, event = _charge_event("evt_immutable")
    _record(engine, raw, event)
    _record(engine, raw + b" ", json.loads(raw))
    with _session(engine) as session:
        row = session.execute(sa.select(ExternalEventInbox)).scalar_one()
        inbox.requeue_quarantined(session, row, now=NOW)
        session.commit()
    with _session(engine) as session:
        inbox.mark_processed(session, inbox.claim_next_event(session, now=NOW), now=NOW + timedelta(seconds=1))
        session.commit()
    _rejected(engine, sql, {"other": "c" * 64, "now": NOW + timedelta(days=1)})


# --------------------------------------------------------------------------- retention

def _processed_event(engine, event_id, processed_days_ago):
    moment = NOW - timedelta(days=processed_days_ago, minutes=5)
    raw, event = _charge_event(event_id, created=moment)
    _record(engine, raw, event, now=moment)
    with _session(engine) as session:
        row = session.execute(
            sa.select(ExternalEventInbox).where(ExternalEventInbox.event_id == event_id)
        ).scalar_one()
        row.state = "processing"
        row.attempt_count = 1
        row.lease_expires_at = moment + timedelta(minutes=5)
        session.flush()
        inbox.mark_processed(session, row, now=moment + timedelta(minutes=1))
        session.commit()


def _unprocessed_event(engine, event_id, state, days_ago):
    moment = NOW - timedelta(days=days_ago)
    raw, event = _charge_event(event_id, created=moment)
    _record(engine, raw, event, now=moment)
    if state == "received":
        return
    with _session(engine) as session:
        row = inbox.claim_next_event(session, now=moment)
        if state == "retryable":
            inbox.mark_retryable(session, row, "still_failing", now=moment)
        elif state == "quarantined":
            inbox.mark_quarantined(session, row, "investigation")
        session.commit()


def test_retention_purges_only_expired_processed_events(engine):
    _processed_event(engine, "evt_expired", inbox.RETENTION_DAYS + 1)
    _processed_event(engine, "evt_recent", inbox.RETENTION_DAYS - 1)
    _unprocessed_event(engine, "evt_oldquarantined", "quarantined", inbox.RETENTION_DAYS + 50)
    _unprocessed_event(engine, "evt_oldretryable", "retryable", inbox.RETENTION_DAYS + 50)
    _unprocessed_event(engine, "evt_oldreceived", "received", inbox.RETENTION_DAYS + 50)
    with _session(engine) as session:
        assert inbox.purge_expired_events(session) == 1
        session.commit()
    with engine.connect() as connection:
        remaining = set(connection.execute(sa.text("SELECT event_id FROM external_event_inbox")).scalars())
    assert remaining == {"evt_recent", "evt_oldquarantined", "evt_oldretryable", "evt_oldreceived"}


def test_database_enforces_retention_on_direct_and_early_deletes(engine):
    _processed_event(engine, "evt_recent", inbox.RETENTION_DAYS - 1)
    _unprocessed_event(engine, "evt_oldquarantined", "quarantined", inbox.RETENTION_DAYS + 50)
    for event_id in ("evt_recent", "evt_oldquarantined"):
        _rejected(engine, "DELETE FROM external_event_inbox WHERE event_id = :id", {"id": event_id})
    with pytest.raises(sa.exc.DBAPIError):
        with _session(engine) as session:
            inbox.purge_expired_events(session, now=NOW + timedelta(days=10))
            session.commit()
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT COUNT(*) FROM external_event_inbox")).scalar() == 2


# --------------------------------------------------------------------------- downgrade

def test_downgrade_refuses_populated_inbox_and_empty_downgrade_reverses(engine):
    raw, event = _charge_event("evt_downgrade")
    _record(engine, raw, event)
    module = _revision()
    with pytest.raises(module.ExternalEventInboxNotEmptyError, match="external_event_inbox=1"):
        with _ops(engine):
            module.downgrade()
    assert "external_event_inbox" in sa.inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT COUNT(*) FROM external_event_inbox")).scalar() == 1


def test_empty_downgrade_removes_inbox_and_reupgrade_works(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'inbox-empty.sqlite'}")
    _upgrade(engine)
    _downgrade(engine)
    assert "external_event_inbox" not in sa.inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.execute(sa.text(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'trg_external_event_inbox%'"
        )).scalar() == 0
    _upgrade(engine)
    assert "external_event_inbox" in sa.inspect(engine).get_table_names()
    engine.dispose()


# --------------------------------------------------------------------------- PostgreSQL concurrency

@pytest.mark.postgres
def test_postgres_concurrent_claims_never_share_an_event(postgres_engine):
    for number in range(6):
        raw, event = _charge_event(f"evt_concurrent{number}")
        _record(postgres_engine, raw, event)
    barrier = threading.Barrier(6)
    claimed, errors = [], []

    def worker():
        try:
            with _session(postgres_engine) as session:
                barrier.wait()
                row = inbox.claim_next_event(session)
                claimed.append(row.event_id if row else None)
                session.commit()
        except Exception as exc:  # pragma: no cover - surfaced by assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(20)
    assert errors == []
    assert sorted(claimed) == sorted(f"evt_concurrent{n}" for n in range(6))


@pytest.mark.postgres
@pytest.mark.parametrize("isolation", ["READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE"])
def test_postgres_single_event_is_claimed_once_under_each_isolation(postgres_engine, isolation):
    raw, event = _charge_event("evt_single")
    _record(postgres_engine, raw, event)
    other = postgres_engine.execution_options(isolation_level=isolation)
    with Session(other) as stale, Session(postgres_engine) as first:
        stale.execute(sa.text("SELECT COUNT(*) FROM external_event_inbox")).scalar()  # snapshot taken
        assert inbox.claim_next_event(first) is not None
        first.commit()
        try:
            second = inbox.claim_next_event(stale)
            stale.commit()
            outcome = "claimed" if second is not None else "none"
        except sa.exc.DBAPIError as exc:
            stale.rollback()
            outcome = getattr(exc.orig, "sqlstate", None)
    assert outcome in ("none", "40001")
    with postgres_engine.connect() as connection:
        assert connection.execute(sa.text("SELECT attempt_count FROM external_event_inbox")).scalar() == 1


@pytest.mark.postgres
def test_postgres_concurrent_receipt_of_same_event_stores_one_row(postgres_engine):
    raw, event = _charge_event("evt_race")
    barrier = threading.Barrier(4)
    outcomes, errors = [], []

    def worker():
        try:
            with _session(postgres_engine) as session:
                barrier.wait()
                _, outcome = inbox.record_event(session, raw, event)
                session.commit()
                outcomes.append(outcome)
        except Exception as exc:  # pragma: no cover - surfaced by assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(20)
    assert errors == []
    assert sorted(outcomes) == ["duplicate", "duplicate", "duplicate", "inserted"]
    with postgres_engine.connect() as connection:
        assert connection.execute(sa.text("SELECT COUNT(*) FROM external_event_inbox")).scalar() == 1
