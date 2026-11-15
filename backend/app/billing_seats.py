"""Inactive Phase 8 seat-commitment commands (lifecycle D09).

Paid seat commitment belongs to the Entitlement Authority. Occupancy belongs
to the membership authority and is only read here, never written. A reduction
never removes a member, changes a role, or touches saved work.

No route, webhook, scheduler, worker, or provider integration imports this
module. Every function uses the caller's transaction and never commits.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from .billing_allocations import _claim_registry, _complete_registry_if_claimed
from .billing_entitlements import add_calendar_months
from .billing_ledger import lock_billing_account
from .billing_outbox import BillingOutboxInvariantError, DomainEventConflictError, record_domain_event
from .models import (
    BillingRoleGrant,
    BillingSubscription,
    DomainEvent,
    EntitlementDefinition,
    FinancialLine,
    FinancialTransaction,
    IdempotencyRegistry,
    OrganizationMember,
)
from .models_billing_phase8 import (
    ACTIVE_SEAT_CHANGE_STATES,
    SEAT_FUNDING_CONTRACT_VERSION,
    SeatChange,
    SeatChangeEvent,
    SeatCommitment,
    SeatFundingAttribution,
    SeatFundingUse,
    SeatTermFunding,
)
from .models_billing_phase11 import CONTRACT_PROCESSOR
from .orgs import ORG_EDIT_ROLES, normalize_org_role


COMMAND_NAMESPACE = "seat_command"
TRANSITION_NAMESPACE = "seat_transition"
OPENING_NAMESPACE = "seat_commitment_opening"
ATTRIBUTION_NAMESPACE = "seat_funding_attribution"
TERM_FUNDING_NAMESPACE = "seat_term_funding"

# Billing permission is separate from membership and organization ownership
# (ADR-0001 D03). Founder decision (2026-11-14): only an active billing owner
# may authorize new spending (paid increases); a billing admin may manage
# reductions, schedules, and occupancy-related administration.
SEAT_CHANGE_BILLING_ROLES = ("billing_owner", "billing_admin")
SEAT_PURCHASE_BILLING_ROLES = ("billing_owner",)

# Included seats come only from the approved plan definition's capability
# payload. No allowance is inferred from catalog defaults.
INCLUDED_SEATS_CAPABILITY = "included_seats"
INTERVAL_MONTHS = {"month": 1, "year": 12}

# Occupancy uses the existing paid-seat definition from ``build_seat_usage``:
# active owners, admins, creators, and collaborators. Viewers are unpaid.
PAID_OCCUPANCY_ROLES = frozenset(ORG_EDIT_ROLES)

# Subscription states in which a paid change can be made. Mirrors Phase 7's
# paid-upgrade precondition; terminal subscriptions accept no seat command.
INCREASE_SUBSCRIPTION_STATES = ("active", "past_due")
TERMINAL_SUBSCRIPTION_STATES = ("cancelled", "expired")
RENEWAL_INTERVALS = {"month": "next_monthly_renewal", "year": "next_annual_renewal"}

_ALLOWED = {
    "scheduled_reduction": {"awaiting_payment", "reduced", "blocked_occupancy", "cancelled", "superseded"},
    "blocked_occupancy": {"scheduled_reduction", "cancelled", "superseded"},
    "awaiting_payment": {"reduced", "blocked_occupancy", "cancelled", "superseded"},
}
_USER_TARGETS = {"cancelled", "superseded", "scheduled_reduction"}
_SYSTEM_TARGETS = {"awaiting_payment", "reduced", "blocked_occupancy"}
_EVENT_TYPES = {
    "scheduled_reduction": "seat_change_scheduled",
    "blocked_occupancy": "seat_reduction_blocked",
    "awaiting_payment": "seat_change_awaiting_payment",
    "reduced": "seat_change_applied",
    "cancelled": "seat_change_cancelled",
    "superseded": "seat_change_superseded",
}


class SeatChangeError(ValueError):
    pass


class SeatChangeConflictError(SeatChangeError):
    pass


class SeatChangeRetryError(SeatChangeError):
    pass


class SeatChangePermissionError(SeatChangeError):
    pass


class SeatChangeIsolationError(SeatChangeError):
    """An occupancy decision was attempted under a snapshot that could be stale."""


class SeatFundingError(SeatChangeError):
    """Funding evidence is insufficient, mismatched, or not attributable."""


class SeatFundingDependencyError(SeatFundingError):
    """An approved plan definition does not declare its included seats."""


def _utc(value, field):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise SeatChangeError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _stored_utc(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _text(value, field, maximum):
    if not isinstance(value, str) or not value.strip():
        raise SeatChangeError(f"{field} must be a nonempty string")
    value = value.strip()
    if len(value) > maximum:
        raise SeatChangeError(f"{field} is too long")
    return value


def _positive_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SeatChangeError(f"{field} must be a positive integer")
    if value > 2**31 - 1:
        raise SeatChangeError(f"{field} is too large")
    return value


def _deliveries(value):
    if not isinstance(value, (list, tuple)) or not value:
        raise SeatChangeError("at least one delivery obligation is required")
    return value


def _fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def _event(session, envelope, obligations):
    try:
        return record_domain_event(session, envelope, _deliveries(obligations))
    except DomainEventConflictError as exc:
        raise SeatChangeConflictError(str(exc)) from exc
    except BillingOutboxInvariantError as exc:
        raise SeatChangeError(str(exc)) from exc


def _claim(session, namespace, key, fingerprint, occurred_at):
    try:
        return _claim_registry(session, namespace, key, fingerprint, occurred_at)
    except DBAPIError:
        # Preserve PostgreSQL serialization/deadlock SQLSTATEs for the caller's
        # transaction retry policy (D14).
        raise
    except Exception as exc:
        name = type(exc).__name__
        if "Conflict" in name:
            raise SeatChangeConflictError(str(exc)) from exc
        if "Retry" in name:
            raise SeatChangeRetryError(str(exc)) from exc
        raise SeatChangeError(str(exc)) from exc


def _complete(session, registry, *, completed_at, result_type, result_id):
    try:
        _complete_registry_if_claimed(
            session, registry, completed_at=completed_at,
            result_type=result_type, result_id=result_id,
        )
    except Exception as exc:
        if "Conflict" in type(exc).__name__:
            raise SeatChangeConflictError(str(exc)) from exc
        raise


# ---------------------------------------------------------------------------
# Pure reads (no writes, no locks beyond the caller's transaction)
# ---------------------------------------------------------------------------

def seat_occupancy(session, organization_id):
    """Count active members in paid roles; a projection, never an authority."""
    roles = session.execute(
        select(OrganizationMember.role).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.status == "active",
        )
    ).scalars().all()
    return sum(1 for role in roles if normalize_org_role(role) in PAID_OCCUPANCY_ROLES)


def _require_decision_isolation(session):
    """Fail closed when occupancy could be read from a stale snapshot.

    Membership writers insert member rows or update roles without touching any
    billing row. Under PostgreSQL REPEATABLE READ or SERIALIZABLE a reduction
    whose snapshot predates such a committed change cannot observe it, so an
    occupancy-deciding command must run under READ COMMITTED, where each
    statement after the locks below reads current committed membership.
    """
    if session.get_bind().dialect.name != "postgresql":
        return
    level = session.execute(text("SHOW transaction_isolation")).scalar_one()
    if str(level).lower() != "read committed":
        raise SeatChangeIsolationError(
            "seat occupancy decisions require READ COMMITTED isolation on PostgreSQL"
        )


def _decision_occupancy(session, organization_id):
    """Serialize against concurrent membership changes, then count occupancy.

    PostgreSQL: the organization row ``FOR UPDATE`` waits for, and then blocks,
    member inserts (their foreign-key check takes ``FOR KEY SHARE`` on it);
    ``FOR SHARE`` on the organization's member rows waits for, and then blocks,
    role updates. The count runs afterwards in a new statement. Membership
    data is only read. SQLite writes are already serialized.
    """
    if session.get_bind().dialect.name == "postgresql":
        _require_decision_isolation(session)
        session.execute(
            text("SELECT id FROM organizations WHERE id = :org FOR UPDATE"), {"org": organization_id},
        )
        session.execute(
            text("SELECT id FROM organization_members WHERE organization_id = :org ORDER BY id FOR SHARE"),
            {"org": organization_id},
        )
    return seat_occupancy(session, organization_id)


def current_seat_commitment(session, subscription_id):
    """Return the open commitment interval for a subscription, if any."""
    return session.execute(
        select(SeatCommitment).where(
            SeatCommitment.subscription_id == subscription_id,
            SeatCommitment.state == "active",
        )
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _lock_subscription(session, account_id, subscription_id):
    account = lock_billing_account(session, account_id)
    subscription = session.execute(
        select(BillingSubscription)
        .where(BillingSubscription.id == subscription_id)
        .with_for_update()
    ).scalar_one_or_none()
    if subscription is None or subscription.billing_account_id != account_id:
        raise SeatChangeError("subscription does not belong to the billing account")
    if subscription.processor == CONTRACT_PROCESSOR:
        # Phase 11: contracted seats change only through an executed, staff-
        # approved contract version; customer billing roles cannot change them.
        raise SeatChangePermissionError("contracted seats change only through an Enterprise contract version")
    return account, subscription


def _lock_change(session, change_id):
    """Lock a change in the account-first order shared with every command."""
    change_id = _text(change_id, "seat_change_id", 36)
    probe = session.get(SeatChange, change_id)
    if probe is None:
        raise SeatChangeError("seat change does not exist")
    account, subscription = _lock_subscription(session, probe.billing_account_id, probe.subscription_id)
    change = session.execute(
        select(SeatChange).where(SeatChange.id == change_id).with_for_update()
    ).scalar_one()
    session.refresh(change)
    return account, subscription, change


def _lock_current_commitment(session, subscription_id):
    commitment = session.execute(
        select(SeatCommitment)
        .where(SeatCommitment.subscription_id == subscription_id, SeatCommitment.state == "active")
        .with_for_update()
    ).scalar_one_or_none()
    if commitment is None:
        raise SeatChangeError("subscription has no open seat commitment")
    return commitment


def _active_change(session, subscription_id):
    return session.execute(
        select(SeatChange)
        .where(SeatChange.subscription_id == subscription_id, SeatChange.state.in_(ACTIVE_SEAT_CHANGE_STATES))
        .with_for_update()
    ).scalar_one_or_none()


def _authorize(session, account_id, user_id, at, roles=SEAT_CHANGE_BILLING_ROLES):
    """Return the explicit billing grant that authorizes a seat command."""
    user_id = _text(user_id, "requested_by_user_id", 36)
    query = (
        select(BillingRoleGrant)
        .where(
            BillingRoleGrant.billing_account_id == account_id,
            BillingRoleGrant.user_id == user_id,
            BillingRoleGrant.role.in_(roles),
            BillingRoleGrant.state == "active",
        )
        .order_by(BillingRoleGrant.role, BillingRoleGrant.id)
    )
    if session.get_bind().dialect.name == "postgresql":
        query = query.with_for_update(read=True)
    now = datetime.now(timezone.utc)
    for grant in session.execute(query).scalars().all():
        starts = _stored_utc(grant.starts_at)
        ends = _stored_utc(grant.ends_at) if grant.ends_at is not None else None
        if starts <= at and (ends is None or (at < ends and now < ends)):
            return grant
    if tuple(roles) == SEAT_PURCHASE_BILLING_ROLES:
        raise SeatChangePermissionError("only an active billing owner may authorize new seat spending")
    raise SeatChangePermissionError("an active billing owner or billing admin grant is required")


def _paid_line(session, account, subscription_id, line_id, kind):
    """Return Phase 5.2 payment evidence for one subscription; never mutated."""
    line = session.execute(
        select(FinancialLine).where(FinancialLine.id == line_id).with_for_update()
    ).scalar_one_or_none()
    financial = session.get(FinancialTransaction, line.financial_transaction_id) if line else None
    if (
        line is None or financial is None or financial.kind != "payment"
        or financial.billing_account_id != account.id or financial.principal_minor <= 0
        or financial.currency != account.currency or line.currency != financial.currency
        or line.line_kind != kind or line.principal_minor <= 0
        or line.subscription_id != subscription_id
    ):
        raise SeatFundingError("seat funding requires matching positive paid-line evidence")
    return line, financial


def included_seats_for_definition(definition):
    """Read the approved plan's included seats, or fail closed."""
    if definition is None or definition.approved_at is None or not definition.approval_evidence_reference:
        raise SeatFundingDependencyError("an approved plan definition is required for included seats")
    capabilities = (definition.capability_json or {}).get("capabilities")
    value = capabilities.get(INCLUDED_SEATS_CAPABILITY) if isinstance(capabilities, dict) else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 2**31 - 1:
        raise SeatFundingDependencyError(
            "the approved plan definition does not declare included seats"
        )
    return value


def _included_seats(session, subscription):
    return included_seats_for_definition(
        session.get(EntitlementDefinition, subscription.current_entitlement_definition_id)
    )


def _paid_terms(subscription):
    """The current paid term and the next one, from subscription term evidence."""
    months = INTERVAL_MONTHS.get(subscription.interval)
    if months is None:
        raise SeatChangeError("custom subscription renewal is outside Phase 8")
    starts = _stored_utc(subscription.term_starts_at)
    ends = _stored_utc(subscription.term_ends_at)
    return (starts, ends), (ends, add_calendar_months(ends, months))


def _take_funding(session, subscription, attribution_ids, *, term_starts_at, sources):
    """Lock unused attributions for one paid term; return them and their seats."""
    if not isinstance(attribution_ids, (list, tuple)) or not attribution_ids:
        raise SeatFundingError("at least one seat funding attribution is required")
    ids = [_text(item, "attribution_id", 36) for item in attribution_ids]
    if len(set(ids)) != len(ids):
        raise SeatFundingError("a funding attribution cannot be counted twice")
    rows = session.execute(
        select(SeatFundingAttribution)
        .where(SeatFundingAttribution.id.in_(ids))
        .order_by(SeatFundingAttribution.id)
        .with_for_update()
    ).scalars().all()
    if len(rows) != len(ids):
        raise SeatFundingError("seat funding attribution does not exist")
    ends = {_stored_utc(row.term_ends_at) for row in rows}
    for row in rows:
        if row.subscription_id != subscription.id or row.billing_account_id != subscription.billing_account_id:
            raise SeatFundingError("seat funding belongs to another subscription")
        if _stored_utc(row.term_starts_at) != term_starts_at or len(ends) != 1:
            raise SeatFundingError("seat funding does not cover this paid term")
        if row.seat_source not in sources:
            raise SeatFundingError(f"{row.seat_source} seats cannot fund this change")
    if sum(1 for row in rows if row.seat_source == "included") > 1:
        raise SeatFundingError("a term has one base-plan inclusion at most")
    used = session.execute(
        select(SeatFundingUse.id).where(SeatFundingUse.attribution_id.in_(ids))
    ).first()
    if used is not None:
        raise SeatFundingError("seat funding evidence has already been used")
    return rows, sum(row.seats for row in rows), ends.pop()


def _record_term_funding(
    session, *, subscription, commitment_id, purpose, term_starts_at, term_ends_at,
    required, attributions, occurred_at, delivery_obligations, key, supersedes=None,
):
    funded = sum(row.seats for row in attributions) + (supersedes.funded_seats if supersedes else 0)
    if funded > required:
        raise SeatFundingError("seat funding exceeds the commitment it would fund")
    state = "funded" if funded == required else "unresolved"
    fingerprint = _fingerprint({
        "subscription": subscription.id, "commitment": commitment_id, "purpose": purpose,
        "term_starts_at": term_starts_at.isoformat(), "term_ends_at": term_ends_at.isoformat(),
        "required": required, "attributions": sorted(row.id for row in attributions),
        "supersedes": supersedes.id if supersedes else None,
    })
    registry, inserted = _claim(session, TERM_FUNDING_NAMESPACE, key, fingerprint, occurred_at)
    if not inserted:
        raise SeatFundingError("this paid term already has a recorded funding decision")
    funding_id = str(uuid.uuid4())
    event_type = "seat_term_funded" if state == "funded" else "seat_term_funding_unresolved"
    domain_event, _messages, event_state = _event(session, {
        "billing_account_id": subscription.billing_account_id,
        "event_key": f"{event_type}:{funding_id}",
        "event_type": event_type, "aggregate_type": "seat_term_funding",
        "aggregate_id": funding_id, "occurred_at": occurred_at,
        "reference_ids": [funding_id, subscription.id, commitment_id],
    }, delivery_obligations)
    if event_state != "inserted":
        raise SeatChangeConflictError("new seat funding reused an existing domain event")
    funding = SeatTermFunding(
        id=funding_id, billing_account_id=subscription.billing_account_id,
        subscription_id=subscription.id, commitment_id=commitment_id, purpose=purpose,
        term_starts_at=term_starts_at, term_ends_at=term_ends_at, required_seats=required,
        funded_seats=funded, state=state, supersedes_funding_id=supersedes.id if supersedes else None,
        idempotency_registry_id=registry.id, domain_event_id=domain_event.id,
    )
    session.add(funding)
    session.flush()
    session.add_all([
        SeatFundingUse(id=str(uuid.uuid4()), attribution_id=row.id, term_funding_id=funding.id)
        for row in attributions
    ])
    session.flush()
    _complete(session, registry, completed_at=occurred_at, result_type="seat_term_funding", result_id=funding.id)
    return funding


def _funding_attribution_ids(session, funding_id):
    return sorted(session.execute(
        select(SeatFundingUse.attribution_id).where(SeatFundingUse.term_funding_id == funding_id)
    ).scalars().all())


def _latest_paid_at(session, attributions):
    times = []
    for row in attributions:
        line = session.get(FinancialLine, row.financial_line_id)
        times.append(_stored_utc(session.get(FinancialTransaction, line.financial_transaction_id).effective_at))
    return max(times)


def _renewal_target(subscription, after):
    if subscription.interval not in RENEWAL_INTERVALS:
        raise SeatChangeError("custom subscription renewal is outside Phase 8")
    effective = _stored_utc(subscription.term_ends_at)
    if effective <= after:
        raise SeatChangeError("subscription term evidence does not name a future renewal")
    return effective


def _organization_id(account):
    return account.organization_id


def _replace_commitment(session, current, at):
    if at < _stored_utc(current.starts_at):
        raise SeatChangeError("seat commitment cannot change before its current interval starts")
    current.state = "replaced"
    current.ends_at = at
    session.flush()


def _transition(
    session, *, change, to_state, transition, effective_at, actor_type, actor_id,
    grant, evidence, delivery_obligations, target_effective_at=None,
    occupancy=None, term_funding_id=None, result_commitment_id=None,
    before_record=None,
):
    if to_state not in _ALLOWED.get(change.state, set()):
        raise SeatChangeError(f"invalid seat change transition: {change.state} -> {to_state}")
    if to_state in _USER_TARGETS and (actor_type != "user" or grant is None):
        raise SeatChangePermissionError("this seat transition requires an authorized billing user")
    if to_state in _SYSTEM_TARGETS and (actor_type != "system" or grant is not None):
        raise SeatChangeError("this seat transition is recorded only from renewal evidence")
    occurred_at = _utc(effective_at, "effective_at")
    source_version = change.last_event_id or "created"
    key = f"seat-transition:{change.id}:{source_version}:{to_state}"
    fingerprint = _fingerprint({
        "change": change.id, "from": change.state, "to": to_state, "source": source_version,
        "transition": transition, "effective_at": occurred_at.isoformat(),
        "target_effective_at": target_effective_at.isoformat() if target_effective_at else None,
        "actor_type": actor_type, "actor_id": actor_id,
        "grant": grant.id if grant is not None else None,
        "occupancy": occupancy, "funding": term_funding_id,
        "result": result_commitment_id, "evidence": evidence,
    })
    registry, inserted = _claim(session, TRANSITION_NAMESPACE, key, fingerprint, occurred_at)
    if not inserted:
        raise SeatChangeRetryError("seat change transition is already in progress")
    event_type = _EVENT_TYPES[to_state]
    domain_event, _messages, event_state = _event(session, {
        "billing_account_id": change.billing_account_id,
        "event_key": f"{event_type}:{change.id}:{source_version}:{to_state}",
        "event_type": event_type, "aggregate_type": "seat_change",
        "aggregate_id": change.id, "occurred_at": occurred_at,
        "reference_ids": [change.id, change.subscription_id]
        + ([result_commitment_id] if result_commitment_id else []),
    }, delivery_obligations)
    if event_state != "inserted":
        raise SeatChangeConflictError("new seat transition reused an existing domain event")
    if before_record is not None:
        term_funding_id = before_record(registry, domain_event) or term_funding_id
    item = SeatChangeEvent(
        id=str(uuid.uuid4()), seat_change_id=change.id, from_state=change.state,
        to_state=to_state, transition=transition, effective_at=occurred_at,
        target_effective_at=target_effective_at, occupancy_observed=occupancy,
        actor_type=actor_type, actor_id=actor_id,
        authorizing_role_grant_id=grant.id if grant is not None else None,
        term_funding_id=term_funding_id, result_commitment_id=result_commitment_id,
        evidence_json=evidence, idempotency_registry_id=registry.id,
        domain_event_id=domain_event.id,
    )
    session.add(item)
    session.flush()
    session.refresh(change)
    if change.state != to_state:
        # ORM-created unit schemas have no migration triggers; keep the
        # projection identical to the AFTER INSERT trigger.
        change.state = to_state
        change.last_event_id = item.id
        if target_effective_at is not None:
            change.effective_at = target_effective_at
        if result_commitment_id is not None:
            change.result_commitment_id = result_commitment_id
        session.flush()
    _complete(session, registry, completed_at=occurred_at, result_type="seat_change_event", result_id=item.id)
    session.flush()
    return item, domain_event


def _replay_last_transition(session, change, transitions, delivery_obligations, *, attribution_ids=None):
    """Revalidate the D12 facts of the transition this command already recorded."""
    item = session.get(SeatChangeEvent, change.last_event_id) if change.last_event_id else None
    if item is None or item.seat_change_id != change.id or item.to_state != change.state:
        raise SeatChangeConflictError("seat change projection lacks its transition evidence")
    if item.transition not in transitions:
        raise SeatChangeError(f"seat change is {change.state}, not the result of this command")
    if attribution_ids is not None and (
        item.term_funding_id is None
        or _funding_attribution_ids(session, item.term_funding_id) != sorted(attribution_ids)
    ):
        raise SeatChangeConflictError("seat change replay names different funding evidence")
    registry = session.get(IdempotencyRegistry, item.idempotency_registry_id)
    prefix = f"seat-transition:{change.id}:"
    if registry is None or not registry.key.startswith(prefix):
        raise SeatChangeConflictError("seat transition registry evidence is missing")
    source_version = registry.key[len(prefix):].rsplit(":", 1)[0]
    event_type = _EVENT_TYPES[item.to_state]
    domain_event, _messages, _state = _event(session, {
        "billing_account_id": change.billing_account_id,
        "event_key": f"{event_type}:{change.id}:{source_version}:{item.to_state}",
        "event_type": event_type, "aggregate_type": "seat_change",
        "aggregate_id": change.id, "occurred_at": _stored_utc(item.effective_at),
        "reference_ids": [change.id, change.subscription_id]
        + ([item.result_commitment_id] if item.result_commitment_id else []),
    }, delivery_obligations)
    if domain_event.id != item.domain_event_id:
        raise SeatChangeConflictError("seat change replay is bound to another event")
    return item


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def record_seat_funding_attribution(
    session, *, billing_account_id, subscription_id, financial_line_id, seat_source,
    term_starts_at, term_ends_at, evidence_reference, actor_type, actor_id, seats=None,
):
    """Record, once, how many seats one paid line supports for one paid term.

    ``included``: a paid subscription line; its seats are read from the
    approved plan definition and must not be supplied by the caller.
    ``purchased``: a paid seat line; ``seats`` is the normalized number of
    separately bought seats the payment funds for the stated term. The term
    must be the subscription's current paid term (or its remainder) or the
    next one. ``FinancialLine.quantity`` is not interpreted.
    """
    account_id = _text(billing_account_id, "billing_account_id", 36)
    subscription_id = _text(subscription_id, "subscription_id", 36)
    line_id = _text(financial_line_id, "financial_line_id", 36)
    evidence_reference = _text(evidence_reference, "evidence_reference", 255)
    actor_type = _text(actor_type, "actor_type", 32)
    actor_id = _text(actor_id, "actor_id", 255)
    term_starts_at = _utc(term_starts_at, "term_starts_at")
    term_ends_at = _utc(term_ends_at, "term_ends_at")
    if seat_source not in ("included", "purchased"):
        raise SeatFundingError("seat_source must be included or purchased")
    account, subscription = _lock_subscription(session, account_id, subscription_id)
    if seat_source == "included":
        if seats is not None:
            raise SeatFundingError("included seats come from the approved plan definition")
        definition_id = subscription.current_entitlement_definition_id
        count = _included_seats(session, subscription)
    else:
        definition_id = None
        count = _positive_int(seats, "seats")
    key = f"seat-funding:{line_id}"
    fingerprint = _fingerprint({
        "account": account_id, "subscription": subscription.id, "line": line_id,
        "source": seat_source, "seats": count, "definition": definition_id,
        "term_starts_at": term_starts_at.isoformat(), "term_ends_at": term_ends_at.isoformat(),
        "version": SEAT_FUNDING_CONTRACT_VERSION, "evidence": evidence_reference,
    })
    registry, inserted = _claim(session, ATTRIBUTION_NAMESPACE, key, fingerprint, term_starts_at)
    if not inserted:
        attribution = session.execute(
            select(SeatFundingAttribution).where(SeatFundingAttribution.idempotency_registry_id == registry.id)
        ).scalar_one_or_none()
        if registry.state != "completed" or attribution is None:
            raise SeatChangeRetryError("seat funding attribution is already in progress")
        return attribution, "duplicate"
    _line, financial = _paid_line(
        session, account, subscription.id, line_id, "subscription" if seat_source == "included" else "seat",
    )
    current, upcoming = _paid_terms(subscription)
    in_current = term_ends_at == current[1] and current[0] <= term_starts_at < current[1]
    is_next = (term_starts_at, term_ends_at) == upcoming
    if not (in_current or is_next):
        raise SeatFundingError("seat funding must cover the current or next paid term")
    if seat_source == "included" and term_starts_at not in (current[0], upcoming[0]):
        raise SeatFundingError("base-plan seats fund a whole paid term")
    paid_at = _stored_utc(financial.effective_at)
    if not (term_starts_at <= paid_at < term_ends_at) and not (is_next and current[0] <= paid_at <= term_starts_at):
        raise SeatFundingError("the payment does not fall within the funded term")
    attribution = SeatFundingAttribution(
        id=str(uuid.uuid4()), billing_account_id=account_id, subscription_id=subscription.id,
        financial_line_id=line_id, seat_source=seat_source, seats=count,
        entitlement_definition_id=definition_id, term_starts_at=term_starts_at,
        term_ends_at=term_ends_at, contract_version=SEAT_FUNDING_CONTRACT_VERSION,
        evidence_reference=evidence_reference, actor_type=actor_type, actor_id=actor_id,
        idempotency_registry_id=registry.id,
    )
    session.add(attribution)
    session.flush()
    _complete(session, registry, completed_at=term_starts_at, result_type="seat_funding_attribution", result_id=attribution.id)
    session.flush()
    return attribution, "inserted"


def open_seat_commitment(
    session, *, billing_account_id, subscription_id, quantity, attribution_ids,
    opened_at, actor_type, actor_id, delivery_obligations,
):
    """Record the first paid commitment, funded exactly for its opening term.

    Funding must include the base plan's included seats and any separately
    purchased seats, and together cover the full opening quantity.
    """
    account_id = _text(billing_account_id, "billing_account_id", 36)
    subscription_id = _text(subscription_id, "subscription_id", 36)
    quantity = _positive_int(quantity, "quantity")
    opened_at = _utc(opened_at, "opened_at")
    actor_type = _text(actor_type, "actor_type", 32)
    actor_id = _text(actor_id, "actor_id", 255)
    obligations = _deliveries(delivery_obligations)
    _account, subscription = _lock_subscription(session, account_id, subscription_id)
    funding_ids = sorted(_text(item, "attribution_id", 36) for item in (attribution_ids or ()))
    key = f"seat-opening:{subscription.id}"
    fingerprint = _fingerprint({
        "account": account_id, "subscription": subscription.id, "quantity": quantity,
        "attributions": funding_ids, "opened_at": opened_at.isoformat(),
    })
    registry, inserted = _claim(session, OPENING_NAMESPACE, key, fingerprint, opened_at)
    if not inserted:
        commitment = session.execute(
            select(SeatCommitment).where(SeatCommitment.idempotency_registry_id == registry.id)
        ).scalar_one_or_none()
        if registry.state != "completed" or commitment is None:
            raise SeatChangeRetryError("seat commitment opening is already in progress")
        event, _messages, _state = _event(session, {
            "billing_account_id": account_id,
            "event_key": f"seat_commitment_opened:{commitment.id}",
            "event_type": "seat_commitment_opened", "aggregate_type": "seat_commitment",
            "aggregate_id": commitment.id, "occurred_at": _stored_utc(commitment.starts_at),
            "reference_ids": [commitment.id, subscription.id],
        }, obligations)
        if event.id != commitment.domain_event_id:
            raise SeatChangeConflictError("seat opening replay is bound to another event")
        return commitment, "duplicate"
    if subscription.state not in INCREASE_SUBSCRIPTION_STATES:
        raise SeatChangeError("seat commitment opening requires a nonterminal paid subscription")
    if session.execute(
        select(SeatCommitment.id).where(SeatCommitment.subscription_id == subscription.id)
    ).first() is not None:
        raise SeatChangeConflictError("subscription already has seat commitment history")
    rows, supported, term_ends_at = _take_funding(
        session, subscription, funding_ids, term_starts_at=opened_at, sources=("included", "purchased"),
    )
    if not any(row.seat_source == "included" for row in rows):
        raise SeatFundingError("opening funding must include the base plan's included seats")
    if supported != quantity:
        raise SeatFundingError("opening funding must support exactly the opening quantity")
    commitment_id = str(uuid.uuid4())
    domain_event, _messages, state = _event(session, {
        "billing_account_id": account_id,
        "event_key": f"seat_commitment_opened:{commitment_id}",
        "event_type": "seat_commitment_opened", "aggregate_type": "seat_commitment",
        "aggregate_id": commitment_id, "occurred_at": opened_at,
        "reference_ids": [commitment_id, subscription.id],
    }, obligations)
    if state != "inserted":
        raise SeatChangeConflictError("new seat opening reused an existing domain event")
    commitment = SeatCommitment(
        id=commitment_id, billing_account_id=account_id, subscription_id=subscription.id,
        quantity=quantity, origin_type="opening", state="active", starts_at=opened_at,
        idempotency_registry_id=registry.id, domain_event_id=domain_event.id,
    )
    session.add(commitment)
    session.flush()
    _record_term_funding(
        session, subscription=subscription, commitment_id=commitment.id, purpose="opening",
        term_starts_at=opened_at, term_ends_at=term_ends_at, required=quantity, attributions=rows,
        occurred_at=opened_at, delivery_obligations=obligations,
        key=f"seat-term-funding:{subscription.id}:opening",
    )
    _complete(session, registry, completed_at=opened_at, result_type="seat_commitment", result_id=commitment.id)
    session.flush()
    return commitment, "inserted"


def _command_replay(session, registry, obligations, envelope_for):
    change = session.execute(
        select(SeatChange).where(SeatChange.idempotency_registry_id == registry.id)
    ).scalar_one_or_none()
    if registry.state != "completed" or change is None:
        raise SeatChangeRetryError("seat command is already in progress")
    event, _messages, _state = _event(session, envelope_for(change), obligations)
    if event.id != change.domain_event_id:
        raise SeatChangeConflictError("seat command replay is bound to another event")
    return change


def apply_paid_seat_increase(
    session, *, billing_account_id, subscription_id, client_command_id, seat_delta,
    attribution_ids, requested_at, paid_at, requested_by_user_id, delivery_obligations,
):
    """Raise the commitment from billing-owner-authorized, purchased-seat funding.

    The funding must be purchased seats for the remainder of the current paid
    term, starting at ``paid_at``, and support exactly ``seat_delta`` seats.
    A paid increase supersedes an active reduction (D08 precedence analogue).
    """
    account_id = _text(billing_account_id, "billing_account_id", 36)
    subscription_id = _text(subscription_id, "subscription_id", 36)
    command_id = _text(client_command_id, "client_command_id", 200)
    delta = _positive_int(seat_delta, "seat_delta")
    requested_at = _utc(requested_at, "requested_at")
    paid_at = _utc(paid_at, "paid_at")
    if requested_at > paid_at:
        raise SeatChangeError("seat increase request cannot follow its payment")
    obligations = _deliveries(delivery_obligations)
    user_id = _text(requested_by_user_id, "requested_by_user_id", 36)
    funding_ids = sorted(_text(item, "attribution_id", 36) for item in (attribution_ids or ()))
    account, subscription = _lock_subscription(session, account_id, subscription_id)
    key = f"seat:{_organization_id(account)}:{command_id}"
    fingerprint = _fingerprint({
        "account": account_id, "subscription": subscription.id, "kind": "increase",
        "delta": delta, "attributions": funding_ids, "requested_at": requested_at.isoformat(),
        "paid_at": paid_at.isoformat(), "user": user_id,
    })
    registry, inserted = _claim(session, COMMAND_NAMESPACE, key, fingerprint, requested_at)

    def envelope(change):
        return {
            "billing_account_id": account_id,
            "event_key": f"seat_change_applied:{change.id}:created",
            "event_type": "seat_change_applied", "aggregate_type": "seat_change",
            "aggregate_id": change.id, "occurred_at": _stored_utc(change.effective_at),
            "reference_ids": [change.id, subscription.id, change.result_commitment_id],
        }

    if not inserted:
        change = _command_replay(session, registry, obligations, envelope)
        return change, session.get(SeatCommitment, change.result_commitment_id), "duplicate"
    grant = _authorize(session, account_id, user_id, requested_at, roles=SEAT_PURCHASE_BILLING_ROLES)
    if subscription.state not in INCREASE_SUBSCRIPTION_STATES:
        raise SeatChangeError("paid seat increase requires a nonterminal paid subscription")
    current_term, _next = _paid_terms(subscription)
    if not (current_term[0] <= paid_at < current_term[1]):
        raise SeatChangeError("seat payment is outside the current paid term")
    rows, supported, term_ends_at = _take_funding(
        session, subscription, funding_ids, term_starts_at=paid_at, sources=("purchased",),
    )
    if term_ends_at != current_term[1]:
        raise SeatFundingError("increase funding must cover the rest of the current paid term")
    if supported != delta:
        raise SeatFundingError("increase funding must support exactly the added seats")
    if _latest_paid_at(session, rows) > paid_at:
        raise SeatFundingError("increase funding was paid after the increase")
    current = _lock_current_commitment(session, subscription.id)
    if current.quantity + delta > 2**31 - 1:
        raise SeatChangeError("seat commitment is too large")
    occupancy = seat_occupancy(session, _organization_id(account))
    active = _active_change(session, subscription.id)
    change_id = str(uuid.uuid4())
    commitment_id = str(uuid.uuid4())
    domain_event, _messages, state = _event(session, {
        "billing_account_id": account_id,
        "event_key": f"seat_change_applied:{change_id}:created",
        "event_type": "seat_change_applied", "aggregate_type": "seat_change",
        "aggregate_id": change_id, "occurred_at": paid_at,
        "reference_ids": [change_id, subscription.id, commitment_id],
    }, obligations)
    if state != "inserted":
        raise SeatChangeConflictError("new seat increase reused an existing domain event")
    if active is not None:
        _transition(
            session, change=active, to_state="superseded", transition="superseded_by_paid_increase",
            effective_at=paid_at, actor_type="user", actor_id=grant.user_id, grant=grant,
            evidence={"superseding_change_id": change_id}, delivery_obligations=obligations,
        )
    base_quantity = current.quantity
    _replace_commitment(session, current, paid_at)
    commitment = SeatCommitment(
        id=commitment_id, billing_account_id=account_id, subscription_id=subscription.id,
        quantity=base_quantity + delta, origin_type="increase", state="active",
        starts_at=paid_at, previous_commitment_id=current.id,
        idempotency_registry_id=registry.id, domain_event_id=domain_event.id,
    )
    session.add(commitment)
    session.flush()
    _record_term_funding(
        session, subscription=subscription, commitment_id=commitment.id, purpose="increase",
        term_starts_at=paid_at, term_ends_at=term_ends_at, required=delta, attributions=rows,
        occurred_at=paid_at, delivery_obligations=obligations,
        key=f"seat-term-funding:{subscription.id}:increase:{commitment.id}",
    )
    change = SeatChange(
        id=change_id, billing_account_id=account_id, subscription_id=subscription.id,
        kind="increase", state="increased", base_commitment_id=current.id,
        result_commitment_id=commitment.id, base_quantity=base_quantity,
        target_quantity=base_quantity + delta, seat_delta=delta,
        occupancy_at_request=occupancy, requested_at=requested_at, effective_at=paid_at,
        authorizing_role_grant_id=grant.id, requested_by_user_id=grant.user_id,
        command_key=key, request_fingerprint=fingerprint,
        idempotency_registry_id=registry.id, domain_event_id=domain_event.id,
        supersedes_change_id=active.id if active is not None else None,
    )
    session.add(change)
    session.flush()
    _complete(session, registry, completed_at=paid_at, result_type="seat_change", result_id=change.id)
    session.flush()
    return change, commitment, "inserted"


def request_seat_reduction(
    session, *, billing_account_id, subscription_id, client_command_id, target_quantity,
    requested_at, effective_at, requested_by_user_id, compatible_supersede,
    delivery_obligations,
):
    """Schedule a reduction at the next renewal, or record it as blocked.

    When active paid occupancy exceeds the target the command is recorded as
    ``blocked_occupancy`` and the commitment stays unchanged. Members and work
    are never touched.
    """
    account_id = _text(billing_account_id, "billing_account_id", 36)
    subscription_id = _text(subscription_id, "subscription_id", 36)
    command_id = _text(client_command_id, "client_command_id", 200)
    target = _positive_int(target_quantity, "target_quantity")
    requested_at = _utc(requested_at, "requested_at")
    effective_at = _utc(effective_at, "effective_at")
    obligations = _deliveries(delivery_obligations)
    user_id = _text(requested_by_user_id, "requested_by_user_id", 36)
    account, subscription = _lock_subscription(session, account_id, subscription_id)
    key = f"seat:{_organization_id(account)}:{command_id}"
    fingerprint = _fingerprint({
        "account": account_id, "subscription": subscription.id, "kind": "reduction",
        "target": target, "requested_at": requested_at.isoformat(),
        "effective_at": effective_at.isoformat(), "user": user_id,
        "compatible_supersede": compatible_supersede is True,
    })
    registry, inserted = _claim(session, COMMAND_NAMESPACE, key, fingerprint, requested_at)

    def envelope(change):
        created_state = (
            "blocked_occupancy" if change.occupancy_at_request > change.target_quantity
            else "scheduled_reduction"
        )
        event_type = _EVENT_TYPES[created_state]
        return {
            "billing_account_id": account_id,
            "event_key": f"{event_type}:{change.id}:created",
            "event_type": event_type, "aggregate_type": "seat_change",
            "aggregate_id": change.id, "occurred_at": _stored_utc(change.requested_at),
            "reference_ids": [change.id, subscription.id, change.base_commitment_id],
        }

    if not inserted:
        return _command_replay(session, registry, obligations, envelope), "duplicate"
    _require_decision_isolation(session)
    grant = _authorize(session, account_id, user_id, requested_at)
    if subscription.state in TERMINAL_SUBSCRIPTION_STATES:
        raise SeatChangeError("terminal subscription cannot accept a seat reduction")
    if effective_at != _renewal_target(subscription, requested_at):
        raise SeatChangeError("seat reduction must use the current paid term end")
    current = _lock_current_commitment(session, subscription.id)
    if target >= current.quantity:
        raise SeatChangeError("seat reduction target must be below the current commitment")
    if target < _included_seats(session, subscription):
        raise SeatFundingError("a reduction cannot fall below the plan's included seats")
    if requested_at < _stored_utc(current.starts_at):
        raise SeatChangeError("seat reduction cannot be requested before its base commitment began")
    active = _active_change(session, subscription.id)
    if active is not None and compatible_supersede is not True:
        raise SeatChangeConflictError("an active seat change exists and supersession was not confirmed")
    occupancy = _decision_occupancy(session, _organization_id(account))
    state = "blocked_occupancy" if occupancy > target else "scheduled_reduction"
    event_type = _EVENT_TYPES[state]
    change_id = str(uuid.uuid4())
    domain_event, _messages, event_state = _event(session, {
        "billing_account_id": account_id,
        "event_key": f"{event_type}:{change_id}:created",
        "event_type": event_type, "aggregate_type": "seat_change",
        "aggregate_id": change_id, "occurred_at": requested_at,
        "reference_ids": [change_id, subscription.id, current.id],
    }, obligations)
    if event_state != "inserted":
        raise SeatChangeConflictError("new seat reduction reused an existing domain event")
    if active is not None:
        _transition(
            session, change=active, to_state="superseded", transition="superseded_by_command",
            effective_at=requested_at, actor_type="user", actor_id=grant.user_id, grant=grant,
            evidence={"superseding_change_id": change_id}, delivery_obligations=obligations,
        )
    change = SeatChange(
        id=change_id, billing_account_id=account_id, subscription_id=subscription.id,
        kind="reduction", state=state, base_commitment_id=current.id,
        base_quantity=current.quantity, target_quantity=target,
        occupancy_at_request=occupancy, requested_at=requested_at, effective_at=effective_at,
        authorizing_role_grant_id=grant.id, requested_by_user_id=grant.user_id,
        command_key=key, request_fingerprint=fingerprint, idempotency_registry_id=registry.id,
        domain_event_id=domain_event.id,
        supersedes_change_id=active.id if active is not None else None,
    )
    session.add(change)
    session.flush()
    _complete(session, registry, completed_at=requested_at, result_type="seat_change", result_id=change.id)
    session.flush()
    return change, "inserted"


def reevaluate_blocked_reduction(
    session, *, seat_change_id, evaluated_at, requested_by_user_id, delivery_obligations,
):
    """Let an authorized admin re-check occupancy for a blocked reduction.

    Compatible occupancy schedules the reduction at the subscription's next
    renewal. Incompatible occupancy leaves it blocked and records nothing.
    """
    evaluated_at = _utc(evaluated_at, "evaluated_at")
    obligations = _deliveries(delivery_obligations)
    account, subscription, change = _lock_change(session, seat_change_id)
    if change.kind != "reduction":
        raise SeatChangeError("only a seat reduction can be re-evaluated")
    if change.state == "scheduled_reduction" and change.last_event_id:
        _replay_last_transition(session, change, {"occupancy_resolved"}, obligations)
        return change, "duplicate"
    _require_decision_isolation(session)
    grant = _authorize(session, change.billing_account_id, requested_by_user_id, evaluated_at)
    if change.state != "blocked_occupancy":
        raise SeatChangeError("seat reduction is not blocked by occupancy")
    if subscription.state in TERMINAL_SUBSCRIPTION_STATES:
        raise SeatChangeError("terminal subscription cannot schedule a seat reduction")
    current = _lock_current_commitment(session, subscription.id)
    if current.id != change.base_commitment_id:
        raise SeatChangeConflictError("seat commitment changed since the reduction was requested")
    occupancy = _decision_occupancy(session, _organization_id(account))
    if occupancy > change.target_quantity:
        return change, "still_blocked"
    target_effective = _renewal_target(subscription, evaluated_at)
    _transition(
        session, change=change, to_state="scheduled_reduction", transition="occupancy_resolved",
        effective_at=evaluated_at, actor_type="user", actor_id=grant.user_id, grant=grant,
        evidence={"occupancy_compatible": True}, delivery_obligations=obligations,
        target_effective_at=target_effective, occupancy=occupancy,
    )
    return change, "inserted"


def cancel_seat_change(
    session, *, seat_change_id, cancelled_at, requested_by_user_id, delivery_obligations,
):
    """Cancel an active reduction; the commitment and history are retained."""
    cancelled_at = _utc(cancelled_at, "cancelled_at")
    obligations = _deliveries(delivery_obligations)
    _account, _subscription, change = _lock_change(session, seat_change_id)
    if change.state == "cancelled":
        _replay_last_transition(session, change, {"cancelled_by_admin"}, obligations)
        return change, "duplicate"
    grant = _authorize(session, change.billing_account_id, requested_by_user_id, cancelled_at)
    if change.state not in ACTIVE_SEAT_CHANGE_STATES:
        raise SeatChangeError("seat change is not active")
    _transition(
        session, change=change, to_state="cancelled", transition="cancelled_by_admin",
        effective_at=cancelled_at, actor_type="user", actor_id=grant.user_id, grant=grant,
        evidence={"commitment_unchanged": True}, delivery_obligations=obligations,
    )
    return change, "inserted"


def mark_seat_renewal_unpaid(
    session, *, seat_change_id, observed_at, actor_id, delivery_obligations,
):
    """Keep the existing commitment when the effective renewal is not paid."""
    observed_at = _utc(observed_at, "observed_at")
    actor_id = _text(actor_id, "actor_id", 255)
    obligations = _deliveries(delivery_obligations)
    _account, _subscription, change = _lock_change(session, seat_change_id)
    if change.state == "awaiting_payment":
        _replay_last_transition(session, change, {"renewal_payment_not_succeeded"}, obligations)
        return change, "duplicate"
    if change.state != "scheduled_reduction":
        raise SeatChangeError("seat reduction is not scheduled")
    if observed_at < _stored_utc(change.effective_at):
        raise SeatChangeError("renewal outcome cannot precede the effective renewal")
    _transition(
        session, change=change, to_state="awaiting_payment",
        transition="renewal_payment_not_succeeded", effective_at=observed_at,
        actor_type="system", actor_id=actor_id, grant=None,
        evidence={"commitment_unchanged": True}, delivery_obligations=obligations,
    )
    return change, "inserted"


def apply_seat_reduction(
    session, *, seat_change_id, attribution_ids, applied_at, actor_id, delivery_obligations,
):
    """Apply a scheduled reduction at its renewal, if occupancy and funding fit.

    Funding for the next paid term must support exactly the reduced target.
    If occupancy exceeds the target the reduction stays blocked, the last
    established commitment is kept, and the term's funding is recorded against
    that commitment: unresolved unless it fully supports it. A lower-quantity
    payment is never treated as funding the higher commitment.
    """
    funding_ids = sorted(_text(item, "attribution_id", 36) for item in (attribution_ids or ()))
    applied_at = _utc(applied_at, "applied_at")
    actor_id = _text(actor_id, "actor_id", 255)
    obligations = _deliveries(delivery_obligations)
    account, subscription, change = _lock_change(session, seat_change_id)
    if change.state == "reduced":
        _replay_last_transition(session, change, {"renewal_paid"}, obligations, attribution_ids=funding_ids)
        return change, session.get(SeatCommitment, change.result_commitment_id), "duplicate"
    if change.state == "blocked_occupancy" and change.last_event_id:
        _replay_last_transition(
            session, change, {"renewal_occupancy_conflict"}, obligations, attribution_ids=funding_ids,
        )
        return change, None, "duplicate_blocked"
    if change.state not in ("scheduled_reduction", "awaiting_payment"):
        raise SeatChangeError("seat reduction is not awaiting its renewal")
    _require_decision_isolation(session)
    effective = _stored_utc(change.effective_at)
    if applied_at < effective:
        raise SeatChangeError("seat reduction cannot apply before its effective renewal")
    current = _lock_current_commitment(session, subscription.id)
    if current.id != change.base_commitment_id:
        raise SeatChangeConflictError("seat commitment changed since the reduction was requested")
    rows, supported, term_ends_at = _take_funding(
        session, subscription, funding_ids, term_starts_at=effective, sources=("included", "purchased"),
    )
    if not any(row.seat_source == "included" for row in rows):
        raise SeatFundingError("renewal funding must include the base plan's included seats")
    if _latest_paid_at(session, rows) > applied_at:
        raise SeatFundingError("renewal funding was paid after the application time")
    occupancy = _decision_occupancy(session, _organization_id(account))
    funding_key = f"seat-term-funding:{subscription.id}:renewal:{effective.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    if occupancy > change.target_quantity:
        if supported > current.quantity:
            raise SeatFundingError("renewal funding exceeds the commitment it would fund")

        def record_blocked(_registry, _event_row):
            funding = _record_term_funding(
                session, subscription=subscription, commitment_id=current.id, purpose="renewal",
                term_starts_at=effective, term_ends_at=term_ends_at, required=current.quantity,
                attributions=rows, occurred_at=applied_at, delivery_obligations=obligations,
                key=funding_key,
            )
            return funding.id

        _transition(
            session, change=change, to_state="blocked_occupancy",
            transition="renewal_occupancy_conflict", effective_at=applied_at,
            actor_type="system", actor_id=actor_id, grant=None,
            evidence={"commitment_unchanged": True, "renewal_funded_seats": supported},
            delivery_obligations=obligations, occupancy=occupancy, before_record=record_blocked,
        )
        return change, None, "blocked"
    if supported != change.target_quantity:
        raise SeatFundingError("renewal funding must support exactly the reduced commitment")
    commitment_id = str(uuid.uuid4())
    created = []

    def insert_commitment(registry, domain_event):
        # The transition's registry and domain event authorize the new interval.
        _replace_commitment(session, current, applied_at)
        commitment = SeatCommitment(
            id=commitment_id, billing_account_id=change.billing_account_id,
            subscription_id=subscription.id, quantity=change.target_quantity,
            origin_type="reduction", state="active", starts_at=applied_at,
            previous_commitment_id=current.id,
            idempotency_registry_id=registry.id, domain_event_id=domain_event.id,
        )
        session.add(commitment)
        session.flush()
        created.append(commitment)
        funding = _record_term_funding(
            session, subscription=subscription, commitment_id=commitment.id, purpose="renewal",
            term_starts_at=effective, term_ends_at=term_ends_at, required=change.target_quantity,
            attributions=rows, occurred_at=applied_at, delivery_obligations=obligations,
            key=funding_key,
        )
        return funding.id

    _transition(
        session, change=change, to_state="reduced", transition="renewal_paid",
        effective_at=applied_at, actor_type="system", actor_id=actor_id, grant=None,
        evidence={"renewal_funded_seats": supported}, delivery_obligations=obligations,
        occupancy=occupancy, result_commitment_id=commitment_id, before_record=insert_commitment,
    )
    return change, created[0], "inserted"


def record_seat_renewal_funding(
    session, *, billing_account_id, subscription_id, attribution_ids, term_starts_at,
    recorded_at, actor_id, delivery_obligations,
):
    """Record how far a renewal term funds the unchanged current commitment.

    Used when no reduction is due at this renewal. Less funding than the
    commitment is recorded as ``unresolved``; it is never rejected silently
    and never lowers the commitment.
    """
    account_id = _text(billing_account_id, "billing_account_id", 36)
    subscription_id = _text(subscription_id, "subscription_id", 36)
    funding_ids = sorted(_text(item, "attribution_id", 36) for item in (attribution_ids or ()))
    term_starts_at = _utc(term_starts_at, "term_starts_at")
    recorded_at = _utc(recorded_at, "recorded_at")
    actor_id = _text(actor_id, "actor_id", 255)
    obligations = _deliveries(delivery_obligations)
    _account, subscription = _lock_subscription(session, account_id, subscription_id)
    key = f"seat-term-funding:{subscription.id}:renewal:{term_starts_at.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    existing = session.execute(
        select(SeatTermFunding).where(
            SeatTermFunding.subscription_id == subscription.id,
            SeatTermFunding.purpose == "renewal",
            SeatTermFunding.term_starts_at == term_starts_at,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if _funding_attribution_ids(session, existing.id) != funding_ids:
            raise SeatFundingError("this renewal already has a recorded funding decision")
        return existing, "duplicate"
    due = session.execute(
        select(SeatChange.id).where(
            SeatChange.subscription_id == subscription.id,
            SeatChange.state.in_(("scheduled_reduction", "awaiting_payment")),
            SeatChange.effective_at == term_starts_at,
        )
    ).first()
    if due is not None:
        raise SeatChangeConflictError("a reduction is due at this renewal; apply it instead")
    current = _lock_current_commitment(session, subscription.id)
    if term_starts_at < _stored_utc(current.starts_at) or recorded_at < term_starts_at:
        raise SeatFundingError("renewal funding must follow the current commitment's start")
    rows, _supported, term_ends_at = _take_funding(
        session, subscription, funding_ids, term_starts_at=term_starts_at, sources=("included", "purchased"),
    )
    if not any(row.seat_source == "included" for row in rows):
        raise SeatFundingError("renewal funding must include the base plan's included seats")
    funding = _record_term_funding(
        session, subscription=subscription, commitment_id=current.id, purpose="renewal",
        term_starts_at=term_starts_at, term_ends_at=term_ends_at, required=current.quantity,
        attributions=rows, occurred_at=recorded_at, delivery_obligations=obligations, key=key,
    )
    return funding, "inserted"


def resolve_seat_term_funding(
    session, *, term_funding_id, attribution_ids, recorded_at, actor_id, delivery_obligations,
):
    """Add purchased-seat funding to an unresolved term; never over-funds."""
    funding_id = _text(term_funding_id, "term_funding_id", 36)
    funding_ids = sorted(_text(item, "attribution_id", 36) for item in (attribution_ids or ()))
    recorded_at = _utc(recorded_at, "recorded_at")
    actor_id = _text(actor_id, "actor_id", 255)
    obligations = _deliveries(delivery_obligations)
    prior = session.get(SeatTermFunding, funding_id)
    if prior is None:
        raise SeatFundingError("seat term funding does not exist")
    _account, subscription = _lock_subscription(session, prior.billing_account_id, prior.subscription_id)
    successor = session.execute(
        select(SeatTermFunding).where(SeatTermFunding.supersedes_funding_id == prior.id)
    ).scalar_one_or_none()
    if successor is not None:
        if _funding_attribution_ids(session, successor.id) != funding_ids:
            raise SeatFundingError("this funding decision was already resolved with other evidence")
        return successor, "duplicate"
    if prior.state != "unresolved":
        raise SeatFundingError("seat term funding is not unresolved")
    rows, _supported, term_ends_at = _take_funding(
        session, subscription, funding_ids, term_starts_at=_stored_utc(prior.term_starts_at), sources=("purchased",),
    )
    if term_ends_at != _stored_utc(prior.term_ends_at):
        raise SeatFundingError("top-up funding must cover the same paid term")
    funding = _record_term_funding(
        session, subscription=subscription, commitment_id=prior.commitment_id, purpose="top_up",
        term_starts_at=_stored_utc(prior.term_starts_at), term_ends_at=term_ends_at,
        required=prior.required_seats, attributions=rows, occurred_at=recorded_at,
        delivery_obligations=obligations, key=f"seat-term-funding:{subscription.id}:top_up:{prior.id}",
        supersedes=prior,
    )
    return funding, "inserted"


def seat_renewal_requirement(session, subscription_id):
    """Pure read for a future payment integration, before it collects renewal.

    Returns the commitment the next term must fund: a scheduled reduction's
    target when occupancy currently fits it, otherwise the current commitment.
    It is advisory; application re-checks occupancy and funding.
    """
    subscription = session.get(BillingSubscription, _text(subscription_id, "subscription_id", 36))
    if subscription is None:
        raise SeatChangeError("subscription does not exist")
    current = current_seat_commitment(session, subscription.id)
    if current is None:
        raise SeatChangeError("subscription has no open seat commitment")
    included = _included_seats(session, subscription)
    _current_term, upcoming = _paid_terms(subscription)
    pending = session.execute(
        select(SeatChange).where(
            SeatChange.subscription_id == subscription.id,
            SeatChange.state.in_(ACTIVE_SEAT_CHANGE_STATES),
        )
    ).scalar_one_or_none()
    from .models import BillingAccount  # local: keeps the module surface small

    organization_id = session.get(BillingAccount, subscription.billing_account_id).organization_id
    occupancy = seat_occupancy(session, organization_id)
    due = current.quantity
    reduction_applies = False
    if (
        pending is not None and pending.state in ("scheduled_reduction", "awaiting_payment")
        and _stored_utc(pending.effective_at) == upcoming[0] and occupancy <= pending.target_quantity
    ):
        due = pending.target_quantity
        reduction_applies = True
    return {
        "subscription_id": subscription.id,
        "commitment_id": current.id,
        "current_quantity": current.quantity,
        "next_term_starts_at": upcoming[0],
        "next_term_ends_at": upcoming[1],
        "pending_change_id": pending.id if pending is not None else None,
        "pending_state": pending.state if pending is not None else None,
        "reduction_applies": reduction_applies,
        "occupancy": occupancy,
        "quantity_due": due,
        "included_seats": included,
        "purchased_seats_due": due - included,
    }


def record_seat_change_approaching(
    session, *, seat_change_id, observed_at, delivery_obligations,
):
    """Record the D09/D12 notice event ahead of an effective renewal.

    No lead time is chosen here: the future caller decides when to record it.
    The event changes no state and is recorded at most once per renewal.
    """
    observed_at = _utc(observed_at, "observed_at")
    obligations = _deliveries(delivery_obligations)
    _account, _subscription, change = _lock_change(session, seat_change_id)
    effective = _stored_utc(change.effective_at)
    key = f"seat_change_approaching:{change.id}:{effective.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    prior = session.execute(select(DomainEvent).where(DomainEvent.event_key == key)).scalar_one_or_none()
    if prior is None:
        if change.state != "scheduled_reduction":
            raise SeatChangeError("only a scheduled seat reduction has an approaching renewal")
        if observed_at >= effective:
            raise SeatChangeError("an approaching notice must precede the effective renewal")
    occurred_at = _stored_utc(prior.occurred_at) if prior is not None else observed_at
    event, _messages, state = _event(session, {
        "billing_account_id": change.billing_account_id, "event_key": key,
        "event_type": "seat_change_approaching", "aggregate_type": "seat_change",
        "aggregate_id": change.id, "occurred_at": occurred_at,
        "reference_ids": [change.id, change.subscription_id],
    }, obligations)
    return event, state
