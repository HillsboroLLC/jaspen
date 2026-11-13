"""Inactive Phase 5.4 domain-event and communication-outbox foundation.

No route, webhook, scheduler, or delivery worker imports this module. Callers
must record a business transition, its domain event, and its outbox obligations
in the same caller-owned transaction.
"""

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .billing_ledger import _begin_serialized_sqlite_write
from .models_billing_phase5 import (
    CommunicationOutbox,
    CommunicationOutboxAttempt,
    DomainEvent,
)


_EVENT_FIELDS = {
    "billing_account_id", "event_key", "event_type", "aggregate_type",
    "aggregate_id", "occurred_at", "reference_ids",
}
_DELIVERY_FIELDS = {"template_key", "template_version", "channel", "locale"}


class BillingOutboxInvariantError(ValueError):
    """Raised when an event or delivery violates the outbox contract."""


class DomainEventConflictError(BillingOutboxInvariantError):
    """Raised when an event key is reused for different committed facts."""


class OutboxAttemptConflictError(BillingOutboxInvariantError):
    """Raised when an attempt result is replayed with different evidence."""


class OutboxConcurrentUpdateError(BillingOutboxInvariantError):
    """Raised when a concurrent event insert requires a transaction retry."""


class StaleOutboxClaimError(BillingOutboxInvariantError):
    """Raised when an attempt result uses an expired or superseded claim."""


def _text(value, field, maximum):
    if not isinstance(value, str) or not value.strip():
        raise BillingOutboxInvariantError(f"{field} must be a nonempty string")
    value = value.strip()
    if len(value) > maximum:
        raise BillingOutboxInvariantError(f"{field} is too long")
    return value


def _utc_datetime(value, field):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise BillingOutboxInvariantError(f"{field} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _stored_utc_datetime(value):
    """SQLite stores timezone-aware SQLAlchemy datetimes without the UTC offset."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _sha256(value):
    canonical = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalize_event(event):
    if not isinstance(event, dict):
        raise BillingOutboxInvariantError("domain event must be an object")
    unknown = set(event) - _EVENT_FIELDS
    missing = _EVENT_FIELDS - set(event)
    if unknown or missing:
        raise BillingOutboxInvariantError(
            f"domain event fields mismatch: missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    references = event["reference_ids"]
    if not isinstance(references, (list, tuple)) or any(
        not isinstance(reference, str) or not reference.strip()
        for reference in references
    ):
        raise BillingOutboxInvariantError("reference_ids must contain nonempty identifiers")
    normalized_references = sorted({reference.strip() for reference in references})
    if len(normalized_references) != len(references):
        raise BillingOutboxInvariantError("reference_ids must not contain duplicates")
    return {
        "billing_account_id": _text(event["billing_account_id"], "billing_account_id", 36),
        "event_key": _text(event["event_key"], "event_key", 255),
        "event_type": _text(event["event_type"], "event_type", 120),
        "aggregate_type": _text(event["aggregate_type"], "aggregate_type", 80),
        "aggregate_id": _text(event["aggregate_id"], "aggregate_id", 255),
        "occurred_at": _utc_datetime(event["occurred_at"], "occurred_at"),
        "reference_ids": normalized_references,
    }


def _normalize_deliveries(deliveries):
    if not isinstance(deliveries, (list, tuple)):
        raise BillingOutboxInvariantError("deliveries must be a list")
    normalized = []
    seen = set()
    for delivery in deliveries:
        if not isinstance(delivery, dict):
            raise BillingOutboxInvariantError("each delivery must be an object")
        unknown = set(delivery) - _DELIVERY_FIELDS
        missing = _DELIVERY_FIELDS - set(delivery)
        if unknown or missing:
            raise BillingOutboxInvariantError(
                f"delivery fields mismatch: missing={sorted(missing)}, unknown={sorted(unknown)}"
            )
        item = {
            "template_key": _text(delivery["template_key"], "template_key", 120),
            "template_version": _text(
                delivery["template_version"], "template_version", 64,
            ),
            "channel": _text(delivery["channel"], "channel", 40),
            "locale": _text(delivery["locale"], "locale", 35),
        }
        if ":" in item["template_version"] or ":" in item["channel"]:
            raise BillingOutboxInvariantError(
                "template_version and channel cannot contain the dedupe-key separator"
            )
        identity = (item["template_version"], item["channel"])
        if identity in seen:
            raise BillingOutboxInvariantError("delivery identity is duplicated")
        seen.add(identity)
        normalized.append(item)
    return sorted(
        normalized,
        key=lambda item: (
            item["template_version"], item["channel"],
            item["template_key"], item["locale"],
        ),
    )


def _request_fingerprint(event, deliveries):
    return _sha256({
        **event,
        "occurred_at": event["occurred_at"].isoformat(),
        "deliveries": deliveries,
    })


def _delivery_dedupe_key(event_id, template_version, account_id, channel):
    return f"message:{event_id}:{template_version}:{account_id}:{channel}"


def record_domain_event(session, proposed_event, proposed_deliveries=()):
    """Append an idempotent event and its account-scoped delivery obligations.

    The caller owns the transaction; this function never commits. The event's
    stable key and normalized envelope identify an exact replay. A changed
    event or delivery obligation under that key is a conflict.
    """
    event = _normalize_event(proposed_event)
    deliveries = _normalize_deliveries(proposed_deliveries)
    fingerprint = _request_fingerprint(event, deliveries)
    _begin_serialized_sqlite_write(session)

    event_id = str(uuid.uuid4())
    values = {
        "id": event_id,
        "billing_account_id": event["billing_account_id"],
        "event_key": event["event_key"],
        "event_type": event["event_type"],
        "aggregate_type": event["aggregate_type"],
        "aggregate_id": event["aggregate_id"],
        "occurred_at": event["occurred_at"],
        "reference_ids_json": event["reference_ids"],
        "request_fingerprint": fingerprint,
    }
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        statement = postgresql_insert(DomainEvent).values(**values)
    elif dialect == "sqlite":
        statement = sqlite_insert(DomainEvent).values(**values)
    else:
        raise BillingOutboxInvariantError(f"unsupported database dialect: {dialect}")
    inserted_id = session.execute(
        statement.on_conflict_do_nothing(
            index_elements=[DomainEvent.event_key],
        ).returning(DomainEvent.id)
    ).scalar_one_or_none()

    if inserted_id is None:
        existing = session.execute(
            select(DomainEvent)
            .where(DomainEvent.event_key == event["event_key"])
            .with_for_update()
        ).scalar_one_or_none()
        if existing is None:
            raise OutboxConcurrentUpdateError(
                "domain event creation raced under the current snapshot; retry the transaction"
            )
        if existing.request_fingerprint != fingerprint:
            raise DomainEventConflictError(
                "domain event key was reused with different event or delivery facts"
            )
        messages = session.execute(
            select(CommunicationOutbox)
            .where(CommunicationOutbox.domain_event_id == existing.id)
            .order_by(CommunicationOutbox.dedupe_key)
        ).scalars().all()
        expected_keys = sorted(
            _delivery_dedupe_key(
                existing.id, delivery["template_version"],
                event["billing_account_id"], delivery["channel"],
            )
            for delivery in deliveries
        )
        if [message.dedupe_key for message in messages] != expected_keys:
            raise BillingOutboxInvariantError(
                "domain event replay has mismatched atomic outbox obligations"
            )
        return existing, messages, "duplicate"

    domain_event = session.get(DomainEvent, inserted_id)
    if domain_event is None:
        raise BillingOutboxInvariantError("inserted domain event could not be reloaded")
    messages = [
        CommunicationOutbox(
            id=str(uuid.uuid4()),
            domain_event_id=domain_event.id,
            billing_account_id=event["billing_account_id"],
            template_key=delivery["template_key"],
            template_version=delivery["template_version"],
            channel=delivery["channel"],
            locale=delivery["locale"],
            dedupe_key=_delivery_dedupe_key(
                domain_event.id, delivery["template_version"],
                event["billing_account_id"], delivery["channel"],
            ),
        )
        for delivery in deliveries
    ]
    session.add_all(messages)
    session.flush()
    return domain_event, messages, "inserted"


def claim_next_outbox_message(session, *, now, lease_seconds):
    """Claim one due delivery obligation without invoking a transport."""
    now = _utc_datetime(now, "now")
    if (
        isinstance(lease_seconds, bool)
        or not isinstance(lease_seconds, int)
        or lease_seconds <= 0
    ):
        raise BillingOutboxInvariantError("lease_seconds must be a positive integer")
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        _begin_serialized_sqlite_write(session)
    elif dialect != "postgresql":
        raise BillingOutboxInvariantError(f"unsupported database dialect: {dialect}")

    due = or_(
        CommunicationOutbox.next_attempt_at.is_(None),
        CommunicationOutbox.next_attempt_at <= now,
    )
    eligible = or_(
        and_(
            CommunicationOutbox.state.in_(("pending", "retryable")),
            due,
        ),
        and_(
            CommunicationOutbox.state == "processing",
            CommunicationOutbox.lease_expires_at <= now,
        ),
    )
    statement = (
        select(CommunicationOutbox)
        .where(eligible)
        .order_by(CommunicationOutbox.created_at, CommunicationOutbox.id)
        .limit(1)
    )
    if dialect == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    outbox = session.execute(statement).scalar_one_or_none()
    if outbox is None:
        return None

    if outbox.state == "processing":
        expired = session.execute(
            select(CommunicationOutboxAttempt)
            .where(
                CommunicationOutboxAttempt.outbox_id == outbox.id,
                CommunicationOutboxAttempt.attempt_number == outbox.attempt_count,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if expired is None or expired.outcome != "started":
            raise BillingOutboxInvariantError(
                "expired outbox lease has no matching active attempt"
            )
        expired.completed_at = now
        expired.outcome = "retryable_failure"
        expired.error_code = "delivery_lease_expired"
        expired.result_fingerprint = _result_fingerprint(
            "retryable_failure", now, None, "delivery_lease_expired", None,
        )
        session.flush()
        session.refresh(outbox)

    attempt_number = outbox.attempt_count + 1
    attempt = CommunicationOutboxAttempt(
        id=str(uuid.uuid4()),
        outbox_id=outbox.id,
        attempt_number=attempt_number,
        started_at=now,
        lease_expires_at=now + timedelta(seconds=lease_seconds),
    )
    session.add(attempt)
    session.flush()
    session.refresh(outbox)
    return outbox, attempt_number


def _result_fingerprint(outcome, completed_at, provider_message_id, error_code, retry_at):
    return _sha256({
        "outcome": outcome,
        "completed_at": completed_at.isoformat(),
        "provider_message_id": provider_message_id,
        "error_code": error_code,
        "next_attempt_at": retry_at.isoformat() if retry_at else None,
    })


def record_outbox_attempt(
    session, outbox_id, attempt_number, *, outcome, completed_at,
    provider_message_id=None, error_code=None, next_attempt_at=None,
):
    """Record a delivery result; retries are caller-scheduled and transport-free."""
    completed_at = _utc_datetime(completed_at, "completed_at")
    outbox_id = _text(outbox_id, "outbox_id", 36)
    if (
        isinstance(attempt_number, bool)
        or not isinstance(attempt_number, int)
        or attempt_number <= 0
    ):
        raise BillingOutboxInvariantError("attempt_number must be a positive integer")
    if outcome not in {"delivered", "retryable_failure"}:
        raise BillingOutboxInvariantError("outcome must be delivered or retryable_failure")
    if provider_message_id is not None:
        provider_message_id = _text(provider_message_id, "provider_message_id", 255)
    if error_code is not None:
        error_code = _text(error_code, "error_code", 120)
    retry_at = (
        _utc_datetime(next_attempt_at, "next_attempt_at")
        if next_attempt_at is not None else None
    )
    if outcome == "delivered":
        if error_code is not None or retry_at is not None:
            raise BillingOutboxInvariantError(
                "delivered attempts cannot carry an error or retry time"
            )
    else:
        if error_code is None:
            raise BillingOutboxInvariantError("retryable failures require an error code")
        if retry_at is not None and retry_at < completed_at:
            raise BillingOutboxInvariantError(
                "next_attempt_at cannot precede the completed attempt"
            )

    fingerprint = _result_fingerprint(
        outcome, completed_at, provider_message_id, error_code, retry_at,
    )
    outbox = session.execute(
        select(CommunicationOutbox)
        .where(CommunicationOutbox.id == outbox_id)
        .with_for_update()
    ).scalar_one_or_none()
    if outbox is None:
        raise StaleOutboxClaimError("outbox message does not exist")
    attempt = session.execute(
        select(CommunicationOutboxAttempt)
        .where(
            CommunicationOutboxAttempt.outbox_id == outbox_id,
            CommunicationOutboxAttempt.attempt_number == attempt_number,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if attempt is None:
        raise StaleOutboxClaimError("outbox attempt does not exist")
    if attempt.outcome != "started":
        if attempt.result_fingerprint == fingerprint:
            return "duplicate"
        if attempt.error_code == "delivery_lease_expired":
            raise StaleOutboxClaimError("outbox attempt lease expired and was reclaimed")
        raise OutboxAttemptConflictError(
            "outbox attempt result was replayed with different evidence"
        )
    if (
        outbox.state != "processing"
        or outbox.attempt_count != attempt_number
        or outbox.lease_expires_at is None
        or completed_at >= _stored_utc_datetime(outbox.lease_expires_at)
    ):
        raise StaleOutboxClaimError("outbox attempt claim is stale")

    attempt.outcome = outcome
    attempt.completed_at = completed_at
    attempt.provider_message_id = provider_message_id
    attempt.error_code = error_code
    attempt.next_attempt_at = retry_at
    attempt.result_fingerprint = fingerprint
    session.flush()
    return "completed"
