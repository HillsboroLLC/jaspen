"""Phase 5.1 minimal-data external event inbox: migration, policy, and concurrency."""

import contextlib
import hashlib
import json
import os
import threading
import time
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


def _variant(raw, suffix=b" "):
    """The same parsed event with a different byte digest."""
    altered = raw + suffix
    return altered, json.loads(altered)


def _rows_text(connection):
    parts = []
    for table in ("external_event_inbox", "external_event_inbox_conflicts"):
        rows = connection.execute(sa.text(f"SELECT * FROM {table}")).mappings().all()
        parts.extend({k: str(v) for k, v in row.items()} for row in rows)
    return json.dumps(parts)


# --------------------------------------------------------------------------- engines

@pytest.fixture
def sqlite_engine(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'inbox.sqlite'}")
    _upgrade(engine)
    yield engine
    engine.dispose()


@contextlib.contextmanager
def _postgres_schema(validate_test_database_url, postgres_schema_url, upgrade=True):
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("local disposable PostgreSQL is not configured")
    base_url = validate_test_database_url(os.environ["TEST_DATABASE_URL"])
    schema = f"phase_5_1_{uuid.uuid4().hex}"
    admin = sa.create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    engine = sa.create_engine(postgres_schema_url(base_url, schema), pool_size=6)
    try:
        if upgrade:
            _upgrade(engine)
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def postgres_engine(validate_test_database_url, postgres_schema_url):
    with _postgres_schema(validate_test_database_url, postgres_schema_url) as engine:
        yield engine


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


def _claim(engine, now=None, lease_seconds=inbox.LEASE_SECONDS):
    with _session(engine) as session:
        row = inbox.claim_next_event(session, now=now or NOW, lease_seconds=lease_seconds)
        session.commit()
        return None if row is None else (row.id, row.attempt_count)


def _state(engine, event_pk):
    with engine.connect() as connection:
        return connection.execute(sa.text(
            "SELECT state, attempt_count, error_code FROM external_event_inbox WHERE id = :id"
        ), {"id": event_pk}).one()


def _conflicts(engine, event_pk):
    with engine.connect() as connection:
        return connection.execute(sa.text(
            "SELECT conflicting_digest, state_at_detection FROM external_event_inbox_conflicts "
            "WHERE inbox_event_id = :id ORDER BY detected_at, conflicting_digest"
        ), {"id": event_pk}).all()


def _rejected(engine, sql, params=None):
    with pytest.raises(sa.exc.DBAPIError) as error:
        with engine.begin() as connection:
            connection.execute(sa.text(sql), params or {})
    return error.value


# --------------------------------------------------------------------------- schema

def test_revision_is_linear_and_constants_match_library():
    script = ScriptDirectory(MIGRATIONS_DIR)
    assert script.get_revision(REVISION).down_revision == PARENT
    assert REVISION in {
        item.revision for item in script.iterate_revisions(script.get_current_head(), "base")
    }
    module = _revision()
    assert module.SUMMARY_FIELDS == inbox.SUMMARY_FIELDS
    assert module.RETENTION_DAYS == inbox.RETENTION_DAYS == 400
    assert module.DIGEST_CONFLICT_ERROR == inbox.DIGEST_CONFLICT_ERROR
    assert tuple(module.INBOX_STATES) == ("received", "processing", "processed", "retryable", "quarantined")


def test_inbox_has_no_live_runtime_importers():
    app_dir = BACKEND_DIR / "app"
    importers = []
    for path in app_dir.rglob("*.py"):
        if path.name in {
            "billing_inbox.py", "billing_financial.py", "models_billing_phase5.py", "models.py",
        }:
            continue
        text = path.read_text()
        if "billing_inbox" in text or "models_billing_phase5" in text or "ExternalEventInbox" in text:
            importers.append(str(path.relative_to(BACKEND_DIR)))
    assert importers == []
    assert "purge_expired_events" not in "".join(
        path.read_text() for path in app_dir.rglob("*.py") if path.name != "billing_inbox.py"
    )


def test_upgrade_creates_empty_inbox_and_conflict_tables(engine):
    inspector = sa.inspect(engine)
    assert {"external_event_inbox", "external_event_inbox_conflicts"}.issubset(inspector.get_table_names())
    indexes = {index["name"] for index in inspector.get_indexes("external_event_inbox")}
    assert {
        "ix_external_event_inbox_state_next_attempt",
        "ix_external_event_inbox_provider_object_created",
        "ix_external_event_inbox_state_processed",
    }.issubset(indexes)
    columns = {column["name"] for column in inspector.get_columns("external_event_inbox")}
    assert not {"digest_conflict_count", "last_conflict_digest", "last_conflict_at"} & columns
    with engine.connect() as connection:
        for table in ("external_event_inbox", "external_event_inbox_conflicts"):
            assert connection.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar() == 0


# --------------------------------------------------------------------------- minimization

def test_only_allowlisted_minimal_data_is_stored(engine):
    raw, event = _charge_event()
    event_pk, _ = _record(engine, raw, event)
    _record(engine, *_variant(raw))  # conflict evidence must also stay minimal
    with engine.connect() as connection:
        row = connection.execute(sa.text("SELECT * FROM external_event_inbox")).mappings().one()
        stored = _rows_text(connection)
    summary = row["summary_json"] if isinstance(row["summary_json"], dict) else json.loads(row["summary_json"])
    assert set(summary).issubset(set(inbox.SUMMARY_FIELDS))
    assert summary == {
        "schema_version": 1, "api_version": "2024-06-20", "status": "succeeded", "currency": "usd",
        "amount": 2500, "amount_refunded": 0, "customer": "cus_synthetic001",
        "invoice": "in_synthetic001", "payment_intent": "pi_synthetic001", "charge": "ch_synthetic001",
    }
    assert row["payload_digest"] == hashlib.sha256(raw).hexdigest()
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
          payload_digest, summary_json, livemode, provider_created_at, received_at, state, attempt_count)
        VALUES ('direct-1', 'stripe', 'evt_direct1', 'charge.succeeded', 'charge', 'ch_direct1',
          :digest, :summary, false, :now, :now, 'received', 0)
    """, {"digest": "a" * 64, "summary": json.dumps(summary), "now": NOW})


def test_database_rejects_events_that_skip_received(engine):
    _rejected(engine, """
        INSERT INTO external_event_inbox (id, provider, event_id, event_type, object_type, object_id,
          payload_digest, summary_json, livemode, provider_created_at, received_at, state, attempt_count,
          processed_at)
        VALUES ('direct-2', 'stripe', 'evt_direct2', 'charge.succeeded', 'charge', 'ch_direct2',
          :digest, '{"schema_version": 1}', false, :now, :now, 'processed', 0, :now)
    """, {"digest": "b" * 64, "now": NOW})


# --------------------------------------------------------------------------- idempotency and conflicts

def test_duplicates_converge_and_conflicts_are_append_only_evidence(engine):
    raw, event = _charge_event()
    first_id, first = _record(engine, raw, event)
    second_id, second = _record(engine, raw, event)
    assert (first, second) == ("inserted", "duplicate") and first_id == second_id
    variant_a, variant_b = _variant(raw, b" "), _variant(raw, b"  ")
    assert _record(engine, *variant_a) == (first_id, "digest_conflict")
    assert _record(engine, *variant_b) == (first_id, "digest_conflict")
    assert _record(engine, *variant_a) == (first_id, "digest_conflict")  # repeat adds nothing
    state = _state(engine, first_id)
    assert (state.state, state.error_code) == ("quarantined", "digest_conflict")
    conflicts = {row.conflicting_digest: row.state_at_detection for row in _conflicts(engine, first_id)}
    assert conflicts == {
        hashlib.sha256(variant_a[0]).hexdigest(): "received",
        hashlib.sha256(variant_b[0]).hexdigest(): "quarantined",
    }
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT payload_digest FROM external_event_inbox")).scalar() == \
            hashlib.sha256(raw).hexdigest()
    _rejected(engine, "UPDATE external_event_inbox_conflicts SET conflicting_digest = :d", {"d": "f" * 64})
    _rejected(engine, "DELETE FROM external_event_inbox_conflicts")
    _rejected(engine, """
        INSERT INTO external_event_inbox_conflicts (id, inbox_event_id, conflicting_digest, state_at_detection,
          detected_at) VALUES ('same-digest', :id, :digest, 'received', :now)
    """, {"id": first_id, "digest": hashlib.sha256(raw).hexdigest(), "now": NOW})


def test_conflict_during_processing_quarantines_and_fences_the_worker(engine):
    raw, event = _charge_event("evt_processingconflict")
    event_pk, _ = _record(engine, raw, event)
    claimed_pk, token = _claim(engine)
    assert claimed_pk == event_pk
    assert _record(engine, *_variant(raw)) == (event_pk, "digest_conflict")
    state = _state(engine, event_pk)
    assert (state.state, state.error_code, state.attempt_count) == ("quarantined", "digest_conflict", 1)
    assert [row.state_at_detection for row in _conflicts(engine, event_pk)] == ["processing"]
    with _session(engine) as session:
        with pytest.raises(inbox.StaleClaimError):
            inbox.mark_processed(session, event_pk, token)
        session.rollback()
    assert _state(engine, event_pk).state == "quarantined"


def test_conflict_after_processing_keeps_state_and_blocks_retention(engine):
    moment = NOW - timedelta(days=inbox.RETENTION_DAYS + 5)
    raw, event = _charge_event("evt_processedconflict", created=moment)
    event_pk, _ = _record(engine, raw, event, now=moment)
    _, token = _claim(engine, now=moment, lease_seconds=(inbox.RETENTION_DAYS + 6) * 86400)
    with _session(engine) as session:
        inbox.mark_processed(session, event_pk, token, now=moment + timedelta(minutes=1))
        session.commit()
    assert _record(engine, *_variant(raw)) == (event_pk, "digest_conflict")
    assert _state(engine, event_pk).state == "processed"
    assert [row.state_at_detection for row in _conflicts(engine, event_pk)] == ["processed"]
    with _session(engine) as session:
        assert inbox.purge_expired_events(session) == 0
        session.commit()
    _rejected(engine, "DELETE FROM external_event_inbox WHERE id = :id", {"id": event_pk})


# --------------------------------------------------------------------------- lifecycle and fencing

def test_claim_retry_backoff_and_processing_lifecycle(engine):
    raw, event = _charge_event("evt_lifecycle")
    event_pk, _ = _record(engine, raw, event)
    with _session(engine) as session:
        row = inbox.claim_next_event(session, now=NOW)
        assert (row.state, row.attempt_count) == ("processing", 1)
        row = inbox.mark_retryable(session, event_pk, 1, "downstream_unavailable", now=NOW)
        session.commit()
        assert row.state == "retryable"
        assert row.next_attempt_at.replace(tzinfo=timezone.utc) == NOW + timedelta(seconds=60)
    assert _claim(engine, now=NOW + timedelta(seconds=30)) is None
    _, token = _claim(engine, now=NOW + timedelta(seconds=61))
    assert token == 2
    with _session(engine) as session:
        inbox.mark_processed(session, event_pk, token, now=NOW + timedelta(seconds=62))
        session.commit()
    assert _state(engine, event_pk).state == "processed"
    assert _claim(engine, now=NOW + timedelta(days=1)) is None
    assert [inbox.retry_delay_seconds(n) for n in (1, 2, 3, 20)] == [60, 120, 240, inbox.MAX_RETRY_SECONDS]


def test_retry_exhaustion_quarantines_and_operator_requeue(engine):
    raw, event = _charge_event("evt_exhaust")
    event_pk, _ = _record(engine, raw, event)
    moment = NOW
    for _ in range(inbox.MAX_ATTEMPTS):
        _, token = _claim(engine, now=moment)
        with _session(engine) as session:
            inbox.mark_retryable(session, event_pk, token, "still_failing", now=moment)
            session.commit()
        moment = moment + timedelta(days=1)
    state = _state(engine, event_pk)
    assert (state.state, state.error_code, state.attempt_count) == ("quarantined", "retry_exhausted", inbox.MAX_ATTEMPTS)
    assert _claim(engine, now=moment) is None
    with _session(engine) as session:
        inbox.requeue_quarantined(session, event_pk, now=moment)
        session.commit()
    assert _claim(engine, now=moment)[1] == inbox.MAX_ATTEMPTS + 1


@pytest.mark.parametrize("action", ["processed", "retryable", "quarantined"])
def test_expired_lease_cannot_complete_retry_or_quarantine(engine, action):
    raw, event = _charge_event(f"evt_expired{action}")
    event_pk, _ = _record(engine, raw, event)
    _, token = _claim(engine, now=NOW - timedelta(hours=2), lease_seconds=60)
    with _session(engine) as session:
        with pytest.raises(inbox.StaleClaimError):
            if action == "processed":
                inbox.mark_processed(session, event_pk, token)
            elif action == "retryable":
                inbox.mark_retryable(session, event_pk, token, "late_worker")
            else:
                inbox.mark_quarantined(session, event_pk, "late_worker", claim_token=token)
        session.rollback()
    assert _state(engine, event_pk).state == "processing"
    # The database independently rejects a worker transition on an expired lease.
    _rejected(engine, """
        UPDATE external_event_inbox SET state = 'processed', processed_at = :now, lease_expires_at = NULL
        WHERE id = :id
    """, {"id": event_pk, "now": NOW})


def test_reclaimed_lease_fences_the_previous_worker(engine):
    raw, event = _charge_event("evt_reclaimed")
    event_pk, _ = _record(engine, raw, event)
    _, stale_token = _claim(engine, now=NOW - timedelta(hours=2), lease_seconds=60)
    reclaimed_pk, current_token = _claim(engine, now=NOW)
    assert (reclaimed_pk, stale_token, current_token) == (event_pk, 1, 2)
    with _session(engine) as session:
        for stale_call in (
            lambda: inbox.mark_processed(session, event_pk, stale_token),
            lambda: inbox.mark_retryable(session, event_pk, stale_token, "late_worker"),
            lambda: inbox.mark_quarantined(session, event_pk, "late_worker", claim_token=stale_token),
        ):
            with pytest.raises(inbox.StaleClaimError):
                stale_call()
        inbox.mark_processed(session, event_pk, current_token)
        session.commit()
    assert tuple(_state(engine, event_pk))[:2] == ("processed", 2)
    with _session(engine) as session:
        with pytest.raises(inbox.StaleClaimError):
            inbox.mark_processed(session, event_pk, current_token)  # already completed
        session.rollback()


def test_live_lease_cannot_be_reclaimed_directly(engine):
    raw, event = _charge_event("evt_livelease")
    event_pk, _ = _record(engine, raw, event)
    _claim(engine, lease_seconds=600)
    _rejected(engine, """
        UPDATE external_event_inbox SET attempt_count = attempt_count + 1, lease_expires_at = :later
        WHERE id = :id
    """, {"id": event_pk, "later": NOW + timedelta(hours=1)})


@pytest.mark.parametrize("sql", [
    "UPDATE external_event_inbox SET event_id = 'evt_rewritten'",
    "UPDATE external_event_inbox SET payload_digest = :other",
    "UPDATE external_event_inbox SET summary_json = '{\"schema_version\": 1, \"amount\": 1}'",
    "UPDATE external_event_inbox SET state = 'processing'",
    "UPDATE external_event_inbox SET attempt_count = attempt_count + 1",
    "UPDATE external_event_inbox SET processed_at = :now",
    "UPDATE external_event_inbox SET state = 'quarantined', error_code = 'late'",
])
def test_processed_events_are_immutable(engine, sql):
    raw, event = _charge_event("evt_immutable")
    event_pk, _ = _record(engine, raw, event)
    _, token = _claim(engine)
    with _session(engine) as session:
        inbox.mark_processed(session, event_pk, token, now=NOW + timedelta(seconds=1))
        session.commit()
    _rejected(engine, sql, {"other": "c" * 64, "now": NOW + timedelta(days=1)})


# --------------------------------------------------------------------------- retention

def _processed_event(engine, event_id, processed_days_ago):
    moment = NOW - timedelta(days=processed_days_ago, minutes=5)
    raw, event = _charge_event(event_id, created=moment)
    event_pk, _ = _record(engine, raw, event, now=moment)
    _, token = _claim(engine, now=moment, lease_seconds=(processed_days_ago + 1) * 86400)
    with _session(engine) as session:
        inbox.mark_processed(session, event_pk, token, now=moment + timedelta(minutes=1))
        session.commit()
    return event_pk


def _unprocessed_event(engine, event_id, state, days_ago):
    moment = NOW - timedelta(days=days_ago)
    raw, event = _charge_event(event_id, created=moment)
    event_pk, _ = _record(engine, raw, event, now=moment)
    if state == "received":
        return event_pk
    _, token = _claim(engine, now=moment, lease_seconds=(days_ago + 1) * 86400)
    with _session(engine) as session:
        if state == "retryable":
            inbox.mark_retryable(session, event_pk, token, "still_failing", now=moment)
        elif state == "quarantined":
            inbox.mark_quarantined(session, event_pk, "investigation", claim_token=token, now=moment)
        session.commit()
    return event_pk


def test_retention_purges_only_expired_conflict_free_processed_events(engine):
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
    recent = _processed_event(engine, "evt_recent", inbox.RETENTION_DAYS - 1)
    quarantined = _unprocessed_event(engine, "evt_oldquarantined", "quarantined", inbox.RETENTION_DAYS + 50)
    for event_pk in (recent, quarantined):
        _rejected(engine, "DELETE FROM external_event_inbox WHERE id = :id", {"id": event_pk})
    with pytest.raises(sa.exc.DBAPIError):
        with _session(engine) as session:
            inbox.purge_expired_events(session, now=NOW + timedelta(days=10))
            session.commit()
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT COUNT(*) FROM external_event_inbox")).scalar() == 2


# --------------------------------------------------------------------------- downgrade

def test_downgrade_refuses_populated_inbox(engine):
    raw, event = _charge_event("evt_downgrade")
    _record(engine, raw, event)
    module = _revision()
    with pytest.raises(module.ExternalEventInboxNotEmptyError, match="external_event_inbox=1"):
        with _ops(engine):
            module.downgrade()
    assert "external_event_inbox" in sa.inspect(engine).get_table_names()


def test_empty_downgrade_removes_inbox_and_reupgrade_works(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'inbox-empty.sqlite'}")
    _upgrade(engine)
    with _ops(engine):
        _revision().downgrade()
    names = sa.inspect(engine).get_table_names()
    assert not {"external_event_inbox", "external_event_inbox_conflicts"} & set(names)
    with engine.connect() as connection:
        assert connection.execute(sa.text(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'trg_external_event_inbox%'"
        )).scalar() == 0
    _upgrade(engine)
    assert "external_event_inbox" in sa.inspect(engine).get_table_names()
    engine.dispose()


# --------------------------------------------------------------------------- PostgreSQL only

@pytest.mark.postgres
@pytest.mark.parametrize("statement", [
    "TRUNCATE external_event_inbox_conflicts",
    "TRUNCATE external_event_inbox CASCADE",
    "TRUNCATE external_event_inbox, external_event_inbox_conflicts",
])
def test_postgres_truncate_is_rejected(postgres_engine, statement):
    raw, event = _charge_event("evt_truncate")
    _record(postgres_engine, raw, event)
    _record(postgres_engine, *_variant(raw))
    error = _rejected(postgres_engine, statement)
    assert getattr(error.orig, "sqlstate", None) == "23514"
    assert "cannot be truncated" in str(error.orig)
    with postgres_engine.connect() as connection:
        assert connection.execute(sa.text("SELECT COUNT(*) FROM external_event_inbox")).scalar() == 1
        assert connection.execute(sa.text("SELECT COUNT(*) FROM external_event_inbox_conflicts")).scalar() == 1


@pytest.mark.postgres
def test_postgres_downgrade_waits_for_concurrent_insert_and_refuses(postgres_engine):
    """ACCESS EXCLUSIVE before counting: an in-flight insert cannot be dropped."""
    raw, event = _charge_event("evt_downgraderace")
    writer = postgres_engine.connect()
    writer_tx = writer.begin()
    writer.execute(sa.text("""
        INSERT INTO external_event_inbox (id, provider, event_id, event_type, object_type, object_id,
          payload_digest, summary_json, livemode, provider_created_at, received_at, state, attempt_count)
        VALUES ('race-row', 'stripe', 'evt_downgraderace', 'charge.succeeded', 'charge', 'ch_race',
          :digest, '{"schema_version": 1}', false, now(), now(), 'received', 0)
    """), {"digest": hashlib.sha256(raw).hexdigest()})
    module = _revision()
    outcome = {}

    def run_downgrade():
        try:
            with _ops(postgres_engine) as connection:
                outcome["pid"] = connection.execute(sa.text("SELECT pg_backend_pid()")).scalar()
                module.downgrade()
            outcome["result"] = "dropped"
        except module.ExternalEventInboxNotEmptyError as exc:
            outcome["result"] = str(exc)

    thread = threading.Thread(target=run_downgrade)
    thread.start()
    waited = None
    for _ in range(60):
        time.sleep(0.05)
        if "pid" in outcome:
            with postgres_engine.connect() as probe:
                waited = probe.execute(sa.text(
                    "SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"
                ), {"pid": outcome["pid"]}).scalar()
            if waited == "Lock":
                break
    assert waited == "Lock" and thread.is_alive()
    writer_tx.commit()
    writer.close()
    thread.join(20)
    assert "external_event_inbox=1" in outcome["result"]
    assert "external_event_inbox" in sa.inspect(postgres_engine).get_table_names()
    with postgres_engine.connect() as connection:
        assert connection.execute(sa.text("SELECT COUNT(*) FROM external_event_inbox")).scalar() == 1


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
