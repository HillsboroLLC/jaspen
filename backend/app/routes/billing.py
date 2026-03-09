import time
from flask import Blueprint, request, jsonify, current_app, abort
from flask_jwt_extended import jwt_required, get_jwt_identity
import stripe

from app import db
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
    to_public_plan,
)
from app.tool_registry import get_context_budget, get_tool_entitlements

billing_bp = Blueprint('billing', __name__)


@billing_bp.before_app_request
def _set_stripe_key():
    stripe.api_key = current_app.config['STRIPE_SECRET_KEY']


def _frontend_url(path='/pages/pricing'):
    base = (current_app.config.get('FRONTEND_BASE_URL') or 'http://localhost:3000').rstrip('/')
    return f"{base}{path}"


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

    plan_key = to_public_plan(user.subscription_plan)
    plan_catalog = get_plan_catalog(current_app.config)
    current_plan = plan_catalog.get(plan_key) or {}
    monthly_limit = get_monthly_credit_limit(plan_key, current_app.config)
    credits_used = None
    if monthly_limit is not None and user.credits_remaining is not None:
        credits_used = max(0, int(monthly_limit) - int(user.credits_remaining))
    allowed_model_types = get_allowed_model_types(plan_key, current_app.config)
    default_model_type = get_default_model_type(plan_key, current_app.config)

    return jsonify({
        'plan_key': plan_key,
        'plan': current_plan,
        'credits_remaining': user.credits_remaining,
        'monthly_credit_limit': monthly_limit,
        'credits_used': credits_used,
        'allowed_model_types': allowed_model_types,
        'default_model_type': default_model_type,
        'context_budget': get_context_budget(plan_key),
        'tool_entitlements': get_tool_entitlements(plan_key),
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

    success_url = data.get('success_url') or _frontend_url('/pricing?session_id={CHECKOUT_SESSION_ID}&status=success')
    cancel_url = data.get('cancel_url') or _frontend_url('/pricing?status=cancel')

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

    success_url = data.get('success_url') or _frontend_url('/pricing?status=success')
    cancel_url = data.get('cancel_url') or _frontend_url('/pricing?status=cancel')

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
    return_url = data.get('return_url') or _frontend_url('/account')

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
    secret = current_app.config.get('STRIPE_WEBHOOK_SECRET')

    try:
        if secret:
            event = stripe.Webhook.construct_event(payload, sig_header, secret)
        else:
            event = request.get_json(force=True)
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
            monthly_limit = get_monthly_credit_limit(user.subscription_plan, current_app.config)
            if monthly_limit is not None:
                user.credits_remaining = monthly_limit
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
