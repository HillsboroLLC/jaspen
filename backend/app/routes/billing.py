import os
import time
from urllib.parse import urlparse
from flask import Blueprint, request, jsonify, current_app, abort
from flask_jwt_extended import jwt_required, get_jwt_identity
import stripe

from app import db
from app.admin_policy import is_global_admin
from app.models import User
from app.billing_config import (
    apply_plan_to_user,
    add_credits,
    bootstrap_legacy_credits,
    get_allowed_model_types,
    get_default_model_type,
    get_model_catalog,
    get_monthly_credit_limit,
    get_overage_packs,
    get_plan_catalog,
    is_sales_only_plan,
    normalize_plan_key,
    reset_user_monthly_credits,
    to_public_plan,
)
from app.connector_store import get_all_connector_settings
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


def _allowed_frontend_origins():
    origins = set()
    frontend_base = current_app.config.get('FRONTEND_BASE_URL') or 'http://localhost:3000'
    frontend_origin = _normalized_origin(frontend_base)
    if frontend_origin:
        origins.add(frontend_origin)

    raw = (
        current_app.config.get('BILLING_REDIRECT_ALLOWED_ORIGINS')
        or os.getenv('BILLING_REDIRECT_ALLOWED_ORIGINS')
        or ''
    )
    for item in str(raw).split(','):
        origin = _normalized_origin(item)
        if origin:
            origins.add(origin)
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


@billing_bp.route('/plans', methods=['GET'])
def list_plans():
    """Legacy response: plan_key -> Stripe Price ID."""
    return jsonify(current_app.config.get('STRIPE_PRICE_IDS', {})), 200


@billing_bp.route('/catalog', methods=['GET'])
def get_billing_catalog():
    plan_catalog = get_plan_catalog(current_app.config)
    pack_catalog = get_overage_packs(current_app.config)
    model_catalog = get_model_catalog(current_app.config)

    return jsonify({
        'plans': plan_catalog,
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
        # Global Jaspen admins should always have enterprise internal access.
        if to_public_plan(user.subscription_plan) != 'enterprise' or user.credits_remaining is not None:
            apply_plan_to_user(user, 'enterprise', current_app.config, reset_credits=True)
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
    plan_catalog = get_plan_catalog(current_app.config)
    current_plan = plan_catalog.get(plan_key) or {}
    monthly_limit = get_monthly_credit_limit(plan_key, current_app.config)
    credits_remaining = user.credits_remaining
    credits_used = 0 if admin_override else None
    if not admin_override and monthly_limit is not None and credits_remaining is not None:
        credits_used = max(0, int(monthly_limit) - int(credits_remaining))
    allowed_model_types = get_allowed_model_types(plan_key, current_app.config)
    default_model_type = get_default_model_type(plan_key, current_app.config)
    tool_entitlements = get_tool_entitlements(plan_key)
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

    return jsonify({
        'plan_key': plan_key,
        'plan': current_plan,
        'is_admin': admin_override,
        'credits_remaining': credits_remaining,
        'monthly_credit_limit': monthly_limit,
        'credits_used': credits_used,
        'allowed_model_types': allowed_model_types,
        'default_model_type': default_model_type,
        'context_budget': get_context_budget(plan_key),
        'tool_entitlements': tool_entitlements,
        'stripe_customer_id': user.stripe_customer_id,
        'stripe_subscription_id': user.stripe_subscription_id,
    }), 200


@billing_bp.route('/create-payment-intent', methods=['POST'])
def create_payment_intent():
    """Legacy one-off PaymentIntent flow (amount in cents)."""
    data = request.get_json() or {}
    amount = int(data.get('amount', 0))
    intent = stripe.PaymentIntent.create(
        amount=amount,
        currency='usd',
    )
    return jsonify({'client_secret': intent.client_secret}), 200


@billing_bp.route('/create-checkout-session', methods=['POST'])
@jwt_required()
def create_checkout_session():
    """Create a self-serve subscription Checkout session (Free/Essential)."""
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({'msg': 'User not found'}), 404

    data = request.get_json() or {}
    raw_plan_key = data.get('plan_key') or data.get('plan')
    plan_key = normalize_plan_key(raw_plan_key)
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

    price_id = current_app.config.get('STRIPE_PRICE_IDS', {}).get(plan_key)
    if not price_id:
        return jsonify({'msg': f"No Stripe price configured for '{plan_key}'"}), 400

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
            'checkout_type': 'subscription',
        },
        success_url=success_url,
        cancel_url=cancel_url,
        allow_promotion_codes=True,
    )
    return jsonify({'sessionId': session.id, 'url': session.url}), 200


@billing_bp.route('/create-overage-checkout-session', methods=['POST'])
@jwt_required()
def create_overage_checkout_session():
    """Create a one-time Checkout session for overage credit packs."""
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({'msg': 'User not found'}), 404

    data = request.get_json() or {}
    pack_key = str(data.get('pack_key') or '').strip()
    if not pack_key:
        return jsonify({'msg': 'Missing pack_key'}), 400

    packs = get_overage_packs(current_app.config)
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
            'credits': str(pack.get('credits', 0)),
            'checkout_type': 'overage_pack',
        },
        success_url=success_url,
        cancel_url=cancel_url,
        allow_promotion_codes=True,
    )

    return jsonify({'sessionId': session.id, 'url': session.url}), 200


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
    """Receive Stripe events and keep user subscription/credits in sync."""
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

    if event.get('type') == 'checkout.session.completed':
        sess = event['data']['object']
        metadata = sess.get('metadata') or {}
        user_id = metadata.get('user_id')
        user = User.query.get(user_id) if user_id else None

        if user:
            checkout_type = metadata.get('checkout_type')
            if checkout_type == 'overage_pack':
                add_credits(user, int(metadata.get('credits') or 0))
                if sess.get('customer'):
                    user.stripe_customer_id = sess.get('customer')
                db.session.commit()
            else:
                plan_key = normalize_plan_key(metadata.get('plan_key'))
                apply_plan_to_user(user, plan_key, current_app.config, reset_credits=True)
                user.stripe_customer_id = sess.get('customer')
                user.stripe_subscription_id = sess.get('subscription')
                db.session.commit()

    elif event.get('type') == 'invoice.payment_succeeded':
        inv = event['data']['object']
        subscription_id = inv.get('subscription')
        customer_id = inv.get('customer')

        user = None
        if subscription_id:
            user = User.query.filter_by(stripe_subscription_id=subscription_id).first()
        if not user and customer_id:
            user = User.query.filter_by(stripe_customer_id=customer_id).first()

        if user:
            if reset_user_monthly_credits(user, current_app.config, force=True):
                db.session.commit()

    elif event.get('type') == 'customer.subscription.deleted':
        sub = event['data']['object']
        user = User.query.filter_by(stripe_subscription_id=sub.get('id')).first()
        if user:
            apply_plan_to_user(user, 'free', current_app.config, reset_credits=True)
            user.stripe_subscription_id = None
            db.session.commit()

    elif event.get('type') == 'customer.subscription.updated':
        sub = event['data']['object']
        user = User.query.filter_by(stripe_subscription_id=sub.get('id')).first()
        if user and sub.get('status') in {'canceled', 'incomplete_expired', 'unpaid'}:
            apply_plan_to_user(user, 'free', current_app.config, reset_credits=True)
            user.stripe_subscription_id = None
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
