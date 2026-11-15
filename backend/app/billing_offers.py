"""Inactive Phase 10 trial, promotion, comp, and internal-funding commands.

No live route, webhook, scheduler, or worker imports this module. Callers own
the transaction; nothing here commits or contacts a processor.

Authorities are unchanged:

* An offer is an approved, effective, unretired, versioned Phase 4
  ``EntitlementDefinition`` whose ``funding_policy_json.offer`` (v1) completely
  defines origin, owner, eligibility, capabilities (``capability_json``),
  credit components, term, credit expiry, funding source, and redemption
  limits (D07). No commercial offer is defined here; until one is approved,
  every redemption fails closed.
* Phase 4 is the only entitlement authority (instances and append-only
  transitions). Phase 3 is the only credit ledger; every grant is written
  through ``billing_ledger.append_entry``. Phase 5.4 records the domain event
  and outbox obligations.
* Trials and promotions are redeemed only by the trusted offer service
  (``actor_type='system'``). Comps and internal funding require a named Jaspen
  staff user holding an explicit, versioned, unrevoked
  ``BillingStaffPermissionGrant`` for that command family plus a reason,
  justification, and evidence reference (P08, D11 pattern, STOP-12/13).
  Global-admin identity, organization membership, and customer billing roles
  grant nothing.

Lock order: billing account, then every definition sharing the offer key (in
ascending ID order), then entitlement instance, then credit lots and ledger
appends (which re-take the account lock they already hold).
"""

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text

from .billing_allocations import (
    RecurringAllocationConflictError,
    RecurringAllocationRetryError,
    _claim_registry,
    _complete_registry_if_claimed,
)
from .billing_entitlements import (
    EntitlementInvariantError,
    append_entitlement_transition,
    validate_definition_payloads,
)
from .billing_ledger import CreditLedgerInvariantError, append_entry, lock_billing_account
from .billing_outbox import (
    BillingOutboxInvariantError,
    DomainEventConflictError,
    record_domain_event,
)
from .models import (
    CreditLedgerEntry,
    CreditLot,
    EntitlementDefinition,
    EntitlementInstance,
    User,
)
from .models_billing_phase10 import (
    PERMISSION_VERSION,
    STAFF_PERMISSIONS,
    BillingStaffPermissionGrant,
    BillingStaffPermissionRevocation,
    CreditOfferFunding,
    CreditOfferRedemption,
)


CONTRACT_VERSION = 1
REDEMPTION_NAMESPACE = "credit_offer_redemption"
FUNDING_NAMESPACE = "credit_offer_funding"
ENTITLEMENT_NAMESPACE = "credit_offer_entitlement"
PERMISSION_NAMESPACE = "billing_staff_permission"
SYSTEM_ACTOR = "system"
USER_ACTOR = "user"
MAX_TERM_DAYS = 3660
MAX_COMPONENT_AMOUNT = 2**63 - 1
ACCOUNT_STATUSES = frozenset({"proposed", "active", "restricted", "closed"})

# Entitlement origin -> Phase 3 credit-lot source taxonomy (D06).
LOT_SOURCE_TYPES = {
    "trial": "trial",
    "promotion": "promotional",
    "comp": "comp",
    "internal": "internal",
}
# Command family authority. ``None`` means the trusted offer service only.
REQUIRED_PERMISSION = {
    "trial": None,
    "promotion": None,
    "comp": "billing.comp.grant",
    "internal": "billing.internal_funding.grant",
}
EVENT_TYPES = {
    "trial": "trial_started",
    "promotion": "promotion_redeemed",
    "comp": "comp_granted",
    "internal": "internal_funding_granted",
}
_OFFER_FIELDS = {
    "schema_version", "origin", "funding_source", "owner", "eligibility",
    "redemption_limits", "term", "credit_expiry", "components",
}


class OfferError(ValueError):
    """Raised when a Phase 10 command violates its approved contract."""


class OfferConflictError(OfferError):
    """Raised when an idempotency identity is reused with different facts."""


class OfferRetryError(OfferError):
    """Raised when the command must be retried (concurrent claim)."""


class OfferPermissionError(OfferError):
    """Raised when the actor lacks the explicit authority for this command family."""


class OfferDependencyError(OfferError):
    """Raised when no approved, effective, complete offer definition exists."""


class OfferEligibilityError(OfferError):
    """Raised when the account or interval is not eligible under the approved offer."""


class OfferLimitError(OfferEligibilityError):
    """Raised when an approved redemption limit is already reached."""


class OfferIsolationError(OfferError):
    """Raised when an authorization-bearing command runs outside READ COMMITTED (PostgreSQL)."""


class OfferPolicyRequiredError(OfferError):
    """Raised when the request needs a commercial or policy decision not yet approved."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc(value, field):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise OfferError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _stored_utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _text(value, field, maximum, *, identifier=False):
    if not isinstance(value, str) or not value.strip():
        raise OfferError(f"{field} must be a nonempty string")
    value = value.strip()
    if len(value) > maximum:
        raise OfferError(f"{field} is too long")
    if identifier and ":" in value:
        raise OfferError(f"{field} must not contain ':'")
    return value


def _optional_text(value, field, maximum):
    if value is None:
        return None
    return _text(value, field, maximum)


def _fingerprint(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _deliveries(delivery_obligations):
    if not isinstance(delivery_obligations, (list, tuple)) or not delivery_obligations:
        raise OfferError("at least one delivery obligation is required for the domain event")
    return delivery_obligations


def _lock_account(session, billing_account_id):
    try:
        return lock_billing_account(session, billing_account_id)
    except CreditLedgerInvariantError as exc:
        raise OfferError("billing account is not available") from exc


def _claim(session, namespace, key, fingerprint, claimed_at):
    try:
        return _claim_registry(session, namespace, key, fingerprint, claimed_at)
    except RecurringAllocationConflictError as exc:
        raise OfferConflictError("offer command identity was reused with different facts") from exc
    except RecurringAllocationRetryError as exc:
        raise OfferRetryError(str(exc)) from exc


def _complete(session, registry, *, completed_at, result_type, result_id):
    try:
        _complete_registry_if_claimed(
            session, registry, completed_at=completed_at, result_type=result_type, result_id=result_id,
        )
    except RecurringAllocationConflictError as exc:
        raise OfferConflictError(str(exc)) from exc


def _record_event(session, event, delivery_obligations):
    try:
        return record_domain_event(session, event, delivery_obligations)
    except DomainEventConflictError as exc:
        raise OfferConflictError(str(exc)) from exc
    except BillingOutboxInvariantError as exc:
        raise OfferError(str(exc)) from exc


def _append(session, entry):
    try:
        return append_entry(session, entry)
    except CreditLedgerInvariantError as exc:
        raise OfferError(str(exc)) from exc


def _positive_int(value, field, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > maximum:
        raise OfferDependencyError(f"offer terms require a positive integer {field}")
    return value


def _database_now(session):
    """Authoritative command time from the database, never from the caller (audit F1).

    PostgreSQL ``now()`` is the transaction timestamp, which the Phase 10
    guards compare against, so service and database checks agree exactly.
    """
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        return session.execute(text("SELECT now()")).scalar_one().astimezone(timezone.utc)
    if dialect == "sqlite":
        raw = session.execute(text("SELECT strftime('%Y-%m-%d %H:%M:%f', 'now')")).scalar_one()
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=timezone.utc)
    raise OfferError(f"unsupported database dialect: {dialect}")


def _database_clock(session):
    """Actual current database time for authorization decisions (audit R2).

    ``now()`` stays fixed at the transaction start, so a transaction opened
    before a grant expired or an offer retired would still see it as valid.
    Authorization therefore uses ``clock_timestamp()``, read only after every
    lock the decision depends on is held, so no lock wait can fall between
    the check and the write. The database guards repeat the check at insert
    and again at commit. SQLite has no transaction-fixed clock; it uses the
    same wall-clock reading as ``_database_now``.
    """
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        return session.execute(text("SELECT clock_timestamp()")).scalar_one().astimezone(timezone.utc)
    return _database_now(session)


def _require_read_committed(session):
    """Refuse authorization-bearing commands outside READ COMMITTED (audit F2).

    Under REPEATABLE READ or SERIALIZABLE, a transaction whose snapshot was
    taken before a revocation committed would not see it, even after waiting
    on the grant lock. PostgreSQL fixes the isolation level for the whole
    transaction, so checking it here is reliable whether or not earlier
    statements ran. The database guards repeat the check. SQLite serializes
    every write transaction and needs no check.
    """
    if session.get_bind().dialect.name != "postgresql":
        return
    level = session.execute(text("SELECT current_setting('transaction_isolation')")).scalar_one()
    if level != "read committed":
        raise OfferIsolationError(
            "offer redemption and permission revocation must run in a READ COMMITTED transaction"
        )


# ---------------------------------------------------------------------------
# Approved offer contract (D07; P07)
# ---------------------------------------------------------------------------

def offer_terms(definition, at):
    """Validate the approved, effective, complete v1 offer definition at ``at``.

    Returns a normalized dict. Unknown or missing fields fail closed: a trial,
    comp, or promotion is valid only when its approved version completely
    defines eligibility, owner, capabilities, credit amount, start/end rules,
    funding source, and redemption limits.
    """
    if definition is None:
        raise OfferDependencyError("offer definition is not available")
    if definition.approved_at is None or not definition.approval_evidence_reference:
        raise OfferDependencyError("offer definition is not approved")
    effective_at = _stored_utc(definition.effective_at)
    retired_at = _stored_utc(definition.retired_at)
    if effective_at is None or effective_at > at:
        raise OfferDependencyError("offer definition is not effective at redemption time")
    if retired_at is not None and retired_at <= at:
        raise OfferDependencyError("offer definition is retired at redemption time")
    capability_json = definition.capability_json
    policy = definition.funding_policy_json
    try:
        validate_definition_payloads(capability_json, policy)
    except EntitlementInvariantError as exc:
        raise OfferDependencyError(f"offer definition payload is invalid: {exc}") from exc
    if policy.get("period_kind") != "none":
        raise OfferDependencyError("offer definition must not describe a recurring period")
    if "purchase" in policy:
        raise OfferDependencyError("offer definition must not also describe a purchase")
    terms = policy.get("offer")
    if not isinstance(terms, dict) or set(terms) != _OFFER_FIELDS or terms.get("schema_version") != 1:
        raise OfferDependencyError("definition has no complete approved v1 offer terms")
    origin = terms["origin"]
    if origin not in LOT_SOURCE_TYPES:
        raise OfferDependencyError("offer origin is not an approved Phase 10 origin")
    funding_source = terms["funding_source"]
    if not isinstance(funding_source, str) or not funding_source.strip() or len(funding_source.strip()) > 80:
        raise OfferDependencyError("offer terms require a funding source")
    if terms["owner"] != {"kind": "billing_account"}:
        # D06 permits member-attributed eligibility only under approved terms.
        # No member-attribution offer contract is approved yet.
        raise OfferPolicyRequiredError("member-attributed offer ownership is not approved")
    eligibility = terms["eligibility"]
    if not isinstance(eligibility, dict) or set(eligibility) != {"account_statuses"}:
        raise OfferDependencyError("offer eligibility shape is invalid")
    statuses = eligibility["account_statuses"]
    if (
        not isinstance(statuses, list) or not statuses
        or any(status not in ACCOUNT_STATUSES for status in statuses)
        or len(set(statuses)) != len(statuses)
    ):
        raise OfferDependencyError("offer eligibility must list explicit billing-account statuses")
    limits = terms["redemption_limits"]
    if not isinstance(limits, dict) or set(limits) != {"per_account", "total"}:
        raise OfferDependencyError("offer redemption limits must be explicit")
    per_account = _positive_int(limits["per_account"], "per_account limit", 2**31 - 1)
    total = _positive_int(limits["total"], "total limit", 2**31 - 1)
    if per_account > total:
        raise OfferDependencyError("per-account limit cannot exceed the total limit")
    term = terms["term"]
    if not isinstance(term, dict) or set(term) != {"kind", "days"} or term["kind"] != "fixed_days":
        raise OfferDependencyError("offer term must be an explicit fixed number of days")
    days = _positive_int(term["days"], "term days", MAX_TERM_DAYS)
    expiry = terms["credit_expiry"]
    if expiry not in ({"kind": "term_end"}, {"kind": "none"}):
        raise OfferDependencyError("offer credit expiry must be explicit")
    components = terms["components"]
    if not isinstance(components, list):
        raise OfferDependencyError("offer components must be a list")
    normalized, seen = [], set()
    for component in components:
        if not isinstance(component, dict) or set(component) != {"component", "credit_amount"}:
            raise OfferDependencyError("offer component shape is invalid")
        name = component["component"]
        amount = component["credit_amount"]
        if not isinstance(name, str) or not name.strip() or name != name.strip() or ":" in name or len(name) > 64:
            raise OfferDependencyError("offer component name is invalid")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0 or amount > MAX_COMPONENT_AMOUNT:
            raise OfferDependencyError("offer component credit amount is invalid")
        if name in seen:
            raise OfferDependencyError("offer component is duplicated")
        seen.add(name)
        normalized.append((name, amount))
    credit_amount = policy["credit_amount"]
    if credit_amount != sum(amount for _name, amount in normalized):
        raise OfferDependencyError("offer components do not equal the approved credit amount")
    capabilities = capability_json["capabilities"]
    if credit_amount == 0 and not capabilities:
        raise OfferDependencyError("offer grants neither capabilities nor credits")
    return {
        "origin": origin,
        "funding_source": funding_source.strip(),
        "account_statuses": frozenset(statuses),
        "per_account": per_account,
        "total": total,
        "days": days,
        "credit_expiry": expiry["kind"],
        "components": sorted(normalized),
        "credit_amount": credit_amount,
        "grants_entitlement": bool(capabilities),
    }


# ---------------------------------------------------------------------------
# Explicit staff permission authority (P08; STOP-12/13)
# ---------------------------------------------------------------------------

def _system_actor(actor_type, actor_id):
    actor_type = _text(actor_type, "actor_type", 40)
    actor_id = _text(actor_id, "actor_id", 255)
    if actor_type != SYSTEM_ACTOR:
        raise OfferPermissionError("this command requires the trusted provisioning service actor")
    return actor_type, actor_id


def record_staff_billing_permission(
    session, *, grant_command_id, user_id, permission, starts_at, ends_at,
    approval_evidence_reference, justification, actor_type, actor_id,
):
    """Record one explicit staff permission from documented approval evidence.

    The recording time comes from the database. ``starts_at``/``ends_at`` are
    the approved validity interval; authority is always evaluated at the
    database time of the command that uses it.

    Only the trusted provisioning service records grants; there is no
    self-service or admin-shortcut path. Returns ``(grant, 'inserted'|'duplicate')``.
    """
    actor_type, actor_id = _system_actor(actor_type, actor_id)
    command_id = _text(grant_command_id, "grant_command_id", 128, identifier=True)
    user_id = _text(user_id, "user_id", 36)
    if permission not in STAFF_PERMISSIONS:
        raise OfferError("permission is not an approved Phase 10 staff permission")
    starts_at = _utc(starts_at, "starts_at")
    ends_at = None if ends_at is None else _utc(ends_at, "ends_at")
    if ends_at is not None and ends_at <= starts_at:
        raise OfferError("permission interval is invalid")
    evidence = _text(approval_evidence_reference, "approval_evidence_reference", 255)
    justification = _text(justification, "justification", 2000)
    recorded_at = _database_now(session)
    if session.get(User, user_id) is None:
        raise OfferError("permission user is not available")
    key = f"staff-permission:{command_id}"
    fingerprint = _fingerprint({
        "user_id": user_id, "permission": permission, "permission_version": PERMISSION_VERSION,
        "starts_at": starts_at.isoformat(), "ends_at": ends_at.isoformat() if ends_at else None,
        "approval_evidence_reference": evidence, "justification": justification,
        "actor_type": actor_type, "actor_id": actor_id,
    })
    registry, inserted = _claim(session, PERMISSION_NAMESPACE, key, fingerprint, recorded_at)
    if not inserted:
        grant = session.execute(
            select(BillingStaffPermissionGrant).where(BillingStaffPermissionGrant.idempotency_registry_id == registry.id)
        ).scalar_one_or_none()
        if registry.state != "completed" or grant is None:
            raise OfferRetryError("permission grant is already in progress")
        return grant, "duplicate"
    grant = BillingStaffPermissionGrant(
        id=str(uuid.uuid4()), user_id=user_id, permission=permission,
        permission_version=PERMISSION_VERSION, starts_at=starts_at, ends_at=ends_at,
        grant_key=key, request_fingerprint=fingerprint,
        approval_evidence_reference=evidence, justification=justification,
        idempotency_registry_id=registry.id, actor_type=actor_type, actor_id=actor_id,
    )
    session.add(grant)
    session.flush()
    _complete(session, registry, completed_at=recorded_at,
              result_type="billing_staff_permission_grant", result_id=grant.id)
    return grant, "inserted"


def revoke_staff_billing_permission(
    session, *, grant_id, reason, evidence_reference, actor_type, actor_id,
):
    """Append the revocation of one grant. Returns ``(revocation, 'inserted'|'duplicate')``.

    Revocation takes effect at the database time it is recorded. A revoked
    grant authorizes no later command. The grant row lock serializes this
    command with every redemption that uses the grant (audit F2).
    """
    actor_type, actor_id = _system_actor(actor_type, actor_id)
    grant_id = _text(grant_id, "grant_id", 36)
    _require_read_committed(session)
    reason = _text(reason, "reason", 2000)
    evidence = _text(evidence_reference, "evidence_reference", 255)
    grant = session.execute(
        select(BillingStaffPermissionGrant).where(BillingStaffPermissionGrant.id == grant_id).with_for_update()
    ).scalar_one_or_none()
    if grant is None:
        raise OfferError("permission grant is not available")
    revoked_at = _database_now(session)
    existing = session.execute(
        select(BillingStaffPermissionRevocation).where(BillingStaffPermissionRevocation.grant_id == grant.id)
    ).scalar_one_or_none()
    if existing is not None:
        if (existing.reason, existing.evidence_reference) != (reason, evidence):
            raise OfferConflictError("permission grant was already revoked with different facts")
        return existing, "duplicate"
    revocation = BillingStaffPermissionRevocation(
        id=str(uuid.uuid4()), grant_id=grant.id, revoked_at=revoked_at, reason=reason,
        evidence_reference=evidence, actor_type=actor_type, actor_id=actor_id,
    )
    session.add(revocation)
    session.flush()
    return revocation, "inserted"


def _authorized_grant(session, *, user_id, permission, started_at):
    """Return the explicit, unrevoked grant valid now, or ``None``.

    The candidate grants (started by the transaction's recorded time) are
    locked first. Only then is the actual current time read and the
    expiry compared against it (audit R2), and revocation is read in a
    separate statement. Under READ COMMITTED that statement takes a fresh
    snapshot after any concurrent revocation (which also locks the grant)
    has committed, so a revoked grant is never used (audit F2).
    """
    candidates = session.execute(
        select(BillingStaffPermissionGrant)
        .where(
            BillingStaffPermissionGrant.user_id == user_id,
            BillingStaffPermissionGrant.permission == permission,
            BillingStaffPermissionGrant.permission_version == PERMISSION_VERSION,
            BillingStaffPermissionGrant.starts_at <= started_at,
        )
        .order_by(BillingStaffPermissionGrant.starts_at, BillingStaffPermissionGrant.id)
        .with_for_update()
    ).scalars().all()
    authorized_at = _database_clock(session)
    for grant in candidates:
        ends_at = _stored_utc(grant.ends_at)
        if ends_at is not None and ends_at <= authorized_at:
            continue
        revoked = session.execute(
            select(BillingStaffPermissionRevocation.id)
            .where(BillingStaffPermissionRevocation.grant_id == grant.id)
        ).first()
        if revoked is None:
            return grant
    return None


def _authorize(session, origin, *, actor_type, actor_id, at, reason_code, justification, evidence_reference):
    required = REQUIRED_PERMISSION[origin]
    if required is None:
        if actor_type != SYSTEM_ACTOR:
            # Customers, customer billing roles, and staff cannot self-issue a
            # trial or promotion; only the offer service evaluating the
            # approved eligibility may redeem it.
            raise OfferPermissionError("trials and promotions are redeemed only by the trusted offer service")
        return None
    if actor_type != USER_ACTOR:
        raise OfferPermissionError("comps and internal funding require a named, authorized staff user")
    if reason_code is None or justification is None or evidence_reference is None:
        raise OfferPermissionError("comps and internal funding require a reason, justification, and evidence")
    grant = _authorized_grant(session, user_id=actor_id, permission=required, started_at=at)
    if grant is None:
        # Global-admin identity, organization admin, and customer billing
        # roles are never consulted (P08; STOP-13).
        raise OfferPermissionError("actor does not hold the explicit permission for this command")
    return grant


# ---------------------------------------------------------------------------
# Offer redemption (D06 trial/promotional/comp/internal; D13 offer key)
# ---------------------------------------------------------------------------

def _lock_offer_definitions(session, key):
    return session.execute(
        select(EntitlementDefinition)
        .where(EntitlementDefinition.key == key)
        .order_by(EntitlementDefinition.id)
        .with_for_update()
    ).scalars().all()


def _offer_event(account_id, redemption_id_value, definition, origin, redemption_row_id, funding_ids, at):
    event_type = EVENT_TYPES[origin]
    return {
        "billing_account_id": account_id,
        "event_key": f"{event_type}:{definition.id}:{redemption_id_value}",
        "event_type": event_type,
        "aggregate_type": "credit_offer_redemption",
        "aggregate_id": redemption_row_id,
        "occurred_at": at,
        "reference_ids": [definition.id, redemption_row_id, *funding_ids],
    }


def _overlapping_exclusive_instance(session, account_id, definition, starts_at, ends_at):
    """Service mirror of the Phase 4 exclusivity guard for ORM-only schemas."""
    rows = session.execute(
        select(EntitlementInstance, EntitlementDefinition.exclusivity_key)
        .join(EntitlementDefinition, EntitlementDefinition.id == EntitlementInstance.entitlement_definition_id)
        .where(
            EntitlementInstance.billing_account_id == account_id,
            EntitlementInstance.state.in_(("scheduled", "active", "reducing")),
            EntitlementDefinition.exclusivity_key == definition.exclusivity_key,
        )
    ).all()
    for instance, _key in rows:
        other_end = _stored_utc(instance.ends_at)
        if _stored_utc(instance.starts_at) < ends_at and (other_end is None or starts_at < other_end):
            return instance
    return None


def _entitlement_transition(session, instance, to_state, transition, effective_at, actor_type, actor_id, source_id):
    key = f"offer-entitlement:{instance.id}:{to_state}"
    fingerprint = _fingerprint({"instance": instance.id, "from": instance.state, "to": to_state, "source": source_id})
    registry, inserted = _claim(session, ENTITLEMENT_NAMESPACE, key, fingerprint, effective_at)
    if not inserted:
        if registry.state == "completed" and registry.result_type == "entitlement_event":
            return registry.result_id
        raise OfferRetryError("entitlement transition is already in progress")
    try:
        event = append_entitlement_transition(
            session, instance_id=instance.id, next_state=to_state, transition=transition,
            effective_at=effective_at, actor_type=actor_type, actor_id=actor_id,
            source_type="phase10_offer_redemption", source_id=source_id, idempotency=registry,
            evidence_json={"credit_offer_redemption_id": source_id},
        )
    except EntitlementInvariantError as exc:
        raise OfferError(str(exc)) from exc
    session.flush()
    session.refresh(instance)
    if instance.state != to_state:
        # ORM-created unit schemas do not install migration triggers. Keep the
        # service projection identical to the database AFTER INSERT trigger.
        instance.state = to_state
        instance.last_event_id = event.id
        session.flush()
    _complete(session, registry, completed_at=effective_at, result_type="entitlement_event", result_id=event.id)
    return event.id


def _replay(session, account, registry, definition, redemption_id_value, delivery_obligations):
    redemption = session.execute(
        select(CreditOfferRedemption).where(CreditOfferRedemption.idempotency_registry_id == registry.id)
    ).scalar_one_or_none()
    if registry.state != "completed" or redemption is None or redemption.billing_account_id != account.id:
        raise OfferRetryError("offer redemption is already in progress")
    fundings = session.execute(
        select(CreditOfferFunding)
        .where(CreditOfferFunding.redemption_id == redemption.id)
        .order_by(CreditOfferFunding.funding_component)
    ).scalars().all()
    event, _messages, _state = _record_event(
        session,
        _offer_event(account.id, redemption_id_value, definition, redemption.origin, redemption.id,
                     [funding.id for funding in fundings], _stored_utc(redemption.redeemed_at)),
        delivery_obligations,
    )
    if event.id != redemption.domain_event_id:
        raise OfferConflictError("offer redemption is bound to another domain event")
    lots = [session.get(CreditLot, funding.lot_id) for funding in fundings]
    return redemption, fundings, lots, "duplicate"


def redeem_credit_offer(
    session, *, billing_account_id, entitlement_definition_id, redemption_id,
    actor_type, actor_id, delivery_obligations,
    reason_code=None, justification=None, evidence_reference=None,
):
    """Redeem one approved offer version once for one billing account.

    ``redemption_id`` is the caller's stable business identity for this
    redemption (for example the signup or staff command identity); random
    retries must reuse it. The redemption time is the database transaction
    time; callers cannot supply it, so a retired offer or an expired or
    revoked grant cannot be used by claiming an earlier time (audit F1). A
    retry of a completed redemption returns the stored result and its
    original time without new effects. On PostgreSQL the transaction must be
    READ COMMITTED (audit F2). Returns
    ``(redemption, fundings, lots, 'inserted'|'duplicate')``.
    """
    account_id = _text(billing_account_id, "billing_account_id", 36)
    definition_id = _text(entitlement_definition_id, "entitlement_definition_id", 36)
    redemption_id_value = _text(redemption_id, "redemption_id", 128, identifier=True)
    actor_type = _text(actor_type, "actor_type", 40)
    actor_id = _text(actor_id, "actor_id", 255)
    reason_code = _optional_text(reason_code, "reason_code", 64)
    justification = _optional_text(justification, "justification", 2000)
    evidence_reference = _optional_text(evidence_reference, "evidence_reference", 255)
    delivery_obligations = _deliveries(delivery_obligations)

    _require_read_committed(session)
    account = _lock_account(session, account_id)
    redeemed_at = _database_now(session)
    definition = session.get(EntitlementDefinition, definition_id)
    if definition is None:
        raise OfferDependencyError("offer definition is not available")
    _lock_offer_definitions(session, definition.key)

    key = f"offer-redemption:{definition.id}:{redemption_id_value}"
    fingerprint = _fingerprint({
        "billing_account_id": account.id, "entitlement_definition_id": definition.id,
        "redemption_id": redemption_id_value,
        "actor_type": actor_type, "actor_id": actor_id, "reason_code": reason_code,
        "justification": justification, "evidence_reference": evidence_reference,
        "contract_version": CONTRACT_VERSION,
    })
    registry, inserted = _claim(session, REDEMPTION_NAMESPACE, key, fingerprint, redeemed_at)
    if not inserted:
        # A retry returns the stored result; it never re-evaluates terms or
        # authority at a new time and never adds effects.
        return _replay(session, account, registry, definition, redemption_id_value, delivery_obligations)
    terms = offer_terms(definition, redeemed_at)

    grant = _authorize(
        session, terms["origin"], actor_type=actor_type, actor_id=actor_id, at=redeemed_at,
        reason_code=reason_code, justification=justification, evidence_reference=evidence_reference,
    )
    # Audit R2: the offer must still be unretired at the actual current time,
    # read after the definition and grant locks are held.
    retired_at = _stored_utc(definition.retired_at)
    if retired_at is not None and retired_at <= _database_clock(session):
        raise OfferDependencyError("offer definition is retired at redemption time")
    if account.status not in terms["account_statuses"]:
        raise OfferEligibilityError("billing account is not eligible for this offer")
    account_count = session.execute(
        select(func.count()).select_from(CreditOfferRedemption).where(
            CreditOfferRedemption.offer_key == definition.key,
            CreditOfferRedemption.billing_account_id == account.id,
        )
    ).scalar_one()
    total_count = session.execute(
        select(func.count()).select_from(CreditOfferRedemption).where(
            CreditOfferRedemption.offer_key == definition.key,
        )
    ).scalar_one()
    if account_count >= terms["per_account"]:
        raise OfferLimitError("this account has reached the offer's redemption limit")
    if total_count >= terms["total"]:
        raise OfferLimitError("the offer's total redemption limit has been reached")

    starts_at = redeemed_at
    ends_at = starts_at + timedelta(days=terms["days"])
    credit_expires_at = ends_at if terms["credit_expiry"] == "term_end" else None
    if terms["grants_entitlement"] and _overlapping_exclusive_instance(
        session, account.id, definition, starts_at, ends_at,
    ) is not None:
        raise OfferEligibilityError("an incompatible entitlement already covers this interval")

    redemption_row_id = str(uuid.uuid4())
    funding_ids = {name: str(uuid.uuid4()) for name, _amount in terms["components"]}
    event, _messages, event_state = _record_event(
        session,
        _offer_event(account.id, redemption_id_value, definition, terms["origin"], redemption_row_id,
                     sorted(funding_ids.values()), redeemed_at),
        delivery_obligations,
    )
    if event_state != "inserted":
        raise OfferConflictError("new offer redemption reused an existing domain event")

    instance = None
    if terms["grants_entitlement"]:
        instance = EntitlementInstance(
            id=str(uuid.uuid4()), billing_account_id=account.id,
            entitlement_definition_id=definition.id, state="proposed",
            starts_at=starts_at, ends_at=ends_at, source_type=terms["origin"],
            source_id=redemption_row_id,
            approval_evidence_reference=f"offer-redemption:{redemption_row_id}",
        )
        session.add(instance)
        session.flush()

    redemption = CreditOfferRedemption(
        id=redemption_row_id, billing_account_id=account.id, entitlement_definition_id=definition.id,
        offer_key=definition.key, offer_version=definition.version, origin=terms["origin"],
        redemption_id=redemption_id_value, redemption_key=key, request_fingerprint=fingerprint,
        funding_source=terms["funding_source"], redeemed_at=redeemed_at,
        term_starts_at=starts_at, term_ends_at=ends_at, credit_amount=terms["credit_amount"],
        credit_expires_at=credit_expires_at, per_account_limit=terms["per_account"],
        total_limit=terms["total"], account_redemption_index=account_count + 1,
        total_redemption_index=total_count + 1,
        entitlement_instance_id=instance.id if instance is not None else None,
        staff_permission_grant_id=grant.id if grant is not None else None,
        reason_code=reason_code, justification=justification, evidence_reference=evidence_reference,
        idempotency_registry_id=registry.id, domain_event_id=event.id,
        contract_version=CONTRACT_VERSION, actor_type=actor_type, actor_id=actor_id,
    )
    session.add(redemption)
    session.flush()

    if instance is not None:
        for to_state, transition in (("scheduled", "offer_redeemed"), ("active", "offer_term_started")):
            _entitlement_transition(
                session, instance, to_state, transition, starts_at, actor_type, actor_id, redemption.id,
            )

    source_type = LOT_SOURCE_TYPES[terms["origin"]]
    fundings, lots = [], []
    for name, amount in terms["components"]:
        funding_key = f"offer:{definition.id}:{redemption_id_value}:{name}"
        funding_fingerprint = _fingerprint({
            "redemption": redemption.id, "component": name, "credit_amount": amount,
            "contract_version": CONTRACT_VERSION,
        })
        funding_registry, funding_inserted = _claim(
            session, FUNDING_NAMESPACE, funding_key, funding_fingerprint, redeemed_at,
        )
        if not funding_inserted:
            raise OfferConflictError("offer funding identity already exists for a new redemption")
        funding_id = funding_ids[name]
        lot_id, entry_id = str(uuid.uuid4()), str(uuid.uuid4())
        funding = CreditOfferFunding(
            id=funding_id, redemption_id=redemption.id, billing_account_id=account.id,
            funding_component=name, funding_key=funding_key, request_fingerprint=funding_fingerprint,
            credit_amount=amount, lot_id=lot_id, grant_entry_id=entry_id,
            idempotency_registry_id=funding_registry.id, contract_version=CONTRACT_VERSION,
        )
        session.add(funding)
        session.flush()
        lot = CreditLot(
            id=lot_id, billing_account_id=account.id, source_type=source_type, source_id=funding_id,
            original_amount=amount, available_at=starts_at, expires_at=credit_expires_at,
            origin_evidence_json={
                "credit_offer_funding_id": funding_id,
                "credit_offer_redemption_id": redemption.id,
                "entitlement_definition_id": definition.id,
                "funding_component": name,
                "funding_source": terms["funding_source"],
            },
        )
        session.add(lot)
        session.flush()
        _append(session, CreditLedgerEntry(
            id=entry_id, billing_account_id=account.id, lot_id=lot_id, entry_type="grant",
            available_delta=amount, held_delta=0, idempotency_registry_id=funding_registry.id,
            effective_at=starts_at, actor_type=actor_type, actor_id=actor_id,
            reason_code=f"offer_{terms['origin']}",
            evidence_json={"credit_offer_funding_id": funding_id, "credit_offer_redemption_id": redemption.id},
        ))
        _complete(session, funding_registry, completed_at=redeemed_at,
                  result_type="credit_offer_funding", result_id=funding_id)
        fundings.append(funding)
        lots.append(lot)

    _complete(session, registry, completed_at=redeemed_at,
              result_type="credit_offer_redemption", result_id=redemption.id)
    session.flush()
    return redemption, fundings, lots, "inserted"


def expire_offer_entitlement(session, *, credit_offer_redemption_id, actor_type, actor_id):
    """Move an offer entitlement from ``active`` to ``expired`` once its term has ended.

    The check uses database time, so a caller cannot end a customer's term
    early by claiming a later time. The transition is recorded at the term
    end. Credit availability already ends at the lot's ``expires_at``.
    Returns ``(instance, 'inserted'|'duplicate')``.
    """
    actor_type, actor_id = _system_actor(actor_type, actor_id)
    redemption_row_id = _text(credit_offer_redemption_id, "credit_offer_redemption_id", 36)
    account_id = session.execute(
        select(CreditOfferRedemption.billing_account_id).where(CreditOfferRedemption.id == redemption_row_id)
    ).scalar_one_or_none()
    if account_id is None:
        raise OfferError("offer redemption is not available")
    _lock_account(session, account_id)
    expired_at = _database_now(session)
    redemption = session.get(CreditOfferRedemption, redemption_row_id)
    if redemption.entitlement_instance_id is None:
        raise OfferError("offer redemption granted no entitlement")
    instance = session.execute(
        select(EntitlementInstance).where(EntitlementInstance.id == redemption.entitlement_instance_id)
        .with_for_update()
    ).scalar_one()
    term_ends_at = _stored_utc(redemption.term_ends_at)
    if expired_at < term_ends_at:
        raise OfferError("offer term has not ended")
    if instance.state == "expired":
        return instance, "duplicate"
    if instance.state != "active":
        raise OfferError("offer entitlement is not active")
    _entitlement_transition(
        session, instance, "expired", "offer_term_ended", term_ends_at, actor_type, actor_id, redemption.id,
    )
    return instance, "inserted"
