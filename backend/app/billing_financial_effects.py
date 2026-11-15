"""Inactive Phase 9 purchase funding and refund/dispute/recovery credit effects.

No live route, webhook, scheduler, or worker imports this module. Callers own
the transaction; nothing here commits or contacts a processor.

Authorities are unchanged:

* Phase 5.2 financial transactions and lines are read only.
* Phase 5.3 cases and case versions are recorded by
  ``billing_financial_cases.record_financial_case_event``; this module only
  links its credit effects to the accepted current version.
* Phase 3 is the only credit ledger. Every effect is an append-only entry
  written through ``billing_ledger.append_entry``.
* Phase 5.4 records the domain event and outbox obligations.

Lock order for every command: billing account (``lock_billing_account``), then
financial case, then credit lots in ascending ID order, then ledger appends
(which re-take the account lock they already hold and then the lot lock).

All D10 arithmetic uses exact integers. ``floor(U * R / P)`` is computed as
``(U * R) // P`` with nonnegative operands.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select

from .billing_allocations import (
    RecurringAllocationConflictError,
    RecurringAllocationRetryError,
    _claim_registry,
    _complete_registry_if_claimed,
)
from .billing_financial_cases import (
    FinancialCaseInvariantError,
    record_financial_case_event,
)
from .billing_ledger import CreditLedgerInvariantError, append_entry, lock_billing_account
from .billing_outbox import (
    BillingOutboxInvariantError,
    DomainEventConflictError,
    record_domain_event,
)
from .models import (
    BillingAccount,
    CreditLedgerEntry,
    CreditLot,
    CreditPeriod,
    EntitlementDefinition,
    FinancialCase,
    FinancialCaseEvent,
    FinancialCaseEventLedgerEntry,
    FinancialCaseEventLine,
    FinancialLine,
    FinancialTransaction,
    IdempotencyRegistry,
    RecurringCreditAllocation,
    UpgradeCreditAllocation,
)
from .models_billing_phase9 import (
    CreditPurchaseFunding,
    FinancialCaseCreditEffect,
    FinancialCaseLotEvaluation,
)


CONTRACT_VERSION = 1
PURCHASE_NAMESPACE = "credit_purchase_funding"
EVALUATION_NAMESPACE = "financial_case_evaluation"
EFFECT_NAMESPACE = "financial_case_credit_effect"
SERVICE_ACTOR_TYPES = frozenset({"system"})
INELIGIBLE_LINE_KINDS = frozenset({"tax", "fee", "discount"})
CREDIT_EFFECT_REFUND_STATES = frozenset({"refund_recorded"})
NO_CREDIT_EFFECT_REFUND_STATES = frozenset({"financial_only", "entitlement_reducing_review"})
CASE_EVENT_TYPES = {
    "refund_recorded": "refund_recorded",
    "financial_only": "refund_recorded",
    "entitlement_reducing_review": "refund_recorded",
    "opened": "dispute_opened",
    "pending": "dispute_pending",
    "won": "dispute_won",
    "lost": "dispute_lost",
}


class FinancialEffectError(ValueError):
    """Raised when a Phase 9 command violates its approved contract."""


class FinancialEffectConflictError(FinancialEffectError):
    """Raised when an idempotency identity is reused with different facts."""


class FinancialEffectRetryError(FinancialEffectError):
    """Raised when the command must be retried (concurrent claim or missing prerequisite)."""


class FinancialEffectPermissionError(FinancialEffectError):
    """Raised when the actor is not the authorized processor-evidence service."""


class FinancialEffectDependencyError(FinancialEffectError):
    """Raised when an approved product definition or adapter normalization is absent."""


class FinancialEffectPolicyRequiredError(FinancialEffectError):
    """Raised when the operation needs a commercial or policy decision not yet approved."""


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------

def _utc(value, field):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise FinancialEffectError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _stored_utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _text(value, field, maximum):
    if not isinstance(value, str) or not value.strip():
        raise FinancialEffectError(f"{field} must be a nonempty string")
    value = value.strip()
    if len(value) > maximum:
        raise FinancialEffectError(f"{field} is too long")
    return value


def _positive_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise FinancialEffectError(f"{field} must be a positive integer")
    return value


def _fingerprint(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _service_actor(actor_type, actor_id):
    actor_type = _text(actor_type, "actor_type", 40)
    actor_id = _text(actor_id, "actor_id", 255)
    if actor_type not in SERVICE_ACTOR_TYPES:
        # Customer billing roles, organization membership, and global-admin
        # identity grant no financial-adjustment authority. Only the trusted
        # processor-evidence service may apply verified financial facts.
        raise FinancialEffectPermissionError(
            "financial effects require the authorized processor-evidence service actor"
        )
    return actor_type, actor_id


def _deliveries(delivery_obligations):
    if not isinstance(delivery_obligations, (list, tuple)) or not delivery_obligations:
        raise FinancialEffectError("at least one delivery obligation is required for the domain event")
    return delivery_obligations


def _lock_account(session, billing_account_id):
    try:
        return lock_billing_account(session, billing_account_id)
    except CreditLedgerInvariantError as exc:
        raise FinancialEffectError("billing account is not available") from exc


def _claim(session, namespace, key, fingerprint, claimed_at):
    try:
        return _claim_registry(session, namespace, key, fingerprint, claimed_at)
    except RecurringAllocationConflictError as exc:
        raise FinancialEffectConflictError(
            "financial effect identity was reused with different facts"
        ) from exc
    except RecurringAllocationRetryError as exc:
        raise FinancialEffectRetryError(str(exc)) from exc


def _complete(session, registry, *, completed_at, result_type, result_id):
    try:
        _complete_registry_if_claimed(
            session, registry, completed_at=completed_at,
            result_type=result_type, result_id=result_id,
        )
    except RecurringAllocationConflictError as exc:
        raise FinancialEffectConflictError(str(exc)) from exc


def _record_event(session, event, delivery_obligations):
    try:
        return record_domain_event(session, event, delivery_obligations)
    except DomainEventConflictError as exc:
        raise FinancialEffectConflictError(str(exc)) from exc
    except BillingOutboxInvariantError as exc:
        raise FinancialEffectError(str(exc)) from exc


def _append(session, entry):
    try:
        return append_entry(session, entry)
    except CreditLedgerInvariantError as exc:
        raise FinancialEffectError(str(exc)) from exc


def _net_principal(line):
    return int(line.principal_minor) + int(line.discount_minor)


def _lot_balance(session, lot_id):
    available, held = session.execute(
        select(
            func.coalesce(func.sum(CreditLedgerEntry.available_delta), 0),
            func.coalesce(func.sum(CreditLedgerEntry.held_delta), 0),
        ).where(CreditLedgerEntry.lot_id == lot_id)
    ).one()
    return int(available or 0), int(held or 0)


def _lot_expired(lot, at):
    expires_at = _stored_utc(lot.expires_at)
    return expires_at is not None and expires_at <= at


# ---------------------------------------------------------------------------
# Purchase funding (D06 credit_pack_purchase; D13 purchase key; D14.10)
# ---------------------------------------------------------------------------

def _purchase_terms(definition, paid_at):
    """Validate the approved, versioned v1 purchase definition. Never guess values."""
    if definition.approved_at is None or not definition.approval_evidence_reference:
        raise FinancialEffectDependencyError("purchase definition is not approved")
    effective_at = _stored_utc(definition.effective_at)
    retired_at = _stored_utc(definition.retired_at)
    if effective_at is None or effective_at > paid_at:
        raise FinancialEffectDependencyError("purchase definition is not effective at payment time")
    if retired_at is not None and retired_at <= paid_at:
        raise FinancialEffectDependencyError("purchase definition is retired at payment time")
    policy = definition.funding_policy_json
    if not isinstance(policy, dict) or policy.get("schema_version") != 1 or policy.get("period_kind") != "none":
        raise FinancialEffectDependencyError("definition is not an approved one-time purchase definition")
    terms = policy.get("purchase")
    if not isinstance(terms, dict) or terms.get("schema_version") != 1:
        raise FinancialEffectDependencyError("definition has no approved v1 purchase terms")
    if terms.get("line_kind") != "credit_pack":
        raise FinancialEffectDependencyError("purchase terms do not describe a credit pack")
    for field in ("source_type", "source_id", "currency"):
        if not isinstance(terms.get(field), str) or not terms[field].strip():
            raise FinancialEffectDependencyError(f"purchase terms require {field}")
    for field in ("unit_principal_minor", "quantity"):
        value = terms.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise FinancialEffectDependencyError(f"purchase terms require a positive integer {field}")
    if terms.get("expiry") != {"kind": "none"}:
        # D06: purchased credit does not expire unless an approved offer says
        # otherwise. No approved purchased-credit expiry rule exists yet.
        raise FinancialEffectDependencyError("purchased-credit expiry terms are not approved")
    components = terms.get("components")
    if not isinstance(components, list) or not components:
        raise FinancialEffectDependencyError("purchase terms require funding components")
    normalized = []
    seen = set()
    for component in components:
        if not isinstance(component, dict) or set(component) != {"component", "credit_amount"}:
            raise FinancialEffectDependencyError("purchase component shape is invalid")
        name = component["component"]
        amount = component["credit_amount"]
        if not isinstance(name, str) or not name.strip() or ":" in name or len(name) > 64:
            raise FinancialEffectDependencyError("purchase component name is invalid")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0 or amount > 2**63 - 1:
            raise FinancialEffectDependencyError("purchase component credit amount is invalid")
        if name in seen:
            raise FinancialEffectDependencyError("purchase component is duplicated")
        seen.add(name)
        normalized.append((name, amount))
    total = policy.get("credit_amount")
    if isinstance(total, bool) or not isinstance(total, int) or total != sum(a for _n, a in normalized):
        raise FinancialEffectDependencyError("purchase components do not equal the approved credit amount")
    return terms, sorted(normalized)


def fund_credit_purchase(
    session, *, billing_account_id, financial_line_id, entitlement_definition_id,
    funded_at, actor_type, actor_id, delivery_obligations,
):
    """Fund one paid credit-pack line from its approved purchase definition.

    Returns ``(fundings, lots, 'inserted'|'duplicate')``. Webhook replay,
    browser confirmation, and concurrent commands share the canonical
    ``purchase:<payment_line_id>:<component>`` identity and converge.
    """
    account_id = _text(billing_account_id, "billing_account_id", 36)
    line_id = _text(financial_line_id, "financial_line_id", 36)
    definition_id = _text(entitlement_definition_id, "entitlement_definition_id", 36)
    funded_at = _utc(funded_at, "funded_at")
    actor_type, actor_id = _service_actor(actor_type, actor_id)
    delivery_obligations = _deliveries(delivery_obligations)

    account = _lock_account(session, account_id)
    row = session.execute(
        select(FinancialLine, FinancialTransaction)
        .join(FinancialTransaction, FinancialTransaction.id == FinancialLine.financial_transaction_id)
        .where(FinancialLine.id == line_id)
    ).one_or_none()
    if row is None or row[1].billing_account_id != account.id:
        # One message for "missing" and "another account" so no other
        # organization's financial objects are disclosed.
        raise FinancialEffectError("financial line is not available for this billing account")
    line, transaction = row
    paid_at = _stored_utc(transaction.effective_at)
    if (
        transaction.kind != "payment"
        or int(transaction.principal_minor) <= 0
        or transaction.currency != account.currency
        or line.currency != account.currency
    ):
        raise FinancialEffectError("purchase funding requires a successful payment in the account currency")
    if line.line_kind != "credit_pack" or line.subscription_id is not None or line.entitlement_instance_id is not None:
        raise FinancialEffectError("purchase funding requires a one-time credit-pack payment line")
    if int(line.principal_minor) <= 0 or int(line.discount_minor) > 0 or _net_principal(line) <= 0:
        raise FinancialEffectError("purchase line principal is invalid")
    if funded_at < paid_at:
        raise FinancialEffectError("purchase cannot be funded before its payment")

    definition = session.get(EntitlementDefinition, definition_id)
    if definition is None:
        raise FinancialEffectDependencyError("purchase definition is not available")
    terms, components = _purchase_terms(definition, paid_at)
    if (
        line.source_type != terms["source_type"]
        or line.source_id != terms["source_id"]
        or line.currency != terms["currency"]
        or int(line.quantity) != terms["quantity"]
        or int(line.principal_minor) != terms["unit_principal_minor"] * terms["quantity"]
    ):
        # FinancialLine.quantity is compared to the approved term only; it is
        # never interpreted as credits. Multi-quantity normalization is a
        # future payment-adapter contract.
        raise FinancialEffectError("payment line does not match the approved purchase definition")

    registries = []
    any_inserted = False
    for name, amount in components:
        key = f"purchase:{line.id}:{name}"
        fingerprint = _fingerprint({
            "billing_account_id": account.id, "financial_transaction_id": transaction.id,
            "financial_line_id": line.id, "entitlement_definition_id": definition.id,
            "package_component": name, "credit_amount": amount,
            "paid_at": paid_at.isoformat(), "contract_version": CONTRACT_VERSION,
        })
        registry, inserted = _claim(session, PURCHASE_NAMESPACE, key, fingerprint, funded_at)
        registries.append((name, amount, key, fingerprint, registry, inserted))
        any_inserted = any_inserted or inserted

    if not any_inserted:
        fundings = []
        for name, _amount, _key, _fp, registry, _inserted in registries:
            funding = session.execute(
                select(CreditPurchaseFunding).where(CreditPurchaseFunding.idempotency_registry_id == registry.id)
            ).scalar_one_or_none()
            if registry.state != "completed" or funding is None:
                raise FinancialEffectRetryError("purchase funding is already in progress")
            fundings.append(funding)
        event, _messages, _state = _record_event(
            session, _purchase_event(account.id, line, transaction, definition, fundings, paid_at),
            delivery_obligations,
        )
        if any(funding.domain_event_id != event.id for funding in fundings):
            raise FinancialEffectConflictError("purchase funding is bound to another domain event")
        lots = [session.get(CreditLot, funding.lot_id) for funding in fundings]
        return fundings, lots, "duplicate"
    if not all(inserted for *_rest, inserted in registries):
        raise FinancialEffectRetryError("purchase funding components raced; retry the transaction")

    funding_ids = {name: str(uuid.uuid4()) for name, *_rest in registries}
    planned = [SimplePurchase(funding_ids[name], name) for name, *_rest in registries]
    event, _messages, event_state = _record_event(
        session, _purchase_event(account.id, line, transaction, definition, planned, paid_at),
        delivery_obligations,
    )
    if event_state != "inserted":
        raise FinancialEffectConflictError("new purchase funding reused an existing domain event")

    fundings, lots = [], []
    for name, amount, key, fingerprint, registry, _inserted in registries:
        funding_id = funding_ids[name]
        lot_id, entry_id = str(uuid.uuid4()), str(uuid.uuid4())
        funding = CreditPurchaseFunding(
            id=funding_id, billing_account_id=account.id,
            financial_transaction_id=transaction.id, financial_line_id=line.id,
            entitlement_definition_id=definition.id, package_component=name,
            funding_key=key, request_fingerprint=fingerprint, credit_amount=amount,
            paid_at=paid_at, lot_id=lot_id, grant_entry_id=entry_id,
            idempotency_registry_id=registry.id, domain_event_id=event.id,
            contract_version=CONTRACT_VERSION, actor_type=actor_type, actor_id=actor_id,
        )
        session.add(funding)
        session.flush()
        lot = CreditLot(
            id=lot_id, billing_account_id=account.id,
            source_type="credit_pack_purchase", source_id=funding_id,
            original_amount=amount, available_at=paid_at, expires_at=None,
            origin_evidence_json={
                "credit_purchase_funding_id": funding_id,
                "financial_line_id": line.id,
                "entitlement_definition_id": definition.id,
                "package_component": name,
            },
        )
        session.add(lot)
        session.flush()
        _append(session, CreditLedgerEntry(
            id=entry_id, billing_account_id=account.id, lot_id=lot_id,
            entry_type="grant", available_delta=amount, held_delta=0,
            idempotency_registry_id=registry.id, effective_at=paid_at,
            actor_type=actor_type, actor_id=actor_id, reason_code="credit_pack_purchase",
            evidence_json={"credit_purchase_funding_id": funding_id, "financial_line_id": line.id},
        ))
        _complete(session, registry, completed_at=funded_at,
                  result_type="credit_purchase_funding", result_id=funding_id)
        fundings.append(funding)
        lots.append(lot)
    session.flush()
    return fundings, lots, "inserted"


class SimplePurchase:
    """Planned funding identity used before rows exist, so replay references match."""

    def __init__(self, funding_id, component):
        self.id = funding_id
        self.package_component = component


def _purchase_event(account_id, line, transaction, definition, fundings, paid_at):
    references = [line.id, transaction.id, definition.id, *(funding.id for funding in fundings)]
    return {
        "billing_account_id": account_id,
        "event_key": f"credit_purchase_funded:{line.id}",
        "event_type": "credit_purchase_funded",
        "aggregate_type": "financial_line",
        "aggregate_id": line.id,
        "occurred_at": paid_at,
        "reference_ids": references,
    }


# ---------------------------------------------------------------------------
# Mixed-invoice attribution (D10)
# ---------------------------------------------------------------------------

def proportional_case_attribution(
    session, *, billing_account_id, source_financial_transaction_id, cumulative_principal_minor,
):
    """Return exact line allocations for a cumulative refund/dispute principal.

    Tax, fee, and discount lines never receive principal. Line principal is
    evaluated after its line-level discount. Allocation is returned only when
    it is unambiguous:

    * zero principal: no lines;
    * one eligible line: that line;
    * the full eligible principal: every eligible line in full;
    * a partial amount across several subscription lines whose proportional
      shares divide exactly.

    Every other partial split across several lines needs the deterministic
    residual/tie-break rule that Phase 5.3 deferred to Phase 9. No such rule is
    approved, so those inputs fail closed with ``FinancialEffectPolicyRequiredError``.
    """
    account_id = _text(billing_account_id, "billing_account_id", 36)
    source_id = _text(source_financial_transaction_id, "source_financial_transaction_id", 36)
    amount = cumulative_principal_minor
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise FinancialEffectError("cumulative principal must be a nonnegative integer")
    source = session.get(FinancialTransaction, source_id)
    if source is None or source.billing_account_id != account_id or source.kind not in {"invoice", "payment"}:
        raise FinancialEffectError("financial source is not available for this billing account")
    lines = session.execute(
        select(FinancialLine)
        .where(FinancialLine.financial_transaction_id == source.id)
        .order_by(FinancialLine.id)
    ).scalars().all()
    eligible = [
        line for line in lines
        if line.line_kind not in INELIGIBLE_LINE_KINDS and _net_principal(line) > 0
    ]
    total = sum(_net_principal(line) for line in eligible)
    if amount > total:
        raise FinancialEffectError("cumulative principal exceeds eligible source principal")
    if amount == 0:
        return []
    if amount == total:
        return [{"financial_line_id": line.id, "attributed_principal_minor": _net_principal(line)} for line in eligible]
    if len(eligible) == 1:
        return [{"financial_line_id": eligible[0].id, "attributed_principal_minor": amount}]
    if all(line.line_kind == "subscription" for line in eligible):
        shares = []
        for line in eligible:
            numerator = amount * _net_principal(line)
            if numerator % total:
                break
            shares.append({"financial_line_id": line.id, "attributed_principal_minor": numerator // total})
        else:
            return shares
    raise FinancialEffectPolicyRequiredError(
        "partial principal across several lines needs an approved residual allocation rule"
    )


# ---------------------------------------------------------------------------
# Case effects (D10 refund, dispute, recovery)
# ---------------------------------------------------------------------------

class _LotFunding:
    __slots__ = ("lot", "kind", "reference_id")

    def __init__(self, lot, kind, reference_id):
        self.lot = lot
        self.kind = kind
        self.reference_id = reference_id


def _funded_lots(session, account_id, line):
    """Lots funded by exactly this financial line, through an existing authority."""
    found = []
    if line.line_kind == "credit_pack":
        for funding in session.execute(
            select(CreditPurchaseFunding).where(CreditPurchaseFunding.financial_line_id == line.id)
        ).scalars():
            found.append((funding.lot_id, "credit_purchase", funding.id))
    elif line.line_kind == "subscription":
        for allocation, lot_id in session.execute(
            select(RecurringCreditAllocation, CreditPeriod.funded_lot_id)
            .join(CreditPeriod, CreditPeriod.id == RecurringCreditAllocation.credit_period_id)
            .where(RecurringCreditAllocation.financial_line_id == line.id)
        ).all():
            if lot_id:
                found.append((lot_id, "recurring_allocation", allocation.id))
        for upgrade in session.execute(
            select(UpgradeCreditAllocation).where(
                UpgradeCreditAllocation.financial_line_id == line.id,
                UpgradeCreditAllocation.funded_lot_id.is_not(None),
            )
        ).scalars():
            found.append((upgrade.funded_lot_id, "upgrade_allocation", upgrade.id))
    found.sort(key=lambda item: item[0])
    lots = []
    for lot_id, kind, reference_id in found:
        lot = session.execute(
            select(CreditLot).where(CreditLot.id == lot_id).with_for_update()
        ).scalar_one()
        if lot.billing_account_id != account_id:
            raise FinancialEffectError("funded lot does not belong to the case billing account")
        lots.append(_LotFunding(lot, kind, reference_id))
    return lots


def _case_effects(session, case_id, lot_id, effect_type):
    return session.execute(
        select(FinancialCaseCreditEffect, CreditLedgerEntry)
        .join(CreditLedgerEntry, CreditLedgerEntry.id == FinancialCaseCreditEffect.credit_ledger_entry_id)
        .where(
            FinancialCaseCreditEffect.financial_case_id == case_id,
            FinancialCaseCreditEffect.lot_id == lot_id,
            FinancialCaseCreditEffect.effect_type == effect_type,
        )
        .order_by(CreditLedgerEntry.created_at, CreditLedgerEntry.id)
    ).all()


def _consumed_against(session, entry_ids, entry_types):
    if not entry_ids:
        return {}
    rows = session.execute(
        select(CreditLedgerEntry.related_entry_id, CreditLedgerEntry.entry_type,
               CreditLedgerEntry.available_delta, CreditLedgerEntry.held_delta)
        .where(
            CreditLedgerEntry.related_entry_id.in_(entry_ids),
            CreditLedgerEntry.entry_type.in_(entry_types),
        )
    ).all()
    consumed = {}
    for related_id, entry_type, available_delta, held_delta in rows:
        bucket = consumed.setdefault(related_id, {})
        magnitude = int(available_delta) if entry_type == "recovery" else -int(held_delta)
        bucket[entry_type] = bucket.get(entry_type, 0) + magnitude
    return consumed


class _CaseLotState:
    """Applied state of one case on one lot, derived only from immutable evidence."""

    def __init__(self, session, case_id, lot_id):
        self.live_holds = []        # [(hold_entry, remaining)]
        self.expired_from_holds = 0
        self.reversals = []         # [(reversal_entry, unrecovered)]
        holds = [entry for _effect, entry in _case_effects(session, case_id, lot_id, "hold")]
        consumed = _consumed_against(
            session, [entry.id for entry in holds], ("release", "dispute_reversal", "expiration"),
        )
        for entry in holds:
            used = consumed.get(entry.id, {})
            remaining = int(entry.held_delta) - sum(used.values())
            self.expired_from_holds += used.get("expiration", 0)
            if remaining > 0:
                self.live_holds.append((entry, remaining))
        reversals = [entry for _effect, entry in _case_effects(session, case_id, lot_id, "reversal")]
        recovered = _consumed_against(session, [entry.id for entry in reversals], ("recovery",))
        for entry in reversals:
            magnitude = -int(entry.available_delta) if entry.entry_type == "refund_reversal" else -int(entry.held_delta)
            left = magnitude - recovered.get(entry.id, {}).get("recovery", 0)
            if left > 0:
                self.reversals.append((entry, left, recovered.get(entry.id, {}).get("recovery", 0)))
        self.unrestorable = int(session.execute(
            select(func.coalesce(func.sum(FinancialCaseLotEvaluation.unrestorable_recovery_amount), 0))
            .where(
                FinancialCaseLotEvaluation.financial_case_id == case_id,
                FinancialCaseLotEvaluation.lot_id == lot_id,
            )
        ).scalar_one() or 0)

    @property
    def held(self):
        return sum(amount for _entry, amount in self.live_holds)

    @property
    def reversed(self):
        return max(0, sum(amount for _entry, amount, _done in self.reversals) - self.unrestorable)


def _prior_attribution(session, case_id, lot_id):
    """Attribution of the latest previously evaluated version of this case on this lot.

    Versions are ordered by the Phase 5.3 acceptance order: the recorder only
    accepts a version whose ``(effective_at, received_at)`` is strictly later
    than the case's current one, so that pair is unique and increasing per
    case. Row creation time and random IDs are never used as the version order.
    """
    previous = session.execute(
        select(FinancialCaseLotEvaluation)
        .join(FinancialCaseEvent, FinancialCaseEvent.id == FinancialCaseLotEvaluation.financial_case_event_id)
        .where(
            FinancialCaseLotEvaluation.financial_case_id == case_id,
            FinancialCaseLotEvaluation.lot_id == lot_id,
        )
        .order_by(FinancialCaseEvent.effective_at.desc(), FinancialCaseEvent.received_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return 0 if previous is None else int(previous.attributed_principal_minor)


def _current_refund_attribution(session, line_id, *, exclude_case_id=None):
    """Cumulative refunded principal on a line across all current credit-affecting refund cases."""
    query = (
        select(func.coalesce(func.sum(FinancialCaseEventLine.attributed_principal_minor), 0))
        .select_from(FinancialCaseEventLine)
        .join(FinancialCase, FinancialCase.current_event_id == FinancialCaseEventLine.financial_case_event_id)
        .where(
            FinancialCaseEventLine.financial_line_id == line_id,
            FinancialCase.case_type == "refund",
            FinancialCase.state.in_(sorted(CREDIT_EFFECT_REFUND_STATES)),
        )
    )
    if exclude_case_id is not None:
        query = query.where(FinancialCase.id != exclude_case_id)
    return int(session.execute(query).scalar_one() or 0)


def _refund_reversed_on_lot(session, lot_id, *, exclude_case_id):
    total = 0
    case_ids = session.execute(
        select(FinancialCaseCreditEffect.financial_case_id).distinct().where(
            FinancialCaseCreditEffect.lot_id == lot_id,
            FinancialCaseCreditEffect.effect_type == "reversal",
            FinancialCaseCreditEffect.financial_case_id != exclude_case_id,
        )
    ).scalars().all()
    for other_case_id in case_ids:
        other = session.get(FinancialCase, other_case_id)
        if other.case_type == "refund":
            total += _CaseLotState(session, other_case_id, lot_id).reversed
    return total


def _grant_entry(session, lot_id):
    return session.execute(
        select(CreditLedgerEntry).where(
            CreditLedgerEntry.lot_id == lot_id,
            CreditLedgerEntry.entry_type.in_(("grant", "migration_opening")),
        )
    ).scalar_one()


def _plan_refund(case, event_cumulative, line, lot, state, *, available, prior_r, r_case, r_other, x_other):
    p = _net_principal(line)
    if r_case == 0:
        # This refund no longer attributes the line (for example a refund that
        # failed or was cancelled): restore what this case reversed, nothing else.
        return {"unused_basis": available + state.reversed + x_other, "target": 0, "recover": state.reversed}
    if r_case < prior_r:
        raise FinancialEffectPolicyRequiredError(
            "a partial reduction of a refunded amount needs an approved recovery rule"
        )
    r_total = min(p, r_case + r_other)
    x_all = state.reversed + x_other
    unused = available + x_all
    target = (unused * r_total) // p
    new_reversal = max(0, target - x_all)
    return {"unused_basis": unused, "target": target, "reverse": min(new_reversal, available)}


def _plan_dispute(case_state, line, lot, state, *, available, prior_r, r_case, restorable):
    p = _net_principal(line)
    held, reversed_ = state.held, state.reversed
    unused = available + held + reversed_
    target = (unused * r_case) // p
    plan = {"unused_basis": unused, "target": target}
    if case_state == "won" or r_case == 0:
        plan["release"] = held
        plan["recover"] = reversed_
        return plan
    if r_case < prior_r:
        raise FinancialEffectPolicyRequiredError(
            "a partial reduction of a disputed amount needs an approved recovery rule"
        )
    # Applied value never shrinks while the dispute principal does not shrink.
    desired = max(target, held + reversed_)
    if case_state in {"opened", "pending"}:
        pool = available
        if reversed_:
            # Reopened after a loss: the reversed value returns to the hold it
            # came from (recovery, then hold). Expired value cannot be re-held.
            plan["recover"] = reversed_
            if restorable:
                pool += reversed_
        plan["hold"] = min(max(0, desired - held), pool)
        return plan
    if case_state == "lost":
        top_up = min(max(0, desired - held - reversed_), available)
        plan["hold"] = top_up
        plan["reverse"] = held + top_up
        attributable = (int(lot.original_amount) * r_case) // p
        plan["absorbed_total"] = max(
            0, attributable - (reversed_ + held + top_up) - state.expired_from_holds,
        )
        return plan
    raise FinancialEffectError("unsupported dispute state")


def _effect_registry(session, key, facts, at, *, allow_applied=False):
    """Claim one ledger-effect identity.

    Only a refund reversal may legitimately find its D13 identity already used:
    a later version at the same cumulative principal must not reverse again, so
    ``allow_applied`` returns ``None`` for it. Every other identity includes
    the case version or cumulative recovery, so reuse is a conflict.
    """
    registry, inserted = _claim(session, EFFECT_NAMESPACE, key, _fingerprint(facts), at)
    if inserted:
        return registry
    if registry.state == "completed" and allow_applied:
        # The D13 refund key is reused only by a genuine replay of a reversal
        # that is still in force. If that reversal was later recovered (for
        # example 500 -> 0 -> 500), skipping would report the target as met
        # while no value is reversed, and a new key scheme is not approved.
        recovered = session.execute(
            select(func.coalesce(func.sum(CreditLedgerEntry.available_delta), 0)).where(
                CreditLedgerEntry.related_entry_id == registry.result_id,
                CreditLedgerEntry.entry_type == "recovery",
            )
        ).scalar_one()
        if int(recovered or 0) > 0:
            raise FinancialEffectPolicyRequiredError(
                "re-refunding a previously recovered cumulative amount needs an approved rule"
            )
        return None
    if registry.state == "completed":
        raise FinancialEffectConflictError("financial case effect identity was already used")
    raise FinancialEffectRetryError("financial case effect is already in progress")


def _write_effect(
    session, *, evaluation, case, event, lot, entry_type, effect_type, amount,
    related_entry_id, registry, effective_at, actor_type, actor_id, reason_code,
):
    available_delta, held_delta = {
        "dispute_hold": (-amount, amount),
        "release": (amount, -amount),
        "dispute_reversal": (0, -amount),
        "refund_reversal": (-amount, 0),
        "recovery": (amount, 0),
    }[entry_type]
    entry = _append(session, CreditLedgerEntry(
        id=str(uuid.uuid4()), billing_account_id=case.billing_account_id, lot_id=lot.id,
        entry_type=entry_type, available_delta=available_delta, held_delta=held_delta,
        related_entry_id=related_entry_id, idempotency_registry_id=registry.id,
        effective_at=effective_at, actor_type=actor_type, actor_id=actor_id,
        reason_code=reason_code,
        evidence_json={
            "financial_case_id": case.id, "financial_case_event_id": event.id,
            "financial_case_lot_evaluation_id": evaluation.id,
        },
    ))
    session.add(FinancialCaseCreditEffect(
        id=str(uuid.uuid4()), evaluation_id=evaluation.id,
        billing_account_id=case.billing_account_id, financial_case_id=case.id,
        lot_id=lot.id, credit_ledger_entry_id=entry.id, effect_type=effect_type, amount=amount,
    ))
    session.add(FinancialCaseEventLedgerEntry(
        financial_case_event_id=event.id, credit_ledger_entry_id=entry.id, effect_type=effect_type,
    ))
    session.flush()
    _complete(session, registry, completed_at=effective_at,
              result_type="credit_ledger_entry", result_id=entry.id)
    return entry


def _case_event(case, event):
    return {
        "billing_account_id": case.billing_account_id,
        "event_key": f"financial_case_version_applied:{event.id}",
        "event_type": CASE_EVENT_TYPES[event.state],
        "aggregate_type": "financial_case",
        "aggregate_id": case.id,
        "occurred_at": _stored_utc(event.effective_at),
        "reference_ids": [case.id, event.id, case.source_financial_transaction_id],
    }


def apply_financial_case_effects(
    session, *, billing_account_id, financial_case_id, applied_at,
    actor_type, actor_id, delivery_obligations,
):
    """Apply the credit effects of a case's current accepted version.

    Safe to repeat: each (case version, lot) is evaluated at most once, and a
    repeat call evaluates only lots funded after the earlier call. Returns
    ``(case, event, evaluations)`` where ``evaluations`` lists the new rows.
    """
    account_id = _text(billing_account_id, "billing_account_id", 36)
    case_id = _text(financial_case_id, "financial_case_id", 36)
    applied_at = _utc(applied_at, "applied_at")
    actor_type, actor_id = _service_actor(actor_type, actor_id)
    delivery_obligations = _deliveries(delivery_obligations)

    _lock_account(session, account_id)
    case = session.execute(
        select(FinancialCase).where(FinancialCase.id == case_id).with_for_update()
    ).scalar_one_or_none()
    if case is None or case.billing_account_id != account_id:
        raise FinancialEffectError("financial case is not available for this billing account")
    event = session.get(FinancialCaseEvent, case.current_event_id)
    if event is None or event.financial_case_id != case.id:
        raise FinancialEffectError("financial case has no accepted current version")
    domain_event, _messages, _state = _record_event(session, _case_event(case, event), delivery_obligations)

    if case.case_type == "refund" and case.state in NO_CREDIT_EFFECT_REFUND_STATES:
        # D10: financial-only never changes capabilities or funded credits. An
        # entitlement-reducing disposition names its own period, capabilities
        # and credit treatment through an authorized review; no such authority
        # or credit treatment is approved, so no automatic effect is applied.
        prior_effects = session.execute(
            select(func.count()).select_from(FinancialCaseCreditEffect)
            .where(FinancialCaseCreditEffect.financial_case_id == case.id)
        ).scalar_one()
        if prior_effects:
            raise FinancialEffectPolicyRequiredError(
                "changing a refund with applied credit effects to a no-credit disposition needs a decision"
            )
        return case, event, []

    source_lines = {
        line.id: line for line in session.execute(
            select(FinancialLine)
            .where(FinancialLine.financial_transaction_id == case.source_financial_transaction_id)
        ).scalars()
    }
    attributions = {
        row.financial_line_id: int(row.attributed_principal_minor)
        for row in session.execute(
            select(FinancialCaseEventLine).where(FinancialCaseEventLine.financial_case_event_id == event.id)
        ).scalars()
    }
    previously = set(session.execute(
        select(FinancialCaseLotEvaluation.financial_line_id).distinct()
        .where(FinancialCaseLotEvaluation.financial_case_id == case.id)
    ).scalars())
    evaluations = []
    for line_id in sorted(set(attributions) | previously):
        line = source_lines.get(line_id)
        if line is None:
            raise FinancialEffectError("case attribution does not reference its source transaction")
        if line.line_kind in INELIGIBLE_LINE_KINDS:
            continue
        p = _net_principal(line)
        if p <= 0:
            raise FinancialEffectError("source line has no eligible principal")
        r_case = attributions.get(line_id, 0)
        if case.case_type == "refund" and line.line_kind not in {"credit_pack"}:
            # Subscription, seat, and other refunds carry an explicit
            # disposition (Phase 5.3); their entitlement effects are not
            # automatic. Only one-time credit-pack refunds reverse credits.
            continue
        if case.case_type == "dispute" and line.line_kind not in {"credit_pack", "subscription"}:
            continue
        lots = _funded_lots(session, account_id, line)
        if not lots and line.line_kind == "credit_pack" and r_case > 0:
            # D14.8: attribution must resolve before a credit-affecting
            # command. The purchase has not been funded yet; retry later.
            raise FinancialEffectRetryError("credit-pack source line has not been funded yet")
        for funded in lots:
            evaluation = _evaluate_lot(
                session, case=case, event=event, line=line, funded=funded, r_case=r_case,
                applied_at=applied_at, actor_type=actor_type, actor_id=actor_id,
            )
            if evaluation is not None:
                evaluations.append(evaluation)
    if domain_event.aggregate_id != case.id:
        raise FinancialEffectConflictError("case event aggregate does not match")
    session.flush()
    return case, event, evaluations


def _evaluate_lot(session, *, case, event, line, funded, r_case, applied_at, actor_type, actor_id):
    lot = funded.lot
    key = f"financial-case-evaluation:{event.id}:{lot.id}"
    if session.execute(
        select(FinancialCaseLotEvaluation.id).where(FinancialCaseLotEvaluation.evaluation_key == key)
    ).scalar_one_or_none():
        return None
    available_raw, _held_raw = _lot_balance(session, lot.id)
    expired = _lot_expired(lot, applied_at)
    available = 0 if expired else available_raw
    state = _CaseLotState(session, case.id, lot.id)
    prior_r = _prior_attribution(session, case.id, lot.id)
    if case.case_type == "refund":
        plan = _plan_refund(
            case, case.cumulative_principal_minor, line, lot, state,
            available=available, prior_r=prior_r, r_case=r_case,
            r_other=_current_refund_attribution(session, line.id, exclude_case_id=case.id),
            x_other=_refund_reversed_on_lot(session, lot.id, exclude_case_id=case.id),
        )
    else:
        plan = _plan_dispute(
            case.state, line, lot, state, available=available, prior_r=prior_r,
            r_case=r_case, restorable=not expired,
        )
    recover = plan.get("recover", 0)
    restored = 0 if expired else recover
    unrestorable = recover - restored

    # Resolve each ledger identity before writing evidence so the evaluation
    # records exactly what was applied (an identity already used at the same
    # cumulative state is never applied twice).
    effective_at = applied_at
    common = {"financial_case_id": case.id, "lot_id": lot.id}
    steps = []
    if restored:
        remaining = restored
        for reversal_entry, left, already in state.reversals:
            if not remaining:
                break
            amount = min(left, remaining)
            cumulative = already + amount
            registry = _effect_registry(session, (
                f"recovery:{case.case_object_id}:{reversal_entry.id}:{cumulative}"
            ), {**common, "effect": "recovery", "related_entry_id": reversal_entry.id}, applied_at)
            if registry is not None:
                steps.append(("recovery", "recovery", amount, reversal_entry.id, registry))
            remaining -= amount
    if plan.get("release"):
        remaining = plan["release"]
        for hold_entry, left in state.live_holds:
            if not remaining:
                break
            amount = min(left, remaining)
            registry = _effect_registry(session, (
                f"dispute:{case.case_object_id}:{event.external_version}:{lot.id}:release:{hold_entry.id}"
            ), {**common, "effect": "release", "related_entry_id": hold_entry.id}, applied_at)
            if registry is not None:
                steps.append(("release", "release", amount, hold_entry.id, registry))
            remaining -= amount
    if plan.get("hold"):
        registry = _effect_registry(session, (
            f"dispute:{case.case_object_id}:{event.external_version}:{lot.id}:hold"
        ), {**common, "effect": "hold"}, applied_at)
        if registry is not None:
            steps.append(("dispute_hold", "hold", plan["hold"], None, registry))
    if plan.get("reverse"):
        if case.case_type == "refund":
            registry = _effect_registry(session, (
                f"refund:{case.case_object_id}:{case.cumulative_principal_minor}:{lot.id}"
            ), {**common, "effect": "reversal"}, applied_at, allow_applied=True)
            if registry is not None:
                steps.append(("refund_reversal", "reversal", plan["reverse"], _grant_entry(session, lot.id).id, registry))
        else:
            steps.append(("dispute_reversal_all", "reversal", plan["reverse"], None, None))

    applied = {"hold": 0, "release": 0, "reversal": 0, "recovery": 0}
    for entry_type, effect_type, amount, _related, _registry in steps:
        if entry_type != "dispute_reversal_all":
            applied[effect_type] += amount
    if any(step[0] == "dispute_reversal_all" for step in steps):
        applied["reversal"] = plan["reverse"]

    evaluation_registry, inserted = _claim(
        session, EVALUATION_NAMESPACE, key,
        _fingerprint({"financial_case_event_id": event.id, "lot_id": lot.id}), applied_at,
    )
    if not inserted:
        raise FinancialEffectRetryError("financial case evaluation is already in progress")
    evaluation = FinancialCaseLotEvaluation(
        id=str(uuid.uuid4()), billing_account_id=case.billing_account_id,
        financial_case_id=case.id, financial_case_event_id=event.id,
        financial_line_id=line.id, lot_id=lot.id, funding_kind=funded.kind,
        funding_reference_id=funded.reference_id, case_type=case.case_type,
        case_state=case.state, line_principal_minor=_net_principal(line),
        attributed_principal_minor=r_case, unused_basis=plan["unused_basis"],
        target_amount=plan["target"], held_before=state.held, reversed_before=state.reversed,
        hold_amount=applied["hold"], release_amount=applied["release"],
        reversal_amount=applied["reversal"], recovery_amount=applied["recovery"],
        unrestorable_recovery_amount=unrestorable,
        absorbed_shortfall_total=plan.get("absorbed_total", 0),
        evaluation_key=key,
        request_fingerprint=_fingerprint({
            "financial_case_event_id": event.id, "lot_id": lot.id, "plan": plan,
            "applied": applied, "unrestorable": unrestorable,
        }),
        idempotency_registry_id=evaluation_registry.id, contract_version=CONTRACT_VERSION,
        evaluated_at=applied_at,
    )
    session.add(evaluation)
    session.flush()

    reason = f"{case.case_type}_{case.state}"
    new_holds = []
    for entry_type, effect_type, amount, related, registry in steps:
        if entry_type == "dispute_reversal_all":
            continue
        entry = _write_effect(
            session, evaluation=evaluation, case=case, event=event, lot=lot,
            entry_type=entry_type, effect_type=effect_type, amount=amount,
            related_entry_id=related, registry=registry, effective_at=effective_at,
            actor_type=actor_type, actor_id=actor_id, reason_code=reason,
        )
        if entry_type == "dispute_hold":
            new_holds.append((entry, amount))
    if any(step[0] == "dispute_reversal_all" for step in steps):
        for hold_entry, left in [*state.live_holds, *new_holds]:
            registry = _effect_registry(session, (
                f"dispute:{case.case_object_id}:{event.external_version}:{lot.id}:reversal:{hold_entry.id}"
            ), {**common, "effect": "reversal", "related_entry_id": hold_entry.id}, applied_at)
            _write_effect(
                session, evaluation=evaluation, case=case, event=event, lot=lot,
                entry_type="dispute_reversal", effect_type="reversal", amount=left,
                related_entry_id=hold_entry.id, registry=registry, effective_at=effective_at,
                actor_type=actor_type, actor_id=actor_id, reason_code=reason,
            )
    _complete(session, evaluation_registry, completed_at=applied_at,
              result_type="financial_case_lot_evaluation", result_id=evaluation.id)
    return evaluation


def record_and_apply_financial_case_event(
    session, proposed_case, *, applied_at, actor_type, actor_id, delivery_obligations,
):
    """Record a Phase 5.3 case version and apply its credit effects atomically.

    Takes the billing-account lock before the Phase 5.3 recorder takes its
    case lock, so the documented lock order holds. A stale version records
    nothing new and applies nothing. Returns
    ``(case, event_or_none, record_state, evaluations)``.
    """
    if not isinstance(proposed_case, dict):
        raise FinancialEffectError("financial case must be an object")
    account_id = _text(proposed_case.get("billing_account_id"), "billing_account_id", 36)
    _service_actor(actor_type, actor_id)
    _deliveries(delivery_obligations)
    _lock_account(session, account_id)
    try:
        case, event, state = record_financial_case_event(session, proposed_case)
    except FinancialCaseInvariantError as exc:
        raise FinancialEffectError(str(exc)) from exc
    if state == "stale":
        return case, None, state, []
    case, event, evaluations = apply_financial_case_effects(
        session, billing_account_id=account_id, financial_case_id=case.id,
        applied_at=applied_at, actor_type=actor_type, actor_id=actor_id,
        delivery_obligations=delivery_obligations,
    )
    return case, event, state, evaluations
