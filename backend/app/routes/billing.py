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
from app.models import StripeWebhookEvent, User
from app.billing_config import (
    apply_plan_to_user,
    add_credits,
    bootstrap_legacy_credits,
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
    """Reverse-map a Stripe price id -> our plan_key (STRIPE_PRICE_IDS is plan->price)."""
    if not price_id:
        return None
    mapping = app_config.get('STRIPE_PRICE_IDS', {}) or {}
    for plan_key, pid in mapping.items():
        if pid == price_id:
            return normalize_plan_key(plan_key)
    return None


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
    usage_meta = _usage_warning_fields(cycle_limit, tokens_used)

    # Surface pending-state details from the live Stripe subscription so the UI
    # can show scheduled cancellations / downgrades and offer an undo. Best
    # effort only — never let a Stripe hiccup break the status endpoint.
    cancel_at_period_end = False
    current_period_end = None
    scheduled_plan_change = None
    if user.stripe_subscription_id:
        try:
            sub = stripe.Subscription.retrieve(user.stripe_subscription_id)
            cancel_at_period_end = bool(sub.get('cancel_at_period_end'))
            cpe = sub.get('current_period_end')
            if cpe:
                current_period_end = datetime.utcfromtimestamp(int(cpe)).isoformat()
            sub_meta = sub.get('metadata') or {}
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
        'access_restricted': (not admin_override) and (effective_plan_key(user, current_app.config) != plan_key),
        'effective_plan_key': plan_key if admin_override else effective_plan_key(user, current_app.config),
        'credits_remaining': credits_remaining,
        'monthly_credit_limit': tokens_to_credits(monthly_limit, precision=0),
        'credits_used': credits_used,
        'usage_scope': usage_state.get('scope'),
        'cycle_credit_limit': tokens_to_credits(cycle_limit, precision=0),
        'cycle_reset_at': usage_state.get('reset_at').isoformat() if usage_state.get('reset_at') else None,
        'purchased_credits_this_cycle': tokens_to_credits(usage_state.get('overage_tokens'), precision=0),
        # Backward-compatible alias for older clients.
        'overage_credits_this_cycle': tokens_to_credits(usage_state.get('overage_tokens'), precision=0),
        'credit_soft_stop_limit': tokens_to_credits(cycle_limit, precision=0),
        'credit_block_limit': tokens_to_credits(None if cycle_limit is None else int(math.floor(int(cycle_limit) * 1.05)), precision=0),
        'allowed_model_types': allowed_model_types,
        'default_model_type': default_model_type,
        'context_budget': get_context_budget(plan_key),
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


def _credit_pack_tokens_from_metadata(metadata):
    tokens = int(metadata.get('tokens') or 0)
    if tokens > 0:
        return tokens
    credits = int(metadata.get('credits') or 0)
    return credits * 1000 if credits > 0 else 0


def _fulfill_credit_pack_payment_intent(intent, expected_user=None):
    metadata = intent.get('metadata') or {}
    checkout_type = str(metadata.get('checkout_type') or '').strip()
    if checkout_type not in {'credit_pack', 'overage_pack'}:
        return {'granted': False, 'reason': 'not_credit_pack'}
    if intent.get('status') != 'succeeded':
        return {'granted': False, 'reason': intent.get('status') or 'not_succeeded'}

    payment_intent_id = intent.get('id')
    event_id = _credit_pack_payment_event_id(payment_intent_id)
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

    tokens = _credit_pack_tokens_from_metadata(metadata)
    if tokens <= 0:
        return {'granted': False, 'reason': 'missing_tokens'}

    add_credits(user, tokens)
    if intent.get('customer'):
        user.stripe_customer_id = intent.get('customer')
    event_row.processed = True
    event_row.processed_at = datetime.utcnow()
    current_app.logger.info(
        "payment_intent.succeeded: added %s credit-pack tokens for user=%s",
        tokens, user.id,
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

    price_id = current_app.config.get('STRIPE_PRICE_IDS', {}).get(plan_key)
    if not price_id:
        return jsonify({'msg': f"No Stripe price configured for '{plan_key}'."}), 400

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
        'publishable_key': current_app.config.get('STRIPE_PUBLISHABLE_KEY') or '',
    }), 200


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

    price_id = current_app.config.get('STRIPE_PRICE_IDS', {}).get(plan_key)
    if not price_id:
        return jsonify({'msg': f"No Stripe price configured for '{plan_key}'"}), 400

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
                metadata={'scheduled_plan_change': ''},
                expand=['latest_invoice'],
            )
        else:
            # Downgrade: schedule for next cycle, no immediate charge/credit.
            updated = stripe.Subscription.modify(
                user.stripe_subscription_id,
                items=[{'id': item_id, 'price': price_id}],
                proration_behavior='none',
                metadata={'scheduled_plan_change': plan_key},
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
                tokens = int(metadata.get('tokens') or metadata.get('credits') or 0)
                add_credits(user, tokens)
                if sess.get('customer'):
                    user.stripe_customer_id = sess.get('customer')
                current_app.logger.info(
                    "checkout.session.completed: added %s credit-pack tokens for user=%s",
                    tokens, user_id,
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

    elif event_type == 'invoice.payment_succeeded':
        inv = event['data']['object']
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
                if user.credits_remaining > free_limit:
                    user.credits_remaining = free_limit
                    current_app.logger.info(
                        "Capped credits to free limit (%s) for past-due user=%s",
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
