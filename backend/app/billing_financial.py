"""Inactive Phase 5.2 financial transaction recorder.

This module is deliberately disconnected from Stripe routes, browser
confirmations, jobs, entitlements, and the credit ledger. It records immutable
money facts and their exact source-attributed line evidence only.
"""

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.exc import IntegrityError

from .billing_ledger import _begin_serialized_sqlite_write
from .models_billing_phase5 import (
    FINANCIAL_LINE_KINDS,
    FINANCIAL_TRANSACTION_KINDS,
    FinancialLine,
    FinancialTransaction,
)


_CURRENCY = re.compile(r"^[a-z]{3}$")
_HEADER_FIELDS = {
    "billing_account_id", "kind", "provider", "object_type", "object_id",
    "external_version", "effective_at", "currency", "principal_minor",
    "tax_minor", "fee_minor", "discount_minor", "gross_minor", "inbox_event_id",
}
_LINE_FIELDS = {
    "external_line_id", "line_kind", "source_type", "source_id", "quantity",
    "currency", "principal_minor", "tax_minor", "fee_minor", "discount_minor",
    "subscription_id", "entitlement_instance_id",
}
_MONEY_FIELDS = (
    "principal_minor", "tax_minor", "fee_minor", "discount_minor",
)


class FinancialInvariantError(ValueError):
    """Raised when proposed immutable financial evidence is incomplete or inconsistent."""


class FinancialIdentityConflictError(FinancialInvariantError):
    """Raised when one business version is reused with different financial evidence."""


def _required_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise FinancialInvariantError(f"{field} must be a nonempty string")
    return value.strip()


def _integer(value, field, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, int):
        raise FinancialInvariantError(f"{field} must use integer minor units")
    if positive and value <= 0:
        raise FinancialInvariantError(f"{field} must be positive")
    return value


def _utc_datetime(value, field):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise FinancialInvariantError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _normalize_header(header):
    if not isinstance(header, dict):
        raise FinancialInvariantError("transaction header must be an object")
    unknown = set(header) - _HEADER_FIELDS
    missing = _HEADER_FIELDS - set(header)
    if unknown or missing:
        raise FinancialInvariantError(
            f"transaction header fields mismatch: missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    normalized = dict(header)
    for field in (
        "billing_account_id", "provider", "object_type", "object_id", "external_version",
    ):
        normalized[field] = _required_text(normalized[field], field)
    if normalized["kind"] not in FINANCIAL_TRANSACTION_KINDS:
        raise FinancialInvariantError("unsupported financial transaction kind")
    if not _CURRENCY.fullmatch(str(normalized["currency"] or "")):
        raise FinancialInvariantError("currency must be a lowercase ISO-style code")
    normalized["effective_at"] = _utc_datetime(normalized["effective_at"], "effective_at")
    for field in (*_MONEY_FIELDS, "gross_minor"):
        normalized[field] = _integer(normalized[field], field)
    if normalized["gross_minor"] != sum(normalized[field] for field in _MONEY_FIELDS):
        raise FinancialInvariantError("gross minor units must equal all signed components")
    if normalized["kind"] != "adjustment" and normalized["inbox_event_id"] is None:
        raise FinancialInvariantError("external financial facts require inbox evidence")
    if normalized["inbox_event_id"] is not None:
        normalized["inbox_event_id"] = _required_text(
            normalized["inbox_event_id"], "inbox_event_id"
        )
    return normalized


def _normalize_lines(lines, currency):
    if not isinstance(lines, (list, tuple)) or not lines:
        raise FinancialInvariantError("at least one financial line is required")
    normalized_lines = []
    identities = set()
    for raw in lines:
        if not isinstance(raw, dict):
            raise FinancialInvariantError("each financial line must be an object")
        unknown = set(raw) - _LINE_FIELDS
        missing = _LINE_FIELDS - set(raw)
        if unknown or missing:
            raise FinancialInvariantError(
                f"financial line fields mismatch: missing={sorted(missing)}, unknown={sorted(unknown)}"
            )
        line = dict(raw)
        for field in ("external_line_id", "source_type", "source_id"):
            line[field] = _required_text(line[field], field)
        if line["line_kind"] not in FINANCIAL_LINE_KINDS:
            raise FinancialInvariantError("unsupported financial line kind")
        line["quantity"] = _integer(line["quantity"], "quantity", positive=True)
        if line["currency"] != currency:
            raise FinancialInvariantError("line currency must match its transaction")
        for field in _MONEY_FIELDS:
            line[field] = _integer(line[field], field)
        for field in ("subscription_id", "entitlement_instance_id"):
            if line[field] is not None:
                line[field] = _required_text(line[field], field)
        identity = (line["external_line_id"], line["line_kind"])
        if identity in identities:
            raise FinancialInvariantError("financial line identity is duplicated")
        identities.add(identity)
        normalized_lines.append(line)
    return normalized_lines


def _validate_reconciliation(header, lines):
    actual = {field: sum(line[field] for line in lines) for field in _MONEY_FIELDS}
    expected = {field: header[field] for field in _MONEY_FIELDS}
    if actual != expected:
        raise FinancialInvariantError(
            f"transaction totals do not reconcile to lines: expected={expected}, actual={actual}"
        )


def _datetime_key(value):
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _header_matches(existing, header):
    for field in _HEADER_FIELDS - {"effective_at"}:
        if getattr(existing, field) != header[field]:
            return False
    return _datetime_key(existing.effective_at) == header["effective_at"]


def _line_key(line):
    return tuple(
        line[field] if isinstance(line, dict) else getattr(line, field)
        for field in sorted(_LINE_FIELDS)
    )


def _existing_matches(session, existing, header, lines):
    if not _header_matches(existing, header):
        return False
    stored = session.execute(
        select(FinancialLine).where(FinancialLine.financial_transaction_id == existing.id)
    ).scalars().all()
    stored_keys = [_line_key(line) for line in stored]
    proposed_keys = [_line_key(line) for line in lines]
    return sorted(stored_keys, key=repr) == sorted(proposed_keys, key=repr)


def _locked_business_version(session, header):
    return session.execute(
        select(FinancialTransaction).where(
            FinancialTransaction.provider == header["provider"],
            FinancialTransaction.object_type == header["object_type"],
            FinancialTransaction.object_id == header["object_id"],
            FinancialTransaction.kind == header["kind"],
            FinancialTransaction.external_version == header["external_version"],
        ).with_for_update()
    ).scalar_one_or_none()


def record_financial_transaction(session, header, lines):
    """Atomically record one immutable business version and its exact lines.

    Returns ``(transaction, 'inserted'|'duplicate')``. Reuse of the business
    identity with different header or line evidence is an integrity conflict.
    PostgreSQL also verifies reconciliation with a deferred constraint trigger;
    this shared validation provides equivalent SQLite outcomes.
    """
    header = _normalize_header(header)
    lines = _normalize_lines(lines, header["currency"])
    _validate_reconciliation(header, lines)
    _begin_serialized_sqlite_write(session)

    existing = _locked_business_version(session, header)
    if existing is not None:
        if _existing_matches(session, existing, header, lines):
            return existing, "duplicate"
        raise FinancialIdentityConflictError(
            "financial business identity was reused with different immutable evidence"
        )

    transaction = FinancialTransaction(id=str(uuid.uuid4()), **header)
    if session.get_bind().dialect.name == "postgresql":
        inserted_id = session.execute(
            postgresql_insert(FinancialTransaction)
            .values(id=transaction.id, **header)
            .on_conflict_do_nothing(constraint="uq_financial_transactions_business_version")
            .returning(FinancialTransaction.id)
        ).scalar_one_or_none()
        if inserted_id is None:
            existing = _locked_business_version(session, header)
            if existing is not None and _existing_matches(session, existing, header, lines):
                return existing, "duplicate"
            raise FinancialIdentityConflictError(
                "financial business identity was concurrently reused with different evidence"
            )
        transaction = session.get(FinancialTransaction, inserted_id)
        for line in lines:
            session.add(FinancialLine(
                id=str(uuid.uuid4()), financial_transaction_id=inserted_id, **line
            ))
        session.flush()
        return transaction, "inserted"

    try:
        with session.begin_nested():
            session.add(transaction)
            session.flush()
            for line in lines:
                session.add(FinancialLine(
                    id=str(uuid.uuid4()), financial_transaction_id=transaction.id, **line
                ))
            session.flush()
    except IntegrityError:
        existing = _locked_business_version(session, header)
        if existing is None:
            raise
        if _existing_matches(session, existing, header, lines):
            return existing, "duplicate"
        raise FinancialIdentityConflictError(
            "financial business identity was concurrently reused with different evidence"
        )
    return transaction, "inserted"
