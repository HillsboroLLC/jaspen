"""Inactive Phase 14 legacy backfill (D16 evidence-ranked ownership and opening balances).

Commands, run in order for each explicit organization (the payment archive
is global and runs once before plan mappings):

1. ``establish_billing_account`` (D16 step 1): the organization's Phase 3
   billing account (created ``proposed`` when absent), the legacy payer whose
   processor customer it carries, and every legacy payment receipt of that
   payer, each bound to exactly one billing account across the whole database.
2. ``backfill_billing_account`` (D16 steps 2-8): preserved legacy credit value
   moved into the organization-owned Phase 3 ledger as ``migration_opening``
   lots, each legacy source at most once across every billing account.
3. ``archive_legacy_payments`` (founder decision 2026-11-18): every legacy
   payment row preserved exactly as an immutable archive, ``test_activity``
   only for payers an explicit founder attestation names, else
   ``unverified``; never a Phase 5.2 financial transaction, nothing missing
   filled in, and nothing created when no payment exists.
4. ``map_legacy_plan`` (founder decision 2026-11-18): the evidence-backed
   legacy plan, subscription, entitlements, and seats of one established
   account. Free accounts map as free; a paid subscription maps with its
   dates, paid seats, and payment details unresolved (a later, separately
   authorized processor read); ambiguous records quarantine. No Phase 4
   subscription or entitlement is created: that needs approved definitions.

* **Gate 1 (credit units).** Legacy stored integers and ledger integers are the
  same unit: the legacy internal unit, 1,000 per displayed credit
  (``billing_config.TOKENS_PER_CREDIT``, ``ai_governance.INTERNAL_UNITS_PER_CREDIT``;
  D16 "exact in internal integer credit units"). Values are copied as stored,
  never converted. The stored scale changed on 2026-05-08 (commit 8599941d,
  no data rewrite); a value whose cycle or grant started before that boundary
  is never opened as available.
* **Ownership.** Every customer is an organization. Personal legacy value
  (a user's own meter and persistent grants) belongs to the organization
  proven by payer evidence (a processor customer or payment already linked to
  a billing account), else the pooled organization the user owns and pays for,
  else the user's sole-member organization; the active organization (and the
  active-organization stamp on legacy payments and grants) is never evidence,
  only a veto. Once a payer is bound, any later disagreeing evidence
  quarantines instead of moving value. Organization pool value belongs to the
  organization. Member attribution is preserved; no personal billing account
  is created. Ambiguous ownership quarantines.
* **Expiry (founder decision 2026-11-18).** Purchased credit keeps its
  original terms: recurring value expires at its legacy cycle end; credit
  packs and the 300K offer were sold non-expiring and stay non-expiring; a
  reviewed unattributed amount needs the evidence of its terms. No expiry is
  ever invented, and value whose terms cannot be established quarantines.
* **Evidence ranks (D16).** Persistent grants with their immutable payment
  and transaction log (rank 1, grant rows rank 2 behind it); organization and
  user meters with anchored reset dates (rank 3); the combined counter and
  plan (rank 4) are compared, never used to mint value; reviewed
  ``legacy_unattributed`` only with a recorded reconciliation review (rank 6).
* **Reconciliation.** Openings are written in a probe savepoint, then checked
  with the D16 conservation equations (exact integers) and the accepted
  Phase 13 comparison; any unexplained credit difference rolls the openings
  back and records a quarantined result. The Phase 3 ledger stays the only
  balance authority and no historical entry is changed.
* **Idempotency and uniqueness.** Each opening has a deterministic key and a
  source fingerprint, and the database admits one opening per legacy source
  across all accounts. Replaying the same evidence opens nothing (outcome
  ``unchanged``); changed evidence for an opened account, or a source already
  opened elsewhere, quarantines and never mints value.

Nothing in live routes, the AI runtime, webhooks, jobs, or startup calls this
module, and it never writes a legacy field. Phase 15 orchestrates rehearsals
from these commands and reports.
"""

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import uuid

from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from .ai_audit import STARTED as OPERATION_STARTED
from .ai_audit import TERMINAL_STATUSES as TERMINAL_OPERATION_STATUSES
from .ai_audit import TURN_LIFECYCLE_KEY, classify_unclosed_operation
from .ai_governance import CREDITS_PER_PROVIDER_DOLLAR, INTERNAL_UNITS_PER_CREDIT, credits_for_provider_cost
from .billing_allocations import (
    RecurringAllocationConflictError,
    RecurringAllocationRetryError,
    _claim_registry,
    _complete_registry_if_claimed,
)
from .billing_config import DEFAULT_PLAN_CATALOG, SHARED_POOL_PLANS, TOKENS_PER_CREDIT, normalize_plan_key
from .billing_entitlements import add_calendar_months
from .billing_ledger import CreditLedgerInvariantError, append_entry, lock_billing_account
from .billing_offers import (
    OfferIsolationError,
    _authorized_grant,
    _database_clock,
    _database_now,
    _require_read_committed,
)
from .billing_projections import (
    MATCH,
    UNRESOLVED,
    _int_or_none,
    _lot_balances,
    _meter,
    _open_at,
    _parsed,
    _settled_by_operation,
    _utc,
    compare_legacy_compatibility,
    project_billing_account,
)
from .models import (
    AccountEntitlement,
    AIOperation,
    BillingAccount,
    CreditLedgerEntry,
    CreditLot,
    Organization,
    OrganizationMember,
    Payment,
    PersistentCreditGrant,
    PersistentCreditTransaction,
    PricingPolicyVersion,
    User,
)
from .models_billing_phase12 import CONVERSION_KEY
from .models_billing_phase14 import (
    ALGORITHM_VERSION,
    CREDIT_UNIT_BASIS,
    EXPIRY_POLICY,
    OPERATION_DECISION_CLASSES,
    OPERATION_DECISION_RULE_VERSION,
    OPERATION_DISPOSITIONS,
    REVIEW_PERMISSION,
    UNITS_PER_DISPLAYED_CREDIT,
    BillingMigrationAccountResult,
    BillingMigrationEstablishment,
    BillingMigrationOpening,
    BillingMigrationOperationDecision,
    BillingMigrationPayerBinding,
    BillingMigrationPaymentArchive,
    BillingMigrationPaymentAttribution,
    BillingMigrationPlanMapping,
    BillingMigrationReview,
    BillingMigrationRun,
    PAYMENT_CLASSIFICATIONS,
)


# The 2026-05-08 change of the stored scale (commit 8599941d, 09:33:57 -0400).
UNIT_BOUNDARY_AT = datetime(2026, 5, 8, 13, 33, 57, tzinfo=timezone.utc)

# The verified accounting relationship (Gate 1 and ai_governance): 3,600
# displayed credits per provider dollar = 3,600,000 internal units per dollar.
DISPLAYED_CREDITS_PER_PROVIDER_USD = 3600
INTERNAL_UNITS_PER_PROVIDER_USD = DISPLAYED_CREDITS_PER_PROVIDER_USD * UNITS_PER_DISPLAYED_CREDIT

# Founder decision (2026-11-18): purchased credit keeps its original terms.
# Each legacy persistent-grant source, and the legacy evidence that it was sold
# non-expiring. Any other source has no established terms and quarantines.
NON_EXPIRING_LEGACY_CONTRACTS = {
    "credit_pack": "legacy credit packs are fulfilled as a non-expiring PersistentCreditGrant "
                   "(routes/billing.py credit-pack fulfilment; models.PersistentCreditGrant)",
    "300k_limited_time": "the 300K offer was sold as 'One payment. No subscription. Credits never expire.' "
                         "(app/__init__.py 300K grant; RankThemPromoModal and checkout terms)",
}
# Legacy checkout creates every price in this currency (routes/billing.py).
LEGACY_CATALOG_CURRENCY = "usd"

SYSTEM_ACTOR = "system"
RUN_NAMESPACE = "billing.migration.run"
ESTABLISHMENT_NAMESPACE = "billing.migration.establishment"
RESULT_NAMESPACE = "billing.migration.account_result"
OPENING_NAMESPACE = "billing.migration.opening"
REVIEW_NAMESPACE = "billing.migration.review"

GRANT_PREFIXES = {"credit_pack": "credit-pack:", "300k_limited_time": "300k-limited-time-credit:"}
PAYMENT_SOURCES = {"credit_pack": "credit_pack", "300k_limited_time": "limited_time_300k"}
SALES_LED_PLANS = frozenset({"enterprise_custom"})
RECURRING_KINDS = ("user_recurring_meter", "organization_recurring_meter")

# Phase 13 comparison fields that carry credit value. Plan, status, seat, offer,
# and reset-date fields need the entitlement, subscription, and period records
# of a separate backfill; they block cutover but never quarantine credits.
CREDIT_FIELDS = frozenset({
    "users.credits_remaining",
    "users.ui_preferences.thinking_power.remaining",
    "organizations.settings.thinking_power.remaining",
    "persistent_credit_grants.remaining_amount",
    "ai_operations.charged_credits",
})


class MigrationError(ValueError):
    """A migration command that cannot be performed as asked."""


class MigrationConflictError(MigrationError):
    """A migration identity was reused with different facts."""


class MigrationRetryError(MigrationError):
    """A concurrent command holds the identity; retry the transaction."""


class MigrationPermissionError(MigrationError):
    """The actor lacks the explicit authority the command requires."""


class MigrationUnitError(MigrationError):
    """Gate 1 no longer holds: the legacy and ledger units are not proven identical."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _fingerprint(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _iso(value):
    value = _utc(value)
    return value.isoformat() if value is not None else None


def _text(value, field, maximum):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise MigrationError(f"{field} must be non-empty text of at most {maximum} characters")
    return value.strip()


def _claim(session, namespace, key, fingerprint, at):
    try:
        return _claim_registry(session, namespace, key, fingerprint, at)
    except RecurringAllocationConflictError as exc:
        raise MigrationConflictError(f"{namespace} identity was reused with different facts") from exc
    except RecurringAllocationRetryError as exc:
        raise MigrationRetryError(str(exc)) from exc


def _complete(session, registry, at, result_type, result_id):
    try:
        _complete_registry_if_claimed(session, registry, completed_at=at, result_type=result_type,
                                      result_id=result_id)
    except RecurringAllocationConflictError as exc:
        raise MigrationConflictError(str(exc)) from exc


def _lock_account(session, billing_account_id):
    try:
        return lock_billing_account(session, billing_account_id)
    except CreditLedgerInvariantError as exc:
        raise MigrationError("billing account is not available") from exc


def _read_committed(session):
    try:
        _require_read_committed(session)
    except OfferIsolationError as exc:
        raise MigrationError("migration commands must run in a READ COMMITTED transaction") from exc


def _system(actor_type, actor_id):
    if actor_type != SYSTEM_ACTOR:
        raise MigrationPermissionError("the backfill runs only as the trusted migration service actor")
    return actor_type, _text(actor_id, "actor_id", 255)


def _quarantine(codes, code, subject=None, detail=None):
    codes.append({"code": code, "subject": subject, "detail": detail})


# ---------------------------------------------------------------------------
# Gate 1: credit-unit equivalence
# ---------------------------------------------------------------------------

def verify_credit_unit_equivalence():
    """Return the Gate 1 evidence, or raise when the unit identity no longer holds."""
    legacy = int(TOKENS_PER_CREDIT)
    governance = int(INTERNAL_UNITS_PER_CREDIT)
    if not legacy == governance == UNITS_PER_DISPLAYED_CREDIT:
        raise MigrationUnitError(
            f"legacy ({legacy}) and governance ({governance}) internal units per displayed credit "
            f"must both equal {UNITS_PER_DISPLAYED_CREDIT}"
        )
    live_rate = credits_for_provider_cost(1, internal=True)
    if Decimal(CREDITS_PER_PROVIDER_DOLLAR) != DISPLAYED_CREDITS_PER_PROVIDER_USD \
            or live_rate != INTERNAL_UNITS_PER_PROVIDER_USD:
        raise MigrationUnitError(
            f"the live rate must remain {DISPLAYED_CREDITS_PER_PROVIDER_USD} displayed credits = "
            f"{INTERNAL_UNITS_PER_PROVIDER_USD} internal units per provider dollar (found {live_rate})"
        )
    return {
        "credit_unit_basis": CREDIT_UNIT_BASIS,
        "units_per_displayed_credit": UNITS_PER_DISPLAYED_CREDIT,
        "legacy_tokens_per_credit": legacy,
        "governance_internal_units_per_credit": governance,
        "conversion": "identity: legacy stored integers are ledger integers",
        "displayed_credits_per_provider_usd": DISPLAYED_CREDITS_PER_PROVIDER_USD,
        "internal_units_per_provider_usd": INTERNAL_UNITS_PER_PROVIDER_USD,
        "unit_boundary_at": UNIT_BOUNDARY_AT.isoformat(),
        "unit_boundary_rule": "a cycle or grant that started before the boundary is never opened as available",
    }


def pricing_unit_findings(session):
    """Approved, announced, or effective pricing versions not stated in internal units (pure).

    Migrated balances are legacy internal units, so an approved pricing version
    must state ``credits_per_provider_usd`` in the same unit. A version stating
    3,600 (displayed credits) would make every migrated credit 1,000 times
    cheaper to spend; any other rate is a pricing change with its own approval
    and never a migration input. Returns one finding per offending version.
    """
    findings = []
    for version in session.execute(
        select(PricingPolicyVersion).where(PricingPolicyVersion.approved_at.is_not(None),
                                           PricingPolicyVersion.state.in_(("approved", "announced", "effective")))
        .order_by(PricingPolicyVersion.version, PricingPolicyVersion.id)
    ).scalars():
        raw = version.conversion_json.get(CONVERSION_KEY) if isinstance(version.conversion_json, dict) else None
        try:
            rate = Decimal(str(raw)) if raw is not None and not isinstance(raw, bool) else None
        except ArithmeticError:
            rate = None
        if rate == INTERNAL_UNITS_PER_PROVIDER_USD:
            continue
        code = ("pricing_rate_in_displayed_credits" if rate == DISPLAYED_CREDITS_PER_PROVIDER_USD
                else "pricing_rate_not_the_verified_internal_rate")
        findings.append({"code": code, "pricing_policy_version_id": version.id, "version": version.version,
                         "stated_rate": None if raw is None else str(raw),
                         "required_rate": INTERNAL_UNITS_PER_PROVIDER_USD})
    return findings


# ---------------------------------------------------------------------------
# Ownership (D16 step 1)
# ---------------------------------------------------------------------------

def _members(session, organization_id, *, active_only):
    query = select(OrganizationMember).where(OrganizationMember.organization_id == organization_id)
    if active_only:
        query = query.where(OrganizationMember.status == "active")
    return session.execute(query.order_by(OrganizationMember.user_id)).scalars().all()


def _account_for(session, organization_id):
    return session.execute(
        select(BillingAccount).where(BillingAccount.organization_id == organization_id)
    ).scalar_one_or_none()


def _migration_assigned_accounts():
    """Accounts whose processor customer Phase 14 itself assigned: its output, never legacy evidence."""
    return select(BillingMigrationPayerBinding.billing_account_id).where(
        BillingMigrationPayerBinding.customer_assigned_by_migration.is_(True))


def _legacy_payer_organizations(session, user):
    """Rank 1: payer evidence the legacy system or an external processor recorded (never Phase 14's own).

    A billing account already carrying the user's processor customer (unless
    Phase 14 itself assigned it), and legacy payments linked to a billing
    account. Returns ``{organization_id: [evidence]}``.
    """
    found = defaultdict(list)
    if user.stripe_customer_id:
        for account_id, organization_id in session.execute(
            select(BillingAccount.id, BillingAccount.organization_id).where(
                BillingAccount.processor == "stripe",
                BillingAccount.processor_customer_id == user.stripe_customer_id,
                BillingAccount.id.not_in(_migration_assigned_accounts()),
            )
        ):
            found[organization_id].append({"kind": "processor_customer", "billing_account_id": account_id})
    for payment_id, account_id, organization_id in session.execute(
        select(Payment.id, Payment.billing_account_id, BillingAccount.organization_id)
        .join(BillingAccount, BillingAccount.id == Payment.billing_account_id)
        .where(Payment.user_id == user.id).order_by(Payment.id)
    ):
        found[organization_id].append({"kind": "payment_link", "payment_id": payment_id,
                                       "billing_account_id": account_id})
    return found


def _pooled_owned_organizations(session, user):
    """Rank 2: the pooled organization the user owns while on its pooled plan (the pool's payer)."""
    if normalize_plan_key(user.subscription_plan) not in SHARED_POOL_PLANS:
        return []
    return session.execute(
        select(Organization.id).where(Organization.owner_user_id == user.id)
        .where(or_(*[Organization.plan_key == plan for plan in sorted(SHARED_POOL_PLANS)]))
        .order_by(Organization.id)
    ).scalars().all()


def _sole_member_organizations(session, user):
    """Rank 3: organizations the user owns and is the only member of (any membership status)."""
    found = []
    for organization_id in session.execute(
        select(Organization.id).where(Organization.owner_user_id == user.id).order_by(Organization.id)
    ).scalars():
        if {m.user_id for m in _members(session, organization_id, active_only=False)} == {user.id}:
            found.append(organization_id)
    return found


def _legacy_owner(session, user):
    """The organization owning a user's personal legacy value, from legacy evidence only (stable across runs)."""
    evidence = []
    payer = _legacy_payer_organizations(session, user)
    for organization_id in sorted(payer):
        evidence += payer[organization_id]
    if len(payer) > 1:
        return None, evidence, "conflicting_payer_evidence"
    if payer:
        organization_id, reason = next(iter(payer)), "payer_evidence"
    else:
        pooled = _pooled_owned_organizations(session, user)
        evidence += [{"kind": "pooled_organization_owner", "organization_id": o} for o in pooled]
        if len(pooled) > 1:
            return None, evidence, "several_pooled_organizations"
        if pooled:
            organization_id, reason = pooled[0], "pooled_organization_owner"
        else:
            sole = _sole_member_organizations(session, user)
            evidence += [{"kind": "sole_member_organization", "organization_id": o} for o in sole]
            if len(sole) != 1:
                return None, evidence, "no_ownership_evidence" if not sole else "several_sole_member_organizations"
            organization_id, reason = sole[0], "sole_member_organization"
    # The active-organization stamp on legacy payments is never evidence, only a veto.
    stamped = sorted(set(session.execute(
        select(Payment.organization_id).where(Payment.user_id == user.id, Payment.organization_id.is_not(None),
                                              Payment.organization_id != organization_id)
    ).scalars()))
    if stamped:
        evidence.append({"kind": "payment_organization_stamp", "organization_ids": stamped})
        return None, evidence, "payment_organization_conflict"
    return organization_id, evidence, reason


def resolve_legacy_value_owner(session, user):
    """The organization (and its billing account) that owns a user's personal legacy value, from evidence only.

    Ranked legacy evidence decides (payer evidence, then the pooled
    organization the user owns and pays for, then the sole-member
    organization); the active organization is never consulted. A Phase 14
    payer binding or payment attribution pins that decision: any later
    disagreement returns ``None`` (``payer_binding_conflict``) so value is
    quarantined, never moved. Returns a dict with ``organization_id``,
    ``billing_account_id`` (either ``None`` when unresolved; the account is
    also ``None`` while the organization has none), ``evidence``, and ``reason``.
    """
    organization_id, evidence, reason = _legacy_owner(session, user)
    pinned = set(session.execute(
        select(BillingAccount.organization_id).join(
            BillingMigrationPayerBinding, BillingMigrationPayerBinding.billing_account_id == BillingAccount.id)
        .where(BillingMigrationPayerBinding.payer_user_id == user.id)
    ).scalars())
    pinned |= set(session.execute(
        select(BillingAccount.organization_id).join(
            BillingMigrationPaymentAttribution,
            BillingMigrationPaymentAttribution.billing_account_id == BillingAccount.id)
        .join(Payment, Payment.id == BillingMigrationPaymentAttribution.payment_id)
        .where(Payment.user_id == user.id)
    ).scalars())
    if pinned and (organization_id is None or pinned != {organization_id}):
        return {"organization_id": None, "billing_account_id": None,
                "evidence": evidence + [{"kind": "phase14_pinned_organizations", "organization_ids": sorted(pinned)}],
                "reason": "payer_binding_conflict"}
    account = _account_for(session, organization_id) if organization_id else None
    return {"organization_id": organization_id, "billing_account_id": account.id if account else None,
            "evidence": evidence, "reason": reason}


# ---------------------------------------------------------------------------
# Legacy evidence (read only)
# ---------------------------------------------------------------------------

def _meter_evidence(meter):
    """The recorded meter fields as evidence, or the reason they cannot be used."""
    if meter is None:
        return None, "legacy_meter_absent"
    remaining, limit = _int_or_none(meter.get("remaining")), _int_or_none(meter.get("cycle_limit"))
    overage = _int_or_none(meter.get("overage_tokens", 0))
    reset = _parsed(meter.get("cycle_reset_at"))
    fields = {"remaining": meter.get("remaining"), "cycle_limit": meter.get("cycle_limit"),
              "overage_tokens": meter.get("overage_tokens", 0), "cycle_reset_at": meter.get("cycle_reset_at")}
    if remaining is None or limit is None or overage is None or reset is None:
        return fields, "malformed_legacy_meter"
    if remaining < 0:
        return fields, "negative_legacy_meter"
    if overage < 0:
        return fields, "malformed_legacy_meter"
    if remaining > limit:
        return fields, "meter_above_cycle_limit"
    # Overage is judged by its cycle: it expired with a lapsed cycle (original terms), and quarantines in a live one.
    return {**fields, "remaining": remaining, "cycle_limit": limit, "overage_tokens": overage,
            "cycle_reset_at": reset.isoformat()}, None


def _grant_evidence(session, grant):
    log = session.execute(
        select(PersistentCreditTransaction)
        .where(PersistentCreditTransaction.grant_id == grant.id)
        .order_by(PersistentCreditTransaction.created_at, PersistentCreditTransaction.id)
    ).scalars().all()
    reasons = sorted({str((t.transaction_metadata or {}).get("reason") or "") for t in log
                      if t.transaction_type == "reversal"})
    prefix = GRANT_PREFIXES.get(grant.source)
    reference = grant.external_reference[len(prefix):] if prefix and grant.external_reference.startswith(prefix) else None
    return {
        "grant_id": grant.id, "user_id": grant.user_id, "source": grant.source, "status": grant.status,
        "original_amount": int(grant.original_amount), "remaining_amount": int(grant.remaining_amount),
        "external_reference": grant.external_reference, "payment_reference": reference,
        "organization_id": grant.organization_id, "granted_at": _iso(grant.granted_at),
        "log": [{"id": t.id, "type": t.transaction_type, "amount": int(t.amount), "balance_after": int(t.balance_after)}
                for t in log],
        "reversal_reasons": reasons,
    }


def _payment_evidence(session, reference):
    if not reference:
        return None
    payment = session.execute(select(Payment).where(Payment.external_reference == reference)).scalar_one_or_none()
    if payment is None:
        return None
    attributed = session.execute(
        select(BillingMigrationPaymentAttribution.billing_account_id)
        .where(BillingMigrationPaymentAttribution.payment_id == payment.id)
    ).scalar_one_or_none()
    return {
        "attributed_billing_account_id": attributed,
        "payment_id": payment.id, "external_reference": payment.external_reference, "user_id": payment.user_id,
        "billing_account_id": payment.billing_account_id, "source": payment.source,
        "currency": (payment.currency or "").lower(), "amount_paid_cents": int(payment.amount_paid_cents or 0),
        "amount_due_cents": int(payment.amount_due_cents or 0), "discount_cents": int(payment.discount_cents or 0),
        "is_comped": bool(payment.is_comped), "paid_at": _iso(payment.paid_at),
    }


def _duplicate_payment_references(session, reference, grant_id):
    if not reference:
        return []
    candidates = [prefix + reference for prefix in GRANT_PREFIXES.values()]
    return session.execute(
        select(PersistentCreditGrant.id).where(
            PersistentCreditGrant.external_reference.in_(candidates), PersistentCreditGrant.id != grant_id,
        ).order_by(PersistentCreditGrant.id)
    ).scalars().all()


def _user_has_personal_value(session, user):
    plan = normalize_plan_key(user.subscription_plan)
    shared = plan in SHARED_POOL_PLANS
    meter = _meter(user.ui_preferences)
    meter_value = meter is not None and meter.get("remaining") not in (None, 0)
    counter = user.credits_remaining not in (None, 0)
    grants = session.execute(
        select(func.count()).select_from(PersistentCreditGrant).where(PersistentCreditGrant.user_id == user.id)
    ).scalar_one() > 0
    return grants or (not shared and (meter_value or counter))


def _holder_evidence(session, user):
    """Every legacy field of one user that bears on their personal value, as references and amounts."""
    grants = session.execute(
        select(PersistentCreditGrant).where(PersistentCreditGrant.user_id == user.id)
        .order_by(PersistentCreditGrant.granted_at, PersistentCreditGrant.id)
    ).scalars().all()
    plan = normalize_plan_key(user.subscription_plan)
    meter = _meter(user.ui_preferences)
    grant_evidence = []
    for grant in grants:
        item = _grant_evidence(session, grant)
        item["payment"] = _payment_evidence(session, item["payment_reference"])
        item["duplicate_reference_grants"] = _duplicate_payment_references(session, item["payment_reference"], grant.id)
        grant_evidence.append(item)
    return {
        "user_id": user.id, "plan": plan, "shared_pool_plan": plan in SHARED_POOL_PLANS,
        "credits_remaining": user.credits_remaining, "credits_reset_at": _iso(user.credits_reset_at),
        "meter": None if meter is None else {k: meter.get(k) for k in
                                             ("remaining", "cycle_limit", "overage_tokens", "cycle_reset_at")},
        "grants": grant_evidence,
    }


# ---------------------------------------------------------------------------
# Legacy AI operations that never closed (BI-1: P4.1 X1 wiring, D-1, D-3)
# ---------------------------------------------------------------------------
#
# An unclosed legacy operation used to quarantine its account whatever it was.
# The P4.1 X1 classifier (``ai_audit.classify_unclosed_operation``) tells a
# chat turn that is still running apart from one whose process is long gone.
# Phase 14 refines its answer into five classes and never writes to the row:
#
# * ``in_flight``: may still change a balance (a young turn, a young runtime
#   operation, a row bound to a billing account, or no age limit configured).
#   Quarantines, as before.
# * ``unrecognized``: a status, lifecycle version, or timestamp the classifier
#   does not positively recognise. Quarantines; no decision can clear it.
# * ``already_charged``: a P4.0 turn past the age limit whose own durable
#   facts show the settlement committed (only its status write failed). It
#   cannot change a balance and its charge stands, so it does not quarantine.
# * ``stale_turn_evidence``: a P4.0 turn killed before it recorded an outcome.
#   Whether a mid-turn commit kept its reservation is unknown (F3).
# * ``outstanding_reservation``: an unbound runtime operation past the age
#   limit, whose reservation was committed with its claim and never settled
#   or released.
#
# The last two quarantine until a reviewer records a decision for that exact
# row (``record_operation_decision``). Nothing is compensated automatically:
# ``compensation_owed`` keeps the account quarantined until a separately
# approved compensation path exists.

MAX_TURN_SECONDS_CONFIG_KEY = "BILLING_MIGRATION_MAX_TURN_SECONDS"
# A floor against a mistyped bound (minutes entered as seconds). The approved
# value is set at integration from the production gunicorn timeout plus margin (D-3).
MIN_MAX_TURN_SECONDS = 300
OPERATION_DECISION_NAMESPACE = "billing.migration.operation_decision"
DECIDABLE_OPERATION_CLASSES = frozenset(OPERATION_DECISION_CLASSES)


def migration_max_turn_seconds(config=None):
    """The explicitly configured age limit for unclosed operations, or None.

    There is no default: missing, non-integer, or below-floor values return
    None, and every unclosed operation is then treated as in flight.
    """
    if config is None:
        from flask import current_app, has_app_context
        if not has_app_context():
            return None
        config = current_app.config
    value = config.get(MAX_TURN_SECONDS_CONFIG_KEY)
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if not isinstance(value, int) or value < MIN_MAX_TURN_SECONDS:
        return None
    return value


def operation_fingerprint(operation):
    """The fingerprint of every column of a legacy operation row: any change ends a decision's validity."""
    return _fingerprint({column.name: getattr(operation, column.key, None)
                         for column in AIOperation.__table__.columns})


def _effective_start(operation):
    """The later of the row's creation and its last write (UTC, naive).

    A runtime retry (``ai_runtime._claim_operation``) puts a failed row back to
    'started' without changing ``created_at``; its last write is the new claim.
    """
    times = [t for t in (operation.created_at, getattr(operation, "updated_at", None)) if t is not None]
    return _naive_utc(max(_utc(t) for t in times)) if times else None


def _naive_utc(at):
    value = _utc(at)
    return value.replace(tzinfo=None) if value is not None else None


def classify_legacy_operation(operation, *, at, max_turn_seconds):
    """Phase 14 class of one unclosed legacy operation (see above). Reads only."""
    base = {"operation_id": operation.id, "status": operation.status, "operation_type": operation.operation_type,
            "billing_account_id": getattr(operation, "billing_account_id", None)}
    if operation.status in TERMINAL_OPERATION_STATUSES:
        return None
    if max_turn_seconds is None:
        return {**base, "class": "in_flight", "reason": "age_limit_not_configured"}
    if operation.status != OPERATION_STARTED:
        return {**base, "class": "unrecognized", "reason": "unrecognized_status"}
    x1 = classify_unclosed_operation(operation, now=_naive_utc(at), max_turn_seconds=max_turn_seconds)
    result = {**base, "x1_class": x1["class"], "x1_reason": x1["reason"], "age_seconds": x1["age_seconds"],
              "max_turn_seconds": max_turn_seconds}
    if x1["class"] == "in_progress":
        return {**result, "class": "in_flight", "reason": "turn_within_age_limit"}
    effective = _effective_start(operation)
    if effective is not None and x1["age_seconds"] is not None:
        result["age_seconds"] = min(x1["age_seconds"], int((_naive_utc(at) - effective).total_seconds()))
        if result["age_seconds"] < max_turn_seconds:
            # Written to (or reclaimed) within the limit: it may still be running.
            return {**result, "class": "in_flight", "reason": "written_within_age_limit"}
    if x1["class"] == "stale_turn_evidence":
        lifecycle = (operation.metadata_json or {}).get(TURN_LIFECYCLE_KEY) or {}
        facts = {key: lifecycle.get(key) for key in (
            "outcome", "settlement_ok", "balance_committed", "settled_credits", "estimated_reservation",
            "cycle_marker", "claim_committed", "claimed_at")}
        if (lifecycle.get("outcome") == "settled" and lifecycle.get("settlement_ok") is True
                and lifecycle.get("balance_committed") is True):
            return {**result, "class": "already_charged", "reason": "settled_with_durable_charge", "facts": facts}
        reason = "no_recorded_outcome" if lifecycle.get("outcome") is None else "outcome_without_durable_charge"
        return {**result, "class": "stale_turn_evidence", "reason": reason, "facts": facts}
    # X1 says outstanding. Runtime operations reach here; so do rows it cannot recognise.
    if x1["reason"] != "not_a_p4_0_turn_claim" or x1["age_seconds"] is None:
        return {**result, "class": "unrecognized", "reason": x1["reason"]}
    metadata = operation.metadata_json if isinstance(operation.metadata_json, dict) else None
    if result["billing_account_id"] is not None or metadata is None or TURN_LIFECYCLE_KEY in metadata:
        return {**result, "class": "in_flight" if result["billing_account_id"] is not None else "unrecognized",
                "reason": "bound_to_billing_account" if result["billing_account_id"] is not None
                else "unrecognized_runtime_metadata"}
    if result["age_seconds"] < max_turn_seconds:
        return {**result, "class": "in_flight", "reason": "runtime_within_age_limit"}
    return {**result, "class": "outstanding_reservation", "reason": "runtime_reservation_never_closed"}


def _unclosed_operations(session, user_ids):
    if not user_ids:
        return []
    return session.execute(
        select(AIOperation).where(AIOperation.user_id.in_(sorted(user_ids)),
                                  or_(AIOperation.status.is_(None),
                                      AIOperation.status.notin_(sorted(TERMINAL_OPERATION_STATUSES))))
        .order_by(AIOperation.id)
    ).scalars().all()


def _decisions_for(session, operation_ids):
    if not operation_ids:
        return {}
    rows = session.execute(
        select(BillingMigrationOperationDecision)
        .where(BillingMigrationOperationDecision.ai_operation_id.in_(sorted(operation_ids)))
        .order_by(BillingMigrationOperationDecision.created_at, BillingMigrationOperationDecision.id)
    ).scalars().all()
    found = defaultdict(list)
    for row in rows:
        found[row.ai_operation_id].append(row)
    return found


def _effective_decision(decisions, fingerprint):
    """The current decision for ``fingerprint``: the end of its append-only correction chain, or None."""
    matching = [d for d in decisions if d.evidence_fingerprint == fingerprint]
    superseded = {d.supersedes_decision_id for d in matching if d.supersedes_decision_id}
    current = [d for d in matching if d.id not in superseded]
    # More than one current decision cannot happen under the database constraints; if it did, none applies.
    return current[0] if len(current) == 1 else None


def _current_decision(session, operation_id, fingerprint):
    return _effective_decision(_decisions_for(session, [operation_id]).get(operation_id, []), fingerprint)


def operation_affected_organization_ids(session, operation):
    """Every organization an unclosed operation can block, by the same rules Phase 14 uses to pick an
    account's candidate users (``plan_account_backfill``): its own organization, and each organization whose
    candidates include the operation's user, as owner or member (any status), as the Stripe customer of its
    billing account, or as the payer of a payment on that account."""
    found = {operation.organization_id} if operation.organization_id else set()
    if not operation.user_id:
        return found
    found |= set(session.execute(select(Organization.id).where(
        Organization.owner_user_id == operation.user_id)).scalars())
    found |= set(session.execute(select(OrganizationMember.organization_id).where(
        OrganizationMember.user_id == operation.user_id)).scalars())
    subject = session.get(User, operation.user_id)
    if subject is not None and subject.stripe_customer_id:
        found |= set(session.execute(select(BillingAccount.organization_id).where(
            BillingAccount.processor == "stripe",
            BillingAccount.processor_customer_id == subject.stripe_customer_id)).scalars())
    found |= set(session.execute(select(BillingAccount.organization_id).join(
        Payment, Payment.billing_account_id == BillingAccount.id).where(
        Payment.user_id == operation.user_id)).scalars())
    return found


def legacy_operation_status(operation, *, at, max_turn_seconds, decisions=()):
    """Whether one unclosed legacy operation blocks migration, and why. Reads only.

    Returns None for a closed operation, else a dict with the Phase 14
    ``class``, its ``reason``, the quarantine ``code`` (None when it does not
    block), and, for the decidable classes, the ``evidence_fingerprint`` and
    the matching decision, if any. ``decisions`` are the operation's recorded
    decisions.
    """
    item = classify_legacy_operation(operation, at=at, max_turn_seconds=max_turn_seconds)
    if item is None:
        return None
    cls = item["class"]
    result = {"operation_id": operation.id, "class": cls, "reason": item["reason"], "code": None, "detail": None}
    if cls == "in_flight":
        return {**result, "code": "legacy_operation_in_flight",
                "detail": "pause or drain operations; a hold is never inferred from a counter"}
    if cls == "unrecognized":
        return {**result, "code": "legacy_operation_unrecognized",
                "detail": f"{item['reason']}: no decision can clear an operation the classifier does not recognise"}
    result["evidence_fingerprint"] = operation_fingerprint(operation)
    if cls == "already_charged":
        return result
    decision = _effective_decision(decisions, result["evidence_fingerprint"])
    if decision is None:
        if decisions:
            return {**result, "code": "legacy_operation_decision_evidence_changed",
                    "detail": "the operation differs from the evidence its decision was recorded from"}
        return {**result, "code": "legacy_operation_decision_required",
                "detail": f"{cls}: record an individual reviewed decision for this operation"}
    result.update(decision_id=decision.id, disposition=decision.disposition,
                  supersedes_decision_id=decision.supersedes_decision_id)
    if decision.disposition == "compensation_owed":
        return {**result, "code": "legacy_operation_compensation_pending",
                "detail": "compensation is recorded as owed; no approved compensation path has paid it"}
    return result


def blocking_legacy_operations(session, operations, at):
    """The subset of ``operations`` that still blocks migration, with their status. Reads only."""
    bound = migration_max_turn_seconds()
    decisions = _decisions_for(session, [o.id for o in operations])
    found = []
    for operation in operations:
        status = legacy_operation_status(operation, at=at, max_turn_seconds=bound,
                                         decisions=decisions.get(operation.id, []))
        if status is not None and status["code"] is not None:
            found.append(status)
    return found


def _legacy_operation_findings(session, user_ids, at, codes):
    """Quarantine codes for the members' unclosed operations; returns the ones that do not block."""
    bound = migration_max_turn_seconds()
    operations = _unclosed_operations(session, user_ids)
    decisions = _decisions_for(session, [o.id for o in operations])
    reported = []
    for operation in operations:
        status = legacy_operation_status(operation, at=at, max_turn_seconds=bound,
                                         decisions=decisions.get(operation.id, []))
        if status is None:
            continue
        if status["code"] is not None:
            _quarantine(codes, status["code"], operation.id, status["detail"])
            continue
        reported.append({key: status[key] for key in ("operation_id", "class", "reason", "evidence_fingerprint",
                                                      "decision_id", "disposition") if key in status})
    return reported


def _legacy_usage_history(session, user_ids):
    """Legacy (unbound) operation charges: reported for the D16 usage equation, never re-ledgered."""
    if not user_ids:
        return {}
    rows = session.execute(
        select(AIOperation.user_id, func.count(), func.coalesce(func.sum(AIOperation.charged_credits), 0))
        .where(AIOperation.user_id.in_(sorted(user_ids)), AIOperation.billing_account_id.is_(None))
        .group_by(AIOperation.user_id)
    ).all()
    return {user_id: {"operations": int(count), "charged_credits": int(total)} for user_id, count, total in rows}


def _opened_elsewhere(session, kind, source_id, account_id):
    """The billing account that already opened this legacy source, when it is another account."""
    return session.execute(
        select(BillingMigrationOpening.billing_account_id).where(
            BillingMigrationOpening.legacy_source_kind == kind,
            BillingMigrationOpening.legacy_source_id == source_id,
            BillingMigrationOpening.billing_account_id != account_id,
        )
    ).scalar_one_or_none()


def _latest_establishment(session, organization_id):
    return session.execute(
        select(BillingMigrationEstablishment).where(BillingMigrationEstablishment.organization_id == organization_id)
        .order_by(BillingMigrationEstablishment.created_at.desc(), BillingMigrationEstablishment.id.desc()).limit(1)
    ).scalar_one_or_none()


def _established(session, organization, account, at, codes):
    """The organization's latest establishment when it still holds for this account; otherwise quarantine codes."""
    establishment = _latest_establishment(session, organization.id)
    if establishment is None or establishment.billing_account_id not in (None, account.id):
        _quarantine(codes, "billing_account_not_established", organization.id,
                    "establish the organization's billing account, payer, and payments first")
    elif establishment.outcome == "quarantined":
        _quarantine(codes, "establishment_quarantined", organization.id,
                    "the latest establishment of this organization's payer and payments is quarantined")
    elif establishment.evidence_fingerprint != plan_establishment(session, organization_id=organization.id,
                                                                  at=at)["evidence_fingerprint"]:
        _quarantine(codes, "establishment_evidence_changed", organization.id,
                    "the payer or payment evidence differs from the evidence the account was established from")
    else:
        return establishment
    return None


def _review_for(session, account_id, user_id, fingerprint, amount):
    used = select(BillingMigrationOpening.review_id).where(BillingMigrationOpening.review_id.is_not(None))
    return session.execute(
        select(BillingMigrationReview).where(
            BillingMigrationReview.billing_account_id == account_id,
            BillingMigrationReview.subject_user_id == user_id,
            BillingMigrationReview.evidence_fingerprint == fingerprint,
            BillingMigrationReview.amount == amount,
            BillingMigrationReview.id.not_in(used),
        ).order_by(BillingMigrationReview.reviewed_at, BillingMigrationReview.id).limit(1)
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Planning (pure): D16 steps 1-3 and 7, quarantine, fingerprints
# ---------------------------------------------------------------------------

def _recurring_source(kind, owner_id, member_id, plan, meter_fields, error, at, account_id):
    """One legacy recurring meter: an opening, an expired or zero cycle, or a quarantine code."""
    source = {"kind": kind, "legacy_source_id": owner_id, "member_attribution_id": member_id, "plan": plan,
              "meter": meter_fields}
    if error:
        return source, error, None
    reset = _parsed(meter_fields["cycle_reset_at"])
    cycle_end = add_calendar_months(reset, 1)
    source.update(cycle_starts_at=reset.isoformat(), cycle_ends_at=cycle_end.isoformat())
    if cycle_end <= at:
        # Original terms: a lapsed cycle's remainder (and any overage in it) expired with the cycle.
        source["classification"] = "expired_recurring_value"
        source["expired_amount"] = meter_fields["remaining"] + meter_fields["overage_tokens"]
        source["pre_unit_boundary"] = reset < UNIT_BOUNDARY_AT
        return source, None, None
    if reset > at:
        return source, "reset_date_in_future", None
    if reset < UNIT_BOUNDARY_AT:
        return source, "pre_unit_boundary_value", None
    if meter_fields["overage_tokens"] != 0:
        return source, "overage_in_recurring_meter", None
    if meter_fields["remaining"] == 0:
        source["classification"] = "zero_remaining"
        return source, None, None
    source["classification"] = "live_cycle"
    opening = {
        "opening_key": f"migration-opening:{account_id}:{kind}:{owner_id}:{reset.isoformat()}",
        "legacy_source_kind": kind, "legacy_source_id": owner_id,
        "lot_source_type": "free_recurring" if plan == "free" else "subscription_recurring",
        "member_attribution_id": member_id, "original_amount": meter_fields["cycle_limit"],
        "opening_amount": meter_fields["remaining"], "available_at": reset, "expires_at": cycle_end,
        "expiry_basis": "legacy_cycle_end", "evidence_rank": 3, "review_id": None,
        "expiry_evidence": "the legacy cycle that holds this remainder ends one calendar month after its reset",
    }
    return source, None, opening


def _grant_source(grant, user, account, organization, at):
    """One legacy persistent grant: an opening, a zero or reversed lot, or quarantine codes."""
    codes = []
    source = {"kind": "persistent_credit_grant", "legacy_source_id": grant["grant_id"],
              "member_attribution_id": user.id, "grant": grant}
    original, remaining = grant["original_amount"], grant["remaining_amount"]
    log = grant["log"]
    if grant["source"] not in GRANT_PREFIXES:
        codes.append("unknown_grant_source")
    if grant["source"] not in NON_EXPIRING_LEGACY_CONTRACTS:
        codes.append("expiry_terms_unestablished")
    if original <= 0 or not 0 <= remaining <= original:
        codes.append("malformed_persistent_grant")
    if grant["status"] not in ("active", "reversed") or (grant["status"] == "reversed" and remaining != 0):
        codes.append("contradictory_grant_status")
    if not log or log[0]["type"] != "grant" or log[0]["amount"] != original:
        codes.append("persistent_grant_log_incomplete")
    elif log[-1]["balance_after"] != remaining:
        codes.append("persistent_grant_log_mismatch")
    elif sum(t["amount"] for t in log) != remaining:
        codes.append("persistent_grant_transaction_sum_mismatch")
    if "stripe_chargeback" in grant["reversal_reasons"]:
        codes.append("legacy_dispute_state_unknown")
    if grant["duplicate_reference_grants"]:
        codes.append("duplicate_external_reference")
    if grant["organization_id"] is not None and grant["organization_id"] != organization.id:
        codes.append("grant_organization_conflict")
    granted_at = _parsed(grant["granted_at"])
    if granted_at is None:
        codes.append("grant_date_missing")
    elif granted_at < UNIT_BOUNDARY_AT:
        codes.append("pre_unit_boundary_value")
    elif granted_at > at:
        codes.append("grant_in_future")
    payment = grant["payment"]
    lot_source = None
    if payment is None:
        codes.append("payment_evidence_missing")
    else:
        if payment["user_id"] != user.id or payment["billing_account_id"] not in (None, account.id):
            codes.append("payment_owner_conflict")
        if payment["attributed_billing_account_id"] != account.id:
            # The receipt must be pinned to this account by establishment (globally unique), never assumed.
            codes.append("payment_not_attributed_to_account")
        if payment["source"] != PAYMENT_SOURCES.get(grant["source"]):
            codes.append("payment_source_conflict")
        if payment["amount_paid_cents"] > 0 and not payment["is_comped"]:
            lot_source = "credit_pack_purchase"
        elif payment["amount_paid_cents"] == 0 and payment["is_comped"]:
            lot_source = "promotional"
        else:
            codes.append("payment_amount_conflict")
    if codes or grant["status"] != "active" or remaining == 0:
        source["classification"] = "quarantined" if codes else ("reversed" if grant["status"] == "reversed" else "consumed")
        return source, codes, None
    source["classification"] = "preserved"
    opening = {
        "opening_key": f"migration-opening:{account.id}:persistent_credit_grant:{grant['grant_id']}",
        "legacy_source_kind": "persistent_credit_grant", "legacy_source_id": grant["grant_id"],
        "lot_source_type": lot_source, "member_attribution_id": user.id, "original_amount": original,
        "opening_amount": remaining, "available_at": granted_at, "expires_at": None,
        "expiry_basis": "non_expiring_legacy_contract", "evidence_rank": 1, "review_id": None,
        "expiry_evidence": NON_EXPIRING_LEGACY_CONTRACTS[grant["source"]],
    }
    return source, [], opening


def _payment_record(payment):
    return {
        "payment_id": payment.id, "external_reference": payment.external_reference, "source": payment.source,
        "currency": (payment.currency or "").lower(), "amount_paid_cents": int(payment.amount_paid_cents or 0),
        "amount_due_cents": int(payment.amount_due_cents or 0), "discount_cents": int(payment.discount_cents or 0),
        "is_comped": bool(payment.is_comped), "organization_id": payment.organization_id,
        "billing_account_id": payment.billing_account_id, "paid_at": _iso(payment.paid_at),
    }


def plan_establishment(session, *, organization_id, at=None):
    """Pure D16 step 1 plan for one organization: its billing account, payer, and payments; writes nothing.

    The payer is the member (any status) or owner whose processor customer the
    ranked legacy evidence assigns to this organization; at most one payer per
    account and one account per payer. Every legacy payment of that payer is
    attributed here. Currency comes from those payments (one currency only),
    else the legacy catalog currency; the account anchor is the organization's
    creation time (D07 free anchor). The fingerprint covers legacy evidence
    only, so a replay after establishment is recognised as unchanged.
    """
    with session.no_autoflush:
        verify_credit_unit_equivalence()
        organization = session.get(Organization, organization_id) if organization_id else None
        if organization is None:
            raise MigrationError("organization does not exist")
        at = _database_clock(session) if at is None else _utc(at)
        account = _account_for(session, organization.id)
        codes = []
        if account is not None and account.status == "closed":
            _quarantine(codes, "billing_account_closed", account.id)
        people = {m.user_id for m in _members(session, organization.id, active_only=False)}
        if organization.owner_user_id:
            people.add(organization.owner_user_id)
        considered, payers = [], []
        for user_id in sorted(people):
            user = session.get(User, user_id)
            if user is None or not user.stripe_customer_id:
                continue
            owner_id, evidence, reason = _legacy_owner(session, user)
            considered.append({"user_id": user.id, "processor_customer_id": user.stripe_customer_id,
                               "owner_organization_id": owner_id, "reason": reason, "evidence": evidence})
            if session.execute(select(func.count()).select_from(User).where(
                    User.stripe_customer_id == user.stripe_customer_id, User.id != user.id)).scalar_one():
                _quarantine(codes, "shared_processor_customer", user.id,
                            "one processor customer names several legacy users")
            elif owner_id == organization.id:
                payers.append(user)
            elif owner_id is None and (user.id == organization.owner_user_id or session.execute(
                    select(func.count()).select_from(Payment).where(
                        Payment.user_id == user.id, Payment.organization_id == organization.id)).scalar_one()):
                _quarantine(codes, "payer_unresolved", user.id, reason)
        if len(payers) > 1:
            _quarantine(codes, "several_payers_for_account", organization.id,
                        "a billing account carries one processor customer")
        payer = payers[0] if len(payers) == 1 else None

        conditions = []
        if payer is not None:
            conditions.append(BillingMigrationPayerBinding.payer_user_id == payer.id)
        if account is not None:
            conditions.append(BillingMigrationPayerBinding.billing_account_id == account.id)
        bound = session.execute(select(BillingMigrationPayerBinding).where(or_(*conditions))).scalars().all() \
            if conditions else []
        for binding in bound:
            if payer is None or account is None or binding.payer_user_id != payer.id \
                    or binding.billing_account_id != account.id:
                _quarantine(codes, "payer_binding_conflict", binding.payer_user_id,
                            "a payer and an account are each bound once; this evidence disagrees")
        if account is not None and account.processor_customer_id and (
                payer is None or account.processor != "stripe"
                or account.processor_customer_id != payer.stripe_customer_id):
            _quarantine(codes, "processor_customer_conflict", account.id)

        payments = []
        if payer is not None:
            for payment in session.execute(
                select(Payment).where(Payment.user_id == payer.id).order_by(Payment.id)
            ).scalars():
                payments.append(_payment_record(payment))
                if payment.billing_account_id is not None and (account is None
                                                               or payment.billing_account_id != account.id):
                    _quarantine(codes, "payment_account_conflict", payment.id)
                attributed = session.execute(
                    select(BillingMigrationPaymentAttribution.billing_account_id)
                    .where(BillingMigrationPaymentAttribution.payment_id == payment.id)
                ).scalar_one_or_none()
                if attributed is not None and (account is None or attributed != account.id):
                    _quarantine(codes, "payment_attribution_conflict", payment.id)
        currencies = sorted({p["currency"] for p in payments})
        if len(currencies) > 1:
            _quarantine(codes, "mixed_payment_currencies", organization.id, ",".join(currencies))
        currency, currency_basis = (currencies[0], "payer_payments") if len(currencies) == 1 \
            else (LEGACY_CATALOG_CURRENCY, "legacy_catalog_currency")
        if account is not None and payments and account.currency != currency:
            _quarantine(codes, "account_currency_conflict", account.id)
        anchor = _utc(organization.created_at)
        if anchor is None:
            _quarantine(codes, "organization_created_at_missing", organization.id)
        evidence_doc = {
            "algorithm_version": ALGORITHM_VERSION, "organization_id": organization.id,
            "owner_user_id": organization.owner_user_id, "organization_created_at": _iso(organization.created_at),
            "people": sorted(people), "payers_considered": considered,
            "payer_user_id": payer.id if payer else None,
            "processor_customer_id": payer.stripe_customer_id if payer else None,
            "payments": payments, "currency": currency, "currency_basis": currency_basis,
        }
        return {
            "organization_id": organization.id, "billing_account_id": account.id if account else None, "at": at,
            "payer_user_id": payer.id if payer else None,
            "processor_customer_id": payer.stripe_customer_id if payer else None,
            "payments": payments, "currency": currency, "currency_basis": currency_basis,
            "account_anchor_at": anchor, "quarantine": codes, "evidence": evidence_doc,
            "evidence_fingerprint": _fingerprint(evidence_doc),
        }


def _verified_zero_cycle(session, user, at, account_id):
    """True when a user with no personal value shows a well-formed live legacy cycle with nothing left."""
    if normalize_plan_key(user.subscription_plan) in SHARED_POOL_PLANS or user.credits_remaining not in (0,):
        return False
    fields, error = _meter_evidence(_meter(user.ui_preferences))
    if error or (user.credits_reset_at is not None and _utc(user.credits_reset_at) != _parsed(fields["cycle_reset_at"])):
        return False
    source, error, opening = _recurring_source("user_recurring_meter", user.id, user.id,
                                               normalize_plan_key(user.subscription_plan), fields, None, at, account_id)
    return error is None and opening is None and source.get("classification") == "zero_remaining"


def plan_account_backfill(session, *, billing_account_id, at=None):
    """Pure D16 plan for one organization billing account; writes nothing.

    Returns the holders, every legacy source and its classification, the
    planned openings, quarantine codes, legacy totals for the conservation
    equation, money evidence by currency, the owner map and the evidence-backed
    zero cycles for the Phase 13 comparison, and the evidence fingerprint.
    """
    with session.no_autoflush:
        unit = verify_credit_unit_equivalence()
        account = session.get(BillingAccount, billing_account_id) if billing_account_id else None
        if account is None:
            raise MigrationError("billing account does not exist")
        organization = session.get(Organization, account.organization_id)
        at = _database_clock(session) if at is None else _utc(at)
        codes, sources, openings = [], [], []
        owners, owned_elsewhere, holders, zero_cycles = {}, [], [], set()
        if account.status == "closed":
            _quarantine(codes, "billing_account_closed", account.id)

        # D16 step 1 comes first: the account, its payer, and its payments must be established from evidence.
        _established(session, organization, account, at, codes)

        active = {m.user_id for m in _members(session, organization.id, active_only=True)}
        candidates = {m.user_id for m in _members(session, organization.id, active_only=False)}
        if account.processor == "stripe" and account.processor_customer_id:
            candidates |= set(session.execute(
                select(User.id).where(User.stripe_customer_id == account.processor_customer_id)).scalars())
        candidates |= {uid for uid in session.execute(
            select(Payment.user_id).where(Payment.billing_account_id == account.id, Payment.user_id.is_not(None))
        ).scalars()}
        users = [session.get(User, uid) for uid in sorted(candidates)]

        # Enterprise (D16): only an executed, organization-owned contract is evidence.
        contract_state = project_billing_account(session, billing_account_id=account.id, at=at)["contract_access"]["state"]
        sales_led = normalize_plan_key(organization.plan_key) in SALES_LED_PLANS or any(
            normalize_plan_key(u.subscription_plan) in SALES_LED_PLANS for u in users if u.id in active)
        if sales_led and contract_state == "none":
            _quarantine(codes, "enterprise_without_contract", organization.id,
                        "a plan label or null balance is not Enterprise evidence")

        holder_evidence = {}
        for user in users:
            if not _user_has_personal_value(session, user):
                continue
            owner = resolve_legacy_value_owner(session, user)
            owners[user.id] = owner["organization_id"]
            if owner["organization_id"] is None:
                _quarantine(codes, "ambiguous_owner", user.id, owner["reason"])
                continue
            if owner["organization_id"] != organization.id:
                owned_elsewhere.append({"user_id": user.id, "organization_id": owner["organization_id"],
                                        "reason": owner["reason"]})
                continue
            evidence = _holder_evidence(session, user)
            evidence["owner"] = owner
            holder_evidence[user.id] = evidence
            holders.append(user.id)
            if user.id not in active:
                _quarantine(codes, "attributed_member_not_active", user.id,
                            "member-attributed value would be unspendable; reinstate or review the owner")

        # Personal recurring meters (users on a non-pooled plan).
        for user in users:
            evidence = holder_evidence.get(user.id)
            if evidence is None:
                zero = _verified_zero_cycle(session, user, at, account.id)
                if zero:
                    # No value to own or open; recorded so Phase 13 can match a verified empty live cycle.
                    zero_cycles.add(("users.ui_preferences.thinking_power.remaining", user.id))
                continue
            if evidence["shared_pool_plan"]:
                continue  # Pooled and sales-led plans meter the organization, not the user.
            meter = _meter(user.ui_preferences)
            fields, error = _meter_evidence(meter)
            if error == "legacy_meter_absent":
                persistent = sum(g["remaining_amount"] for g in evidence["grants"] if g["status"] == "active")
                if user.credits_remaining is None:
                    _quarantine(codes, "null_legacy_balance", user.id)
                elif user.credits_remaining != persistent:
                    # Only the part of the counter that proven persistent value does not explain is unevidenced.
                    _quarantine(codes, "legacy_meter_absent", user.id,
                                "a counter without a meter has no evidence of its unit or terms")
                continue
            if not error and user.credits_reset_at is not None and \
                    _utc(user.credits_reset_at) != _parsed(fields["cycle_reset_at"]):
                error = "reset_date_conflict"
            source, error, opening = _recurring_source(
                "user_recurring_meter", user.id, user.id, evidence["plan"], fields, error, at, account.id)
            sources.append(source)
            if error:
                _quarantine(codes, error, user.id)
            elif opening:
                openings.append(opening)
            elif source.get("classification") == "zero_remaining":
                zero_cycles.add(("users.ui_preferences.thinking_power.remaining", user.id))

        # The organization pool, metered only while an active member is on a pooled plan.
        pool_members = [u for u in users if u.id in active and normalize_plan_key(u.subscription_plan) in SHARED_POOL_PLANS]
        pool_evidence = None
        org_meter = _meter(organization.settings)
        if pool_members and org_meter is not None:
            fields, error = _meter_evidence(org_meter)
            pool_plans = sorted({normalize_plan_key(u.subscription_plan) for u in pool_members})
            pool_evidence = {"organization_id": organization.id, "plans": pool_plans, "meter": fields}
            if sales_led:
                if (_int_or_none(org_meter.get("remaining")) or 0) != 0:
                    _quarantine(codes, "enterprise_pool_meter_value", organization.id)
            else:
                source, error, opening = _recurring_source(
                    "organization_recurring_meter", organization.id, None, "pooled", fields, error, at, account.id)
                sources.append(source)
                if error:
                    _quarantine(codes, error, organization.id)
                elif opening:
                    openings.append(opening)
                elif source.get("classification") == "zero_remaining":
                    zero_cycles.add(("organizations.settings.thinking_power.remaining", organization.id))

        # Persistent grants (purchased or promotional, member-attributed), original terms preserved.
        for user in users:
            evidence = holder_evidence.get(user.id)
            if evidence is None:
                continue
            for grant in evidence["grants"]:
                source, grant_codes, opening = _grant_source(grant, user, account, organization, at)
                sources.append(source)
                for code in grant_codes:
                    _quarantine(codes, code, grant["grant_id"])
                if opening:
                    openings.append(opening)

        # Combined counter above all evidence: reviewed legacy_unattributed only (D16 step 7).
        for user in users:
            evidence = holder_evidence.get(user.id)
            if evidence is None or evidence["shared_pool_plan"] or user.credits_remaining is None:
                continue
            live = sum(o["opening_amount"] for o in openings if o["legacy_source_kind"] == "user_recurring_meter"
                       and o["member_attribution_id"] == user.id)
            lapsed = sum(s.get("expired_amount", 0) for s in sources if s["kind"] == "user_recurring_meter"
                         and s["member_attribution_id"] == user.id
                         and s.get("classification") == "expired_recurring_value")
            persistent = sum(g["remaining_amount"] for g in evidence["grants"] if g["status"] == "active")
            # Net of the lapsed remainder: expired value explains part of the counter and is never opened.
            difference = int(user.credits_remaining) - live - lapsed - persistent
            evidence["unexplained_difference"] = difference
            if difference > 0:
                review = _review_for(session, account.id, user.id, holder_fingerprint(evidence), difference)
                if review is not None:
                    openings.append({
                        "opening_key": f"migration-opening:{account.id}:reviewed_unattributed:{review.id}",
                        "legacy_source_kind": "reviewed_unattributed", "legacy_source_id": review.id,
                        "lot_source_type": "legacy_unattributed", "member_attribution_id": user.id,
                        "original_amount": difference, "opening_amount": difference,
                        "available_at": _utc(review.reviewed_at), "expires_at": _utc(review.expires_at),
                        "expiry_basis": review.expiry_basis, "evidence_rank": 6, "review_id": review.id,
                        "reviewer_user_id": review.reviewer_user_id,
                        "expiry_evidence": review.expiry_evidence_reference,
                    })
                    sources.append({"kind": "reviewed_unattributed", "legacy_source_id": review.id,
                                    "member_attribution_id": user.id, "classification": "reviewed",
                                    "amount": difference})

        # B1: a legacy source opened in another billing account is never opened again.
        for opening in list(openings):
            elsewhere = _opened_elsewhere(session, opening["legacy_source_kind"], opening["legacy_source_id"],
                                          account.id)
            if elsewhere is not None:
                openings.remove(opening)
                _quarantine(codes, "legacy_source_opened_elsewhere", opening["legacy_source_id"],
                            f"already opened in billing account {elsewhere}")

        reported_operations = _legacy_operation_findings(session, active | set(holders), at, codes)

        holder_fps = {uid: holder_fingerprint(e) for uid, e in holder_evidence.items()}
        for opening in openings:
            if opening["legacy_source_kind"] == "organization_recurring_meter":
                opening["source_fingerprint"] = _fingerprint(pool_evidence)
            elif opening["legacy_source_kind"] == "persistent_credit_grant":
                grant = next(g for g in holder_evidence[opening["member_attribution_id"]]["grants"]
                             if g["grant_id"] == opening["legacy_source_id"])
                opening["source_fingerprint"] = _fingerprint(grant)
            else:
                opening["source_fingerprint"] = holder_fps[opening["member_attribution_id"]]

        money = defaultdict(lambda: {"payments": 0, "amount_paid_cents": 0, "amount_due_cents": 0, "discount_cents": 0})
        for evidence in holder_evidence.values():
            for grant in evidence["grants"]:
                payment = grant["payment"]
                if payment is not None:
                    row = money[payment["currency"]]
                    row["payments"] += 1
                    for column in ("amount_paid_cents", "amount_due_cents", "discount_cents"):
                        row[column] += payment[column]

        accepted = {
            "recurring_remaining": sum(o["opening_amount"] for o in openings if o["legacy_source_kind"] in RECURRING_KINDS),
            "persistent_remaining": sum(o["opening_amount"] for o in openings
                                        if o["legacy_source_kind"] == "persistent_credit_grant"),
            "approved_adjustments": sum(o["opening_amount"] for o in openings
                                        if o["legacy_source_kind"] == "reviewed_unattributed"),
        }
        # The fingerprint covers the evidence only (legacy rows and their pinned attribution), never the
        # snapshot time or the run.
        evidence_doc = {
            "billing_account_id": account.id, "organization_id": organization.id,
            "algorithm_version": ALGORITHM_VERSION, "expiry_policy": EXPIRY_POLICY,
            "holders": [holder_evidence[uid] for uid in sorted(holder_evidence)],
            "pool": pool_evidence, "owned_elsewhere": owned_elsewhere,
            "candidates": sorted(candidates), "active_members": sorted(active),
        }
        if reported_operations:
            # BI-1: unclosed operations that do not block (already charged, or cleared by a recorded
            # decision). Present only when there are any, so every other plan's fingerprint is unchanged.
            evidence_doc["unclosed_operations"] = sorted(reported_operations, key=lambda o: o["operation_id"])
        return {
            "billing_account_id": account.id, "organization_id": organization.id, "at": at, "unit": unit,
            "holders": sorted(holders), "owners": owners, "owned_elsewhere": owned_elsewhere,
            "zero_cycles": sorted(zero_cycles),
            "sources": sources, "openings": sorted(openings, key=lambda o: o["opening_key"]),
            "quarantine": codes, "accepted": accepted, "money_by_currency": dict(money),
            "legacy_usage_history": _legacy_usage_history(session, set(holders)),
            "contract_state": contract_state, "evidence": evidence_doc,
            "evidence_fingerprint": _fingerprint(evidence_doc),
        }


def holder_fingerprint(evidence):
    """Fingerprint of one holder's legacy evidence (counter, meter, reset dates, grants, payments)."""
    return _fingerprint({k: v for k, v in evidence.items() if k not in ("owner", "unexplained_difference")})


# ---------------------------------------------------------------------------
# Conservation (D16) and the Phase 13 comparison
# ---------------------------------------------------------------------------

def _conservation(session, account_id, at, plan):
    balances = _lot_balances(session, account_id)
    open_total = sum(available + held for lot, available, held in balances if _open_at(lot, at))
    accepted = plan["accepted"]
    expected = accepted["recurring_remaining"] + accepted["persistent_remaining"] + accepted["approved_adjustments"]
    migration_lots = {
        row.lot_id: row for row in session.execute(
            select(BillingMigrationOpening).where(BillingMigrationOpening.billing_account_id == account_id)
        ).scalars()
    }
    purchased = {}
    principal_exact = True
    for lot, _available, _held in balances:
        opening = migration_lots.get(lot.id)
        if opening is not None and opening.legacy_source_kind == "persistent_credit_grant":
            grant = session.get(PersistentCreditGrant, opening.legacy_source_id)
            purchased[opening.legacy_source_id] = {"target_original": int(lot.original_amount),
                                                   "legacy_original": int(grant.original_amount)}
            principal_exact = principal_exact and int(lot.original_amount) == int(grant.original_amount)
    pre_existing = sorted(lot.id for lot, available, held in balances
                          if lot.id not in migration_lots and _open_at(lot, at) and available + held > 0)
    # D16 usage equation: settled usage by operation equals the bound operations' recorded charges.
    # Legacy (unbound) usage is reported, never re-ledgered as settlements.
    bound = {operation_id: int(charged or 0) for operation_id, charged in session.execute(
        select(AIOperation.id, AIOperation.charged_credits).where(AIOperation.billing_account_id == account_id))}
    settled = _settled_by_operation(session, account_id, sorted(bound))
    usage_exact = all(settled.get(operation_id, 0) == charged for operation_id, charged in bound.items()) and \
        set(settled) <= set(bound)
    return {
        "target_available_plus_held": open_total,
        "accepted_legacy_recurring_remaining": accepted["recurring_remaining"],
        "accepted_legacy_persistent_remaining": accepted["persistent_remaining"],
        "approved_migration_adjustments": accepted["approved_adjustments"],
        "balance_exact": open_total == expected,
        "purchased_principal_by_source": purchased,
        "purchased_principal_exact": principal_exact,
        "pre_existing_target_lots": pre_existing,
        "settled_usage_by_operation": settled,
        "settled_usage_exact": usage_exact,
        "legacy_usage_history": plan["legacy_usage_history"],
        "money_by_currency": plan["money_by_currency"],
    }


def _credit_findings(report):
    codes = []
    for item in report["comparisons"]:
        if item["field"] in CREDIT_FIELDS and item["classification"] == UNRESOLVED:
            codes.append({"code": f"comparison:{item['field']}:{item['special_case'] or 'unresolved'}",
                          "subject": item["subject"], "detail": item["detail"]})
    for flag in report["flags"]:
        if flag["blocks_cutover"]:
            codes.append({"code": f"flag:{flag['code']}", "subject": report["billing_account_id"],
                          "detail": flag["detail"]})
    return codes


def _comparison_summary(report):
    return {
        "projection_version": report["projection_version"], "as_of": report["as_of"],
        "summary": report["summary"], "blocked": report["blocked"],
        "flags": report["flags"], "not_applicable": report["not_applicable"],
        "unresolved": [item for item in report["comparisons"] if item["classification"] == UNRESOLVED],
        "credit_fields_matched": sum(1 for item in report["comparisons"]
                                     if item["field"] in CREDIT_FIELDS and item["classification"] == MATCH),
    }


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def start_migration_run(session, *, run_key, authorization_reference, actor_type, actor_id, operator_user_id):
    """Record one controlled run under the founder-approved expiry policy (original terms).

    ``operator_user_id`` is the internal person executing the run; no review
    they approved can be consumed by it. The run refuses to start while Gate 1
    fails or an approved pricing version states its provider-dollar rate in
    anything but internal units. Returns ``(run, 'inserted'|'duplicate')``.
    The caller owns the transaction.
    """
    actor_type, actor_id = _system(actor_type, actor_id)
    run_key = _text(run_key, "run_key", 128)
    authorization_reference = _text(authorization_reference, "authorization_reference", 255)
    operator_user_id = _text(operator_user_id, "operator_user_id", 36)
    if session.get(User, operator_user_id) is None:
        raise MigrationPermissionError("the run operator must be an identified internal user")
    unit = verify_credit_unit_equivalence()
    pricing = pricing_unit_findings(session)
    if pricing:
        raise MigrationUnitError(f"approved pricing must state {INTERNAL_UNITS_PER_PROVIDER_USD} internal units per "
                                 f"provider dollar: {pricing}")
    now = _database_now(session)
    fingerprint = _fingerprint({"run_key": run_key, "authorization_reference": authorization_reference,
                                "actor_type": actor_type, "actor_id": actor_id, "operator_user_id": operator_user_id,
                                "expiry_policy": EXPIRY_POLICY, "unit": unit, "algorithm_version": ALGORITHM_VERSION})
    registry, inserted = _claim(session, RUN_NAMESPACE, run_key, fingerprint, now)
    if not inserted:
        run = session.execute(
            select(BillingMigrationRun).where(BillingMigrationRun.idempotency_registry_id == registry.id)
        ).scalar_one_or_none()
        if registry.state != "completed" or run is None:
            raise MigrationRetryError("the migration run is already being recorded")
        return run, "duplicate"
    run = BillingMigrationRun(
        id=str(uuid.uuid4()), run_key=run_key, algorithm_version=ALGORITHM_VERSION,
        credit_unit_basis=CREDIT_UNIT_BASIS, units_per_displayed_credit=UNITS_PER_DISPLAYED_CREDIT,
        expiry_policy=EXPIRY_POLICY, authorization_reference=authorization_reference,
        actor_type=actor_type, actor_id=actor_id, operator_user_id=operator_user_id, request_fingerprint=fingerprint,
        idempotency_registry_id=registry.id, started_at=now,
    )
    session.add(run)
    session.flush()
    _complete(session, registry, now, "billing_migration_run", run.id)
    return run, "inserted"


def _run(session, run_id):
    run = session.get(BillingMigrationRun, run_id) if run_id else None
    if run is None:
        raise MigrationError("migration run does not exist")
    return run


def _lock_organization_sources(session, organization_id):
    """Hold the legacy rows an organization's evidence is read from until commit (consistent snapshot).

    PostgreSQL ``FOR SHARE`` blocks a concurrent legacy writer from changing a
    member, counter, meter, grant, or payment between the read and the commit;
    SQLite already holds its single write lock. The members' processor-customer
    peers and payments are included, so a payer cannot move mid-command.
    """
    session.execute(select(Organization.id).where(Organization.id == organization_id)
                    .with_for_update(read=True)).all()
    members = select(OrganizationMember.user_id).where(OrganizationMember.organization_id == organization_id)
    owner = select(Organization.owner_user_id).where(Organization.id == organization_id)
    users = session.execute(select(User.id).where(or_(User.id.in_(members), User.id.in_(owner))).order_by(User.id)
                            .with_for_update(read=True)).scalars().all()
    session.execute(select(PersistentCreditGrant.id).where(PersistentCreditGrant.user_id.in_(users))
                    .order_by(PersistentCreditGrant.id).with_for_update(read=True)).all()
    session.execute(select(Payment.id).where(Payment.user_id.in_(users))
                    .order_by(Payment.id).with_for_update(read=True)).all()


def establish_billing_account(session, *, run_id, organization_id):
    """D16 step 1 for one organization inside the caller's transaction.

    Outcomes: ``established`` (the billing account exists, created
    ``proposed`` when absent; its payer's processor customer and every legacy
    payment of that payer are bound to it, each globally unique),
    ``unchanged`` (already established from the same evidence; nothing
    written), or ``quarantined`` (nothing bound; the codes say why). Changed
    evidence after establishment quarantines and never moves a binding.
    Returns ``(establishment, 'inserted'|'duplicate')``.
    """
    _read_committed(session)
    run = _run(session, run_id)
    organization_id = _text(organization_id, "organization_id", 36)
    if session.execute(select(Organization.id).where(Organization.id == organization_id)
                       .with_for_update()).scalar_one_or_none() is None:
        raise MigrationError("organization does not exist")
    _lock_organization_sources(session, organization_id)
    at = _database_clock(session)
    plan = plan_establishment(session, organization_id=organization_id, at=at)
    registry, inserted = _claim(session, ESTABLISHMENT_NAMESPACE, f"{run.id}:{organization_id}",
                                plan["evidence_fingerprint"], at)
    if not inserted:
        row = session.execute(
            select(BillingMigrationEstablishment).where(
                BillingMigrationEstablishment.idempotency_registry_id == registry.id)
        ).scalar_one_or_none()
        if registry.state != "completed" or row is None:
            raise MigrationRetryError("this organization is already being established in this run")
        return row, "duplicate"

    codes = list(plan["quarantine"])
    latest = _latest_establishment(session, organization_id)
    established_before = latest is not None and latest.outcome in ("established", "unchanged")
    if established_before and latest.evidence_fingerprint != plan["evidence_fingerprint"]:
        _quarantine(codes, "evidence_changed_since_establishment", organization_id,
                    "a payer or payment binding is permanent; changed evidence is reviewed, never re-bound")

    def record(outcome, account_id, created):
        row = BillingMigrationEstablishment(
            id=str(uuid.uuid4()), run_id=run.id, organization_id=organization_id, billing_account_id=account_id,
            outcome=outcome, account_created=created, evidence_fingerprint=plan["evidence_fingerprint"],
            evidence_json={**plan["evidence"], "account_anchor_at": _iso(plan["account_anchor_at"])},
            quarantine_codes_json=codes, idempotency_registry_id=registry.id,
        )
        session.add(row)
        session.flush()
        return row

    if codes or established_before:
        row = record("quarantined" if codes else "unchanged", plan["billing_account_id"], False)
        _complete(session, registry, at, "billing_migration_establishment", row.id)
        return row, "inserted"

    account = _account_for(session, organization_id)
    created = account is None
    try:
        if created:
            account = BillingAccount(
                id=str(uuid.uuid4()), organization_id=organization_id, status="proposed",
                currency=plan["currency"], account_anchor_at=plan["account_anchor_at"],
            )
            session.add(account)
            session.flush()
        row = record("established", account.id, created)
        if plan["payer_user_id"] is not None:
            assigned = account.processor_customer_id is None
            if assigned:
                account.processor = "stripe"
                account.processor_customer_id = plan["processor_customer_id"]
                session.flush()
            binding = BillingMigrationPayerBinding(
                id=str(uuid.uuid4()), establishment_id=row.id, billing_account_id=account.id,
                payer_user_id=plan["payer_user_id"], processor="stripe",
                processor_customer_id=plan["processor_customer_id"], customer_assigned_by_migration=assigned,
                evidence_json={"payers_considered": plan["evidence"]["payers_considered"]},
            )
            session.add(binding)
            session.flush()
            for payment in plan["payments"]:
                session.add(BillingMigrationPaymentAttribution(
                    id=str(uuid.uuid4()), establishment_id=row.id, payer_binding_id=binding.id,
                    billing_account_id=account.id, payment_id=payment["payment_id"],
                    external_reference=payment["external_reference"], source=payment["source"],
                    currency=payment["currency"], amount_paid_cents=payment["amount_paid_cents"],
                    amount_due_cents=payment["amount_due_cents"], discount_cents=payment["discount_cents"],
                    is_comped=payment["is_comped"],
                ))
            session.flush()
    except IntegrityError as exc:
        # A concurrent command bound this account, payer, customer, or payment first.
        raise MigrationRetryError("a concurrent establishment holds this evidence; retry the transaction") from exc
    _complete(session, registry, at, "billing_migration_establishment", row.id)
    return row, "inserted"


def _lock_legacy_sources(session, account):
    _lock_organization_sources(session, account.organization_id)


def _existing_openings(session, account_id):
    return session.execute(
        select(BillingMigrationOpening).where(BillingMigrationOpening.billing_account_id == account_id)
        .order_by(BillingMigrationOpening.opening_key)
    ).scalars().all()


def _last_opened_fingerprint(session, account_id):
    return session.execute(
        select(BillingMigrationAccountResult.evidence_fingerprint).where(
            BillingMigrationAccountResult.billing_account_id == account_id,
            BillingMigrationAccountResult.outcome == "opened",
        ).order_by(BillingMigrationAccountResult.created_at.desc(), BillingMigrationAccountResult.id.desc()).limit(1)
    ).scalar_one_or_none()


class _SourceAlreadyOpened(MigrationError):
    """The global one-opening-per-legacy-source rule refused an opening (a concurrent account opened it)."""


def _source_uniqueness_violation(exc):
    text = str(getattr(exc, "orig", exc))
    return "uq_billing_migration_openings_source" in text or (
        "UNIQUE constraint failed" in text and "billing_migration_openings.legacy_source_kind" in text)


def _write_openings(session, run, result, plan, at):
    for planned in plan["openings"]:
        opening_id, lot_id, entry_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
        registry, inserted = _claim(session, OPENING_NAMESPACE, planned["opening_key"],
                                    planned["source_fingerprint"], at)
        if not inserted:
            raise MigrationConflictError("a migration opening identity is already claimed")
        evidence = {
            "run_id": run.id, "evidence_rank": planned["evidence_rank"],
            "calculation": {"original_amount": planned["original_amount"],
                            "opening_amount": planned["opening_amount"],
                            "available_at": _iso(planned["available_at"]), "expires_at": _iso(planned["expires_at"])},
            "expiry_policy": EXPIRY_POLICY, "expiry_basis": planned["expiry_basis"],
            "expiry_evidence": planned["expiry_evidence"],
            "unit": plan["unit"]["credit_unit_basis"],
        }
        try:
            session.add(BillingMigrationOpening(
                id=opening_id, run_id=run.id, account_result_id=result.id,
                billing_account_id=plan["billing_account_id"],
                opening_key=planned["opening_key"], legacy_source_kind=planned["legacy_source_kind"],
                legacy_source_id=planned["legacy_source_id"], lot_id=lot_id, ledger_entry_id=entry_id,
                idempotency_registry_id=registry.id, lot_source_type=planned["lot_source_type"],
                member_attribution_id=planned["member_attribution_id"], original_amount=planned["original_amount"],
                opening_amount=planned["opening_amount"], available_at=planned["available_at"],
                expires_at=planned["expires_at"], expiry_basis=planned["expiry_basis"], effective_at=at,
                evidence_rank=planned["evidence_rank"], source_fingerprint=planned["source_fingerprint"],
                evidence_json=evidence, review_id=planned["review_id"],
            ))
            session.flush()
        except IntegrityError as exc:
            if _source_uniqueness_violation(exc):
                raise _SourceAlreadyOpened(planned["legacy_source_id"]) from exc
            raise
        session.add(CreditLot(
            id=lot_id, billing_account_id=plan["billing_account_id"], source_type=planned["lot_source_type"],
            # eligibility_scope is left unset: SQL NULL (an explicit None would store JSON null).
            source_id=opening_id, member_attribution_id=planned["member_attribution_id"],
            original_amount=planned["original_amount"], available_at=planned["available_at"],
            expires_at=planned["expires_at"],
            origin_evidence_json={"phase": 14, "migration_opening_id": opening_id, "run_id": run.id,
                                  "legacy_source_kind": planned["legacy_source_kind"],
                                  "legacy_source_id": planned["legacy_source_id"]},
        ))
        session.flush()
        try:
            append_entry(session, CreditLedgerEntry(
                id=entry_id, billing_account_id=plan["billing_account_id"], lot_id=lot_id,
                entry_type="migration_opening", available_delta=planned["opening_amount"], held_delta=0,
                idempotency_registry_id=registry.id, effective_at=at, actor_type=run.actor_type,
                actor_id=run.actor_id, reason_code="legacy_migration_opening",
                evidence_json={"migration_opening_id": opening_id, "run_id": run.id,
                               "source_fingerprint": planned["source_fingerprint"]},
            ))
        except CreditLedgerInvariantError as exc:
            raise MigrationError(str(exc)) from exc
        _complete(session, registry, at, "billing_migration_opening", opening_id)


def backfill_billing_account(session, *, run_id, billing_account_id):
    """Apply the D16 opening balance for one established billing account inside the caller's transaction.

    Returns ``(result, 'inserted'|'duplicate')``. Outcomes: ``opened`` (new
    ``migration_opening`` lots, conservation exact, credit fields reconciled),
    ``unchanged`` (already opened from the same evidence, or nothing to open;
    zero new entries), or ``quarantined`` (nothing opened; the codes say why).
    A legacy source already opened in any other account quarantines; the
    database refuses a second opening even under concurrency.
    ``cutover_eligible`` additionally requires the whole Phase 13 comparison
    to be unblocked.
    """
    _read_committed(session)
    run = _run(session, run_id)
    account = _lock_account(session, billing_account_id)
    _lock_legacy_sources(session, account)
    at = _database_clock(session)
    plan = plan_account_backfill(session, billing_account_id=account.id, at=at)
    key = f"{run.id}:{account.id}"
    registry, inserted = _claim(session, RESULT_NAMESPACE, key, plan["evidence_fingerprint"], at)
    if not inserted:
        result = session.execute(
            select(BillingMigrationAccountResult).where(
                BillingMigrationAccountResult.idempotency_registry_id == registry.id)
        ).scalar_one_or_none()
        if registry.state != "completed" or result is None:
            raise MigrationRetryError("this account is already being migrated in this run")
        return result, "duplicate"

    codes = list(plan["quarantine"])
    for opening in plan["openings"]:
        if opening.get("reviewer_user_id") == run.operator_user_id:
            _quarantine(codes, "reviewer_is_run_operator", opening["review_id"],
                        "the operator of a run cannot consume a review they approved")
    existing = _existing_openings(session, account.id)
    if existing:
        planned = {o["opening_key"]: o for o in plan["openings"]}
        changed = [o.opening_key for o in existing
                   if o.opening_key in planned and planned[o.opening_key]["source_fingerprint"] != o.source_fingerprint]
        if changed or _last_opened_fingerprint(session, account.id) != plan["evidence_fingerprint"]:
            _quarantine(codes, "evidence_changed_since_opening", account.id,
                        "the legacy evidence differs from the evidence these openings were made from")

    def build(outcome, conservation, report, final_codes, reconciled, eligible, reason):
        opened = plan["openings"] if outcome == "opened" else []
        return BillingMigrationAccountResult(
            id=str(uuid.uuid4()), run_id=run.id, billing_account_id=account.id,
            organization_id=plan["organization_id"], outcome=outcome, snapshot_at=at,
            evidence_fingerprint=plan["evidence_fingerprint"],
            evidence_json={**plan["evidence"], "sources": plan["sources"], "unit": plan["unit"],
                           "contract_state": plan["contract_state"], "owners": plan["owners"],
                           "zero_cycles": plan["zero_cycles"], "decision_reason": reason},
            quarantine_codes_json=final_codes, conservation_json=conservation,
            comparison_json=_comparison_summary(report) if report is not None else {},
            opened_count=len(opened), opened_total=sum(o["opening_amount"] for o in opened),
            credit_reconciled=reconciled, cutover_eligible=eligible, idempotency_registry_id=registry.id,
        )

    def check():
        conservation = _conservation(session, account.id, at, plan)
        report = compare_legacy_compatibility(session, billing_account_id=account.id, at=at,
                                              value_owners=plan["owners"], zero_cycles=plan["zero_cycles"])
        findings = _credit_findings(report)
        if not conservation["balance_exact"]:
            findings.append({"code": "conservation_mismatch", "subject": account.id,
                             "detail": "target available + held must equal accepted legacy value exactly"})
        if not conservation["purchased_principal_exact"]:
            findings.append({"code": "purchased_principal_mismatch", "subject": account.id, "detail": None})
        if not conservation["settled_usage_exact"]:
            findings.append({"code": "settled_usage_mismatch", "subject": account.id, "detail": None})
        return conservation, report, findings

    def record(result):
        session.add(result)
        session.flush()
        _complete(session, registry, at, "billing_migration_account_result", result.id)
        return result, "inserted"

    if codes or existing or not plan["openings"]:
        # Nothing new may be opened: record the reconciliation of what the ledger already holds.
        conservation, report, findings = check()
        final = codes or findings
        reason = "quarantined" if final else ("already_opened" if existing else "nothing_to_open")
        return record(build("quarantined" if final else "unchanged", conservation, report, final, not final,
                            not final and not report["blocked"], reason))

    # Probe: write the openings, reconcile them exactly, then always roll the probe back.
    taken = None
    probe = session.begin_nested()
    try:
        provisional = build("opened", {}, None, [], True, False, "probe")
        session.add(provisional)
        session.flush()
        try:
            _write_openings(session, run, provisional, plan, at)
            conservation, report, findings = check()
        except _SourceAlreadyOpened as exc:
            taken = str(exc)
    finally:
        probe.rollback()
    if taken is not None:
        conservation, report, _findings = check()
        final = [{"code": "legacy_source_opened_elsewhere", "subject": taken,
                  "detail": "a concurrent command opened this legacy source in another account"}]
        return record(build("quarantined", conservation, report, final, False, False, "quarantined"))
    if findings:
        return record(build("quarantined", conservation, report, findings, False, False, "quarantined"))
    result = build("opened", conservation, report, [], True, not report["blocked"], "opened")
    session.add(result)
    session.flush()
    try:
        _write_openings(session, run, result, plan, at)
    except _SourceAlreadyOpened as exc:
        raise MigrationRetryError("a concurrent command opened a legacy source; retry the transaction") from exc
    confirmed, _report, confirmed_findings = check()
    if confirmed_findings or confirmed != conservation:
        raise MigrationError("the opening balance did not reproduce its reconciled probe")
    _complete(session, registry, at, "billing_migration_account_result", result.id)
    return result, "inserted"


def _non_expiring_purchase(session, account_id, subject_user_id, payment_id):
    """A real non-expiring legacy purchase of the subject, attributed here, that funds no grant of its own."""
    payment = session.get(Payment, payment_id) if isinstance(payment_id, str) and payment_id else None
    sources = {PAYMENT_SOURCES[source] for source in NON_EXPIRING_LEGACY_CONTRACTS}
    if payment is None or payment.user_id != subject_user_id or payment.source not in sources:
        raise MigrationError("a non-expiring review needs a non-expiring legacy purchase by the subject")
    attributed = session.execute(
        select(BillingMigrationPaymentAttribution.billing_account_id)
        .where(BillingMigrationPaymentAttribution.payment_id == payment.id)
    ).scalar_one_or_none()
    if attributed != account_id:
        raise MigrationError("the purchase evidence must be attributed to this billing account")
    if session.execute(select(func.count()).select_from(PersistentCreditGrant).where(
            PersistentCreditGrant.external_reference.in_(
                [prefix + payment.external_reference for prefix in GRANT_PREFIXES.values()]))).scalar_one():
        raise MigrationError("the purchase already funds a persistent grant; it cannot also fund a review")
    if session.execute(select(func.count()).select_from(BillingMigrationReview).where(
            BillingMigrationReview.expiry_evidence_payment_id == payment.id)).scalar_one():
        raise MigrationConflictError("the purchase is already the evidence of another review")
    return payment


def record_unattributed_review(
    session, *, review_command_id, billing_account_id, subject_user_id, amount, expiry_basis,
    expiry_evidence_reference, candidates_considered, reason, reviewer_user_id, expiry_evidence_payment_id=None,
):
    """Record the documented reconciliation review that permits one ``legacy_unattributed`` opening.

    Separation of duties: the reviewer needs an explicit, unrevoked
    ``billing.migration.review`` staff grant valid now, and may be neither the
    subject, a member or owner of the beneficiary organization, nor its bound
    payer; a run never consumes a review its own operator approved. The amount
    must equal the subject's current unexplained combined-counter difference
    (net of a lapsed cycle) exactly, and the review binds the fingerprint of
    that evidence; one review per evidence, so a conflicting second approval
    is refused. Expiry is never chosen: ``legacy_cycle_end`` takes the end of
    the subject's live legacy cycle; ``non_expiring_legacy_contract`` needs a
    real non-expiring purchase of the subject, attributed to this account,
    that funds no grant. Returns ``(review, 'inserted'|'duplicate')``.
    """
    _read_committed(session)
    command_id = _text(review_command_id, "review_command_id", 128)
    reason = _text(reason, "reason", 4000)
    expiry_evidence_reference = _text(expiry_evidence_reference, "expiry_evidence_reference", 255)
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise MigrationError("amount must be a positive integer of legacy internal units")
    if not isinstance(candidates_considered, (list, tuple)) or not candidates_considered:
        raise MigrationError("the review must list the candidates considered")
    if expiry_basis not in ("legacy_cycle_end", "non_expiring_legacy_contract"):
        raise MigrationError("the expiry basis must be the legacy cycle end or a non-expiring legacy contract")
    if subject_user_id == reviewer_user_id:
        raise MigrationPermissionError("a reviewer cannot review their own legacy value")
    account = _lock_account(session, billing_account_id)
    now = _database_now(session)
    grant = _authorized_grant(session, user_id=reviewer_user_id, permission=REVIEW_PERMISSION, started_at=now)
    if grant is None:
        raise MigrationPermissionError("the reviewer does not hold the explicit migration review permission")
    organization = session.get(Organization, account.organization_id)
    if reviewer_user_id == organization.owner_user_id or reviewer_user_id in {
            m.user_id for m in _members(session, organization.id, active_only=False)}:
        raise MigrationPermissionError("a member or owner of the beneficiary organization cannot approve its value")
    if session.execute(select(func.count()).select_from(BillingMigrationPayerBinding).where(
            BillingMigrationPayerBinding.billing_account_id == account.id,
            BillingMigrationPayerBinding.payer_user_id == reviewer_user_id)).scalar_one():
        raise MigrationPermissionError("the beneficiary account's payer cannot approve its value")
    plan = plan_account_backfill(session, billing_account_id=account.id)
    evidence = next((h for h in plan["evidence"]["holders"] if h["user_id"] == subject_user_id), None)
    if evidence is None:
        raise MigrationError("the subject holds no legacy value owned by this billing account")
    if evidence["shared_pool_plan"] or evidence.get("unexplained_difference") != amount:
        raise MigrationError("the review amount must equal the subject's unexplained difference exactly")
    if expiry_basis == "legacy_cycle_end":
        if expiry_evidence_payment_id is not None:
            raise MigrationError("a cycle-end review takes no purchase evidence")
        live = [s for s in plan["sources"] if s["kind"] == "user_recurring_meter"
                and s["member_attribution_id"] == subject_user_id
                and s.get("classification") in ("live_cycle", "zero_remaining")]
        if len(live) != 1:
            raise MigrationError("no live legacy cycle establishes this amount's expiry; the quarantine stands")
        expires_at = _parsed(live[0]["cycle_ends_at"])
    else:
        expiry_evidence_payment_id = _non_expiring_purchase(
            session, account.id, subject_user_id, expiry_evidence_payment_id).id
        expires_at = None
    fingerprint = holder_fingerprint(evidence)
    key = f"migration-review:{command_id}"
    request = _fingerprint({"billing_account_id": account.id, "subject_user_id": subject_user_id, "amount": amount,
                            "expiry_basis": expiry_basis, "expires_at": _iso(expires_at),
                            "expiry_evidence_payment_id": expiry_evidence_payment_id,
                            "expiry_evidence_reference": expiry_evidence_reference,
                            "candidates": list(candidates_considered), "reason": reason,
                            "reviewer_user_id": reviewer_user_id, "evidence_fingerprint": fingerprint})
    registry, inserted = _claim(session, REVIEW_NAMESPACE, key, request, now)
    if not inserted:
        review = session.execute(
            select(BillingMigrationReview).where(BillingMigrationReview.idempotency_registry_id == registry.id)
        ).scalar_one_or_none()
        if registry.state != "completed" or review is None:
            raise MigrationRetryError("the review is already being recorded")
        return review, "duplicate"
    if session.execute(select(func.count()).select_from(BillingMigrationReview).where(
            BillingMigrationReview.billing_account_id == account.id,
            BillingMigrationReview.subject_user_id == subject_user_id,
            BillingMigrationReview.evidence_fingerprint == fingerprint)).scalar_one():
        raise MigrationConflictError("this evidence already has a review; a second approval is refused")
    review = BillingMigrationReview(
        id=str(uuid.uuid4()), review_key=key, billing_account_id=account.id, subject_user_id=subject_user_id,
        amount=amount, expiry_basis=expiry_basis, expires_at=expires_at,
        expiry_evidence_payment_id=expiry_evidence_payment_id, expiry_evidence_reference=expiry_evidence_reference,
        candidates_json=list(candidates_considered), reason=reason, evidence_fingerprint=fingerprint,
        reviewer_user_id=reviewer_user_id, staff_permission_grant_id=grant.id, reviewed_at=now,
        request_fingerprint=request, idempotency_registry_id=registry.id,
    )
    session.add(review)
    session.flush()
    _complete(session, registry, now, "billing_migration_review", review.id)
    return review, "inserted"


def _cycle_reset_after(value, claimed_at):
    reset = _parsed(value) if isinstance(value, str) else _utc(value)
    return None if reset is None or claimed_at is None else reset > claimed_at


def operation_review_evidence(session, operation, *, at, max_turn_seconds):
    """What a reviewer needs to decide one unclosed operation, and a recommendation. Reads only.

    The recommendation is advice for the individual review, never applied:
    ``no_compensation_owed`` only when the evidence shows any reservation came
    from a monthly meter whose cycle has reset since the claim (the approved S1
    rule: a reservation from an ended period is not restored, F2-F4 decisions
    section 1.5, addition 2); otherwise ``individual_review``, because the row
    cannot show whether or how much of a reservation was kept.
    """
    item = classify_legacy_operation(operation, at=at, max_turn_seconds=max_turn_seconds)
    # The latest claim of the row (a runtime retry reclaims it without changing created_at).
    claimed_at = _utc(_effective_start(operation))
    holder = session.get(User, operation.user_id) if operation.user_id else None
    organization = session.get(Organization, operation.organization_id) if operation.organization_id else None
    org_meter = _meter(organization.settings) if organization is not None else None
    grants_before_claim = 0 if holder is None or claimed_at is None else session.execute(
        select(func.count()).select_from(PersistentCreditGrant).where(
            PersistentCreditGrant.user_id == holder.id,
            PersistentCreditGrant.granted_at <= _naive_utc(claimed_at))).scalar_one()
    user_reset_since = None if holder is None else _cycle_reset_after(holder.credits_reset_at, claimed_at)
    org_reset_since = None if org_meter is None else _cycle_reset_after(org_meter.get("cycle_reset_at"), claimed_at)
    metadata = operation.metadata_json if isinstance(operation.metadata_json, dict) else {}
    evidence = {
        "classification": item,
        "operation": {
            "operation_type": operation.operation_type, "status": operation.status,
            "created_at": _iso(operation.created_at), "updated_at": _iso(operation.updated_at),
            "settled_at": _iso(operation.settled_at),
            "customer_visible": operation.customer_visible, "subsidized": operation.subsidized,
            "subsidy_classification": operation.subsidy_classification,
            "projected_credits": operation.projected_credits, "charged_credits": operation.charged_credits,
            "has_thread": operation.thread_id is not None, "has_idempotency_key": operation.idempotency_key is not None,
            "metadata_keys": sorted(metadata),
        },
        "subject": None if holder is None else {
            "plan": normalize_plan_key(holder.subscription_plan), "credits_reset_at": _iso(holder.credits_reset_at),
            "persistent_grants_before_claim": int(grants_before_claim),
        },
        "monthly_cycle_reset_since_claim": {"user": user_reset_since, "organization": org_reset_since},
        "evidence_fingerprint": operation_fingerprint(operation),
    }
    # A shared-pool plan draws on the organization's meter, and its debits restamp the member's
    # ``credits_reset_at``, so only the organization's cycle counts; otherwise the member's own cycle does.
    shared_pool = holder is not None and normalize_plan_key(holder.subscription_plan) in SHARED_POOL_PLANS
    monthly_reset = (org_reset_since is True) if shared_pool else (user_reset_since is True)
    evidence["monthly_cycle_reset_since_claim"]["meter_used"] = "organization" if shared_pool else "user"
    if holder is not None and grants_before_claim == 0 and monthly_reset:
        evidence["recommendation"] = {
            "disposition": "no_compensation_owed",
            "basis": "the subject held no persistent credit at the claim, so any reservation came from the monthly "
                     "meter, whose cycle has reset since; a reservation from an ended period is not restored "
                     "(F2-F4 decisions 1.5, addition 2)",
        }
    else:
        evidence["recommendation"] = {
            "disposition": "individual_review",
            "basis": "the evidence cannot show whether or how much of a reservation was kept; nothing is "
                     "compensated without evidence of the amount",
        }
    return evidence


def unclosed_operation_review(session, *, at=None):
    """Every unclosed legacy operation, its class, whether it blocks, and for each one that needs a decision
    the evidence and a recommended disposition. Reads only; changes nothing."""
    at = _database_clock(session) if at is None else _utc(at)
    bound = migration_max_turn_seconds()
    operations = session.execute(
        select(AIOperation).where(or_(AIOperation.status.is_(None),
                                      AIOperation.status.notin_(sorted(TERMINAL_OPERATION_STATUSES))))
        .order_by(AIOperation.created_at, AIOperation.id)).scalars().all()
    decisions = _decisions_for(session, [o.id for o in operations])
    rows = []
    for operation in operations:
        status = legacy_operation_status(operation, at=at, max_turn_seconds=bound,
                                         decisions=decisions.get(operation.id, []))
        if status is None:
            continue
        row = {**status, "user_id": operation.user_id, "organization_id": operation.organization_id}
        if status["class"] in DECIDABLE_OPERATION_CLASSES and status.get("decision_id") is None:
            row["evidence"] = operation_review_evidence(session, operation, at=at, max_turn_seconds=bound)
        rows.append(row)
    return {"at": _iso(at), "max_turn_seconds": bound, "operations": rows,
            "needs_decision": sum(1 for r in rows if r["code"] in ("legacy_operation_decision_required",
                                                                   "legacy_operation_decision_evidence_changed")),
            "blocking": sum(1 for r in rows if r["code"] is not None)}


def record_operation_decision(
    session, *, decision_command_id, ai_operation_id, disposition, evidence_reference, reason, reviewer_user_id,
    amount=None, beneficiary_billing_account_id=None, supersedes_decision_id=None,
):
    """Record one reviewer's decision about one unclosed legacy operation (BI-1, D-1).

    Only a ``stale_turn_evidence`` or ``outstanding_reservation`` operation
    takes a decision, and only while the age limit is configured. Separation
    of duties as for reviews: an explicit, unrevoked ``billing.migration.review``
    grant valid now, held by someone who is not the operation's user, nor an
    owner or member of any organization the operation can block (its own, and
    every organization its user owns or belongs to), nor the bound payer of
    any of their billing accounts. ``compensation_owed`` names an amount and
    the operation's own organization's billing account; it moves no money and
    keeps that account quarantined (compensation, when justified, is paid by a
    separately approved, reviewed ledger entry). The decision binds the
    operation's fingerprint, taken under a row lock; one decision per
    operation evidence. A correction never edits a decision: it is a new,
    append-only decision that names the current decision for the same
    evidence in ``supersedes_decision_id``; each decision is superseded at
    most once. Replaying a recorded command with the same facts returns it.
    Returns ``(decision, 'inserted'|'duplicate')``.
    """
    _read_committed(session)
    command_id = _text(decision_command_id, "decision_command_id", 128)
    reason = _text(reason, "reason", 4000)
    evidence_reference = _text(evidence_reference, "evidence_reference", 255)
    if disposition not in OPERATION_DISPOSITIONS:
        raise MigrationError(f"the disposition must be one of {', '.join(OPERATION_DISPOSITIONS)}")
    if disposition == "no_compensation_owed":
        if amount is not None or beneficiary_billing_account_id is not None:
            raise MigrationError("no_compensation_owed takes no amount or beneficiary")
    elif isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0 \
            or not beneficiary_billing_account_id:
        raise MigrationError("compensation_owed needs a positive integer amount of legacy internal units "
                             "and the beneficiary billing account")
    key = f"migration-operation-decision:{command_id}"
    recorded = session.execute(select(BillingMigrationOperationDecision).where(
        BillingMigrationOperationDecision.decision_key == key)).scalar_one_or_none()
    if recorded is not None:
        # A replay is judged against what was recorded, so it stays stable after the operation changes.
        asked = (ai_operation_id, disposition, amount, beneficiary_billing_account_id, evidence_reference, reason,
                 reviewer_user_id, supersedes_decision_id)
        if asked != (recorded.ai_operation_id, recorded.disposition, recorded.amount,
                     recorded.beneficiary_billing_account_id, recorded.evidence_reference, recorded.reason,
                     recorded.reviewer_user_id, recorded.supersedes_decision_id):
            raise MigrationConflictError(f"{OPERATION_DECISION_NAMESPACE} identity was reused with different facts")
        return recorded, "duplicate"
    bound = migration_max_turn_seconds()
    if bound is None:
        raise MigrationError(f"{MAX_TURN_SECONDS_CONFIG_KEY} is not configured; no operation can be decided")
    operation = session.execute(select(AIOperation).where(AIOperation.id == ai_operation_id)
                                .with_for_update()).scalar_one_or_none()
    if operation is None:
        raise MigrationError("the operation does not exist")
    now = _database_now(session)
    item = classify_legacy_operation(operation, at=now, max_turn_seconds=bound)
    if item is None or item["class"] not in DECIDABLE_OPERATION_CLASSES:
        found = "closed" if item is None else item["class"]
        raise MigrationError(f"a {found} operation cannot take a decision")
    if reviewer_user_id is None or reviewer_user_id == operation.user_id:
        raise MigrationPermissionError("a reviewer cannot decide their own operation")
    grant = _authorized_grant(session, user_id=reviewer_user_id, permission=REVIEW_PERMISSION, started_at=now)
    if grant is None:
        raise MigrationPermissionError("the reviewer does not hold the explicit migration review permission")
    organization = session.get(Organization, operation.organization_id) if operation.organization_id else None
    affected = operation_affected_organization_ids(session, operation)
    for organization_id in sorted(affected):
        affected_org = session.get(Organization, organization_id)
        if affected_org is not None and (reviewer_user_id == affected_org.owner_user_id or reviewer_user_id in {
                m.user_id for m in _members(session, organization_id, active_only=False)}):
            raise MigrationPermissionError("a member or owner of an organization the operation blocks cannot decide it")
    if affected and session.execute(select(func.count()).select_from(BillingMigrationPayerBinding).join(
            BillingAccount, BillingAccount.id == BillingMigrationPayerBinding.billing_account_id).where(
            BillingAccount.organization_id.in_(sorted(affected)),
            BillingMigrationPayerBinding.payer_user_id == reviewer_user_id)).scalar_one():
        raise MigrationPermissionError("the payer of an organization the operation blocks cannot decide it")
    beneficiary = None
    if disposition == "compensation_owed":
        beneficiary = _lock_account(session, beneficiary_billing_account_id)
        if organization is None or beneficiary.organization_id != organization.id:
            raise MigrationError("compensation can be owed only to the operation's own organization's billing account")
        if session.execute(select(func.count()).select_from(BillingMigrationPayerBinding).where(
                BillingMigrationPayerBinding.billing_account_id == beneficiary.id,
                BillingMigrationPayerBinding.payer_user_id == reviewer_user_id)).scalar_one():
            raise MigrationPermissionError("the beneficiary account's payer cannot decide its compensation")
        estimate = (item.get("facts") or {}).get("estimated_reservation")
        if isinstance(estimate, int) and not isinstance(estimate, bool) and estimate > 0 and amount > estimate:
            raise MigrationError("compensation cannot exceed the reservation the operation recorded")
    fingerprint = operation_fingerprint(operation)
    current = _current_decision(session, operation.id, fingerprint)
    if supersedes_decision_id is None:
        if current is not None:
            raise MigrationConflictError("this operation evidence already has a decision; record a correction "
                                         "that supersedes it instead of a second decision")
    elif current is None or current.id != supersedes_decision_id:
        raise MigrationConflictError("a correction must supersede the current decision for this operation's "
                                     "current evidence")
    request = _fingerprint({"ai_operation_id": operation.id, "operation_class": item["class"],
                            "disposition": disposition, "amount": amount,
                            "beneficiary_billing_account_id": beneficiary.id if beneficiary else None,
                            "evidence_reference": evidence_reference, "reason": reason,
                            "reviewer_user_id": reviewer_user_id, "evidence_fingerprint": fingerprint,
                            "supersedes_decision_id": supersedes_decision_id,
                            "rule_version": OPERATION_DECISION_RULE_VERSION})
    registry, inserted = _claim(session, OPERATION_DECISION_NAMESPACE, key, request, now)
    if not inserted:
        decision = session.execute(select(BillingMigrationOperationDecision).where(
            BillingMigrationOperationDecision.idempotency_registry_id == registry.id)).scalar_one_or_none()
        if registry.state != "completed" or decision is None:
            raise MigrationRetryError("the decision is already being recorded")
        return decision, "duplicate"
    decision = BillingMigrationOperationDecision(
        id=str(uuid.uuid4()), decision_key=key, ai_operation_id=operation.id, subject_user_id=operation.user_id,
        operation_organization_id=operation.organization_id, operation_class=item["class"],
        disposition=disposition, amount=amount, beneficiary_billing_account_id=beneficiary.id if beneficiary else None,
        evidence_json=operation_review_evidence(session, operation, at=now, max_turn_seconds=bound),
        evidence_fingerprint=fingerprint, evidence_reference=evidence_reference, reason=reason,
        rule_version=OPERATION_DECISION_RULE_VERSION, reviewer_user_id=reviewer_user_id,
        staff_permission_grant_id=grant.id, decided_at=now, request_fingerprint=request,
        idempotency_registry_id=registry.id, supersedes_decision_id=supersedes_decision_id,
    )
    session.add(decision)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        # A concurrent decision or correction for the same evidence won (the uniqueness of the root and of
        # each successor is the final arbiter).
        raise MigrationConflictError("another decision for this operation evidence was recorded first") from exc
    _complete(session, registry, now, "billing_migration_operation_decision", decision.id)
    return decision, "inserted"


# ---------------------------------------------------------------------------
# Reports (pure): coverage across every legacy holder, per-run results
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Legacy payment archive and plan mappings (founder decisions 2026-11-18)
# ---------------------------------------------------------------------------

ARCHIVE_NAMESPACE = "billing.migration.payment_archive"
PLAN_MAPPING_NAMESPACE = "billing.migration.plan_mapping"
# What a legacy payment row never recorded: listed on every archive, never filled in.
PAYMENT_ARCHIVE_UNRESOLVED = ("processor_event", "processor_mode", "tax", "fees", "line_items", "payment_method",
                              "refunds_and_disputes")
# Subscription terms legacy records cannot prove; only a separately authorized processor read can.
SUBSCRIPTION_UNRESOLVED = ("current_period_start", "current_period_end", "billing_anchor", "cancel_at_period_end",
                           "price", "paid_seat_quantity", "payment_details")
# Legacy webhook states (routes/billing.py): a live subscription keeps the plan; an ended one resets it to free.
LIVE_SUBSCRIPTION_STATUSES = frozenset({"active", "trialing", "past_due"})
ENDED_SUBSCRIPTION_STATUSES = frozenset({"canceled", "cancelled", "paused", "incomplete_expired", "unpaid"})
# Legacy entitlement keys with a known meaning (founder_entitlements.LIMITED_TIME_300K_ENTITLEMENT).
KNOWN_LEGACY_ENTITLEMENTS = frozenset({"300k_limited_time"})


def _archive_record(payment):
    """Every column of a legacy payment row, exactly as stored."""
    return {
        "payment_id": payment.id, "external_reference": payment.external_reference, "source": payment.source,
        "legacy_user_id": payment.user_id, "legacy_organization_id": payment.organization_id,
        "legacy_billing_account_id": payment.billing_account_id, "currency": payment.currency,
        "amount_paid_cents": int(payment.amount_paid_cents), "amount_due_cents": int(payment.amount_due_cents),
        "discount_cents": int(payment.discount_cents), "is_comped": bool(payment.is_comped),
        "promotion_code": payment.promotion_code, "plan_key": payment.plan_key,
        "billing_interval": payment.billing_interval, "stripe_subscription_id": payment.stripe_subscription_id,
        "paid_at": payment.paid_at, "legacy_created_at": payment.created_at,
    }


def _archive_fingerprint(record):
    return _fingerprint({key: (value.isoformat() if isinstance(value, datetime) else value)
                         for key, value in record.items()})


def _test_activity_attestation(session, attestation):
    """A founder attestation naming the payers whose historical payments were test activity; never a default."""
    if attestation is None:
        return None
    if not isinstance(attestation, dict) or set(attestation) != {"reference", "payer_user_ids"}:
        raise MigrationError("a test-activity attestation names exactly its reference and payer_user_ids")
    reference = _text(attestation["reference"], "attestation reference", 255)
    payers = attestation["payer_user_ids"]
    if isinstance(payers, str) or not isinstance(payers, (list, tuple)) or not payers \
            or any(not isinstance(p, str) or not p.strip() for p in payers) or len(set(payers)) != len(payers):
        raise MigrationError("a test-activity attestation names each attested payer exactly once")
    for payer in payers:
        if session.get(User, payer) is None:
            raise MigrationError("an attested test payer must be an existing legacy user")
    return {"reference": reference, "payer_user_ids": sorted(payers)}


def plan_payment_archive(session, *, test_activity_attestation=None):
    """Pure: every legacy payment row, how it would be archived, and its archive state; writes nothing.

    ``state`` is ``new`` (not archived), ``unchanged`` (archived from the same
    row), or ``changed`` (the row differs from its archive; never rewritten).
    """
    with session.no_autoflush:
        attestation = _test_activity_attestation(session, test_activity_attestation)
        attested = set(attestation["payer_user_ids"]) if attestation else set()
        items = []
        for payment in session.execute(select(Payment).order_by(Payment.id)).scalars():
            record = _archive_record(payment)
            fingerprint = _archive_fingerprint(record)
            test = payment.user_id is not None and payment.user_id in attested
            archive = session.execute(select(BillingMigrationPaymentArchive).where(
                BillingMigrationPaymentArchive.payment_id == payment.id)).scalar_one_or_none()
            state = "new" if archive is None else (
                "unchanged" if archive.evidence_fingerprint == fingerprint else "changed")
            items.append({"payment_id": payment.id, "record": record, "evidence_fingerprint": fingerprint,
                          "classification": "test_activity" if test else "unverified",
                          "classification_reference": attestation["reference"] if test else None,
                          "state": state, "archive_id": archive.id if archive else None,
                          "archived_classification": archive.classification if archive else None})
        live = {item["payment_id"] for item in items}
        missing = [pid for pid in session.execute(
            select(BillingMigrationPaymentArchive.payment_id).order_by(BillingMigrationPaymentArchive.payment_id)
        ).scalars() if pid not in live]
        paying = {item["record"]["legacy_user_id"] for item in items}
        return {"attestation": attestation, "payments": items, "archived_payment_missing": missing,
                "attested_payers_without_payments": sorted(attested - paying)}


def archive_legacy_payments(session, *, run_id, test_activity_attestation=None):
    """Preserve every legacy payment row as an immutable archive inside the caller's transaction.

    Founder decision (2026-11-18): historical payments enter a legacy archive,
    never a Phase 5.2 financial transaction. Each row is copied exactly as
    stored, at most once ever; nothing it never recorded (processor event,
    tax, fees, lines, payment method) is filled in. A payment is
    ``test_activity`` only when ``test_activity_attestation``
    (``{"reference": ..., "payer_user_ids": [...]}``) names its payer;
    otherwise it stays ``unverified``. No archive is a verified customer
    payment: that needs a separately authorized processor verification. With
    no legacy payment, nothing is written. A changed or missing row is
    reported, never rewritten. Returns a summary.
    """
    _read_committed(session)
    run = _run(session, run_id)
    session.execute(select(Payment.id).order_by(Payment.id).with_for_update(read=True)).all()
    at = _database_clock(session)
    plan = plan_payment_archive(session, test_activity_attestation=test_activity_attestation)
    archived, unchanged, findings = [], [], []
    for item in plan["payments"]:
        if item["state"] == "changed":
            _quarantine(findings, "archived_payment_changed", item["payment_id"],
                        "the legacy row differs from its archive; an archive is never rewritten")
            continue
        if item["state"] == "unchanged":
            unchanged.append(item["archive_id"])
            if plan["attestation"] is not None and item["archived_classification"] != item["classification"]:
                _quarantine(findings, "classification_differs_from_archive", item["payment_id"],
                            "an archived classification is permanent; a different attestation is reviewed")
            continue
        record = item["record"]
        registry, inserted = _claim(session, ARCHIVE_NAMESPACE, item["payment_id"], item["evidence_fingerprint"], at)
        if not inserted:
            raise MigrationRetryError("this legacy payment is already being archived")
        row = BillingMigrationPaymentArchive(
            id=str(uuid.uuid4()), run_id=run.id, **record, classification=item["classification"],
            classification_reference=item["classification_reference"],
            unresolved_json=list(PAYMENT_ARCHIVE_UNRESOLVED), evidence_fingerprint=item["evidence_fingerprint"],
            idempotency_registry_id=registry.id,
        )
        try:
            session.add(row)
            session.flush()
        except IntegrityError as exc:
            raise MigrationRetryError("a concurrent command archived this payment; retry the transaction") from exc
        _complete(session, registry, at, "billing_migration_payment_archive", row.id)
        archived.append(row.id)
    for payment_id in plan["archived_payment_missing"]:
        _quarantine(findings, "archived_payment_missing", payment_id,
                    "an archived legacy payment row no longer exists; the archive keeps it")
    for payer in plan["attested_payers_without_payments"]:
        _quarantine(findings, "attested_payer_without_payments", payer, None)
    return {"run_id": run.id, "archived": len(archived), "unchanged": len(unchanged), "findings": findings,
            "summary": payment_archive_summary(session)}


def payment_archive_summary(session):
    """Pure: archived legacy payments by classification, and what is not archived.

    ``verified_customer_payments`` is always 0 here: an archive is never a
    verified customer payment; only a separately authorized processor
    verification (not part of Phase 14) could establish one.
    """
    with session.no_autoflush:
        by = {key: {"payments": 0, "amount_paid_cents_by_currency": {}} for key in PAYMENT_CLASSIFICATIONS}
        for row in session.execute(select(BillingMigrationPaymentArchive)
                                   .order_by(BillingMigrationPaymentArchive.payment_id)).scalars():
            entry = by[row.classification]
            entry["payments"] += 1
            currency = (row.currency or "").lower()
            entry["amount_paid_cents_by_currency"][currency] = \
                entry["amount_paid_cents_by_currency"].get(currency, 0) + int(row.amount_paid_cents)
        archived = select(BillingMigrationPaymentArchive.payment_id)
        unarchived = session.execute(select(func.count()).select_from(Payment)
                                     .where(Payment.id.not_in(archived))).scalar_one()
        return {"by_classification": by, "verified_customer_payments": 0, "unarchived_payments": int(unarchived),
                "unresolved_fields": list(PAYMENT_ARCHIVE_UNRESOLVED)}


def _subject_plan(session, user, contract_state, codes, unresolved):
    """The legacy plan, subscription, payments, and entitlements of one user whose plan this organization owns."""
    plan = normalize_plan_key(user.subscription_plan)
    status = (user.subscription_status or "").strip().lower() or None
    subscription_id = user.stripe_subscription_id or None
    payments = []
    for payment in session.execute(select(Payment).where(Payment.user_id == user.id).order_by(Payment.id)).scalars():
        archive = session.execute(select(BillingMigrationPaymentArchive).where(
            BillingMigrationPaymentArchive.payment_id == payment.id)).scalar_one_or_none()
        if archive is None:
            _quarantine(codes, "payment_not_archived", payment.id, "archive every legacy payment before mapping plans")
        elif archive.evidence_fingerprint != _archive_fingerprint(_archive_record(payment)):
            _quarantine(codes, "archived_payment_changed", payment.id, None)
        payments.append({"payment_id": payment.id, "source": payment.source, "plan_key": payment.plan_key,
                         "billing_interval": payment.billing_interval,
                         "stripe_subscription_id": payment.stripe_subscription_id,
                         "archive_id": archive.id if archive else None,
                         "classification": archive.classification if archive else None})
    invoices = [p for p in payments if p["source"] == "subscription_invoice"]
    entitlements = []
    for row in session.execute(select(AccountEntitlement).where(
            AccountEntitlement.user_id == user.id, AccountEntitlement.revoked_at.is_(None))
            .order_by(AccountEntitlement.id)).scalars():
        entitlements.append(_entitlement_record(row))
        if row.entitlement_key not in KNOWN_LEGACY_ENTITLEMENTS:
            _quarantine(codes, "unknown_legacy_entitlement", row.id, row.entitlement_key)
    subject = {"user_id": user.id, "legacy_subscription_plan": user.subscription_plan, "plan_key": plan,
               "subscription_status": user.subscription_status, "processor_subscription_id": subscription_id,
               "payments": payments, "entitlements": entitlements,
               "seat_configuration": {"seat_limit": user.seat_limit, "max_seats": user.max_seats},
               "mapping": None, "subscription": None}
    if plan not in DEFAULT_PLAN_CATALOG:
        _quarantine(codes, "unknown_legacy_plan", user.id, user.subscription_plan)
    elif plan in SALES_LED_PLANS:
        if contract_state == "none":
            _quarantine(codes, "enterprise_without_contract", user.id,
                        "a plan label is not Enterprise evidence; an executed contract is required")
        else:
            subject["mapping"] = "executed_contract"
    elif plan == "free":
        if subscription_id is not None or status in LIVE_SUBSCRIPTION_STATUSES:
            _quarantine(codes, "subscription_state_conflict", user.id,
                        "a free plan alongside a live processor subscription")
        elif status in ENDED_SUBSCRIPTION_STATUSES:
            subject["mapping"] = "free_after_ended_subscription"
            subject["subscription"] = {"state": "ended", "status": status,
                                       "invoices": [p["payment_id"] for p in invoices]}
        elif status is not None:
            _quarantine(codes, "subscription_status_unrecognized", user.id, status)
        elif invoices:
            _quarantine(codes, "subscription_history_without_end_state", user.id,
                        "subscription invoices exist but the legacy record never shows how the subscription ended")
        else:
            subject["mapping"] = "free"
    elif subscription_id is None:
        _quarantine(codes, "plan_without_subscription_evidence", user.id,
                    "a paid plan label is not evidence of a subscription (comped, coupon, or set by hand)")
    elif status is None:
        _quarantine(codes, "subscription_status_missing", user.id, None)
    elif status not in LIVE_SUBSCRIPTION_STATUSES:
        _quarantine(codes, "subscription_state_conflict", user.id, f"a paid plan with subscription status {status}")
    else:
        subject["mapping"] = "paid_subscription_unverified"
        subject["subscription"] = {
            "state": "unverified", "processor_subscription_id": subscription_id, "status": status, "plan_key": plan,
            "billing_intervals": sorted({p["billing_interval"] for p in invoices if p["billing_interval"]}),
            "invoices": [p["payment_id"] for p in invoices],
            "funded_only_by_test_activity": bool(invoices) and all(
                p["classification"] == "test_activity" for p in invoices),
        }
        for field in SUBSCRIPTION_UNRESOLVED:
            unresolved.append({"subject": user.id, "field": field, "reason": "requires_processor_verification"})
    return subject


def _entitlement_record(row):
    return {"entitlement_id": row.id, "entitlement_key": row.entitlement_key, "source": row.source,
            "external_reference": row.external_reference, "user_id": row.user_id,
            "organization_id": row.organization_id, "granted_at": _iso(row.granted_at)}


def plan_legacy_plan_mapping(session, *, billing_account_id, at=None):
    """Pure plan of one established account's legacy plan, subscription, entitlements, and seats; writes nothing.

    Each person's plan is mapped in the organization that owns their personal
    legacy value (the same evidence-ranked owner as the credit backfill). The
    organization's plan is its owner's plan (the legacy rule,
    ``orgs.sync_org_plan_from_owner``). Free accounts map as free with no
    subscription and no paid seats. A live paid subscription maps with its
    dates, paid seats, and payment details unresolved. A paid label without a
    processor subscription, contradictory states, unknown plans or
    entitlements, unarchived payments, and unresolved owners quarantine.
    Credit balances are the credit backfill's (referenced, never re-derived).
    """
    with session.no_autoflush:
        account = session.get(BillingAccount, billing_account_id) if billing_account_id else None
        if account is None:
            raise MigrationError("billing account does not exist")
        organization = session.get(Organization, account.organization_id)
        at = _database_clock(session) if at is None else _utc(at)
        codes, unresolved = [], []
        establishment = _established(session, organization, account, at, codes)
        contract_state = project_billing_account(session, billing_account_id=account.id, at=at)["contract_access"]["state"]
        people = {m.user_id for m in _members(session, organization.id, active_only=False)}
        if organization.owner_user_id:
            people.add(organization.owner_user_id)
        subjects, elsewhere, unowned = [], [], []
        for user_id in sorted(people):
            user = session.get(User, user_id)
            if user is None:
                continue
            owner = resolve_legacy_value_owner(session, user)
            if owner["organization_id"] == organization.id:
                subjects.append(_subject_plan(session, user, contract_state, codes, unresolved))
            elif owner["organization_id"] is not None:
                elsewhere.append({"user_id": user.id, "organization_id": owner["organization_id"],
                                  "reason": owner["reason"]})
            else:
                probe_codes = []
                probe = _subject_plan(session, user, contract_state, probe_codes, [])
                if probe["mapping"] == "free" and not probe["payments"] and not probe["entitlements"]:
                    # Nothing to map or guess: a free member with no personal plan evidence of their own.
                    unowned.append({"user_id": user.id, "plan_key": "free", "reason": owner["reason"]})
                else:
                    _quarantine(codes, "plan_owner_unresolved", user.id, owner["reason"])

        owner_user = session.get(User, organization.owner_user_id) if organization.owner_user_id else None
        owner_subject = next((s for s in subjects if owner_user is not None and s["user_id"] == owner_user.id), None)
        legacy_plan_key = None
        if owner_user is None:
            _quarantine(codes, "organization_owner_missing", organization.id,
                        "the legacy organization plan is its owner's plan")
        elif owner_subject is not None:
            legacy_plan_key = owner_subject["plan_key"] if owner_subject["mapping"] else None
        elif normalize_plan_key(owner_user.subscription_plan) == "free":
            legacy_plan_key = "free"
        else:
            _quarantine(codes, "organization_plan_paid_elsewhere", organization.id,
                        "the owner's paid plan belongs to another organization's subscription")

        organization_entitlements = []
        for row in session.execute(select(AccountEntitlement).where(
                AccountEntitlement.organization_id == organization.id, AccountEntitlement.user_id.is_(None),
                AccountEntitlement.revoked_at.is_(None)).order_by(AccountEntitlement.id)).scalars():
            organization_entitlements.append(_entitlement_record(row))
            if row.entitlement_key not in KNOWN_LEGACY_ENTITLEMENTS:
                _quarantine(codes, "unknown_legacy_entitlement", row.id, row.entitlement_key)

        mappings = {s["mapping"] for s in subjects}
        paid = "paid_subscription_unverified" in mappings
        seats = {
            "organization_configuration": {
                "max_admin_seats": organization.max_admin_seats,
                "max_total_paid_seats": organization.max_total_paid_seats,
                "max_creator_seats": organization.max_creator_seats,
                "max_collaborator_seats": organization.max_collaborator_seats,
                "seat_policy_overrides": organization.seat_policy_overrides,
            },
            # Legacy seat fields are configuration, never a paid commitment (D18 row 14 boundary 3).
            "paid_seats": "unresolved" if paid else ("executed_contract" if "executed_contract" in mappings
                                                     else "none"),
            "basis": "requires_processor_verification" if paid else (
                "executed_contract" if "executed_contract" in mappings else "no_paid_subscription_evidence"),
        }
        evidence = {
            "algorithm_version": ALGORITHM_VERSION, "organization_id": organization.id,
            "billing_account_id": account.id, "establishment_id": establishment.id if establishment else None,
            "contract_state": contract_state,
            "organization_plan": {"plan_key": organization.plan_key,
                                  "owner_user_id": organization.owner_user_id,
                                  "owner_plan_key": normalize_plan_key(owner_user.subscription_plan)
                                  if owner_user else None,
                                  "synced_to_owner": legacy_plan_key is not None
                                  and normalize_plan_key(organization.plan_key) == legacy_plan_key},
            "subjects": subjects, "owned_elsewhere": elsewhere, "free_members_without_own_plan": unowned,
            "organization_entitlements": organization_entitlements, "seats": seats,
        }
        latest = session.execute(
            select(BillingMigrationAccountResult).where(BillingMigrationAccountResult.billing_account_id == account.id)
            .order_by(BillingMigrationAccountResult.created_at.desc(), BillingMigrationAccountResult.id.desc())
            .limit(1)).scalar_one_or_none()
        credit = {"account_result_id": latest.id, "run_id": latest.run_id, "outcome": latest.outcome,
                  "opened_total": int(latest.opened_total)} if latest else None
        outcome = "quarantined" if codes else ("mapped_pending_processor" if unresolved else "mapped")
        return {
            "billing_account_id": account.id, "organization_id": organization.id,
            "establishment_id": establishment.id if establishment else None, "at": at, "outcome": outcome,
            "legacy_plan_key": legacy_plan_key if outcome != "quarantined" else None,
            "quarantine": codes, "unresolved": unresolved, "evidence": evidence, "credit_balances": credit,
            "evidence_fingerprint": _fingerprint(evidence),
        }


def map_legacy_plan(session, *, run_id, billing_account_id):
    """Record the evidence-backed legacy plan mapping of one established account inside the caller's transaction.

    Founder decision (2026-11-18). Outcomes: ``mapped`` (free, ended, or
    contract-backed; nothing unresolved), ``mapped_pending_processor`` (a live
    paid subscription whose dates, paid seats, and payment details wait for a
    separately authorized processor read), or ``quarantined``. Creates no
    Phase 4 subscription or entitlement and no processor call. The account
    must be established first. Returns ``(mapping, 'inserted'|'duplicate')``.
    """
    _read_committed(session)
    run = _run(session, run_id)
    account = _lock_account(session, billing_account_id)
    _lock_legacy_sources(session, account)
    at = _database_clock(session)
    plan = plan_legacy_plan_mapping(session, billing_account_id=account.id, at=at)
    if plan["establishment_id"] is None:
        raise MigrationError("map the legacy plan only of an established account: "
                             + ", ".join(sorted({c["code"] for c in plan["quarantine"]})))
    registry, inserted = _claim(session, PLAN_MAPPING_NAMESPACE, f"{run.id}:{account.id}",
                                plan["evidence_fingerprint"], at)
    if not inserted:
        row = session.execute(select(BillingMigrationPlanMapping).where(
            BillingMigrationPlanMapping.idempotency_registry_id == registry.id)).scalar_one_or_none()
        if registry.state != "completed" or row is None:
            raise MigrationRetryError("this account's plan is already being mapped in this run")
        return row, "duplicate"
    row = BillingMigrationPlanMapping(
        id=str(uuid.uuid4()), run_id=run.id, establishment_id=plan["establishment_id"],
        billing_account_id=account.id, organization_id=plan["organization_id"], outcome=plan["outcome"],
        legacy_plan_key=plan["legacy_plan_key"], snapshot_at=at,
        mapping_json={**plan["evidence"], "credit_balances": plan["credit_balances"]},
        unresolved_json=plan["unresolved"], quarantine_codes_json=plan["quarantine"],
        evidence_fingerprint=plan["evidence_fingerprint"], idempotency_registry_id=registry.id,
    )
    session.add(row)
    session.flush()
    _complete(session, registry, at, "billing_migration_plan_mapping", row.id)
    return row, "inserted"


def legacy_value_inventory(session):
    """Every legacy holder of personal or pooled value and the organization and account that own it (pure).

    An entry with ``billing_account_id`` ``None`` is unresolved or not yet
    established; its value can never be opened and it blocks the global write
    cutover.
    """
    with session.no_autoflush:
        holders = []
        for user in session.execute(select(User).order_by(User.id)).scalars():
            if _user_has_personal_value(session, user):
                owner = resolve_legacy_value_owner(session, user)
                holders.append({"kind": "user", "id": user.id, "organization_id": owner["organization_id"],
                                "billing_account_id": owner["billing_account_id"], "reason": owner["reason"]})
        pooled_ids = session.execute(
            select(Organization.id).join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
            .join(User, User.id == OrganizationMember.user_id)
            .where(OrganizationMember.status == "active",
                   or_(*[User.subscription_plan == plan for plan in sorted(SHARED_POOL_PLANS)]))
            .distinct().order_by(Organization.id)
        ).scalars().all()
        for organization in (session.get(Organization, org_id) for org_id in pooled_ids):
            meter = _meter(organization.settings)
            if meter is None or meter.get("remaining") == 0:
                continue
            account = _account_for(session, organization.id)
            holders.append({"kind": "organization", "id": organization.id, "organization_id": organization.id,
                            "billing_account_id": account.id if account else None,
                            "reason": "organization_pool" if account else "billing_account_missing"})
        return holders


def historical_value_population(session):
    """Counters and values the backfill can never open on its own evidence, for a founder decision (pure).

    Counts and sums of combined counters with no meter, net of proven
    persistent value (``legacy_meter_absent``: pre-2026-05-08 value lived
    there, in old units and terms), live meters and
    grants from before the unit boundary, and grants with no date. The
    2026-05-08 change was a repricing, not a unit conversion, so none of this
    is converted or discarded; it stays quarantined until honoured by an
    approved rule.
    """
    with session.no_autoflush:
        population = {key: {"holders": 0, "amount": 0} for key in
                      ("legacy_meter_absent", "pre_unit_boundary_meter", "pre_unit_boundary_grant",
                       "grant_date_missing")}
        for user in session.execute(select(User).order_by(User.id)).scalars():
            meter = _meter(user.ui_preferences)
            persistent = session.execute(
                select(func.coalesce(func.sum(PersistentCreditGrant.remaining_amount), 0)).where(
                    PersistentCreditGrant.user_id == user.id, PersistentCreditGrant.status == "active")
            ).scalar_one()
            unexplained = int(user.credits_remaining or 0) - int(persistent)
            if meter is None and unexplained != 0:
                population["legacy_meter_absent"]["holders"] += 1
                population["legacy_meter_absent"]["amount"] += unexplained
            reset = _parsed(meter.get("cycle_reset_at")) if meter else None
            remaining = _int_or_none(meter.get("remaining")) if meter else None
            if reset is not None and reset < UNIT_BOUNDARY_AT and remaining:
                population["pre_unit_boundary_meter"]["holders"] += 1
                population["pre_unit_boundary_meter"]["amount"] += remaining
        for grant in session.execute(select(PersistentCreditGrant).where(
                PersistentCreditGrant.status == "active", PersistentCreditGrant.remaining_amount > 0)
                .order_by(PersistentCreditGrant.id)).scalars():
            granted_at = _utc(grant.granted_at)
            key = "grant_date_missing" if granted_at is None else (
                "pre_unit_boundary_grant" if granted_at < UNIT_BOUNDARY_AT else None)
            if key:
                population[key]["holders"] += 1
                population[key]["amount"] += int(grant.remaining_amount)
        return population


def sources_opened_more_than_once(session):
    """Every legacy source with more than one opening across all accounts (always empty under the guard)."""
    return [{"legacy_source_kind": kind, "legacy_source_id": source_id, "openings": int(count)}
            for kind, source_id, count in session.execute(
                select(BillingMigrationOpening.legacy_source_kind, BillingMigrationOpening.legacy_source_id,
                       func.count())
                .group_by(BillingMigrationOpening.legacy_source_kind, BillingMigrationOpening.legacy_source_id)
                .having(func.count() > 1)
            )]


def migration_run_report(session, *, run_id):
    """Pure D16 report of one run: establishments, outcomes, sums by source, quarantine, coverage, global gate."""
    with session.no_autoflush:
        run = _run(session, run_id)
        establishments = session.execute(
            select(BillingMigrationEstablishment).where(BillingMigrationEstablishment.run_id == run.id)
            .order_by(BillingMigrationEstablishment.organization_id)
        ).scalars().all()
        results = session.execute(
            select(BillingMigrationAccountResult).where(BillingMigrationAccountResult.run_id == run.id)
            .order_by(BillingMigrationAccountResult.billing_account_id)
        ).scalars().all()
        openings = session.execute(
            select(BillingMigrationOpening).where(BillingMigrationOpening.run_id == run.id)
        ).scalars().all()
        by_source = Counter()
        for opening in openings:
            by_source[opening.lot_source_type] += int(opening.opening_amount)
        codes = Counter(code["code"] for result in results for code in result.quarantine_codes_json)
        establishment_codes = Counter(code["code"] for row in establishments for code in row.quarantine_codes_json)
        covered = {result.billing_account_id for result in results}
        uncovered = [h for h in legacy_value_inventory(session)
                     if h["billing_account_id"] is None or h["billing_account_id"] not in covered]
        outcomes = Counter(result.outcome for result in results)
        eligible = sum(1 for result in results if result.cutover_eligible)
        duplicates = sources_opened_more_than_once(session)
        mappings = session.execute(
            select(BillingMigrationPlanMapping).where(BillingMigrationPlanMapping.run_id == run.id)
            .order_by(BillingMigrationPlanMapping.billing_account_id)
        ).scalars().all()
        mapped_accounts = {m.billing_account_id for m in mappings}
        unmapped = sorted(covered - mapped_accounts)
        mapping_codes = Counter(code["code"] for m in mappings for code in m.quarantine_codes_json)
        archive = payment_archive_summary(session)
        return {
            "run_id": run.id, "run_key": run.run_key, "algorithm_version": run.algorithm_version,
            "credit_unit_basis": run.credit_unit_basis, "expiry_policy": run.expiry_policy,
            "operator_user_id": run.operator_user_id,
            "establishments": [{
                "organization_id": e.organization_id, "billing_account_id": e.billing_account_id,
                "outcome": e.outcome, "account_created": e.account_created,
                "quarantine_codes": [c["code"] for c in e.quarantine_codes_json],
            } for e in establishments],
            "establishment_outcomes": {key: sum(1 for e in establishments if e.outcome == key)
                                       for key in ("established", "unchanged", "quarantined")},
            "establishment_quarantine_codes": dict(sorted(establishment_codes.items())),
            "accounts": [{
                "billing_account_id": r.billing_account_id, "outcome": r.outcome,
                "opened_count": r.opened_count, "opened_total": int(r.opened_total),
                "credit_reconciled": r.credit_reconciled, "cutover_eligible": r.cutover_eligible,
                "quarantine_codes": [c["code"] for c in r.quarantine_codes_json],
                "evidence_fingerprint": r.evidence_fingerprint,
            } for r in results],
            "outcomes": {key: outcomes[key] for key in ("opened", "unchanged", "quarantined")},
            "opened_by_source": dict(sorted(by_source.items())),
            "quarantine_codes": dict(sorted(codes.items())),
            "sources_opened_more_than_once": duplicates,
            "historical_value_population": historical_value_population(session),
            "uncovered_holders": uncovered,
            "payment_archive": archive,
            "plan_mappings": [{
                "billing_account_id": m.billing_account_id, "outcome": m.outcome,
                "legacy_plan_key": m.legacy_plan_key,
                "unresolved_fields": sorted({u["field"] for u in m.unresolved_json}),
                "quarantine_codes": [c["code"] for c in m.quarantine_codes_json],
            } for m in mappings],
            "plan_mapping_outcomes": {key: sum(1 for m in mappings if m.outcome == key)
                                      for key in ("mapped", "mapped_pending_processor", "quarantined")},
            "plan_mapping_quarantine_codes": dict(sorted(mapping_codes.items())),
            "accounts_without_plan_mapping": unmapped,
            "global_write_cutover_blocked": bool(uncovered) or eligible != len(results) or not results
            or bool(duplicates) or bool(unmapped) or any(m.outcome != "mapped" for m in mappings)
            or archive["unarchived_payments"] > 0,
        }
