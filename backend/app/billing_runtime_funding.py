"""D18 row 17, I2: the modern credit-funding family runtime (``credit_funding``).

This is the only live module that reaches the inactive Phase 4/6/9 funding services for
modern organizations. Every entry point requires a ``ModernContext`` from
``billing_cutover.modern_context(family="credit_funding")``, or the switch itself for
operator commands, so nothing here runs while the family is off. Legacy accounts never
reach it.

**Definitions (D2, staging only).** ``define_test_catalog`` records approved entitlement
definitions copied from the configured catalog only: plan credits, ``included_seats`` and
credit-pack prices. Nothing is invented. Each definition is labeled test pricing and cites
``founder-decision-D2-2026-11-26``. The approver is an explicit argument. Keys follow the
coordinator-approved convention: ``plan.free``, ``plan.<plan>.monthly``,
``plan.<plan>.annual`` (exclusivity key ``plan``) and ``pack.<pack>``. Enterprise
contracts keep their own Phase 11 keys.

**Free allowance (D4).** Each modern organization owns its Free allowance: one
organization lot per calendar month from the billing account anchor, using the approved
``plan.free`` definition's quantity. There is no personal Free credit.

**Communications.** No customer template, channel or locale is approved, and wording
needs Lydia's approval before production. Phase 5.4 still requires an obligation, so a
staging-only placeholder (channel ``none``, version ``unapproved-v0``) is recorded. It is
refused in a production runtime, and no worker exists to deliver it.
"""

from dataclasses import dataclass
import hashlib
import json
import uuid

from sqlalchemy import select

from .billing_allocations import (
    RecurringAllocationError,
    RecurringAllocationRetryError,
    _claim_registry,
    _complete_registry_if_claimed,
    allocate_recurring_credits,
)
from .billing_cutover import _database_now, cutover_config
from .billing_entitlements import append_entitlement_transition, monthly_period_bounds
from .billing_ledger import lock_billing_account
from .models import BillingAccount, EntitlementDefinition, EntitlementInstance
from .models_billing_identity import BillingModelAssignment


FAMILY = "credit_funding"
APPROVAL_EVIDENCE = "founder-decision-D2-2026-11-26"
FREE_APPROVAL_EVIDENCE = "founder-decision-D4-2026-11-26"
PRICING_LABEL = "test"
PLAN_EXCLUSIVITY_KEY = "plan"
PACK_EXCLUSIVITY_KEY = "credit_pack"
INTERVALS = ("monthly", "annual")
PERIOD_KINDS = {"monthly": "monthly_subscription", "annual": "annual_monthly"}
TRANSITION_NAMESPACE = "billing_runtime_entitlement_transition"
SYSTEM_ACTOR = ("system", "billing_runtime")
PLACEHOLDER_TEMPLATE_VERSION = "unapproved-v0"
PLACEHOLDER_CHANNEL = "none"
PLACEHOLDER_LOCALE = "en-US"


class FundingRuntimeError(Exception):
    """A funding command cannot proceed (operational message only)."""


class FundingRetryError(FundingRuntimeError):
    """A concurrent command holds the identity; retry the transaction."""


# ---------------------------------------------------------------------------
# Keys and placeholders
# ---------------------------------------------------------------------------

def plan_definition_key(plan_key, interval=None):
    """``plan.free`` or ``plan.<plan>.<monthly|annual>`` (coordinator-approved convention)."""
    plan_key = str(plan_key or "").strip().lower()
    if not plan_key:
        raise FundingRuntimeError("a plan key is required")
    if plan_key == "free":
        return "plan.free"
    if interval not in INTERVALS:
        raise FundingRuntimeError("a paid plan definition needs interval monthly or annual")
    return f"plan.{plan_key}.{interval}"


def plan_tier_key(definition_or_key):
    """The capacity tier (``plan.<plan>``) of a plan definition or definition key."""
    key = definition_or_key.key if isinstance(definition_or_key, EntitlementDefinition) else str(definition_or_key)
    parts = key.split(".")
    if len(parts) < 2 or parts[0] != "plan":
        raise FundingRuntimeError("not a plan definition key")
    return f"plan.{parts[1]}"


def pack_definition_key(pack_key):
    pack_key = str(pack_key or "").strip().lower()
    if not pack_key:
        raise FundingRuntimeError("a credit pack key is required")
    return f"pack.{pack_key}"


def _refuse_production():
    from .rate_limits import is_production_runtime

    if is_production_runtime():
        raise FundingRuntimeError(
            "staging-only billing placeholders are refused in a production runtime")


def placeholder_obligations(event_type):
    """The staging-only Phase 5.4 obligation (Q2/Q5): never sent, refused in production."""
    _refuse_production()
    return [{"template_key": str(event_type), "template_version": PLACEHOLDER_TEMPLATE_VERSION,
             "channel": PLACEHOLDER_CHANNEL, "locale": PLACEHOLDER_LOCALE}]


def _fingerprint(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def require_family(config=None):
    from .billing_cutover import _require_family

    _require_family(FAMILY, config)


# ---------------------------------------------------------------------------
# D2 test catalog
# ---------------------------------------------------------------------------

def _whole_credits(tokens, label):
    from .billing_config import TOKENS_PER_CREDIT

    if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens <= 0:
        raise FundingRuntimeError(f"{label}: the configured quantity is not a positive integer")
    if tokens % TOKENS_PER_CREDIT:
        raise FundingRuntimeError(f"{label}: the configured quantity is not a whole number of credits")
    return tokens // TOKENS_PER_CREDIT


def _price_minor(amount, label):
    if amount is None or isinstance(amount, bool):
        raise FundingRuntimeError(f"{label}: no configured price")
    minor = round(float(amount) * 100)
    if minor <= 0 or abs(minor - float(amount) * 100) > 1e-6:
        raise FundingRuntimeError(f"{label}: the configured price is not a positive whole number of cents")
    return int(minor)


def test_catalog_specs(app_config, currency="usd"):
    """The definitions the configured catalog supports (values copied, never invented)."""
    from .billing_config import get_credit_packs, get_plan_catalog

    specs = []
    plans = get_plan_catalog(app_config)
    free = plans.get("free") or {}
    specs.append({
        "key": plan_definition_key("free"), "exclusivity_key": PLAN_EXCLUSIVITY_KEY,
        "capabilities": {"pricing_label": PRICING_LABEL, "plan_key": "free"},
        "funding": {"schema_version": 1, "period_kind": "free",
                    "credit_amount": _whole_credits(free.get("monthly_credits"), "free")},
    })
    for plan_key, plan in plans.items():
        if plan_key == "free" or plan.get("sales_only") or not plan.get("self_serve"):
            continue
        for interval in INTERVALS:
            capabilities = {"pricing_label": PRICING_LABEL, "plan_key": plan_key, "interval": interval}
            if plan.get("included_seats") is not None:
                capabilities["included_seats"] = int(plan["included_seats"])
            specs.append({
                "key": plan_definition_key(plan_key, interval), "exclusivity_key": PLAN_EXCLUSIVITY_KEY,
                "capabilities": capabilities,
                "funding": {"schema_version": 1, "period_kind": PERIOD_KINDS[interval],
                            "credit_amount": _whole_credits(plan.get("monthly_credits"), plan_key)},
            })
    from .billing_financial_effects import PURCHASE_EXPIRY

    for pack_key, pack in get_credit_packs(app_config).items():
        credits = _whole_credits(pack.get("credits"), pack_key)
        specs.append({
            "key": pack_definition_key(pack_key), "exclusivity_key": PACK_EXCLUSIVITY_KEY,
            "capabilities": {"pricing_label": PRICING_LABEL, "pack_key": pack_key},
            "funding": {"schema_version": 1, "period_kind": "none", "credit_amount": credits, "purchase": {
                "schema_version": 1, "line_kind": "credit_pack", "source_type": PACK_SOURCE_TYPE,
                "source_id": pack_key, "currency": currency,
                "unit_principal_minor": _price_minor(pack.get("price_usd"), pack_key), "quantity": 1,
                "components": [{"component": "credits", "credit_amount": credits}],
                "expiry": dict(PURCHASE_EXPIRY),
            }},
        })
    return specs


PACK_SOURCE_TYPE = "jaspen_credit_pack"


def define_test_catalog(session, *, approver_user_id, app_config, effective_at=None, config=None):
    """Record the D2 staging test catalog once. Returns ``[(key, version, state)]``.

    ``state`` is ``inserted`` or ``unchanged``. A key whose stored payload differs from
    the configured catalog is refused: changing an approved definition is a new,
    separately decided version. The caller commits.
    """
    from .models import User

    _refuse_production()
    require_family(config)
    approver = session.get(User, str(approver_user_id or ""))
    if approver is None:
        raise FundingRuntimeError("the approver user does not exist")
    at = _database_now(session)
    effective = at if effective_at is None else effective_at
    if effective.tzinfo is None or effective > at:
        raise FundingRuntimeError("effective_at must be timezone-aware and not in the future")
    results = []
    for spec in test_catalog_specs(app_config):
        capability_json = {"schema_version": 1, "capabilities": spec["capabilities"]}
        existing = session.execute(
            select(EntitlementDefinition).where(EntitlementDefinition.key == spec["key"])
            .order_by(EntitlementDefinition.version.desc()).limit(1)
        ).scalar_one_or_none()
        if existing is not None:
            if (existing.capability_json, existing.funding_policy_json, existing.exclusivity_key) != (
                    capability_json, spec["funding"], spec["exclusivity_key"]):
                raise FundingRuntimeError(
                    f"{spec['key']} v{existing.version} differs from the configured catalog; "
                    "a new version needs a separate decision")
            results.append((spec["key"], existing.version, "unchanged"))
            continue
        session.add(EntitlementDefinition(
            id=str(uuid.uuid4()), key=spec["key"], version=1, exclusivity_key=spec["exclusivity_key"],
            capability_json=capability_json, funding_policy_json=spec["funding"], effective_at=effective,
            approved_at=at, approved_by_user_id=approver.id, approval_evidence_reference=APPROVAL_EVIDENCE,
        ))
        session.flush()
        results.append((spec["key"], 1, "inserted"))
    return results


def current_definition(session, key, at):
    """The approved definition in force for ``key`` at ``at`` (highest version), or ``None``."""
    rows = session.execute(
        select(EntitlementDefinition).where(
            EntitlementDefinition.key == key, EntitlementDefinition.approved_at.is_not(None),
            EntitlementDefinition.effective_at.is_not(None),
        ).order_by(EntitlementDefinition.version.desc())
    ).scalars().all()
    for row in rows:
        effective = _utc(row.effective_at)
        retired = _utc(row.retired_at) if row.retired_at else None
        if effective <= at and (retired is None or retired > at):
            return row
    return None


def _utc(value):
    from datetime import timezone

    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Entitlement transitions (create_all schemas have no triggers: D10-10)
# ---------------------------------------------------------------------------

def transition_instance(session, instance, to_state, transition, at, source_id):
    """Append one Phase 4 transition under its own registry claim; idempotent."""
    key = f"runtime-entitlement:{instance.id}:{to_state}:{source_id}"
    fingerprint = _fingerprint({"instance": instance.id, "to": to_state, "source": source_id})
    try:
        registry, inserted = _claim_registry(session, TRANSITION_NAMESPACE, key, fingerprint, at)
    except RecurringAllocationRetryError as exc:
        raise FundingRetryError(str(exc)) from exc
    if not inserted:
        if registry.state == "completed" and registry.result_type == "entitlement_event":
            return registry.result_id
        raise FundingRetryError("the entitlement transition is already in progress")
    event = append_entitlement_transition(
        session, instance_id=instance.id, next_state=to_state, transition=transition, effective_at=at,
        actor_type=SYSTEM_ACTOR[0], actor_id=SYSTEM_ACTOR[1], source_type="billing_runtime",
        source_id=source_id, idempotency=registry, evidence_json={"runtime_source_id": source_id},
    )
    session.flush()
    session.refresh(instance)
    if instance.state != to_state:  # no migration trigger projected it (create_all schema)
        instance.state = to_state
        instance.last_event_id = event.id
        session.flush()
    _complete_registry_if_claimed(session, registry, completed_at=at, result_type="entitlement_event",
                                  result_id=event.id)
    return event.id


# ---------------------------------------------------------------------------
# D4 Free allowance
# ---------------------------------------------------------------------------

def period_index_at(anchor_at, at):
    """The calendar-month period of ``anchor_at`` that contains ``at``."""
    anchor, at = _utc(anchor_at), _utc(at)
    if at < anchor:
        raise FundingRuntimeError("the time precedes the account anchor")
    index = max(0, (at.year - anchor.year) * 12 + (at.month - anchor.month))
    while index > 0 and monthly_period_bounds(anchor, index)[0] > at:
        index -= 1
    while monthly_period_bounds(anchor, index)[1] <= at:
        index += 1
    return index


@dataclass(frozen=True)
class FreeAllocation:
    organization_id: str
    billing_account_id: str
    outcome: str  # inserted | duplicate | paid_plan_active | not_yet_effective | no_definition
    period_index: int | None = None
    credit_amount: int | None = None


def _active_plan_instances(session, account_id):
    return session.execute(
        select(EntitlementInstance).join(
            EntitlementDefinition, EntitlementDefinition.id == EntitlementInstance.entitlement_definition_id
        ).where(
            EntitlementInstance.billing_account_id == account_id,
            EntitlementInstance.state.in_(("scheduled", "active", "reducing")),
            EntitlementDefinition.exclusivity_key == PLAN_EXCLUSIVITY_KEY,
        )
    ).scalars().all()


def active_free_instance(session, account_id):
    for instance in _active_plan_instances(session, account_id):
        if instance.source_type == "free" and instance.state == "active":
            return instance
    return None


def allocate_free(session, context):
    """Open the organization's current monthly Free lot from its account anchor (D4). The caller commits."""
    account = lock_billing_account(session, context.billing_account_id)
    at = _database_now(session)
    index = period_index_at(account.account_anchor_at, at)
    period_start, _period_end = monthly_period_bounds(_utc(account.account_anchor_at), index)
    base = dict(organization_id=context.organization_id, billing_account_id=account.id, period_index=index)
    plan_instances = _active_plan_instances(session, account.id)
    if any(instance.source_type != "free" for instance in plan_instances):
        return FreeAllocation(outcome="paid_plan_active", **base)
    definition = current_definition(session, plan_definition_key("free"), period_start)
    if definition is None:
        if current_definition(session, plan_definition_key("free"), at) is not None:
            return FreeAllocation(outcome="not_yet_effective", **base)
        return FreeAllocation(outcome="no_definition", **base)
    instance = next((i for i in plan_instances if i.source_type == "free"), None)
    if instance is not None and instance.entitlement_definition_id != definition.id:
        raise FundingRuntimeError("the active Free entitlement uses another definition version")
    if instance is None:
        source_id = f"free:{account.id}:{period_start.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        instance = session.execute(select(EntitlementInstance).where(
            EntitlementInstance.billing_account_id == account.id, EntitlementInstance.source_type == "free",
            EntitlementInstance.source_id == source_id)).scalar_one_or_none()
        if instance is None:
            instance = EntitlementInstance(
                id=str(uuid.uuid4()), billing_account_id=account.id, entitlement_definition_id=definition.id,
                subscription_id=None, state="proposed", starts_at=period_start, ends_at=None,
                source_type="free", source_id=source_id, approval_evidence_reference=FREE_APPROVAL_EVIDENCE,
            )
            session.add(instance)
            session.flush()
        if instance.state == "proposed":
            transition_instance(session, instance, "scheduled", "free_allowance_approved", at, source_id)
        if instance.state == "scheduled":
            transition_instance(session, instance, "active", "free_allowance_activated", at, source_id)
    try:
        _allocation, _period, _lot, state = allocate_recurring_credits(
            session, billing_account_id=account.id, entitlement_instance_id=instance.id, period_index=index,
            opened_at=at, delivery_obligations=placeholder_obligations("credit_period_funded"),
            actor_type=SYSTEM_ACTOR[0], actor_id=SYSTEM_ACTOR[1],
        )
    except RecurringAllocationRetryError as exc:
        raise FundingRetryError(str(exc)) from exc
    except RecurringAllocationError as exc:
        raise FundingRuntimeError(str(exc)) from exc
    return FreeAllocation(outcome=state, credit_amount=int(definition.funding_policy_json["credit_amount"]),
                          **base)


def modern_contexts(session):
    """Every modern organization's context (organization id, billing account id), oldest first."""
    from .billing_cutover import ModernContext

    rows = session.execute(
        select(BillingModelAssignment.organization_id, BillingModelAssignment.billing_account_id)
        .join(BillingAccount, BillingAccount.id == BillingModelAssignment.billing_account_id)
        .where(BillingAccount.status == "active")
        .order_by(BillingModelAssignment.assigned_at, BillingModelAssignment.id)
    ).all()
    return [ModernContext(organization_id=o, billing_account_id=a) for o, a in rows]


def families_enabled():
    return sorted(cutover_config().families)
