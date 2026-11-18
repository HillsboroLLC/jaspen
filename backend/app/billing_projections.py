"""Inactive Phase 13 pure billing projections and legacy compatibility comparison.

Phase 13 is the first read layer over the Phase 3-12 billing records
(traceability D18 row 13: "pure projections, all writer/reader inventory,
compatibility field proofs"). Three things live here:

* ``project_billing_account`` builds the ADR-0001 "derived target fields" and
  the D23 Usage & Billing data for one organization billing account, with an
  optional member view.
* ``project_usage_history`` lists AI operations with their ledger-settled
  credits, per operation and per session (``AIOperation.thread_id``).
* ``compare_legacy_compatibility`` reads the legacy compatibility fields of
  the same account and classifies each difference with the D16 step-5
  classes. It is a report: it opens no lot, writes no ``migration_opening``,
  quarantines nothing and records no run. That is Phase 14.

Rules every function here keeps:

* Pure reads. No write, flush, lock, or autoflush of the caller's pending
  changes (D06 "preflight is a pure read"; T-READ-01..08). The Phase 3 ledger
  stays the only balance authority; nothing here becomes a second write path
  (ADR "Projection rule"; current-state-inventory STOP-20).
* A projection rejects, never clamps or hides, an invariant violation
  (lifecycle specification, ledger rules): ``ProjectionInvariantError``.
* Tenant isolation: one billing account at a time; a member view requires an
  active membership of that account's organization; member-attributed lots
  are spendable only by that member and scoped lots fail closed, by the same
  rule Phase 12 authorization uses.
* Deterministic for the same database state and ``at``.

Nothing in live routes, the AI runtime, webhooks, jobs, or readers calls this
module; legacy readers switch to it only at the Phase 17 reader cutover.
Legacy integers are compared as stored: D16 requires exact conservation in
internal integer credit units, and the unit identity of the legacy counters
is confirmed before Phase 14 uses these reports.
"""

from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select

from .billing_ai_operations import ACTIVE_ENTITLEMENT_STATES, _clock, _eligible
from .billing_config import SHARED_POOL_PLANS, normalize_plan_key
from .billing_enterprise_contracts import contract_access_state
from .billing_entitlements import add_calendar_months
from .billing_ledger import SOURCE_PRIORITY
from .billing_plan_changes import ACTIVE_SCHEDULE_STATES
from .billing_seats import current_seat_commitment, seat_occupancy
from .models import (
    AccountEntitlement,
    AIOperation,
    BillingAccount,
    CreditLedgerEntry,
    CreditLot,
    Organization,
    OrganizationMember,
    PersistentCreditGrant,
    PersistentCreditTransaction,
    User,
)
from .models_billing_phase4 import (
    BillingSubscription,
    CreditPeriod,
    EntitlementDefinition,
    EntitlementInstance,
)
from .models_billing_phase5 import FinancialCase
from .models_billing_phase7 import ScheduledPlanChange, UpgradeCreditAllocation
from .models_billing_phase12 import AIBillingOperation, AICapacityDecision


PROJECTION_VERSION = "jaspen.billing.projection.v1"

RECURRING_SOURCES = frozenset({"free_recurring", "subscription_recurring", "enterprise_recurring"})
PURCHASED_SOURCES = frozenset({"credit_pack_purchase"})
PLAN_SOURCES = ("free", "subscription", "enterprise_contract")
OFFER_SOURCES = ("trial", "promotion", "comp", "internal")
RENEWING_SUBSCRIPTION_STATES = ("active", "past_due")
OPEN_DISPUTE_STATES = ("opened", "pending")
# Legacy "enterprise" is an alias of the self-serve "business" plan (billing_config.PLAN_ALIASES).
ENTERPRISE_PLAN_KEYS = frozenset({"enterprise_custom"})

# D16 step 5 difference classes, plus "match".
MATCH = "match"
PROJECTION_DUPLICATION = "known_projection_duplication"
STALE_COUNTER = "known_stale_counter"
EVIDENCE_BACKED_ADJUSTMENT = "evidence_backed_adjustment"
UNRESOLVED = "unresolved"
CLASSIFICATIONS = (MATCH, PROJECTION_DUPLICATION, STALE_COUNTER, EVIDENCE_BACKED_ADJUSTMENT, UNRESOLVED)


class ProjectionError(ValueError):
    """A projection request that cannot be answered as asked."""


class ProjectionInvariantError(ProjectionError):
    """Stored billing records violate an invariant; the projection refuses to hide it."""


class ProjectionIsolationError(ProjectionError):
    """The request crosses an organization or membership boundary."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value):
    value = _utc(value)
    return value.isoformat() if value is not None else None


def _zone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ProjectionError(f"unknown display time zone: {name!r}") from exc


def _local(value, zone):
    value = _utc(value)
    return value.astimezone(zone).isoformat() if value is not None else None


def _account(session, billing_account_id):
    account = session.get(BillingAccount, billing_account_id) if billing_account_id else None
    if account is None:
        raise ProjectionError("billing account does not exist")
    return account


def _require_member(session, organization_id, user_id):
    membership = session.execute(
        select(OrganizationMember.id).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
            OrganizationMember.status == "active",
        )
    ).first()
    if membership is None:
        raise ProjectionIsolationError("the member is not an active member of this billing account's organization")


def _active_members(session, organization_id):
    return session.execute(
        select(OrganizationMember.user_id)
        .where(OrganizationMember.organization_id == organization_id, OrganizationMember.status == "active")
        .order_by(OrganizationMember.user_id)
    ).scalars().all()


def _active(column_start, column_end, at):
    return (column_start <= at) & ((column_end.is_(None)) | (column_end > at))


# ---------------------------------------------------------------------------
# Ledger reads (Phase 3 is the only balance authority)
# ---------------------------------------------------------------------------

def _lot_balances(session, account_id):
    """Every lot of the account with its ledger available and held sums, validated."""
    lots = session.execute(
        select(CreditLot).where(CreditLot.billing_account_id == account_id).order_by(CreditLot.id)
    ).scalars().all()
    sums = {
        row.lot_id: (int(row.available), int(row.held))
        for row in session.execute(
            select(
                CreditLedgerEntry.lot_id,
                func.coalesce(func.sum(CreditLedgerEntry.available_delta), 0).label("available"),
                func.coalesce(func.sum(CreditLedgerEntry.held_delta), 0).label("held"),
            )
            .where(CreditLedgerEntry.billing_account_id == account_id)
            .group_by(CreditLedgerEntry.lot_id)
        )
    }
    stray = set(sums) - {lot.id for lot in lots}
    if stray:
        raise ProjectionInvariantError("ledger entries of this account reference a lot of another account")
    balances = []
    for lot in lots:
        available, held = sums.get(lot.id, (0, 0))
        if available < 0 or held < 0:
            raise ProjectionInvariantError(f"credit lot {lot.id} is below the zero floor")
        if available + held > int(lot.original_amount):
            raise ProjectionInvariantError(f"credit lot {lot.id} exceeds its original amount")
        if lot.source_type not in SOURCE_PRIORITY:
            raise ProjectionInvariantError(f"credit lot {lot.id} has an unknown source type")
        balances.append((lot, available, held))
    return balances


def _open_at(lot, at):
    return _utc(lot.available_at) <= at and (lot.expires_at is None or _utc(lot.expires_at) > at)


def _credit_view(balances, at, member_user_id):
    by_source = Counter()
    available = held = scoped = attributed_to_others = 0
    member_spendable = 0 if member_user_id else None
    for lot, lot_available, lot_held in balances:
        held += lot_held
        if not _open_at(lot, at):
            continue  # Not yet available or expired: never purchasing power (D16).
        if lot.eligibility_scope is not None:
            scoped += lot_available  # Eligibility semantics are deferred; fail closed.
            continue
        available += lot_available
        by_source[lot.source_type] += lot_available
        if member_user_id is not None:
            if _eligible(lot, member_user_id):
                member_spendable += lot_available
            else:
                attributed_to_others += lot_available
    recurring = sum(v for k, v in by_source.items() if k in RECURRING_SOURCES)
    purchased = sum(v for k, v in by_source.items() if k in PURCHASED_SOURCES)
    view = {
        "available": available,
        "held": held,
        "recurring_available": recurring,
        "purchased_available": purchased,
        "other_available": available - recurring - purchased,
        "by_source": {key: by_source[key] for key in sorted(by_source)},
        "scoped_unspendable": scoped,
    }
    if member_user_id is not None:
        view["member_spendable"] = member_spendable
        view["attributed_to_other_members"] = attributed_to_others
    return view


def _settled_by_operation(session, account_id, operation_ids=None):
    query = (
        select(CreditLedgerEntry.operation_id, func.coalesce(func.sum(-CreditLedgerEntry.held_delta), 0))
        .where(
            CreditLedgerEntry.billing_account_id == account_id,
            CreditLedgerEntry.entry_type == "settlement",
        )
        .group_by(CreditLedgerEntry.operation_id)
    )
    if operation_ids is not None:
        query = query.where(CreditLedgerEntry.operation_id.in_(operation_ids))
    return {operation_id: int(total) for operation_id, total in session.execute(query)}


def _settled_between(session, account_id, starts_at, ends_at, member_user_id):
    query = (
        select(func.coalesce(func.sum(-CreditLedgerEntry.held_delta), 0))
        .where(
            CreditLedgerEntry.billing_account_id == account_id,
            CreditLedgerEntry.entry_type == "settlement",
            CreditLedgerEntry.effective_at >= starts_at,
            CreditLedgerEntry.effective_at <= ends_at,
        )
    )
    if member_user_id is not None:
        query = query.join(
            AIBillingOperation, AIBillingOperation.operation_id == CreditLedgerEntry.operation_id,
        ).where(AIBillingOperation.actor_user_id == member_user_id)
    return int(session.execute(query).scalar_one())


# ---------------------------------------------------------------------------
# Entitlement, subscription, period reads
# ---------------------------------------------------------------------------

def _active_instances(session, account_id, at, sources):
    return session.execute(
        select(EntitlementInstance, EntitlementDefinition.key)
        .join(EntitlementDefinition, EntitlementDefinition.id == EntitlementInstance.entitlement_definition_id)
        .where(
            EntitlementInstance.billing_account_id == account_id,
            EntitlementInstance.state.in_(ACTIVE_ENTITLEMENT_STATES),
            EntitlementInstance.source_type.in_(sources),
            _active(EntitlementInstance.starts_at, EntitlementInstance.ends_at, at),
        )
        .order_by(EntitlementInstance.starts_at, EntitlementInstance.id)
    ).all()


def _plan(session, account_id, at):
    plans = _active_instances(session, account_id, at, PLAN_SOURCES)
    if len(plans) > 1:
        raise ProjectionInvariantError("more than one base plan entitlement is active for this billing account")
    return plans[0] if plans else (None, None)


def _current_period(session, account_id, instance, subscription, at):
    """The credit period covering ``at``, found by subscription when there is one.

    A Phase 7 paid upgrade supersedes the entitlement mid-period but keeps the
    subscription's period, so a subscription-backed plan is matched by
    subscription, not by the (new) entitlement instance.
    """
    if instance is None:
        return None
    owner = CreditPeriod.subscription_id == subscription.id if subscription is not None \
        else CreditPeriod.entitlement_instance_id == instance.id
    periods = session.execute(
        select(CreditPeriod).where(
            CreditPeriod.billing_account_id == account_id,
            owner,
            CreditPeriod.state.in_(("planned", "funded")),
            CreditPeriod.starts_at <= at,
            CreditPeriod.ends_at > at,
        )
    ).scalars().all()
    if len(periods) > 1:
        raise ProjectionInvariantError("more than one credit period covers this moment for the plan")
    return periods[0] if periods else None


def _period_lot_ids(session, period):
    """The period's own allocation lot plus Phase 7 upgrade lots funded for the same period."""
    lot_ids = {period.funded_lot_id} if period.funded_lot_id else set()
    if period.subscription_id is not None:
        lot_ids.update(session.execute(
            select(UpgradeCreditAllocation.funded_lot_id).where(
                UpgradeCreditAllocation.subscription_id == period.subscription_id,
                UpgradeCreditAllocation.period_starts_at == period.starts_at,
                UpgradeCreditAllocation.funded_lot_id.is_not(None),
            )
        ).scalars().all())
    return lot_ids


def _active_schedule(session, subscription_id):
    rows = session.execute(
        select(ScheduledPlanChange, EntitlementDefinition.key)
        .outerjoin(EntitlementDefinition,
                   EntitlementDefinition.id == ScheduledPlanChange.target_entitlement_definition_id)
        .where(
            ScheduledPlanChange.subscription_id == subscription_id,
            ScheduledPlanChange.state.in_(ACTIVE_SCHEDULE_STATES),
        )
    ).all()
    if len(rows) > 1:
        raise ProjectionInvariantError("more than one scheduled plan change is active for the subscription")
    return rows[0] if rows else (None, None)


def _renews(instance, subscription, schedule):
    """A self-serve subscription renews unless it is ending; contracts renew by contract."""
    if instance.source_type == "free":
        return True
    if instance.source_type != "subscription" or subscription is None:
        return False
    if subscription.state not in RENEWING_SUBSCRIPTION_STATES:
        return False
    return schedule is None or schedule.kind != "cancellation"


def _next_allocation_at(instance, subscription, schedule, period):
    """Next period boundary from the immutable anchor; None when no further period is funded."""
    if period is None:
        return None
    boundary = _utc(period.ends_at)
    term_end = _utc(subscription.term_ends_at) if subscription is not None else _utc(instance.ends_at)
    if term_end is not None and boundary < term_end:
        return boundary  # Annual-monthly release within the paid term.
    return boundary if _renews(instance, subscription, schedule) else None


# ---------------------------------------------------------------------------
# Public projections
# ---------------------------------------------------------------------------

def project_billing_account(session, *, billing_account_id, at=None, member_user_id=None,
                            display_time_zone="UTC"):
    """Pure Usage & Billing projection of one organization billing account (ADR, D23).

    ``member_user_id`` adds the member view (what that member may spend and
    has used). ``display_time_zone`` only formats dates for display; every
    value is computed in UTC.
    """
    zone = _zone(display_time_zone)
    with session.no_autoflush:
        account = _account(session, billing_account_id)
        if member_user_id is not None:
            _require_member(session, account.organization_id, member_user_id)
        at = _clock(session) if at is None else _utc(at)

        balances = _lot_balances(session, account.id)
        credits = _credit_view(balances, at, member_user_id)

        instance, plan_key = _plan(session, account.id, at)
        subscription = session.get(BillingSubscription, instance.subscription_id) \
            if instance is not None and instance.subscription_id else None
        schedule, schedule_target = _active_schedule(session, subscription.id) \
            if subscription is not None else (None, None)
        period = _current_period(session, account.id, instance, subscription, at)
        if period is not None:
            lot_ids = _period_lot_ids(session, period)
            credits["period_remaining"] = sum(
                available for lot, available, _held in balances
                if lot.id in lot_ids and _open_at(lot, at) and lot.eligibility_scope is None
                and (member_user_id is None or _eligible(lot, member_user_id))
            )
            credits["used_this_period"] = _settled_between(
                session, account.id, _utc(period.starts_at), at, member_user_id,
            )
        else:
            credits["period_remaining"] = None
            credits["used_this_period"] = None
        next_allocation = _next_allocation_at(instance, subscription, schedule, period) \
            if instance is not None else None

        offers = [
            {"key": key, "source_type": offer.source_type, "starts_at": _iso(offer.starts_at),
             "ends_at": _iso(offer.ends_at)}
            for offer, key in _active_instances(session, account.id, at, OFFER_SOURCES)
        ]

        subscription_view = next_payment = None
        if subscription is not None:
            next_payment = _utc(subscription.term_ends_at) if _renews(instance, subscription, schedule) else None
            subscription_view = {
                "subscription_id": subscription.id,
                "status": subscription.state,
                "billing_interval": subscription.interval,
                "term_starts_at": _iso(subscription.term_starts_at),
                "term_ends_at": _iso(subscription.term_ends_at),
                "next_payment_at": _iso(next_payment),
            }

        commitment = current_seat_commitment(session, subscription.id) if subscription is not None else None
        contract = contract_access_state(session, billing_account_id=account.id, at=at)
        restriction = None
        if account.status in ("restricted", "closed"):
            restriction = f"billing_account_{account.status}"
        elif contract["state"] in ("read_only_grace", "read_only_retention"):
            restriction = f"contract_{contract['state']}"

        display = {
            "time_zone": display_time_zone,
            "next_allocation_at": _local(next_allocation, zone),
            "next_payment_at": _local(next_payment, zone),
            "term_ends_at": _local(subscription.term_ends_at if subscription is not None else None, zone),
        }

        return {
            "projection_version": PROJECTION_VERSION,
            "billing_account_id": account.id,
            "organization_id": account.organization_id,
            "member_user_id": member_user_id,
            "as_of": _iso(at),
            "credits": credits,
            "next_allocation_at": _iso(next_allocation),
            "effective_plan_key": plan_key,
            "plan_source_type": instance.source_type if instance is not None else None,
            "subscription": subscription_view,
            "scheduled_plan_change": None if schedule is None else {
                "kind": schedule.kind, "state": schedule.state, "effective_rule": schedule.effective_rule,
                "effective_at": _iso(schedule.effective_at), "target_plan_key": schedule_target,
            },
            "offers": offers,
            "has_offer": bool(offers),
            "seats": {
                "commitment": commitment.quantity if commitment is not None else None,
                "occupancy": seat_occupancy(session, account.organization_id),
            },
            "contract_access": {key: (_iso(value) if isinstance(value, datetime) else value)
                                for key, value in contract.items()},
            "access_restricted": {"restricted": restriction is not None, "reason": restriction},
            "capacity": _capacity_view(session, account.id, member_user_id, at),
            "display": display,
        }


def _capacity_view(session, account_id, member_user_id, at):
    """Short-term capacity, kept apart from credits (D22, D23): the latest recorded decision."""
    query = (
        select(AICapacityDecision)
        .join(AIBillingOperation, AIBillingOperation.operation_id == AICapacityDecision.operation_id)
        .where(AIBillingOperation.billing_account_id == account_id)
        .order_by(AICapacityDecision.decided_at.desc(), AICapacityDecision.id.desc())
        .limit(1)
    )
    if member_user_id is not None:
        query = query.where(AIBillingOperation.actor_user_id == member_user_id)
    decision = session.execute(query).scalar_one_or_none()
    if decision is None:
        return {"status": "no_decision_recorded", "available_again_at": None, "reason_code": None,
                "decided_at": None}
    waiting = decision.outcome == "denied" and decision.available_again_at is not None \
        and _utc(decision.available_again_at) > at
    return {
        "status": "temporarily_unavailable" if waiting else "available",
        "available_again_at": _iso(decision.available_again_at) if waiting else None,
        "reason_code": decision.reason_code if waiting else None,
        "decided_at": _iso(decision.decided_at),
    }


def project_usage_history(session, *, billing_account_id, member_user_id=None, since=None, until=None):
    """Pure per-operation and per-session usage history from the ledger (D23, T-USAGE).

    Charged credits always come from settlement entries. A finalized operation
    whose recorded charge disagrees with its settlements is an invariant
    violation, never reconciled silently.
    """
    with session.no_autoflush:
        account = _account(session, billing_account_id)
        if member_user_id is not None:
            _require_member(session, account.organization_id, member_user_id)
        query = (
            select(AIBillingOperation, AIOperation.thread_id)
            .join(AIOperation, AIOperation.id == AIBillingOperation.operation_id)
            .where(AIBillingOperation.billing_account_id == account.id)
            .order_by(AIBillingOperation.authorized_at, AIBillingOperation.operation_id)
        )
        if member_user_id is not None:
            query = query.where(AIBillingOperation.actor_user_id == member_user_id)
        if since is not None:
            query = query.where(AIBillingOperation.authorized_at >= _utc(since))
        if until is not None:
            query = query.where(AIBillingOperation.authorized_at < _utc(until))
        rows = session.execute(query).all()
        if any(op.organization_id != account.organization_id for op, _thread in rows):
            raise ProjectionInvariantError("an operation of this billing account names another organization")
        settled = _settled_by_operation(session, account.id, [op.operation_id for op, _ in rows])
        operations, sessions = [], {}
        for op, thread_id in rows:
            charged = settled.get(op.operation_id, 0)
            if op.state in ("finalized", "expired") and int(op.charged_credits or 0) != charged:
                raise ProjectionInvariantError(
                    f"operation {op.operation_id} records {op.charged_credits} credits but settled {charged}"
                )
            activity = _utc(op.finalized_at or op.authorized_at)
            operations.append({
                "operation_id": op.operation_id, "session_id": thread_id, "member_user_id": op.actor_user_id,
                "step_key": op.step_key, "state": op.state, "delivery_status": op.delivery_status,
                "charged_credits": charged, "authorized_at": _iso(op.authorized_at),
                "finalized_at": _iso(op.finalized_at),
            })
            if thread_id is not None:
                entry = sessions.setdefault(thread_id, {"session_id": thread_id, "charged_credits": 0,
                                                        "operations": 0, "first_activity_at": activity,
                                                        "last_activity_at": activity})
                entry["charged_credits"] += charged
                entry["operations"] += 1
                entry["first_activity_at"] = min(entry["first_activity_at"], activity)
                entry["last_activity_at"] = max(entry["last_activity_at"], activity)
        return {
            "projection_version": PROJECTION_VERSION,
            "billing_account_id": account.id,
            "member_user_id": member_user_id,
            "total_charged_credits": sum(item["charged_credits"] for item in operations),
            "operations": operations,
            "sessions": [
                {**entry, "first_activity_at": _iso(entry["first_activity_at"]),
                 "last_activity_at": _iso(entry["last_activity_at"])}
                for _key, entry in sorted(sessions.items())
            ],
        }


# ---------------------------------------------------------------------------
# Legacy compatibility comparison (D16 classification only; writes nothing)
# ---------------------------------------------------------------------------

def _meter(container):
    value = container.get("thinking_power") if isinstance(container, dict) else None
    return value if isinstance(value, dict) else None


def _parsed(value):
    if isinstance(value, datetime):
        return _utc(value)
    if isinstance(value, str) and value.strip():
        try:
            return _utc(datetime.fromisoformat(value.strip().replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _lapsed(last_reset, at):
    """True only for a known reset date whose monthly cycle has ended; a missing date proves nothing."""
    return last_reset is not None and add_calendar_months(last_reset, 1) <= at


def _int_or_none(value):
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _lapsed_cycle_value(meter, fallback_reset, at):
    """The recurring value a lapsed legacy cycle still shows, or None without positive evidence.

    Evidence required (H1): a recorded ``remaining`` and ``cycle_limit``, a known
    reset date whose cycle has ended, and ``0 <= remaining <= cycle_limit``. The
    old date alone never explains a difference, and no amount above the lapsed
    cycle's own limit is ever attributed to it.
    """
    if not meter:
        return None
    remaining, limit = _int_or_none(meter.get("remaining")), _int_or_none(meter.get("cycle_limit"))
    last_reset = _parsed(meter.get("cycle_reset_at")) or _parsed(fallback_reset)
    if remaining is None or limit is None or not _lapsed(last_reset, at) or not 0 <= remaining <= limit:
        return None
    return remaining


def _comparison(field, subject, legacy, projected, classification, *, special_case=None, detail=None):
    assert classification in CLASSIFICATIONS
    return {"field": field, "subject": subject, "legacy": legacy, "projected": projected,
            "classification": classification, "special_case": special_case, "detail": detail}


def _plan_comparison(field, subject, legacy, projected, has_contract):
    legacy_key = normalize_plan_key(legacy) if legacy else None
    if legacy_key == projected:
        return _comparison(field, subject, legacy, projected, MATCH)
    if legacy_key in ENTERPRISE_PLAN_KEYS and not has_contract:
        return _comparison(field, subject, legacy, projected, UNRESOLVED, special_case="enterprise_without_contract",
                           detail="a plan label is not Enterprise evidence; an executed contract is required")
    return _comparison(field, subject, legacy, projected, UNRESOLVED)


def _grant_log_balance(session, grant):
    latest = session.execute(
        select(PersistentCreditTransaction.balance_after)
        .where(PersistentCreditTransaction.grant_id == grant.id)
        .order_by(PersistentCreditTransaction.created_at.desc(), PersistentCreditTransaction.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return int(grant.original_amount) if latest is None else int(latest)


def _null_counter(field, subject, target, *, sales_led, has_contract, contract_funded):
    """L2: a null legacy balance carries no value to preserve and is never a stale counter.

    On the sales-led Enterprise plan (catalog ``monthly_credits: None``) the
    legacy runtime did not meter credits, so null is neither stale nor a credit
    entitlement (D16 "Enterprise": a plan label or null balance is
    insufficient). The target is explained only when every spendable credit
    comes from an executed contract's funding; otherwise the account stays
    blocked.
    """
    if sales_led and has_contract and target == contract_funded:
        return _comparison(field, subject, None, target, EVIDENCE_BACKED_ADJUSTMENT,
                           special_case="unmetered_sales_led_plan",
                           detail="legacy did not meter this plan; every target credit is executed-contract funding")
    if sales_led:
        return _comparison(field, subject, None, target, UNRESOLVED,
                           special_case="unmetered_sales_led_plan" if has_contract else "enterprise_without_contract",
                           detail="a null balance on a sales-led plan is not a credit entitlement or a stale counter")
    return _comparison(field, subject, None, target, UNRESOLVED, special_case="null_legacy_balance",
                       detail="the legacy counter was never initialized; it is evidence of nothing")


def _counter_comparison(user, legacy, target, *, at, purchased, target_recurring, legacy_persistent,
                        org_meter_remaining, in_flight, sales_led, has_contract, contract_funded):
    """``User.credits_remaining`` against the member's spendable ledger balance (D16 steps 4-5)."""
    subject = user.id
    field = "users.credits_remaining"
    if legacy is None:
        return _null_counter(field, subject, target, sales_led=sales_led, has_contract=has_contract,
                             contract_funded=contract_funded)
    legacy = int(legacy)
    if legacy < 0:
        return _comparison(field, subject, legacy, target, UNRESOLVED, special_case="negative_legacy_meter",
                           detail="quarantine; the target stays at zero or above and no debt is created")
    if legacy == target:
        return _comparison(field, subject, legacy, target, MATCH)
    if in_flight:
        return _comparison(field, subject, legacy, target, UNRESOLVED, special_case="in_flight_reservation",
                           detail="drain operations first; a hold is never inferred from a combined counter")
    if org_meter_remaining is not None and legacy - legacy_persistent == org_meter_remaining:
        return _comparison(field, subject, legacy, target, PROJECTION_DUPLICATION, special_case="shared_pool_copied",
                           detail="the counter copies the organization pool; the target holds one organization lot")
    if legacy < purchased:
        return _comparison(field, subject, legacy, target, UNRESOLVED, special_case="counter_below_proven_purchased",
                           detail="preserve the proven purchased balance; do not reduce it silently")
    lapsed = _lapsed_cycle_value(_meter(user.ui_preferences), user.credits_reset_at, at)
    if lapsed is not None and legacy - lapsed == target - target_recurring:
        return _comparison(field, subject, legacy, target, STALE_COUNTER, special_case="expired_recurring_value",
                           detail=f"exactly the lapsed cycle's {lapsed} recurring credits differ; "
                                  "never migrated as available")
    if legacy_persistent > 0 and legacy - target == legacy_persistent:
        return _comparison(field, subject, legacy, target, EVIDENCE_BACKED_ADJUSTMENT,
                           detail="the difference equals legacy persistent grants not yet held by the ledger")
    if legacy > target:
        return _comparison(field, subject, legacy, target, UNRESOLVED, special_case="counter_above_evidence",
                           detail="legacy_unattributed only after documented review; otherwise block cutover")
    return _comparison(field, subject, legacy, target, UNRESOLVED)


def _meter_remaining_comparison(field, subject, meter, fallback_reset, projected, *, at):
    """A legacy recurring meter's ``remaining`` against the ledger's period remaining (M1).

    Called only for the pool the legacy runtime meters; the other pool is
    listed in ``not_applicable`` instead (M2b).
    """
    if meter is None or "remaining" not in meter:
        if not projected:
            return _comparison(field, subject, None, projected, MATCH, detail="neither side holds a period value")
        return _comparison(field, subject, None, projected, UNRESOLVED, special_case="legacy_field_absent")
    remaining = _int_or_none(meter.get("remaining"))
    if remaining is None:
        return _comparison(field, subject, meter.get("remaining"), projected, UNRESOLVED,
                           special_case="malformed_legacy_meter")
    if remaining < 0:
        return _comparison(field, subject, remaining, projected, UNRESOLVED, special_case="negative_legacy_meter")
    if remaining == projected:
        return _comparison(field, subject, remaining, projected, MATCH)
    # The whole meter is recurring value: a bounded lapsed cycle explains it exactly or not at all.
    if _lapsed_cycle_value(meter, fallback_reset, at) == remaining:
        return _comparison(field, subject, remaining, projected, STALE_COUNTER, special_case="expired_recurring_value",
                           detail="the meter shows a lapsed cycle within its own limit; never migrated as available")
    return _comparison(field, subject, remaining, projected, UNRESOLVED,
                       special_case="counter_above_evidence" if projected is None or remaining > projected else None)


def _on_anchor(value, anchor, at):
    """True when ``value`` is one of the target anchor's monthly boundaries, at or before ``at``."""
    if anchor is None or value is None or value < anchor:
        return False
    months = (value.year - anchor.year) * 12 + value.month - anchor.month
    return any(k >= 0 and add_calendar_months(anchor, k) == value for k in (months - 1, months, months + 1)) \
        and value <= at


def _reset_date_comparison(field, subject, raw, projected_next, anchor, *, at):
    """A legacy last-reset date against the ledger's next allocation (ADR: project ``next_allocation_at``).

    Legacy stores the last reset; its next boundary is that date plus one
    calendar month. A lapsed date is stale only when it sits on the ledger's
    own anchor sequence (the counter simply was not advanced); a date from a
    different anchor is drift and stays unresolved.
    """
    if raw is None:
        if projected_next is None:
            return _comparison(field, subject, None, None, MATCH, detail="neither side schedules an allocation")
        return _comparison(field, subject, None, _iso(projected_next), UNRESOLVED, special_case="legacy_field_absent")
    last_reset = _parsed(raw)
    legacy_value = raw if isinstance(raw, str) else _iso(raw)
    if last_reset is None:
        return _comparison(field, subject, legacy_value, _iso(projected_next), UNRESOLVED,
                           special_case="malformed_legacy_meter")
    legacy_next = add_calendar_months(last_reset, 1)
    detail = "legacy value is the last reset; compared as last reset + 1 calendar month"
    if legacy_next == projected_next:
        return _comparison(field, subject, legacy_value, _iso(projected_next), MATCH, detail=detail)
    if projected_next is not None and legacy_next <= at and _on_anchor(last_reset, anchor, at):
        return _comparison(field, subject, legacy_value, _iso(projected_next), STALE_COUNTER,
                           special_case="lapsed_reset_date", detail=detail)
    return _comparison(field, subject, legacy_value, _iso(projected_next), UNRESOLVED,
                       special_case="anchor_mismatch", detail=detail)


def _period_anchor(session, account_id, at):
    """The immutable anchor of the plan's current credit period, if any."""
    instance, _key = _plan(session, account_id, at)
    subscription = session.get(BillingSubscription, instance.subscription_id) \
        if instance is not None and instance.subscription_id else None
    period = _current_period(session, account_id, instance, subscription, at)
    return _utc(period.anchor_at) if period is not None else None


def _contract_funded_lot_ids(session, account_id):
    """Lots funded by credit periods of executed-contract entitlements (Phase 11 contract-backed terms)."""
    return set(session.execute(
        select(CreditPeriod.funded_lot_id)
        .join(EntitlementInstance, EntitlementInstance.id == CreditPeriod.entitlement_instance_id)
        .where(
            CreditPeriod.billing_account_id == account_id,
            CreditPeriod.funded_lot_id.is_not(None),
            EntitlementInstance.source_type == "enterprise_contract",
        )
    ).scalars().all())


def _unique(rows):
    seen, out = set(), []
    for row in rows:
        key = tuple(sorted(row.items()))
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out


def compare_legacy_compatibility(session, *, billing_account_id, at=None):
    """Read-only D16 comparison of every legacy compatibility field of one account.

    Returns a report; any ``unresolved`` comparison or blocking flag marks the
    account ``blocked`` for cutover. Legacy readers that write on read
    (``get_usage_meter_state`` and the pool resolvers, STOP-01) are never
    called: stored legacy values are read directly.
    """
    with session.no_autoflush:
        account = _account(session, billing_account_id)
        at = _clock(session) if at is None else _utc(at)
        organization = session.get(Organization, account.organization_id)
        projection = project_billing_account(session, billing_account_id=account.id, at=at)
        has_contract = projection["contract_access"]["state"] != "none"
        comparisons = []

        open_operations = session.execute(
            select(func.count()).select_from(AIBillingOperation).where(
                AIBillingOperation.billing_account_id == account.id, AIBillingOperation.state == "authorized",
            )
        ).scalar_one()
        open_disputes = session.execute(
            select(func.count()).select_from(FinancialCase).where(
                FinancialCase.billing_account_id == account.id, FinancialCase.case_type == "dispute",
                FinancialCase.state.in_(OPEN_DISPUTE_STATES),
            )
        ).scalar_one()
        flags = []
        if open_operations:
            flags.append({"code": "in_flight_reservation", "count": int(open_operations), "blocks_cutover": True,
                          "detail": "pause or drain AI operations before any opening balance"})
        if open_disputes:
            flags.append({"code": "active_dispute", "count": int(open_disputes), "blocks_cutover": True,
                          "detail": "migrate case state and source hold before exposing balance"})

        members = [session.get(User, user_id) for user_id in _active_members(session, account.organization_id)]
        # Legacy pool semantics (billing_config.get_usage_meter_state): shared-pool plans
        # meter the organization; every other plan meters the user.
        shared_pool = any(normalize_plan_key(user.subscription_plan) in SHARED_POOL_PLANS for user in members)
        projected_next = _parsed(projection["next_allocation_at"])
        anchor = _period_anchor(session, account.id, at)
        not_applicable = []

        # Organization-level fields.
        org_meter = _meter(organization.settings)
        org_remaining = _int_or_none(org_meter.get("remaining")) if org_meter and "remaining" in org_meter else None
        # A pool the legacy runtime does not meter is listed once as not applicable and never compared,
        # whatever it stores (M2b): its value is spent by no reader, so it is neither a match nor evidence.
        if shared_pool:
            comparisons.append(_meter_remaining_comparison(
                "organizations.settings.thinking_power.remaining", organization.id, org_meter, None,
                projection["credits"]["period_remaining"], at=at,
            ))
            comparisons.append(_reset_date_comparison(
                "organizations.settings.thinking_power.cycle_reset_at", organization.id,
                org_meter.get("cycle_reset_at") if org_meter else None, projected_next, anchor, at=at,
            ))
        else:
            not_applicable.append({"subject": organization.id, "reason": "no member is on a shared-pool plan",
                                   "fields": "organizations.settings.thinking_power"})
        comparisons.append(_plan_comparison("organizations.plan_key", organization.id, organization.plan_key,
                                            projection["effective_plan_key"], has_contract))
        commitment = projection["seats"]["commitment"]
        legacy_seats = organization.max_total_paid_seats
        comparisons.append(_comparison(
            "organizations.max_total_paid_seats", organization.id, legacy_seats, commitment,
            MATCH if legacy_seats == commitment else UNRESOLVED,
        ))

        # Member-level fields.
        subscription = projection["subscription"]
        balances = _lot_balances(session, account.id)
        contract_lot_ids = _contract_funded_lot_ids(session, account.id)
        for user in members:
            user_id = user.id
            member = project_billing_account(session, billing_account_id=account.id, at=at, member_user_id=user_id)
            credits = member["credits"]
            spendable = [
                (lot, available) for lot, available, _held in balances
                if _open_at(lot, at) and lot.eligibility_scope is None and _eligible(lot, user_id)
            ]
            purchased_spendable = sum(a for lot, a in spendable if lot.source_type in PURCHASED_SOURCES)
            recurring_spendable = sum(a for lot, a in spendable if lot.source_type in RECURRING_SOURCES)
            contract_funded = sum(a for lot, a in spendable if lot.id in contract_lot_ids)
            grants = session.execute(
                select(PersistentCreditGrant).where(PersistentCreditGrant.user_id == user_id)
                .order_by(PersistentCreditGrant.granted_at, PersistentCreditGrant.id)
            ).scalars().all()
            legacy_persistent = sum(int(g.remaining_amount) for g in grants
                                    if g.status == "active" and int(g.remaining_amount) > 0)
            personal_pool = normalize_plan_key(user.subscription_plan) not in SHARED_POOL_PLANS
            comparisons.append(_counter_comparison(
                user, user.credits_remaining, credits["member_spendable"], at=at, purchased=purchased_spendable,
                target_recurring=recurring_spendable, legacy_persistent=legacy_persistent,
                # Only a shared-pool member's counter can copy the organization pool.
                org_meter_remaining=None if personal_pool else org_remaining, in_flight=bool(open_operations),
                sales_led=normalize_plan_key(user.subscription_plan) in ENTERPRISE_PLAN_KEYS,
                has_contract=has_contract, contract_funded=contract_funded,
            ))
            user_meter = _meter(user.ui_preferences)
            if personal_pool:
                comparisons.append(_meter_remaining_comparison(
                    "users.ui_preferences.thinking_power.remaining", user_id, user_meter, user.credits_reset_at,
                    credits["period_remaining"], at=at,
                ))
                comparisons.append(_reset_date_comparison(
                    "users.ui_preferences.thinking_power.cycle_reset_at", user_id,
                    user_meter.get("cycle_reset_at") if user_meter else None, projected_next, anchor, at=at,
                ))
            else:
                not_applicable.append({"subject": user_id, "reason": "the user's plan meters the organization pool",
                                       "fields": "users.ui_preferences.thinking_power"})
            comparisons.append(_reset_date_comparison(
                "users.credits_reset_at", user_id, user.credits_reset_at, projected_next, anchor, at=at,
            ))
            for grant in grants:
                log_balance = _grant_log_balance(session, grant)
                comparisons.append(_comparison(
                    "persistent_credit_grants.remaining_amount", grant.id, int(grant.remaining_amount), log_balance,
                    MATCH if int(grant.remaining_amount) == log_balance else UNRESOLVED,
                    special_case=None if int(grant.remaining_amount) == log_balance else "persistent_grant_log_mismatch",
                    detail="projected value is the grant's transaction log; external evidence decides, not the cleaner run",
                ))
            comparisons.append(_plan_comparison("users.subscription_plan", user_id, user.subscription_plan,
                                                projection["effective_plan_key"], has_contract))
            legacy_status = (user.subscription_status or "").strip().lower().replace("canceled", "cancelled") or None
            projected_status = subscription["status"] if subscription else None
            comparisons.append(_comparison("users.subscription_status", user_id, user.subscription_status,
                                           projected_status, MATCH if legacy_status == projected_status else UNRESOLVED))
            legacy_offer = session.execute(
                select(func.count()).select_from(AccountEntitlement).where(
                    AccountEntitlement.user_id == user_id, AccountEntitlement.revoked_at.is_(None),
                )
            ).scalar_one() > 0
            comparisons.append(_comparison("account_entitlements (has_offer)", user_id, legacy_offer,
                                           projection["has_offer"],
                                           MATCH if legacy_offer == projection["has_offer"] else UNRESOLVED))

        # Phase 12-bound operations: the operation audit must equal its ledger settlements.
        bound = session.execute(
            select(AIOperation.id, AIOperation.charged_credits)
            .where(AIOperation.billing_account_id == account.id).order_by(AIOperation.id)
        ).all()
        settled = _settled_by_operation(session, account.id, [row.id for row in bound])
        for operation_id, legacy_charge in bound:
            projected = settled.get(operation_id, 0)
            legacy_value = int(legacy_charge) if legacy_charge is not None else None
            comparisons.append(_comparison("ai_operations.charged_credits", operation_id, legacy_value, projected,
                                           MATCH if (legacy_value or 0) == projected else UNRESOLVED))

        summary = Counter(item["classification"] for item in comparisons)
        blocked = summary[UNRESOLVED] > 0 or any(flag["blocks_cutover"] for flag in flags)
        return {
            "projection_version": PROJECTION_VERSION,
            "billing_account_id": account.id,
            "organization_id": account.organization_id,
            "as_of": _iso(at),
            "comparisons": comparisons,
            "flags": flags,
            "not_applicable": _unique(not_applicable),
            "summary": {key: summary[key] for key in CLASSIFICATIONS},
            "blocked": blocked,
        }
