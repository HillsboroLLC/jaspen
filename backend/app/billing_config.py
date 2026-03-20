from copy import deepcopy

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
        'monthly_credits': 300,
        'self_serve': True,
        'sales_only': False,
        'description': 'Individual access for exploring core workflows.',
    },
    'essential': {
        'label': 'Essential',
        'monthly_price_usd': 20,
        'monthly_credits': 3000,
        'self_serve': True,
        'sales_only': False,
        'description': 'Individual plan with higher monthly usage limits.',
    },
    'team': {
        'label': 'Team',
        'monthly_price_usd': 49,
        'price_model': 'per_seat',
        'min_seats': 5,
        'monthly_credits_base': 5000,
        'monthly_credits_per_seat': 500,
        'monthly_credits': None,
        'self_serve': True,
        'sales_only': False,
        'description': 'Collaborative workspace for teams with shared projects and pooled credits.',
        'max_admin_seats': 3,
        'max_total_paid_seats': None,
        'max_viewer_seats': None,
    },
    'enterprise': {
        'label': 'Enterprise',
        'monthly_price_usd': None,
        'price_model': 'custom',
        'monthly_credits': None,
        'self_serve': False,
        'sales_only': True,
        'description': 'Sales-led deployment with governance, SSO, and advanced model access.',
        'max_admin_seats': 10,
        'max_total_paid_seats': None,
        'max_viewer_seats': None,
    },
}

DEFAULT_OVERAGE_PACKS = {
    'pack_1000': {
        'label': '1,000 credits',
        'credits': 1000,
        'price_usd': 12,
    },
    'pack_5000': {
        'label': '5,000 credits',
        'credits': 5000,
        'price_usd': 50,
    },
    'pack_20000': {
        'label': '20,000 credits',
        'credits': 20000,
        'price_usd': 180,
    },
}

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
        'min_plan': 'team',
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


def get_overage_packs(app_config):
    """Overage packs enriched with configured Stripe price ids."""
    packs = deepcopy(DEFAULT_OVERAGE_PACKS)
    stripe_pack_ids = app_config.get('STRIPE_OVERAGE_PACK_PRICE_IDS', {}) or {}
    for key, value in packs.items():
        value['pack_key'] = key
        value['stripe_price_id'] = stripe_pack_ids.get(key)
    return packs


def get_model_catalog(app_config):
    catalog = deepcopy(DEFAULT_MODEL_CATALOG)
    backing_ids = app_config.get('MODEL_TYPE_BACKING_IDS', {}) or {}
    for key, value in catalog.items():
        value['model_type'] = key
        value['llm_model'] = backing_ids.get(key) or value.get('default_llm_model')
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
        user.credits_remaining = monthly_limit
    elif monthly_limit is None and user.credits_remaining is not None:
        # Sales-led plans can be tracked outside of per-user credit counters.
        user.credits_remaining = None


def add_credits(user, amount):
    amount = int(amount or 0)
    if amount <= 0:
        return

    if user.credits_remaining is None:
        user.credits_remaining = amount
    else:
        user.credits_remaining += amount


def bootstrap_legacy_credits(user, app_config):
    """
    One-time credit initialization for legacy rows that predate credit enforcement.
    Returns True when credits were updated.
    """
    plan_key = normalize_plan_key(user.subscription_plan)
    monthly_limit = get_monthly_credit_limit(plan_key, app_config)
    if monthly_limit is None:
        return False

    if user.credits_remaining is None:
        user.credits_remaining = monthly_limit
        return True

    if user.credits_remaining != 0:
        return False

    # Only bootstrap untouched legacy rows (created_at ~= updated_at).
    if user.created_at and user.updated_at:
        if abs((user.updated_at - user.created_at).total_seconds()) <= 1:
            user.credits_remaining = monthly_limit
            return True

    return False


def consume_credits(user, amount):
    """
    Deduct usage credits from user. Returns (ok, remaining_after).
    If credits are unmetered (None), always succeeds.
    """
    amount = int(amount or 0)
    if amount <= 0:
        return True, user.credits_remaining

    if user.credits_remaining is None:
        return True, None

    if user.credits_remaining < amount:
        return False, user.credits_remaining

    user.credits_remaining -= amount
    return True, user.credits_remaining


def to_public_plan(plan_key):
    """Safe plan key for public responses."""
    return normalize_plan_key(plan_key)
