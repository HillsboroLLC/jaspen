from flask import Blueprint, request, jsonify, current_app
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import (
    create_access_token,
    jwt_required,
    get_jwt_identity,
    decode_token,
    set_access_cookies,
    unset_jwt_cookies,
)
import stripe

from app import db
from app.models import User
from app.billing_config import (
    apply_plan_to_user,
    bootstrap_legacy_credits,
    is_sales_only_plan,
    normalize_plan_key,
    to_public_plan,
)


auth_bp = Blueprint('auth', __name__)


@auth_bp.before_app_request
def _set_stripe_key():
    stripe.api_key = current_app.config['STRIPE_SECRET_KEY']


def _attach_auth_cookie(resp, token):
    # New primary auth cookie name is configured in app config (jaspen_access).
    set_access_cookies(resp, token)
    return resp


@auth_bp.route('/signup', methods=['POST'])
def signup():
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    requested_plan = normalize_plan_key(data.get('plan_key', 'free'))

    if not name or not email or not password:
        return jsonify(message='Name, email and password are all required'), 400
    if User.query.filter_by(email=email).first():
        return jsonify(message='Email already registered'), 409

    if is_sales_only_plan(requested_plan, current_app.config):
        return jsonify(
            message='Team and Enterprise are sales-led right now. Please contact sales to get started.',
            contact_sales=True,
            plan_key=requested_plan,
        ), 400

    user = User(
        name=name,
        email=email,
        password_hash=generate_password_hash(password),
        seat_limit=1,
        max_seats=1,
    )
    apply_plan_to_user(user, requested_plan, current_app.config, reset_credits=True)
    db.session.add(user)
    db.session.commit()

    access_token = create_access_token(identity=str(user.id))

    # Free plan can complete sign-up with no payment flow.
    if requested_plan == 'free':
        resp = jsonify(
            message='User created',
            token=access_token,
            user={
                'id': user.id,
                'email': user.email,
                'name': user.name,
                'subscription_plan': to_public_plan(user.subscription_plan),
                'credits_remaining': user.credits_remaining,
            },
        )
        resp.status_code = 201
        return _attach_auth_cookie(resp, access_token)

    # Essential goes through Stripe checkout.
    price_id = (current_app.config.get('STRIPE_PRICE_IDS') or {}).get(requested_plan)
    if not price_id:
        return jsonify(message=f"No Stripe price configured for plan '{requested_plan}'"), 500

    frontend = (current_app.config.get('FRONTEND_BASE_URL') or 'http://localhost:3000').rstrip('/')

    customer = stripe.Customer.create(
        email=user.email,
        name=user.name,
        metadata={'user_id': str(user.id)},
    )
    user.stripe_customer_id = customer.id
    db.session.commit()

    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        mode='subscription',
        customer=customer.id,
        line_items=[{'price': price_id, 'quantity': 1}],
        metadata={'user_id': str(user.id), 'plan_key': requested_plan, 'checkout_type': 'subscription'},
        success_url=f"{frontend}/pricing?session_id={{CHECKOUT_SESSION_ID}}&status=success",
        cancel_url=f"{frontend}/pricing?status=cancel",
    )

    resp = jsonify(
        message='User created; complete payment',
        token=access_token,
        checkout_session_id=session.id,
        checkout_url=session.url,
        user={
            'id': user.id,
            'email': user.email,
            'name': user.name,
            'subscription_plan': to_public_plan(user.subscription_plan),
            'credits_remaining': user.credits_remaining,
        },
    )
    resp.status_code = 201
    return _attach_auth_cookie(resp, access_token)


@auth_bp.route('/register', methods=['POST'])
def register_alias():
    """Legacy alias used by some frontend clients."""
    return signup()


@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not email or not password:
        return jsonify(message='Email and password required'), 400

    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify(message='Invalid credentials'), 401

    if bootstrap_legacy_credits(user, current_app.config):
        db.session.commit()

    token = create_access_token(identity=str(user.id))
    resp = jsonify(
        token=token,
        user={
            'id': user.id,
            'email': user.email,
            'name': user.name,
            'subscription_plan': to_public_plan(user.subscription_plan),
            'credits_remaining': user.credits_remaining,
        },
    )
    resp.status_code = 200
    return _attach_auth_cookie(resp, token)


@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def get_current_user():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return jsonify(error='User not found'), 404

    if bootstrap_legacy_credits(user, current_app.config):
        db.session.commit()

    return jsonify(
        id=user.id,
        email=user.email,
        name=user.name,
        subscription_plan=to_public_plan(user.subscription_plan),
        credits_remaining=user.credits_remaining,
    ), 200


@auth_bp.route('/logout', methods=['POST'])
def logout():
    """Clear auth cookies while staying backward-compatible with token clients."""
    resp = jsonify(message='Logged out')
    unset_jwt_cookies(resp)
    # Clear legacy cookie key used during Sekki era.
    resp.set_cookie(
        'sekki_access',
        '',
        max_age=0,
        expires=0,
        path='/',
        secure=bool(current_app.config.get('JWT_COOKIE_SECURE')),
        samesite=current_app.config.get('JWT_COOKIE_SAMESITE', 'Lax'),
        domain=current_app.config.get('JWT_COOKIE_DOMAIN'),
    )
    return resp, 200


@auth_bp.route('/me-cookie', methods=['GET'])
def get_current_user_from_cookie():
    token = request.cookies.get('jaspen_access') or request.cookies.get('sekki_access')
    if not token:
        return jsonify(error='Missing auth cookie'), 401

    try:
        decoded = decode_token(token)
        user_id = decoded.get('sub')
        if not user_id:
            return jsonify(error='Invalid token'), 401
    except Exception:
        return jsonify(error='Invalid token'), 401

    user = User.query.get(user_id)
    if not user:
        return jsonify(error='User not found'), 404

    if bootstrap_legacy_credits(user, current_app.config):
        db.session.commit()

    return jsonify(
        id=user.id,
        email=user.email,
        name=user.name,
        subscription_plan=to_public_plan(user.subscription_plan),
        credits_remaining=user.credits_remaining,
    ), 200
