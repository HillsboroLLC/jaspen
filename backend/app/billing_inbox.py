"""Inactive Phase 5.1 minimal-data external event inbox.

Nothing in live routes, webhooks, authentication, jobs, or readers imports this
module. A later, separately authorized increment will verify the Stripe
signature at the webhook boundary and then call ``record_event``. Retention
purging is not scheduled and requires separate authorization to run.

Data minimization and retention policy (documented in
docs/specs/billing/phase-2-5-implementation-proposal.md, Phase 5.1):

* Stored: provider, event ID and type, referenced object type and ID, livemode,
  provider-created and received times, a SHA-256 digest of the verified raw
  payload, processing state/attempts/errors, and an allowlisted scalar summary
  (identifiers, amounts, currency, status). Conflicting digests are separate
  append-only evidence rows.
* Never stored: the raw payload, payment-card details, billing details,
  customer names, emails, addresses, phone numbers, metadata, descriptions,
  or any nested object.
* Processed events without digest conflicts may be deleted RETENTION_DAYS
  after processing. Received, processing, retryable, quarantined, and
  conflicted events are never deleted by retention. The database enforces the
  same rule.

Claims are fenced: ``claim_next_event`` returns the row whose ``attempt_count``
is the claim token. Completing, retrying, or quarantining requires that token
and an unexpired lease; a stale worker updates zero rows and gets
``StaleClaimError``.
"""

import hashlib
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, column, exists, inspect, or_, select, table, update
from sqlalchemy.exc import IntegrityError

from .billing_ledger import _begin_serialized_sqlite_write
from .models_billing_phase5 import ExternalEventInbox, ExternalEventInboxConflict

PROVIDER = "stripe"
SUMMARY_SCHEMA_VERSION = 1
RETENTION_DAYS = 400
LEASE_SECONDS = 300
MAX_ATTEMPTS = 10
BASE_RETRY_SECONDS = 60
MAX_RETRY_SECONDS = 6 * 60 * 60
DIGEST_CONFLICT_ERROR = "digest_conflict"

AMOUNT_FIELDS = ("amount", "amount_due", "amount_paid", "amount_refunded")
REFERENCE_FIELDS = (
    "customer", "subscription", "invoice", "payment_intent", "charge",
    "refund", "dispute", "checkout_session",
)
SUMMARY_FIELDS = (
    "schema_version", "api_version", "status", "currency",
    *AMOUNT_FIELDS, *REFERENCE_FIELDS,
)
UNPROCESSED_STATES = ("received", "processing", "retryable")

_STRIPE_ID = re.compile(r"^[a-z]+_[A-Za-z0-9]{1,250}$")
_TOKEN = re.compile(r"^[a-z][a-z0-9_.]{0,119}$")
_CURRENCY = re.compile(r"^[a-z]{3}$")
_API_VERSION = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}(\.[a-z]+)?$")


class InboxInvariantError(ValueError):
    """Raised before a write that would violate the inbox contract."""


class StaleClaimError(InboxInvariantError):
    """Raised when a worker's claim token or lease is no longer current."""


def _utcnow():
    return datetime.now(timezone.utc)


def _stripe_id(value):
    if isinstance(value, dict):
        value = value.get("id")
    if isinstance(value, str) and _STRIPE_ID.match(value):
        return value
    return None


def minimize_stripe_event(raw_body: bytes, event: dict) -> dict:
    """Return only the inbox fields allowed by the data-minimization policy.

    ``raw_body`` must be the exact signed request body; only its digest is kept.
    """
    if not isinstance(raw_body, (bytes, bytearray)) or not raw_body:
        raise InboxInvariantError("raw_body must be the verified request bytes")
    if not isinstance(event, dict):
        raise InboxInvariantError("event must be a parsed JSON object")
    event_id = _stripe_id(event.get("id"))
    event_type = event.get("type")
    data_object = (event.get("data") or {}).get("object")
    if not event_id or not event_id.startswith("evt_"):
        raise InboxInvariantError("event id must be a Stripe event id")
    if not isinstance(event_type, str) or not _TOKEN.match(event_type):
        raise InboxInvariantError("event type is invalid")
    if not isinstance(data_object, dict):
        raise InboxInvariantError("event data.object is required")
    object_type = data_object.get("object")
    object_id = _stripe_id(data_object.get("id"))
    if not isinstance(object_type, str) or not _TOKEN.match(object_type) or not object_id:
        raise InboxInvariantError("event object identity is invalid")
    created = event.get("created")
    if isinstance(created, bool) or not isinstance(created, int) or created <= 0:
        raise InboxInvariantError("event created time is invalid")
    livemode = event.get("livemode")
    if not isinstance(livemode, bool):
        raise InboxInvariantError("event livemode must be boolean")

    summary = {"schema_version": SUMMARY_SCHEMA_VERSION}
    api_version = event.get("api_version")
    if isinstance(api_version, str) and _API_VERSION.match(api_version):
        summary["api_version"] = api_version
    status = data_object.get("status")
    if isinstance(status, str) and _TOKEN.match(status):
        summary["status"] = status
    currency = data_object.get("currency")
    if isinstance(currency, str) and _CURRENCY.match(currency):
        summary["currency"] = currency
    for field in AMOUNT_FIELDS:
        value = data_object.get(field)
        if isinstance(value, int) and not isinstance(value, bool):
            summary[field] = value
    for field in REFERENCE_FIELDS:
        reference = _stripe_id(data_object.get(field))
        if reference:
            summary[field] = reference
    if object_type in REFERENCE_FIELDS:
        summary[object_type] = object_id

    return {
        "provider": PROVIDER,
        "event_id": event_id,
        "event_type": event_type,
        "object_type": object_type,
        "object_id": object_id,
        "payload_digest": hashlib.sha256(bytes(raw_body)).hexdigest(),
        "summary_json": summary,
        "livemode": livemode,
        "provider_created_at": datetime.fromtimestamp(created, tz=timezone.utc),
    }


def _locked_event(session, provider, event_id):
    return session.execute(
        select(ExternalEventInbox)
        .where(ExternalEventInbox.provider == provider, ExternalEventInbox.event_id == event_id)
        .with_for_update()
    ).scalar_one_or_none()


def _reload(session, event_pk):
    return session.execute(
        select(ExternalEventInbox)
        .where(ExternalEventInbox.id == event_pk)
        .execution_options(populate_existing=True)
    ).scalar_one()


def record_event(session, raw_body: bytes, event: dict, *, now=None):
    """Record a verified event once.

    Returns ``(row, outcome)`` where outcome is ``inserted``, ``duplicate``, or
    ``digest_conflict``. A same-ID event with a different digest is never
    stored as the event. Each distinct conflicting digest is appended once to
    ``external_event_inbox_conflicts``, and an unprocessed event (received,
    processing, or retryable) is quarantined. Processed and already
    quarantined events keep their state.
    """
    now = now or _utcnow()
    fields = minimize_stripe_event(raw_body, event)
    _begin_serialized_sqlite_write(session)
    existing = _locked_event(session, fields["provider"], fields["event_id"])
    if existing is None:
        row = ExternalEventInbox(id=str(uuid.uuid4()), received_at=now, **fields)
        try:
            with session.begin_nested():
                session.add(row)
                session.flush()
            return row, "inserted"
        except IntegrityError:
            # A concurrent receiver inserted the same event first.
            existing = _locked_event(session, fields["provider"], fields["event_id"])
            if existing is None:
                raise
    if existing.payload_digest == fields["payload_digest"]:
        return existing, "duplicate"

    already_recorded = session.execute(
        select(ExternalEventInboxConflict.id).where(
            ExternalEventInboxConflict.inbox_event_id == existing.id,
            ExternalEventInboxConflict.conflicting_digest == fields["payload_digest"],
        )
    ).scalar_one_or_none()
    if already_recorded is None:
        try:
            with session.begin_nested():
                session.add(ExternalEventInboxConflict(
                    id=str(uuid.uuid4()), inbox_event_id=existing.id,
                    conflicting_digest=fields["payload_digest"],
                    state_at_detection=existing.state, detected_at=now,
                ))
                session.flush()
        except IntegrityError:
            pass  # The same conflicting digest was recorded concurrently.
    session.execute(
        update(ExternalEventInbox)
        .where(
            ExternalEventInbox.id == existing.id,
            ExternalEventInbox.state.in_(UNPROCESSED_STATES),
        )
        .values(
            state="quarantined", error_code=DIGEST_CONFLICT_ERROR,
            lease_expires_at=None, next_attempt_at=None,
        )
        .execution_options(synchronize_session=False)
    )
    return _reload(session, existing.id), "digest_conflict"


def claim_next_event(session, *, now=None, lease_seconds=LEASE_SECONDS):
    """Claim one available event with ``FOR UPDATE SKIP LOCKED``.

    Available means received, retryable and due, or processing with an expired
    lease. Returns the claimed row (its ``attempt_count`` is the claim token)
    or ``None``.
    """
    now = now or _utcnow()
    _begin_serialized_sqlite_write(session)
    inbox = ExternalEventInbox
    row = session.execute(
        select(inbox)
        .where(or_(
            inbox.state == "received",
            and_(inbox.state == "retryable", inbox.next_attempt_at <= now),
            and_(inbox.state == "processing", inbox.lease_expires_at <= now),
        ))
        .order_by(inbox.received_at, inbox.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if row is None:
        return None
    row.state = "processing"
    row.attempt_count = int(row.attempt_count or 0) + 1
    row.next_attempt_at = None
    row.lease_expires_at = now + timedelta(seconds=lease_seconds)
    session.flush()
    return row


def _fenced_update(session, event_pk, claim_token, now, values):
    """Apply a worker transition only for the current, unexpired claim."""
    if isinstance(claim_token, bool) or not isinstance(claim_token, int) or claim_token < 1:
        raise InboxInvariantError("a positive integer claim token is required")
    inbox = ExternalEventInbox
    result = session.execute(
        update(inbox)
        .where(
            inbox.id == event_pk,
            inbox.state == "processing",
            inbox.attempt_count == claim_token,
            inbox.lease_expires_at > now,
        )
        .values(lease_expires_at=None, **values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise StaleClaimError("claim is no longer current: lease expired, reclaimed, or completed")
    return _reload(session, event_pk)


def mark_processed(session, event_pk, claim_token, *, now=None):
    now = now or _utcnow()
    return _fenced_update(session, event_pk, claim_token, now, {
        "state": "processed", "processed_at": now,
    })


def retry_delay_seconds(attempt_count: int) -> int:
    exponent = max(0, int(attempt_count) - 1)
    return min(MAX_RETRY_SECONDS, BASE_RETRY_SECONDS * (2 ** min(exponent, 20)))


def _bounded_error(error_code):
    if not isinstance(error_code, str) or not error_code or len(error_code) > 120:
        raise InboxInvariantError("a bounded error code is required")


def mark_retryable(session, event_pk, claim_token, error_code: str, *, now=None):
    """Schedule a retry, or quarantine once MAX_ATTEMPTS is reached."""
    _bounded_error(error_code)
    now = now or _utcnow()
    if int(claim_token) >= MAX_ATTEMPTS:
        values = {"state": "quarantined", "error_code": "retry_exhausted", "next_attempt_at": None}
    else:
        values = {
            "state": "retryable", "error_code": error_code,
            "next_attempt_at": now + timedelta(seconds=retry_delay_seconds(claim_token)),
        }
    return _fenced_update(session, event_pk, claim_token, now, values)


def mark_quarantined(session, event_pk, error_code: str, *, claim_token=None, now=None):
    """Quarantine an event.

    A worker holding a claim passes its ``claim_token``. Without a token only a
    received or retryable event can be quarantined (operator action).
    """
    _bounded_error(error_code)
    now = now or _utcnow()
    if claim_token is not None:
        return _fenced_update(session, event_pk, claim_token, now, {
            "state": "quarantined", "error_code": error_code, "next_attempt_at": None,
        })
    result = session.execute(
        update(ExternalEventInbox)
        .where(ExternalEventInbox.id == event_pk, ExternalEventInbox.state.in_(("received", "retryable")))
        .values(state="quarantined", error_code=error_code, next_attempt_at=None)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise InboxInvariantError("only received or retryable events can be quarantined without a claim")
    return _reload(session, event_pk)


def requeue_quarantined(session, event_pk, *, now=None):
    """Operator action after investigation: make a quarantined event retryable."""
    result = session.execute(
        update(ExternalEventInbox)
        .where(ExternalEventInbox.id == event_pk, ExternalEventInbox.state == "quarantined")
        .values(state="retryable", next_attempt_at=now or _utcnow())
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise InboxInvariantError("only quarantined events can be requeued")
    return _reload(session, event_pk)


def purge_expired_events(session, *, now=None, batch_size=500):
    """Delete processed, conflict-free events older than RETENTION_DAYS.

    Financial transaction evidence pins its source inbox event; those rows are
    skipped so one retained fact cannot abort a batch of otherwise eligible
    transport records.

    Not scheduled; running it requires separate authorization. The database
    rejects any delete outside this rule, so a caller-supplied ``now`` in the
    future cannot shorten retention.
    """
    now = now or _utcnow()
    cutoff = now - timedelta(days=RETENTION_DAYS)
    _begin_serialized_sqlite_write(session)
    inbox = ExternalEventInbox
    conflict = ExternalEventInboxConflict
    statement = select(inbox).where(
        inbox.state == "processed",
        inbox.processed_at <= cutoff,
        ~exists().where(conflict.inbox_event_id == inbox.id),
    )
    if inspect(session.connection()).has_table("financial_transactions"):
        financial_transactions = table(
            "financial_transactions", column("inbox_event_id")
        )
        statement = statement.where(
            ~exists().where(financial_transactions.c.inbox_event_id == inbox.id)
        )
    rows = session.execute(
        statement.order_by(inbox.processed_at, inbox.id)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    ).scalars().all()
    for row in rows:
        session.delete(row)
    session.flush()
    return len(rows)
