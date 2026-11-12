"""Inactive refund and dispute case recorder for billing Phase 5.3."""

import hashlib
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import Numeric, cast, func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from .billing_ledger import _begin_serialized_sqlite_write
from .models_billing_phase5 import (
    ExternalEventInbox,
    ExternalEventInboxConflict,
    FinancialCase,
    FinancialCaseEvent,
    FinancialCaseEventLine,
    FinancialLine,
    FinancialTransaction,
)


_CASE_FIELDS = {
    "billing_account_id", "provider", "case_type", "case_object_id",
    "source_financial_transaction_id", "financial_transaction_id", "state",
    "disposition", "cumulative_principal_minor", "line_allocations",
}
_ALLOCATION_FIELDS = {"financial_line_id", "attributed_principal_minor"}
_REFUND_STATES = {"refund_recorded", "financial_only", "entitlement_reducing_review"}
_DISPUTE_STATES = {"opened", "pending", "won", "lost"}
_DISPOSITIONS = {"financial_only", "entitlement_reducing_review"}
_INELIGIBLE_LINE_KINDS = {"tax", "fee", "discount"}


class FinancialCaseInvariantError(ValueError):
    """Raised when proposed case evidence violates its financial contract."""


class FinancialCaseIdentityConflictError(FinancialCaseInvariantError):
    """Raised when a provider version is reused with different case evidence."""


class FinancialCaseConcurrentUpdateError(FinancialCaseInvariantError):
    """Raised when a transaction must be retried after a concurrent case insert."""


def _required_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise FinancialCaseInvariantError(f"{field} must be a nonempty string")
    return value.strip()


def _integer(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise FinancialCaseInvariantError(f"{field} must be a nonnegative integer minor-unit amount")
    return value


def _utc_datetime(value, field):
    if not isinstance(value, datetime):
        raise FinancialCaseInvariantError(f"{field} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _time_key(value):
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_case(case):
    if not isinstance(case, dict):
        raise FinancialCaseInvariantError("financial case must be an object")
    unknown = set(case) - _CASE_FIELDS
    missing = _CASE_FIELDS - set(case)
    if unknown or missing:
        raise FinancialCaseInvariantError(
            f"financial case fields mismatch: missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    normalized = dict(case)
    for field in (
        "billing_account_id", "provider", "case_type", "case_object_id",
        "source_financial_transaction_id", "financial_transaction_id", "state",
    ):
        normalized[field] = _required_text(normalized[field], field)
    if normalized["case_type"] not in {"refund", "dispute"}:
        raise FinancialCaseInvariantError("case_type must be refund or dispute")
    supported_states = _REFUND_STATES if normalized["case_type"] == "refund" else _DISPUTE_STATES
    if normalized["state"] not in supported_states:
        raise FinancialCaseInvariantError("case state is not owned by Phase 5.3")
    disposition = normalized["disposition"]
    if disposition is not None and disposition not in _DISPOSITIONS:
        raise FinancialCaseInvariantError("unsupported financial case disposition")
    if normalized["case_type"] == "dispute" and disposition is not None:
        raise FinancialCaseInvariantError("dispute cases do not have refund dispositions")
    normalized["cumulative_principal_minor"] = _integer(
        normalized["cumulative_principal_minor"], "cumulative_principal_minor"
    )
    allocations = normalized["line_allocations"]
    if not isinstance(allocations, (list, tuple)):
        raise FinancialCaseInvariantError("line_allocations must be a list")
    normalized_allocations = []
    seen_lines = set()
    for raw in allocations:
        if not isinstance(raw, dict):
            raise FinancialCaseInvariantError("each line allocation must be an object")
        unknown = set(raw) - _ALLOCATION_FIELDS
        missing = _ALLOCATION_FIELDS - set(raw)
        if unknown or missing:
            raise FinancialCaseInvariantError(
                f"line allocation fields mismatch: missing={sorted(missing)}, unknown={sorted(unknown)}"
            )
        line_id = _required_text(raw["financial_line_id"], "financial_line_id")
        amount = _integer(raw["attributed_principal_minor"], "attributed_principal_minor")
        if line_id in seen_lines:
            raise FinancialCaseInvariantError("financial line attribution is duplicated")
        seen_lines.add(line_id)
        normalized_allocations.append({
            "financial_line_id": line_id,
            "attributed_principal_minor": amount,
        })
    normalized_allocations.sort(key=lambda allocation: allocation["financial_line_id"])
    if sum(line["attributed_principal_minor"] for line in normalized_allocations) != normalized[
        "cumulative_principal_minor"
    ]:
        raise FinancialCaseInvariantError(
            "line attribution must equal the cumulative case principal"
        )
    normalized["line_allocations"] = normalized_allocations
    return normalized


def _fingerprint(case):
    encoded = json.dumps(case, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _case_matches(case_row, case):
    return all(
        getattr(case_row, field) == case[field]
        for field in (
            "billing_account_id", "provider", "case_type", "case_object_id",
            "source_financial_transaction_id",
        )
    )


def _transition_allowed(existing, case):
    if existing is None:
        return True
    if existing.case_type == "refund":
        allowed = (
            case["state"] == existing.state
            or (
                existing.state == "refund_recorded"
                and case["state"] in {"financial_only", "entitlement_reducing_review"}
            )
        )
    else:
        allowed = (
            case["state"] == existing.state
            or (existing.state == "opened" and case["state"] in {"pending", "won", "lost"})
            or (existing.state == "pending" and case["state"] in {"won", "lost"})
            or (
                existing.state in {"won", "lost"}
                and case["state"] in _DISPUTE_STATES
            )
        )
    if not allowed:
        raise FinancialCaseInvariantError(
            f"invalid {existing.case_type} state transition: {existing.state} -> {case['state']}"
        )
    if existing.disposition is not None and case["disposition"] != existing.disposition:
        raise FinancialCaseInvariantError("financial case disposition cannot be changed")


def _validate_sources(session, case):
    source = session.get(FinancialTransaction, case["source_financial_transaction_id"])
    event_transaction = session.get(FinancialTransaction, case["financial_transaction_id"])
    if source is None or event_transaction is None:
        raise FinancialCaseInvariantError("source and event financial transactions are required")
    if (
        source.billing_account_id != case["billing_account_id"]
        or source.provider != case["provider"]
        or source.kind not in {"invoice", "payment"}
    ):
        raise FinancialCaseInvariantError("source transaction does not belong to this billing case")
    if (
        event_transaction.billing_account_id != case["billing_account_id"]
        or event_transaction.provider != case["provider"]
        or event_transaction.kind != case["case_type"]
        or event_transaction.object_type != case["case_type"]
        or event_transaction.object_id != case["case_object_id"]
        or not event_transaction.inbox_event_id
        or event_transaction.currency != source.currency
    ):
        raise FinancialCaseInvariantError(
            "event transaction does not match the billing case and source currency"
        )
    if case["cumulative_principal_minor"] > abs(source.principal_minor):
        raise FinancialCaseInvariantError("case principal exceeds its source transaction")
    if event_transaction.principal_minor != -case["cumulative_principal_minor"]:
        raise FinancialCaseInvariantError(
            "case cumulative principal must equal the signed financial transaction version"
        )
    inbox_event = session.execute(
        select(ExternalEventInbox)
        .where(ExternalEventInbox.id == event_transaction.inbox_event_id)
        .with_for_update()
    ).scalar_one_or_none()
    if (
        inbox_event is None
        or inbox_event.provider != case["provider"]
        or inbox_event.object_type != case["case_type"]
        or inbox_event.object_id != case["case_object_id"]
        or inbox_event.state not in {"processing", "processed"}
    ):
        raise FinancialCaseInvariantError("case event requires compatible inbox evidence")
    has_conflict = session.execute(
        select(ExternalEventInboxConflict.id).where(
            ExternalEventInboxConflict.inbox_event_id == inbox_event.id
        ).limit(1)
    ).scalar_one_or_none()
    if has_conflict is not None:
        raise FinancialCaseInvariantError("conflicted inbox evidence cannot support a financial case")
    if not event_transaction.effective_at or not inbox_event.received_at:
        raise FinancialCaseInvariantError("case event requires effective and received timestamps")
    source_lines = session.execute(
        select(FinancialLine).where(
            FinancialLine.financial_transaction_id == source.id
        )
    ).scalars().all()
    source_lines_by_id = {line.id: line for line in source_lines}
    for allocation in case["line_allocations"]:
        line = source_lines_by_id.get(allocation["financial_line_id"])
        if line is None or line.line_kind in _INELIGIBLE_LINE_KINDS:
            raise FinancialCaseInvariantError("case attribution must reference an eligible source line")
        maximum = max(0, line.principal_minor + line.discount_minor)
        if allocation["attributed_principal_minor"] > maximum:
            raise FinancialCaseInvariantError("case attribution exceeds source-line principal")
    if case["case_type"] == "refund":
        includes_subscription = any(
            source_lines_by_id[allocation["financial_line_id"]].line_kind == "subscription"
            for allocation in case["line_allocations"]
        )
        if includes_subscription and case["disposition"] is None:
            raise FinancialCaseInvariantError(
                "subscription refund evidence requires an explicit disposition"
            )
        if case["state"] == "financial_only" and case["disposition"] != "financial_only":
            raise FinancialCaseInvariantError("financial_only state requires its matching disposition")
        if case["state"] == "entitlement_reducing_review" and case["disposition"] != (
            "entitlement_reducing_review"
        ):
            raise FinancialCaseInvariantError(
                "entitlement review state requires its matching disposition"
            )
    return source, event_transaction, inbox_event, source_lines_by_id


def _validate_aggregate_attribution(session, case, source_lines_by_id, current_case):
    for allocation in case["line_allocations"]:
        line_id = allocation["financial_line_id"]
        current_amount = session.execute(
            select(func.coalesce(
                func.sum(cast(
                    FinancialCaseEventLine.attributed_principal_minor,
                    Numeric(38, 0),
                )),
                0,
            ))
            .select_from(FinancialCaseEventLine)
            .join(
                FinancialCase,
                FinancialCase.current_event_id
                == FinancialCaseEventLine.financial_case_event_id,
            )
            .where(FinancialCaseEventLine.financial_line_id == line_id)
            .where(
                FinancialCase.id != current_case.id
                if current_case is not None
                else True
            )
        ).scalar_one()
        proposed_total = current_amount + allocation["attributed_principal_minor"]
        source_line = source_lines_by_id[line_id]
        source_limit = max(0, source_line.principal_minor + source_line.discount_minor)
        if proposed_total > source_limit:
            raise FinancialCaseInvariantError(
                "current case attributions exceed eligible source-line principal"
            )


def _event_matches(existing_event, case, fingerprint):
    return (
        existing_event.event_fingerprint == fingerprint
        and existing_event.state == case["state"]
        and existing_event.disposition == case["disposition"]
        and existing_event.cumulative_principal_minor == case["cumulative_principal_minor"]
    )


def record_financial_case_event(session, proposed_case):
    """Atomically append a case version and advance its cumulative projection.

    Returns ``(case, event_or_none, 'inserted'|'duplicate'|'stale')``. The caller
    owns the surrounding transaction and inbox processing state.
    """
    case = _normalize_case(proposed_case)
    _begin_serialized_sqlite_write(session)
    session.flush()
    source, event_transaction, inbox_event, source_lines_by_id = _validate_sources(session, case)
    effective_at = _utc_datetime(event_transaction.effective_at, "effective_at")
    received_at = _utc_datetime(inbox_event.received_at, "received_at")
    fingerprint = _fingerprint(case)

    existing = session.execute(
        select(FinancialCase).where(
            FinancialCase.provider == case["provider"],
            FinancialCase.case_type == case["case_type"],
            FinancialCase.case_object_id == case["case_object_id"],
            FinancialCase.source_financial_transaction_id
            == case["source_financial_transaction_id"],
        ).with_for_update()
    ).scalar_one_or_none()
    is_new_case = False
    current_event_id = None
    if existing is not None and not _case_matches(existing, case):
        raise FinancialCaseIdentityConflictError("financial case identity conflicts with existing evidence")

    if existing is None and session.get_bind().dialect.name == "postgresql":
        case_id = str(uuid.uuid4())
        current_event_id = str(uuid.uuid4())
        inserted_id = session.execute(
            postgresql_insert(FinancialCase)
            .values(
                id=case_id,
                billing_account_id=case["billing_account_id"],
                provider=case["provider"],
                case_type=case["case_type"],
                case_object_id=case["case_object_id"],
                source_financial_transaction_id=case["source_financial_transaction_id"],
                state=case["state"],
                disposition=case["disposition"],
                cumulative_principal_minor=case["cumulative_principal_minor"],
                current_external_version=event_transaction.external_version,
                current_event_id=current_event_id,
                current_effective_at=effective_at,
                current_received_at=received_at,
            )
            .on_conflict_do_nothing(constraint="uq_financial_cases_provider_object_source")
            .returning(FinancialCase.id)
        ).scalar_one_or_none()
        if inserted_id is None:
            existing = session.execute(
                select(FinancialCase).where(
                    FinancialCase.provider == case["provider"],
                    FinancialCase.case_type == case["case_type"],
                    FinancialCase.case_object_id == case["case_object_id"],
                    FinancialCase.source_financial_transaction_id
                    == case["source_financial_transaction_id"],
                ).with_for_update()
            ).scalar_one_or_none()
            if existing is None:
                raise FinancialCaseConcurrentUpdateError(
                    "financial case creation raced under the current snapshot; retry the transaction"
                )
            if not _case_matches(existing, case):
                raise FinancialCaseIdentityConflictError(
                    "financial case identity conflicts with existing evidence"
                )
        else:
            existing = session.get(FinancialCase, inserted_id)
            is_new_case = True
            session.flush()

    if existing is not None and not is_new_case:
        existing_event = session.execute(
            select(FinancialCaseEvent).where(
                FinancialCaseEvent.financial_case_id == existing.id,
                FinancialCaseEvent.external_version == event_transaction.external_version,
            )
        ).scalar_one_or_none()
        if existing_event is not None:
            if _event_matches(existing_event, case, fingerprint):
                return existing, existing_event, "duplicate"
            raise FinancialCaseIdentityConflictError(
                "financial case version was reused with different evidence"
            )
        if (_time_key(effective_at), _time_key(received_at)) <= (
            _time_key(existing.current_effective_at),
            _time_key(existing.current_received_at),
        ):
            return existing, None, "stale"
        _transition_allowed(existing, case)

    _validate_aggregate_attribution(session, case, source_lines_by_id, existing)

    if existing is None:
        case_id = str(uuid.uuid4())
        current_event_id = str(uuid.uuid4())
        existing = FinancialCase(
            id=case_id,
            billing_account_id=case["billing_account_id"],
            provider=case["provider"],
            case_type=case["case_type"],
            case_object_id=case["case_object_id"],
            source_financial_transaction_id=source.id,
            state=case["state"],
            disposition=case["disposition"],
            cumulative_principal_minor=case["cumulative_principal_minor"],
            current_external_version=event_transaction.external_version,
            current_event_id=current_event_id,
            current_effective_at=effective_at,
            current_received_at=received_at,
        )
        session.add(existing)
        session.flush()
        is_new_case = True
    elif not is_new_case:
        current_event_id = str(uuid.uuid4())

    event = FinancialCaseEvent(
        id=current_event_id,
        financial_case_id=existing.id,
        financial_transaction_id=event_transaction.id,
        inbox_event_id=inbox_event.id,
        external_version=event_transaction.external_version,
        event_fingerprint=fingerprint,
        state=case["state"],
        disposition=case["disposition"],
        cumulative_principal_minor=case["cumulative_principal_minor"],
        effective_at=effective_at,
        received_at=received_at,
    )
    session.add(event)
    session.flush()
    if existing.current_event_id != event.id:
        existing.state = case["state"]
        existing.disposition = case["disposition"]
        existing.cumulative_principal_minor = case["cumulative_principal_minor"]
        existing.current_external_version = event_transaction.external_version
        existing.current_event_id = event.id
        existing.current_effective_at = effective_at
        existing.current_received_at = received_at
        existing.updated_at = datetime.now(timezone.utc)
    session.flush()

    for allocation in case["line_allocations"]:
        session.add(FinancialCaseEventLine(
            financial_case_event_id=event.id,
            financial_line_id=allocation["financial_line_id"],
            attributed_principal_minor=allocation["attributed_principal_minor"],
        ))
    session.flush()
    return existing, event, "inserted"
