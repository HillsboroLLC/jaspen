"""Inactive Phase 5.1 minimal-data external event inbox.

Nothing in live routes, webhooks, authentication, jobs, or readers imports this
module. A later, separately authorized increment will verify the Stripe
signature at the webhook boundary and then call ``record_event``.

Data minimization and retention policy (approved 2026-11-11; documented in
docs/specs/billing/phase-2-5-implementation-proposal.md, Phase 5.1):

* Stored: provider, event ID and type, referenced object type and ID, livemode,
  provider-created and received times, a SHA-256 digest of the verified raw
  payload, processing state/attempts/errors, digest-conflict evidence, and an
  allowlisted scalar summary (identifiers, amounts, currency, status).
* Never stored: the raw payload, payment-card details, billing details,
  customer names, emails, addresses, phone numbers, metadata, descriptions,
  or any nested object.
* Processed events may be deleted RETENTION_DAYS after processing. Received,
  processing, retryable, and quarantined events are never deleted by
  retention. The database enforces the same rule.
"""

import hashlib
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError

from .billing_ledger import _begin_serialized_sqlite_write
from .models_billing_phase5 import ExternalEventInbox

PROVIDER = "stripe"
SUMMARY_SCHEMA_VERSION = 1
RETENTION_DAYS = 400
LEASE_SECONDS = 300
MAX_ATTEMPTS = 10
BASE_RETRY_SECONDS = 60
MAX_RETRY_SECONDS = 6 * 60 * 60

AMOUNT_FIELDS = ("amount", "amount_due", "amount_paid", "amount_refunded")
REFERENCE_FIELDS = (
    "customer", "subscription", "invoice", "payment_intent", "charge",
    "refund", "dispute", "checkout_session",
)
SUMMARY_FIELDS = (
    "schema_version", "api_version", "status", "currency",
    *AMOUNT_FIELDS, *REFERENCE_FIELDS,
)

_STRIPE_ID = re.compile(r"^[a-z]+_[A-Za-z0-9]{1,250}$")
_TOKEN = re.compile(r"^[a-z][a-z0-9_.]{0,119}$")
_CURRENCY = re.compile(r"^[a-z]{3}$")
_API_VERSION = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}(\.[a-z]+)?$")


class InboxInvariantError(ValueError):
    """Raised before a write that would violate the inbox contract."""


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
    # The referenced object itself is identified by object_type/object_id; also
    # expose it under its own reference key when it is one of the known types.
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


def record_event(session, raw_body: bytes, event: dict, *, now=None):
    """Record a verified event once.

    Returns ``(row, outcome)`` where outcome is ``inserted``, ``duplicate``, or
    ``digest_conflict``. A same-ID event with a different digest is never
    stored; its digest is recorded as conflict evidence and an unprocessed event
    is quarantined for investigation.
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
    existing.digest_conflict_count = int(existing.digest_conflict_count or 0) + 1
    existing.last_conflict_digest = fields["payload_digest"]
    existing.last_conflict_at = now
    if existing.state in ("received", "retryable"):
        existing.state = "quarantined"
        existing.next_attempt_at = None
        existing.error_code = "digest_conflict"
    session.flush()
    return existing, "digest_conflict"


def _locked_event(session, provider, event_id):
    return session.execute(
        select(ExternalEventInbox)
        .where(ExternalEventInbox.provider == provider, ExternalEventInbox.event_id == event_id)
        .with_for_update()
    ).scalar_one_or_none()


def claim_next_event(session, *, now=None, lease_seconds=LEASE_SECONDS):
    """Claim one available event with ``FOR UPDATE SKIP LOCKED``.

    Available means received, retryable and due, or processing with an expired
    lease. Returns the claimed row or ``None``.
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


def _require_processing(row):
    if row.state != "processing":
        raise InboxInvariantError("event must be claimed before it is completed")


def mark_processed(session, row, *, now=None):
    _require_processing(row)
    row.state = "processed"
    row.processed_at = now or _utcnow()
    row.lease_expires_at = None
    session.flush()
    return row


def retry_delay_seconds(attempt_count: int) -> int:
    exponent = max(0, int(attempt_count) - 1)
    return min(MAX_RETRY_SECONDS, BASE_RETRY_SECONDS * (2 ** min(exponent, 20)))


def mark_retryable(session, row, error_code: str, *, now=None):
    """Schedule a retry, or quarantine once MAX_ATTEMPTS is reached."""
    _require_processing(row)
    if not error_code or len(error_code) > 120:
        raise InboxInvariantError("a bounded error code is required")
    now = now or _utcnow()
    row.lease_expires_at = None
    if int(row.attempt_count or 0) >= MAX_ATTEMPTS:
        row.state = "quarantined"
        row.error_code = "retry_exhausted"
        row.next_attempt_at = None
    else:
        row.state = "retryable"
        row.error_code = error_code
        row.next_attempt_at = now + timedelta(seconds=retry_delay_seconds(row.attempt_count))
    session.flush()
    return row


def mark_quarantined(session, row, error_code: str):
    if row.state not in ("processing", "received", "retryable"):
        raise InboxInvariantError("only unprocessed events can be quarantined")
    if not error_code or len(error_code) > 120:
        raise InboxInvariantError("a bounded error code is required")
    row.state = "quarantined"
    row.error_code = error_code
    row.lease_expires_at = None
    row.next_attempt_at = None
    session.flush()
    return row


def requeue_quarantined(session, row, *, now=None):
    """Operator action after investigation: make a quarantined event retryable."""
    if row.state != "quarantined":
        raise InboxInvariantError("only quarantined events can be requeued")
    row.state = "retryable"
    row.next_attempt_at = now or _utcnow()
    session.flush()
    return row


def purge_expired_events(session, *, now=None, batch_size=500):
    """Delete processed events older than RETENTION_DAYS. Returns the count.

    The database rejects any delete outside this rule, so a caller-supplied
    ``now`` in the future cannot shorten retention.
    """
    now = now or _utcnow()
    cutoff = now - timedelta(days=RETENTION_DAYS)
    _begin_serialized_sqlite_write(session)
    inbox = ExternalEventInbox
    rows = session.execute(
        select(inbox)
        .where(inbox.state == "processed", inbox.processed_at <= cutoff)
        .order_by(inbox.processed_at, inbox.id)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    ).scalars().all()
    for row in rows:
        session.delete(row)
    session.flush()
    return len(rows)
