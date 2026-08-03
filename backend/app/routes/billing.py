import os
import time
import math
from datetime import datetime
from urllib.parse import urlparse
from flask import Blueprint, request, jsonify, current_app, abort
from flask_jwt_extended import jwt_required, get_jwt_identity
import stripe
from sqlalchemy.exc import IntegrityError

from app import db
from app.admin_policy import is_global_admin
from app.models import PersistentCreditGrant, StripeWebhookEvent, User
from app.orgs import build_seat_usage, can_manage_org, resolve_active_org_for_user
from app.billing_config import (
    apply_plan_to_user,
    add_credits,
    bootstrap_legacy_credits,
    cap_monthly_credits,
    consume_credits,
    get_credit_packs,
    get_allowed_model_types,
    get_default_model_type,
    get_model_catalog,
    get_monthly_credit_limit,
    normalize_credit_pack_key,
    get_plan_catalog,
    is_sales_only_plan,
    normalize_plan_key,
    reset_user_monthly_credits,
    tokens_to_credits,
    to_public_plan,
    get_usage_meter_state,
    effective_plan_key,
    subscription_in_good_standing,
)
from app.connector_store import get_all_connector_settings
from app.founder_entitlements import (
    LIMITED_TIME_300K_CREDIT_SOURCE,
    limited_time_300k_credit_balance,
    grant_limited_time_300k_offer,
    has_limited_time_300k_entitlement,
    reverse_limited_time_300k_credits,
)
from app.tool_registry import get_context_budget, get_tool_entitlements

billing_bp = Blueprint('billing', __name__)


@billing_bp.before_app_request
def _set_stripe_key():
    stripe.api_key = current_app.config['STRIPE_SECRET_KEY']


def _frontend_url(path='/pages/pricing'):
    base = (current_app.config.get('FRONTEND_BASE_URL') or 'http://localhost:3000').rstrip('/')
    return f"{base}{path}"


def _normalized_origin(url):
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _origin_variants(origin):
    """Return the origin plus its www/apex counterpart.

    The frontend is served at https://www.jaspen.ai while FRONTEND_BASE_URL is
    often configured as the apex https://jaspen.ai (or vice-versa). Treat the
    two as equivalent so redirect validation doesn't reject a legitimate
    same-site return URL.
    """
    if not origin:
        return set()
    variants = {origin}
    parsed = urlparse(origin)
    host = parsed.netloc
    if host.startswith('www.'):
        variants.add(f"{parsed.scheme}://{host[4:]}")
    else:
        variants.add(f"{parsed.scheme}://www.{host}")
    return variants


def _allowed_frontend_origins():
    origins = set()
    frontend_base = current_app.config.get('FRONTEND_BASE_URL') or 'http://localhost:3000'
    origins |= _origin_variants(_normalized_origin(frontend_base))

    raw = (
        current_app.config.get('BILLING_REDIRECT_ALLOWED_ORIGINS')
        or os.getenv('BILLING_REDIRECT_ALLOWED_ORIGINS')
        or ''
    )
    for item in str(raw).split(','):
        origins |= _origin_variants(_normalized_origin(item))
    origins.discard(None)
    return origins


def _validated_frontend_redirect(url, *, fallback_path):
    candidate = str(url or '').strip()
    if not candidate:
        return _frontend_url(fallback_path)

    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Redirect URL must be an absolute http(s) URL.")

    origin = _normalized_origin(candidate)
    if origin not in _allowed_frontend_origins():
        raise ValueError("Redirect URL must use an approved frontend origin.")

    return candidate


def _plan_key_for_price_id(price_id, app_config):
    """Reverse-map either a monthly or annual Stripe price id to its plan key."""
    if not price_id:
        return None
    for mapping_name in ('STRIPE_PRICE_IDS', 'STRIPE_ANNUAL_PRICE_IDS'):
        mapping = app_config.get(mapping_name, {}) or {}
        for plan_key, pid in mapping.items():
            if pid == price_id:
                return normalize_plan_key(plan_key)
    return None


def _normalize_billing_interval(value):
    return 'annual' if str(value or '').strip().lower() == 'annual' else 'monthly'


def _price_id_for_plan(plan_key, billing_interval, app_config):
    mapping_name = 'STRIPE_ANNUAL_PRICE_IDS' if billing_interval == 'annual' else 'STRIPE_PRICE_IDS'
    return (app_config.get(mapping_name, {}) or {}).get(plan_key)


def _ensure_customer_for_user(user):
    if user.stripe_customer_id:
        return user.stripe_customer_id

    customer = stripe.Customer.create(
        email=user.email,
        name=user.name,
        metadata={'user_id': str(user.id)},
    )
    user.stripe_customer_id = customer.id
    db.session.commit()
    return customer.id


def _usage_warning_fields(cycle_limit, tokens_used):
    if cycle_limit is None or tokens_used is None:
        return {"usage_percent": None, "usage_warning_level": "normal"}
    try:
        limit = max(0, int(cycle_limit))
        used = max(0, int(tokens_used))
    except Exception:
        return {"usage_percent": None, "usage_warning_level": "normal"}
    if limit <= 0:
        return {"usage_percent": None, "usage_warning_level": "normal"}

    usage_percent = max(0.0, (used / float(limit)) * 100.0)
    if usage_percent >= 105.0:
        level = "blocked"
    elif usage_percent >= 100.0:
        level = "exhausted"
    elif usage_percent >= 95.0:
        level = "urgent"
    elif usage_percent >= 80.0:
        level = "warning"
    elif usage_percent >= 50.0:
        level = "moderate"
    else:
        level = "normal"
    return {"usage_percent": round(usage_percent, 2), "usage_warning_level": level}


def _find_user_for_billing_event(subscription_id=None, customer_id=None):
    user = None
    if subscription_id:
        user = User.query.filter_by(stripe_subscription_id=subscription_id).first()
    if not user and customer_id:
        user = User.query.filter_by(stripe_customer_id=customer_id).first()
    return user


@billing_bp.route('/plans', methods=['GET'])
def list_plans():
    """Legacy response: plan_key -> Stripe Price ID."""
    return jsonify(current_app.config.get('STRIPE_PRICE_IDS', {})), 200


@billing_bp.route('/catalog', methods=['GET'])
def get_billing_catalog():
    raw_plan_catalog = get_plan_catalog(current_app.config)
    raw_pack_catalog = get_credit_packs(current_app.config)
    model_catalog = get_model_catalog(current_app.config)

    plan_catalog = {}
    for key, plan in (raw_plan_catalog or {}).items():
        row = dict(plan or {})
        monthly_tokens = row.get('monthly_credits')
        row['monthly_credits'] = tokens_to_credits(monthly_tokens, precision=0) if monthly_tokens is not None else None
        plan_catalog[key] = row

    pack_catalog = {}
    for key, pack in (raw_pack_catalog or {}).items():
        row = dict(pack or {})
        pack_tokens = row.get('credits')
        row['credits'] = tokens_to_credits(pack_tokens, precision=0) if pack_tokens is not None else None
        pack_catalog[key] = row

    return jsonify({
        'plans': plan_catalog,
        'credit_packs': pack_catalog,
        # Backward-compatible alias for older clients.
        'overage_packs': pack_catalog,
        'model_types': model_catalog,
    }), 200


@billing_bp.route('/status', methods=['GET'])
@jwt_required()
def get_billing_status():
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({'msg': 'User not found'}), 404

    if bootstrap_legacy_credits(user, current_app.config):
        db.session.commit()

    admin_override = is_global_admin(user, app_config=current_app.config)
    if admin_override:
        changed = False
        # Global Jaspen admins should always have the highest self-service plan.
        if to_public_plan(user.subscription_plan) != 'business' or user.credits_remaining is not None:
            apply_plan_to_user(user, 'business', current_app.config, reset_credits=True)
            changed = True
        if not bool(user.unlimited_analysis):
            user.unlimited_analysis = True
            changed = True
        if user.max_concurrent_sessions is not None:
            user.max_concurrent_sessions = None
            changed = True
        if changed:
            db.session.commit()

    plan_key = to_public_plan(user.subscription_plan)
    access_plan_key = plan_key if admin_override else effective_plan_key(user, current_app.config)
    plan_catalog = get_plan_catalog(current_app.config)
    current_plan = plan_catalog.get(plan_key) or {}
    usage_state = get_usage_meter_state(user, current_app.config)
    monthly_limit = usage_state.get('monthly_limit')
    cycle_limit = usage_state.get('cycle_limit')
    tokens_remaining = usage_state.get('remaining')
    tokens_used = usage_state.get('used')
    credits_remaining = tokens_to_credits(tokens_remaining, precision=1)
    credits_used = tokens_to_credits(tokens_used, precision=1)
    if admin_override:
        credits_used = 0
    allowed_model_types = get_allowed_model_types(access_plan_key, current_app.config)
    default_model_type = get_default_model_type(access_plan_key, current_app.config)
    tool_entitlements = get_tool_entitlements(access_plan_key)
    connector_settings = get_all_connector_settings(user.id)
    for tool in tool_entitlements:
        if str(tool.get('type') or '').lower() != 'connector':
            continue
        connector_id = str(tool.get('id') or '').strip().lower()
        settings = connector_settings.get(connector_id) or {}
        connection_status = str(settings.get('connection_status') or 'disconnected').strip().lower()
        if connection_status not in ('connected', 'disconnected'):
            connection_status = 'disconnected'
        tool['connection_status'] = connection_status
        tool['connected'] = bool(tool.get('enabled')) and connection_status == 'connected'
        tool['sync_mode'] = settings.get('sync_mode') or 'import'
        tool['conflict_policy'] = settings.get('conflict_policy') or 'prefer_external'
        tool['last_sync_at'] = settings.get('last_sync_at')
        tool['auto_sync'] = bool(settings.get('auto_sync', True))
        tool['external_workspace'] = settings.get('external_workspace') or ''
    usage_meta = _usage_warning_fields(cycle_limit, tokens_used)

    # Surface pending-state details from the live Stripe subscription so the UI
    # can show scheduled cancellations / downgrades and offer an undo. Best
    # effort only — never let a Stripe hiccup break the status endpoint.
    cancel_at_period_end = False
    current_period_end = None
    scheduled_plan_change = None
    billing_interval = 'monthly'
    if user.stripe_subscription_id:
        try:
            sub = stripe.Subscription.retrieve(user.stripe_subscription_id)
            cancel_at_period_end = bool(sub.get('cancel_at_period_end'))
            cpe = sub.get('current_period_end')
            if cpe:
                current_period_end = datetime.utcfromtimestamp(int(cpe)).isoformat()
            sub_meta = sub.get('metadata') or {}
            items = (sub.get('items') or {}).get('data') or []
            current_price_id = (items[0].get('price') or {}).get('id') if items else None
            if current_price_id in set((current_app.config.get('STRIPE_ANNUAL_PRICE_IDS', {}) or {}).values()):
                billing_interval = 'annual'
            elif str(sub_meta.get('billing_interval') or '').strip().lower() == 'annual':
                billing_interval = 'annual'
            scheduled_raw = str(sub_meta.get('scheduled_plan_change') or '').strip()
            if scheduled_raw:
                scheduled_plan_change = to_public_plan(scheduled_raw)
        except Exception as exc:  # noqa: BLE001 - status must not fail on Stripe
            current_app.logger.warning(
                'get_billing_status: could not retrieve Stripe subscription %s: %s',
                user.stripe_subscription_id, exc,
            )

    return jsonify({
        'plan_key': plan_key,
        'plan': current_plan,
        'is_admin': admin_override,
        'subscription_status': user.subscription_status,
        'cancel_at_period_end': cancel_at_period_end,
        'current_period_end': current_period_end,
        'scheduled_plan_change': scheduled_plan_change,
        'billing_interval': billing_interval,
        'access_restricted': (
            (not admin_override)
            and plan_key != 'free'
            and access_plan_key == 'free'
        ),
        'effective_plan_key': access_plan_key,
        'credits_remaining': credits_remaining,
        'monthly_credit_limit': tokens_to_credits(monthly_limit, precision=0),
        'credits_used': credits_used,
        'usage_scope': usage_state.get('scope'),
        'cycle_credit_limit': tokens_to_credits(cycle_limit, precision=0),
        'cycle_reset_at': usage_state.get('reset_at').isoformat() if usage_state.get('reset_at') else None,
        'purchased_credits_this_cycle': tokens_to_credits(usage_state.get('overage_tokens'), precision=0),
        'persistent_credits': tokens_to_credits(usage_state.get('persistent_credits'), precision=1),
        '300k_limited_time_credits_remaining': tokens_to_credits(limited_time_300k_credit_balance(user), precision=1),
        'has_300k_limited_time': has_limited_time_300k_entitlement(user),
        # Backward-compatible fields for clients deployed before the offer rename.
        'founder_credits_remaining': tokens_to_credits(limited_time_300k_credit_balance(user), precision=1),
        'is_founder': has_limited_time_300k_entitlement(user),
        # Backward-compatible alias for older clients.
        'overage_credits_this_cycle': tokens_to_credits(usage_state.get('overage_tokens'), precision=0),
        'credit_soft_stop_limit': tokens_to_credits(cycle_limit, precision=0),
        'credit_block_limit': tokens_to_credits(None if cycle_limit is None else int(math.floor(int(cycle_limit) * 1.05)), precision=0),
        'allowed_model_types': allowed_model_types,
        'default_model_type': default_model_type,
        'context_budget': get_context_budget(access_plan_key),
        'tool_entitlements': tool_entitlements,
        'stripe_customer_id': user.stripe_customer_id,
        'stripe_subscription_id': user.stripe_subscription_id,
        'usage_percent': usage_meta.get('usage_percent'),
        'usage_warning_level': usage_meta.get('usage_warning_level'),
    }), 200


@billing_bp.route('/create-payment-intent', methods=['POST'])
@jwt_required()
def create_payment_intent():
    """Legacy one-off PaymentIntent flow (amount in cents)."""
    data = request.get_json() or {}
    amount = int(data.get('amount', 0) or 0)
    if amount <= 0:
        return jsonify({'msg': 'amount must be a positive integer (in cents)'}), 400
    intent = stripe.PaymentIntent.create(
        amount=amount,
        currency='usd',
    )
    return jsonify({'client_secret': intent.client_secret}), 200


def _credit_pack_payment_event_id(payment_intent_id):
    return f"credit_pack_payment:{payment_intent_id}"


def _limited_time_300k_payment_event_id(payment_intent_id):
    return f"limited_time_300k_payment:{payment_intent_id}"


def _credit_pack_tokens_from_metadata(metadata):
    tokens = int(metadata.get('tokens') or 0)
    if tokens > 0:
        return tokens
    credits = int(metadata.get('credits') or 0)
    return credits * 1000 if credits > 0 else 0


def _send_limited_time_300k_welcome_email(user, *, amount_label='$999', reference=''):
    """Receipt and welcome note, sent once when the credits are granted.

    Never lets a mail failure undo a paid purchase: the credits are already on
    the account by the time this runs, so a bounced send is logged and dropped
    rather than raised.
    """
    email = str(getattr(user, 'email', '') or '').strip()
    if not email:
        return False
    try:
        from flask_mail import Message

        from app import mail
        from app.email_templates.limited_time_300k_welcome import (
            render_limited_time_300k_welcome_email,
        )

        rendered = render_limited_time_300k_welcome_email(
            recipient_name=getattr(user, 'name', '') or '',
            amount_label=amount_label,
            workspace_url=_frontend_url('/'),
            receipt_reference=reference,
        )
        message = Message(
            subject=rendered['subject'],
            recipients=[email],
            sender='Jaspen <hello@jaspen.ai>',
            reply_to='hello@jaspen.ai',
        )
        message.body = rendered['body']
        message.html = rendered['html']
        mail.send(message)
        return True
    except Exception:
        current_app.logger.exception(
            '300K Limited-Time: welcome email failed for user=%s', getattr(user, 'id', None),
        )
        return False


def _is_limited_time_300k_charge(user, charge):
    if user is None:
        return False
    metadata = charge.get('metadata') if isinstance(charge.get('metadata'), dict) else {}
    if str(metadata.get('checkout_type') or '').strip() == LIMITED_TIME_300K_CHECKOUT_TYPE:
        return True
    # A discounted purchase settles through an invoice, so its grant records an
    # invoice id and its charge carries none of our metadata. Matching only on
    # the payment intent let a refunded or disputed promo-code purchase keep all
    # 300,000 credits.
    payment_intent_id = str(charge.get('payment_intent') or '').strip()
    invoice_id = str(charge.get('invoice') or '').strip()
    if not payment_intent_id and not invoice_id:
        return False
    grants = PersistentCreditGrant.query.filter_by(
        user_id=str(user.id),
        source=LIMITED_TIME_300K_CREDIT_SOURCE,
    ).all()
    for grant in grants:
        grant_metadata = grant.grant_metadata or {}
        if payment_intent_id and str(
            grant_metadata.get('stripe_payment_intent_id') or ''
        ).strip() == payment_intent_id:
            return True
        if invoice_id and (
            str(grant_metadata.get('stripe_invoice_id') or '').strip() == invoice_id
            or str(grant.stripe_invoice_id or '').strip() == invoice_id
        ):
            return True
    return False


def _fulfill_credit_pack_purchase(
    reference, metadata, *, event_type, customer_id=None, expected_user=None,
):
    """Add credit-pack tokens once per purchase, whatever event carries it.

    Stripe announces one hosted-checkout purchase twice, as
    checkout.session.completed and again as payment_intent.succeeded, under two
    different event ids - so the webhook's own event ledger cannot see that
    they are the same sale. The claim is keyed on the PaymentIntent instead,
    which is the one id both events agree on, and the unique index on
    stripe_webhook_events.stripe_event_id is what actually settles who grants.

    Mirrors _fulfill_limited_time_300k_payment_intent. The difference is that
    credit packs add to a counter rather than writing a grant row, so there is
    no second unique constraint underneath this one to catch a duplicate - this
    claim has to be right on its own.
    """
    checkout_type = str(_stripe_field(metadata, 'checkout_type') or '').strip()
    if checkout_type not in {'credit_pack', 'overage_pack'}:
        return {'granted': False, 'reason': 'not_credit_pack'}
    reference = str(reference or '').strip()
    if not reference:
        return {'granted': False, 'reason': 'missing_reference'}

    event_id = _credit_pack_payment_event_id(reference)
    event_row = StripeWebhookEvent.query.filter_by(stripe_event_id=event_id).first()
    if event_row and bool(event_row.processed):
        return {'granted': False, 'reason': 'already_processed'}
    if event_row is None:
        event_row = StripeWebhookEvent(
            stripe_event_id=event_id,
            event_type=event_type,
            processed=False,
        )
        db.session.add(event_row)
        try:
            db.session.flush()
        except IntegrityError:
            # Another delivery of this same purchase claimed it between our
            # read and our write. The unique index decides, not the read, and
            # the other worker is mid-grant - so stand down rather than add the
            # tokens a second time. Stripe redelivers if that worker fails.
            db.session.rollback()
            return {'granted': False, 'reason': 'in_flight'}

    user_id = _stripe_field(metadata, 'user_id')
    user = User.query.get(user_id) if user_id else None
    if not user:
        user = _find_user_for_billing_event(customer_id=customer_id)
    if not user:
        return {'granted': False, 'reason': 'user_not_found'}
    if expected_user and str(user.id) != str(expected_user.id):
        return {'granted': False, 'reason': 'wrong_user'}

    tokens = _credit_pack_tokens_from_metadata(metadata)
    if tokens <= 0:
        return {'granted': False, 'reason': 'missing_tokens'}

    add_credits(user, tokens)
    if customer_id:
        user.stripe_customer_id = customer_id
    event_row.processed = True
    event_row.processed_at = datetime.utcnow()
    current_app.logger.info(
        "%s: added %s credit-pack tokens for user=%s (purchase=%s)",
        event_type, tokens, user.id, reference,
    )
    return {'granted': True, 'tokens': tokens, 'user_id': str(user.id)}


def _fulfill_credit_pack_payment_intent(intent, expected_user=None):
    metadata = intent.get('metadata') or {}
    if intent.get('status') != 'succeeded':
        checkout_type = str(metadata.get('checkout_type') or '').strip()
        if checkout_type not in {'credit_pack', 'overage_pack'}:
            return {'granted': False, 'reason': 'not_credit_pack'}
        return {'granted': False, 'reason': intent.get('status') or 'not_succeeded'}
    return _fulfill_credit_pack_purchase(
        intent.get('id'),
        metadata,
        event_type='payment_intent.succeeded',
        customer_id=intent.get('customer'),
        expected_user=expected_user,
    )


def _fulfill_credit_pack_checkout_session(session, expected_user=None):
    """Fulfil a hosted-checkout credit pack, claiming it as the same purchase.

    The session's payment_intent is what ties this to the payment_intent.succeeded
    delivery of the same sale; the session id is only a fallback for a session
    that has not been paid through an intent.
    """
    metadata = session.get('metadata') or {}
    return _fulfill_credit_pack_purchase(
        session.get('payment_intent') or session.get('id'),
        metadata,
        event_type='checkout.session.completed',
        customer_id=session.get('customer'),
        expected_user=expected_user,
    )


def _fulfill_limited_time_300k_payment_intent(intent, expected_user=None):
    metadata = intent.get('metadata') or {}
    checkout_type = str(metadata.get('checkout_type') or '').strip()
    if checkout_type != LIMITED_TIME_300K_CHECKOUT_TYPE:
        return {'granted': False, 'reason': 'not_limited_time_300k'}
    if intent.get('status') != 'succeeded':
        return {'granted': False, 'reason': intent.get('status') or 'not_succeeded'}

    payment_intent_id = intent.get('id')
    event_id = _limited_time_300k_payment_event_id(payment_intent_id)
    event_row = StripeWebhookEvent.query.filter_by(stripe_event_id=event_id).first()
    if event_row and bool(event_row.processed):
        return {'granted': False, 'reason': 'already_processed'}
    if event_row is None:
        event_row = StripeWebhookEvent(
            stripe_event_id=event_id,
            event_type='payment_intent.succeeded',
            processed=False,
        )
        db.session.add(event_row)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            event_row = StripeWebhookEvent.query.filter_by(stripe_event_id=event_id).first()
            if event_row and bool(event_row.processed):
                return {'granted': False, 'reason': 'already_processed'}
            if event_row is None:
                event_row = StripeWebhookEvent(
                    stripe_event_id=event_id,
                    event_type='payment_intent.succeeded',
                    processed=False,
                )
                db.session.add(event_row)
                db.session.flush()

    user_id = metadata.get('user_id')
    user = User.query.get(user_id) if user_id else None
    if not user:
        user = _find_user_for_billing_event(customer_id=intent.get('customer'))
    if not user:
        return {'granted': False, 'reason': 'user_not_found'}
    if expected_user and str(user.id) != str(expected_user.id):
        return {'granted': False, 'reason': 'wrong_user'}

    tokens = int(metadata.get('tokens') or 0)
    if tokens <= 0:
        return {'granted': False, 'reason': 'missing_tokens'}

    _entitlement, _grant, created = grant_limited_time_300k_offer(
        user,
        tokens,
        payment_reference=payment_intent_id,
        checkout_id=payment_intent_id,
        metadata={
            'campaign_id': metadata.get('campaign_id'),
            'stripe_payment_intent_id': payment_intent_id,
        },
    )
    if intent.get('customer'):
        user.stripe_customer_id = intent.get('customer')
    get_usage_meter_state(user, current_app.config)
    if created:
        _send_limited_time_300k_welcome_email(user, reference=payment_intent_id)
    event_row.processed = True
    event_row.processed_at = datetime.utcnow()
    current_app.logger.info(
        "payment_intent.succeeded: 300K Limited-Time grant created=%s tokens=%s user=%s",
        created, tokens, user.id,
    )
    return {'granted': True, 'tokens': tokens, 'user_id': str(user.id)}


def _invoice_payment_client_secret(invoice):
    """Client secret for the PaymentIntent backing a finalized invoice."""
    secret = _stripe_field(invoice, 'confirmation_secret')
    if isinstance(secret, str):
        return secret
    if secret is not None:
        nested = _stripe_field(secret, 'client_secret')
        if nested:
            return nested
    payment_intent = _stripe_field(invoice, 'payment_intent')
    if isinstance(payment_intent, str):
        try:
            payment_intent = stripe.PaymentIntent.retrieve(payment_intent)
        except stripe.error.StripeError:
            return ''
    nested = _stripe_field(payment_intent, 'client_secret', '') or ''
    if nested:
        return nested
    # Current API versions drop payment_intent from the invoice and only return
    # confirmation_secret on request, so ask for it explicitly before giving up.
    invoice_id = _stripe_field(invoice, 'id')
    if not invoice_id:
        return ''
    try:
        expanded = stripe.Invoice.retrieve(invoice_id, expand=['confirmation_secret'])
    except stripe.error.StripeError:
        return ''
    secret = _stripe_field(expanded, 'confirmation_secret')
    if isinstance(secret, str):
        return secret
    return _stripe_field(secret, 'client_secret', '') or ''


def _fulfill_limited_time_300k_invoice(invoice, expected_user=None):
    """Grant 300K credits for an invoice Stripe reports as paid.

    Stripe is the source of truth here: we only grant once it says the invoice
    is paid, the same way sync_embedded_subscription waits for Stripe to report
    the subscription active before applying a plan. Idempotent on invoice id.
    """
    metadata = _stripe_field(invoice, 'metadata') or {}
    if _stripe_field(metadata, 'checkout_type') != LIMITED_TIME_300K_CHECKOUT_TYPE:
        return {'granted': False, 'reason': 'not_limited_time_300k'}
    status = str(_stripe_field(invoice, 'status') or '').strip().lower()
    if status != 'paid':
        return {'granted': False, 'reason': status or 'not_paid'}

    invoice_id = _stripe_field(invoice, 'id')
    event_id = f'limited_time_300k_invoice:{invoice_id}'
    event_row = StripeWebhookEvent.query.filter_by(stripe_event_id=event_id).first()
    if event_row and bool(event_row.processed):
        return {'granted': False, 'reason': 'already_processed'}
    if event_row is None:
        event_row = StripeWebhookEvent(
            stripe_event_id=event_id,
            event_type='invoice.paid',
            processed=False,
        )
        db.session.add(event_row)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            event_row = StripeWebhookEvent.query.filter_by(stripe_event_id=event_id).first()
            if event_row and bool(event_row.processed):
                return {'granted': False, 'reason': 'already_processed'}
            if event_row is None:
                event_row = StripeWebhookEvent(
                    stripe_event_id=event_id,
                    event_type='invoice.paid',
                    processed=False,
                )
                db.session.add(event_row)
                db.session.flush()

    user_id = _stripe_field(metadata, 'user_id')
    user = User.query.get(user_id) if user_id else None
    if not user:
        user = _find_user_for_billing_event(customer_id=_stripe_field(invoice, 'customer'))
    if not user:
        return {'granted': False, 'reason': 'user_not_found'}
    if expected_user and str(user.id) != str(expected_user.id):
        return {'granted': False, 'reason': 'wrong_user'}

    tokens = int(_stripe_field(metadata, 'tokens') or 0)
    if tokens <= 0:
        tokens = int(current_app.config.get('LIMITED_TIME_300K_CREDIT_TOKENS') or 0)
    if tokens <= 0:
        return {'granted': False, 'reason': 'missing_tokens'}

    _entitlement, _grant, created = grant_limited_time_300k_offer(
        user,
        tokens,
        payment_reference=invoice_id,
        checkout_id=invoice_id,
        metadata={
            'campaign_id': _stripe_field(metadata, 'campaign_id'),
            'stripe_invoice_id': invoice_id,
            'promotion_code': _stripe_field(metadata, 'promotion_code'),
        },
    )
    customer_id = _stripe_field(invoice, 'customer')
    if customer_id:
        user.stripe_customer_id = customer_id
    get_usage_meter_state(user, current_app.config)
    if created:
        _send_limited_time_300k_welcome_email(
            user,
            amount_label=_price_label(int(_stripe_field(invoice, 'amount_paid', 0) or 0)),
            reference=invoice_id,
        )
    event_row.processed = True
    event_row.processed_at = datetime.utcnow()
    current_app.logger.info(
        'invoice.paid: 300K Limited-Time grant created=%s tokens=%s user=%s invoice=%s',
        created, tokens, user.id, invoice_id,
    )
    return {'granted': True, 'tokens': tokens, 'user_id': str(user.id)}


@billing_bp.route('/create-credit-pack-payment-intent', methods=['POST'])
@jwt_required()
def create_credit_pack_payment_intent():
    """Create an in-page PaymentIntent for a one-time credit pack."""
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({'msg': 'User not found'}), 404

    data = request.get_json() or {}
    pack_key = normalize_credit_pack_key(data.get('pack_key'))
    if not pack_key:
        return jsonify({'msg': 'Missing pack_key'}), 400

    packs = get_credit_packs(current_app.config)
    pack = packs.get(pack_key)
    if not pack:
        return jsonify({'msg': f'Unknown pack_key {pack_key}'}), 400

    amount = int(round(float(pack.get('price_usd') or 0) * 100))
    tokens = int(pack.get('credits') or 0)
    if amount <= 0 or tokens <= 0:
        return jsonify({'msg': f'Credit pack {pack_key} is not configured correctly'}), 400

    customer_id = _ensure_customer_for_user(user)
    intent = stripe.PaymentIntent.create(
        amount=amount,
        currency='usd',
        customer=customer_id,
        payment_method_types=['card'],
        setup_future_usage='off_session',
        description=f"Jaspen {pack.get('label') or pack_key}",
        metadata={
            'user_id': str(user.id),
            'pack_key': pack_key,
            'credits': str(int(tokens_to_credits(tokens, precision=0) or 0)),
            'tokens': str(tokens),
            'checkout_type': 'credit_pack',
        },
    )
    return jsonify({
        'client_secret': intent.client_secret,
        'publishable_key': current_app.config.get('STRIPE_PUBLISHABLE_KEY'),
        'pack_key': pack_key,
        'pack_label': pack.get('label') or pack_key,
        'price_label': f"${pack.get('price_usd')}",
    }), 200


@billing_bp.route('/confirm-credit-pack-payment', methods=['POST'])
@jwt_required()
def confirm_credit_pack_payment():
    """Finalize a completed in-page credit-pack payment immediately."""
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({'msg': 'User not found'}), 404

    data = request.get_json() or {}
    payment_intent_id = str(data.get('payment_intent_id') or '').strip()
    if not payment_intent_id:
        return jsonify({'msg': 'Missing payment_intent_id'}), 400

    try:
        intent = stripe.PaymentIntent.retrieve(payment_intent_id)
    except stripe.error.StripeError as exc:
        return jsonify({'msg': str(exc)}), 400

    result = _fulfill_credit_pack_payment_intent(intent, expected_user=user)
    if result.get('reason') == 'wrong_user':
        return jsonify({'msg': 'Payment does not belong to this user'}), 403
    if result.get('reason') not in {None, 'already_processed'} and not result.get('granted'):
        return jsonify({'msg': 'Payment is not ready yet', **result}), 409
    db.session.commit()
    return jsonify({'success': True, **result}), 200


@billing_bp.route('/create-checkout-session', methods=['POST'])
@jwt_required()
def create_checkout_session():
    """Create a self-serve subscription Checkout session for paid self-serve plans."""
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({'msg': 'User not found'}), 404

    data = request.get_json() or {}
    raw_plan_key = data.get('plan_key') or data.get('plan')
    plan_key = normalize_plan_key(raw_plan_key)
    billing_interval = _normalize_billing_interval(data.get('billing_interval'))
    if not raw_plan_key:
        return jsonify({'msg': 'Missing plan_key'}), 400

    plan_catalog = get_plan_catalog(current_app.config)
    if plan_key not in plan_catalog:
        return jsonify({'msg': f'Unknown plan_key {raw_plan_key}'}), 400

    if is_sales_only_plan(plan_key, current_app.config):
        return jsonify({
            'msg': f'{plan_catalog[plan_key]["label"]} is sales-led. Please contact sales.',
            'contact_sales': True,
            'plan_key': plan_key,
        }), 400

    if plan_key == 'free':
        apply_plan_to_user(user, 'free', current_app.config, reset_credits=True)
        user.stripe_subscription_id = None
        db.session.commit()
        return jsonify({
            'message': 'Moved to Free plan',
            'plan_key': 'free',
        }), 200

    price_id = _price_id_for_plan(plan_key, billing_interval, current_app.config)
    if not price_id:
        return jsonify({'msg': f"No {billing_interval} Stripe price configured for '{plan_key}'"}), 400

    customer_id = _ensure_customer_for_user(user)

    try:
        success_url = _validated_frontend_redirect(
            data.get('success_url'),
            fallback_path='/pricing?session_id={CHECKOUT_SESSION_ID}&status=success',
        )
        cancel_url = _validated_frontend_redirect(
            data.get('cancel_url'),
            fallback_path='/pricing?status=cancel',
        )
    except ValueError as exc:
        return jsonify({'msg': str(exc)}), 400

    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        mode='subscription',
        customer=customer_id,
        line_items=[{'price': price_id, 'quantity': 1}],
        metadata={
            'user_id': str(user.id),
            'plan_key': plan_key,
            'billing_interval': billing_interval,
            'checkout_type': 'subscription',
        },
        success_url=success_url,
        cancel_url=cancel_url,
        allow_promotion_codes=True,
    )
    return jsonify({'sessionId': session.id, 'url': session.url}), 200


@billing_bp.route('/config', methods=['GET'])
def billing_config():
    """Public Stripe config for the embedded Payment Element.

    The publishable key is designed to be exposed to the browser. Serving it from
    the backend keeps the frontend in lock-step with the backend's test/live mode.
    """
    return jsonify({
        'publishable_key': current_app.config.get('STRIPE_PUBLISHABLE_KEY') or '',
    }), 200


@billing_bp.route('/invoices', methods=['GET'])
@jwt_required()
def list_invoices():
    """Simple in-app payment history (date / amount / status) — so the user never
    has to leave for the Stripe-hosted invoice page."""
    user = User.query.get(get_jwt_identity())
    if not user or not user.stripe_customer_id:
        return jsonify({'invoices': []}), 200
    out = []
    try:
        resp = stripe.Invoice.list(customer=user.stripe_customer_id, limit=24)
    except stripe.error.StripeError:
        current_app.logger.exception('list_invoices failed')
    else:
        for inv in resp.get('data', []):
            amount = inv.get('amount_paid') or inv.get('total') or 0
            out.append({
                'id': inv.get('id'),
                'number': inv.get('number'),
                'description': inv.get('description') or inv.get('number') or 'Subscription',
                'created': inv.get('created'),
                'amount': amount,  # cents
                'currency': (inv.get('currency') or 'usd').upper(),
                'status': inv.get('status'),
                'hosted_invoice_url': inv.get('hosted_invoice_url'),
                'invoice_pdf': inv.get('invoice_pdf'),
            })

    try:
        intents = stripe.PaymentIntent.list(
            customer=user.stripe_customer_id,
            limit=24,
            expand=['data.latest_charge'],
        )
    except stripe.error.StripeError:
        current_app.logger.exception('list_invoices credit-pack payments failed')
    else:
        for intent in intents.get('data', []):
            metadata = intent.get('metadata') or {}
            if str(metadata.get('checkout_type') or '').strip() not in {'credit_pack', 'overage_pack'}:
                continue
            if intent.get('status') != 'succeeded':
                continue
            charge = intent.get('latest_charge')
            receipt_url = charge.get('receipt_url') if isinstance(charge, dict) else None
            out.append({
                'id': intent.get('id'),
                'number': None,
                'description': intent.get('description') or 'Credit pack',
                'created': intent.get('created'),
                'amount': intent.get('amount_received') or intent.get('amount') or 0,
                'currency': (intent.get('currency') or 'usd').upper(),
                'status': 'paid' if intent.get('status') == 'succeeded' else intent.get('status'),
                'hosted_invoice_url': receipt_url,
                'invoice_pdf': None,
            })
    out.sort(key=lambda item: int(item.get('created') or 0), reverse=True)
    return jsonify({'invoices': out}), 200


def _subscription_payment_client_secret(subscription):
    """Get the client_secret to confirm payment for an incomplete subscription,
    resilient to Stripe API version differences:
      - older versions:        invoice.payment_intent.client_secret
      - 2025-03-31 'basil'+:    invoice.confirmation_secret.client_secret
      - trials / nothing-due:   subscription.pending_setup_intent.client_secret
    Re-fetches the invoice with the correct expand so we don't depend on whatever
    field name the create call's API version used.
    """
    def _cs(obj):
        if obj is None:
            return None
        if hasattr(obj, 'get'):
            return obj.get('client_secret')
        return getattr(obj, 'client_secret', None)

    invoice_ref = subscription.get('latest_invoice') if hasattr(subscription, 'get') else None
    invoice_id = invoice_ref.get('id') if hasattr(invoice_ref, 'get') else invoice_ref
    if invoice_id:
        for expand in (['confirmation_secret'], ['payment_intent']):
            try:
                inv = stripe.Invoice.retrieve(invoice_id, expand=expand)
            except stripe.error.StripeError:
                continue
            secret = _cs(inv.get('confirmation_secret'))
            if secret:
                return secret
            pi = inv.get('payment_intent')
            if isinstance(pi, str):
                try:
                    pi = stripe.PaymentIntent.retrieve(pi)
                except stripe.error.StripeError:
                    pi = None
            secret = _cs(pi)
            if secret:
                return secret

    psi = subscription.get('pending_setup_intent') if hasattr(subscription, 'get') else None
    if isinstance(psi, str):
        try:
            psi = stripe.SetupIntent.retrieve(psi)
        except stripe.error.StripeError:
            psi = None
    return _cs(psi)


@billing_bp.route('/create-subscription', methods=['POST'])
@jwt_required()
def create_subscription_embedded():
    """Start a subscription for the EMBEDDED Payment Element (no redirect).

    Creates an incomplete subscription and returns the PaymentIntent client_secret
    so the frontend confirms payment in-page with our own branding. On success the
    webhook (invoice.payment_succeeded / customer.subscription.updated) activates the
    plan. We do NOT persist the subscription id here — abandoned/incomplete subs would
    leave a dangling id; the webhook reconciles via the (persisted) customer id +
    metadata. Existing paid subscribers upgrade/downgrade via /modify-subscription
    instead (their card is already on file — no Payment Element needed).
    """
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({'msg': 'User not found'}), 404

    data = request.get_json() or {}
    raw_plan_key = data.get('plan_key') or data.get('plan')
    plan_key = normalize_plan_key(raw_plan_key)
    billing_interval = _normalize_billing_interval(data.get('billing_interval'))
    if not raw_plan_key:
        return jsonify({'msg': 'Missing plan_key'}), 400

    plan_catalog = get_plan_catalog(current_app.config)
    if plan_key not in plan_catalog:
        return jsonify({'msg': f'Unknown plan_key {raw_plan_key}'}), 400
    if plan_key == 'free':
        return jsonify({'msg': 'The Free plan does not require payment.'}), 400
    if is_sales_only_plan(plan_key, current_app.config):
        return jsonify({
            'msg': f'{plan_catalog[plan_key]["label"]} is sales-led. Please contact sales.',
            'contact_sales': True,
            'plan_key': plan_key,
        }), 400

    price_id = _price_id_for_plan(plan_key, billing_interval, current_app.config)
    if not price_id:
        return jsonify({'msg': f"No {billing_interval} Stripe price configured for '{plan_key}'."}), 400

    coupon_code = str(data.get('coupon_code') or '').strip()
    discounts = []
    if coupon_code:
        try:
            matches = stripe.PromotionCode.list(code=coupon_code, active=True, limit=1)
            promotion = (matches.get('data') or [None])[0]
            if not promotion:
                return jsonify({'msg': 'That coupon code was not found or is no longer active.'}), 400
            discounts = [{'promotion_code': promotion.id}]
        except stripe.error.StripeError as exc:
            current_app.logger.warning('create-subscription: coupon lookup failed: %s', exc)
            return jsonify({'msg': 'Could not validate that coupon code. Please try again.'}), 400

    customer_id = _ensure_customer_for_user(user)

    # Reuse an existing INCOMPLETE subscription for this price instead of creating a
    # new one every time the user re-opens the modal (which piled up draft invoices).
    try:
        if not discounts:
            existing = stripe.Subscription.list(customer=customer_id, status='incomplete', limit=20)
            for sub in existing.get('data', []):
                items = (sub.get('items') or {}).get('data') or []
                if any(((it.get('price') or {}).get('id')) == price_id for it in items):
                    reuse_secret = _subscription_payment_client_secret(sub)
                    if reuse_secret:
                        return jsonify({
                            'subscription_id': sub.id,
                            'client_secret': reuse_secret,
                            'plan_key': plan_key,
                            'publishable_key': current_app.config.get('STRIPE_PUBLISHABLE_KEY') or '',
                        }), 200
    except stripe.error.StripeError:
        pass

    try:
        subscription_args = {
            'customer': customer_id,
            'items': [{'price': price_id}],
            'payment_behavior': 'default_incomplete',
            # card-only so the embedded form shows the full card fields (and so it's
            # testable without Stripe Link's SMS step). To allow Link/wallets later,
            # drop payment_method_types and/or enable them in the Stripe dashboard.
            'payment_settings': {'save_default_payment_method': 'on_subscription', 'payment_method_types': ['card']},
            'metadata': {
                'user_id': str(user.id),
                'plan_key': plan_key,
                'billing_interval': billing_interval,
                'checkout_type': 'subscription_embedded',
            },
        }
        if discounts:
            subscription_args['discounts'] = discounts
        subscription = stripe.Subscription.create(**subscription_args)
    except stripe.error.StripeError as exc:
        current_app.logger.exception('create-subscription (embedded) failed')
        return jsonify({'msg': str(getattr(exc, 'user_message', None) or 'Could not start the subscription.')}), 400

    client_secret = _subscription_payment_client_secret(subscription)
    if not client_secret:
        try:
            current_app.logger.error(
                'create-subscription: no client_secret (sub=%s status=%s)',
                getattr(subscription, 'id', '?'), subscription.get('status'),
            )
        except Exception:
            pass
        return jsonify({'msg': 'Could not initialize payment for this plan.'}), 400

    return jsonify({
        'subscription_id': subscription.id,
        'client_secret': client_secret,
        'plan_key': plan_key,
        'billing_interval': billing_interval,
        'publishable_key': current_app.config.get('STRIPE_PUBLISHABLE_KEY') or '',
    }), 200


# —— Standalone limited-time credit checkout ————
LIMITED_TIME_300K_CHECKOUT_TYPE = '300k_limited_time'


def _price_label(amount):
    return f"${amount // 100}" if amount % 100 == 0 else f"${amount / 100:.2f}"


def _stripe_field(obj, name, default=None):
    """Read a field from a Stripe object whether it behaves as an object or a dict.

    stripe-python returns StripeObjects that expose fields as attributes; plain
    dicts show up in tests and in partially-populated nested payloads. Reading
    only one way silently yields None for the other.
    """
    if obj is None:
        return default
    value = getattr(obj, name, None)
    if value is None and hasattr(obj, 'get'):
        try:
            value = obj.get(name)
        except Exception:
            value = None
    return default if value is None else value


def _trace_coupon(label, obj):
    """TEMPORARY: dump how Stripe shaped an object while tracking down a
    promo code whose nested coupon arrives empty. Remove with the rest of
    the 300K coupon diagnostics."""
    try:
        if isinstance(obj, str):
            detail = f'{label}: str={obj[:80]}'
        else:
            try:
                keys = sorted([str(k) for k in obj.keys()])[:25]
            except Exception:
                keys = '<no keys>'
            attrs = [a for a in ('id', 'coupon', 'percent_off', 'amount_off', 'valid', 'object')
                     if getattr(obj, a, None) is not None]
            detail = f'{label}: type={type(obj).__name__} keys={keys} attrs_present={attrs}'
        with open('/tmp/jaspen-coupon-debug.log', 'a') as handle:
            handle.write(f'{datetime.utcnow().isoformat()}Z TRACE {detail}\n')
    except Exception:
        pass


def _log_coupon_diagnostics(coupon_code, promotion_code_id, preview, currency, base_amount):
    """TEMPORARY: record what Stripe priced a promo code at.

    Journald needs root here, so this also appends to a file the app user can
    read while confirming the 300K coupon flow in production. Remove once the
    flow is verified end to end.
    """
    detail = (
        f"code={coupon_code} promo={promotion_code_id} type={type(preview).__name__} "
        f"base_amount={base_amount} currency={currency!r} "
        f"amount_due={_stripe_field(preview, 'amount_due')!r} "
        f"total={_stripe_field(preview, 'total')!r} "
        f"subtotal={_stripe_field(preview, 'subtotal')!r} "
        f"total_discount_amounts={_stripe_field(preview, 'total_discount_amounts')!r}"
    )
    current_app.logger.info('300k-limited-time coupon resolve: %s', detail)
    try:
        with open('/tmp/jaspen-coupon-debug.log', 'a') as handle:
            handle.write(f"{datetime.utcnow().isoformat()}Z {detail}\n")
    except Exception:
        pass


def _log_coupon_outcome(outcome, **fields):
    """TEMPORARY: record the branch the coupon flow ended on."""
    detail = ' '.join(f'{k}={v!r}' for k, v in fields.items())
    current_app.logger.info('300k-limited-time coupon outcome=%s %s', outcome, detail)
    try:
        with open('/tmp/jaspen-coupon-debug.log', 'a') as handle:
            handle.write(f'{datetime.utcnow().isoformat()}Z OUTCOME={outcome} {detail}\n')
    except Exception:
        pass


def _create_invoice_item_for_price(customer_id, price_id, invoice_id=None):
    """Put a one-time price onto a specific draft invoice.

    Two things here are version-sensitive and were getting this wrong in
    production. Stripe's current API takes the price nested under `pricing`;
    the top-level `price` form these calls used was removed, so every attempt
    failed with an unknown-parameter error before any discount was applied.
    And a standalone invoice does not pick up pending invoice items unless it
    asks for them, so the item is attached to the invoice by id rather than
    left floating on the customer - a floating item would otherwise land on
    whatever the customer is invoiced for next.
    """
    params = {'customer': customer_id}
    if invoice_id:
        params['invoice'] = invoice_id
    try:
        return stripe.InvoiceItem.create(pricing={'price': price_id}, **params)
    except stripe.error.InvalidRequestError as exc:
        # Older API versions took the price at the top level. Fall back rather
        # than break if this app is ever pinned back to one of them.
        if 'pricing' not in str(exc):
            raise
        return stripe.InvoiceItem.create(price=price_id, **params)


def _discard_limited_time_300k_invoice(invoice):
    """Throw away an offer invoice we are not going to collect.

    Used when a code turns out not to discount this offer, and when a buyer
    applies a second code - otherwise each attempt leaves an open invoice on
    the customer that Stripe will keep chasing.
    """
    invoice_id = _stripe_field(invoice, 'id')
    if not invoice_id:
        return
    status = str(_stripe_field(invoice, 'status') or '').strip().lower()
    try:
        if status == 'draft':
            stripe.Invoice.delete(invoice_id)
        elif status in {'open', 'uncollectible'}:
            stripe.Invoice.void_invoice(invoice_id)
    except stripe.error.StripeError as exc:
        current_app.logger.warning('300k-limited-time: could not discard invoice %s: %s', invoice_id, exc)


def _discard_open_limited_time_300k_invoices(customer_id):
    """Clear this customer's unpaid offer invoices before starting another.

    Applying a promo code, then trying a different one, used to leave the first
    invoice open and payable. Only invoices carrying this checkout type are
    touched, so a buyer's subscription invoices are never affected.
    """
    if not customer_id:
        return
    try:
        invoices = stripe.Invoice.list(customer=customer_id, limit=20)
    except stripe.error.StripeError as exc:
        current_app.logger.warning('300k-limited-time: could not list invoices to clean up: %s', exc)
        return
    for invoice in _stripe_field(invoices, 'data') or []:
        metadata = _stripe_field(invoice, 'metadata') or {}
        if _stripe_field(metadata, 'checkout_type') != LIMITED_TIME_300K_CHECKOUT_TYPE:
            continue
        if str(_stripe_field(invoice, 'status') or '').strip().lower() not in {'draft', 'open'}:
            continue
        _discard_limited_time_300k_invoice(invoice)


def _resolve_300k_limited_time_amount(price_id, coupon_code, customer_id=None):
    """Returns (amount, currency, promotion_code_id, error_response).

    The discount math is Stripe's, not ours. The subscription flow above hands
    Stripe a promotion_code and lets it price the result; reading percent_off
    off the promotion code here instead produced no discount at all, because
    the nested coupon on a PromotionCode.list() result comes back empty. So
    price a throwaway invoice preview with the same promotion_code and use the
    total Stripe computes.
    """
    try:
        price = stripe.Price.retrieve(price_id)
    except stripe.error.StripeError as exc:
        current_app.logger.exception('300k-limited-time: could not retrieve price')
        return None, None, None, (str(getattr(exc, 'user_message', None) or 'Could not start checkout.'), 400)
    amount = int(_stripe_field(price, 'unit_amount', 0) or 0)
    currency = _stripe_field(price, 'currency') or 'usd'
    if amount <= 0:
        return None, None, None, ('The limited-time offer price is not configured correctly.', 503)

    coupon_code = str(coupon_code or '').strip()
    promotion_code_id = ''
    if not coupon_code:
        return amount, currency, promotion_code_id, None
    if not customer_id:
        return None, None, None, ('Could not apply that coupon to this account.', 400)

    try:
        matches = stripe.PromotionCode.list(code=coupon_code, active=True, limit=1)
        promotion = (_stripe_field(matches, 'data') or [None])[0]
        if not promotion:
            return None, None, None, ('That coupon code was not found or is no longer active.', 400)
        promotion_code_id = _stripe_field(promotion, 'id', '')

        preview = stripe.Invoice.create_preview(
            customer=customer_id,
            invoice_items=[{'price': price_id}],
            discounts=[{'promotion_code': promotion_code_id}],
        )
        discounted = _stripe_field(preview, 'amount_due')
        if discounted is None:
            discounted = _stripe_field(preview, 'total')
        _log_coupon_diagnostics(coupon_code, promotion_code_id, preview, currency, amount)
        if discounted is None:
            return None, None, None, ('Could not price that coupon code. Please try again.', 400)
        discounted = max(0, int(discounted))
        if discounted >= amount:
            return None, None, None, (
                'That code was found but does not reduce the price of this offer.', 400,
            )
        amount = discounted
    except stripe.error.StripeError as exc:
        current_app.logger.warning('300k-limited-time: coupon pricing failed: %s', exc)
        _trace_coupon('preview-failed', repr(exc))
        return None, None, None, (
            str(getattr(exc, 'user_message', None) or 'Could not validate that coupon code. Please try again.'),
            400,
        )

    return amount, currency, promotion_code_id, None


@billing_bp.route('/create-300k-limited-time-payment-intent', methods=['POST'])
@jwt_required()
def create_300k_limited_time_payment_intent():
    """Create an in-page PaymentIntent for the standalone limited-time credit offer.

    Embedded (Stripe Elements) rather than a redirect to Stripe's hosted
    Checkout page, so the buyer never leaves jaspen.ai. Created at full
    price - a promo code is applied afterward, on the payment screen itself,
    via apply_300k_limited_time_coupon below.
    """
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({'msg': 'User not found'}), 404

    data = request.get_json() or {}
    if data.get('terms_accepted') is not True or data.get('final_sale_acknowledged') is not True:
        return jsonify({'msg': 'Accept both purchase acknowledgements before continuing.'}), 400
    price_id = current_app.config.get('STRIPE_LIMITED_TIME_300K_PRICE_ID')
    if not price_id:
        return jsonify({'msg': 'The limited-time offer price is not configured yet.'}), 503
    credit_tokens = int(current_app.config.get('LIMITED_TIME_300K_CREDIT_TOKENS') or 0)
    if credit_tokens <= 0:
        return jsonify({'msg': 'The limited-time offer credit amount is not configured.'}), 503

    return_path = str(data.get('return_path') or '/limited-time/client-decisions').strip()
    allowed_return_paths = {
        '/limited-time/client-decisions',
        '/limited-time/project-prioritization',
        '/limited-time/strategic-planning',
    }
    if return_path not in allowed_return_paths:
        return jsonify({'msg': 'Invalid campaign return path.'}), 400

    amount, currency, _promotion_code_id, error = _resolve_300k_limited_time_amount(price_id, None)
    if error:
        return jsonify({'msg': error[0]}), error[1]

    customer_id = _ensure_customer_for_user(user)
    metadata = {
        'user_id': str(user.id),
        'checkout_type': LIMITED_TIME_300K_CHECKOUT_TYPE,
        'tokens': str(credit_tokens),
        'campaign_id': str(data.get('campaign_id') or '').strip()[:80],
        'terms_accepted': 'true',
        'final_sale_acknowledged': 'true',
        'acknowledged_at': datetime.utcnow().replace(microsecond=0).isoformat() + 'Z',
    }
    try:
        intent = stripe.PaymentIntent.create(
            amount=amount,
            currency=currency,
            customer=customer_id,
            payment_method_types=['card'],
            description='Jaspen 300K Limited-Time offer',
            metadata=metadata,
        )
    except stripe.error.StripeError as exc:
        current_app.logger.exception('create-300k-limited-time-payment-intent failed')
        return jsonify({'msg': str(getattr(exc, 'user_message', None) or 'Could not start checkout.')}), 400
    return jsonify({
        'client_secret': intent.client_secret,
        'publishable_key': current_app.config.get('STRIPE_PUBLISHABLE_KEY') or '',
        'price_label': _price_label(amount),
    }), 200


@billing_bp.route('/apply-300k-limited-time-coupon', methods=['POST'])
@jwt_required()
def apply_300k_limited_time_coupon():
    """Re-price an existing, not-yet-confirmed 300K Limited-Time PaymentIntent.

    Called from the payment screen itself (where the card fields already are)
    so the buyer sees the reduced price before paying, rather than needing to
    guess on an earlier acknowledgements screen. An empty coupon_code resets
    back to full price.
    """
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({'msg': 'User not found'}), 404

    data = request.get_json() or {}
    payment_intent_id = str(data.get('payment_intent_id') or '').strip()
    if not payment_intent_id:
        return jsonify({'msg': 'Missing payment_intent_id'}), 400

    try:
        intent = stripe.PaymentIntent.retrieve(payment_intent_id)
    except stripe.error.StripeError as exc:
        return jsonify({'msg': str(exc)}), 400

    intent_metadata = _stripe_field(intent, 'metadata') or {}
    if _stripe_field(intent_metadata, 'checkout_type') != LIMITED_TIME_300K_CHECKOUT_TYPE:
        return jsonify({'msg': 'Payment not found'}), 404
    if _stripe_field(intent_metadata, 'user_id') != str(user.id):
        return jsonify({'msg': 'Payment does not belong to this user'}), 403
    intent_status = str(_stripe_field(intent, 'status') or '')
    # 'canceled' is expected on a second attempt: applying a code moves the
    # charge onto an invoice and cancels this intent, and the buyer must still
    # be able to try a different code after that.
    if intent_status not in {'requires_payment_method', 'requires_confirmation', 'canceled'}:
        return jsonify({'msg': 'This payment can no longer be modified.'}), 409

    price_id = current_app.config.get('STRIPE_LIMITED_TIME_300K_PRICE_ID')
    if not price_id:
        return jsonify({'msg': 'The limited-time offer price is not configured yet.'}), 503
    coupon_code = str(data.get('coupon_code') or '').strip()
    if not coupon_code:
        return jsonify({'msg': 'Enter a promo code to apply.'}), 400
    customer_id = _stripe_field(intent, 'customer') or _ensure_customer_for_user(user)

    try:
        matches = stripe.PromotionCode.list(code=coupon_code, active=True, limit=1)
        promotion = (_stripe_field(matches, 'data') or [None])[0]
        if not promotion:
            return jsonify({'msg': 'That coupon code was not found or is no longer active.'}), 400
        promotion_code_id = _stripe_field(promotion, 'id', '')

        # Hand the discount to Stripe on a real invoice rather than pricing it
        # here, so Stripe records the redemption and owns the money movement -
        # the same way create_subscription attaches discounts to the
        # subscription instead of computing a reduced amount itself.
        _discard_open_limited_time_300k_invoices(customer_id)
        invoice = stripe.Invoice.create(
            customer=customer_id,
            discounts=[{'promotion_code': promotion_code_id}],
            auto_advance=False,
            collection_method='charge_automatically',
            description='Jaspen 300K Limited-Time offer',
            metadata={
                'user_id': str(user.id),
                'checkout_type': LIMITED_TIME_300K_CHECKOUT_TYPE,
                'tokens': str(_stripe_field(intent_metadata, 'tokens') or ''),
                'campaign_id': str(_stripe_field(intent_metadata, 'campaign_id') or ''),
                'promotion_code': coupon_code,
            },
        )
        _create_invoice_item_for_price(customer_id, price_id, _stripe_field(invoice, 'id'))
        # confirmation_secret is only returned when asked for, and without it
        # there is no client secret to hand a partially discounted payment.
        invoice = stripe.Invoice.finalize_invoice(
            _stripe_field(invoice, 'id'), expand=['confirmation_secret'],
        )
    except stripe.error.StripeError as exc:
        current_app.logger.exception('apply-300k-limited-time-coupon: invoice failed')
        return jsonify({
            'msg': str(getattr(exc, 'user_message', None) or 'Could not apply that coupon.'),
        }), 400

    invoice_id = _stripe_field(invoice, 'id')
    amount_due = int(_stripe_field(invoice, 'amount_due', 0) or 0)
    subtotal = int(_stripe_field(invoice, 'subtotal', 0) or 0)
    total = _stripe_field(invoice, 'total')
    total = subtotal if total is None else int(total)
    _log_coupon_diagnostics(coupon_code, promotion_code_id, invoice, 'usd', 99900)

    # An invoice that never picked up the offer line must not be mistaken for a
    # fully discounted one - that would hand out the credits for nothing.
    if subtotal <= 0:
        _discard_limited_time_300k_invoice(invoice)
        _log_coupon_outcome('empty_invoice', invoice=invoice_id, subtotal=subtotal)
        return jsonify({'msg': 'Could not price this offer. Please try again.'}), 400

    if total >= subtotal:
        # Stripe accepted the code but it does not apply to this product,
        # usually because the coupon is restricted to the subscription prices.
        _discard_limited_time_300k_invoice(invoice)
        _log_coupon_outcome('no_discount', invoice=invoice_id, subtotal=subtotal, total=total)
        return jsonify({
            'msg': 'That code was found but does not reduce the price of this offer.',
        }), 400

    if amount_due <= 0:
        # Stripe finalizes a fully-discounted invoice straight to paid, so the
        # redemption is recorded on its side before we grant anything.
        result = _fulfill_limited_time_300k_invoice(invoice, expected_user=user)
        if not result.get('granted') and result.get('reason') not in {None, 'already_processed'}:
            _log_coupon_outcome('free_not_granted', invoice=invoice_id, **result)
            return jsonify({'msg': 'Could not redeem this offer.', **result}), 409
        db.session.commit()
        try:
            stripe.PaymentIntent.cancel(payment_intent_id)
        except stripe.error.StripeError:
            pass  # the invoice already settled this purchase; a stale intent is harmless
        _log_coupon_outcome('free_granted', invoice=invoice_id, **result)
        return jsonify({'free': True, 'price_label': '$0.00', 'invoice_id': invoice_id, **result}), 200

    # Partially discounted: Stripe priced it, and the buyer pays that invoice.
    client_secret = _invoice_payment_client_secret(invoice)
    if not client_secret:
        return jsonify({'msg': 'Could not initialize payment for that coupon.'}), 400
    try:
        stripe.PaymentIntent.cancel(payment_intent_id)
    except stripe.error.StripeError:
        pass  # superseded by the invoice's own payment intent
    _log_coupon_outcome('repriced', invoice=invoice_id, amount_due=amount_due)
    return jsonify({
        'price_label': _price_label(amount_due),
        'invoice_id': invoice_id,
        'client_secret': client_secret,
    }), 200


@billing_bp.route('/confirm-300k-limited-time-payment', methods=['POST'])
@jwt_required()
def confirm_300k_limited_time_payment():
    """Finalize a completed in-page 300K Limited-Time payment immediately.

    A safety net alongside the payment_intent.succeeded webhook - both paths
    are idempotent (see _fulfill_limited_time_300k_payment_intent), so
    whichever arrives first grants the credits.
    """
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({'msg': 'User not found'}), 404

    data = request.get_json() or {}
    payment_intent_id = str(data.get('payment_intent_id') or '').strip()
    invoice_id = str(data.get('invoice_id') or '').strip()
    if not payment_intent_id and not invoice_id:
        return jsonify({'msg': 'Missing payment_intent_id'}), 400

    # A discounted purchase is paid through an invoice, and that invoice's own
    # payment intent carries none of our metadata - so fulfil from the invoice
    # when the frontend tells us the payment went through one.
    if invoice_id:
        try:
            invoice = stripe.Invoice.retrieve(invoice_id)
        except stripe.error.StripeError as exc:
            return jsonify({'msg': str(exc)}), 400
        result = _fulfill_limited_time_300k_invoice(invoice, expected_user=user)
        if result.get('reason') == 'wrong_user':
            return jsonify({'msg': 'Payment does not belong to this user'}), 403
        if result.get('reason') not in {None, 'already_processed'} and not result.get('granted'):
            return jsonify({'msg': 'Payment is not ready yet', **result}), 409
        db.session.commit()
        return jsonify({'success': True, **result}), 200

    try:
        intent = stripe.PaymentIntent.retrieve(payment_intent_id)
    except stripe.error.StripeError as exc:
        return jsonify({'msg': str(exc)}), 400

    result = _fulfill_limited_time_300k_payment_intent(intent, expected_user=user)
    if result.get('reason') == 'wrong_user':
        return jsonify({'msg': 'Payment does not belong to this user'}), 403
    if result.get('reason') not in {None, 'already_processed'} and not result.get('granted'):
        return jsonify({'msg': 'Payment is not ready yet', **result}), 409
    db.session.commit()
    return jsonify({'success': True, **result}), 200


@billing_bp.route('/sync-embedded-subscription', methods=['POST'])
@jwt_required()
def sync_embedded_subscription():
    """Confirm an embedded subscription after Stripe accepts payment.

    Stripe's embedded confirmation can occasionally take longer than the UI
    should wait, especially around saved cards, coupons, and invoice finalizing.
    This endpoint lets the frontend ask our backend to verify the subscription
    directly with Stripe, then apply the plan only after Stripe reports it in
    good standing.
    """
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({'msg': 'User not found'}), 404

    data = request.get_json() or {}
    subscription_id = str(data.get('subscription_id') or '').strip()
    expected_plan = normalize_plan_key(data.get('plan_key')) if data.get('plan_key') else None
    if not subscription_id:
        return jsonify({'msg': 'Missing subscription_id'}), 400

    try:
        subscription = stripe.Subscription.retrieve(subscription_id, expand=['latest_invoice'])
    except stripe.error.StripeError as exc:
        current_app.logger.warning('sync-embedded-subscription: retrieve failed for %s: %s', subscription_id, exc)
        return jsonify({'active': False, 'msg': 'Subscription is not ready yet.'}), 200

    customer_id = subscription.get('customer')
    if user.stripe_customer_id and customer_id and str(customer_id) != str(user.stripe_customer_id):
        return jsonify({'msg': 'Subscription does not belong to this account.'}), 403
    if not user.stripe_customer_id and customer_id:
        user.stripe_customer_id = customer_id

    meta = subscription.get('metadata') or {}
    plan_key = normalize_plan_key(meta.get('plan_key')) if meta.get('plan_key') else None
    if not plan_key or plan_key == 'free':
        items = (subscription.get('items') or {}).get('data') or []
        price_id = (items[0].get('price') or {}).get('id') if items else None
        plan_key = _plan_key_for_price_id(price_id, current_app.config)

    if expected_plan and plan_key and plan_key != expected_plan:
        return jsonify({
            'active': False,
            'msg': 'Subscription plan does not match the selected plan.',
            'plan_key': plan_key,
        }), 409

    status = str(subscription.get('status') or '').strip().lower()
    latest_invoice = subscription.get('latest_invoice')
    invoice_paid = True
    if isinstance(latest_invoice, dict):
        invoice_status = str(latest_invoice.get('status') or '').strip().lower()
        invoice_paid = invoice_status in ('', 'paid')

    if status in ('active', 'trialing') and invoice_paid and plan_key and plan_key != 'free':
        already_applied = (
            user.stripe_subscription_id == subscription_id
            and to_public_plan(user.subscription_plan) == plan_key
            and user.subscription_status in ('active', 'trialing')
        )
        if not already_applied:
            apply_plan_to_user(user, plan_key, current_app.config, reset_credits=True)
        user.stripe_subscription_id = subscription_id
        user.subscription_status = status
        db.session.commit()
        return jsonify({
            'active': True,
            'plan_key': plan_key,
            'subscription_status': status,
        }), 200

    db.session.commit()
    return jsonify({
        'active': False,
        'plan_key': plan_key,
        'subscription_status': status,
    }), 200


@billing_bp.route('/create-setup-intent', methods=['POST'])
@jwt_required()
def create_setup_intent_embedded():
    """For the EMBEDDED 'update / add payment method' flow (no Stripe portal).

    Returns a SetupIntent client_secret so the user can save a card in our own UI.
    After confirmSetup succeeds the frontend calls /set-default-payment-method.
    """
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({'msg': 'User not found'}), 404
    customer_id = _ensure_customer_for_user(user)
    try:
        si = stripe.SetupIntent.create(
            customer=customer_id,
            payment_method_types=['card'],
            usage='off_session',
            metadata={'user_id': str(user.id)},
        )
    except stripe.error.StripeError as exc:
        current_app.logger.exception('create-setup-intent failed')
        return jsonify({'msg': str(getattr(exc, 'user_message', None) or 'Could not start.')}), 400
    return jsonify({
        'client_secret': si.client_secret,
        'publishable_key': current_app.config.get('STRIPE_PUBLISHABLE_KEY') or '',
    }), 200


@billing_bp.route('/set-default-payment-method', methods=['POST'])
@jwt_required()
def set_default_payment_method():
    """Make a saved card the default for invoices + the active subscription."""
    user = User.query.get(get_jwt_identity())
    if not user or not user.stripe_customer_id:
        return jsonify({'msg': 'No billing account found.'}), 404
    pm_id = (request.get_json() or {}).get('payment_method_id')
    if not pm_id:
        return jsonify({'msg': 'Missing payment_method_id'}), 400
    try:
        stripe.Customer.modify(
            user.stripe_customer_id,
            invoice_settings={'default_payment_method': pm_id},
        )
        if user.stripe_subscription_id:
            stripe.Subscription.modify(user.stripe_subscription_id, default_payment_method=pm_id)
    except stripe.error.StripeError as exc:
        current_app.logger.exception('set-default-payment-method failed')
        return jsonify({'msg': str(getattr(exc, 'user_message', None) or 'Could not update the card.')}), 400
    return jsonify({'ok': True}), 200


# Plan tier used to detect upgrade vs downgrade direction.
_PLAN_TIER = {'free': 0, 'starter': 1, 'essential': 2, 'team': 3, 'business': 4}


def _seat_billing_context(user):
    org, membership = resolve_active_org_for_user(user)
    plan_key = to_public_plan(getattr(org, 'plan_key', None) or user.subscription_plan)
    plan = get_plan_catalog(current_app.config).get(plan_key) or {}
    if plan_key not in {'team', 'business'}:
        return None, ({'msg': 'Seat add-ons are available only on Team and Business.'}, 404)
    if not org or not membership or not can_manage_org(membership.role):
        return None, ({'msg': 'Only an organization owner or admin can manage seats.'}, 403)

    included = int(plan.get('included_seats') or plan.get('min_seats') or 0)
    maximum = int(plan.get('max_total_paid_seats') or included)
    current = int(getattr(org, 'max_total_paid_seats', None) or included)
    current = max(included, min(current, maximum))
    usage = build_seat_usage(org) or {}
    subscription = None
    billing_interval = 'monthly'
    if user.stripe_subscription_id:
        try:
            subscription = stripe.Subscription.retrieve(user.stripe_subscription_id)
        except stripe.error.StripeError as exc:
            return None, ({'msg': str(getattr(exc, 'user_message', None) or 'Could not verify the subscription billing interval.')}, 400)
        items = (subscription.get('items') or {}).get('data') or []
        annual_price_ids = set(
            value for value in (current_app.config.get('STRIPE_ANNUAL_PRICE_IDS', {}) or {}).values() if value
        )
        if any(str((item.get('price') or {}).get('id') or '') in annual_price_ids for item in items):
            billing_interval = 'annual'
        elif str((subscription.get('metadata') or {}).get('billing_interval') or '').strip().lower() == 'annual':
            billing_interval = 'annual'

    seat_mapping_name = (
        'STRIPE_ANNUAL_ADDITIONAL_SEAT_PRICE_IDS'
        if billing_interval == 'annual'
        else 'STRIPE_ADDITIONAL_SEAT_PRICE_IDS'
    )
    return {
        'org': org,
        'membership': membership,
        'plan_key': plan_key,
        'plan': plan,
        'included_seats': included,
        'current_seats': current,
        'additional_seats': max(0, current - included),
        'max_total_seats': maximum,
        'used_seats': int(usage.get('total_paid_used') or 0),
        'billing_interval': billing_interval,
        'subscription': subscription,
        'price_id': (current_app.config.get(seat_mapping_name, {}) or {}).get(plan_key),
    }, None


def _seat_billing_payload(ctx):
    monthly_seat_price = ctx['plan'].get('additional_seat_price')
    displayed_seat_price = (
        monthly_seat_price * 12
        if ctx['billing_interval'] == 'annual' and monthly_seat_price is not None
        else monthly_seat_price
    )
    return {
        'available': True,
        'plan_key': ctx['plan_key'],
        'plan_label': ctx['plan'].get('label', ctx['plan_key'].title()),
        'seat_product_label': f"{ctx['plan'].get('label', ctx['plan_key'].title())} Seat",
        'included_seats': ctx['included_seats'],
        'current_seats': ctx['current_seats'],
        'additional_seats': ctx['additional_seats'],
        'max_total_seats': ctx['max_total_seats'],
        'used_seats': ctx['used_seats'],
        'billing_interval': ctx['billing_interval'],
        'additional_seat_price_usd': displayed_seat_price,
        'purchase_configured': bool(ctx['price_id']),
        'can_purchase': str(ctx['membership'].role or '').lower() == 'owner',
    }


@billing_bp.route('/seats', methods=['GET'])
@jwt_required()
def get_seat_billing():
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({'msg': 'User not found'}), 404
    ctx, error = _seat_billing_context(user)
    if error:
        body, status = error
        return jsonify(body), status
    return jsonify(_seat_billing_payload(ctx)), 200


@billing_bp.route('/seats', methods=['POST'])
@jwt_required()
def add_billed_seat():
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({'msg': 'User not found'}), 404
    ctx, error = _seat_billing_context(user)
    if error:
        body, status = error
        return jsonify(body), status
    if str(ctx['membership'].role or '').lower() != 'owner':
        return jsonify({'msg': 'Only the organization owner can purchase seats.'}), 403
    if not user.stripe_subscription_id:
        return jsonify({'msg': 'No active subscription to add a seat to.'}), 400
    if not ctx['price_id']:
        return jsonify({'msg': f"{ctx['plan'].get('label')} seat purchasing is not configured yet."}), 503
    target = ctx['current_seats'] + 1
    if target > ctx['max_total_seats']:
        upgrade = 'Business' if ctx['plan_key'] == 'team' else 'Enterprise'
        return jsonify({'msg': f"{ctx['plan'].get('label')} supports up to {ctx['max_total_seats']} users. Contact Sales about {upgrade}."}), 400

    quantity = target - ctx['included_seats']
    try:
        subscription = ctx['subscription'] or stripe.Subscription.retrieve(user.stripe_subscription_id)
        items = (subscription.get('items') or {}).get('data') or []
        seat_item = next(
            (item for item in items if str((item.get('price') or {}).get('id') or '') == str(ctx['price_id'])),
            None,
        )
        item_change = (
            {'id': seat_item.get('id'), 'quantity': quantity}
            if seat_item else {'price': ctx['price_id'], 'quantity': quantity}
        )
        updated = stripe.Subscription.modify(
            user.stripe_subscription_id,
            items=[item_change],
            proration_behavior='always_invoice',
            expand=['latest_invoice'],
        )
    except stripe.error.StripeError as exc:
        return jsonify({'msg': str(getattr(exc, 'user_message', None) or exc)}), 400

    latest_invoice = updated.get('latest_invoice')
    invoice_status = str(latest_invoice.get('status') or '').lower() if isinstance(latest_invoice, dict) else ''
    subscription_status = str(updated.get('status') or '').lower()
    if subscription_status not in {'active', 'trialing'} or invoice_status not in {'', 'paid'}:
        return jsonify({
            'msg': "We couldn't add the seat because the prorated payment did not complete.",
            'payment_problem': True,
        }), 402

    ctx['org'].max_total_paid_seats = target
    db.session.commit()
    ctx['current_seats'] = target
    ctx['additional_seats'] = quantity
    return jsonify({**_seat_billing_payload(ctx), 'success': True}), 200


@billing_bp.route('/modify-subscription', methods=['POST'])
@jwt_required()
def modify_subscription():
    """Modify an existing paid subscription in-place.

    Upgrades (higher tier): prorate immediately — Stripe charges the
    difference for the rest of the current cycle and the new plan is
    active right away.

    Downgrades (lower tier): no immediate charge or credit — the new
    (lower) price is scheduled in Stripe metadata and applied the next
    time invoice.payment_succeeded fires (i.e. at the start of the next
    billing cycle). The user keeps their current plan and credits until
    then.
    """
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({'msg': 'User not found'}), 404
    if not user.stripe_subscription_id:
        return jsonify({'msg': 'No active subscription to modify'}), 400

    data = request.get_json() or {}
    raw_plan_key = data.get('plan_key') or data.get('plan')
    if not raw_plan_key:
        return jsonify({'msg': 'Missing plan_key'}), 400
    plan_key = normalize_plan_key(raw_plan_key)
    billing_interval = _normalize_billing_interval(data.get('billing_interval'))

    plan_catalog = get_plan_catalog(current_app.config)
    if plan_key not in plan_catalog:
        return jsonify({'msg': f'Unknown plan_key {raw_plan_key}'}), 400
    if plan_key == 'free':
        return jsonify({
            'msg': 'Use cancel-subscription to move to free at period end.',
            'plan_key': plan_key,
        }), 400
    if is_sales_only_plan(plan_key, current_app.config):
        return jsonify({
            'msg': f'{plan_catalog[plan_key]["label"]} is sales-led. Please contact sales.',
            'contact_sales': True,
            'plan_key': plan_key,
        }), 400

    price_id = _price_id_for_plan(plan_key, billing_interval, current_app.config)
    if not price_id:
        return jsonify({'msg': f"No {billing_interval} Stripe price configured for '{plan_key}'"}), 400

    current_plan = to_public_plan(user.subscription_plan)
    current_tier = _PLAN_TIER.get(current_plan, 0)
    new_tier = _PLAN_TIER.get(plan_key, 0)
    is_upgrade = new_tier > current_tier

    try:
        subscription = stripe.Subscription.retrieve(user.stripe_subscription_id)
        items = (subscription.get('items') or {}).get('data') or []
        if not items:
            return jsonify({'msg': 'Subscription has no modifiable items'}), 400
        item_id = items[0].get('id')
        if not item_id:
            return jsonify({'msg': 'Subscription item missing id'}), 400

        if is_upgrade:
            # Charge the prorated difference immediately ('always_invoice'):
            # Stripe finalizes and attempts to pay an invoice for the proration
            # right now, so the charge shows up as a real transaction and we can
            # tell — synchronously — whether the card on file was accepted.
            updated = stripe.Subscription.modify(
                user.stripe_subscription_id,
                items=[{'id': item_id, 'price': price_id}],
                proration_behavior='always_invoice',
                metadata={'scheduled_plan_change': '', 'billing_interval': billing_interval},
                expand=['latest_invoice'],
            )
        else:
            # Downgrade: schedule for next cycle, no immediate charge/credit.
            updated = stripe.Subscription.modify(
                user.stripe_subscription_id,
                items=[{'id': item_id, 'price': price_id}],
                proration_behavior='none',
                metadata={'scheduled_plan_change': plan_key, 'billing_interval': billing_interval},
            )
    except stripe.error.StripeError as exc:
        return jsonify({'msg': str(exc)}), 400

    stripe_customer = updated.get('customer')
    if stripe_customer:
        user.stripe_customer_id = stripe_customer
    user.subscription_status = str(updated.get('status') or '').strip().lower() or user.subscription_status

    if is_upgrade:
        # Guard: only grant the higher tier if Stripe actually accepted payment.
        # With 'always_invoice' the prorated charge is attempted now, so we check
        # both the subscription status and the proration invoice's payment state.
        # If the card on file is declined we must NOT hand out premium access
        # (see P0: enforce subscription_status).
        invoice_paid = True
        latest_invoice = updated.get('latest_invoice')
        if isinstance(latest_invoice, dict):
            inv_status = str(latest_invoice.get('status') or '').strip().lower()
            # 'paid' = charged; '' / no invoice = $0 proration (nothing to charge).
            # Anything else ('open', 'uncollectible', …) means payment didn't land.
            invoice_paid = inv_status in ('', 'paid')
        status_ok = user.subscription_status in ('active', 'trialing')
        if not (status_ok and invoice_paid):
            db.session.commit()  # persist the status change, but keep the old plan
            return jsonify({
                'success': False,
                'payment_problem': True,
                'msg': (
                    "We couldn't complete the upgrade — the payment on your card "
                    "on file didn't go through. Update your payment method and try "
                    "again."
                ),
                'plan_key': current_plan,
                'subscription_status': user.subscription_status,
            }), 402

        apply_plan_to_user(user, plan_key, current_app.config, reset_credits=False)
        db.session.commit()
        return jsonify({
            'success': True,
            'effective': 'immediate',
            'plan_key': plan_key,
            'billing_interval': billing_interval,
            'plan_label': plan_catalog[plan_key].get('label', plan_key),
            'subscription_status': user.subscription_status,
        }), 200
    else:
        current_period_end = updated.get('current_period_end')
        period_end_iso = (
            time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(current_period_end))
            if current_period_end else None
        )
        db.session.commit()
        return jsonify({
            'success': True,
            'effective': 'period_end',
            'plan_key': plan_key,
            'billing_interval': billing_interval,
            'plan_label': plan_catalog[plan_key].get('label', plan_key),
            'current_plan_label': plan_catalog.get(current_plan, {}).get('label', current_plan),
            'current_period_end': current_period_end,
            'current_period_end_iso': period_end_iso,
            'subscription_status': user.subscription_status,
        }), 200


def _create_credit_pack_checkout_session():
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({'msg': 'User not found'}), 404

    data = request.get_json() or {}
    pack_key = normalize_credit_pack_key(data.get('pack_key'))
    if not pack_key:
        return jsonify({'msg': 'Missing pack_key'}), 400

    packs = get_credit_packs(current_app.config)
    pack = packs.get(pack_key)
    if not pack:
        return jsonify({'msg': f'Unknown pack_key {pack_key}'}), 400

    price_id = pack.get('stripe_price_id')
    if not price_id:
        return jsonify({'msg': f"No Stripe price configured for '{pack_key}'"}), 400

    customer_id = _ensure_customer_for_user(user)

    try:
        success_url = _validated_frontend_redirect(
            data.get('success_url'),
            fallback_path='/pricing?status=success',
        )
        cancel_url = _validated_frontend_redirect(
            data.get('cancel_url'),
            fallback_path='/pricing?status=cancel',
        )
    except ValueError as exc:
        return jsonify({'msg': str(exc)}), 400

    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        mode='payment',
        customer=customer_id,
        line_items=[{'price': price_id, 'quantity': 1}],
        metadata={
            'user_id': str(user.id),
            'pack_key': pack_key,
            'credits': str(int(tokens_to_credits(pack.get('credits', 0), precision=0) or 0)),
            'tokens': str(pack.get('credits', 0)),
            'checkout_type': 'credit_pack',
        },
        success_url=success_url,
        cancel_url=cancel_url,
        allow_promotion_codes=True,
    )

    return jsonify({'sessionId': session.id, 'url': session.url}), 200


@billing_bp.route('/create-credit-pack-checkout-session', methods=['POST'])
@jwt_required()
def create_credit_pack_checkout_session():
    """Create a one-time Checkout session for credit packs."""
    return _create_credit_pack_checkout_session()


@billing_bp.route('/create-overage-checkout-session', methods=['POST'])
@jwt_required()
def create_overage_checkout_session():
    """Backward-compatible alias for legacy clients."""
    return _create_credit_pack_checkout_session()


@billing_bp.route('/create-portal-session', methods=['POST'])
@jwt_required()
def create_portal_session():
    """Open Stripe customer portal for self-serve subscription management."""
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({'msg': 'User not found'}), 404

    if not user.stripe_customer_id:
        return jsonify({'msg': 'No Stripe customer found for this account'}), 400

    data = request.get_json(silent=True) or {}
    try:
        return_url = _validated_frontend_redirect(
            data.get('return_url'),
            fallback_path='/account',
        )
    except ValueError as exc:
        return jsonify({'msg': str(exc)}), 400

    session = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=return_url,
    )

    return jsonify({'url': session.url}), 200


@billing_bp.route('/checkout-session', methods=['GET'])
def get_checkout_session():
    """Fetch checkout session details for success page rendering."""
    session_id = request.args.get('session_id')
    if not session_id:
        return jsonify({'msg': 'Missing session_id'}), 400

    try:
        sess = stripe.checkout.Session.retrieve(session_id, expand=['subscription'])
        return jsonify(sess.to_dict()), 200
    except stripe.error.StripeError as e:
        return jsonify({'msg': str(e)}), 400


@billing_bp.route('/webhook', methods=['POST'])
def stripe_webhook():
    """Receive Stripe events and keep user subscription and thinking power in sync."""
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')
    webhook_secret = current_app.config.get('STRIPE_WEBHOOK_SECRET') or os.getenv('STRIPE_WEBHOOK_SECRET')

    if not webhook_secret:
        current_app.logger.error("STRIPE_WEBHOOK_SECRET not configured")
        return jsonify({"error": "Webhook not configured"}), 503

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except (ValueError, stripe.error.SignatureVerificationError):
        return abort(400)
    event_id = str(event.get('id') or '').strip()
    event_type = str(event.get('type') or '').strip()
    if not event_id:
        return abort(400)

    existing_event = StripeWebhookEvent.query.filter_by(stripe_event_id=event_id).first()
    if existing_event and bool(existing_event.processed):
        return '', 200
    event_row = existing_event
    if event_row is None:
        event_row = StripeWebhookEvent(
            stripe_event_id=event_id,
            event_type=event_type,
            processed=False,
        )
        db.session.add(event_row)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            existing_event = StripeWebhookEvent.query.filter_by(stripe_event_id=event_id).first()
            if existing_event and bool(existing_event.processed):
                return '', 200
            event_row = existing_event
            if event_row is None:
                event_row = StripeWebhookEvent(
                    stripe_event_id=event_id,
                    event_type=event_type,
                    processed=False,
                )
                db.session.add(event_row)
                db.session.flush()

    if event_type == 'checkout.session.completed':
        sess = event['data']['object']
        metadata = sess.get('metadata') or {}
        user_id = metadata.get('user_id')
        user = User.query.get(user_id) if user_id else None

        if not user_id:
            current_app.logger.warning(
                "checkout.session.completed event %s has no user_id in metadata — skipping credit reset",
                event_id,
            )
        elif not user:
            current_app.logger.error(
                "checkout.session.completed event %s: user_id=%s not found in DB — skipping credit reset",
                event_id,
                user_id,
            )

        if user:
            checkout_type = metadata.get('checkout_type')
            if checkout_type in {'credit_pack', 'overage_pack'}:
                # Claimed against the PaymentIntent, so the payment_intent.succeeded
                # delivery of this same purchase cannot add the tokens again.
                result = _fulfill_credit_pack_checkout_session(sess)
                if not result.get('granted'):
                    current_app.logger.info(
                        "checkout.session.completed: no credit-pack grant for user=%s (%s)",
                        user_id, result.get('reason'),
                    )
            elif checkout_type == LIMITED_TIME_300K_CHECKOUT_TYPE:
                tokens = int(metadata.get('tokens') or 0)
                _entitlement, _grant, created = grant_limited_time_300k_offer(
                    user,
                    tokens,
                    payment_reference=sess.get('payment_intent') or sess.get('id'),
                    checkout_id=sess.get('id'),
                    metadata={
                        'campaign_id': metadata.get('campaign_id'),
                        'stripe_payment_intent_id': sess.get('payment_intent'),
                    },
                )
                if sess.get('customer'):
                    user.stripe_customer_id = sess.get('customer')
                get_usage_meter_state(user, current_app.config)
                current_app.logger.info(
                    "checkout.session.completed: 300K Limited-Time grant created=%s amount=%s user=%s",
                    created, tokens, user_id,
                )
            else:
                plan_key = normalize_plan_key(metadata.get('plan_key'))
                apply_plan_to_user(user, plan_key, current_app.config, reset_credits=True)
                user.stripe_customer_id = sess.get('customer')
                user.stripe_subscription_id = sess.get('subscription')
                user.subscription_status = 'active'
                current_app.logger.info(
                    "checkout.session.completed: applied plan=%s and reset credits for user=%s (credits_remaining=%s, credits_reset_at=%s)",
                    plan_key, user_id, user.credits_remaining, user.credits_reset_at,
                )

    elif event_type == 'payment_intent.succeeded':
        intent = event['data']['object']
        _fulfill_credit_pack_payment_intent(intent)
        _fulfill_limited_time_300k_payment_intent(intent)

    elif event_type == 'invoice.paid':
        # One-time 300K purchases settle as invoices (so Stripe records the
        # promotion-code redemption); subscription invoices keep using
        # invoice.payment_succeeded below.
        _fulfill_limited_time_300k_invoice(event['data']['object'])

    elif event_type == 'invoice.payment_succeeded':
        inv = event['data']['object']
        _fulfill_limited_time_300k_invoice(inv)
        user = _find_user_for_billing_event(
            subscription_id=inv.get('subscription'),
            customer_id=inv.get('customer'),
        )
        if not user:
            current_app.logger.warning(
                "invoice.payment_succeeded event %s: could not resolve user for subscription=%s customer=%s",
                event_id, inv.get('subscription'), inv.get('customer'),
            )
        if user:
            subscription_id = inv.get('subscription')
            sub = None
            if subscription_id:
                try:
                    sub = stripe.Subscription.retrieve(subscription_id)
                except stripe.error.StripeError as exc:
                    current_app.logger.warning(
                        "invoice.payment_succeeded: could not retrieve subscription %s: %s",
                        subscription_id, exc,
                    )

            meta = (sub.get('metadata') or {}) if sub is not None else {}
            # Deferred downgrade scheduled at a prior cycle.
            raw_scheduled = str(meta.get('scheduled_plan_change') or '').strip()
            scheduled_plan_key = normalize_plan_key(raw_scheduled) if raw_scheduled else None
            # Plan this subscription should grant — from our metadata (set by both the
            # embedded and hosted flows) or, failing that, reverse-mapped from the price.
            sub_plan_key = None
            if sub is not None:
                pk = str(meta.get('plan_key') or '').strip()
                sub_plan_key = normalize_plan_key(pk) if pk else None
                if not sub_plan_key or sub_plan_key == 'free':
                    items = (sub.get('items') or {}).get('data') or []
                    price_id = (items[0].get('price') or {}).get('id') if items else None
                    sub_plan_key = _plan_key_for_price_id(price_id, current_app.config)

            if scheduled_plan_key:
                # Deferred downgrade takes effect now (also resets credits for the new plan).
                apply_plan_to_user(user, scheduled_plan_key, current_app.config, reset_credits=True)
                user.stripe_subscription_id = subscription_id
                try:
                    stripe.Subscription.modify(subscription_id, metadata={'scheduled_plan_change': ''})
                except stripe.error.StripeError as exc:
                    current_app.logger.warning(
                        "invoice.payment_succeeded: could not clear scheduled_plan_change for sub %s: %s",
                        subscription_id, exc,
                    )
                current_app.logger.info(
                    "invoice.payment_succeeded: applied deferred downgrade to plan=%s for user=%s",
                    scheduled_plan_key, user.id,
                )
            elif sub_plan_key and sub_plan_key != 'free':
                # ACTIVATE / re-affirm the subscription's plan. This is how the EMBEDDED
                # subscribe flow grants the plan (it never fires checkout.session.completed)
                # and it persists the subscription id so later cancel/update events resolve
                # the user. On a normal renewal the plan already matches — harmless.
                apply_plan_to_user(user, sub_plan_key, current_app.config, reset_credits=True)
                user.stripe_subscription_id = subscription_id
                current_app.logger.info(
                    "invoice.payment_succeeded: applied plan=%s for user=%s (sub=%s)",
                    sub_plan_key, user.id, subscription_id,
                )
            else:
                # Couldn't resolve a paid plan — treat as a renewal (reset credits only).
                reset_user_monthly_credits(user, current_app.config, force=True)
                current_app.logger.info(
                    "invoice.payment_succeeded: reset credits for user=%s (no plan resolved)", user.id,
                )

            user.subscription_status = 'active'

    elif event_type == 'invoice.payment_failed':
        inv = event['data']['object']
        user = _find_user_for_billing_event(
            subscription_id=inv.get('subscription'),
            customer_id=inv.get('customer'),
        )
        if user:
            user.subscription_status = 'past_due'
            # Cap credits to the free-plan limit so a past-due user cannot
            # continue burning premium capacity while payment is unresolved.
            # When payment succeeds the monthly reset restores their full
            # plan allotment (invoice.payment_succeeded handler above).
            free_limit = get_monthly_credit_limit('free', current_app.config)
            if free_limit is not None and user.credits_remaining is not None:
                before_cap = int(user.credits_remaining)
                after_cap = cap_monthly_credits(user, free_limit, current_app.config)
                if after_cap != before_cap:
                    current_app.logger.info(
                        "Capped monthly credits to free limit (%s) for past-due user=%s; durable credits preserved",
                        free_limit, user.id,
                    )
            current_app.logger.warning(
                "Stripe payment failed for user=%s subscription=%s",
                user.id,
                inv.get('subscription'),
            )

    elif event_type == 'customer.subscription.deleted':
        sub = event['data']['object']
        user = User.query.filter_by(stripe_subscription_id=sub.get('id')).first()
        if user:
            apply_plan_to_user(user, 'free', current_app.config, reset_credits=True)
            user.stripe_subscription_id = None
            user.subscription_status = 'canceled'

    elif event_type == 'customer.subscription.updated':
        sub = event['data']['object']
        user = User.query.filter_by(stripe_subscription_id=sub.get('id')).first()
        if user:
            status = str(sub.get('status') or '').strip().lower()
            if status:
                user.subscription_status = status
            if status in {'canceled', 'incomplete_expired', 'unpaid'}:
                apply_plan_to_user(user, 'free', current_app.config, reset_credits=True)
                user.stripe_subscription_id = None

    elif event_type == 'customer.subscription.paused':
        sub = event['data']['object']
        user = User.query.filter_by(stripe_subscription_id=sub.get('id')).first()
        if user:
            apply_plan_to_user(user, 'free', current_app.config, reset_credits=True)
            user.stripe_subscription_id = None
            user.subscription_status = 'paused'

    elif event_type == 'charge.refunded':
        charge = event['data']['object']
        user = _find_user_for_billing_event(customer_id=charge.get('customer'))
        metadata = charge.get('metadata') if isinstance(charge.get('metadata'), dict) else {}
        if user and str(metadata.get('checkout_type') or '').strip() in {'credit_pack', 'overage_pack'}:
            refund_credits = int(metadata.get('tokens') or metadata.get('credits') or 0)
            if refund_credits > 0 and user.credits_remaining is not None:
                user.credits_remaining = max(0, int(user.credits_remaining or 0) - refund_credits)
            elif refund_credits > 0 and user.credits_remaining is None:
                consume_credits(user, refund_credits)
        limited_time_300k_charge = _is_limited_time_300k_charge(user, charge)
        if user and limited_time_300k_charge:
            reverse_limited_time_300k_credits(
                user,
                reason='stripe_refund',
                external_reference=event_id,
            )
            get_usage_meter_state(user, current_app.config)

    elif event_type == 'charge.dispute.created':
        charge = event['data']['object']
        user = _find_user_for_billing_event(customer_id=charge.get('customer'))
        limited_time_300k_charge = _is_limited_time_300k_charge(user, charge)
        if user and limited_time_300k_charge:
            reverse_limited_time_300k_credits(
                user,
                reason='stripe_chargeback',
                external_reference=event_id,
            )
            get_usage_meter_state(user, current_app.config)

    event_row.event_type = event_type
    event_row.processed = True
    event_row.processed_at = datetime.utcnow()
    db.session.commit()
    return '', 200


@billing_bp.route('/cancel-subscription', methods=['POST'])
@jwt_required()
def cancel_subscription():
    """Cancel the logged-in user's active subscription at period end."""
    user = User.query.get(get_jwt_identity())
    if not user or not user.stripe_subscription_id:
        return jsonify({'msg': 'No active subscription'}), 400

    try:
        sub = stripe.Subscription.modify(user.stripe_subscription_id, cancel_at_period_end=True)
        current_period_end = sub.get('current_period_end')
        return jsonify({
            'msg': 'Will cancel at period end',
            'current_period_end': current_period_end,
            'current_period_end_iso': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(current_period_end)) if current_period_end else None,
        }), 200
    except stripe.error.StripeError as e:
        return jsonify({'msg': str(e)}), 400


@billing_bp.route('/resume-subscription', methods=['POST'])
@jwt_required()
def resume_subscription():
    """Undo a pending cancellation — keep the subscription running.

    Clears ``cancel_at_period_end`` on the Stripe subscription so the plan
    renews normally at the next billing date instead of lapsing to free.
    """
    user = User.query.get(get_jwt_identity())
    if not user or not user.stripe_subscription_id:
        return jsonify({'msg': 'No active subscription'}), 400

    try:
        sub = stripe.Subscription.modify(user.stripe_subscription_id, cancel_at_period_end=False)
        return jsonify({
            'success': True,
            'msg': 'Your subscription will continue.',
            'cancel_at_period_end': bool(sub.get('cancel_at_period_end')),
            'subscription_status': str(sub.get('status') or '').strip().lower() or user.subscription_status,
        }), 200
    except stripe.error.StripeError as e:
        return jsonify({'success': False, 'msg': str(e)}), 400


@billing_bp.route('/clear-scheduled-change', methods=['POST'])
@jwt_required()
def clear_scheduled_change():
    """Undo a pending downgrade — keep the current (higher) plan.

    Reverts the Stripe subscription item price back to the user's current
    plan and clears the ``scheduled_plan_change`` metadata so the queued
    downgrade does not apply at the next invoice.
    """
    user = User.query.get(get_jwt_identity())
    if not user or not user.stripe_subscription_id:
        return jsonify({'msg': 'No active subscription'}), 400

    current_plan = to_public_plan(user.subscription_plan)
    price_id = current_app.config.get('STRIPE_PRICE_IDS', {}).get(current_plan)
    if not price_id:
        return jsonify({'msg': f"No Stripe price configured for '{current_plan}'"}), 400

    try:
        subscription = stripe.Subscription.retrieve(user.stripe_subscription_id)
        items = (subscription.get('items') or {}).get('data') or []
        if not items:
            return jsonify({'msg': 'Subscription has no modifiable items'}), 400
        item_id = items[0].get('id')
        # Restore the current plan's price (in case a downgrade price was set)
        # and clear the scheduled change so nothing applies next cycle.
        sub = stripe.Subscription.modify(
            user.stripe_subscription_id,
            items=[{'id': item_id, 'price': price_id}],
            proration_behavior='none',
            metadata={'scheduled_plan_change': ''},
        )
        return jsonify({
            'success': True,
            'msg': 'Your current plan will continue — the scheduled change was cancelled.',
            'plan_key': current_plan,
            'subscription_status': str(sub.get('status') or '').strip().lower() or user.subscription_status,
        }), 200
    except stripe.error.StripeError as e:
        return jsonify({'success': False, 'msg': str(e)}), 400
