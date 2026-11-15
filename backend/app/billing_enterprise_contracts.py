"""Inactive Phase 11 Enterprise contract authority (P09; STOP-15).

Founder-approved directions (2026-11-15): P11-DEP-001 (annual term credit
carryforward), P11-DEP-002 (Stripe Invoicing is the Enterprise payment
pathway; no manual payment verification), P11-DEP-003
(``billing.enterprise_contract.manage``), and P11-DEP-004 option A (each paid
contract term is a contract-backed ``BillingSubscription``).

The contract is the commercial authority; it does not hold money or credits.
Every effect goes through an existing authority:

* Phase 4 entitlement definitions, instances, and transitions;
* Phase 6 recurring allocation (and so the Phase 3 ledger) for credits;
* Phase 5.2 financial transactions as the only payment evidence;
* Phase 8 seat commitments, with a ``contract`` origin;
* Phase 5.4 domain events and caller-supplied delivery obligations;
* Phase 10 staff permission grants for authority.

Only a named staff user holding an explicit, unrevoked
``billing.enterprise_contract.manage`` grant can record, approve, fund,
activate, renew, or close a contract. Global admin, organization admin, and
customer billing roles are never consulted. Command times come from the
database. No live route, webhook, scheduler, or worker imports this module;
callers own the transaction and nothing here commits.

Deliberately not implemented here (see the Phase 11 record): read-only access
enforcement, customer notices and their wording, data export, deletion,
reimport, per-member allowances, allocation amendments, contract exceptions
to the occupancy rule, and catch-up releases for a term activated late.
"""

import hashlib
import json
import uuid
from datetime import timedelta, timezone

from sqlalchemy import select

from .billing_allocations import (
    RecurringAllocationConflictError,
    RecurringAllocationError,
    RecurringAllocationRetryError,
    _claim_registry,
    _complete_registry_if_claimed,
    allocate_recurring_credits,
)
from .billing_entitlements import (
    EntitlementInvariantError,
    add_calendar_months,
    append_entitlement_transition,
    monthly_period_bounds,
    validate_definition_payloads,
)
from .billing_ledger import CreditLedgerInvariantError, lock_billing_account
from .billing_offers import (
    OfferIsolationError,
    _authorized_grant,
    _database_clock,
    _database_now,
    _require_read_committed,
)
from .billing_outbox import BillingOutboxInvariantError, DomainEventConflictError, record_domain_event
from .billing_seats import _replace_commitment, current_seat_commitment, seat_occupancy
from .models import (
    BillingSubscription,
    EntitlementDefinition,
    EntitlementInstance,
    ExternalEventInbox,
    FinancialLine,
    FinancialTransaction,
    Organization,
    SeatCommitment,
)
from .models_billing_phase11 import (
    CONTRACT_PERMISSION,
    CONTRACT_PROCESSOR,
    NONRENEWAL_NOTICE_DAYS,
    RENEWAL_GRACE_DAYS,
    RENEWAL_MODES,
    RETENTION_REVIEW_DAYS,
    TERM_INTERVALS,
    EnterpriseContract,
    EnterpriseContractActivation,
    EnterpriseContractEvent,
    EnterpriseContractNotice,
    EnterpriseContractTermFunding,
    EnterpriseContractVersion,
)


COMMAND_NAMESPACE = "enterprise_contract_command"
ENTITLEMENT_NAMESPACE = "enterprise_contract_entitlement"
SEAT_NAMESPACE = "enterprise_contract_seat"
INTERVAL_MONTHS = {"month": 1, "year": 12}
PERIOD_KINDS = {"month": "monthly_subscription", "year": "annual_monthly"}
LIVE_RENEWAL_STATES = ("recorded", "approved", "active")
MAX_SEATS = 2**31 - 1
MAX_MINOR = 2**63 - 1


class ContractError(ValueError):
    """A contract command violates the approved Phase 11 contract."""


class ContractConflictError(ContractError):
    """A command identity or natural key was reused with different facts."""


class ContractRetryError(ContractError):
    """The command raced a concurrent one; retry the transaction."""


class ContractPermissionError(ContractError):
    """The actor does not hold the explicit Enterprise contract permission."""


class ContractFundingError(ContractError):
    """Payment evidence is missing, unverified, or does not match the agreed amount."""


class ContractIsolationError(ContractError):
    """An authorization-bearing command ran outside READ COMMITTED."""


class ContractPolicyRequiredError(ContractError):
    """The operation needs a founder decision that has not been made."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _stored_utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _utc(value, field):
    if not hasattr(value, "tzinfo") or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _text(value, field, maximum, *, identifier=False):
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field} must be a nonempty string")
    value = value.strip()
    if len(value) > maximum:
        raise ContractError(f"{field} is too long")
    if identifier and ":" in value:
        raise ContractError(f"{field} must not contain ':'")
    return value


def _positive_int(value, field, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > maximum:
        raise ContractError(f"{field} must be a positive integer")
    return value


def _fingerprint(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _deliveries(value):
    if not isinstance(value, (list, tuple)) or not value:
        raise ContractError("at least one delivery obligation is required for the domain event")
    return value


def _claim(session, namespace, key, fingerprint, at):
    try:
        return _claim_registry(session, namespace, key, fingerprint, at)
    except RecurringAllocationConflictError as exc:
        raise ContractConflictError("contract command identity was reused with different facts") from exc
    except RecurringAllocationRetryError as exc:
        raise ContractRetryError(str(exc)) from exc


def _complete(session, registry, *, at, result_type, result_id):
    try:
        _complete_registry_if_claimed(
            session, registry, completed_at=at, result_type=result_type, result_id=result_id,
        )
    except RecurringAllocationConflictError as exc:
        raise ContractConflictError(str(exc)) from exc


def _record_event(session, envelope, obligations):
    try:
        return record_domain_event(session, envelope, obligations)
    except DomainEventConflictError as exc:
        raise ContractConflictError(str(exc)) from exc
    except BillingOutboxInvariantError as exc:
        raise ContractError(str(exc)) from exc


def _now(session):
    """Recorded command time: the database transaction time (Phase 10 audit F1)."""
    return _database_now(session)


def _clock(session):
    """Actual current database time, for effective-date and deadline decisions (audit R2)."""
    return _database_clock(session)


def _lock_account(session, billing_account_id):
    try:
        return lock_billing_account(session, billing_account_id)
    except CreditLedgerInvariantError as exc:
        raise ContractError("billing account is not available") from exc


def _authorize(session, actor_user_id):
    """Return the explicit, unrevoked staff grant valid now, or refuse.

    Runs after the account and contract locks. Global admin, organization
    admin, and customer billing roles are never consulted (P08; STOP-13).
    """
    actor = _text(actor_user_id, "actor_user_id", 36)
    try:
        _require_read_committed(session)
    except OfferIsolationError as exc:
        raise ContractIsolationError(
            "Enterprise contract commands must run in a READ COMMITTED transaction"
        ) from exc
    grant = _authorized_grant(
        session, user_id=actor, permission=CONTRACT_PERMISSION, started_at=_now(session),
    )
    if grant is None:
        raise ContractPermissionError("actor does not hold the explicit Enterprise contract permission")
    return grant


def _lock_contract(session, billing_account_id, contract_id):
    """Lock the account then the contract; one message for missing and foreign."""
    account = _lock_account(session, _text(billing_account_id, "billing_account_id", 36))
    contract = session.execute(
        select(EnterpriseContract)
        .where(EnterpriseContract.id == _text(contract_id, "contract_id", 36))
        .with_for_update()
    ).scalar_one_or_none()
    if contract is None or contract.billing_account_id != account.id:
        raise ContractError("contract is not available for this billing account")
    return account, contract


def _lock_version(session, contract, version_id):
    version = session.execute(
        select(EnterpriseContractVersion)
        .where(EnterpriseContractVersion.id == _text(version_id, "version_id", 36))
        .with_for_update()
    ).scalar_one_or_none()
    if version is None or version.contract_id != contract.id:
        raise ContractError("contract version is not available for this contract")
    return version


def _replay(session, registry, result_type, model):
    if registry.state != "completed" or registry.result_type != result_type:
        raise ContractRetryError("contract command is already in progress")
    return session.get(model, registry.result_id)


def _term_bounds(interval, starts_at):
    if interval not in TERM_INTERVALS:
        raise ContractError("contract term interval must be month or year")
    return starts_at, add_calendar_months(starts_at, INTERVAL_MONTHS[interval])


def _envelope(account_id, event_type, aggregate_type, aggregate_id, occurred_at, references):
    return {
        "billing_account_id": account_id,
        "event_key": f"{event_type}:{aggregate_id}",
        "event_type": event_type,
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
        "occurred_at": occurred_at,
        "reference_ids": [ref for ref in references if ref],
    }


def _transition(
    session, *, contract, version, to_state, transition, grant, at, evidence_reference,
    obligations, reason=None, also=None,
):
    """Append one contract or version event and move its projection with it.

    ``also`` names projection columns that the database guards allow to
    change only together with this state change, in one UPDATE.
    """
    target = version if version is not None else contract
    if target.state == to_state:
        return None
    # A contract can pass through the same states again in a later term
    # (active -> renewal_grace -> active), so each event has its own identity;
    # replay safety comes from the enclosing command's idempotency claim.
    event_id = str(uuid.uuid4())
    registry, inserted = _claim(
        session, COMMAND_NAMESPACE, f"enterprise-contract-event:{event_id}",
        _fingerprint({"target": target.id, "from": target.state, "to": to_state, "transition": transition}),
        at,
    )
    if not inserted:
        raise ContractRetryError("contract event identity raced; retry the transaction")
    domain_event, _messages, state = _record_event(session, _envelope(
        contract.billing_account_id, f"enterprise_contract_{transition}",
        "enterprise_contract_version" if version is not None else "enterprise_contract",
        event_id, at, [event_id, contract.id, version.id if version is not None else None],
    ), obligations)
    if state != "inserted":
        raise ContractConflictError("new contract transition reused an existing domain event")
    event = EnterpriseContractEvent(
        id=event_id, contract_id=contract.id,
        version_id=version.id if version is not None else None,
        scope="version" if version is not None else "contract",
        transition=transition, from_state=target.state, to_state=to_state, occurred_at=at,
        actor_user_id=grant.user_id, permission_grant_id=grant.id, reason=reason,
        evidence_reference=evidence_reference, idempotency_registry_id=registry.id,
        domain_event_id=domain_event.id,
    )
    session.add(event)
    session.flush()
    target.state = to_state
    target.last_event_id = event.id
    for column, value in (also or {}).items():
        setattr(target, column, value)
    session.flush()
    _complete(session, registry, at=at, result_type="enterprise_contract_event", result_id=event.id)
    return event


def _entitlement_transition(session, instance, to_state, transition, at, grant, source_id):
    key = f"enterprise-contract-entitlement:{instance.id}:{to_state}"
    registry, inserted = _claim(
        session, ENTITLEMENT_NAMESPACE, key,
        _fingerprint({"instance": instance.id, "from": instance.state, "to": to_state, "source": source_id}),
        at,
    )
    if not inserted:
        raise ContractConflictError("this entitlement transition was already recorded")
    try:
        event = append_entitlement_transition(
            session, instance_id=instance.id, next_state=to_state, transition=transition,
            effective_at=at, actor_type="user", actor_id=grant.user_id,
            source_type="phase11_contract_activation", source_id=source_id, idempotency=registry,
            evidence_json={"enterprise_contract_activation_id": source_id},
        )
    except EntitlementInvariantError as exc:
        raise ContractError(str(exc)) from exc
    session.flush()
    session.refresh(instance)
    if instance.state != to_state:
        # ORM-only unit schemas have no projection trigger; mirror it.
        instance.state = to_state
        instance.last_event_id = event.id
        session.flush()
    _complete(session, registry, at=at, result_type="entitlement_event", result_id=event.id)
    return event


def _validate_term_terms(terms, *, starts_at=None):
    """Validate negotiated term facts; nothing is defaulted or inferred."""
    if not isinstance(terms, dict):
        raise ContractError("contract terms must be an object")
    allowed = {
        "interval", "term_starts_at", "currency", "price_minor", "monthly_credit_amount",
        "committed_seats", "capabilities", "renewal_mode", "exclusivity_key",
    }
    if set(terms) - allowed:
        raise ContractError("contract terms contain unapproved fields")
    interval = terms.get("interval")
    if interval not in TERM_INTERVALS:
        raise ContractError("contract term interval must be month or year")
    term_start = starts_at if starts_at is not None else _utc(terms.get("term_starts_at"), "term_starts_at")
    if starts_at is not None and "term_starts_at" in terms and _utc(terms["term_starts_at"], "term_starts_at") != starts_at:
        raise ContractError("a renewal term starts exactly when the renewed term ends")
    term_start, term_end = _term_bounds(interval, term_start)
    currency = terms.get("currency")
    if not isinstance(currency, str) or len(currency) != 3 or currency != currency.lower() or not currency.isalpha():
        raise ContractError("contract currency must be a lowercase ISO code")
    price = _positive_int(terms.get("price_minor"), "price_minor", MAX_MINOR)
    credits = _positive_int(terms.get("monthly_credit_amount"), "monthly_credit_amount", MAX_MINOR)
    seats = _positive_int(terms.get("committed_seats"), "committed_seats", MAX_SEATS)
    capabilities = terms.get("capabilities")
    if not isinstance(capabilities, dict):
        raise ContractError("contract capabilities must be an explicit object")
    if "included_seats" in capabilities:
        raise ContractError("contracted seats are committed_seats, not a capability value")
    renewal_mode = terms.get("renewal_mode")
    if renewal_mode not in RENEWAL_MODES:
        raise ContractError("renewal_mode must be manual or automatic")
    exclusivity = _text(terms.get("exclusivity_key"), "exclusivity_key", 80)
    capability_json = {"schema_version": 1, "capabilities": {**capabilities, "included_seats": seats}}
    funding_json = {"schema_version": 1, "period_kind": PERIOD_KINDS[interval], "credit_amount": credits}
    try:
        validate_definition_payloads(capability_json, funding_json)
    except EntitlementInvariantError as exc:
        raise ContractError(str(exc)) from exc
    return {
        "interval": interval, "term_starts_at": term_start, "term_ends_at": term_end,
        "currency": currency, "price_minor": price, "monthly_credit_amount": credits,
        "committed_seats": seats, "capabilities": capabilities, "renewal_mode": renewal_mode,
        "exclusivity_key": exclusivity,
    }


def _new_version(
    session, *, contract, kind, number, term_version_id, facts, effective_at, seats, price, currency,
    executed_reference, evidence, grant, at, registry, fingerprint,
):
    version = EnterpriseContractVersion(
        id=str(uuid.uuid4()), contract_id=contract.id, billing_account_id=contract.billing_account_id,
        version_number=number, version_kind=kind, term_version_id=term_version_id,
        interval=facts.get("interval") if facts else None,
        term_starts_at=facts.get("term_starts_at") if facts else None,
        term_ends_at=facts.get("term_ends_at") if facts else None,
        effective_at=effective_at, currency=currency, price_minor=price,
        monthly_credit_amount=facts.get("monthly_credit_amount") if facts else None,
        committed_seats=seats,
        capabilities_json=facts.get("capabilities") if facts else None,
        exclusivity_key=facts.get("exclusivity_key") if facts else None,
        renewal_mode=facts.get("renewal_mode") if facts else None,
        executed_reference=executed_reference, executed_evidence_reference=evidence,
        recorded_by_user_id=grant.user_id, recorded_permission_grant_id=grant.id,
        request_fingerprint=fingerprint, idempotency_registry_id=registry.id, recorded_at=at,
        state="recorded",
    )
    session.add(version)
    session.flush()
    return version


def _version_recorded_event(session, contract, version, at, obligations):
    _event, _messages, state = _record_event(session, _envelope(
        contract.billing_account_id, "enterprise_contract_version_recorded",
        "enterprise_contract_version", version.id, at, [version.id, contract.id],
    ), obligations)
    if state != "inserted":
        raise ContractConflictError("new contract version reused an existing domain event")


# ---------------------------------------------------------------------------
# Recording and approval
# ---------------------------------------------------------------------------

def record_enterprise_contract(
    session, *, command_id, billing_account_id, contract_reference, terms,
    executed_reference, executed_evidence_reference, actor_user_id, delivery_obligations,
):
    """Record an executed contract and its initial term. Returns ``(contract, version, state)``.

    Recording grants nothing. A contract may be recorded and approved before
    its term starts; benefits begin only at activation.
    """
    command_id = _text(command_id, "command_id", 128, identifier=True)
    reference = _text(contract_reference, "contract_reference", 255)
    executed = _text(executed_reference, "executed_reference", 255)
    evidence = _text(executed_evidence_reference, "executed_evidence_reference", 255)
    obligations = _deliveries(delivery_obligations)
    account = _lock_account(session, _text(billing_account_id, "billing_account_id", 36))
    grant = _authorize(session, actor_user_id)
    facts = _validate_term_terms(terms)
    if facts["currency"] != account.currency:
        raise ContractError("contract currency must match the organization billing account")
    at = _now(session)
    fingerprint = _fingerprint({
        "account": account.id, "reference": reference, "facts": facts,
        "executed": executed, "evidence": evidence, "actor": grant.user_id,
    })
    registry, inserted = _claim(
        session, COMMAND_NAMESPACE, f"enterprise-contract:record:{command_id}", fingerprint, at,
    )
    if not inserted:
        version = _replay(session, registry, "enterprise_contract_version", EnterpriseContractVersion)
        return session.get(EnterpriseContract, version.contract_id), version, "duplicate"
    if session.execute(
        select(EnterpriseContract.id).where(EnterpriseContract.contract_reference == reference)
    ).first() is not None:
        raise ContractConflictError("contract reference is already recorded")
    contract_registry, _ = _claim(
        session, COMMAND_NAMESPACE, f"enterprise-contract:identity:{reference}",
        _fingerprint({"account": account.id, "reference": reference}), at,
    )
    contract = EnterpriseContract(
        id=str(uuid.uuid4()), billing_account_id=account.id, contract_reference=reference,
        state="recorded", idempotency_registry_id=contract_registry.id,
    )
    session.add(contract)
    session.flush()
    _complete(session, contract_registry, at=at, result_type="enterprise_contract", result_id=contract.id)
    version = _new_version(
        session, contract=contract, kind="initial", number=1, term_version_id=None, facts=facts,
        effective_at=facts["term_starts_at"], seats=facts["committed_seats"],
        price=facts["price_minor"], currency=facts["currency"], executed_reference=executed,
        evidence=evidence, grant=grant, at=at, registry=registry, fingerprint=fingerprint,
    )
    _version_recorded_event(session, contract, version, at, obligations)
    _complete(session, registry, at=at, result_type="enterprise_contract_version", result_id=version.id)
    return contract, version, "inserted"


def _latest_term(session, contract_id):
    return session.execute(
        select(EnterpriseContractVersion)
        .where(
            EnterpriseContractVersion.contract_id == contract_id,
            EnterpriseContractVersion.version_kind.in_(("initial", "renewal")),
            EnterpriseContractVersion.state.notin_(("cancelled", "superseded")),
        )
        .order_by(EnterpriseContractVersion.term_starts_at.desc(), EnterpriseContractVersion.version_number.desc())
    ).scalars().first()


def _next_number(session, contract_id):
    numbers = session.execute(
        select(EnterpriseContractVersion.version_number).where(EnterpriseContractVersion.contract_id == contract_id)
    ).scalars().all()
    return max(numbers, default=0) + 1


def _effective_seats(session, term):
    """The seats the term commits to now: its own, or its latest activated amendment."""
    amendments = session.execute(
        select(EnterpriseContractVersion.committed_seats)
        .where(
            EnterpriseContractVersion.term_version_id == term.id,
            EnterpriseContractVersion.version_kind == "amendment",
            EnterpriseContractVersion.state.in_(("approved", "active", "completed")),
        )
    ).scalars().all()
    return max([term.committed_seats, *amendments])


def _live_renewal(session, term):
    return session.execute(
        select(EnterpriseContractVersion)
        .where(
            EnterpriseContractVersion.term_version_id == term.id,
            EnterpriseContractVersion.version_kind == "renewal",
            EnterpriseContractVersion.state.in_(LIVE_RENEWAL_STATES),
        )
    ).scalars().first()


def record_contract_version(
    session, *, command_id, billing_account_id, contract_id, version_kind, term_version_id,
    executed_reference, executed_evidence_reference, actor_user_id, delivery_obligations,
    terms=None, effective_at=None, committed_seats=None, price_minor=None, monthly_credit_amount=None,
):
    """Record an executed renewal or amendment. Returns ``(version, state)``.

    Renewal: a whole next term, starting when the renewed term ends; seats may
    be reduced only here. Amendment: a mid-term seat increase effective on the
    agreed date, with its agreed price. Mid-term reductions are refused, and
    mid-term allocation changes need a founder decision.
    """
    command_id = _text(command_id, "command_id", 128, identifier=True)
    executed = _text(executed_reference, "executed_reference", 255)
    evidence = _text(executed_evidence_reference, "executed_evidence_reference", 255)
    obligations = _deliveries(delivery_obligations)
    account, contract = _lock_contract(session, billing_account_id, contract_id)
    grant = _authorize(session, actor_user_id)
    term = _lock_version(session, contract, term_version_id)
    at = _now(session)
    if term.version_kind not in ("initial", "renewal"):
        raise ContractError("renewals and amendments apply to a contract term")
    if version_kind == "renewal":
        facts = _validate_term_terms(terms, starts_at=_stored_utc(term.term_ends_at))
        if facts["currency"] != account.currency:
            raise ContractError("contract currency must match the organization billing account")
        payload = {"kind": "renewal", "term": term.id, "facts": facts}
        version_effective, seats, price, currency = (
            facts["term_starts_at"], facts["committed_seats"], facts["price_minor"], facts["currency"],
        )
    elif version_kind == "amendment":
        if monthly_credit_amount is not None or terms is not None:
            raise ContractPolicyRequiredError(
                "mid-term changes to the recurring allocation need a founder decision on proration"
            )
        version_effective = _utc(effective_at, "effective_at")
        if not (_stored_utc(term.term_starts_at) <= version_effective < _stored_utc(term.term_ends_at)):
            raise ContractError("an amendment takes effect within the term it amends")
        seats = _positive_int(committed_seats, "committed_seats", MAX_SEATS)
        price = _positive_int(price_minor, "price_minor", MAX_MINOR)
        currency = term.currency
        facts = None
        payload = {
            "kind": "amendment", "term": term.id, "effective_at": version_effective.isoformat(),
            "seats": seats, "price": price,
        }
    else:
        raise ContractError("version_kind must be renewal or amendment")
    fingerprint = _fingerprint({**payload, "executed": executed, "evidence": evidence, "actor": grant.user_id})
    registry, inserted = _claim(
        session, COMMAND_NAMESPACE, f"enterprise-contract:version:{contract.id}:{command_id}", fingerprint, at,
    )
    if not inserted:
        return _replay(session, registry, "enterprise_contract_version", EnterpriseContractVersion), "duplicate"
    if contract.state in ("ended", "cancelled"):
        raise ContractError("an ended or cancelled contract cannot change")
    if version_kind == "renewal":
        if term.state not in ("approved", "active", "completed"):
            raise ContractError("a renewal must follow an approved contract term")
        if _live_renewal(session, term) is not None:
            raise ContractConflictError("this term already has a renewal in progress")
    else:
        if term.state not in ("approved", "active"):
            raise ContractError("an amendment must amend an approved or active contract term")
        if seats <= _effective_seats(session, term):
            raise ContractError(
                "mid-term seat reductions are not allowed; reductions take effect at renewal"
            )
    version = _new_version(
        session, contract=contract, kind=version_kind, number=_next_number(session, contract.id),
        term_version_id=term.id, facts=facts, effective_at=version_effective, seats=seats, price=price,
        currency=currency, executed_reference=executed, evidence=evidence, grant=grant, at=at,
        registry=registry, fingerprint=fingerprint,
    )
    _version_recorded_event(session, contract, version, at, obligations)
    _complete(session, registry, at=at, result_type="enterprise_contract_version", result_id=version.id)
    return version, "inserted"


def _materialize_term(session, contract, version, grant, at):
    """Create the approved definition, contract-backed term, and proposed entitlement."""
    definition = EntitlementDefinition(
        id=str(uuid.uuid4()), key=f"enterprise-contract:{contract.id}", version=version.version_number,
        exclusivity_key=version.exclusivity_key,
        capability_json={
            "schema_version": 1,
            "capabilities": {**(version.capabilities_json or {}), "included_seats": version.committed_seats},
        },
        funding_policy_json={
            "schema_version": 1, "period_kind": PERIOD_KINDS[version.interval],
            "credit_amount": int(version.monthly_credit_amount),
        },
        effective_at=_stored_utc(version.term_starts_at), approved_at=at,
        approved_by_user_id=grant.user_id, approval_evidence_reference=version.executed_reference,
    )
    session.add(definition)
    session.flush()
    subscription = BillingSubscription(
        id=str(uuid.uuid4()), billing_account_id=contract.billing_account_id,
        processor=CONTRACT_PROCESSOR, external_subscription_id=f"{contract.id}:v{version.version_number}",
        interval=version.interval, anchor_at=_stored_utc(version.term_starts_at),
        term_starts_at=_stored_utc(version.term_starts_at), term_ends_at=_stored_utc(version.term_ends_at),
        state="proposed", current_entitlement_definition_id=definition.id,
        origin_evidence_json={"enterprise_contract_version_id": version.id},
    )
    session.add(subscription)
    session.flush()
    instance = EntitlementInstance(
        id=str(uuid.uuid4()), billing_account_id=contract.billing_account_id,
        entitlement_definition_id=definition.id, subscription_id=subscription.id, state="proposed",
        starts_at=_stored_utc(version.term_starts_at), ends_at=_stored_utc(version.term_ends_at),
        source_type="enterprise_contract", source_id=version.id,
        approval_evidence_reference=version.executed_reference,
    )
    session.add(instance)
    session.flush()
    return definition, subscription, instance


def _approve(session, contract, version, grant, at, evidence, obligations):
    if version.state != "recorded":
        raise ContractError("only a recorded contract version can be approved")
    if version.version_kind == "amendment":
        term = session.get(EnterpriseContractVersion, version.term_version_id)
        if term.subscription_id is None:
            raise ContractError("an amendment needs its approved term")
        binding = {"subscription_id": term.subscription_id}
    else:
        definition, subscription, instance = _materialize_term(session, contract, version, grant, at)
        binding = {
            "entitlement_definition_id": definition.id, "subscription_id": subscription.id,
            "entitlement_instance_id": instance.id,
        }
    _transition(
        session, contract=contract, version=version, to_state="approved", transition="version_approved",
        grant=grant, at=at, evidence_reference=evidence, obligations=obligations, also=binding,
    )
    if version.version_kind == "initial":
        _transition(
            session, contract=contract, version=None, to_state="approved", transition="approved",
            grant=grant, at=at, evidence_reference=evidence, obligations=obligations,
        )


def approve_contract_version(
    session, *, command_id, billing_account_id, contract_id, version_id, approval_evidence_reference,
    actor_user_id, delivery_obligations,
):
    """Approve a recorded version. Approval may precede its effective date and grants nothing."""
    command_id = _text(command_id, "command_id", 128, identifier=True)
    evidence = _text(approval_evidence_reference, "approval_evidence_reference", 255)
    obligations = _deliveries(delivery_obligations)
    _account, contract = _lock_contract(session, billing_account_id, contract_id)
    grant = _authorize(session, actor_user_id)
    version = _lock_version(session, contract, version_id)
    at = _now(session)
    registry, inserted = _claim(
        session, COMMAND_NAMESPACE, f"enterprise-contract:approve:{version.id}",
        _fingerprint({"version": version.id, "evidence": evidence}), at,
    )
    if not inserted:
        return _replay(session, registry, "enterprise_contract_version", EnterpriseContractVersion), "duplicate"
    if contract.state in ("ended", "cancelled"):
        raise ContractError("an ended or cancelled contract cannot change")
    _approve(session, contract, version, grant, at, evidence, obligations)
    _complete(session, registry, at=at, result_type="enterprise_contract_version", result_id=version.id)
    return version, "inserted"


def prepare_automatic_renewal(
    session, *, command_id, billing_account_id, contract_id, term_version_id, actor_user_id,
    delivery_obligations,
):
    """Create and approve the next term with unchanged terms, under the recorded opt-in.

    Refused for manual renewal, after an effective nonrenewal notice, or when
    a renewal already exists. Any change needs an executed renewal instead.
    """
    command_id = _text(command_id, "command_id", 128, identifier=True)
    obligations = _deliveries(delivery_obligations)
    _account, contract = _lock_contract(session, billing_account_id, contract_id)
    grant = _authorize(session, actor_user_id)
    term = _lock_version(session, contract, term_version_id)
    at = _now(session)
    fingerprint = _fingerprint({"kind": "automatic_renewal", "term": term.id})
    registry, inserted = _claim(
        session, COMMAND_NAMESPACE, f"enterprise-contract:auto-renew:{term.id}", fingerprint, at,
    )
    if not inserted:
        return _replay(session, registry, "enterprise_contract_version", EnterpriseContractVersion), "duplicate"
    if term.version_kind not in ("initial", "renewal") or term.state not in ("approved", "active"):
        raise ContractError("automatic renewal follows an approved or active term")
    if term.renewal_mode != "automatic":
        raise ContractError("this term renews manually")
    if contract.state in ("ended", "cancelled"):
        raise ContractError("an ended or cancelled contract cannot renew")
    if _effective_nonrenewal(session, term) is not None:
        raise ContractError("a timely nonrenewal notice is in effect for this term")
    if _live_renewal(session, term) is not None:
        raise ContractConflictError("this term already has a renewal in progress")
    if _effective_seats(session, term) != term.committed_seats:
        # An amendment priced only the remainder of this term, so the agreed
        # full-term price for the amended seats is not recorded anywhere.
        raise ContractPolicyRequiredError(
            "after a seat amendment the renewal price is not determined; record an executed renewal"
        )
    starts_at = _stored_utc(term.term_ends_at)
    _start, ends_at = _term_bounds(term.interval, starts_at)
    seats = term.committed_seats
    facts = {
        "interval": term.interval, "term_starts_at": starts_at, "term_ends_at": ends_at,
        "monthly_credit_amount": int(term.monthly_credit_amount), "capabilities": term.capabilities_json,
        "renewal_mode": term.renewal_mode, "exclusivity_key": term.exclusivity_key,
    }
    version = _new_version(
        session, contract=contract, kind="renewal", number=_next_number(session, contract.id),
        term_version_id=term.id, facts=facts, effective_at=starts_at, seats=seats,
        price=int(term.price_minor), currency=term.currency,
        executed_reference=term.executed_reference,
        evidence=f"automatic-renewal:{term.id}", grant=grant, at=at, registry=registry,
        fingerprint=fingerprint,
    )
    _version_recorded_event(session, contract, version, at, obligations)
    _approve(session, contract, version, grant, at, f"automatic-renewal:{term.id}", obligations)
    _complete(session, registry, at=at, result_type="enterprise_contract_version", result_id=version.id)
    return version, "inserted"


# ---------------------------------------------------------------------------
# Verified Stripe funding (P11-DEP-002)
# ---------------------------------------------------------------------------

def record_contract_funding(
    session, *, command_id, billing_account_id, contract_id, version_id, financial_line_id,
    actor_user_id, delivery_obligations,
):
    """Bind one verified Stripe payment line to one approved version, in the exact agreed amount.

    Only a ``payment`` transaction recorded from a non-quarantined Stripe
    inbox event qualifies. Adjustments, manual claims, partial payments,
    other currencies, other subscriptions, and a line that already funded
    something else are refused. Recording funding grants nothing by itself.
    """
    command_id = _text(command_id, "command_id", 128, identifier=True)
    line_id = _text(financial_line_id, "financial_line_id", 36)
    obligations = _deliveries(delivery_obligations)
    account, contract = _lock_contract(session, billing_account_id, contract_id)
    grant = _authorize(session, actor_user_id)
    version = _lock_version(session, contract, version_id)
    at = _now(session)
    registry, inserted = _claim(
        session, COMMAND_NAMESPACE, f"enterprise-contract:fund:{version.id}",
        _fingerprint({"version": version.id, "line": line_id}), at,
    )
    if not inserted:
        return _replay(session, registry, "enterprise_contract_term_funding", EnterpriseContractTermFunding), "duplicate"
    if version.state != "approved":
        raise ContractError("only an approved, not yet active contract version can be funded")
    row = session.execute(
        select(FinancialLine, FinancialTransaction)
        .join(FinancialTransaction, FinancialTransaction.id == FinancialLine.financial_transaction_id)
        .where(FinancialLine.id == line_id)
        .with_for_update()
    ).one_or_none()
    if row is None or row[1].billing_account_id != account.id:
        raise ContractFundingError("payment line is not available for this billing account")
    line, transaction = row
    inbox = session.get(ExternalEventInbox, transaction.inbox_event_id) if transaction.inbox_event_id else None
    expected_kind = "seat" if version.version_kind == "amendment" else "subscription"
    net = int(line.principal_minor) + int(line.discount_minor)
    if (
        transaction.kind != "payment" or inbox is None or inbox.provider != "stripe"
        or inbox.state == "quarantined" or transaction.provider != "stripe"
        or int(transaction.principal_minor) <= 0
    ):
        raise ContractFundingError("contract funding requires a verified Stripe payment")
    if (
        line.line_kind != expected_kind or line.subscription_id != version.subscription_id
        or (expected_kind == "subscription" and line.entitlement_instance_id != version.entitlement_instance_id)
        or line.currency != version.currency or transaction.currency != version.currency
        or int(line.principal_minor) <= 0 or int(line.discount_minor) > 0
        or net != int(version.price_minor)
    ):
        raise ContractFundingError("payment does not match the agreed contract amount and term")
    if session.execute(
        select(EnterpriseContractTermFunding.id).where(EnterpriseContractTermFunding.financial_line_id == line.id)
    ).first() is not None:
        raise ContractConflictError("this payment line already funds a contract version")
    funding_id = str(uuid.uuid4())
    domain_event, _messages, state = _record_event(session, _envelope(
        account.id, "enterprise_contract_funded", "enterprise_contract_term_funding", funding_id, at,
        [funding_id, contract.id, version.id, line.id, transaction.id],
    ), obligations)
    if state != "inserted":
        raise ContractConflictError("new contract funding reused an existing domain event")
    funding = EnterpriseContractTermFunding(
        id=funding_id, contract_id=contract.id, version_id=version.id, billing_account_id=account.id,
        subscription_id=version.subscription_id, financial_transaction_id=transaction.id,
        financial_line_id=line.id, amount_minor=net, currency=version.currency,
        paid_at=_stored_utc(transaction.effective_at), recorded_at=at, actor_user_id=grant.user_id,
        permission_grant_id=grant.id, idempotency_registry_id=registry.id, domain_event_id=domain_event.id,
    )
    session.add(funding)
    session.flush()
    _complete(session, registry, at=at, result_type="enterprise_contract_term_funding", result_id=funding.id)
    return funding, "inserted"


# ---------------------------------------------------------------------------
# Activation, completion, grace, and end of paid access
# ---------------------------------------------------------------------------

def _overlapping_plan(session, account_id, version):
    rows = session.execute(
        select(EntitlementInstance)
        .join(EntitlementDefinition, EntitlementDefinition.id == EntitlementInstance.entitlement_definition_id)
        .where(
            EntitlementInstance.billing_account_id == account_id,
            EntitlementInstance.id != version.entitlement_instance_id,
            EntitlementInstance.state.in_(("scheduled", "active", "reducing")),
            EntitlementDefinition.exclusivity_key == version.exclusivity_key,
        )
    ).scalars().all()
    start, end = _stored_utc(version.term_starts_at), _stored_utc(version.term_ends_at)
    for instance in rows:
        other_end = _stored_utc(instance.ends_at)
        if _stored_utc(instance.starts_at) < end and (other_end is None or start < other_end):
            return instance
    return None


def _contract_seat_commitment(
    session, *, commitment_id, account_id, subscription_id, seats, at, previous, activation_id, obligations,
):
    registry, inserted = _claim(
        session, SEAT_NAMESPACE, f"enterprise-contract-seats:{activation_id}",
        _fingerprint({"activation": activation_id, "seats": seats}), at,
    )
    if not inserted:
        raise ContractConflictError("contract seats were already committed for this activation")
    domain_event, _messages, state = _record_event(session, _envelope(
        account_id, "seat_commitment_contracted", "seat_commitment", commitment_id, at,
        [commitment_id, subscription_id, activation_id],
    ), obligations)
    if state != "inserted":
        raise ContractConflictError("new contract seat commitment reused an existing domain event")
    if previous is not None:
        _replace_commitment(session, previous, at)
    commitment = SeatCommitment(
        id=commitment_id, billing_account_id=account_id, subscription_id=subscription_id, quantity=seats,
        origin_type="contract", state="active", starts_at=at,
        previous_commitment_id=previous.id if previous is not None else None,
        idempotency_registry_id=registry.id, domain_event_id=domain_event.id,
    )
    session.add(commitment)
    session.flush()
    _complete(session, registry, at=at, result_type="seat_commitment", result_id=commitment.id)
    return commitment


def _current_period_index(anchor_at, at, months):
    for index in range(months):
        start, end = monthly_period_bounds(anchor_at, index)
        if start <= at < end:
            return index
    raise ContractError("the activation time is outside the paid term")


def activate_contract_version(
    session, *, command_id, billing_account_id, contract_id, version_id, actor_user_id, delivery_obligations,
):
    """Put one approved, effective, fully funded version into effect, exactly once.

    A term: the entitlement becomes active, the term's contracted seats are
    committed (Phase 8, ``contract`` origin), and the current month's
    recurring credits are allocated through Phase 6. An amendment: the seat
    commitment rises from its effective date. Nothing is granted before the
    effective date or without verified funding. Returns ``(activation, state)``.
    """
    command_id = _text(command_id, "command_id", 128, identifier=True)
    obligations = _deliveries(delivery_obligations)
    account, contract = _lock_contract(session, billing_account_id, contract_id)
    grant = _authorize(session, actor_user_id)
    version = _lock_version(session, contract, version_id)
    at = _now(session)
    registry, inserted = _claim(
        session, COMMAND_NAMESPACE, f"enterprise-contract:activate:{version.id}",
        _fingerprint({"version": version.id}), at,
    )
    if not inserted:
        return _replay(session, registry, "enterprise_contract_activation", EnterpriseContractActivation), "duplicate"
    if version.state != "approved":
        raise ContractError("only an approved contract version can be activated")
    funding = session.execute(
        select(EnterpriseContractTermFunding).where(EnterpriseContractTermFunding.version_id == version.id)
    ).scalar_one_or_none()
    if funding is None:
        raise ContractFundingError("activation requires verified funding of the full agreed amount")
    clock = _clock(session)
    if clock < _stored_utc(version.effective_at):
        raise ContractError("the contract version is not yet effective")
    subscription = session.execute(
        select(BillingSubscription).where(BillingSubscription.id == version.subscription_id).with_for_update()
    ).scalar_one()
    organization = session.get(Organization, account.organization_id)
    activation_id = str(uuid.uuid4())
    commitment_id = str(uuid.uuid4())
    reinstating = False

    # Validate everything before any effect.
    current = None
    if version.version_kind == "amendment":
        term = session.get(EnterpriseContractVersion, version.term_version_id)
        if term.state != "active" or clock >= _stored_utc(term.term_ends_at):
            raise ContractError("an amendment takes effect only during its active term")
        current = current_seat_commitment(session, subscription.id)
        if current is None or version.committed_seats <= current.quantity:
            raise ContractError("an amendment must increase the contracted seats")
        instance = None
    else:
        if clock >= _stored_utc(version.term_ends_at):
            raise ContractError("the contract term has already ended")
        previous_term = None
        if version.version_kind == "initial":
            if contract.state != "approved":
                raise ContractError("the contract is not awaiting its first term")
        else:
            previous_term = session.get(EnterpriseContractVersion, version.term_version_id)
            # Approved rule (B1, 2026-11-15): eligibility is judged by the
            # verified payment time, not by when the command runs. A renewal
            # paid within the 15-day grace may be activated after grace ends.
            if _stored_utc(funding.paid_at) >= _grace_end(previous_term):
                raise ContractPolicyRequiredError(
                    "the renewal was paid after the grace deadline; it is preserved for refund review"
                )
            if _effective_nonrenewal(session, previous_term) is not None:
                raise ContractPolicyRequiredError(
                    "a timely nonrenewal notice is in effect; the funded renewal needs a refund or "
                    "reversal decision"
                )
            if contract.state == "ended" and _ended_by_grace_lapse(session, contract, previous_term):
                reinstating = True
            elif contract.state not in ("active", "renewal_grace"):
                raise ContractError("a renewal applies only to an active contract or one in renewal grace")
        # Credits release monthly from the term start. Activating after the
        # first month would need a catch-up credit decision that is not approved.
        if clock >= _activation_window_end(version):
            raise ContractPolicyRequiredError(
                "activation after the term's first month needs an approved catch-up credit policy; "
                "the funded version is preserved for review"
            )
        occupancy = seat_occupancy(session, organization.id)
        if occupancy > version.committed_seats:
            raise ContractPolicyRequiredError(
                "paid occupancy exceeds the contracted seats; contract exceptions to the "
                "occupancy rule are not approved"
            )
        instance = session.execute(
            select(EntitlementInstance).where(EntitlementInstance.id == version.entitlement_instance_id).with_for_update()
        ).scalar_one()
        if previous_term is not None and previous_term.state == "active":
            _complete_term(session, contract, previous_term, grant, at, obligations, renewal_activating=True)
        if _overlapping_plan(session, account.id, version) is not None:
            raise ContractConflictError("another plan of the same exclusivity group overlaps this term")

    # The activation evidence is written first; the database guards on the
    # entitlement transition and the contracted seat commitment check it.
    domain_event, _messages, state = _record_event(session, _envelope(
        account.id, "enterprise_contract_activated", "enterprise_contract_activation", activation_id, at,
        [activation_id, contract.id, version.id, subscription.id, funding.id, commitment_id],
    ), obligations)
    if state != "inserted":
        raise ContractConflictError("new contract activation reused an existing domain event")
    activation = EnterpriseContractActivation(
        id=activation_id, contract_id=contract.id, version_id=version.id, billing_account_id=account.id,
        subscription_id=subscription.id, entitlement_instance_id=instance.id if instance is not None else None,
        term_funding_id=funding.id, seat_commitment_id=commitment_id, seats=version.committed_seats,
        activated_at=at, actor_user_id=grant.user_id, permission_grant_id=grant.id,
        idempotency_registry_id=registry.id, domain_event_id=domain_event.id,
    )
    session.add(activation)
    session.flush()
    if instance is not None:
        subscription.state = "active"
        session.flush()
        _entitlement_transition(session, instance, "scheduled", "contract_term_approved", at, grant, activation_id)
        _entitlement_transition(session, instance, "active", "contract_term_activated", at, grant, activation_id)
    _contract_seat_commitment(
        session, commitment_id=commitment_id, account_id=account.id, subscription_id=subscription.id,
        seats=version.committed_seats, at=at, previous=current, activation_id=activation_id,
        obligations=obligations,
    )
    instance_id = instance.id if instance is not None else None
    _transition(
        session, contract=contract, version=version, to_state="active", transition="version_activated",
        grant=grant, at=at, evidence_reference=f"activation:{activation_id}", obligations=obligations,
    )
    if version.version_kind != "amendment":
        _transition(
            session, contract=contract, version=None, to_state="active",
            transition="reinstated_after_grace_payment" if reinstating else "activated",
            grant=grant, at=at, evidence_reference=f"activation:{activation_id}", obligations=obligations,
            also={"paid_access_ended_at": None, "retention_review_until": None} if reinstating else None,
        )
        months = INTERVAL_MONTHS[version.interval]
        index = _current_period_index(_stored_utc(subscription.anchor_at), at, months)
        try:
            allocate_recurring_credits(
                session, billing_account_id=account.id, entitlement_instance_id=instance_id,
                period_index=index, opened_at=at, delivery_obligations=obligations,
                financial_line_id=funding.financial_line_id, actor_type="user", actor_id=grant.user_id,
            )
        except RecurringAllocationError as exc:
            raise ContractError(f"contract credit allocation failed: {exc}") from exc
    _complete(session, registry, at=at, result_type="enterprise_contract_activation", result_id=activation.id)
    return activation, "inserted"


def _effective_nonrenewal(session, term):
    notices = session.execute(
        select(EnterpriseContractNotice).where(EnterpriseContractNotice.term_version_id == term.id)
    ).scalars().all()
    reversed_ids = {n.reverses_notice_id for n in notices if n.kind == "nonrenewal_reversal"}
    for notice in notices:
        if notice.kind == "nonrenewal" and notice.timely and notice.id not in reversed_ids:
            return notice
    return None


def _end_access(session, contract, term, grant, at, obligations, transition):
    ended_at = _stored_utc(term.term_ends_at)
    _transition(
        session, contract=contract, version=None, to_state="ended", transition=transition,
        grant=grant, at=at, evidence_reference=f"term:{term.id}", obligations=obligations,
        also={
            "paid_access_ended_at": ended_at,
            "retention_review_until": ended_at + timedelta(days=RETENTION_REVIEW_DAYS),
        },
    )
    for pending in session.execute(
        select(EnterpriseContractVersion).where(
            EnterpriseContractVersion.contract_id == contract.id,
            EnterpriseContractVersion.state.in_(("recorded", "approved")),
        ).order_by(EnterpriseContractVersion.version_number).with_for_update()
    ).scalars().all():
        # B1: a funded version is never cancelled; it stays approved with its
        # verified payment evidence and is listed for refund review.
        if _funding_of(session, pending.id) is not None:
            continue
        # A payment made within grace may be recorded after it lapses, so the
        # lapsed term's renewal stays open to receive that evidence.
        if (transition == "ended_after_unpaid_grace" and pending.version_kind == "renewal"
                and pending.term_version_id == term.id):
            continue
        _transition(
            session, contract=contract, version=pending, to_state="cancelled", transition="version_lapsed",
            grant=grant, at=at, evidence_reference=f"ended:{contract.id}", obligations=obligations,
        )


def _funding_of(session, version_id):
    return session.execute(
        select(EnterpriseContractTermFunding).where(EnterpriseContractTermFunding.version_id == version_id)
    ).scalar_one_or_none()


def _grace_end(term):
    return _stored_utc(term.term_ends_at) + timedelta(days=RENEWAL_GRACE_DAYS)


def _activation_window_end(version):
    """A term may activate only within its first monthly period (no catch-up policy is approved)."""
    return add_calendar_months(_stored_utc(version.term_starts_at), 1)


def _ended_by_grace_lapse(session, contract, term):
    """True when the contract ended only because ``term``'s renewal grace lapsed unpaid."""
    if contract.state != "ended" or contract.last_event_id is None:
        return False
    event = session.get(EnterpriseContractEvent, contract.last_event_id)
    return (
        event is not None and event.transition == "ended_after_unpaid_grace"
        and _stored_utc(contract.paid_access_ended_at) == _stored_utc(term.term_ends_at)
    )


def _complete_term(session, contract, term, grant, at, obligations, *, renewal_activating=False):
    if _clock(session) < _stored_utc(term.term_ends_at):
        raise ContractError("the contract term has not ended")
    for amendment in session.execute(
        select(EnterpriseContractVersion).where(
            EnterpriseContractVersion.term_version_id == term.id,
            EnterpriseContractVersion.version_kind == "amendment",
            EnterpriseContractVersion.state == "active",
        ).with_for_update()
    ).scalars().all():
        _transition(
            session, contract=contract, version=amendment, to_state="completed", transition="version_completed",
            grant=grant, at=at, evidence_reference=f"term:{term.id}", obligations=obligations,
        )
    instance = session.execute(
        select(EntitlementInstance).where(EntitlementInstance.id == term.entitlement_instance_id).with_for_update()
    ).scalar_one()
    if instance.state == "active":
        _entitlement_transition(
            session, instance, "expired", "contract_term_ended", _stored_utc(term.term_ends_at), grant, term.id,
        )
    subscription = session.execute(
        select(BillingSubscription).where(BillingSubscription.id == term.subscription_id).with_for_update()
    ).scalar_one()
    subscription.state = "expired"
    session.flush()
    _transition(
        session, contract=contract, version=term, to_state="completed", transition="version_completed",
        grant=grant, at=at, evidence_reference=f"term:{term.id}", obligations=obligations,
    )
    if renewal_activating:
        return
    if _effective_nonrenewal(session, term) is not None:
        _end_access(session, contract, term, grant, at, obligations, "ended_by_nonrenewal")
    elif term.renewal_mode == "automatic" or _live_renewal(session, term) is not None:
        # Unpaid renewal: 15 days of read-only grace; no new-term benefits.
        _transition(
            session, contract=contract, version=None, to_state="renewal_grace",
            transition="renewal_grace_started", grant=grant, at=at,
            evidence_reference=f"term:{term.id}", obligations=obligations,
        )
    else:
        _end_access(session, contract, term, grant, at, obligations, "ended_without_renewal")


def complete_contract_term(
    session, *, command_id, billing_account_id, contract_id, version_id, actor_user_id, delivery_obligations,
):
    """Close an active term at or after its end. Saved work, members, and data are untouched.

    The contract then enters renewal grace (renewal expected but unpaid) or
    ends (timely nonrenewal, or manual renewal with none recorded). Unspent
    recurring credits expire through the Phase 6 expiration command.
    """
    command_id = _text(command_id, "command_id", 128, identifier=True)
    obligations = _deliveries(delivery_obligations)
    _account, contract = _lock_contract(session, billing_account_id, contract_id)
    grant = _authorize(session, actor_user_id)
    term = _lock_version(session, contract, version_id)
    at = _now(session)
    registry, inserted = _claim(
        session, COMMAND_NAMESPACE, f"enterprise-contract:complete:{term.id}", _fingerprint({"term": term.id}), at,
    )
    if not inserted:
        return _replay(session, registry, "enterprise_contract_version", EnterpriseContractVersion), "duplicate"
    if term.version_kind not in ("initial", "renewal") or term.state != "active":
        raise ContractError("only an active contract term can be completed")
    _complete_term(session, contract, term, grant, at, obligations)
    _complete(session, registry, at=at, result_type="enterprise_contract_version", result_id=term.id)
    return term, "inserted"


def end_contract_after_grace(
    session, *, command_id, billing_account_id, contract_id, actor_user_id, delivery_obligations,
):
    """End paid access once the 15-day renewal grace has passed unpaid.

    Paid access is recorded as ending at the original paid term end, not at
    the end of grace. The retention-review date is recorded for later,
    separately approved offboarding work; nothing is deleted or exported.
    """
    command_id = _text(command_id, "command_id", 128, identifier=True)
    obligations = _deliveries(delivery_obligations)
    _account, contract = _lock_contract(session, billing_account_id, contract_id)
    grant = _authorize(session, actor_user_id)
    at = _now(session)
    term = _latest_completed_term(session, contract.id)
    if term is None:
        raise ContractError("the contract is not in renewal grace")
    # Keyed by the lapsed term: a contract can pass through grace again in a
    # later cycle, and each lapse is its own decision.
    registry, inserted = _claim(
        session, COMMAND_NAMESPACE, f"enterprise-contract:end-after-grace:{term.id}",
        _fingerprint({"contract": contract.id, "term": term.id}), at,
    )
    if not inserted:
        return _replay(session, registry, "enterprise_contract", EnterpriseContract), "duplicate"
    if contract.state != "renewal_grace":
        raise ContractError("the contract is not in renewal grace")
    if _clock(session) < _grace_end(term):
        raise ContractError("the renewal grace period has not ended")
    renewal = _live_renewal(session, term)
    funding = _funding_of(session, renewal.id) if renewal is not None else None
    # C1: only a renewal that can still activate holds the contract in grace.
    # Once its first month has passed, activation needs an unapproved catch-up
    # policy, so the lapse proceeds and the funded renewal stays for review.
    if (
        funding is not None and renewal.state == "approved"
        and _stored_utc(funding.paid_at) < _grace_end(term)
        and _clock(session) < _activation_window_end(renewal)
    ):
        raise ContractError("a renewal paid within the grace period awaits activation")
    _end_access(session, contract, term, grant, at, obligations, "ended_after_unpaid_grace")
    _complete(session, registry, at=at, result_type="enterprise_contract", result_id=contract.id)
    return contract, "inserted"


def _latest_completed_term(session, contract_id):
    return session.execute(
        select(EnterpriseContractVersion)
        .where(
            EnterpriseContractVersion.contract_id == contract_id,
            EnterpriseContractVersion.version_kind.in_(("initial", "renewal")),
            EnterpriseContractVersion.state == "completed",
        )
        .order_by(EnterpriseContractVersion.term_ends_at.desc())
    ).scalars().first()


def cancel_contract_version(
    session, *, command_id, billing_account_id, contract_id, version_id, reason, evidence_reference,
    actor_user_id, delivery_obligations,
):
    """Cancel a recorded or approved version that never took effect.

    A funded version is refused: unwinding a verified payment is a Phase 9
    refund decision, not a contract edit.
    """
    command_id = _text(command_id, "command_id", 128, identifier=True)
    reason = _text(reason, "reason", 2000)
    evidence = _text(evidence_reference, "evidence_reference", 255)
    obligations = _deliveries(delivery_obligations)
    _account, contract = _lock_contract(session, billing_account_id, contract_id)
    grant = _authorize(session, actor_user_id)
    version = _lock_version(session, contract, version_id)
    at = _now(session)
    registry, inserted = _claim(
        session, COMMAND_NAMESPACE, f"enterprise-contract:cancel:{version.id}",
        _fingerprint({"version": version.id, "reason": reason, "evidence": evidence}), at,
    )
    if not inserted:
        return _replay(session, registry, "enterprise_contract_version", EnterpriseContractVersion), "duplicate"
    if version.state not in ("recorded", "approved"):
        raise ContractError("only a version that never took effect can be cancelled")
    if session.execute(
        select(EnterpriseContractTermFunding.id).where(EnterpriseContractTermFunding.version_id == version.id)
    ).first() is not None:
        raise ContractPolicyRequiredError("a funded version is unwound through a refund decision, not cancellation")
    _transition(
        session, contract=contract, version=version, to_state="cancelled", transition="version_cancelled",
        grant=grant, at=at, evidence_reference=evidence, obligations=obligations, reason=reason,
    )
    if version.version_kind == "initial":
        _transition(
            session, contract=contract, version=None, to_state="cancelled", transition="cancelled",
            grant=grant, at=at, evidence_reference=evidence, obligations=obligations, reason=reason,
        )
    _complete(session, registry, at=at, result_type="enterprise_contract_version", result_id=version.id)
    return version, "inserted"


# ---------------------------------------------------------------------------
# Nonrenewal notices (30 calendar days)
# ---------------------------------------------------------------------------

def _notice(session, *, contract, term, kind, grant, at, evidence, obligations, registry, reverses=None):
    deadline = _stored_utc(term.term_ends_at) - timedelta(days=NONRENEWAL_NOTICE_DAYS)
    notice_id = str(uuid.uuid4())
    event_type = "enterprise_contract_nonrenewal_recorded" if kind == "nonrenewal" else "enterprise_contract_nonrenewal_reversed"
    domain_event, _messages, state = _record_event(session, _envelope(
        contract.billing_account_id, event_type, "enterprise_contract_notice", notice_id, at,
        [notice_id, contract.id, term.id, reverses.id if reverses else None],
    ), obligations)
    if state != "inserted":
        raise ContractConflictError("new contract notice reused an existing domain event")
    notice = EnterpriseContractNotice(
        id=notice_id, contract_id=contract.id, term_version_id=term.id, kind=kind,
        reverses_notice_id=reverses.id if reverses else None, received_at=at, deadline_at=deadline,
        timely=at <= deadline, evidence_reference=evidence, actor_user_id=grant.user_id,
        permission_grant_id=grant.id, idempotency_registry_id=registry.id, domain_event_id=domain_event.id,
    )
    session.add(notice)
    session.flush()
    return notice


def record_nonrenewal_notice(
    session, *, command_id, billing_account_id, contract_id, term_version_id, evidence_reference,
    actor_user_id, delivery_obligations,
):
    """Record a customer's nonrenewal notice as received now (database time).

    Timely only on or before 30 calendar days before the term ends. A late
    notice is recorded but does not stop a renewal. A notice never shortens
    current paid access. Legal sufficiency is not assessed here.
    """
    command_id = _text(command_id, "command_id", 128, identifier=True)
    evidence = _text(evidence_reference, "evidence_reference", 255)
    obligations = _deliveries(delivery_obligations)
    _account, contract = _lock_contract(session, billing_account_id, contract_id)
    grant = _authorize(session, actor_user_id)
    term = _lock_version(session, contract, term_version_id)
    at = _now(session)
    registry, inserted = _claim(
        session, COMMAND_NAMESPACE, f"enterprise-contract:nonrenewal:{term.id}:{command_id}",
        _fingerprint({"term": term.id, "evidence": evidence}), at,
    )
    if not inserted:
        return _replay(session, registry, "enterprise_contract_notice", EnterpriseContractNotice), "duplicate"
    if term.version_kind not in ("initial", "renewal") or term.state not in ("approved", "active"):
        raise ContractError("a nonrenewal notice applies to an approved or active term")
    if _effective_nonrenewal(session, term) is not None:
        raise ContractConflictError("a timely nonrenewal notice is already in effect for this term")
    notice = _notice(
        session, contract=contract, term=term, kind="nonrenewal", grant=grant, at=at, evidence=evidence,
        obligations=obligations, registry=registry,
    )
    _complete(session, registry, at=at, result_type="enterprise_contract_notice", result_id=notice.id)
    return notice, "inserted"


def reverse_nonrenewal_notice(
    session, *, command_id, billing_account_id, contract_id, notice_id, evidence_reference,
    actor_user_id, delivery_obligations,
):
    """Reverse an effective nonrenewal notice on or before its deadline."""
    command_id = _text(command_id, "command_id", 128, identifier=True)
    evidence = _text(evidence_reference, "evidence_reference", 255)
    obligations = _deliveries(delivery_obligations)
    _account, contract = _lock_contract(session, billing_account_id, contract_id)
    grant = _authorize(session, actor_user_id)
    notice = session.execute(
        select(EnterpriseContractNotice).where(EnterpriseContractNotice.id == _text(notice_id, "notice_id", 36))
        .with_for_update()
    ).scalar_one_or_none()
    if notice is None or notice.contract_id != contract.id:
        raise ContractError("notice is not available for this contract")
    at = _now(session)
    registry, inserted = _claim(
        session, COMMAND_NAMESPACE, f"enterprise-contract:nonrenewal-reversal:{notice.id}",
        _fingerprint({"notice": notice.id, "evidence": evidence}), at,
    )
    if not inserted:
        return _replay(session, registry, "enterprise_contract_notice", EnterpriseContractNotice), "duplicate"
    term = session.get(EnterpriseContractVersion, notice.term_version_id)
    if notice.kind != "nonrenewal" or _effective_nonrenewal(session, term) is None or \
            _effective_nonrenewal(session, term).id != notice.id:
        raise ContractError("only an effective nonrenewal notice can be reversed")
    if _clock(session) > _stored_utc(notice.deadline_at):
        raise ContractError("the nonrenewal deadline has passed")
    reversal = _notice(
        session, contract=contract, term=term, kind="nonrenewal_reversal", grant=grant, at=at,
        evidence=evidence, obligations=obligations, registry=registry, reverses=notice,
    )
    _complete(session, registry, at=at, result_type="enterprise_contract_notice", result_id=reversal.id)
    return reversal, "inserted"


# ---------------------------------------------------------------------------
# Funded versions awaiting a decision (B1 refund review; read-only)
# ---------------------------------------------------------------------------

def _holds_contract_permission(session, user_id):
    """Non-locking check of an explicit, unrevoked grant valid now (reads only)."""
    from .models_billing_phase10 import (
        PERMISSION_VERSION,
        BillingStaffPermissionGrant,
        BillingStaffPermissionRevocation,
    )
    now = _clock(session)
    grants = session.execute(
        select(BillingStaffPermissionGrant).where(
            BillingStaffPermissionGrant.user_id == user_id,
            BillingStaffPermissionGrant.permission == CONTRACT_PERMISSION,
            BillingStaffPermissionGrant.permission_version == PERMISSION_VERSION,
        )
    ).scalars().all()
    for grant in grants:
        ends = _stored_utc(grant.ends_at)
        if _stored_utc(grant.starts_at) <= now and (ends is None or now < ends) and session.execute(
            select(BillingStaffPermissionRevocation.id).where(BillingStaffPermissionRevocation.grant_id == grant.id)
        ).first() is None:
            return True
    return False


def _review_reason(session, contract, version, funding, at):
    term = session.get(EnterpriseContractVersion, version.term_version_id) if version.term_version_id else None
    if version.version_kind == "renewal" and _stored_utc(funding.paid_at) >= _grace_end(term):
        return "paid_after_grace"
    if term is not None and version.version_kind == "renewal" and _effective_nonrenewal(session, term) is not None:
        return "nonrenewal_in_effect"
    if version.version_kind == "amendment" and (term.state != "active" or at >= _stored_utc(term.term_ends_at)):
        return "amended_term_ended"
    if version.version_kind != "amendment" and at >= _activation_window_end(version):
        return "catch_up_policy_required"
    if contract.state in ("ended", "cancelled") and not (
        version.version_kind == "renewal" and _ended_by_grace_lapse(session, contract, term)
    ):
        return "contract_ended"
    return "awaiting_activation"


def funded_versions_for_review(session, *, billing_account_id, actor_user_id):
    """Pure read: one organization's funded contract versions that have not taken effect.

    Each row carries its verified payment evidence and why it is unresolved
    (``awaiting_activation`` can still be activated; every other reason
    needs a founder or refund decision under Phase 9). Only a holder of the
    explicit Enterprise contract permission may read it; nothing is locked,
    written, cancelled, or refunded here.
    """
    account_id = _text(billing_account_id, "billing_account_id", 36)
    if not _holds_contract_permission(session, _text(actor_user_id, "actor_user_id", 36)):
        raise ContractPermissionError("actor does not hold the explicit Enterprise contract permission")
    at = _clock(session)
    rows = session.execute(
        select(EnterpriseContractVersion, EnterpriseContractTermFunding, EnterpriseContract)
        .join(EnterpriseContractTermFunding, EnterpriseContractTermFunding.version_id == EnterpriseContractVersion.id)
        .join(EnterpriseContract, EnterpriseContract.id == EnterpriseContractVersion.contract_id)
        .outerjoin(EnterpriseContractActivation, EnterpriseContractActivation.version_id == EnterpriseContractVersion.id)
        .where(
            EnterpriseContractVersion.billing_account_id == account_id,
            EnterpriseContractTermFunding.billing_account_id == account_id,
            EnterpriseContractActivation.id.is_(None),
        )
        .order_by(EnterpriseContractTermFunding.paid_at, EnterpriseContractVersion.id)
    ).all()
    return [
        {
            "contract_id": contract.id, "version_id": version.id, "version_kind": version.version_kind,
            "version_state": version.state, "funding_id": funding.id,
            "financial_transaction_id": funding.financial_transaction_id,
            "financial_line_id": funding.financial_line_id, "amount_minor": int(funding.amount_minor),
            "currency": funding.currency, "paid_at": _stored_utc(funding.paid_at),
            "reason": _review_reason(session, contract, version, funding, at),
        }
        for version, funding, contract in rows
    ]


# ---------------------------------------------------------------------------
# Recorded access state (integration contract; enforcement deferred)
# ---------------------------------------------------------------------------

def _renewal_expected(session, term):
    return _effective_nonrenewal(session, term) is None and (
        term.renewal_mode == "automatic" or _live_renewal(session, term) is not None
    )


def contract_access_state(session, *, billing_account_id, at=None):
    """Pure read of the billing-recorded access state of an organization's contracts.

    ``paid``: an activated term is in force. ``read_only_grace``: the paid
    term has ended, a renewal is expected but unpaid, and it is within 15 days
    of the paid end; saved work stays readable but no new paid operation,
    credit, seat, or entitlement exists. ``read_only_retention``: paid access
    has ended; the retention-review date (paid end + 180 days) is a target
    subject to legal review and triggers nothing. ``none``: no contract
    applies. Paid access is judged from term dates, so a term that has ended
    is never reported as paid even before its completion is recorded. This
    function only reports state; the application-access workstream enforces it.
    """
    account_id = _text(billing_account_id, "billing_account_id", 36)
    at = _clock(session) if at is None else _utc(at, "at")
    rank = {"none": 0, "read_only_retention": 1, "read_only_grace": 2, "paid": 3}
    best = {"state": "none", "contract_id": None}
    contracts = session.execute(
        select(EnterpriseContract).where(EnterpriseContract.billing_account_id == account_id)
        .order_by(EnterpriseContract.created_at, EnterpriseContract.id)
    ).scalars().all()
    for contract in contracts:
        terms = session.execute(
            select(EnterpriseContractVersion)
            .join(EnterpriseContractActivation, EnterpriseContractActivation.version_id == EnterpriseContractVersion.id)
            .where(
                EnterpriseContractVersion.contract_id == contract.id,
                EnterpriseContractVersion.version_kind.in_(("initial", "renewal")),
                EnterpriseContractVersion.state.in_(("active", "completed")),
            )
            .order_by(EnterpriseContractVersion.term_ends_at.desc())
        ).scalars().all()
        if not terms:
            continue
        latest = terms[0]
        paid_end = _stored_utc(latest.term_ends_at)
        if _stored_utc(latest.term_starts_at) <= at < paid_end:
            candidate = {"state": "paid", "contract_id": contract.id, "paid_through": paid_end}
        elif at >= paid_end and contract.state != "ended" and _renewal_expected(session, latest) \
                and at < paid_end + timedelta(days=RENEWAL_GRACE_DAYS):
            candidate = {
                "state": "read_only_grace", "contract_id": contract.id,
                "paid_access_ended_at": paid_end,
                "grace_ends_at": paid_end + timedelta(days=RENEWAL_GRACE_DAYS),
            }
        elif at >= paid_end:
            ended = _stored_utc(contract.paid_access_ended_at) or paid_end
            candidate = {
                "state": "read_only_retention", "contract_id": contract.id,
                "paid_access_ended_at": ended,
                "retention_review_until": ended + timedelta(days=RETENTION_REVIEW_DAYS),
            }
        else:
            continue
        if rank[candidate["state"]] > rank[best["state"]]:
            best = candidate
    return best
