"""app.routes.auth

Purpose
  Centralize authentication endpoints (signup/login/me) and Stripe Checkout
  session creation for paid plans.

Why this file exists
  Auth is a high-risk surface area. This module keeps auth behavior explicit
  and auditable, and it avoids spreading URL/config assumptions throughout
  the codebase.
"""

from __future__ import annotations

import os

from flask import Blueprint, request, jsonify, current_app
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from app import db
from app.models import User
import stripe

auth_bp = Blueprint('auth', __name__)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------
def _get_frontend_base_url() -> str:
    """Return the frontend base URL for redirects.

    Precedence:
      1) Flask config FRONTEND_BASE_URL
      2) Flask config FRONTEND_URL (back-compat)
      3) Environment variables FRONTEND_BASE_URL then FRONTEND_URL

    Normalization:
      - Trailing slashes are removed so URL joining is predictable.

    Notes
      - If no value is configured, we raise to preserve existing failure
        behavior (previously a KeyError -> 500) without changing response
        shapes or status codes.
    """
    value = (
        current_app.config.get("FRONTEND_BASE_URL")
        or current_app.config.get("FRONTEND_URL")
        or os.getenv("FRONTEND_BASE_URL")
        or os.getenv("FRONTEND_URL")
    )
    if not value:
        raise RuntimeError(
            "Missing FRONTEND_BASE_URL/FRONTEND_URL configuration for Stripe redirects"
        )
    return str(value).rstrip("/")


@auth_bp.before_app_request
def _set_stripe_key():
    stripe.api_key = current_app.config['STRIPE_SECRET_KEY']


# ---------------------------------------------------------------------------
# Routes: signup
# ---------------------------------------------------------------------------

@auth_bp.route('/signup', methods=['POST'])
def signup():
    data = request.get_json() or {}
    name        = data.get('name', '').strip()
    email       = data.get('email', '').strip().lower()
    password    = data.get('password', '')
    plan_key    = data.get('plan_key', 'essential')
    extra_seats = int(data.get('extra_seats', 0))

    # Basic validation
    if not name or not email or not password:
        return jsonify(message="Name, email and password are all required"), 400
    if User.query.filter_by(email=email).first():
        return jsonify(message="Email already registered"), 409

    # Create local user record
    user = User(
        name          = name,
        email         = email,
        password_hash = generate_password_hash(password),
        subscription_plan = plan_key,
        seat_limit    = 1 + extra_seats,
        max_seats     = 1 + extra_seats
    )
    db.session.add(user)
    db.session.commit()

    # Issue JWT
    access_token = create_access_token(identity=str(user.id))

    # If free plan, just return token/user
    if plan_key == 'essential':
        return jsonify(
            message="User created",
            token=access_token,
            user={ 'id':user.id, 'email':user.email, 'name':user.name }
        ), 201

    # Otherwise, create Stripe Checkout Session for the chosen plan
    price_ids = current_app.config.get('STRIPE_PRICE_IDS', {})
    price_id = price_ids.get(plan_key)
    if not price_id:
        return jsonify(message=f"Unknown or unconfigured plan_key '{plan_key}'"), 400

    frontend = _get_frontend_base_url()

    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        mode='subscription',
        line_items=[{ 'price': price_id, 'quantity': 1 }],
        metadata={ 'user_id': str(user.id), 'plan_key': plan_key },
        success_url=f"{frontend}/pricing?session_id={{CHECKOUT_SESSION_ID}}&status=success",
        cancel_url =f"{frontend}/pricing?status=cancel",
    )

    return jsonify(
        message="User created; complete payment",
        token=access_token,
        checkout_session_id=session.id,
        user={ 'id':user.id, 'email':user.email, 'name':user.name }
    ), 201


# ---------------------------------------------------------------------------
# Routes: login
# ---------------------------------------------------------------------------

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    email    = data.get('email','').strip().lower()
    password = data.get('password','')

    if not email or not password:
        return jsonify(message="Email and password required"), 400

    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify(message="Invalid credentials"), 401

    token = create_access_token(identity=str(user.id))
    resp = jsonify(token=token, user={ 'id':user.id,'email':user.email,'name':user.name })
    # why cookie: some clients omit Authorization header; cookie keeps session working across tabs
    resp.set_cookie('sekki_access', token, httponly=False, secure=True, samesite='None', path='/', domain='.sekki.io', max_age=28800)
    return resp, 200


# ---------------------------------------------------------------------------
# Routes: current user
# ---------------------------------------------------------------------------

@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def get_current_user():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return jsonify(error="User not found"), 404
    return jsonify(id=user.id, email=user.email, name=user.name), 200

