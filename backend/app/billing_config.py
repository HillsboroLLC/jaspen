import calendar
from copy import deepcopy
from datetime import datetime
import math
import os

PLAN_ALIASES = {
    'growth': 'team',
    'transform': 'enterprise',
    'transform_basic': 'enterprise',
    'transform_standard': 'enterprise',
    'transform_premium': 'enterprise',
    'transform_enterprise': 'enterprise',
    'founder': 'essential',
}

PLAN_RANK = {
    'free': 0,
    'essential': 1,
    'team': 2,
    'enterprise': 3,
}

DEFAULT_PLAN_CATALOG = {
    'free': {
        'label': 'Free',
        'monthly_price_usd': 0,
        'monthly_credits': 1_000_000,
        'self_serve': True,
        'sales_only': False,
        'description': 'Individual access for exploring core workflows.',
    },
    'essential': {
        'label': 'Essential',
        'monthly_price_usd': 20,
        'monthly_credits': 7_000_000,
        'self_serve': True,
        'sales_only': False,
        'description': 'Individual plan with higher monthly usage limits.',
    },
    'team': {
        'label': 'Team',
        'monthly_price_usd': 129,
        'price_model': 'per_seat',
        'min_seats': 3,
        'included_seats': 3,
        'additional_seat_price': 25,
        'monthly_credits': 29_000_000,
        'self_serve': True,
        'sales_only': False,
        'description': 'Collaborative workspace with shared thinking power and seat-based pricing.',
        'max_admin_seats': 3,
        'max_total_paid_seats': None,
        'max_viewer_seats': None,
    },
    'enterprise': {
        'label': 'Enterprise',
        'monthly_price_usd': 299,
        'price_model': 'per_seat',
        'min_seats': 5,
        'included_seats': 5,
        'included_admins': 1,
        'additional_seat_price': 30,
        'monthly_credits': 80_000_000,
        'self_serve': True,
        'sales_only': False,
        'description': 'Advanced deployment with larger pooled thinking power and Titan model access.',
        'max_admins': 5,
        'max_admin_seats': 5,
        'max_total_paid_seats': None,
        'collaborators': None,
        'viewer_seats': None,
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

SHARED_POOL_PLANS = {'team', 'enterprise'}
SOFT_STOP_GRACE_MULTIPLIER = 1.05
TOKENS_PER_CREDIT = 1000

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
        'default_llm_model': 'claude-3-5-haiku-latest',
    },
    'orbit': {
        'label': 'Orbit',
        'version': '1.0',
        'description': 'Balanced depth and speed for broader cross-functional synthesis.',
        'min_plan': 'essential',
        'default_llm_model': 'claude-sonnet-4-20250514',
    },
    'titan': {
        'label': 'Titan',
        'version': '1.0',
        'description': 'Highest-depth reasoning for complex multi-team initiatives.',
        'min_plan': 'enterprise',
        'default_llm_model': 'claude-opus-4-20250514',
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
    org.settings = settings

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
        remaining = monthly_limit
        reset_at = now
    else:
        remaining = int(meter.get("remaining", user.credits_remaining if user.credits_remaining is not None else cycle_limit))

    meter["overage_tokens"] = overage_tokens
    meter["cycle_limit"] = cycle_limit
    meter["remaining"] = remaining
    meter["tokens_used_this_month"] = max(0, cycle_limit - remaining)
    meter["cycle_reset_at"] = reset_at.isoformat() if isinstance(reset_at, datetime) else now.isoformat()
    prefs["thinking_power"] = meter
    user.ui_preferences = prefs
    user.credits_remaining = remaining
    user.credits_reset_at = reset_at if isinstance(reset_at, datetime) else now
    return {
        "meter": meter,
        "monthly_limit": monthly_limit,
        "cycle_limit": cycle_limit,
        "remaining": remaining,
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
            _resolve_org_pool(user, app_config, now=datetime.utcnow(), force_reset=True)
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
            meter = pool["meter"]
            meter["overage_tokens"] = _coerce_non_negative_int(meter.get("overage_tokens")) + amount
            meter["cycle_limit"] = _coerce_non_negative_int(meter.get("cycle_limit")) + amount
            meter["remaining"] = int(meter.get("remaining", 0)) + amount
            meter["tokens_used_this_month"] = max(0, int(meter.get("cycle_limit", 0)) - int(meter.get("remaining", 0)))
            user.credits_remaining = int(meter.get("remaining", 0))
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
    user.ui_preferences = prefs
    user.credits_remaining = int(meter.get("remaining", 0))


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
        user.credits_remaining = int(pool["remaining"])
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
        user.credits_remaining = int(pool["remaining"])
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
        remaining = int(meter.get("remaining", 0))
        cycle_limit = int(meter.get("cycle_limit", monthly_limit or 0))
        if cycle_limit > 0:
            grace_floor = -int(math.floor(cycle_limit * max(0.0, SOFT_STOP_GRACE_MULTIPLIER - 1.0)))
        next_remaining = remaining - amount
        if cycle_limit > 0 and next_remaining < grace_floor:
            user.credits_remaining = remaining
            return False, remaining
        meter["remaining"] = next_remaining
        meter["tokens_used_this_month"] = max(0, int(meter.get("cycle_limit", 0)) - next_remaining)
        user.credits_remaining = next_remaining
        user.credits_reset_at = now
        return True, next_remaining

    pool = _resolve_user_pool(user, {}, now=now, force_reset=False)
    remaining = int(pool.get("remaining", user.credits_remaining or 0))
    cycle_limit = int(pool.get("cycle_limit", monthly_limit or 0))
    if cycle_limit > 0:
        grace_floor = -int(math.floor(cycle_limit * max(0.0, SOFT_STOP_GRACE_MULTIPLIER - 1.0)))
    next_remaining = remaining - amount
    if cycle_limit > 0 and next_remaining < grace_floor:
        return False, remaining
    user.credits_remaining = next_remaining
    prefs = user.ui_preferences if isinstance(user.ui_preferences, dict) else {}
    meter = prefs.get("thinking_power") if isinstance(prefs.get("thinking_power"), dict) else {}
    meter["remaining"] = next_remaining
    meter["tokens_used_this_month"] = max(0, cycle_limit - next_remaining)
    meter["cycle_limit"] = cycle_limit
    if not meter.get("cycle_reset_at"):
        meter["cycle_reset_at"] = now.isoformat()
    prefs["thinking_power"] = meter
    user.ui_preferences = prefs
    return True, user.credits_remaining


def get_usage_meter_state(user, app_config, now=None):
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
        remaining = int(meter.get("remaining", pool["cycle_limit"]))
        cycle_limit = int(meter.get("cycle_limit", pool["cycle_limit"]))
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
            "cycle_limit": cycle_limit,
            "remaining": remaining,
            "used": used,
            "grace_tokens": grace_tokens,
            "reset_at": reset_at or user.credits_reset_at,
            "overage_tokens": int(meter.get("overage_tokens", 0) or 0),
        }

    pool = _resolve_user_pool(user, app_config, now=now, force_reset=False)
    remaining = int(pool.get("remaining", user.credits_remaining or 0))
    cycle_limit = int(pool.get("cycle_limit", monthly_limit or 0))
    used = None
    if cycle_limit is not None and remaining is not None:
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


def to_public_plan(plan_key):
    """Safe plan key for public responses."""
    return normalize_plan_key(plan_key)
