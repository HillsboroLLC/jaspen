"""Versioned AI routing and customer-credit policy.

This module is deliberately provider-client agnostic.  It decides *where* an
operation should run and *what a successful result should cost*; provider
adapters execute the request and the normal billing layer settles it.

Both policies can run in shadow mode so development can compare the proposed
decision with the legacy path without changing customer-visible behaviour.
"""

from __future__ import annotations

import math
import os
import re
from copy import deepcopy
from decimal import Decimal, ROUND_CEILING


ROUTER_VERSION = "jaspen-router-v1"
CREDIT_POLICY_VERSION = "provider-cost-3600-v1"
CREDITS_PER_PROVIDER_DOLLAR = Decimal("3600")
INTERNAL_UNITS_PER_CREDIT = Decimal("1000")

ROUTER_MODE_ENV = "JASPEN_AI_ROUTER_MODE"
CREDIT_POLICY_MODE_ENV = "JASPEN_CREDIT_POLICY_MODE"

ROUTE_ROUTINE = "routine"
ROUTE_STANDARD = "standard_judgment"
ROUTE_STRUCTURED = "structured_consequential"
ROUTE_EXCEPTIONAL = "exceptional_depth"

CANONICAL_ANTHROPIC_MODELS = {
    "claude_haiku": "claude-haiku-4-5",
    "claude_sonnet": "claude-sonnet-5",
    "claude_opus": "claude-opus-4-8",
}

_STRUCTURED_OPERATIONS = frozenset({
    "scorecard_generation",
    "score_next",
    "score_batch",
    "batch_ranking",
    "batch_clarification",
    "scenario_generation",
    "execution_plan",
    "execution_plan_refinement",
    "report_generation",
    "decision_impact_narrative",
    "connector_idea_generation",
    "portfolio_analysis",
})

_ROUTINE_OPERATIONS = frozenset({
    "knowledge_refresh",
    "metadata_extraction",
    "classification",
    "short_follow_up",
})

_CONSEQUENCE_TERMS = frozenset({
    "million", "budget", "investment", "acquisition", "merger", "board",
    "regulatory", "compliance", "security", "layoff", "restructuring",
    "migration", "transformation", "enterprise", "contract", "commit",
})
_AMBIGUITY_TERMS = frozenset({
    "uncertain", "unknown", "ambiguous", "trade-off", "tradeoff", "scenario",
    "assumption", "conflicting", "sensitivity", "downside", "irreversible",
})
_ROUTINE_PHRASES = frozenset({
    "thanks", "thank you", "got it", "yes", "no", "continue", "go ahead",
    "what does that mean", "explain that", "summarize", "rename it",
})

# Provider configuration can outlive a model retirement. Normalize only known
# Anthropic retirements here so automatic routing cannot select an unavailable
# model or silently drift into a different capability tier downstream.
_RETIRED_ANTHROPIC_MODEL_REPLACEMENTS = {
    "claude-3-5-haiku-20241022": "claude-haiku-4-5-20251001",
    "claude-3-7-sonnet-latest": CANONICAL_ANTHROPIC_MODELS["claude_sonnet"],
    "claude-3-7-sonnet-20250219": CANONICAL_ANTHROPIC_MODELS["claude_sonnet"],
    "claude-3-5-sonnet-20241022": CANONICAL_ANTHROPIC_MODELS["claude_sonnet"],
    "claude-sonnet-4-20250514": CANONICAL_ANTHROPIC_MODELS["claude_sonnet"],
    "claude-sonnet-4-5-20250929": CANONICAL_ANTHROPIC_MODELS["claude_sonnet"],
    "claude-sonnet-4-6": CANONICAL_ANTHROPIC_MODELS["claude_sonnet"],
    "claude-opus-4-20250514": "claude-opus-4-8",
    "claude-opus-4-1-20250805": "claude-opus-4-8",
}


def resolve_anthropic_model(model_name, *, model_key="claude_sonnet"):
    """Resolve configured/legacy Anthropic IDs to one supported production ID.

    The current model map is the source of truth. Known retired IDs are
    accepted only as inbound compatibility values and are never sent to the
    provider. Empty values fall back to the canonical model for the requested
    routing tier.
    """
    fallback = CANONICAL_ANTHROPIC_MODELS.get(
        str(model_key or "claude_sonnet").strip(),
        CANONICAL_ANTHROPIC_MODELS["claude_sonnet"],
    )
    configured = str(model_name or fallback).strip()
    return _RETIRED_ANTHROPIC_MODEL_REPLACEMENTS.get(configured, configured)


def _mode(value, default="shadow"):
    normalized = str(value or default).strip().lower()
    return normalized if normalized in {"shadow", "active", "off"} else default


def router_mode(config=None):
    config = config if isinstance(config, dict) else {}
    return _mode(config.get(ROUTER_MODE_ENV) or os.getenv(ROUTER_MODE_ENV), "shadow")


def credit_policy_mode(config=None):
    config = config if isinstance(config, dict) else {}
    return _mode(config.get(CREDIT_POLICY_MODE_ENV) or os.getenv(CREDIT_POLICY_MODE_ENV), "shadow")


def credits_for_provider_cost(provider_cost_usd, *, internal=True):
    """Return a conservative (ceiling) charge for one successful result.

    Public Jaspen credits are backed by 1,000 integer ledger units today.  A
    provider dollar therefore maps to 3,600 public credits or 3.6M internal
    units.  Rounding up prevents small calls from falling below the margin
    policy while retaining sub-credit precision in the existing ledger.
    """
    try:
        cost = Decimal(str(provider_cost_usd or 0))
    except Exception:
        return 0
    if cost <= 0:
        return 0
    multiplier = CREDITS_PER_PROVIDER_DOLLAR
    if internal:
        multiplier *= INTERNAL_UNITS_PER_CREDIT
    return int((cost * multiplier).to_integral_value(rounding=ROUND_CEILING))


def provider_cost_for_credits(credits, *, internal=False):
    try:
        amount = Decimal(str(credits or 0))
    except Exception:
        return Decimal("0")
    if amount <= 0:
        return Decimal("0")
    if internal:
        amount /= INTERNAL_UNITS_PER_CREDIT
    return amount / CREDITS_PER_PROVIDER_DOLLAR


def is_subsidized_usage(*, plan_key=None, is_test=False, is_admin=False, is_comped=False):
    return bool(
        str(plan_key or "free").strip().lower() == "free"
        or is_test
        or is_admin
        or is_comped
    )


def _normalized_text(value):
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def classify_request(
    *,
    operation_type="conversation",
    text="",
    attachment_count=0,
    context_tokens=0,
    alternatives_count=0,
    structured_output=False,
    validation_failures=0,
):
    """Classify by work shape and consequence, never by customer plan."""
    operation = str(operation_type or "conversation").strip().lower()
    normalized = _normalized_text(text)
    reasons = [f"operation:{operation}"]
    consequence_hits = sum(1 for term in _CONSEQUENCE_TERMS if term in normalized)
    ambiguity_hits = sum(1 for term in _AMBIGUITY_TERMS if term in normalized)

    if operation in _ROUTINE_OPERATIONS:
        return ROUTE_ROUTINE, reasons + ["routine_operation"]

    if operation in _STRUCTURED_OPERATIONS or structured_output:
        route_class = ROUTE_STRUCTURED
        reasons.append("structured_or_consequential_output")
    elif (
        normalized in _ROUTINE_PHRASES
        or (
            len(normalized) <= 80
            and not attachment_count
            and not alternatives_count
            and consequence_hits == 0
            and ambiguity_hits == 0
        )
    ):
        return ROUTE_ROUTINE, reasons + ["short_low_complexity_turn"]
    else:
        route_class = ROUTE_STANDARD
        reasons.append("standard_judgment")

    depth_score = 0
    if consequence_hits >= 2:
        depth_score += 1
    if ambiguity_hits >= 2:
        depth_score += 1
    if int(context_tokens or 0) >= 18_000:
        depth_score += 1
    if int(attachment_count or 0) >= 3:
        depth_score += 1
    if int(alternatives_count or 0) >= 4:
        depth_score += 1
    if int(validation_failures or 0) >= 1:
        depth_score += 2

    # Opus is exceptional, not a generic synonym for "long prompt".
    if depth_score >= 4:
        route_class = ROUTE_EXCEPTIONAL
        reasons.extend([
            f"depth_score:{depth_score}",
            f"consequence_signals:{consequence_hits}",
            f"ambiguity_signals:{ambiguity_hits}",
        ])
    return route_class, reasons


def _configured_model(models, key, fallback):
    value = (models or {}).get(key) if isinstance(models, dict) else None
    configured = str(value or fallback).strip()
    if str(key or "").startswith("claude_"):
        return resolve_anthropic_model(configured, model_key=key)
    return configured


def routing_decision(
    *,
    provider_models=None,
    operation_type="conversation",
    text="",
    attachment_count=0,
    context_tokens=0,
    alternatives_count=0,
    structured_output=False,
    validation_failures=0,
):
    route_class, reasons = classify_request(
        operation_type=operation_type,
        text=text,
        attachment_count=attachment_count,
        context_tokens=context_tokens,
        alternatives_count=alternatives_count,
        structured_output=structured_output,
        validation_failures=validation_failures,
    )
    models = provider_models if isinstance(provider_models, dict) else {}
    haiku = _configured_model(models, "claude_haiku", CANONICAL_ANTHROPIC_MODELS["claude_haiku"])
    sonnet = _configured_model(models, "claude_sonnet", CANONICAL_ANTHROPIC_MODELS["claude_sonnet"])
    opus = _configured_model(models, "claude_opus", CANONICAL_ANTHROPIC_MODELS["claude_opus"])
    flash = _configured_model(models, "gemini_flash", "gemini-2.5-flash")
    pro = _configured_model(models, "gemini_pro", "gemini-3.8-flash")

    if route_class == ROUTE_ROUTINE:
        routes = [
            {"provider": "anthropic", "model_key": "claude_haiku", "model": haiku},
            {"provider": "gemini", "model_key": "gemini_flash", "model": flash},
        ]
    elif route_class == ROUTE_EXCEPTIONAL:
        routes = [
            {"provider": "anthropic", "model_key": "claude_opus", "model": opus},
            {"provider": "anthropic", "model_key": "claude_sonnet", "model": sonnet},
            {"provider": "gemini", "model_key": "gemini_pro", "model": pro},
        ]
    else:
        routes = [
            {"provider": "anthropic", "model_key": "claude_sonnet", "model": sonnet},
            {"provider": "gemini", "model_key": "gemini_pro", "model": pro},
            {"provider": "gemini", "model_key": "gemini_flash", "model": flash},
        ]

    return {
        "router_version": ROUTER_VERSION,
        "route_class": route_class,
        "routing_reasons": reasons,
        "routes": deepcopy(routes),
        "selected_provider": routes[0]["provider"],
        "selected_model": routes[0]["model"],
        "escalated": route_class == ROUTE_EXCEPTIONAL,
    }


def shadow_comparison(*, legacy_routes, proposed_decision):
    legacy = deepcopy(legacy_routes) if isinstance(legacy_routes, list) else []
    proposed = deepcopy((proposed_decision or {}).get("routes") or [])
    legacy_first = legacy[0] if legacy else {}
    proposed_first = proposed[0] if proposed else {}
    return {
        "legacy_provider": legacy_first.get("provider"),
        "legacy_model": legacy_first.get("model"),
        "proposed_provider": proposed_first.get("provider"),
        "proposed_model": proposed_first.get("model"),
        "would_change": (
            legacy_first.get("provider") != proposed_first.get("provider")
            or legacy_first.get("model") != proposed_first.get("model")
        ),
    }
