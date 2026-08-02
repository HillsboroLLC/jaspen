import calendar
from copy import deepcopy
from datetime import datetime
import math
import os

try:
    from sqlalchemy.orm.attributes import flag_modified as _flag_modified
except ImportError:
    def _flag_modified(obj, key):
        pass

PLAN_ALIASES = {
    # Business is now the canonical plan key. Accept the former key in old
    # subscription metadata and persisted records during the transition.
    'enterprise': 'business',
    'growth': 'team',
    'transform': 'business',
    'transform_basic': 'business',
    'transform_standard': 'business',
    'transform_premium': 'business',
    'transform_enterprise': 'business',
    'founder': 'essential',
}

PLAN_RANK = {
    'free': 0,
    'starter': 1,
    'essential': 2,
    'team': 3,
    'business': 4,
    'enterprise_custom': 5,
}

DEFAULT_PLAN_CATALOG = {
    'free': {
        'label': 'Free',
        'monthly_price_usd': 0,
        'monthly_credits': 300_000,
        'self_serve': True,
        'sales_only': False,
        'description': 'Enough Thinking Power to test Jaspen on a focused evaluation with complete inputs.',
        'project_evaluation_estimate': '~1 focused evaluation with complete inputs',
    },
    'starter': {
        'label': 'Starter',
        'monthly_price_usd': 7,
        'annual_monthly_price_usd': 6,
        'monthly_credits': 1_000_000,
        'self_serve': True,
        'sales_only': False,
        'description': 'Light personal use for approximately 3–4 typical project evaluations.',
        'project_evaluation_estimate': '~3–4 typical project evaluations',
    },
    'essential': {
        'label': 'Essential',
        'monthly_price_usd': 39,
        'annual_monthly_price_usd': 32,
        'monthly_credits': 7_000_000,
        'self_serve': True,
        'sales_only': False,
        'description': 'Turn ideas into clear decisions across approximately 17–29 typical project evaluations.',
        'project_evaluation_estimate': '~17–29 typical project evaluations',
    },
    'team': {
        'label': 'Team',
        'monthly_price_usd': 129,
        'annual_monthly_price_usd': 107,
        'price_model': 'per_seat',
        'min_seats': 3,
        'included_seats': 3,
        'additional_seat_price': 25,
        'monthly_credits': 29_000_000,
        'self_serve': True,
        'sales_only': False,
        'description': 'Align your team across approximately 57–96 typical project evaluations from the shared allowance.',
        'project_evaluation_estimate': '~57–96 typical project evaluations across the shared allowance',
        'max_admin_seats': 3,
        'max_total_paid_seats': 4,
        'max_viewer_seats': None,
    },
    'business': {
        'label': 'Business',
        'monthly_price_usd': 299,
        'annual_monthly_price_usd': 249,
        'price_model': 'per_seat',
        'min_seats': 5,
        'included_seats': 5,
        'included_admins': 1,
        'additional_seat_price': 30,
        'monthly_credits': 80_000_000,
        'self_serve': True,
        'sales_only': False,
        'description': 'Bring structure and consistency across approximately 133–222 typical project evaluations from the shared allowance.',
        'project_evaluation_estimate': '~133–222 typical project evaluations across the shared allowance',
        'max_admins': 5,
        'max_admin_seats': 5,
        'max_total_paid_seats': 10,
        'collaborators': None,
        'viewer_seats': None,
        'max_viewer_seats': None,
    },
    'enterprise_custom': {
        'label': 'Enterprise',
        'monthly_price_usd': None,
        'monthly_credits': None,
        'self_serve': False,
        'sales_only': True,
        'description': 'Custom annual deployment scoped with Jaspen Sales.',
        'max_admin_seats': None,
        'max_total_paid_seats': None,
        'max_viewer_seats': None,
    },
}

CREDIT_PACK_ALIASES = {
    'pack_1000': 'credits_3000',
    'pack_5000': 'credits_8000',
    'pack_20000': 'credits_18000',
}

DEFAULT_CREDIT_PACKS = {
    'credits_3000': {
        'label': '3,000 credits',
        'credits': 3_000_000,
        'price_usd': 10,
    },
    'credits_8000': {
        'label': '8,000 credits',
        'credits': 8_000_000,
        'price_usd': 25,
    },
    'credits_18000': {
        'label': '18,000 credits',
        'credits': 18_000_000,
        'price_usd': 50,
    },
}
# Backward-compatible alias used by legacy callsites.
DEFAULT_OVERAGE_PACKS = DEFAULT_CREDIT_PACKS

SHARED_POOL_PLANS = {'team', 'business', 'enterprise_custom'}
SOFT_STOP_GRACE_MULTIPLIER = 1.05
TOKENS_PER_CREDIT = 1000

# Threshold for the "you're almost out" warning surfaced to the frontend.
# When a user's Thinking Power drops below this fraction of their cycle limit,
# responses include `thinking_power_low_warning: true` and the UI nudges them
# to top up. (Soft cap with grace at 0% lives in SOFT_STOP_GRACE_MULTIPLIER.)
THINKING_POWER_LOW_WARNING_PCT = 10.0

# ── Anthropic published prices ($ per million tokens) ──────────────────────
# STICKY-ON-DECREASE policy (Bailey, 2026-05-17): we update these values
# upward when Anthropic raises prices, but never downward — users don't know
# Claude is the primary engine, and we use multiple agents (Gemini for
# processing, Claude for judgment), so a Claude price drop shouldn't
# automatically reduce what we charge.
#
# Every Claude-routed call's actual cost is computed from these numbers and
# multiplied by MARGIN_MULTIPLIER, then debited from the user's plan budget.
ANTHROPIC_PRICES_USD_PER_M = {
    # Opus 4.x — premium reasoning
    'claude-opus-4-8':             {'input': 5.00,  'output': 25.00},
    'claude-opus-4-7':             {'input': 5.00,  'output': 25.00},
    'claude-opus-4-1-20250805':    {'input': 15.00, 'output': 75.00},
    'claude-opus-4-20250514':      {'input': 15.00, 'output': 75.00},
    # Sonnet 4.x — workhorse
    'claude-sonnet-4-6':           {'input': 3.00,  'output': 15.00},
    'claude-sonnet-4-5-20250929':  {'input': 3.00,  'output': 15.00},
    'claude-sonnet-4-20250514':    {'input': 3.00,  'output': 15.00},
    # Haiku 4.5 — fast/cheap
    'claude-haiku-4-5-20251001':   {'input': 1.00,  'output': 5.00},
    'claude-haiku-4-5':            {'input': 1.00,  'output': 5.00},
    # Fallback when an unknown Claude model surfaces — assume Sonnet rates
    '__default_claude__':          {'input': 3.00,  'output': 15.00},
}

# Google AI standard paid-tier prices ($ per million tokens). Gemini output
# pricing includes thinking tokens.
GEMINI_PRICES_USD_PER_M = {
    'gemini-2.5-flash': {'input': 0.30, 'output': 2.50},
    'gemini-2.5-pro': {'input': 1.25, 'output': 10.00},
    '__default_gemini__': {'input': 1.25, 'output': 10.00},
}

# Margin multiplier on provider cost. Provider cost × this number = what
# we debit from the user's Thinking Power budget. Default 3.0× (≈67% margin).
# Tunable via env so we can adjust without code changes if provider prices
# change significantly.
MARGIN_MULTIPLIER = float(os.getenv('JASPEN_MARGIN_MULTIPLIER', '3.0'))

# Plan-level Thinking Power budget denominator. Provider cost is multiplied by
# MARGIN_MULTIPLIER before comparison with this value, as established by the
# original Thinking Power commit (2149e33a). Consequently the raw provider-cost
# ceiling is `budget / margin`; changing that commercial formula requires an
# explicit pricing decision. Values remain environment-tunable.
PLAN_THINKING_BUDGET_USD = {
    'free':       float(os.getenv('JASPEN_BUDGET_FREE',       '0.25')),
    'starter':    float(os.getenv('JASPEN_BUDGET_STARTER',    '2.00')),
    'essential':  float(os.getenv('JASPEN_BUDGET_ESSENTIAL', '13.00')),
    'team':       float(os.getenv('JASPEN_BUDGET_TEAM',      '43.00')),
    'business': float(os.getenv('JASPEN_BUDGET_BUSINESS') or os.getenv('JASPEN_BUDGET_ENTERPRISE', '100.00')),
}


def anthropic_cost_usd(model_name, input_tokens, output_tokens):
    """Anthropic's $ cost for one completion. Sticky-on-decrease per the
    ANTHROPIC_PRICES_USD_PER_M table. Unknown Claude models fall back to
    Sonnet rates; non-Claude models return 0."""
    if not model_name:
        return 0.0
    name = str(model_name).strip().lower()
    if not name.startswith('claude'):
        # Other providers are handled by provider_cost_usd().
        return 0.0
    prices = ANTHROPIC_PRICES_USD_PER_M.get(name) or ANTHROPIC_PRICES_USD_PER_M['__default_claude__']
    in_tokens = max(0, int(input_tokens or 0))
    out_tokens = max(0, int(output_tokens or 0))
    return (in_tokens * prices['input'] + out_tokens * prices['output']) / 1_000_000.0


def provider_cost_usd(model_name, input_tokens, output_tokens):
    """Published provider cost for one completion.

    Unknown Gemini models conservatively use Pro rates; unknown providers
    remain visible in telemetry but return zero until a rate is configured.
    """
    name = str(model_name or '').strip().lower()
    if name.startswith('claude'):
        return anthropic_cost_usd(name, input_tokens, output_tokens)
    if not name.startswith('gemini'):
        return 0.0
    prices = GEMINI_PRICES_USD_PER_M.get(name) or GEMINI_PRICES_USD_PER_M['__default_gemini__']
    in_tokens = max(0, int(input_tokens or 0))
    out_tokens = max(0, int(output_tokens or 0))
    return (in_tokens * prices['input'] + out_tokens * prices['output']) / 1_000_000.0


def plan_thinking_budget_usd(plan_key):
    """Monthly Thinking Power budget denominator in margin-adjusted USD."""
    canonical = normalize_plan_key(plan_key)
    return PLAN_THINKING_BUDGET_USD.get(canonical, PLAN_THINKING_BUDGET_USD['essential'])


def thinking_power_debit_pct(plan_key, model_name, input_tokens, output_tokens):
    """How much of a user's monthly Thinking Power % to debit for one call.

    Returns a float in 0–100. Supported Claude and Gemini models debit from
    the same plan-level provider-cost ceiling.
    """
    raw_cost = provider_cost_usd(model_name, input_tokens, output_tokens)
    if raw_cost <= 0:
        return 0.0
    budget = plan_thinking_budget_usd(plan_key)
    if budget <= 0:
        # Free plan with zero budget → any metered provider call is "100%" so the
        # caller can decide what to do (typically: deny or pop the paywall).
        return 100.0
    return (raw_cost * MARGIN_MULTIPLIER / budget) * 100.0


def credits_for_completion(plan_key, model_name, input_tokens, output_tokens):
    """Credits to debit (in the legacy 1 credit = 1000 tokens unit) for one
    completion, derived from provider $ cost × MARGIN_MULTIPLIER. This is
    the bridge between the new $-based model and the existing credits-based
    consume_credits() machinery — we don't have to rip out the old plumbing.
    """
    debit_pct = thinking_power_debit_pct(plan_key, model_name, input_tokens, output_tokens)
    if debit_pct <= 0:
        return 0
    monthly_limit = get_monthly_credit_limit(plan_key, {}) or 0
    if monthly_limit <= 0:
        return 0
    # Debit %  →  fraction of monthly token cap
    return int(round(monthly_limit * (debit_pct / 100.0)))

MODEL_TYPE_ALIASES = {
    'pluto-1': 'pluto',
    'orbit-1': 'orbit',
    'titan-1': 'titan',
}

MODEL_TYPE_ORDER = ['pluto', 'orbit', 'titan']

DEFAULT_MODEL_CATALOG = {
    'pluto': {
        'label': 'Pluto',
        'version': '1.0',
        'description': 'Fastest model for core intake and scorecard workflows.',
        'min_plan': 'free',
        'default_llm_model': 'claude-haiku-4-5',
    },
    'orbit': {
        'label': 'Orbit',
        'version': '1.0',
        'description': 'Balanced depth and speed for broader cross-functional synthesis.',
        'min_plan': 'free',
        'default_llm_model': 'claude-sonnet-4-6',
    },
    'titan': {
        'label': 'Titan',
        'version': '1.0',
        'description': 'Highest-depth reasoning for complex multi-team initiatives.',
        'min_plan': 'free',
        'default_llm_model': 'claude-opus-4-8',
    },
}


def normalize_plan_key(plan_key):
    """Return canonical plan keys; unknown values are passed through for validation upstream."""
    if not plan_key:
        return 'free'
    normalized = str(plan_key).strip().lower()
    return PLAN_ALIASES.get(normalized, normalized)


def normalize_model_type(model_type):
    if not model_type:
        return ''
    normalized = str(model_type).strip().lower()
    return MODEL_TYPE_ALIASES.get(normalized, normalized)


def normalize_credit_pack_key(pack_key):
    if not pack_key:
        return ''
    normalized = str(pack_key).strip().lower()
    return CREDIT_PACK_ALIASES.get(normalized, normalized)


def _plan_rank(plan_key):
    canonical = normalize_plan_key(plan_key)
    return PLAN_RANK.get(canonical, 0)


def get_plan_catalog(app_config):
    """Plan catalog enriched with any configured Stripe price ids."""
    catalog = deepcopy(DEFAULT_PLAN_CATALOG)
    stripe_price_ids = app_config.get('STRIPE_PRICE_IDS', {}) or {}
    for key, value in catalog.items():
        value['plan_key'] = key
        value['stripe_price_id'] = stripe_price_ids.get(key)
        value['stripe_annual_price_id'] = (app_config.get('STRIPE_ANNUAL_PRICE_IDS', {}) or {}).get(key)
        value['additional_seat_price_id'] = (app_config.get('STRIPE_ADDITIONAL_SEAT_PRICE_IDS', {}) or {}).get(key)
    return catalog


def get_credit_packs(app_config):
    """Credit packs enriched with configured Stripe price ids."""
    packs = deepcopy(DEFAULT_CREDIT_PACKS)
    stripe_pack_ids = (
        app_config.get('STRIPE_CREDIT_PACK_PRICE_IDS')
        or app_config.get('STRIPE_OVERAGE_PACK_PRICE_IDS')
        or {}
    )
    for key, value in packs.items():
        value['pack_key'] = key
        value['stripe_price_id'] = stripe_pack_ids.get(key)
    return packs


def get_overage_packs(app_config):
    """Backward-compatible alias for legacy references."""
    return get_credit_packs(app_config)


def get_model_catalog(app_config, *, include_backing_ids=False):
    catalog = deepcopy(DEFAULT_MODEL_CATALOG)
    for key, value in catalog.items():
        value['model_type'] = key
        if include_backing_ids:
            backing_ids = app_config.get('MODEL_TYPE_BACKING_IDS', {}) or {}
            value['llm_model'] = backing_ids.get(key) or value.get('default_llm_model')
        value.pop('default_llm_model', None)
    return catalog


def get_allowed_model_types(plan_key, app_config):
    catalog = get_model_catalog(app_config)
    rank = _plan_rank(plan_key)
    allowed = []
    for model_type in MODEL_TYPE_ORDER:
        item = catalog.get(model_type) or {}
        min_plan = item.get('min_plan', 'free')
        if rank >= _plan_rank(min_plan):
            allowed.append(model_type)
    return allowed or ['pluto']


def get_default_model_type(plan_key, app_config):
    allowed = get_allowed_model_types(plan_key, app_config)
    return allowed[0] if allowed else 'pluto'


def is_model_type_allowed(plan_key, model_type, app_config):
    model_type = normalize_model_type(model_type)
    if not model_type:
        return False
    return model_type in get_allowed_model_types(plan_key, app_config)


def get_monthly_credit_limit(plan_key, app_config):
    plan_key = normalize_plan_key(plan_key)
    catalog = get_plan_catalog(app_config)
    return (catalog.get(plan_key) or {}).get('monthly_credits')


def tokens_to_credits(token_value, *, precision=1):
    if token_value is None:
        return None
    try:
        credits = float(token_value) / float(TOKENS_PER_CREDIT)
    except Exception:
        return None
    if precision is None:
        return credits
    precision = int(precision)
    rounded = round(credits, precision)
    if precision <= 0:
        return int(rounded)
    return rounded


def credits_to_tokens(credit_value):
    if credit_value is None:
        return None
    try:
        return int(round(float(credit_value) * float(TOKENS_PER_CREDIT)))
    except Exception:
        return None


def _coerce_non_negative_int(value, default=0):
    try:
        coerced = int(value)
    except Exception:
        coerced = int(default)
    return max(0, coerced)


def _cycle_reset_due(last_reset, now):
    if not last_reset:
        return True
    year = int(last_reset.year)
    month = int(last_reset.month)
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1
    day = min(int(last_reset.day), calendar.monthrange(next_year, next_month)[1])
    next_reset = datetime(
        next_year,
        next_month,
        day,
        int(last_reset.hour),
        int(last_reset.minute),
        int(last_reset.second),
        int(last_reset.microsecond),
    )
    return now >= next_reset


def _active_org_for_user(user):
    org_id = str(getattr(user, "active_organization_id", "") or "").strip()
    if not org_id:
        return None
    from app.models import Organization
    return Organization.query.filter_by(id=org_id).first()


def _resolve_org_pool(user, app_config, now=None, force_reset=False):
    now = now or datetime.utcnow()
    org = _active_org_for_user(user)
    if org is None:
        return None

    settings = org.settings if isinstance(org.settings, dict) else {}
    meter = settings.get("thinking_power") if isinstance(settings.get("thinking_power"), dict) else {}
    monthly_limit = _coerce_non_negative_int(get_monthly_credit_limit(user.subscription_plan, app_config), default=0)
    overage_tokens = _coerce_non_negative_int(meter.get("overage_tokens"), default=0)
    cycle_limit = max(0, monthly_limit + overage_tokens)
    reset_at_raw = meter.get("cycle_reset_at")
    reset_at = None
    if isinstance(reset_at_raw, str) and reset_at_raw.strip():
        try:
            reset_at = datetime.fromisoformat(reset_at_raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            reset_at = None

    if force_reset or _cycle_reset_due(reset_at, now):
        meter["overage_tokens"] = 0
        meter["cycle_limit"] = monthly_limit
        meter["remaining"] = monthly_limit
        meter["tokens_used_this_month"] = 0
        meter["cycle_reset_at"] = now.isoformat()
        reset_at = now
    else:
        meter["overage_tokens"] = overage_tokens
        meter["cycle_limit"] = cycle_limit
        meter["remaining"] = int(meter.get("remaining", cycle_limit))
        meter["tokens_used_this_month"] = max(0, cycle_limit - int(meter.get("remaining", cycle_limit)))
        if not meter.get("cycle_reset_at"):
            meter["cycle_reset_at"] = now.isoformat()

    settings["thinking_power"] = meter
    org.settings = deepcopy(settings)
    _flag_modified(org, "settings")

    return {
        "organization": org,
        "settings": settings,
        "meter": meter,
        "monthly_limit": monthly_limit,
        "cycle_limit": int(meter.get("cycle_limit", monthly_limit)),
        "remaining": int(meter.get("remaining", monthly_limit)),
        "reset_at": reset_at,
    }


def _resolve_user_pool(user, app_config, now=None, force_reset=False):
    now = now or datetime.utcnow()
    prefs = user.ui_preferences if isinstance(user.ui_preferences, dict) else {}
    meter = prefs.get("thinking_power") if isinstance(prefs.get("thinking_power"), dict) else {}
    monthly_limit = _coerce_non_negative_int(get_monthly_credit_limit(user.subscription_plan, app_config), default=0)
    overage_tokens = _coerce_non_negative_int(meter.get("overage_tokens"), default=0)
    cycle_limit = max(0, monthly_limit + overage_tokens)
    reset_at = user.credits_reset_at
    reset_at_raw = meter.get("cycle_reset_at")
    if isinstance(reset_at_raw, str) and reset_at_raw.strip():
        try:
            reset_at = datetime.fromisoformat(reset_at_raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            pass

    if force_reset or _cycle_reset_due(reset_at, now):
        overage_tokens = 0
        cycle_limit = monthly_limit
        monthly_remaining = monthly_limit
        reset_at = now
    else:
        # `meter.remaining` is deliberately monthly/expiring only. Persistent
        # purchased credits live in their own ledger and are added for display.
        if 'remaining' in meter:
            monthly_remaining = int(meter.get('remaining', cycle_limit))
        else:
            # Preserve partially consumed legacy balances when first creating
            # the structured meter; never silently replenish them.
            from app.founder_entitlements import persistent_credit_balance
            legacy_combined = user.credits_remaining
            persistent_existing = persistent_credit_balance(user)
            monthly_remaining = (
                cycle_limit
                if legacy_combined is None
                else int(legacy_combined) - persistent_existing
            )

    meter["overage_tokens"] = overage_tokens
    meter["cycle_limit"] = cycle_limit
    meter["remaining"] = monthly_remaining
    meter["tokens_used_this_month"] = max(0, cycle_limit - monthly_remaining)
    meter["cycle_reset_at"] = reset_at.isoformat() if isinstance(reset_at, datetime) else now.isoformat()
    prefs["thinking_power"] = meter
    user.ui_preferences = deepcopy(prefs)
    _flag_modified(user, "ui_preferences")
    from app.founder_entitlements import persistent_credit_balance
    persistent_remaining = persistent_credit_balance(user)
    combined_remaining = monthly_remaining + persistent_remaining
    user.credits_remaining = combined_remaining
    user.credits_reset_at = reset_at if isinstance(reset_at, datetime) else now
    return {
        "meter": meter,
        "monthly_limit": monthly_limit,
        "cycle_limit": cycle_limit,
        "monthly_remaining": monthly_remaining,
        "persistent_remaining": persistent_remaining,
        "remaining": combined_remaining,
        "reset_at": user.credits_reset_at,
    }


def is_sales_only_plan(plan_key, app_config):
    plan_key = normalize_plan_key(plan_key)
    catalog = get_plan_catalog(app_config)
    return bool((catalog.get(plan_key) or {}).get('sales_only'))


def apply_plan_to_user(user, plan_key, app_config, reset_credits=True):
    """Apply plan defaults and optionally reset monthly credits to plan limit."""
    canonical = normalize_plan_key(plan_key)
    user.subscription_plan = canonical

    monthly_limit = get_monthly_credit_limit(canonical, app_config)
    if reset_credits:
        if canonical in SHARED_POOL_PLANS:
            user.credits_remaining = monthly_limit
            user.credits_reset_at = datetime.utcnow()
            pool = _resolve_org_pool(user, app_config, now=datetime.utcnow(), force_reset=True)
            from app.founder_entitlements import persistent_credit_balance
            user.credits_remaining = int((pool or {}).get('remaining', monthly_limit or 0)) + persistent_credit_balance(user)
        else:
            _resolve_user_pool(user, app_config, now=datetime.utcnow(), force_reset=True)
    elif monthly_limit is None and user.credits_remaining is not None:
        # Sales-led plans can be tracked outside of per-user credit counters.
        user.credits_remaining = None


def add_credits(user, amount):
    amount = int(amount or 0)
    if amount <= 0:
        return

    plan_key = normalize_plan_key(getattr(user, "subscription_plan", None))
    if plan_key in SHARED_POOL_PLANS:
        pool = _resolve_org_pool(user, {}, now=datetime.utcnow(), force_reset=False)
        if pool is not None:
            org = pool["organization"]
            settings = org.settings if isinstance(org.settings, dict) else {}
            meter = settings.get("thinking_power") if isinstance(settings.get("thinking_power"), dict) else {}
            meter["overage_tokens"] = _coerce_non_negative_int(meter.get("overage_tokens")) + amount
            meter["cycle_limit"] = _coerce_non_negative_int(meter.get("cycle_limit")) + amount
            meter["remaining"] = int(meter.get("remaining", 0)) + amount
            meter["tokens_used_this_month"] = max(0, int(meter.get("cycle_limit", 0)) - int(meter.get("remaining", 0)))
            settings["thinking_power"] = meter
            org.settings = deepcopy(settings)
            _flag_modified(org, "settings")
            from app.founder_entitlements import persistent_credit_balance
            user.credits_remaining = int(meter.get("remaining", 0)) + persistent_credit_balance(user)
            user.credits_reset_at = datetime.utcnow()
            return

    pool = _resolve_user_pool(user, {}, now=datetime.utcnow(), force_reset=False)
    meter = pool["meter"]
    meter["overage_tokens"] = _coerce_non_negative_int(meter.get("overage_tokens")) + amount
    meter["cycle_limit"] = _coerce_non_negative_int(meter.get("cycle_limit")) + amount
    meter["remaining"] = int(meter.get("remaining", 0)) + amount
    meter["tokens_used_this_month"] = max(0, int(meter.get("cycle_limit", 0)) - int(meter.get("remaining", 0)))
    prefs = user.ui_preferences if isinstance(user.ui_preferences, dict) else {}
    prefs["thinking_power"] = meter
    user.ui_preferences = deepcopy(prefs)
    _flag_modified(user, "ui_preferences")
    from app.founder_entitlements import persistent_credit_balance
    user.credits_remaining = int(meter.get("remaining", 0)) + persistent_credit_balance(user)


def bootstrap_legacy_credits(user, app_config):
    """
    One-time credit initialization for legacy rows that predate credit enforcement.
    Returns True when credits were updated.
    """
    plan_key = normalize_plan_key(user.subscription_plan)
    monthly_limit = get_monthly_credit_limit(plan_key, app_config)
    if monthly_limit is None:
        return False

    if plan_key in SHARED_POOL_PLANS:
        pool = _resolve_org_pool(user, app_config, now=datetime.utcnow(), force_reset=False)
        if pool is None:
            return False
        from app.founder_entitlements import persistent_credit_balance
        user.credits_remaining = int(pool["remaining"]) + persistent_credit_balance(user)
        if not user.credits_reset_at:
            user.credits_reset_at = datetime.utcnow()
        return True

    pool = _resolve_user_pool(user, app_config, now=datetime.utcnow(), force_reset=False)
    if user.credits_remaining is None:
        user.credits_remaining = int(pool.get("remaining", monthly_limit))
        user.credits_reset_at = datetime.utcnow()
        return True

    if user.credits_remaining != 0:
        return False

    # Only bootstrap untouched legacy rows (created_at ~= updated_at).
    if user.created_at and user.updated_at:
        if abs((user.updated_at - user.created_at).total_seconds()) <= 1:
            user.credits_remaining = int(pool.get("cycle_limit", monthly_limit))
            user.credits_reset_at = datetime.utcnow()
            return True

    return False


def is_credit_reset_due(user, now=None):
    now = now or datetime.utcnow()
    last_reset = user.credits_reset_at
    return _cycle_reset_due(last_reset, now)


def _credit_rollover_cap_percent(app_config):
    raw = app_config.get("CREDIT_ROLLOVER_CAP_PERCENT")
    if raw is None:
        raw = os.getenv("CREDIT_ROLLOVER_CAP_PERCENT", "0")
    try:
        return max(0.0, min(1.0, float(raw)))
    except Exception:
        return 0.0


def reset_user_monthly_credits(user, app_config, now=None, force=False):
    now = now or datetime.utcnow()
    plan_key = normalize_plan_key(user.subscription_plan)
    monthly_limit = get_monthly_credit_limit(plan_key, app_config)
    if monthly_limit is None:
        return False
    if plan_key in SHARED_POOL_PLANS:
        pool = _resolve_org_pool(user, app_config, now=now, force_reset=force)
        if pool is None:
            return False
        if not force and not _cycle_reset_due(user.credits_reset_at, now):
            return False
        from app.founder_entitlements import persistent_credit_balance
        user.credits_remaining = int(pool["remaining"]) + persistent_credit_balance(user)
        user.credits_reset_at = now
        return True
    pool = _resolve_user_pool(user, app_config, now=now, force_reset=force)
    if not force and not _cycle_reset_due(user.credits_reset_at, now):
        return False
    user.credits_remaining = int(pool["remaining"])
    user.credits_reset_at = now
    return True


def consume_credits(user, amount):
    """
    Deduct usage credits from user. Returns (ok, remaining_after).
    If credits are unmetered (None), always succeeds.
    """
    now = datetime.utcnow()
    amount = int(amount or 0)
    if amount <= 0:
        return True, user.credits_remaining

    # Reservation callers release unused capacity immediately after settlement.
    # Keep the source split on this in-memory ORM instance so a release cannot
    # accidentally refund an older persistent-ledger debit.
    user._last_monthly_credit_debit = 0
    user._last_persistent_credit_debit = 0

    plan_key = normalize_plan_key(getattr(user, "subscription_plan", None))
    monthly_limit = get_monthly_credit_limit(plan_key, {})
    grace_floor = 0
    if monthly_limit is not None:
        grace_floor = -int(math.floor(int(monthly_limit) * max(0.0, SOFT_STOP_GRACE_MULTIPLIER - 1.0)))

    if plan_key in SHARED_POOL_PLANS:
        pool = _resolve_org_pool(user, {}, now=now, force_reset=False)
        if pool is None:
            return False, user.credits_remaining
        meter = pool["meter"]
        monthly_remaining = int(meter.get("remaining", 0))
        from app.founder_entitlements import persistent_credit_balance
        persistent_remaining = persistent_credit_balance(user)
        remaining = monthly_remaining + persistent_remaining
        cycle_limit = int(meter.get("cycle_limit", monthly_limit or 0))
        if cycle_limit > 0:
            grace_floor = -int(math.floor(cycle_limit * max(0.0, SOFT_STOP_GRACE_MULTIPLIER - 1.0)))
        next_remaining = remaining - amount
        if cycle_limit > 0 and next_remaining < grace_floor:
            user.credits_remaining = remaining
            return False, remaining

        monthly_debit = min(amount, max(0, monthly_remaining))
        next_monthly_remaining = monthly_remaining - monthly_debit
        persistent_needed = max(0, amount - monthly_debit)
        if persistent_needed:
            from app.founder_entitlements import consume_persistent_credits
            persistent_consumed = consume_persistent_credits(
                user,
                min(persistent_needed, persistent_remaining),
                metadata={'reason': 'thinking_power_usage'},
            )
            user._last_persistent_credit_debit = persistent_consumed
            persistent_needed -= persistent_consumed
        if persistent_needed:
            next_monthly_remaining -= persistent_needed
        user._last_monthly_credit_debit = monthly_debit + persistent_needed

        meter["remaining"] = next_monthly_remaining
        meter["tokens_used_this_month"] = max(0, int(meter.get("cycle_limit", 0)) - next_monthly_remaining)
        user.credits_remaining = next_monthly_remaining + persistent_credit_balance(user)
        user.credits_reset_at = now
        return True, user.credits_remaining

    pool = _resolve_user_pool(user, {}, now=now, force_reset=False)
    monthly_remaining = int(pool.get("monthly_remaining", 0))
    persistent_remaining = int(pool.get("persistent_remaining", 0))
    remaining = monthly_remaining + persistent_remaining
    cycle_limit = int(pool.get("cycle_limit", monthly_limit or 0))
    if cycle_limit > 0:
        grace_floor = -int(math.floor(cycle_limit * max(0.0, SOFT_STOP_GRACE_MULTIPLIER - 1.0)))
    next_remaining = remaining - amount
    if cycle_limit > 0 and next_remaining < grace_floor:
        return False, remaining

    monthly_debit = min(amount, max(0, monthly_remaining))
    next_monthly_remaining = monthly_remaining - monthly_debit
    persistent_needed = max(0, amount - monthly_debit)
    if persistent_needed:
        from app.founder_entitlements import consume_persistent_credits
        persistent_consumed = consume_persistent_credits(
            user,
            min(persistent_needed, persistent_remaining),
            metadata={'reason': 'thinking_power_usage'},
        )
        user._last_persistent_credit_debit = persistent_consumed
        persistent_needed -= persistent_consumed
    if persistent_needed:
        # The soft-stop grace applies only after both paid balances are empty.
        next_monthly_remaining -= persistent_needed
    user._last_monthly_credit_debit = monthly_debit + persistent_needed

    from app.founder_entitlements import persistent_credit_balance
    persistent_after = persistent_credit_balance(user)
    user.credits_remaining = next_monthly_remaining + persistent_after
    prefs = user.ui_preferences if isinstance(user.ui_preferences, dict) else {}
    meter = prefs.get("thinking_power") if isinstance(prefs.get("thinking_power"), dict) else {}
    meter["remaining"] = next_monthly_remaining
    meter["tokens_used_this_month"] = max(0, cycle_limit - next_monthly_remaining)
    meter["cycle_limit"] = cycle_limit
    if not meter.get("cycle_reset_at"):
        meter["cycle_reset_at"] = now.isoformat()
    prefs["thinking_power"] = meter
    user.ui_preferences = deepcopy(prefs)
    _flag_modified(user, "ui_preferences")
    return True, user.credits_remaining


def release_consumed_credits(user, amount):
    """Release a reservation back to the same durable source where possible."""
    amount = max(0, int(amount or 0))
    if amount <= 0 or user.credits_remaining is None:
        return user.credits_remaining
    from app.founder_entitlements import refund_persistent_usage, persistent_credit_balance
    persistent_debit = max(0, int(getattr(user, '_last_persistent_credit_debit', 0) or 0))
    restored_persistent = refund_persistent_usage(
        user,
        min(amount, persistent_debit),
        metadata={'reason': 'provider_reservation_release'},
    )
    monthly_release = amount - restored_persistent
    if monthly_release > 0:
        plan_key = normalize_plan_key(getattr(user, 'subscription_plan', None))
        if plan_key in SHARED_POOL_PLANS:
            pool = _resolve_org_pool(user, {}, now=datetime.utcnow(), force_reset=False)
            if pool is not None:
                meter = pool['meter']
                meter['remaining'] = int(meter.get('remaining', 0)) + monthly_release
                meter['tokens_used_this_month'] = max(
                    0,
                    int(meter.get('cycle_limit', 0)) - meter['remaining'],
                )
                user.credits_remaining = meter['remaining'] + persistent_credit_balance(user)
        else:
            prefs = user.ui_preferences if isinstance(user.ui_preferences, dict) else {}
            meter = prefs.get('thinking_power') if isinstance(prefs.get('thinking_power'), dict) else {}
            meter['remaining'] = int(meter.get('remaining', 0)) + monthly_release
            meter['tokens_used_this_month'] = max(
                0,
                int(meter.get('cycle_limit', 0)) - meter['remaining'],
            )
            prefs['thinking_power'] = meter
            user.ui_preferences = deepcopy(prefs)
            _flag_modified(user, 'ui_preferences')
            user.credits_remaining = meter['remaining'] + persistent_credit_balance(user)
    else:
        prefs = user.ui_preferences if isinstance(user.ui_preferences, dict) else {}
        meter = prefs.get('thinking_power') if isinstance(prefs.get('thinking_power'), dict) else {}
        user.credits_remaining = int(meter.get('remaining', 0)) + persistent_credit_balance(user)
    user._last_persistent_credit_debit = max(0, persistent_debit - restored_persistent)
    user._last_monthly_credit_debit = max(
        0,
        int(getattr(user, '_last_monthly_credit_debit', 0) or 0) - monthly_release,
    )
    return user.credits_remaining


def cap_monthly_credits(user, amount, app_config):
    """Cap only the resettable monthly meter, preserving durable credit lots."""
    cap = max(0, int(amount or 0))
    plan_key = normalize_plan_key(getattr(user, 'subscription_plan', None))
    if plan_key in SHARED_POOL_PLANS:
        pool = _resolve_org_pool(user, app_config, now=datetime.utcnow(), force_reset=False)
        if pool is None:
            return user.credits_remaining
        meter = pool['meter']
        meter['remaining'] = min(int(meter.get('remaining', 0)), cap)
        meter['tokens_used_this_month'] = max(0, int(meter.get('cycle_limit', 0)) - meter['remaining'])
        from app.founder_entitlements import persistent_credit_balance
        user.credits_remaining = meter['remaining'] + persistent_credit_balance(user)
        return user.credits_remaining

    pool = _resolve_user_pool(user, app_config, now=datetime.utcnow(), force_reset=False)
    meter = pool['meter']
    meter['remaining'] = min(int(pool.get('monthly_remaining', 0)), cap)
    meter['tokens_used_this_month'] = max(0, int(meter.get('cycle_limit', 0)) - meter['remaining'])
    prefs = user.ui_preferences if isinstance(user.ui_preferences, dict) else {}
    prefs['thinking_power'] = meter
    user.ui_preferences = deepcopy(prefs)
    _flag_modified(user, 'ui_preferences')
    from app.founder_entitlements import persistent_credit_balance
    user.credits_remaining = meter['remaining'] + persistent_credit_balance(user)
    return user.credits_remaining


def get_usage_meter_state(user, app_config, now=None):
    from app.founder_entitlements import persistent_credit_balance, founder_credit_balance

    now = now or datetime.utcnow()
    plan_key = normalize_plan_key(getattr(user, "subscription_plan", None))
    monthly_limit = get_monthly_credit_limit(plan_key, app_config)
    grace_tokens = 0
    if monthly_limit is not None:
        grace_tokens = int(math.floor(int(monthly_limit) * max(0.0, SOFT_STOP_GRACE_MULTIPLIER - 1.0)))

    if plan_key in SHARED_POOL_PLANS:
        pool = _resolve_org_pool(user, app_config, now=now, force_reset=False)
        if pool is None:
            remaining = int(user.credits_remaining or 0)
            cycle_limit = int(monthly_limit or 0)
            used = max(0, cycle_limit - remaining)
            return {
                "scope": "user",
                "plan_key": plan_key,
                "monthly_limit": monthly_limit,
                "cycle_limit": cycle_limit,
                "remaining": remaining,
                "used": used,
                "grace_tokens": grace_tokens,
                "reset_at": user.credits_reset_at,
                "overage_tokens": 0,
            }
        meter = pool["meter"]
        monthly_remaining = int(meter.get("remaining", pool["cycle_limit"]))
        persistent_remaining = persistent_credit_balance(user)
        remaining = monthly_remaining + persistent_remaining
        cycle_limit = int(meter.get("cycle_limit", pool["cycle_limit"])) + persistent_remaining
        used = max(0, cycle_limit - remaining)
        reset_at = None
        reset_at_raw = meter.get("cycle_reset_at")
        if isinstance(reset_at_raw, str) and reset_at_raw.strip():
            try:
                reset_at = datetime.fromisoformat(reset_at_raw.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                reset_at = user.credits_reset_at
        return {
            "scope": "organization",
            "plan_key": plan_key,
            "organization_id": pool["organization"].id,
            "monthly_limit": int(pool["monthly_limit"] or 0),
            "monthly_remaining": monthly_remaining,
            "cycle_limit": cycle_limit,
            "remaining": remaining,
            "used": used,
            "grace_tokens": grace_tokens,
            "reset_at": reset_at or user.credits_reset_at,
            "overage_tokens": int(meter.get("overage_tokens", 0) or 0),
            "persistent_credits": persistent_remaining,
            "founder_credits": founder_credit_balance(user),
        }

    pool = _resolve_user_pool(user, app_config, now=now, force_reset=False)
    remaining = int(pool.get("remaining", user.credits_remaining or 0))
    persistent_remaining = int(pool.get('persistent_remaining', 0))
    monthly_cycle_limit = int(pool.get("cycle_limit", monthly_limit or 0))
    cycle_limit = monthly_cycle_limit + persistent_remaining
    used = None
    if cycle_limit is not None and remaining is not None:
        used = max(0, cycle_limit - remaining)
    return {
        "scope": "user",
        "plan_key": plan_key,
        "monthly_limit": monthly_limit,
        "monthly_remaining": int(pool.get('monthly_remaining', 0)),
        "cycle_limit": cycle_limit,
        "remaining": remaining,
        "used": used,
        "grace_tokens": grace_tokens,
        "reset_at": user.credits_reset_at,
        "overage_tokens": int(pool.get('meter', {}).get('overage_tokens', 0) or 0),
        "persistent_credits": persistent_remaining,
        "founder_credits": founder_credit_balance(user),
    }


def to_public_plan(plan_key):
    """Safe plan key for public responses."""
    return normalize_plan_key(plan_key)


# Subscription statuses that mean the customer is NOT in good standing and must
# not retain paid-tier entitlements. Stripe webhooks normally also roll the
# plan back to 'free', but gating on status here is a defense-in-depth backstop
# for missed/delayed webhooks and for the 'past_due' state (where the plan tier
# is intentionally left intact while Stripe retries payment).
RESTRICTED_SUBSCRIPTION_STATUSES = frozenset({
    'canceled',
    'cancelled',
    'unpaid',
    'incomplete_expired',
    'past_due',
    'paused',
})


def subscription_in_good_standing(status):
    """True when a subscription_status should retain paid entitlements.

    An empty/missing status is treated as good standing so we never strip
    access from legacy rows or sales-led accounts provisioned outside Stripe.
    """
    normalized = str(status or '').strip().lower()
    if not normalized:
        return True
    return normalized not in RESTRICTED_SUBSCRIPTION_STATUSES


def effective_plan_key(user, app_config=None):
    """Plan key to use for *entitlement* decisions (models, tools, context).

    Falls back to 'free' when the subscription is not in good standing, so a
    canceled / past-due / paused account cannot keep paid-tier access even if
    subscription_plan hasn't been rolled back yet. Sales-led plans (provisioned
    outside Stripe consumer billing) are never downgraded by this check.
    """
    plan_key = normalize_plan_key(getattr(user, 'subscription_plan', None))
    if plan_key == 'free':
        subscription_access = 'free'
    elif subscription_in_good_standing(getattr(user, 'subscription_status', None)):
        subscription_access = plan_key
    elif app_config is not None and is_sales_only_plan(plan_key, app_config):
        subscription_access = plan_key
    else:
        subscription_access = 'free'

    # The 300K Limited-Time offer is a standalone, one-time entitlement. It is
    # not an Essential subscription, but it includes the individual output
    # capabilities needed to use the purchased Thinking Power. Keep the
    # persisted subscription_plan unchanged so billing and renewal UI remain
    # accurate while entitlement checks receive Essential-equivalent access.
    try:
        from .founder_entitlements import has_limited_time_300k_entitlement

        has_limited_time_300k = has_limited_time_300k_entitlement(user)
    except (RuntimeError, TypeError):
        # Some pure unit-test helpers call this function without an active DB
        # context. In that case, preserve normal subscription behavior.
        has_limited_time_300k = False

    if has_limited_time_300k and PLAN_RANK.get(subscription_access, 0) < PLAN_RANK['essential']:
        return 'essential'
    return subscription_access
