"""Inactive Phase 16 shadow calculation and reconciliation (D18 row 16; D16 reports; ADR projection rule).

Phase 16 independently calculates what the legacy runtime and the
authoritative billing records (Phases 3-14) each say about the same
organization, then compares them, field by field, with exact integer
variances. It is evidence for the Phase 17 controlled cutover, never a
second financial authority.

* **Legacy side.** Pure re-computations of what the legacy runtime would
  report at ``at`` (``legacy_member_outcome`` mirrors
  ``billing_config.get_usage_meter_state`` and ``effective_plan_key``
  without their write-on-read resets; ``legacy_seat_usage`` mirrors
  ``orgs.build_seat_usage``), plus the stored legacy rows they read. No
  legacy function that writes is ever called.
* **Authoritative side.** The Phase 13 projections over the Phase 3 ledger,
  re-checked against an independent sum of raw ledger entries, plus the
  Phase 4-12 records (entitlements, schedules, seats, reservations, cases,
  policy bindings) and the Phase 14 migration evidence.
* **Classification** (``MATCH``, ``MISMATCH``, ``UNRESOLVED``,
  ``NOT_APPLICABLE``). A mismatch names its ``difference``:
  ``genuine_discrepancy``; ``approved_policy_difference`` (with the approved
  policy, ``APPROVED_POLICY_DIFFERENCES``); ``d16_explained_difference`` (a
  Phase 13 D16 class); or ``legacy_activity_since_snapshot`` (the legacy
  evidence changed after the Phase 14 snapshot). Nothing is forced to agree:
  a comparison without meaningful evidence on both sides is ``unresolved``
  or ``not_applicable``, never a match.
* **Read-only execution** (``run_shadow_reconciliation``). One fresh
  connection whose transaction the database itself makes read-only
  (PostgreSQL ``REPEATABLE READ READ ONLY``; SQLite ``PRAGMA query_only``),
  always rolled back, refused in a production runtime and, for
  ``fixtures``, on anything but a verified local test database (the Phase 15
  guard). ``restore_copy`` is refused outright until an approved
  authorization mechanism exists (review N4).
* **Scope** (review N2, FR-1). Every section, global ones included, covers only
  records the target organizations own by Phase 14-15 evidence
  (``payment_owner``, ``operation_owner``, Phase 14 value owners); membership
  never establishes ownership. A related record whose owner is unresolved is
  listed by identifier only, blocks, and is counted in no total.
  Population-wide evidence is aggregate counts only. A write attempted by any code path fails the run
  (``ShadowWriteAttemptError``); it is never swallowed.
* **Determinism.** For the same database state, ``at``, targets, and
  attestation, every comparison and the ``report_fingerprint`` are
  identical; ``generated_at`` is the only field outside the fingerprint.

Carried from the Phase 15 acceptance (traceability "Carried to Phase 16"):
L1 post-side settled, expired, and reversed totals come from ledger entries
(``ledger_movements``); L2 the repeat proof is census based
(``shadow_repeat_proof``); I1 the legacy pool rule is Phase 14's (an active
member on a pooled plan); I2 the census covers ``credit_reservations`` and
every Phase 4-14 table (``SHADOW_CENSUS_TABLES``); N2 the writer freeze is
proven per account from recomputed evidence fingerprints, not attested; N4
the founder-test attestation is a required argument.

Nothing in live routes, the AI runtime, webhooks, jobs, scripts, or startup
calls this module.
"""

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math

from sqlalchemy import func, or_, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from . import db
from .ai_governance import CREDITS_PER_PROVIDER_DOLLAR, INTERNAL_UNITS_PER_CREDIT
from .billing_config import (
    DEFAULT_PLAN_CATALOG,
    PLAN_RANK,
    SHARED_POOL_PLANS,
    SOFT_STOP_GRACE_MULTIPLIER,
    normalize_plan_key,
    subscription_in_good_standing,
)
from .billing_entitlements import add_calendar_months
from .ai_audit import TERMINAL_STATUSES as TERMINAL_OPERATION_STATUSES
from .billing_migration import (
    LIVE_SUBSCRIPTION_STATUSES,
    MigrationError,
    _database_clock,
    blocking_legacy_operations,
    holder_fingerprint,
    plan_account_backfill,
    plan_payment_archive,
    pricing_unit_findings,
    resolve_legacy_value_owner,
)
from .billing_projections import (
    CLASSIFICATIONS as D16_CLASSES,
    EVIDENCE_BACKED_ADJUSTMENT,
    MATCH as D16_MATCH,
    PROJECTION_DUPLICATION,
    STALE_COUNTER,
    UNRESOLVED as D16_UNRESOLVED,
    ProjectionError,
    _int_or_none,
    _lot_balances,
    _meter,
    _open_at,
    _parsed,
    _utc,
    compare_legacy_compatibility,
    project_billing_account,
)
from . import billing_rehearsal as _phase15
from .billing_rehearsal import (
    CENSUS_TABLES as PHASE15_CENSUS_TABLES,
    PURCHASED_LOT_SOURCES,
    RehearsalError,
    UNIT_BOUNDARY_AT,
    founder_test_credit_separation,
    legacy_fingerprint,
)
from .models import (
    AccountEntitlement,
    AIOperation,
    BillingAccount,
    CapacityPolicyVersion,
    CreditLedgerEntry,
    Organization,
    OrganizationInvitation,
    OrganizationMember,
    Payment,
    PersistentCreditGrant,
    PersistentCreditTransaction,
    PricingPolicyVersion,
    UsageEvent,
    User,
)
from .models_billing_phase4 import EntitlementDefinition
from .models_billing_phase5 import FinancialCase, FinancialCaseEvent, FinancialCaseEventLedgerEntry, \
    FinancialTransaction
from .models_billing_phase12 import CONVERSION_KEY, AIBillingOperation
from .models_billing_phase14 import (
    BillingMigrationAccountResult,
    BillingMigrationOpening,
    BillingMigrationPayerBinding,
    BillingMigrationPaymentArchive,
    BillingMigrationPaymentAttribution,
    BillingMigrationPlanMapping,
    BillingMigrationReview,
)
from .orgs import ORG_EDIT_ROLES, normalize_org_role


SHADOW_VERSION = "jaspen.billing.shadow.v1"
ENVIRONMENTS = ("fixtures", "restore_copy")
# Review N4: environments refused outright until a founder-approved restore-copy authorization mechanism exists.
RESTORE_COPY_REFUSED = frozenset(("restore_copy",))

MATCH = "match"
MISMATCH = "mismatch"
UNRESOLVED = "unresolved"
NOT_APPLICABLE = "not_applicable"
CLASSIFICATIONS = (MATCH, MISMATCH, UNRESOLVED, NOT_APPLICABLE)

GENUINE = "genuine_discrepancy"
POLICY = "approved_policy_difference"
D16_EXPLAINED = "d16_explained_difference"
SINCE_SNAPSHOT = "legacy_activity_since_snapshot"
DIFFERENCES = (GENUINE, POLICY, D16_EXPLAINED, SINCE_SNAPSHOT)

DOMAINS = (
    "migration_evidence", "balances", "funding", "credit_periods", "plan_and_schedule", "seats",
    "reservations_and_holds", "ai_usage", "financial_cases", "financial_attribution", "policy_versions",
    "ledger_integrity",
)

# Differences the founder or the approved architecture already decided; each names its approval.
APPROVED_POLICY_DIFFERENCES = {
    "delivered_only_billing": (
        "P24 and the AI billability policy (2026-11-11): only a delivered response is charged; undelivered "
        "usage is absorbed with evidence, where legacy charged the operation"),
    "dispute_holds_before_reversal": (
        "P11 (founder approval 2026-11-09): an opened or pending dispute holds the source; legacy reversed "
        "the unused remainder when the chargeback was created"),
    "proportional_refund": (
        "P05 (founder approval 2026-11-09): a partial refund reverses purchase-specific unused credits in "
        "proportion; legacy reversed the whole unused remainder"),
    "founder_test_requires_complete_attestation": (
        "founder decision 2026-11-19 with acceptance C2: a team-pool lot is founder test only when every invoice "
        "of its one bound payer is attested and no other member pays; anything mixed stays unverified"),
    "term_bound_packs": (
        "founder policy 2026-11-15: credit packs bought on the new ledger expire at the paid term end; legacy "
        "packs never expire (migrated legacy packs keep their non-expiring terms)"),
}

# Phase 15 pool funding bases that apply the approved complete-attestation policy (review N3). Every other basis
# (``account_not_mapped``, ``invoice_not_attributed_to_this_account``, or anything unknown) is missing evidence.
POOL_POLICY_BASES = frozenset(("another_member_holds_a_paid_subscription", "invoices_not_all_attested_test_activity"))

# Census (I2): every Phase 15 table plus the reservation table and every Phase 4-12 table a comparison reads.
SHADOW_CENSUS_TABLES = tuple(dict.fromkeys(PHASE15_CENSUS_TABLES + (
    "credit_reservations", "ai_billing_operations", "ai_capacity_decisions", "ai_provider_call_usage",
    "ai_absorbed_usage", "ai_operation_checkpoints", "credit_periods", "entitlement_definitions",
    "entitlement_events", "recurring_credit_allocations", "scheduled_plan_changes", "upgrade_credit_allocations",
    "seat_commitments", "seat_changes", "financial_lines", "financial_cases", "financial_case_events",
    "financial_case_event_ledger_entries", "credit_purchase_fundings", "financial_case_credit_effects",
    "credit_offer_redemptions", "credit_offer_fundings", "enterprise_contracts", "external_event_inbox",
    "domain_events", "communication_outbox", "billing_migration_reviews",
    "users", "organizations", "organization_members", "persistent_credit_grants",
    "persistent_credit_transactions", "payments", "account_entitlements", "ai_operations", "usage_events",
)))

# Legacy paid-seat roles (orgs.build_seat_usage: owner, admin, creator, collaborator).
LEGACY_PAID_ROLES = frozenset(ORG_EDIT_ROLES)
# Ledger movement types (L1); every CreditLedgerEntry.entry_type.
ENTRY_TYPES = ("grant", "migration_opening", "reservation", "settlement", "release", "expiration",
               "refund_reversal", "dispute_hold", "dispute_reversal", "recovery", "admin_adjustment")
# Label for an operation when a caller-supplied classifier cannot tell; the default label is now the
# Phase 14 class (BI-1, ``billing_migration.classify_legacy_operation``).
UNCLASSIFIED = "unclassified"
# Labels meaning the operation's process is gone but its credits were never released: still evidence,
# never authority to release anything.
STALE_LABELS = frozenset({"stale", "stale_turn_evidence", "outstanding_reservation"})


class ShadowError(MigrationError):
    """A shadow comparison that cannot run as asked."""


class ShadowWriteAttemptError(ShadowError):
    """Something tried to write inside the read-only shadow transaction; the run fails closed."""


def _fingerprint(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _iso(value):
    value = _utc(value)
    return value.isoformat() if value is not None else None


def _naive(value):
    return _utc(value).replace(tzinfo=None)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


# ---------------------------------------------------------------------------
# One comparison record
# ---------------------------------------------------------------------------

def _row(domain, key, *, subject, legacy, authoritative, classification, ctx=None, difference=None,
         policy=None, d16_class=None, special_case=None, explanation=None, subsystem, legacy_evidence=None,
         authoritative_evidence=None, period=None, operation_id=None, blocks_cutover=None):
    """A comparison with both values, their evidence, the exact variance, and its classification."""
    assert domain in DOMAINS and classification in CLASSIFICATIONS
    if classification == MISMATCH:
        assert difference in DIFFERENCES, (domain, key, difference)
        if difference == POLICY:
            assert policy in APPROVED_POLICY_DIFFERENCES, policy
    else:
        assert difference is None and policy is None
    if blocks_cutover is None:
        blocks_cutover = classification == UNRESOLVED or (
            classification == MISMATCH and difference in (GENUINE, SINCE_SNAPSHOT))
    return {
        "domain": domain, "comparison": key, "subject": subject,
        "billing_account_id": ctx["account_id"] if ctx else None,
        "organization_id": ctx["organization_id"] if ctx else None,
        "period": period,
        "legacy": {"value": legacy, "evidence": legacy_evidence},
        "authoritative": {"value": authoritative, "evidence": authoritative_evidence},
        "variance": authoritative - legacy if _is_int(legacy) and _is_int(authoritative) else None,
        "classification": classification, "difference": difference,
        "approved_policy": APPROVED_POLICY_DIFFERENCES[policy] if policy else None, "policy_key": policy,
        "d16_class": d16_class, "special_case": special_case, "explanation": explanation,
        "responsible_subsystem": subsystem, "operation_id": operation_id,
        "migration": ctx["migration_ref"] if ctx else None,
        "blocks_cutover": bool(blocks_cutover),
    }


def _equal_or(domain, key, legacy, authoritative, *, otherwise=GENUINE, **kwargs):
    if legacy == authoritative:
        return _row(domain, key, legacy=legacy, authoritative=authoritative, classification=MATCH, **kwargs)
    return _row(domain, key, legacy=legacy, authoritative=authoritative, classification=MISMATCH,
                difference=otherwise, **kwargs)


# ---------------------------------------------------------------------------
# Legacy calculations (pure re-computations; no write-on-read legacy function is called)
# ---------------------------------------------------------------------------

def _legacy_reset(raw, fallback):
    if isinstance(raw, str) and raw.strip():
        parsed = _parsed(raw)
        if parsed is not None:
            return parsed
    return _utc(fallback) if fallback is not None else None


def _legacy_due(last_reset, at):
    """``billing_config._cycle_reset_due``: no reset date, or at/after one calendar month later."""
    return last_reset is None or at >= add_calendar_months(last_reset, 1)


def _monthly_limit(plan_key):
    return (DEFAULT_PLAN_CATALOG.get(normalize_plan_key(plan_key)) or {}).get("monthly_credits")


def _non_negative(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def legacy_persistent_balance(session, user_id, *, source=None):
    """``founder_entitlements.persistent_credit_balance`` (active grants with value), read only."""
    query = select(func.coalesce(func.sum(PersistentCreditGrant.remaining_amount), 0)).where(
        PersistentCreditGrant.user_id == user_id, PersistentCreditGrant.status == "active",
        PersistentCreditGrant.remaining_amount > 0)
    if source:
        query = query.where(PersistentCreditGrant.source == source)
    return int(session.execute(query).scalar_one())


def legacy_effective_plan(session, user):
    """``billing_config.effective_plan_key`` with the default catalog, read only."""
    plan_key = normalize_plan_key(user.subscription_plan)
    if plan_key == "free":
        access = "free"
    elif subscription_in_good_standing(user.subscription_status):
        access = plan_key
    elif (DEFAULT_PLAN_CATALOG.get(plan_key) or {}).get("sales_only"):
        access = plan_key
    else:
        access = "free"
    has_300k = session.execute(select(func.count()).select_from(AccountEntitlement).where(
        AccountEntitlement.user_id == user.id, AccountEntitlement.entitlement_key == "300k_limited_time",
        AccountEntitlement.revoked_at.is_(None))).scalar_one() > 0
    if has_300k and PLAN_RANK.get(access, 0) < PLAN_RANK["essential"]:
        return "essential"
    return access


def legacy_member_outcome(session, user, *, at):
    """What ``billing_config.get_usage_meter_state`` would report for ``user`` at ``at`` (pure).

    The legacy reader resets a due cycle on read (STOP-01); here a due cycle
    is reported as the refill the legacy runtime would show (``reset_due``),
    and nothing is written. Organization pools follow the legacy reader: the
    user's ``active_organization_id`` names the pool for a shared-pool plan.
    """
    at = _utc(at)
    plan_key = normalize_plan_key(user.subscription_plan)
    monthly_limit = _monthly_limit(plan_key)
    grace = int(math.floor(int(monthly_limit) * max(0.0, SOFT_STOP_GRACE_MULTIPLIER - 1.0))) \
        if monthly_limit is not None else 0
    persistent = legacy_persistent_balance(session, user.id)
    base = {"plan_key": plan_key, "effective_plan_key": legacy_effective_plan(session, user),
            "monthly_limit": monthly_limit, "grace_tokens": grace, "persistent_remaining": persistent}
    if plan_key in SHARED_POOL_PLANS:
        org = session.get(Organization, user.active_organization_id) if user.active_organization_id else None
        if org is None:
            remaining = int(user.credits_remaining or 0)
            return {**base, "scope": "user", "organization_id": None, "monthly_remaining": None,
                    "remaining": remaining, "reset_at": _iso(user.credits_reset_at), "next_reset_at": None,
                    "reset_due": False, "cycle_limit": int(monthly_limit or 0), "overage_tokens": 0,
                    "basis": "shared-pool plan without an active organization: the stored combined counter"}
        meter = _meter(org.settings) or {}
        limit = _non_negative(monthly_limit)
        overage = _non_negative(meter.get("overage_tokens"))
        reset = _legacy_reset(meter.get("cycle_reset_at"), None)
        due = _legacy_due(reset, at)
        if due:
            monthly, cycle_limit, overage, reset = limit, limit, 0, at
        else:
            cycle_limit = limit + overage
            monthly = int(meter.get("remaining", cycle_limit))
        return {**base, "scope": "organization", "organization_id": org.id, "monthly_remaining": monthly,
                "remaining": monthly + persistent, "reset_at": _iso(reset),
                "next_reset_at": _iso(add_calendar_months(reset, 1)), "reset_due": due,
                "cycle_limit": cycle_limit, "overage_tokens": overage,
                "basis": "organization pool named by the legacy active organization"}
    meter = _meter(user.ui_preferences) or {}
    limit = _non_negative(monthly_limit)
    overage = _non_negative(meter.get("overage_tokens"))
    reset = _legacy_reset(meter.get("cycle_reset_at"), user.credits_reset_at)
    due = _legacy_due(reset, at)
    if due:
        monthly, cycle_limit, overage, reset = limit, limit, 0, at
    else:
        cycle_limit = limit + overage
        if "remaining" in meter:
            monthly = int(meter.get("remaining", cycle_limit))
        else:
            monthly = cycle_limit if user.credits_remaining is None else int(user.credits_remaining) - persistent
    return {**base, "scope": "user", "organization_id": None, "monthly_remaining": monthly,
            "remaining": monthly + persistent, "reset_at": _iso(reset),
            "next_reset_at": _iso(add_calendar_months(reset, 1)), "reset_due": due,
            "cycle_limit": cycle_limit, "overage_tokens": overage, "basis": "the user's personal meter"}


def legacy_seat_usage(session, organization, *, at):
    """``orgs.build_seat_usage`` paid totals (owner, admin, creator, collaborator), read only."""
    roles = session.execute(select(OrganizationMember.role).where(
        OrganizationMember.organization_id == organization.id, OrganizationMember.status == "active")).scalars()
    used = sum(1 for role in roles if normalize_org_role(role) in LEGACY_PAID_ROLES)
    pending = session.execute(select(OrganizationInvitation.role).where(
        OrganizationInvitation.organization_id == organization.id,
        OrganizationInvitation.status == "pending",
        OrganizationInvitation.expires_at > _naive(at))).scalars()
    pending_paid = sum(1 for role in pending if normalize_org_role(role) in LEGACY_PAID_ROLES)
    return {"total_paid_used": used, "total_paid_pending": pending_paid, "total_paid_reserved": used + pending_paid,
            "total_paid_limit": organization.max_total_paid_seats}


# ---------------------------------------------------------------------------
# Authoritative re-computations (independent of the projections)
# ---------------------------------------------------------------------------

def ledger_movements(session, account_id):
    """Every ledger movement of one account by entry type, from raw entries (L1; pure).

    Settled, expired, and reversed totals are read from the ledger, never
    assumed; ``available_total`` and ``held_total`` are the plain sums every
    projection must equal.
    """
    rows = session.execute(
        select(CreditLedgerEntry.entry_type, func.count(),
               func.coalesce(func.sum(CreditLedgerEntry.available_delta), 0),
               func.coalesce(func.sum(CreditLedgerEntry.held_delta), 0))
        .where(CreditLedgerEntry.billing_account_id == account_id).group_by(CreditLedgerEntry.entry_type)
    ).all()
    by_type = {kind: {"entries": 0, "available_delta": 0, "held_delta": 0} for kind in ENTRY_TYPES}
    for kind, count, available, held in rows:
        by_type[kind] = {"entries": int(count), "available_delta": int(available), "held_delta": int(held)}
    return {
        "by_entry_type": by_type,
        "available_total": sum(v["available_delta"] for v in by_type.values()),
        "held_total": sum(v["held_delta"] for v in by_type.values()),
        "settled": -by_type["settlement"]["held_delta"] - by_type["settlement"]["available_delta"],
        "expired": -by_type["expiration"]["available_delta"],
        "refund_reversed": -(by_type["refund_reversal"]["available_delta"] + by_type["refund_reversal"]["held_delta"]),
        "dispute_held": by_type["dispute_hold"]["held_delta"],
        "dispute_reversed": -(by_type["dispute_reversal"]["available_delta"]
                              + by_type["dispute_reversal"]["held_delta"]),
        "recovered": by_type["recovery"]["available_delta"],
        "adjusted": by_type["admin_adjustment"]["available_delta"],
        "opened": by_type["migration_opening"]["available_delta"],
    }


def _version_effective_at(session, model, at):
    """The approved version in force at ``at`` by its own dates, whatever its state is now."""
    rows = session.execute(select(model).where(
        model.effective_at.is_not(None), model.effective_at <= at,
        model.state.in_(("effective", "superseded")),
    ).order_by(model.effective_at, model.id)).scalars().all()
    in_force = [v for v in rows if v.superseded_at is None or _utc(v.superseded_at) > at]
    return in_force


# ---------------------------------------------------------------------------
# Account context
# ---------------------------------------------------------------------------

def _latest(session, model, account_id):
    return session.execute(select(model).where(model.billing_account_id == account_id)
                           .order_by(model.created_at.desc(), model.id.desc()).limit(1)).scalar_one_or_none()


def _context(session, account, at):
    result = _latest(session, BillingMigrationAccountResult, account.id)
    mapping = _latest(session, BillingMigrationPlanMapping, account.id)
    return {
        "account": account, "account_id": account.id, "organization_id": account.organization_id,
        "organization": session.get(Organization, account.organization_id), "at": at,
        "result": result, "mapping": mapping,
        "migration_ref": None if result is None else {
            "run_id": result.run_id, "account_result_id": result.id, "outcome": result.outcome,
            "snapshot_at": _iso(result.snapshot_at), "evidence_fingerprint": result.evidence_fingerprint,
            "plan_mapping_id": mapping.id if mapping else None,
        },
        "members": [session.get(User, uid) for uid in session.execute(
            select(OrganizationMember.user_id).where(OrganizationMember.organization_id == account.organization_id,
                                                     OrganizationMember.status == "active")
            .order_by(OrganizationMember.user_id)).scalars()],
    }


# ---------------------------------------------------------------------------
# Domains
# ---------------------------------------------------------------------------

def _migration_evidence(session, ctx, plan):
    """N2: the legacy evidence behind this account is unchanged since the Phase 14 snapshot (or not)."""
    result = ctx["result"]
    if result is None:
        return [_row("migration_evidence", "legacy_evidence_since_snapshot", subject=ctx["account_id"], ctx=ctx,
                     legacy=None, authoritative=None, classification=UNRESOLVED,
                     special_case="no_migration_snapshot", subsystem="phase14_backfill",
                     explanation="no Phase 14 result: there is no snapshot to compare the legacy evidence with")]
    rows = [_equal_or(
        "migration_evidence", "legacy_evidence_since_snapshot", plan["evidence_fingerprint"],
        result.evidence_fingerprint, subject=ctx["account_id"], ctx=ctx, otherwise=SINCE_SNAPSHOT,
        subsystem="phase14_backfill", legacy_evidence={"recomputed_at": _iso(ctx["at"])},
        authoritative_evidence={"stored_snapshot_at": _iso(result.snapshot_at)},
        explanation="recomputed Phase 14 evidence fingerprint against the stored snapshot fingerprint; a "
                    "difference proves a legacy write after the snapshot (writer freeze not held)")]
    stored = {h.get("user_id"): holder_fingerprint(h) for h in (result.evidence_json or {}).get("holders") or []}
    current = {h.get("user_id"): holder_fingerprint(h) for h in plan["evidence"]["holders"]}
    for user_id in sorted(set(stored) | set(current)):
        rows.append(_equal_or("migration_evidence", "holder_evidence_since_snapshot", current.get(user_id),
                              stored.get(user_id), subject=user_id, ctx=ctx, otherwise=SINCE_SNAPSHOT,
                              subsystem="phase14_backfill",
                              explanation="this holder's counter, meter, grants, and payments since the snapshot"))
    return rows


def _changed_holders(rows):
    return {r["subject"] for r in rows if r["comparison"] == "holder_evidence_since_snapshot"
            and r["classification"] == MISMATCH}


# ---------------------------------------------------------------------------
# Ownership (review FR-1): membership never establishes ownership of a financial record
# ---------------------------------------------------------------------------

def _account_organization(session, account_id, cache):
    key = ("account", account_id)
    if key not in cache:
        account = session.get(BillingAccount, account_id) if account_id else None
        cache[key] = account.organization_id if account is not None else None
    return cache[key]


def _value_owner(session, user_id, cache):
    """The Phase 14 owner of a user's personal legacy value (``resolve_legacy_value_owner``; pure).

    Ranked evidence only: payer evidence, then the pooled organization the
    user owns and pays for, then the sole-member organization, pinned by any
    Phase 14 binding or attribution. Membership and the active organization
    are never consulted; a payment's organization stamp is only a veto.
    """
    key = ("user", user_id)
    if key not in cache:
        user = session.get(User, user_id) if user_id else None
        if user is None:
            cache[key] = (None, "payer_missing")
        else:
            owner = resolve_legacy_value_owner(session, user)
            cache[key] = (owner["organization_id"], owner["reason"])
    return cache[key]


def payment_owner(session, payment, cache):
    """``(organization_id or None, basis)`` for one legacy payment, from Phase 14-15 evidence only (pure).

    1. The Phase 14 payment attribution (globally unique, made at establishment).
    2. The legacy payment's own billing-account link (rank-1 payer evidence).
    3. The payer's Phase 14 value owner.
    The two account-level sources must agree; any disagreement or missing
    evidence returns ``None`` with the reason, so the payment is unresolved.
    """
    attributed = session.execute(select(BillingMigrationPaymentAttribution.billing_account_id).where(
        BillingMigrationPaymentAttribution.payment_id == payment.id)).scalars().all()
    attributed_orgs = {_account_organization(session, a, cache) for a in attributed}
    linked_org = _account_organization(session, payment.billing_account_id, cache) \
        if payment.billing_account_id else None
    if len(attributed_orgs) > 1 or None in attributed_orgs:
        return None, "payment_attribution_conflict"
    if attributed_orgs and linked_org is not None and attributed_orgs != {linked_org}:
        return None, "payment_owner_conflict"
    if attributed_orgs:
        return next(iter(attributed_orgs)), "phase14_payment_attribution"
    if linked_org is not None:
        return linked_org, "legacy_payment_account_link"
    if payment.user_id is None:
        return None, "payment_without_payer"
    owner, reason = _value_owner(session, payment.user_id, cache)
    return (owner, f"payer_value_owner:{reason}") if owner else (None, reason)


def operation_owner(session, op, cache):
    """``(organization_id or None, basis)`` for one AI operation's credit effect (pure).

    A Phase 12-bound operation belongs to its billing account. An unbound
    legacy operation debited the meter its user's plan names: a personal
    meter belongs to the user's Phase 14 value owner; a pooled plan debited
    the pool of the legacy active organization, which no record proves (the
    operation's organization stamp is not evidence), so its owner is unresolved.
    """
    if op.billing_account_id:
        owner = _account_organization(session, op.billing_account_id, cache)
        return (owner, "phase12_billing_account") if owner else (None, "billing_account_missing")
    user = session.get(User, op.user_id) if op.user_id else None
    if user is None:
        return None, "operation_without_user"
    if normalize_plan_key(user.subscription_plan) in SHARED_POOL_PLANS:
        return None, "pooled_debit_location_unrecorded"
    owner, reason = _value_owner(session, user.id, cache)
    return (owner, f"user_value_owner:{reason}") if owner else (None, reason)


def _in_flight(session, ctx, related_user_ids, classifier, at, cache):
    """Blocking unclosed operations this organization owns, or whose owner is unresolved for a related user.

    BI-1: the same Phase 14 status as the backfill and the drain gate
    (``billing_migration.legacy_operation_status``): an operation proven
    already charged, or cleared by a recorded decision, is not in flight. The
    label is the Phase 14 class unless a classifier is supplied.
    """
    out = []
    query = select(AIOperation).where(or_(AIOperation.status.is_(None),
                                          AIOperation.status.notin_(sorted(TERMINAL_OPERATION_STATUSES))))
    filters = [AIOperation.billing_account_id == ctx["account_id"]]
    if related_user_ids:
        filters.append(AIOperation.user_id.in_(sorted(related_user_ids)))
    unclosed = session.execute(query.where(or_(*filters)).order_by(AIOperation.id)).scalars().all()
    blocking = {b["operation_id"]: b for b in blocking_legacy_operations(session, unclosed, at)}
    for op in unclosed:
        status = blocking.get(op.id)
        if status is None:
            continue  # not blocking under Phase 14: already charged, or cleared by a recorded decision
        owner, basis = operation_owner(session, op, cache)
        if owner is not None and owner != ctx["organization_id"]:
            continue  # owned by another organization by evidence: never this organization's record
        label = classifier(session, op, at) if classifier else status["class"]
        out.append((op, label, owner is not None, basis))
    return out


def _balances(session, ctx, plan, changed, in_flight, owners):
    rows = []
    at = ctx["at"]
    in_flight_users = {op.user_id for op, _label, _owned, _basis in in_flight}
    for user in ctx["members"]:
        personal_pool = normalize_plan_key(user.subscription_plan) not in SHARED_POOL_PLANS
        owner = owners.get(user.id, ctx["organization_id"])
        if personal_pool and owner != ctx["organization_id"]:
            rows.append(_row("balances", "member_spendable", subject=user.id, ctx=ctx, legacy=None,
                             authoritative=None, classification=NOT_APPLICABLE if owner else UNRESOLVED,
                             special_case=None if owner else "ambiguous_owner", subsystem="phase14_backfill",
                             explanation="personal legacy value owned by another organization by Phase 14 "
                                         "evidence; compared in that organization's report" if owner else
                                         "the owner of this personal legacy value is unresolved"))
            continue
        legacy = legacy_member_outcome(session, user, at=at)
        member = project_billing_account(session, billing_account_id=ctx["account_id"], at=at,
                                         member_user_id=user.id)
        target = member["credits"]["member_spendable"]
        kwargs = dict(subject=user.id, ctx=ctx, subsystem="phase13_projection",
                      legacy_evidence={k: legacy[k] for k in ("scope", "organization_id", "monthly_remaining",
                                                              "persistent_remaining", "reset_at", "reset_due",
                                                              "basis")},
                      authoritative_evidence={"by_source": member["credits"]["by_source"],
                                              "held": member["credits"]["held"],
                                              "attributed_to_other_members":
                                                  member["credits"]["attributed_to_other_members"]})
        if legacy["scope"] == "organization" and legacy["organization_id"] != ctx["organization_id"]:
            # FR-1: the other organization's pool amount and identifier stay in that organization's report.
            kwargs["legacy_evidence"] = {"scope": "organization", "organization_id": "another_organization",
                                         "basis": legacy["basis"]}
            rows.append(_row("balances", "member_spendable", legacy=None, authoritative=target,
                             classification=MISMATCH, difference=GENUINE,
                             special_case="legacy_pool_from_another_organization",
                             explanation="the legacy reader spends the pool of the user's active organization, "
                                         "not this organization's (no active-organization leakage, T-OWNER); "
                                         "that pool's value is withheld here", **kwargs))
        elif legacy["remaining"] == target:
            rows.append(_row("balances", "member_spendable", legacy=legacy["remaining"], authoritative=target,
                             classification=MATCH, **kwargs))
        elif user.id in in_flight_users:
            rows.append(_row("balances", "member_spendable", legacy=legacy["remaining"], authoritative=target,
                             classification=UNRESOLVED, special_case="in_flight_operation",
                             explanation="a legacy operation holds an unrecorded meter debit; never inferred",
                             **kwargs))
        elif legacy["reset_due"] and member["effective_plan_key"] is None:
            rows.append(_row("balances", "member_spendable", legacy=legacy["remaining"], authoritative=target,
                             classification=UNRESOLVED, special_case="renewal_due_without_authoritative_allocation",
                             explanation="legacy refills the due cycle on read; the ledger opens a new period only "
                                         "from an approved entitlement through the Phase 6 allocator (cutover gate)",
                             **kwargs))
        elif plan["quarantine"]:
            rows.append(_row("balances", "member_spendable", legacy=legacy["remaining"], authoritative=target,
                             classification=UNRESOLVED, special_case="legacy_evidence_quarantined",
                             explanation="the account's legacy evidence quarantines; nothing was opened to compare",
                             **kwargs))
        elif user.id in changed:
            rows.append(_row("balances", "member_spendable", legacy=legacy["remaining"], authoritative=target,
                             classification=MISMATCH, difference=SINCE_SNAPSHOT,
                             explanation="the holder's legacy evidence changed after the snapshot", **kwargs))
        else:
            rows.append(_row("balances", "member_spendable", legacy=legacy["remaining"], authoritative=target,
                             classification=MISMATCH, difference=GENUINE,
                             explanation="no approved policy or recorded evidence explains this difference",
                             **kwargs))

    # The account as a whole: what Phase 14 would open from today's legacy evidence vs the ledger today.
    balances = _lot_balances(session, ctx["account_id"])
    open_total = sum(a + h for lot, a, h in balances if _open_at(lot, at))
    expected = sum(o["opening_amount"] for o in plan["openings"])
    codes = sorted({c["code"] for c in plan["quarantine"]})
    kwargs = dict(subject=ctx["account_id"], ctx=ctx, subsystem="phase14_backfill",
                  legacy_evidence={"accepted": plan["accepted"], "quarantine_codes": codes},
                  authoritative_evidence={"open_lots": sum(1 for lot, a, h in balances if _open_at(lot, at))})
    if codes:
        rows.append(_row("balances", "account_preserved_value", legacy=expected, authoritative=open_total,
                         classification=UNRESOLVED, special_case="legacy_evidence_quarantined",
                         explanation="the legacy evidence quarantines; no balance comparison is meaningful", **kwargs))
    elif expected == open_total:
        rows.append(_row("balances", "account_preserved_value", legacy=expected, authoritative=open_total,
                         classification=MATCH, explanation="D16 conservation recomputed at the comparison time",
                         **kwargs))
    else:
        rows.append(_row("balances", "account_preserved_value", legacy=expected, authoritative=open_total,
                         classification=MISMATCH, difference=SINCE_SNAPSHOT if changed else GENUINE,
                         explanation="the conservation equation no longer holds", **kwargs))
    return rows


def _funding(session, ctx, plan, changed, separation):
    rows = []
    at = ctx["at"]
    legacy = Counter()
    for opening in plan["openings"]:
        legacy[opening["lot_source_type"]] += opening["opening_amount"]
    target = Counter()
    for lot, available, held in _lot_balances(session, ctx["account_id"]):
        if _open_at(lot, at):
            target[lot.source_type] += available + held
    quarantined = bool(plan["quarantine"])
    for source in sorted(set(legacy) | set(target) | {"credit_pack_purchase", "promotional", "free_recurring",
                                                       "subscription_recurring", "trial", "comp", "internal"}):
        kwargs = dict(subject=f"{ctx['account_id']}:{source}", ctx=ctx, subsystem="phase3_ledger")
        if source in ("trial", "comp", "internal") and not target[source] and not legacy[source]:
            rows.append(_row("funding", "open_value_by_source", legacy=None, authoritative=0,
                             classification=NOT_APPLICABLE, period=source,
                             explanation="legacy has no trial, comp, or internal funding; none in the ledger", **kwargs))
        elif quarantined:
            rows.append(_row("funding", "open_value_by_source", legacy=legacy[source], authoritative=target[source],
                             classification=UNRESOLVED, special_case="legacy_evidence_quarantined", period=source,
                             **kwargs))
        elif source in ("trial", "comp", "internal") and target[source]:
            rows.append(_row("funding", "open_value_by_source", legacy=0, authoritative=target[source],
                             classification=UNRESOLVED, special_case="authoritative_only_funding", period=source,
                             explanation="ledger funding with no legacy counterpart is never matched by default",
                             **kwargs))
        else:
            rows.append(_equal_or("funding", "open_value_by_source", legacy[source], target[source], period=source,
                                  otherwise=SINCE_SNAPSHOT if changed else GENUINE, **kwargs))

    # Purchased-credit preservation: each migrated grant keeps its exact principal and remainder.
    openings = {o.legacy_source_id: o for o in session.execute(select(BillingMigrationOpening).where(
        BillingMigrationOpening.billing_account_id == ctx["account_id"],
        BillingMigrationOpening.legacy_source_kind == "persistent_credit_grant")).scalars()}
    for source in plan["sources"]:
        if source["kind"] != "persistent_credit_grant":
            continue
        grant = source["grant"]
        opening = openings.get(grant["grant_id"])
        kwargs = dict(subject=grant["grant_id"], ctx=ctx, subsystem="phase14_backfill",
                      legacy_evidence={"source": grant["source"], "status": grant["status"],
                                       "payment_id": (grant.get("payment") or {}).get("payment_id"),
                                       "classification": source.get("classification")},
                      authoritative_evidence={"lot_id": opening.lot_id if opening else None,
                                              "opening_id": opening.id if opening else None})
        if source.get("classification") in ("reversed", "consumed"):
            rows.append(_equal_or("funding", "purchased_principal", 0, int(opening.original_amount) if opening else 0,
                                  explanation=f"a {source['classification']} legacy grant opens nothing", **kwargs))
        elif source.get("classification") == "quarantined":
            rows.append(_row("funding", "purchased_principal", legacy=grant["original_amount"],
                             authoritative=int(opening.original_amount) if opening else None,
                             classification=UNRESOLVED, special_case="legacy_evidence_quarantined", **kwargs))
        elif opening is None:
            rows.append(_row("funding", "purchased_principal", legacy=grant["original_amount"], authoritative=None,
                             classification=UNRESOLVED, special_case="preserved_grant_not_opened",
                             explanation="a preserved legacy grant has no migrated lot", **kwargs))
        else:
            rows.append(_equal_or("funding", "purchased_principal", grant["original_amount"],
                                  int(opening.original_amount), **kwargs))
            rows.append(_equal_or("funding", "purchased_remaining_at_opening", grant["remaining_amount"],
                                  int(opening.opening_amount),
                                  otherwise=SINCE_SNAPSHOT if source["member_attribution_id"] in changed else GENUINE,
                                  **kwargs))
            rows.append(_equal_or("funding", "purchased_expiry", None, _iso(opening.expires_at),
                                  explanation="legacy packs were sold non-expiring and keep those terms", **kwargs))

    # Founder-test separation (founder decision 2026-11-19): funding evidence of every migrated lot.
    for lot in separation["lots"]:
        if lot["billing_account_id"] != ctx["account_id"] or lot["lot_source_type"] not in (
                "credit_pack_purchase", "subscription_recurring", "promotional"):
            continue
        payments = lot["payment_ids"]
        archived = sorted({_archive_class(session, p) for p in payments})
        if not archived:
            expected = None
        elif archived == ["test_activity"]:
            expected = "founder_test"
        elif "unarchived" in archived:
            expected = "unarchived"
        else:
            expected = "unverified"
        kwargs = dict(subject=lot["lot_id"], ctx=ctx, subsystem="phase15_founder_test_separation",
                      legacy_evidence={"payment_ids": payments, "archived_classifications": archived},
                      authoritative_evidence={"funding": lot["funding"], "funding_basis": lot["funding_basis"],
                                              "attestation_references": lot["attestation_references"]})
        pool = lot["legacy_source_kind"] == "organization_recurring_meter"
        others = _other_paying_pool_members(session, ctx) if pool else []
        if pool and others and expected == "founder_test":
            # Independent of the plan mapping: any other pooled member with a live paid subscription mixes the pool.
            expected = "unverified"
            kwargs["legacy_evidence"]["other_paying_pool_members"] = others
        if expected is None:
            rows.append(_row("funding", "founder_test_classification", legacy=None, authoritative=lot["funding"],
                             classification=UNRESOLVED, special_case="no_payment_evidence",
                             explanation="funding without an archived payment is never genuine or test by default",
                             **kwargs))
        elif pool and expected == "founder_test" and lot["funding"] == "unverified" \
                and lot["funding_basis"] in POOL_POLICY_BASES:
            rows.append(_row("funding", "founder_test_classification", legacy=expected, authoritative=lot["funding"],
                             classification=MISMATCH, difference=POLICY,
                             policy="founder_test_requires_complete_attestation", **kwargs))
        elif pool and expected == "founder_test" and lot["funding"] == "unverified":
            # Review N3: a missing or unknown basis is missing evidence, never an approved policy (fail closed).
            rows.append(_row("funding", "founder_test_classification", legacy=expected, authoritative=lot["funding"],
                             classification=UNRESOLVED, special_case="team_pool_evidence_missing",
                             explanation="the pool stays unverified because supporting evidence is missing "
                                         f"({lot['funding_basis']}), not because of an approved policy", **kwargs))
        elif pool and others and lot["funding"] == "founder_test":
            rows.append(_row("funding", "founder_test_classification", legacy=expected, authoritative=lot["funding"],
                             classification=MISMATCH, difference=GENUINE,
                             special_case="pool_with_another_paying_member",
                             explanation="another active pooled member holds a live paid subscription, so the pool "
                                         "is mixed and must stay unverified (C2); the plan mapping did not list them",
                             **kwargs))
        else:
            rows.append(_equal_or("funding", "founder_test_classification", expected, lot["funding"], **kwargs))
    return rows


def _other_paying_pool_members(session, ctx):
    """Active pooled members other than the bound payer with a live legacy paid subscription (read only)."""
    payer = session.execute(select(BillingMigrationPayerBinding.payer_user_id).where(
        BillingMigrationPayerBinding.billing_account_id == ctx["account_id"])).scalar_one_or_none()
    return sorted(
        u.id for u in ctx["members"]
        if u.id != payer and normalize_plan_key(u.subscription_plan) in SHARED_POOL_PLANS
        and (u.subscription_status or "").strip().lower() in LIVE_SUBSCRIPTION_STATUSES and u.stripe_subscription_id)


def _archive_class(session, payment_id):
    row = session.execute(select(BillingMigrationPaymentArchive.classification).where(
        BillingMigrationPaymentArchive.payment_id == payment_id)).scalars().first()
    return row or "unarchived"


def _credit_periods(session, ctx, plan, projection):
    rows = []
    openings = {(o.legacy_source_kind, o.legacy_source_id): o for o in session.execute(
        select(BillingMigrationOpening).where(BillingMigrationOpening.billing_account_id == ctx["account_id"],
                                              BillingMigrationOpening.legacy_source_kind.in_(
                                                  ("user_recurring_meter", "organization_recurring_meter")))
    ).scalars()}
    from .models import CreditLot
    for source in plan["sources"]:
        if source["kind"] not in ("user_recurring_meter", "organization_recurring_meter"):
            continue
        subject = source["legacy_source_id"]
        period = f"{source.get('cycle_starts_at')}/{source.get('cycle_ends_at')}"
        opening = openings.get((source["kind"], subject))
        lot = session.get(CreditLot, opening.lot_id) if opening else None
        meter = source.get("meter") or {}
        kwargs = dict(subject=subject, ctx=ctx, subsystem="phase6_allocations", period=period,
                      legacy_evidence={"kind": source["kind"], "classification": source.get("classification"),
                                       "plan": source.get("plan")},
                      authoritative_evidence={"lot_id": lot.id if lot else None,
                                              "source_type": lot.source_type if lot else None})
        state = source.get("classification")
        if state == "live_cycle" and lot is not None:
            rows.append(_equal_or("credit_periods", "cycle_start", source["cycle_starts_at"], _iso(lot.available_at),
                                  **kwargs))
            rows.append(_equal_or("credit_periods", "cycle_expiry", source["cycle_ends_at"], _iso(lot.expires_at),
                                  **kwargs))
            rows.append(_equal_or("credit_periods", "cycle_allocation", meter.get("cycle_limit"),
                                  int(lot.original_amount), **kwargs))
        elif state == "expired_recurring_value":
            rows.append(_row("credit_periods", "cycle_expiry", legacy=source["cycle_ends_at"],
                             authoritative=_iso(lot.expires_at) if lot else None,
                             classification=MATCH if lot is None or not _open_at(lot, ctx["at"]) else MISMATCH,
                             difference=None if lot is None or not _open_at(lot, ctx["at"]) else GENUINE,
                             explanation="a lapsed cycle is never purchasing power on either side", **kwargs))
        elif state in ("live_cycle", "zero_remaining"):
            rows.append(_row("credit_periods", "cycle_allocation", legacy=meter.get("cycle_limit"), authoritative=None,
                             classification=MATCH if state == "zero_remaining" else UNRESOLVED,
                             special_case=None if state == "zero_remaining" else "live_cycle_not_opened",
                             explanation="a live cycle with nothing left opens no lot" if state == "zero_remaining"
                             else "a live legacy cycle has no migrated lot", **kwargs))
        else:
            rows.append(_row("credit_periods", "cycle_allocation", legacy=meter.get("cycle_limit"), authoritative=None,
                             classification=UNRESOLVED, special_case="legacy_meter_quarantined", **kwargs))

    # Renewal: legacy always refills one calendar month after the reset; the ledger only from an entitlement.
    owners = plan["owners"]
    for user in ctx["members"]:
        legacy = legacy_member_outcome(session, user, at=ctx["at"])
        if legacy["scope"] == "organization" and legacy["organization_id"] != ctx["organization_id"]:
            continue
        if legacy["scope"] == "user" and user.id in owners and owners[user.id] != ctx["organization_id"]:
            # FR-1: a personal meter owned elsewhere (or unresolved) is never this organization's renewal.
            if owners[user.id] is None:
                rows.append(_row("credit_periods", "next_renewal", subject=user.id, ctx=ctx, legacy=None,
                                 authoritative=None, classification=UNRESOLVED, special_case="ambiguous_owner",
                                 subsystem="phase14_backfill",
                                 explanation="the owner of this personal meter is unresolved"))
            continue
        authoritative = projection["next_allocation_at"]
        kwargs = dict(subject=user.id if legacy["scope"] == "user" else ctx["organization_id"], ctx=ctx,
                      subsystem="phase4_entitlements",
                      legacy_evidence={"reset_at": legacy["reset_at"], "reset_due": legacy["reset_due"],
                                       "scope": legacy["scope"]},
                      authoritative_evidence={"effective_plan_key": projection["effective_plan_key"]})
        if projection["effective_plan_key"] is None:
            rows.append(_row("credit_periods", "next_renewal", legacy=legacy["next_reset_at"],
                             authoritative=authoritative, classification=UNRESOLVED,
                             special_case="no_authoritative_entitlement",
                             explanation="no approved entitlement schedules a renewal (cutover gate: approved "
                                         "EntitlementDefinitions and the Phase 6 allocator)", **kwargs))
        else:
            rows.append(_equal_or("credit_periods", "next_renewal", legacy["next_reset_at"], authoritative, **kwargs))
    return _dedupe(rows)


def _dedupe(rows):
    seen, out = set(), []
    for row in rows:
        key = (row["domain"], row["comparison"], row["subject"], row["period"])
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out


def _plan_and_schedule(session, ctx, projection, owners):
    rows = []
    mapping = ctx["mapping"]
    subjects = {s.get("user_id"): s for s in ((mapping.mapping_json or {}).get("subjects") or [])} if mapping else {}
    for user in ctx["members"]:
        personal = normalize_plan_key(user.subscription_plan) not in SHARED_POOL_PLANS
        if personal and user.id in owners and owners[user.id] != ctx["organization_id"]:
            # FR-1: a personal plan and subscription owned elsewhere stay in that organization's report.
            for comparison in ("effective_plan", "subscription_status"):
                rows.append(_row("plan_and_schedule", comparison, subject=user.id, ctx=ctx, legacy=None,
                                 authoritative=None,
                                 classification=NOT_APPLICABLE if owners[user.id] else UNRESOLVED,
                                 special_case=None if owners[user.id] else "ambiguous_owner",
                                 subsystem="phase14_backfill",
                                 explanation="the member's personal subscription is owned by another organization "
                                             "by Phase 14 evidence" if owners[user.id] else
                                             "the owner of this member's personal subscription is unresolved"))
            continue
        legacy_plan = legacy_effective_plan(session, user)
        authoritative = projection["effective_plan_key"]
        mapped = subjects.get(user.id) or {}
        kwargs = dict(subject=user.id, ctx=ctx, subsystem="phase4_entitlements",
                      legacy_evidence={"subscription_plan": user.subscription_plan,
                                       "subscription_status": user.subscription_status},
                      authoritative_evidence={"plan_mapping_outcome": mapping.outcome if mapping else None,
                                              "mapped_plan_key": mapped.get("plan_key"),
                                              "plan_source_type": projection["plan_source_type"]})
        if authoritative is None:
            rows.append(_row("plan_and_schedule", "effective_plan", legacy=legacy_plan, authoritative=None,
                             classification=UNRESOLVED, special_case="no_authoritative_entitlement",
                             explanation="the Phase 14 plan mapping is evidence only; no entitlement exists until "
                                         "approved definitions are activated", **kwargs))
        else:
            rows.append(_equal_or("plan_and_schedule", "effective_plan", legacy_plan, authoritative, **kwargs))
        status = (user.subscription_status or "").strip().lower().replace("canceled", "cancelled") or None
        subscription = projection["subscription"]
        if subscription is None and status is None:
            rows.append(_row("plan_and_schedule", "subscription_status", legacy=None, authoritative=None,
                             classification=NOT_APPLICABLE, subject=user.id, ctx=ctx,
                             subsystem="phase4_entitlements", explanation="no subscription on either side"))
        elif subscription is None:
            rows.append(_row("plan_and_schedule", "subscription_status", legacy=status, authoritative=None,
                             classification=UNRESOLVED, special_case="subscription_not_materialized",
                             subject=user.id, ctx=ctx, subsystem="phase4_entitlements",
                             explanation="processor dates, seats, and schedule are unresolved until a separately "
                                         "authorized processor read"))
        else:
            rows.append(_equal_or("plan_and_schedule", "subscription_status", status, subscription["status"],
                                  subject=user.id, ctx=ctx, subsystem="phase4_entitlements"))
    schedule = projection["scheduled_plan_change"]
    rows.append(_row("plan_and_schedule", "scheduled_transition", subject=ctx["account_id"], ctx=ctx,
                     legacy=None, authoritative=schedule,
                     classification=NOT_APPLICABLE if schedule is None else UNRESOLVED,
                     special_case=None if schedule is None else "legacy_schedule_held_by_processor",
                     subsystem="phase7_plan_changes",
                     explanation="legacy keeps no scheduled-change record; any schedule is processor-held"
                     if schedule is None else
                     "an authoritative schedule has no legacy record to compare; verify with the processor"))
    return rows


def _seats(session, ctx, projection):
    legacy = legacy_seat_usage(session, ctx["organization"], at=ctx["at"])
    rows = [_equal_or("seats", "paid_seat_occupancy", legacy["total_paid_used"], projection["seats"]["occupancy"],
                      subject=ctx["organization_id"], ctx=ctx, subsystem="phase8_seats",
                      legacy_evidence=legacy,
                      authoritative_evidence={"rule": "active members in paid roles"})]
    commitment = projection["seats"]["commitment"]
    limit = legacy["total_paid_limit"]
    if commitment is None and limit is None:
        rows.append(_row("seats", "seat_commitment", subject=ctx["organization_id"], ctx=ctx, legacy=None,
                         authoritative=None, classification=NOT_APPLICABLE, subsystem="phase8_seats",
                         explanation="no seat limit on either side"))
    elif commitment is None:
        rows.append(_row("seats", "seat_commitment", subject=ctx["organization_id"], ctx=ctx, legacy=limit,
                         authoritative=None, classification=UNRESOLVED, special_case="seat_commitment_not_opened",
                         subsystem="phase8_seats",
                         explanation="paid seats need the processor subscription (unresolved in the plan mapping)"))
    else:
        rows.append(_equal_or("seats", "seat_commitment", limit, commitment, subject=ctx["organization_id"],
                              ctx=ctx, subsystem="phase8_seats"))
    return rows


def _reservations(session, ctx, in_flight, projection):
    rows = []
    for op, label, owned, basis in in_flight:
        if not owned:
            rows.append(_row(
                "reservations_and_holds", "legacy_in_flight_operation", subject=op.id, ctx=ctx, operation_id=op.id,
                legacy=None, authoritative=None, classification=UNRESOLVED, special_case="operation_owner_unresolved",
                subsystem="ai_operations", legacy_evidence={"status": op.status, "owner_basis": basis},
                explanation="an in-flight operation of a related user whose owning organization no evidence "
                            "proves; it blocks every related organization and is counted in none"))
            continue
        rows.append(_row(
            "reservations_and_holds", "legacy_in_flight_operation", subject=op.id, ctx=ctx, operation_id=op.id,
            legacy=int(op.projected_credits or 0), authoritative=None, classification=UNRESOLVED,
            special_case="stale_operation_not_released" if label in STALE_LABELS else "in_flight_operation",
            subsystem="ai_operations",
            legacy_evidence={"status": op.status, "classification": label, "created_at": _iso(op.created_at)},
            explanation="a stale classification is evidence, never authority to release credits; the meter debit "
                        "is unrecorded, so no hold is inferred (D16)"))
    ops = session.execute(select(AIBillingOperation).where(
        AIBillingOperation.billing_account_id == ctx["account_id"]).order_by(AIBillingOperation.operation_id)).scalars()
    for op in ops:
        held = int(session.execute(select(func.coalesce(func.sum(CreditLedgerEntry.held_delta), 0)).where(
            CreditLedgerEntry.operation_id == op.operation_id)).scalar_one())
        legacy_op = session.get(AIOperation, op.operation_id)
        authoritative_state = "open" if op.state == "authorized" else "closed"
        legacy_state = "open" if legacy_op.status == "started" else "closed"
        kwargs = dict(subject=op.operation_id, ctx=ctx, operation_id=op.operation_id, subsystem="phase12_ai_billing",
                      legacy_evidence={"status": legacy_op.status},
                      authoritative_evidence={"state": op.state, "held": held})
        if op.state != "authorized" and held != 0:
            rows.append(_row("reservations_and_holds", "operation_hold_state", legacy=legacy_state,
                             authoritative=authoritative_state, classification=MISMATCH, difference=GENUINE,
                             explanation="a closed reservation still holds credits in the ledger", **kwargs))
        else:
            rows.append(_equal_or("reservations_and_holds", "operation_hold_state", legacy_state,
                                  authoritative_state, **kwargs))
    held = dict(session.execute(
        select(CreditLedgerEntry.reservation_id.is_not(None), func.coalesce(func.sum(CreditLedgerEntry.held_delta), 0))
        .where(CreditLedgerEntry.billing_account_id == ctx["account_id"])
        .group_by(CreditLedgerEntry.reservation_id.is_not(None))).all())
    reservation_holds, other_holds = int(held.get(True, 0)), int(held.get(False, 0))
    rows.append(_equal_or(
        "reservations_and_holds", "account_held_total", reservation_holds + other_holds,
        projection["credits"]["held"], subject=ctx["account_id"], ctx=ctx, subsystem="phase3_ledger",
        legacy_evidence={"basis": "raw entries: reservation holds plus dispute and other holds",
                         "reservation_holds": reservation_holds, "dispute_and_other_holds": other_holds},
        authoritative_evidence={"basis": "Phase 13 projection"},
        explanation="authoritative self-check: legacy keeps no hold record"))
    return rows


def _ai_usage(session, ctx, plan):
    rows = []
    members = [u.id for u in ctx["members"]]
    events = defaultdict(list)
    if members:
        for event in session.execute(select(UsageEvent).where(or_(
                UsageEvent.user_id.in_(members), UsageEvent.organization_id == ctx["organization_id"]))
                .order_by(UsageEvent.id)).scalars():
            operation_id = (event.metadata_json or {}).get("operation_id") if isinstance(event.metadata_json, dict) \
                else None
            if operation_id:
                events[operation_id].append(event)
    ops = session.execute(select(AIBillingOperation).where(
        AIBillingOperation.billing_account_id == ctx["account_id"]).order_by(AIBillingOperation.operation_id)).scalars()
    for op in ops:
        legacy_op = session.get(AIOperation, op.operation_id)
        settled = int(session.execute(select(func.coalesce(func.sum(-CreditLedgerEntry.held_delta), 0)).where(
            CreditLedgerEntry.operation_id == op.operation_id, CreditLedgerEntry.entry_type == "settlement")
        ).scalar_one())
        legacy_charge = int(legacy_op.charged_credits or 0)
        kwargs = dict(subject=op.operation_id, ctx=ctx, operation_id=op.operation_id, subsystem="phase12_ai_billing",
                      legacy_evidence={"status": legacy_op.status, "operation_type": legacy_op.operation_type},
                      authoritative_evidence={"state": op.state, "delivery_status": op.delivery_status,
                                              "recorded_charge": op.charged_credits,
                                              "absorbed_credits": op.absorbed_credits})
        if op.state in ("finalized", "expired") and int(op.charged_credits or 0) != settled:
            rows.append(_row("ai_usage", "billable_outcome", legacy=legacy_charge, authoritative=settled,
                             classification=MISMATCH, difference=GENUINE,
                             explanation="the operation's recorded charge differs from its settlements", **kwargs))
        elif legacy_charge == settled:
            rows.append(_row("ai_usage", "billable_outcome", legacy=legacy_charge, authoritative=settled,
                             classification=MATCH, **kwargs))
        elif op.state == "authorized":
            rows.append(_row("ai_usage", "billable_outcome", legacy=legacy_charge, authoritative=settled,
                             classification=UNRESOLVED, special_case="operation_not_final", **kwargs))
        elif op.delivery_status != "delivered" and settled == 0 and legacy_charge > 0:
            rows.append(_row("ai_usage", "billable_outcome", legacy=legacy_charge, authoritative=settled,
                             classification=MISMATCH, difference=POLICY, policy="delivered_only_billing", **kwargs))
        else:
            rows.append(_row("ai_usage", "billable_outcome", legacy=legacy_charge, authoritative=settled,
                             classification=MISMATCH, difference=GENUINE, **kwargs))
        # Actual-user attribution (P4.1 D2): the acting member, never the project owner.
        rows.append(_equal_or("ai_usage", "acting_user_attribution", legacy_op.user_id, op.actor_user_id, **kwargs))
        for event in events.get(op.operation_id, ()):
            rows.append(_equal_or("ai_usage", "usage_event_attribution", event.user_id, op.actor_user_id,
                                  subject=f"usage_event:{event.id}", ctx=ctx, operation_id=op.operation_id,
                                  subsystem="usage_telemetry",
                                  explanation="UsageEvent is analytics only; it must still name the actor"))
    history = plan["legacy_usage_history"]
    if history:
        rows.append(_row("ai_usage", "legacy_usage_history", subject=ctx["account_id"], ctx=ctx,
                         legacy={uid: history[uid] for uid in sorted(history)}, authoritative=None,
                         classification=NOT_APPLICABLE, subsystem="ai_operations",
                         explanation="unbound legacy usage before the snapshot is reported, never re-ledgered (D16)"))
    return rows


def _financial_cases(session, ctx, plan):
    rows = []
    # Legacy reversals (refunds and chargebacks) of migrated grants: nothing opened for reversed value.
    for source in plan["sources"]:
        if source["kind"] != "persistent_credit_grant":
            continue
        grant = source["grant"]
        reversals = session.execute(select(PersistentCreditTransaction).where(
            PersistentCreditTransaction.grant_id == grant["grant_id"],
            PersistentCreditTransaction.transaction_type == "reversal")
            .order_by(PersistentCreditTransaction.created_at, PersistentCreditTransaction.id)).scalars().all()
        if not reversals:
            continue
        reasons = sorted({(r.transaction_metadata or {}).get("reason") for r in reversals} - {None})
        reversed_amount = -sum(int(r.amount) for r in reversals)
        kwargs = dict(subject=grant["grant_id"], ctx=ctx, subsystem="phase9_financial_effects",
                      legacy_evidence={"reasons": reasons, "reversed_amount": reversed_amount},
                      authoritative_evidence={"phase14_classification": source.get("classification")})
        if "stripe_chargeback" in reasons:
            rows.append(_row("financial_cases", "legacy_reversal", legacy=reversed_amount, authoritative=None,
                             classification=UNRESOLVED, special_case="legacy_dispute_state_unknown",
                             explanation="legacy reversed on chargeback creation; the dispute outcome is unknown and "
                                         "P11 holds rather than reverses", **kwargs))
        else:
            opened = session.execute(select(func.count()).select_from(BillingMigrationOpening).where(
                BillingMigrationOpening.legacy_source_kind == "persistent_credit_grant",
                BillingMigrationOpening.legacy_source_id == grant["grant_id"])).scalar_one()
            if source.get("classification") == "reversed":
                rows.append(_equal_or("financial_cases", "legacy_reversal", 0, int(opened), **kwargs,
                                      explanation="reversed legacy value is never opened"))
            else:
                rows.append(_row("financial_cases", "legacy_reversal", legacy=int(grant["remaining_amount"]),
                                 authoritative=None, classification=UNRESOLVED,
                                 special_case="reversal_with_remaining_value", **kwargs))
    # Authoritative cases: each case's ledger effects reconcile to its linked entries.
    for case in session.execute(select(FinancialCase).where(FinancialCase.billing_account_id == ctx["account_id"])
                                .order_by(FinancialCase.id)).scalars():
        linked = session.execute(
            select(CreditLedgerEntry.entry_type, func.coalesce(func.sum(CreditLedgerEntry.available_delta), 0),
                   func.coalesce(func.sum(CreditLedgerEntry.held_delta), 0))
            .join(FinancialCaseEventLedgerEntry,
                  FinancialCaseEventLedgerEntry.credit_ledger_entry_id == CreditLedgerEntry.id)
            .join(FinancialCaseEvent, FinancialCaseEvent.id == FinancialCaseEventLedgerEntry.financial_case_event_id)
            .where(FinancialCaseEvent.financial_case_id == case.id)
            .group_by(CreditLedgerEntry.entry_type)).all()
        effects = {kind: {"available": int(a), "held": int(h)} for kind, a, h in linked}
        policy = "dispute_holds_before_reversal" if case.case_type == "dispute" else "proportional_refund"
        rows.append(_row("financial_cases", f"{case.case_type}_case_effect", subject=case.id, ctx=ctx,
                         legacy=None, authoritative=effects or None, classification=NOT_APPLICABLE,
                         subsystem="phase9_financial_effects",
                         authoritative_evidence={"state": case.state, "disposition": case.disposition,
                                                 "cumulative_principal_minor": int(case.cumulative_principal_minor)},
                         explanation="legacy keeps no case record; the approved policy differs by design: "
                                     + APPROVED_POLICY_DIFFERENCES[policy]))
    # Reviewed adjustments (D16 step 7): the reviewed amount is the opened legacy_unattributed lot.
    for review in session.execute(select(BillingMigrationReview).where(
            BillingMigrationReview.billing_account_id == ctx["account_id"]).order_by(BillingMigrationReview.id)
            ).scalars():
        opening = session.execute(select(BillingMigrationOpening).where(
            BillingMigrationOpening.legacy_source_kind == "reviewed_unattributed",
            BillingMigrationOpening.legacy_source_id == review.id)).scalar_one_or_none()
        rows.append(_equal_or("financial_cases", "reviewed_adjustment", int(review.amount),
                              int(opening.opening_amount) if opening else None, subject=review.id, ctx=ctx,
                              subsystem="phase14_backfill",
                              legacy_evidence={"reviewer_user_id": review.reviewer_user_id},
                              authoritative_evidence={"lot_id": opening.lot_id if opening else None}))
    return rows


def _scoped_payments(session, scope):
    """FR-1: each candidate legacy payment's owner by evidence; only target-owned payments are in scope.

    Candidates are payments attributed or linked to a target account and
    payments of related users. A payment owned by another organization is
    left out entirely. A payment whose owner is unresolved is listed only by
    identifier (never counted in any total) for review; it blocks.
    Returns ``{"owned": {payment_id: basis}, "unresolved": {payment_id: reason}}``.
    """
    account_ids = sorted(scope["account_ids"])
    candidates = set()
    if account_ids:
        candidates |= set(session.execute(select(BillingMigrationPaymentAttribution.payment_id).where(
            BillingMigrationPaymentAttribution.billing_account_id.in_(account_ids))).scalars())
        candidates |= set(session.execute(select(Payment.id).where(Payment.billing_account_id.in_(account_ids)))
                          .scalars())
    if scope["related_user_ids"]:
        candidates |= set(session.execute(select(Payment.id).where(
            Payment.user_id.in_(sorted(scope["related_user_ids"])))).scalars())
    owned, unresolved = {}, {}
    for payment_id in sorted(candidates):
        owner, basis = payment_owner(session, session.get(Payment, payment_id), scope["cache"])
        if owner is None:
            unresolved[payment_id] = basis
        elif owner in scope["organization_ids"]:
            owned[payment_id] = basis
    return {"owned": owned, "unresolved": unresolved}


def _scoped_started_operations(session, scope):
    """FR-1: blocking unclosed operations owned by a target, or of a related user with an unresolved owner."""
    filters = []
    if scope["account_ids"]:
        filters.append(AIOperation.billing_account_id.in_(sorted(scope["account_ids"])))
    if scope["related_user_ids"]:
        filters.append(AIOperation.user_id.in_(sorted(scope["related_user_ids"])))
    owned, unresolved = {}, {}
    if filters:
        unclosed = session.execute(
            select(AIOperation).where(or_(AIOperation.status.is_(None),
                                          AIOperation.status.notin_(sorted(TERMINAL_OPERATION_STATUSES))),
                                      or_(*filters)).order_by(AIOperation.id)).scalars().all()
        # BI-1: only operations that still block Phase 14 (in flight, unrecognized, or awaiting or failing
        # a decision) count as not drained.
        blocking = {b["operation_id"] for b in blocking_legacy_operations(
            session, unclosed, scope.get("at") or _database_clock(session))}
        for op in (o for o in unclosed if o.id in blocking):
            owner, basis = operation_owner(session, op, scope["cache"])
            if owner is None:
                unresolved[op.id] = basis
            elif owner in scope["organization_ids"]:
                owned[op.id] = basis
    return {"owned": owned, "unresolved": unresolved}


def _financial_attribution(session, archive_plan, attestation, scope):
    """Target payments against their archive and attribution; revenue with founder tests apart (N2 scoped)."""
    rows = []
    in_scope = set(scope["payments"]["owned"])
    for payment_id, reason in sorted(scope["payments"]["unresolved"].items()):
        # FR-1: identifier and reason only; no amount, and never counted in any total.
        rows.append(_row("financial_attribution", "payment_owner", subject=payment_id, legacy=None,
                         authoritative=None, classification=UNRESOLVED, special_case="payment_owner_unresolved",
                         subsystem="phase14_payment_attribution", legacy_evidence={"reason": reason},
                         explanation="no Phase 14-15 evidence proves which organization owns this payment; "
                                     "membership is never ownership"))
    attributions = {a.payment_id: a.billing_account_id for a in session.execute(
        select(BillingMigrationPaymentAttribution)).scalars() if a.payment_id in in_scope}
    for item in archive_plan["payments"]:
        if item["payment_id"] not in in_scope:
            continue
        payment = session.get(Payment, item["payment_id"])
        kwargs = dict(subject=item["payment_id"], subsystem="phase14_payment_archive",
                      legacy_evidence={"source": payment.source, "currency": (payment.currency or "").lower(),
                                       "user_id": payment.user_id,
                                       "owner_basis": scope["payments"]["owned"][item["payment_id"]]},
                      authoritative_evidence={"archive_state": item["state"],
                                              "attributed_billing_account_id": attributions.get(payment.id)})
        if item["state"] == "new":
            rows.append(_row("financial_attribution", "payment_archived", legacy=int(payment.amount_paid_cents),
                             authoritative=None, classification=UNRESOLVED, special_case="payment_not_archived",
                             **kwargs))
            continue
        rows.append(_row("financial_attribution", "payment_archived", legacy=int(payment.amount_paid_cents),
                         authoritative=int(payment.amount_paid_cents) if item["state"] == "unchanged" else None,
                         classification=MATCH if item["state"] == "unchanged" else MISMATCH,
                         difference=None if item["state"] == "unchanged" else SINCE_SNAPSHOT,
                         explanation="the archive is an exact copy; a changed row is never rewritten", **kwargs))
        if attestation is not None:
            rows.append(_equal_or("financial_attribution", "test_activity_classification", item["classification"],
                                  item["archived_classification"], subject=item["payment_id"],
                                  subsystem="phase14_payment_archive",
                                  explanation="the attestation's classification against the archived one"))
    if attestation is None:
        attested = sum(1 for item in archive_plan["payments"] if item["payment_id"] in in_scope
                       and item.get("archived_classification") == "test_activity")
        rows.append(_row("financial_attribution", "test_activity_attestation", subject="attestation", legacy=None,
                         authoritative=attested, classification=UNRESOLVED if attested else NOT_APPLICABLE,
                         special_case="attestation_not_supplied" if attested else None,
                         subsystem="phase14_payment_archive",
                         explanation="archived test activity cannot be re-verified without the attestation (N4)"
                         if attested else "no attestation and no archived test activity"))
    totals = defaultdict(lambda: {"legacy": 0, "founder_test": 0, "unverified": 0})
    archived = {a.payment_id: a for a in session.execute(select(BillingMigrationPaymentArchive)).scalars()
                if a.payment_id in in_scope}
    for payment in session.execute(select(Payment).where(Payment.id.in_(sorted(in_scope)))
                                   .order_by(Payment.id)).scalars():
        currency = (payment.currency or "").lower()
        totals[currency]["legacy"] += int(payment.amount_paid_cents or 0)
        row = archived.get(payment.id)
        if row is not None:
            key = "founder_test" if row.classification == "test_activity" else "unverified"
            totals[currency][key] += int(row.amount_paid_cents)
    for currency, total in sorted(totals.items()):
        rows.append(_equal_or("financial_attribution", "paid_amount_by_currency", total["legacy"],
                              total["founder_test"] + total["unverified"], subject=currency,
                              subsystem="phase15_founder_test_separation",
                              authoritative_evidence={"excluded_founder_test": total["founder_test"],
                                                      "unverified_not_revenue": total["unverified"],
                                                      "verified_customer_revenue": 0},
                              otherwise=SINCE_SNAPSHOT,
                              explanation="every legacy cent is founder test or unverified; genuine customer "
                                          "revenue needs a verified processor payment (0)"))
    return rows


def _policy_versions(session, at, scope):
    """The pricing version in force, and per target operation its bound versions, independently resolved (N2)."""
    rows = []
    legacy_rate = int(CREDITS_PER_PROVIDER_DOLLAR * INTERNAL_UNITS_PER_CREDIT)
    findings = pricing_unit_findings(session)
    in_force = _version_effective_at(session, PricingPolicyVersion, at)
    if len(in_force) != 1:
        rows.append(_row("policy_versions", "pricing_conversion", subject="pricing", legacy=legacy_rate,
                         authoritative=None, classification=UNRESOLVED,
                         special_case="no_single_pricing_version_in_force", subsystem="phase2_pricing",
                         authoritative_evidence={"versions_in_force": [v.id for v in in_force]}))
    else:
        raw = (in_force[0].conversion_json or {}).get(CONVERSION_KEY)
        try:
            rate = int(str(raw))
        except (TypeError, ValueError):
            rate = raw
        rows.append(_equal_or("policy_versions", "pricing_conversion", legacy_rate, rate, subject="pricing",
                              subsystem="phase2_pricing",
                              legacy_evidence={"credits_per_provider_dollar": CREDITS_PER_PROVIDER_DOLLAR,
                                               "internal_units_per_credit": INTERNAL_UNITS_PER_CREDIT},
                              authoritative_evidence={"version_id": in_force[0].id, "version": in_force[0].version,
                                                      "unit_findings": findings}))
    for op in session.execute(select(AIBillingOperation).where(
            AIBillingOperation.billing_account_id.in_(sorted(scope["account_ids"])))
            .order_by(AIBillingOperation.operation_id)).scalars():
        at_op = _utc(op.authorized_at)
        for model, bound, name in ((PricingPolicyVersion, op.pricing_policy_version_id, "pricing"),
                                   (CapacityPolicyVersion, op.capacity_policy_version_id, "capacity")):
            versions = _version_effective_at(session, model, at_op)
            expected = versions[0].id if len(versions) == 1 else None
            kwargs = dict(subject=op.operation_id, operation_id=op.operation_id, subsystem="phase12_ai_billing",
                          period=_iso(at_op), legacy_evidence={"basis": f"{name} version in force at authorization"},
                          authoritative_evidence={"bound_version_id": bound})
            if expected is None:
                rows.append(_row("policy_versions", f"{name}_version_binding", legacy=None, authoritative=bound,
                                 classification=UNRESOLVED, special_case=f"no_single_{name}_version_in_force",
                                 **kwargs))
            else:
                rows.append(_equal_or("policy_versions", f"{name}_version_binding", expected, bound, **kwargs))
        legacy_op = session.get(AIOperation, op.operation_id)
        if legacy_op.pricing_policy_version_id is not None:
            rows.append(_equal_or("policy_versions", "operation_audit_pricing_version",
                                  legacy_op.pricing_policy_version_id, op.pricing_policy_version_id,
                                  subject=op.operation_id, operation_id=op.operation_id,
                                  subsystem="phase12_ai_billing"))
    return rows


def _ledger_integrity(session, ctx, projection):
    movements = ledger_movements(session, ctx["account_id"])
    lots = _lot_balances(session, ctx["account_id"])
    return [
        _equal_or("ledger_integrity", "available_and_held_from_raw_entries",
                  movements["available_total"] + movements["held_total"], sum(a + h for _lot, a, h in lots),
                  subject=ctx["account_id"], ctx=ctx, subsystem="phase3_ledger",
                  legacy_evidence={"basis": "sum of every raw entry"},
                  authoritative_evidence={"basis": "per-lot validated balances (Phase 13)"}),
        _row("ledger_integrity", "ledger_movements", subject=ctx["account_id"], ctx=ctx, legacy=None,
             authoritative={k: v for k, v in movements.items() if k != "by_entry_type"},
             classification=NOT_APPLICABLE, subsystem="phase3_ledger",
             authoritative_evidence=movements["by_entry_type"],
             explanation="L1: settled, expired, and reversed come from the ledger entries; legacy has no ledger"),
    ]


_D16_TO_SHADOW = {PROJECTION_DUPLICATION, STALE_COUNTER, EVIDENCE_BACKED_ADJUSTMENT}


def _stored_fields(session, ctx, plan):
    """The accepted Phase 13 field comparison, re-expressed in the shadow classes (stored legacy values)."""
    report = compare_legacy_compatibility(session, billing_account_id=ctx["account_id"], at=ctx["at"],
                                          value_owners=plan["owners"],
                                          zero_cycles={tuple(z) for z in plan["zero_cycles"]})
    rows = []
    for item in report["comparisons"]:
        d16 = item["classification"]
        assert d16 in D16_CLASSES
        kwargs = dict(subject=item["subject"], ctx=ctx, subsystem="phase13_projection", d16_class=d16,
                      special_case=item["special_case"], explanation=item["detail"])
        if d16 == D16_MATCH:
            rows.append(_row("migration_evidence", f"stored:{item['field']}", legacy=item["legacy"],
                             authoritative=item["projected"], classification=MATCH, **kwargs))
        elif d16 in _D16_TO_SHADOW:
            rows.append(_row("migration_evidence", f"stored:{item['field']}", legacy=item["legacy"],
                             authoritative=item["projected"], classification=MISMATCH, difference=D16_EXPLAINED,
                             blocks_cutover=False, **kwargs))
        else:
            assert d16 == D16_UNRESOLVED
            rows.append(_row("migration_evidence", f"stored:{item['field']}", legacy=item["legacy"],
                             authoritative=item["projected"], classification=UNRESOLVED, **kwargs))
    for flag in report["flags"]:
        rows.append(_row("migration_evidence", f"flag:{flag['code']}", subject=ctx["account_id"], ctx=ctx,
                         legacy=None, authoritative=flag["count"], classification=UNRESOLVED,
                         special_case=flag["code"], subsystem="phase13_projection", explanation=flag["detail"]))
    return rows


# ---------------------------------------------------------------------------
# Public: one account, the whole comparison, the read-only run
# ---------------------------------------------------------------------------

def shadow_compare_account(session, *, billing_account_id, at, operation_classifier=None, separation=None,
                           ownership_cache=None):
    """Every shadow comparison of one organization billing account at ``at`` (pure read)."""
    with session.no_autoflush:
        account = session.get(BillingAccount, billing_account_id)
        if account is None:
            raise ShadowError("billing account does not exist")
        at = _utc(at)
        ctx = _context(session, account, at)
        try:
            plan = plan_account_backfill(session, billing_account_id=account.id, at=at)
            projection = project_billing_account(session, billing_account_id=account.id, at=at)
        except (ProjectionError, MigrationError) as exc:
            row = _row("ledger_integrity", "projection", subject=account.id, ctx=ctx, legacy=None, authoritative=None,
                       classification=UNRESOLVED, special_case="projection_invariant_violation",
                       subsystem="phase13_projection", explanation=str(exc))
            return _account_report(ctx, [row], owned=(), unresolved=(), related={u.id for u in ctx["members"]})
        if separation is None:
            separation = founder_test_credit_separation(session)
        rows = _migration_evidence(session, ctx, plan)
        changed = _changed_holders(rows)
        cache = ownership_cache if ownership_cache is not None else {}
        # FR-1: users related to this organization by evidence or membership. Relation only lists evidence the
        # organization cannot clear (unresolved owners); it never makes a record this organization's.
        related = set(plan["evidence"]["candidates"]) | {u.id for u in ctx["members"]}
        in_flight = _in_flight(session, ctx, related, operation_classifier, at, cache)
        rows += _stored_fields(session, ctx, plan)
        rows += _balances(session, ctx, plan, changed, in_flight, plan["owners"])
        rows += _funding(session, ctx, plan, changed, separation)
        rows += _credit_periods(session, ctx, plan, projection)
        rows += _plan_and_schedule(session, ctx, projection, plan["owners"])
        rows += _seats(session, ctx, projection)
        rows += _reservations(session, ctx, in_flight, projection)
        rows += _ai_usage(session, ctx, plan)
        rows += _financial_cases(session, ctx, plan)
        rows += _ledger_integrity(session, ctx, projection)
        return _account_report(ctx, rows, owned=plan["holders"],
                               unresolved=[u for u, owner in plan["owners"].items() if owner is None],
                               related=related)


def _sort_key(row):
    return (DOMAINS.index(row["domain"]), row["comparison"], str(row["subject"]), str(row["period"]))


def _summary(rows):
    by_class = Counter(r["classification"] for r in rows)
    by_difference = Counter(r["difference"] for r in rows if r["difference"])
    by_domain = defaultdict(Counter)
    variance = defaultdict(int)
    for r in rows:
        by_domain[r["domain"]][r["classification"]] += 1
        if r["variance"] is not None and r["classification"] == MISMATCH:
            variance[r["domain"]] += r["variance"]
    return {
        "by_classification": {key: by_class[key] for key in CLASSIFICATIONS},
        "by_difference": {key: by_difference[key] for key in DIFFERENCES},
        "by_domain": {d: {k: by_domain[d][k] for k in CLASSIFICATIONS} for d in DOMAINS if d in by_domain},
        "mismatch_variance_by_domain": dict(sorted(variance.items())),
    }


def _account_report(ctx, rows, *, owned, unresolved, related):
    rows = sorted(rows, key=_sort_key)
    blocking = sorted({f"{r['domain']}:{r['comparison']}:{r['special_case'] or r['difference'] or r['classification']}"
                       for r in rows if r["blocks_cutover"]})
    return {"billing_account_id": ctx["account_id"], "organization_id": ctx["organization_id"],
            "migration": ctx["migration_ref"], "comparisons": rows, "summary": _summary(rows),
            "blocked": bool(blocking), "blocking_reasons": blocking,
            # FR-1: holders whose personal value Phase 14 evidence assigns to this organization; holders whose
            # owner is unresolved; and every related user (evidence or membership), used only to list unresolved
            # records. Membership alone never makes a record this organization's.
            "owned_holder_ids": sorted(u for u in owned if u),
            "owner_unresolved_user_ids": sorted(u for u in unresolved if u),
            "related_user_ids": sorted(u for u in related if u)}


def shadow_reconciliation(session, *, organization_ids, at, test_activity_attestation, operation_classifier=None):
    """The whole shadow comparison over explicit target organizations (pure read; N4: attestation required).

    ``test_activity_attestation`` must be passed explicitly (``None`` states
    that no attestation exists, which leaves every payment unverified).
    """
    if isinstance(organization_ids, str) or not organization_ids:
        raise ShadowError("name the explicit target organizations")
    targets = sorted(set(organization_ids))
    at = _utc(at)
    with session.no_autoflush:
        separation = founder_test_credit_separation(session)
        cache = {}
        accounts, missing = [], []
        for organization_id in targets:
            account = session.execute(select(BillingAccount).where(
                BillingAccount.organization_id == organization_id)).scalar_one_or_none()
            if account is None:
                missing.append(_row("migration_evidence", "billing_account_established", subject=organization_id,
                                    legacy=organization_id, authoritative=None, classification=UNRESOLVED,
                                    special_case="billing_account_not_established", subsystem="phase14_backfill"))
                continue
            accounts.append(shadow_compare_account(session, billing_account_id=account.id, at=at,
                                                   operation_classifier=operation_classifier,
                                                   separation=separation, ownership_cache=cache))
        scope = {"organization_ids": set(targets), "account_ids": {a["billing_account_id"] for a in accounts},
                 "owned_holder_ids": {u for a in accounts for u in a["owned_holder_ids"]},
                 "owner_unresolved_user_ids": {u for a in accounts for u in a["owner_unresolved_user_ids"]},
                 "related_user_ids": {u for a in accounts for u in a["related_user_ids"]},
                 "cache": cache, "at": at}
        scope["payments"] = _scoped_payments(session, scope)
        scope["operations"] = _scoped_started_operations(session, scope)
        archive_plan = plan_payment_archive(session, test_activity_attestation=test_activity_attestation)
        global_rows = sorted(missing + _financial_attribution(session, archive_plan, test_activity_attestation, scope)
                             + _policy_versions(session, at, scope), key=_sort_key)
        every = [r for a in accounts for r in a["comparisons"]] + global_rows
        gates = phase17_gates(session, accounts, global_rows, at, scope)
        body = {
            "shadow_version": SHADOW_VERSION, "as_of": _iso(at), "target_organizations": targets,
            "attestation_fingerprint": _fingerprint(test_activity_attestation),
            "operation_classifier": getattr(operation_classifier, "__name__", None) if operation_classifier
            else "phase14_legacy_operation_status",
            "legacy_fingerprint": legacy_fingerprint(session)["fingerprint"],
            "accounts": accounts, "global_comparisons": global_rows, "summary": _summary(every),
            "founder_test_separation": _scoped_separation(session, separation, scope),
            "historical_value_by_state": _scoped_historical_value_by_state(session, at, scope),
            "population_counts": _population_counts(session, scope),
            "phase17_gates": gates,
            # Review N1: ready only when every gate passes; an open or failed gate, local or global, is never ready.
            "cutover_ready": all(g["status"] in GATE_READY_STATUSES for g in gates),
            "accounts_blocked": sorted(a["billing_account_id"] for a in accounts if a["blocked"]),
        }
        body["report_fingerprint"] = _fingerprint(body)
        return body


def phase17_gates(session, accounts, global_rows, at, scope):
    """Cutover gates this evidence settles for the targets, and the ones it cannot (pure)."""
    rows = [r for a in accounts for r in a["comparisons"]] + global_rows
    definitions = session.execute(select(func.count()).select_from(EntitlementDefinition).where(
        EntitlementDefinition.approved_at.is_not(None))).scalar_one()
    account_ids = sorted(scope["account_ids"])
    pending_processor = session.execute(select(func.count()).select_from(BillingMigrationPlanMapping).where(
        BillingMigrationPlanMapping.outcome == "mapped_pending_processor",
        BillingMigrationPlanMapping.billing_account_id.in_(account_ids))).scalar_one()
    # FR-1: operations owned by a target, plus related operations whose owner is unresolved (which block).
    started = len(scope["operations"]["owned"]) + len(scope["operations"]["unresolved"])
    drift = [r["subject"] for r in rows if r["difference"] == SINCE_SNAPSHOT]
    genuine = [r["subject"] for r in rows if r["difference"] == GENUINE]
    # Review N1: a blocking comparison outside any account (attestation, pricing, payments, missing accounts).
    global_blocking = sorted({f"{r['comparison']}:{r['special_case'] or r['difference'] or r['classification']}"
                              for r in global_rows if r["blocks_cutover"]})
    financial = session.execute(select(func.count()).select_from(FinancialTransaction).where(
        FinancialTransaction.billing_account_id.in_(account_ids))).scalar_one()

    def gate(code, status, detail):
        return {"gate": code, "status": status, "detail": detail}

    return [
        gate("no_genuine_discrepancy", "pass" if not genuine else "fail", {"subjects": sorted(set(genuine))}),
        gate("writer_freeze_proven", "pass" if not drift else "fail",
             {"subjects_changed_since_snapshot": sorted(set(drift))}),
        gate("blocked_accounts", "pass" if not any(a["blocked"] for a in accounts) else "fail",
             {"accounts": sorted(a["billing_account_id"] for a in accounts if a["blocked"])}),
        gate("global_comparisons_resolved", "pass" if not global_blocking else "fail",
             {"blocking": global_blocking}),
        gate("in_flight_operations_drained", "pass" if not started else "fail",
             {"started_operations": int(started), "owner_unresolved": len(scope["operations"]["unresolved"])}),
        gate("approved_entitlement_definitions", "pass" if definitions else "open",
             {"approved_definitions": int(definitions)}),
        gate("processor_verification", "pass" if not pending_processor else "open",
             {"mapped_pending_processor_accounts": int(pending_processor), "needs": "separately authorized read"}),
        gate("phase52_financial_transactions_for_migrated_value", "reported", {"financial_transactions": int(financial)}),
        gate("pre_unit_boundary_rule", "open", "a founder rule for live pre-2026-05-08 value (F4 report)"),
        gate("p4_0_writer_inventory", "open", "P4.0 AI-operation writers join the Phase 13 inventory at integration"),
        gate("f2_f4_charging", "open", "OD-1 option C: F2-F4 fixes are Phase 17 / P4.2 acceptance requirements"),
        gate("phase12_reliable_delivery", "open", "Phase 17 reliable delivery is a mandatory activation gate"),
        gate("restore_copy_roles", "open", "migration-only and runtime roles on a restore copy (founder approval)"),
    ]


# Gate statuses compatible with cutover readiness ("reported" is evidence only, never a blocker).
GATE_READY_STATUSES = ("pass", "reported")


def _scoped_separation(session, separation, scope):
    """Phase 15 founder-test separation totals for the target accounts and their payments only (N2; pure).

    The same buckets and rules as ``founder_test_credit_separation``, applied
    to its lots for the target accounts and to the archives of in-scope
    payments; no other organization's lot or payment contributes.
    """
    lots = [lot for lot in separation["lots"] if lot["billing_account_id"] in scope["account_ids"]]

    def bucket(predicate):
        chosen = [lot for lot in lots if predicate(lot)]
        return {"lots": len(chosen), "opening_units": sum(lot["opening_amount"] for lot in chosen),
                "current_units": sum(lot["current_balance"] or 0 for lot in chosen)}

    purchased = lambda lot: lot["lot_source_type"] in PURCHASED_LOT_SOURCES
    in_scope = set(scope["payments"]["owned"])
    revenue = defaultdict(lambda: defaultdict(int))
    for row in session.execute(select(BillingMigrationPaymentArchive).where(
            BillingMigrationPaymentArchive.payment_id.in_(sorted(in_scope)))).scalars():
        key = "excluded_founder_test" if row.classification == "test_activity" else "unverified_not_revenue"
        revenue[key][(row.currency or "").lower()] += int(row.amount_paid_cents)
    return {
        "policy": separation["policy"], "scope": "target_organizations",
        "purchased_credit": {
            "genuine_customer": {"lots": 0, "opening_units": 0, "current_units": 0},
            "excluded_founder_test": bucket(lambda lot: purchased(lot) and lot["funding"] == "founder_test"),
            "unverified": bucket(lambda lot: purchased(lot) and lot["funding"] in
                                 ("unverified", "unarchived", "unmapped", "no_payment_evidence")),
        },
        "promotional": bucket(lambda lot: lot["lot_source_type"] == "promotional"),
        "promotional_funded_by_founder_test": bucket(
            lambda lot: lot["lot_source_type"] == "promotional" and lot["funding"] == "founder_test"),
        "customer_revenue": {
            "verified_customer_cents_by_currency": {},
            "excluded_founder_test_cents_by_currency": dict(sorted(revenue["excluded_founder_test"].items())),
            "unverified_not_revenue_cents_by_currency": dict(sorted(revenue["unverified_not_revenue"].items())),
        },
        "balances_and_classifications_changed": False,
    }


def _scoped_historical_value_by_state(session, at, scope):
    """Phase 15 ``historical_value_by_state`` restricted to the target holders and organizations (N2; pure).

    The same rule, unchanged: a pre-boundary meter is live until one calendar
    month after its reset, a pre-boundary grant is live, and a counter
    without a meter or a grant without a date is undetermined. Only the
    target accounts' holders, members, and organizations are counted.
    """
    empty = lambda: {state: {"holders": 0, "amount": 0} for state in ("expired", "live", "undetermined")}
    out = {key: empty() for key in ("legacy_meter_absent", "pre_unit_boundary_meter",
                                    "pre_unit_boundary_organization_meter", "pre_unit_boundary_grant",
                                    "grant_date_missing")}

    def add(key, state, amount):
        out[key][state]["holders"] += 1
        out[key][state]["amount"] += amount

    def meter_state(meter):
        reset = _parsed(meter.get("cycle_reset_at")) if meter else None
        remaining = _int_or_none(meter.get("remaining")) if meter else None
        if reset is None or reset >= UNIT_BOUNDARY_AT or not remaining:
            return None, 0
        return ("expired" if add_calendar_months(reset, 1) <= at else "live"), remaining

    # FR-1: only holders whose personal value Phase 14 assigns to a target; unresolved owners are counted apart.
    user_ids = sorted(scope["owned_holder_ids"])
    with session.no_autoflush:
        for user in session.execute(select(User).where(User.id.in_(user_ids)).order_by(User.id)).scalars():
            meter = _meter(user.ui_preferences)
            persistent = session.execute(
                select(func.coalesce(func.sum(PersistentCreditGrant.remaining_amount), 0)).where(
                    PersistentCreditGrant.user_id == user.id, PersistentCreditGrant.status == "active")
            ).scalar_one()
            unexplained = int(user.credits_remaining or 0) - int(persistent)
            if meter is None and unexplained != 0:
                add("legacy_meter_absent", "undetermined", unexplained)
            state, amount = meter_state(meter)
            if state:
                add("pre_unit_boundary_meter", state, amount)
        for organization in session.execute(select(Organization).where(
                Organization.id.in_(sorted(scope["organization_ids"]))).order_by(Organization.id)).scalars():
            state, amount = meter_state(_meter(organization.settings))
            if state:
                add("pre_unit_boundary_organization_meter", state, amount)
        for grant in session.execute(select(PersistentCreditGrant).where(
                PersistentCreditGrant.user_id.in_(user_ids), PersistentCreditGrant.status == "active",
                PersistentCreditGrant.remaining_amount > 0).order_by(PersistentCreditGrant.id)).scalars():
            granted_at = _utc(grant.granted_at)
            if granted_at is None:
                add("grant_date_missing", "undetermined", int(grant.remaining_amount))
            elif granted_at < UNIT_BOUNDARY_AT:
                add("pre_unit_boundary_grant", "live", int(grant.remaining_amount))
    return {"as_of": _iso(at), "unit_boundary_at": UNIT_BOUNDARY_AT.isoformat(), "scope": "target_organizations",
            "by_state": out, "owner_unresolved_holders": len(scope["owner_unresolved_user_ids"]),
            "rule": "nothing here is opened, converted, or discarded; live value waits for a founder rule"}


def _population_counts(session, scope):
    """Aggregate counts only (N2): how much of the population the targets cover, never another tenant's rows."""
    def count(model, *where):
        return int(session.execute(select(func.count()).select_from(model).where(*where)).scalar_one())

    account_ids = sorted(scope["account_ids"])
    return {
        "payments": {"population": count(Payment), "in_scope": len(scope["payments"]["owned"]),
                     "owner_unresolved": len(scope["payments"]["unresolved"])},
        "billing_accounts": {"population": count(BillingAccount), "in_scope": len(account_ids)},
        "ai_billing_operations": {"population": count(AIBillingOperation),
                                  "in_scope": count(AIBillingOperation,
                                                    AIBillingOperation.billing_account_id.in_(account_ids))},
        "started_ai_operations": {"population": count(AIOperation, or_(
                                      AIOperation.status.is_(None),
                                      AIOperation.status.notin_(sorted(TERMINAL_OPERATION_STATUSES)))),
                                  "in_scope": len(scope["operations"]["owned"]),
                                  "owner_unresolved": len(scope["operations"]["unresolved"])},
    }


# ---------------------------------------------------------------------------
# Read-only execution
# ---------------------------------------------------------------------------

def shadow_census(session):
    """Row counts of every billing and legacy table a comparison reads (I2; pure)."""
    with session.no_autoflush:
        return {name: int(session.execute(select(func.count()).select_from(db.metadata.tables[name])).scalar_one())
                for name in SHADOW_CENSUS_TABLES if name in db.metadata.tables}


def _guard_environment(connection, environment):
    """The Phase 15 rule (audit C1) on the shadow's own connection: the runtime and the database decide.

    No shadow runs in a production runtime; ``fixtures`` runs only on a
    verified local test database (``billing_rehearsal.is_local_test_database``).
    """
    url = connection.engine.url
    dialect = connection.dialect.name
    server = connection.exec_driver_sql("SELECT current_database()").scalar() if dialect == "postgresql" else None
    facts = {"dialect": dialect, "host": url.host, "database": url.database, "server_database": server,
             "production_runtime": _phase15.is_production_runtime()}
    facts["local_test_database"] = _phase15.is_local_test_database(
        dialect=dialect, host=url.host, url_database=url.database, server_database=server)
    if facts["production_runtime"]:
        raise RehearsalError("a shadow comparison never runs in a production runtime (is_production_runtime)")
    if environment == "fixtures" and not facts["local_test_database"]:
        raise RehearsalError("fixture shadow comparisons run only on a verified local test database; "
                             "any other database needs the restore_copy controls")
    return facts


def _read_only(connection):
    dialect = connection.dialect.name
    if dialect == "postgresql":
        connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        enforced = connection.exec_driver_sql("SHOW transaction_read_only").scalar() == "on"
    elif dialect == "sqlite":
        connection.exec_driver_sql("PRAGMA query_only = ON")
        enforced = connection.exec_driver_sql("PRAGMA query_only").scalar() == 1
    else:
        raise ShadowError("shadow comparisons run only on PostgreSQL or SQLite")
    if not enforced:
        raise ShadowError("the database did not confirm a read-only transaction")
    return {"dialect": dialect, "read_only_enforced": True,
            "isolation": "REPEATABLE READ READ ONLY" if dialect == "postgresql" else "PRAGMA query_only"}


def _read_only_session(bind):
    connection = bind.connect()
    connection.begin()
    try:
        facts = _read_only(connection)
    except Exception:
        _release(connection)
        raise
    return connection, Session(bind=connection, autoflush=False, expire_on_commit=False), facts


def _release(connection):
    try:
        connection.rollback()
    finally:
        if connection.dialect.name == "sqlite":
            connection.invalidate()  # never return a query_only connection to the pool
        connection.close()


def _is_write_refusal(exc):
    message = str(getattr(exc, "orig", exc)).lower()
    return "read-only" in message or "readonly" in message or "read only" in message or "query_only" in message


def run_shadow_reconciliation(bind=None, *, organization_ids, environment, test_activity_attestation, at=None,
                              operation_classifier=None):
    """Run the shadow comparison in one database-enforced read-only transaction; always rolled back.

    ``bind`` defaults to the application engine. The Phase 15 environment
    guard applies (no production runtime; ``fixtures`` only on a verified
    local test database). ``restore_copy`` is refused before any connection
    opens until an approved restore-copy authorization mechanism exists
    (review N4). ``at`` defaults to the database clock; pass it to
    reproduce a report exactly. The census is taken before (inside the
    snapshot) and after (a second read-only transaction); a write attempt
    raises ``ShadowWriteAttemptError``.
    """
    bind = bind if bind is not None else db.engine
    if environment not in ENVIRONMENTS:
        raise ShadowError("a shadow comparison runs only on local fixtures or an approved restore copy")
    if environment in RESTORE_COPY_REFUSED:
        # Review N4 (fail closed): a non-production runtime is not authorization, and no approved mechanism yet
        # proves that a database is an authorized, non-production restore. Refused before any connection opens.
        raise ShadowError("restore_copy shadow runs are refused until an approved restore-copy authorization "
                          "mechanism exists (D18 row 16 production-like run, separately authorized)")
    connection, session, facts = _read_only_session(bind)
    try:
        environment_facts = _guard_environment(connection, environment)
        if at is None:
            at = _database_clock(session)
        before = shadow_census(session)
        try:
            report = shadow_reconciliation(session, organization_ids=organization_ids, at=at,
                                           test_activity_attestation=test_activity_attestation,
                                           operation_classifier=operation_classifier)
        except DBAPIError as exc:
            if _is_write_refusal(exc):
                raise ShadowWriteAttemptError("a write was attempted inside the read-only shadow transaction") \
                    from exc
            raise
        if session.new or session.dirty or session.deleted:
            raise ShadowWriteAttemptError("the shadow session holds pending changes")
    finally:
        session.close()
        _release(connection)
    connection, session, _facts = _read_only_session(bind)
    try:
        after = shadow_census(session)
    finally:
        session.close()
        _release(connection)
    return {"environment": environment, "database": {**facts, **{k: environment_facts[k] for k in
                                                                 ("host", "database", "server_database",
                                                                  "local_test_database", "production_runtime")}},
            "census_before": before, "census_after": after,
            "census_unchanged": before == after, "report": report,
            "generated_at": datetime.now(timezone.utc).isoformat()}


def shadow_repeat_proof(first, second):
    """L2: two runs over the same state reproduce every comparison and write nothing (census based; pure)."""
    a, b = first["report"], second["report"]
    differences = []
    if a["report_fingerprint"] != b["report_fingerprint"]:
        left = {(r["domain"], r["comparison"], str(r["subject"]), str(r["period"])): r
                for acc in a["accounts"] for r in acc["comparisons"]}
        right = {(r["domain"], r["comparison"], str(r["subject"]), str(r["period"])): r
                 for acc in b["accounts"] for r in acc["comparisons"]}
        differences = sorted(str(k) for k in set(left) | set(right) if left.get(k) != right.get(k))
    delta = {name: second["census_after"].get(name, 0) - first["census_before"].get(name, 0)
             for name in first["census_before"]}
    return {"same_fingerprint": a["report_fingerprint"] == b["report_fingerprint"],
            "differences": differences, "census_delta": {k: v for k, v in delta.items() if v},
            "zero_writes": not any(delta.values()) and first["census_unchanged"] and second["census_unchanged"]}


def export_shadow_report(result):
    """Canonical JSON of a run (sorted keys) for durable evidence outside the database."""
    return json.dumps(result, sort_keys=True, indent=2, ensure_ascii=True, default=str)
