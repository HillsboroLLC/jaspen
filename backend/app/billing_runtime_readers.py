"""D18 row 17, readers family (I5): today's response shapes, projected for a modern organization.

A modern organization's billing state lives only in the Phase 3-11 records:
the ledger (balances), Phase 4 entitlements, subscriptions and credit periods,
Phase 6-8 allocations, plan changes and seat commitments, and Phase 11
contracts. This module projects them into the shapes the existing frontend
already reads, so a modern organization works without frontend changes:

* ``modern_usage_meter_state``: the dict ``billing_config.get_usage_meter_state``
  returns (internal credit units), for ``routes/ai_agent.py``.
* ``modern_billing_status``: the ``GET /api/v1/billing/status`` payload.
* ``modern_org_gates``: the organization plan, seat policy, seat limit and
  collaboration gate that ``app/orgs.py`` and the team routes read.

Rules (ADR-0001 projection rule; Constitution Article 9):

* Entry is only through ``billing_cutover.modern_context(family="readers")``:
  callers ask the dispatch contract first, and a legacy context never reaches
  this module. Every function takes the ``ModernContext`` it returned.
* Pure reads, through ``billing_projections``. No write, flush, lock or
  autoflush; no legacy counter (``User.credits_*``, ``ui_preferences``,
  ``Organization.settings.thinking_power``, ``plan_key``, seat columns,
  ``PersistentCreditGrant``, the 300K offer, Stripe) is ever read for a
  modern organization, and no processor is called.
* Code computes every number; each one decomposes into ledger, entitlement,
  period or seat records. A field with no authoritative source yet is
  returned as ``None`` and named in ``not_available``; nothing is invented.
* An invariant violation is raised (``ProjectionInvariantError``), never hidden.
"""

from copy import deepcopy
from datetime import datetime, timezone

from sqlalchemy import select

from .billing_config import (
    PLAN_RANK,
    get_allowed_model_types,
    get_default_model_type,
    get_plan_catalog,
    tokens_to_credits,
)
from .billing_projections import project_billing_account, project_plan_terms
from .models import BillingAccount


READERS_FAMILY = "readers"
MODEL = "modern"

# Plans whose base entitlement is an executed Phase 11 contract are Enterprise, never inferred from text.
CONTRACT_PLAN_KEY = "enterprise_custom"
# Canonical base-plan definition keys: ``plan.<catalog plan key>`` (I2 ``plan_definition_key``; I4 tiers).
PLAN_DEFINITION_PREFIX = "plan."
# Phase 4 subscription states, written in the processor spelling the existing frontend compares against.
# ``cancel_at_period_end`` is an active subscription whose cancellation is scheduled (reported separately).
_STATUS_SPELLING = {"cancelled": "canceled", "cancel_at_period_end": "active"}
_INTERVALS = {"month": "monthly", "year": "annual"}
# Subscription states that keep collaboration invitations open (the processor "good standing" states).
_CURRENT_SUBSCRIPTION_STATES = frozenset({"active", "cancel_at_period_end"})


def _require(context):
    if context is None or not getattr(context, "billing_account_id", None):
        raise ValueError("a modern readers context from billing_cutover.modern_context is required")


def _parse(value):
    if value is None:
        return None
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def _naive(value):
    """UTC without an offset: the format today's payloads use for processor dates."""
    parsed = _parse(value) if isinstance(value, str) else value
    return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed is not None else None


def public_plan_key(definition_key, plan_source_type, app_config):
    """The public plan key of a modern base-plan entitlement, or None when it names no catalog plan.

    An executed-contract plan is Enterprise. A self-serve plan definition is named ``plan.<catalog plan
    key>`` (the canonical key the funding family writes, e.g. ``plan.team``). Any other key is not a
    recognized plan: gates fail closed on it.
    """
    if plan_source_type == "enterprise_contract":
        return CONTRACT_PLAN_KEY
    if not isinstance(definition_key, str) or not definition_key.startswith(PLAN_DEFINITION_PREFIX):
        return None
    key = definition_key[len(PLAN_DEFINITION_PREFIX):]
    return key if key in get_plan_catalog(app_config or {}) else None


def _account_and_terms(session, context, *, member_user_id=None, at=None):
    projection = project_billing_account(session, billing_account_id=context.billing_account_id, at=at,
                                         member_user_id=member_user_id)
    at = _parse(projection["as_of"])
    terms = project_plan_terms(session, billing_account_id=context.billing_account_id, at=at,
                               member_user_id=member_user_id)
    return projection, terms


# ---------------------------------------------------------------------------
# Usage meter (billing_config.get_usage_meter_state shape, internal units)
# ---------------------------------------------------------------------------

def _meter(projection, terms, app_config):
    credits = projection["credits"]
    period = terms["period"]
    plan_key = public_plan_key(terms["definition_key"], terms["plan_source_type"], app_config)
    not_available = []
    if terms["definition_key"] is None:
        not_available += ["plan_key", "monthly_limit"]
    elif plan_key is None:
        not_available.append("plan_key")
    if terms["definition_key"] is not None and terms["monthly_credit_amount"] is None:
        not_available.append("monthly_limit")
    if period is None:
        not_available += ["monthly_remaining", "cycle_limit", "used", "reset_at", "overage_tokens"]
    member_view = projection["member_user_id"] is not None
    return {
        "scope": "organization",
        "plan_key": plan_key,
        "organization_id": projection["organization_id"],
        "monthly_limit": terms["monthly_credit_amount"],
        "monthly_remaining": credits["period_remaining"],
        "cycle_limit": period["allocated"] if period is not None else None,
        # What this member may spend now (pool lots plus their own attributed lots), else the whole pool.
        "remaining": credits["member_spendable"] if member_view else credits["available"],
        # Settled usage of the whole organization this period (ADR: never limit minus balance).
        "used": projection["account_used_this_period"],
        # The modern ledger has a zero floor and no soft-stop grace.
        "grace_tokens": 0,
        # Today's payloads carry the last reset (the period start); the frontend adds one month.
        "reset_at": _naive(period["starts_at"]) if period is not None else None,
        "next_allocation_at": _naive(projection["next_allocation_at"]),
        "overage_tokens": period["purchased_in_period"] if period is not None else None,
        "persistent_credits": terms["non_expiring_available"],
        # The legacy founder/300K offers are personal legacy state, never part of a modern account.
        "founder_credits": 0,
        "billing_model": MODEL,
        "billing_account_id": projection["billing_account_id"],
        "as_of": projection["as_of"],
        "not_available": sorted(set(not_available)),
    }


def _with_account_usage(session, context, projection, at):
    """The organization-wide settled usage this period (the member projection carries only the member's)."""
    if projection["member_user_id"] is None:
        projection["account_used_this_period"] = projection["credits"]["used_this_period"]
        return projection
    account = project_billing_account(session, billing_account_id=context.billing_account_id, at=at)
    projection["account_used_this_period"] = account["credits"]["used_this_period"]
    return projection


def modern_usage_meter_state(session, *, context, user_id=None, app_config=None, at=None):
    """``get_usage_meter_state`` for a modern organization: same keys, internal credit units, pure read.

    ``user_id`` (an active member of the context organization) adds the member view: ``remaining`` is what
    that member may spend. Extra keys: ``billing_model``, ``billing_account_id``, ``as_of``,
    ``next_allocation_at`` and ``not_available`` (fields with no authoritative source yet, returned None).
    """
    _require(context)
    with session.no_autoflush:
        projection, terms = _account_and_terms(session, context, member_user_id=user_id, at=at)
        _with_account_usage(session, context, projection, _parse(projection["as_of"]))
        return _meter(projection, terms, app_config or {})


# ---------------------------------------------------------------------------
# GET /api/v1/billing/status
# ---------------------------------------------------------------------------

def modern_billing_status(session, *, context, user, app_config, usage_warning_fields, is_admin=False,
                          at=None):
    """The ``GET /api/v1/billing/status`` payload for a modern organization (pure read).

    The route answers with this payload instead of the legacy body, before any legacy pre-read
    (``bootstrap_legacy_credits``, the admin plan override, Stripe). ``usage_warning_fields`` is the route's
    ``_usage_warning_fields`` (one implementation of the warning bands). ``is_admin`` is reported as is and
    never impersonates a plan (ADR: internal accounts need explicit internal funding). ``tool_entitlements``
    are returned undecorated; the route adds connector state exactly as it does today (connector settings
    are not billing state).
    """
    from .tool_registry import get_context_budget, get_tool_entitlements

    _require(context)
    with session.no_autoflush:
        projection, terms = _account_and_terms(session, context, member_user_id=user.id, at=at)
        _with_account_usage(session, context, projection, _parse(projection["as_of"]))
        meter = _meter(projection, terms, app_config)
        account = session.get(BillingAccount, context.billing_account_id)
        subscription = projection["subscription"]
        schedule = projection["scheduled_plan_change"]
        plan_key = meter["plan_key"]
        catalog = get_plan_catalog(app_config)
        not_available = list(meter["not_available"])

        cancelling = bool(subscription and subscription["status"] == "cancel_at_period_end") \
            or bool(schedule and schedule["kind"] == "cancellation")
        scheduled_plan = None
        if schedule and schedule["kind"] != "cancellation":
            scheduled_plan = public_plan_key(schedule["target_plan_key"], None, app_config)
            if scheduled_plan is None:
                not_available.append("scheduled_plan_change")
        interval = _INTERVALS.get(subscription["billing_interval"]) if subscription else None
        if subscription and interval is None:
            not_available.append("billing_interval")
        status = subscription["status"] if subscription else None
        # Capabilities (models, tools, context) are configuration keyed by plan; with no recognized plan they
        # fall to the lowest tier (fail closed). This is not a billing number.
        access_plan_key = plan_key or "free"
        cycle_limit = meter["cycle_limit"]
        current_period_end = _naive(subscription["term_ends_at"]) if subscription else None
        stripe_subscription_id = _stripe_subscription_id(session, subscription["subscription_id"]) \
            if subscription is not None else None
        usage_meta = usage_warning_fields(cycle_limit, meter["used"])

        return {
            "plan_key": plan_key,
            "plan": deepcopy(catalog.get(plan_key) or {}),
            "is_admin": bool(is_admin),
            "subscription_status": _STATUS_SPELLING.get(status, status),
            "cancel_at_period_end": cancelling,
            "current_period_end": current_period_end.isoformat() if current_period_end else None,
            "scheduled_plan_change": scheduled_plan,
            "billing_interval": interval,
            "access_restricted": bool(projection["access_restricted"]["restricted"]),
            "effective_plan_key": plan_key,
            "credits_remaining": tokens_to_credits(meter["remaining"], precision=1),
            "monthly_credit_limit": tokens_to_credits(meter["monthly_limit"], precision=0),
            "credits_used": tokens_to_credits(meter["used"], precision=1),
            "usage_scope": meter["scope"],
            "cycle_credit_limit": tokens_to_credits(cycle_limit, precision=0),
            "cycle_reset_at": meter["reset_at"].isoformat() if meter["reset_at"] else None,
            "purchased_credits_this_cycle": tokens_to_credits(meter["overage_tokens"], precision=0),
            "persistent_credits": tokens_to_credits(meter["persistent_credits"], precision=1),
            # The 300K limited-time offer is personal legacy state; a modern account holds no such credits.
            "300k_limited_time_credits_remaining": tokens_to_credits(0, precision=1),
            "has_300k_limited_time": False,
            "founder_credits_remaining": tokens_to_credits(0, precision=1),
            "is_founder": False,
            "overage_credits_this_cycle": tokens_to_credits(meter["overage_tokens"], precision=0),
            # The modern ledger stops at zero: the soft stop and the block are both the period allocation.
            "credit_soft_stop_limit": tokens_to_credits(cycle_limit, precision=0),
            "credit_block_limit": tokens_to_credits(cycle_limit, precision=0),
            "allowed_model_types": get_allowed_model_types(access_plan_key, app_config),
            "default_model_type": get_default_model_type(access_plan_key, app_config),
            "context_budget": get_context_budget(access_plan_key),
            "tool_entitlements": get_tool_entitlements(access_plan_key),
            "stripe_customer_id": account.processor_customer_id if account.processor == "stripe" else None,
            "stripe_subscription_id": stripe_subscription_id,
            "usage_percent": usage_meta.get("usage_percent"),
            "usage_warning_level": usage_meta.get("usage_warning_level"),
            # Additive fields: the model that answered and every field returned None for lack of a source.
            "billing_model": MODEL,
            "billing_account_id": projection["billing_account_id"],
            "projection_version": projection["projection_version"],
            "as_of": projection["as_of"],
            "not_available": sorted(set(not_available)),
        }


def _stripe_subscription_id(session, subscription_id):
    """The processor's subscription id when the Phase 4 subscription is a Stripe one."""
    from .models_billing_phase4 import BillingSubscription

    row = session.execute(
        select(BillingSubscription.processor, BillingSubscription.external_subscription_id)
        .where(BillingSubscription.id == subscription_id)
    ).one_or_none()
    return row.external_subscription_id if row is not None and row.processor == "stripe" else None


# ---------------------------------------------------------------------------
# Organization gates (app/orgs.py and the team routes)
# ---------------------------------------------------------------------------

def modern_org_gates(session, *, context, app_config=None, at=None):
    """The plan, seat and collaboration facts the organization gates read, for a modern organization.

    * ``plan_key``: the public plan of the active base-plan entitlement (None when none is recognized).
    * ``max_total_paid_seats``: the effective Phase 8 seat commitment; without one, the plan definition's
      declared ``included_seats``; without either, 0 (no paid seat is authorized; listed in
      ``not_available``). Never ``None``, which the gates read as unlimited.
    * ``billing_current``: the subscription is in good standing (active, or active with a scheduled
      cancellation) and the account is not restricted; a contract-backed plan without a subscription is
      current while its contract is paid.
    * ``seat_occupancy``: active members in paid roles (Phase 8 occupancy).
    """
    _require(context)
    with session.no_autoflush:
        projection, terms = _account_and_terms(session, context, at=at)
        plan_key = public_plan_key(terms["definition_key"], terms["plan_source_type"], app_config)
        not_available = []
        if plan_key is None:
            not_available.append("plan_key")
        commitment = projection["seats"]["commitment"]
        if commitment is not None:
            seat_limit, seat_source = int(commitment), "seat_commitment"
        elif terms["included_seats"] is not None:
            seat_limit, seat_source = int(terms["included_seats"]), "plan_included_seats"
        else:
            seat_limit, seat_source = 0, None
            not_available.append("max_total_paid_seats")
        subscription = projection["subscription"]
        restricted = bool(projection["access_restricted"]["restricted"])
        if subscription is not None:
            billing_current = subscription["status"] in _CURRENT_SUBSCRIPTION_STATES and not restricted
        elif terms["plan_source_type"] == "enterprise_contract":
            billing_current = projection["contract_access"]["state"] == "paid" and not restricted
        else:
            billing_current = not restricted
        return {
            "billing_model": MODEL,
            "organization_id": projection["organization_id"],
            "billing_account_id": projection["billing_account_id"],
            "as_of": projection["as_of"],
            "plan_key": plan_key,
            "plan_rank": PLAN_RANK.get(plan_key, 0) if plan_key else 0,
            "plan_source_type": terms["plan_source_type"],
            "subscription_status": subscription["status"] if subscription else None,
            "billing_current": billing_current,
            "access_restricted": restricted,
            "max_total_paid_seats": seat_limit,
            "seat_limit_source": seat_source,
            "seat_occupancy": projection["seats"]["occupancy"],
            "not_available": not_available,
        }


def modern_org_gates_for(session, organization_id, *, app_config=None, config=None):
    """``modern_org_gates`` through the dispatch contract: None for a legacy organization.

    Raises ``BillingFamilyDisabledError`` for a modern organization while the readers family is off:
    nobody answers, and a modern organization never falls back to its legacy columns.
    """
    from .billing_cutover import modern_context

    if not organization_id:
        return None
    context = modern_context(session, family=READERS_FAMILY, organization_id=organization_id, config=config)
    if context is None:
        return None
    return modern_org_gates(session, context=context, app_config=app_config)
