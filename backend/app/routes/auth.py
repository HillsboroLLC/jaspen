from urllib.parse import urlencode, urlparse, parse_qs
from datetime import datetime, timedelta, timezone
import base64
import io
import re
import secrets

import pyotp
import qrcode
import requests
from flask import Blueprint, request, jsonify, current_app, redirect
from flask_mail import Message
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import (
    create_access_token,
    jwt_required,
    get_jwt_identity,
    decode_token,
    set_access_cookies,
    unset_jwt_cookies,
)
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import stripe

from app import db, limiter, mail
from app.access_controls import (
    APPROVAL_APPROVED,
    APPROVAL_PENDING,
    APPROVAL_REJECTED,
    get_access_controls,
)
from app.admin_audit import append_user_audit_event
from app.admin_policy import is_global_admin
from app.models import Organization, User
from app.billing_config import (
    apply_plan_to_user,
    bootstrap_legacy_credits,
    is_sales_only_plan,
    normalize_plan_key,
    to_public_plan,
)
from app.connector_store import decrypt_token, encrypt_token
from app.orgs import (
    MFA_POLICY_REQUIRED,
    ensure_default_organization_for_user,
    mfa_policy_for_org,
    resolve_active_org_for_user,
    organization_access_payload_for_user,
)


auth_bp = Blueprint('auth', __name__)
GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_USERINFO_URL = 'https://openidconnect.googleapis.com/v1/userinfo'
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15


def _audit_auth_event(action, *, actor=None, target_user=None, target_email=None, details=None):
    append_user_audit_event(
        actor_user=actor or target_user,
        action=action,
        target_user_id=getattr(target_user, "id", None),
        target_email=(getattr(target_user, "email", None) or target_email),
        details=details if isinstance(details, dict) else {},
    )


def _validate_password(password):
    """Enforce password policy. Returns (is_valid, error_message)."""
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if len(password) > 128:
        return False, "Password must not exceed 128 characters."
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter."
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter."
    if not re.search(r'[0-9]', password):
        return False, "Password must contain at least one digit."
    return True, None


def _utc_now():
    return datetime.now(timezone.utc)


def _normalize_locked_until(value):
    if not value:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@auth_bp.before_app_request
def _set_stripe_key():
    stripe.api_key = current_app.config['STRIPE_SECRET_KEY']


def _attach_auth_cookie(resp, token):
    # New primary auth cookie name is configured in app config (jaspen_access).
    set_access_cookies(resp, token)
    return resp


def _create_user_access_token(user, *, expires_delta=None, additional_claims=None):
    claims = {'token_version': int(getattr(user, 'auth_token_version', 0) or 0)}
    if isinstance(additional_claims, dict):
        claims.update(additional_claims)
    return create_access_token(
        identity=str(user.id),
        expires_delta=expires_delta,
        additional_claims=claims,
    )


def _encrypt_mfa_secret(secret):
    return encrypt_token(secret) if secret else ""


def _decrypt_mfa_secret(value):
    return decrypt_token(value) if value else ""


def _verify_mfa_code(user, code):
    secret = _decrypt_mfa_secret(user.mfa_secret)
    if secret:
        totp = pyotp.TOTP(secret)
        if totp.verify(code, valid_window=1):
            return True
    if user.mfa_backup_codes:
        normalized_code = code.upper()
        for idx, hashed_code in enumerate(list(user.mfa_backup_codes)):
            if check_password_hash(hashed_code, normalized_code):
                remaining_codes = list(user.mfa_backup_codes)
                remaining_codes.pop(idx)
                user.mfa_backup_codes = remaining_codes
                db.session.commit()
                return True
    return False


def _has_mfa_secret(user):
    if not user:
        return False
    return bool(_decrypt_mfa_secret(user.mfa_secret))


def _frontend_base_url():
    return (current_app.config.get('FRONTEND_BASE_URL') or 'http://localhost:3000').rstrip('/')


def _safe_next_path(candidate):
    path = str(candidate or '').strip()
    if not path or not path.startswith('/') or path.startswith('//'):
        return '/new'
    return path


def _frontend_callback_url(next_path):
    return f"{_frontend_base_url()}/auth/callback?{urlencode({'next': _safe_next_path(next_path)})}"


def _frontend_login_error_url(reason):
    return f"{_frontend_base_url()}/?{urlencode({'auth': '1', 'error': reason})}"


def _google_state_serializer():
    secret = current_app.config.get('SECRET_KEY') or current_app.config.get('JWT_SECRET_KEY')
    if not secret:
        raise RuntimeError('Missing SECRET_KEY/JWT_SECRET_KEY for Google OAuth state signing')
    return URLSafeTimedSerializer(secret_key=secret, salt='google-oauth-state')


def _email_verification_serializer():
    secret = current_app.config.get('SECRET_KEY') or current_app.config.get('JWT_SECRET_KEY')
    if not secret:
        raise RuntimeError('Missing SECRET_KEY/JWT_SECRET_KEY for email verification signing')
    return URLSafeTimedSerializer(secret_key=secret, salt='email-verification')


def _password_reset_serializer():
    secret = current_app.config.get('SECRET_KEY') or current_app.config.get('JWT_SECRET_KEY')
    if not secret:
        raise RuntimeError('Missing SECRET_KEY/JWT_SECRET_KEY for password reset signing')
    return URLSafeTimedSerializer(secret_key=secret, salt='password-reset')


def _google_callback_url():
    configured = str(current_app.config.get('GOOGLE_REDIRECT_URI') or '').strip()
    if configured:
        return configured
    return f"{request.url_root.rstrip('/')}/api/v1/auth/google/callback"


def _verification_result_url(status):
    params = {'auth': '1'}
    if status == 'verified':
        params['verified'] = '1'
    else:
        params['error'] = status
    return f"{_frontend_base_url()}/?{urlencode(params)}"


def _email_verification_ttl_seconds():
    return int(current_app.config.get('EMAIL_VERIFICATION_TOKEN_TTL_SECONDS') or 86400)


def _password_reset_ttl_seconds():
    return int(current_app.config.get('PASSWORD_RESET_TOKEN_TTL_SECONDS') or 3600)


def _build_email_verification_token(user):
    return _email_verification_serializer().dumps({
        'user_id': str(user.id),
        'email': str(user.email or '').strip().lower(),
    })


def _email_verification_link(token):
    query = urlencode({'token': token})
    return f"{request.url_root.rstrip('/')}/api/v1/auth/verify-email?{query}"


def _build_password_reset_token(user):
    return _password_reset_serializer().dumps({
        'user_id': str(user.id),
        'email': str(user.email or '').strip().lower(),
        'reset_version': int(getattr(user, 'password_reset_version', 0) or 0),
    })


def _password_reset_link(token):
    return f"{_frontend_base_url()}/reset-password?{urlencode({'token': token})}"


def _normalize_referral_code(value):
    normalized = str(value or '').strip()
    if normalized and ('://' in normalized or normalized.startswith('jaspen.ai/')):
        raw_url = normalized if '://' in normalized else f'https://{normalized}'
        try:
            parsed = urlparse(raw_url)
            query = parse_qs(parsed.query or '')
            normalized = (
                query.get('ref', [None])[0]
                or query.get('referral_code', [None])[0]
                or query.get('invite', [None])[0]
                or query.get('invite_code', [None])[0]
                or normalized
            )
        except Exception:
            pass
    return normalized or None


def _resolve_referring_user(referral_code):
    normalized = _normalize_referral_code(referral_code)
    if not normalized:
        return None
    exact_match = User.query.filter_by(referral_code=normalized).first()
    if exact_match:
        return exact_match

    # Allow a shorter shareable invite code as long as it resolves unambiguously.
    if len(normalized) < 36:
        matches = User.query.filter(User.referral_code.like(f'{normalized}%')).limit(2).all()
        if len(matches) == 1:
            return matches[0]
    return None


def _verification_required_enabled():
    return bool(get_access_controls(current_app.config).get('require_email_verification'))


def _access_controls():
    return get_access_controls(current_app.config)


def _approval_pending_payload():
    return {
        'message': "You're on the list. We're reviewing access now.",
        'detail': "Jaspen is opening access carefully so each early user gets the right level of support. We’ll let you in as soon as your spot is confirmed.",
        'approval_required': True,
        'approval_status': APPROVAL_PENDING,
    }


def _approval_rejected_payload():
    return {
        'message': 'We couldn’t confirm access yet.',
        'approval_required': True,
        'approval_status': APPROVAL_REJECTED,
    }


def _deactivated_account_payload():
    return {
        'message': 'This account is currently unavailable.',
        'detail': 'If this looks wrong, contact Jaspen support and we can review the account history and restore access when appropriate.',
        'account_deactivated': True,
    }


def _signup_closed_payload():
    return {
        'message': 'Jaspen is opening access carefully right now. Use an invite code or request access to join the early list.',
        'signup_closed': True,
    }


def _invite_required_payload():
    return {
        'message': 'An invite code is required right now to get into Jaspen.',
        'invite_required': True,
    }


def _invite_invalid_payload():
    return {
        'message': 'That invite code could not be confirmed. Check the code and try again.',
        'invite_required': True,
        'invite_invalid': True,
    }


def _effective_signup_gate(referral_code):
    controls = _access_controls()
    normalized_referral = _normalize_referral_code(referral_code)
    referring_user = _resolve_referring_user(normalized_referral)
    has_valid_invite = referring_user is not None

    if controls.get('require_invite_code') and normalized_referral and not has_valid_invite:
        return controls, None, _invite_invalid_payload(), 403
    if controls.get('require_invite_code') and not has_valid_invite:
        return controls, None, _invite_required_payload(), 403
    if not controls.get('open_signup') and not has_valid_invite:
        return controls, None, _signup_closed_payload(), 403
    return controls, referring_user, None, None


def _mark_user_email_verified(user):
    if not user:
        return False
    changed = False
    if not bool(user.email_verified):
        user.email_verified = True
        changed = True
    if user.email_verified_at is None:
        user.email_verified_at = datetime.utcnow()
        changed = True
    return changed


def _send_email_verification_email(user):
    token = _build_email_verification_token(user)
    verification_link = _email_verification_link(token)
    msg = Message(
        subject='Verify your email for Jaspen',
        recipients=[user.email],
    )
    msg.body = (
        "You're almost in.\n\n"
        "Verify your email to finish setting up your Jaspen account:\n"
        f"{verification_link}\n\n"
        f"This link expires in {_email_verification_ttl_seconds() // 3600} hours.\n"
        "If you did not request this, you can ignore this email."
    )
    mail.send(msg)
    user.email_verification_sent_at = datetime.utcnow()


def _send_password_reset_email(user):
    token = _build_password_reset_token(user)
    reset_link = _password_reset_link(token)
    msg = Message(
        subject='Reset your Jaspen password',
        recipients=[user.email],
    )
    msg.body = (
        "We received a request to reset your Jaspen password.\n\n"
        "Use the link below to choose a new password:\n"
        f"{reset_link}\n\n"
        f"This link expires in {_password_reset_ttl_seconds() // 60} minutes.\n"
        "If you did not request this, you can ignore this email."
    )
    mail.send(msg)
    user.password_reset_requested_at = datetime.utcnow()


def _load_user_from_verification_token(token):
    decoded = _email_verification_serializer().loads(
        token,
        max_age=_email_verification_ttl_seconds(),
    )
    user_id = str(decoded.get('user_id') or '').strip()
    email = str(decoded.get('email') or '').strip().lower()
    if not user_id or not email:
        raise BadSignature('Invalid verification payload')
    user = User.query.get(user_id)
    if not user or str(user.email or '').strip().lower() != email:
        raise BadSignature('Invalid verification target')
    return user


def _load_user_from_password_reset_token(token):
    decoded = _password_reset_serializer().loads(
        token,
        max_age=_password_reset_ttl_seconds(),
    )
    user_id = str(decoded.get('user_id') or '').strip()
    email = str(decoded.get('email') or '').strip().lower()
    reset_version = int(decoded.get('reset_version') or 0)
    if not user_id or not email:
        raise BadSignature('Invalid reset payload')
    user = User.query.get(user_id)
    if not user or user.deactivated_at is not None:
        raise BadSignature('Invalid reset target')
    if str(user.email or '').strip().lower() != email:
        raise BadSignature('Invalid reset target')
    if int(getattr(user, 'password_reset_version', 0) or 0) != reset_version:
        raise BadSignature('Reset token has been superseded')
    return user


def _enforce_admin_account_profile(user):
    """
    Ensure internal global-admin accounts always have full internal access.
    This is global Jaspen admin only (allowlist), not future org-admin logic.
    """
    if not user or not is_global_admin(user, app_config=current_app.config):
        return False

    changed = False
    if to_public_plan(user.subscription_plan) != 'enterprise' or user.credits_remaining is not None:
        apply_plan_to_user(user, 'enterprise', current_app.config, reset_credits=True)
        changed = True
    if not bool(user.unlimited_analysis):
        user.unlimited_analysis = True
        changed = True
    if user.max_concurrent_sessions is not None:
        user.max_concurrent_sessions = None
        changed = True
    return changed


def _ensure_user_org(user):
    _, _, changed = ensure_default_organization_for_user(user)
    return changed


def _user_payload(user):
    return {
        'id': user.id,
        'email': user.email,
        'name': user.name,
        'is_admin': is_global_admin(user, app_config=current_app.config),
        'subscription_plan': to_public_plan(user.subscription_plan),
        'credits_remaining': user.credits_remaining,
        'email_verified': bool(user.email_verified),
        'email_verified_at': user.email_verified_at.isoformat() if user.email_verified_at else None,
        'access_approval_status': str(user.access_approval_status or APPROVAL_APPROVED),
        'access_approved_at': user.access_approved_at.isoformat() if user.access_approved_at else None,
        'mfa_enabled': bool(user.mfa_enabled),
        'referral_code': user.referral_code,
        'referrals_earned': user.referrals_earned,
        'active_organization_id': user.active_organization_id,
        **organization_access_payload_for_user(user),
    }


@auth_bp.route('/signup', methods=['POST'])
@limiter.limit("5 per minute")
def signup():
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    requested_plan = normalize_plan_key(data.get('plan_key', 'free'))
    referral_code = _normalize_referral_code(
        data.get('referral_code') or data.get('invite_code')
    )

    if not name or not email or not password:
        return jsonify(message='Name, email and password are all required'), 400

    pw_valid, pw_error = _validate_password(password)
    if not pw_valid:
        return jsonify(message=pw_error), 400

    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email):
        return jsonify(message='Please provide a valid email address.'), 400

    if User.query.filter_by(email=email).first():
        return jsonify(message='Email already registered'), 409

    if is_sales_only_plan(requested_plan, current_app.config):
        return jsonify(
            message='Team and Enterprise are sales-led right now. Please contact sales to get started.',
            contact_sales=True,
            plan_key=requested_plan,
        ), 400

    controls, referring_user, gate_payload, gate_status = _effective_signup_gate(referral_code)
    if gate_payload:
        return jsonify(gate_payload), gate_status

    user = User(
        name=name,
        email=email,
        password_hash=generate_password_hash(password),
        seat_limit=1,
        max_seats=1,
    )
    apply_plan_to_user(user, requested_plan, current_app.config, reset_credits=True)
    user.email_verified = False
    user.email_verified_at = None
    if controls.get('require_admin_approval'):
        user.access_approval_status = APPROVAL_PENDING
        user.access_approved_at = None
    else:
        user.access_approval_status = APPROVAL_APPROVED
        user.access_approved_at = datetime.utcnow()
    if referring_user and str(referring_user.email or '').strip().lower() != email:
        user.referred_by_user_id = referring_user.id
        user.signup_referral_code_used = referring_user.referral_code
        referring_user.referrals_earned = int(referring_user.referrals_earned or 0) + 1
    _enforce_admin_account_profile(user)
    db.session.add(user)
    db.session.commit()
    if _ensure_user_org(user):
        db.session.commit()

    if controls.get('require_admin_approval') and user.access_approval_status == APPROVAL_PENDING:
        return jsonify(_approval_pending_payload()), 202

    if _verification_required_enabled():
        try:
            _send_email_verification_email(user)
            db.session.commit()
        except Exception:
            current_app.logger.exception('Failed to send signup verification email for %s', user.email)
            return jsonify(message='We created your account but could not send the verification email yet. Please try again shortly.'), 500
        return jsonify(
            message='Check your inbox to verify your email before getting started.',
            verification_required=True,
            email_verified=False,
        ), 202

    access_token = _create_user_access_token(user)

    # Free plan can complete sign-up with no payment flow.
    if requested_plan == 'free':
        resp = jsonify(
            message='User created',
            token=access_token,
            user=_user_payload(user),
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
        user=_user_payload(user),
    )
    resp.status_code = 201
    return _attach_auth_cookie(resp, access_token)


@auth_bp.route('/register', methods=['POST'])
@limiter.limit("5 per minute")
def register_alias():
    """Legacy alias used by some frontend clients."""
    return signup()


@auth_bp.route('/login', methods=['POST'])
@limiter.limit("5 per minute")
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password', '')

    if not email or not password:
        return jsonify(message='Email and password are required'), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        _audit_auth_event(
            'auth.login.failed',
            target_email=email,
            details={'reason': 'user_not_found'},
        )
        return jsonify(message='Invalid credentials'), 401
    if user.deactivated_at is not None:
        return jsonify(_deactivated_account_payload()), 403

    approval_status = str(user.access_approval_status or APPROVAL_APPROVED).strip().lower()
    if approval_status == APPROVAL_REJECTED:
        return jsonify(_approval_rejected_payload()), 403
    if _access_controls().get('require_admin_approval') and approval_status == APPROVAL_PENDING:
        return jsonify(_approval_pending_payload()), 403

    now = _utc_now()
    locked_until = _normalize_locked_until(user.locked_until)
    if locked_until and locked_until > now:
        remaining = int((locked_until - now).total_seconds() / 60) + 1
        _audit_auth_event(
            'auth.login.failed',
            target_user=user,
            details={'reason': 'account_locked', 'minutes_remaining': remaining},
        )
        return jsonify(message=f'Account locked. Try again in {remaining} minute(s).'), 429

    if not check_password_hash(user.password_hash, password):
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
            user.locked_until = (now + timedelta(minutes=LOCKOUT_DURATION_MINUTES)).replace(tzinfo=None)
            user.failed_login_attempts = 0
        db.session.commit()
        _audit_auth_event(
            'auth.login.failed',
            target_user=user,
            details={
                'reason': 'invalid_password',
                'failed_login_attempts': user.failed_login_attempts or 0,
                'locked_until': user.locked_until.isoformat() if user.locked_until else None,
            },
        )
        return jsonify(message='Invalid credentials'), 401

    if _verification_required_enabled() and not bool(user.email_verified):
        return jsonify(
            message='Please verify your email before signing in.',
            verification_required=True,
        ), 403

    changed = False
    if user.failed_login_attempts or user.locked_until is not None:
        user.failed_login_attempts = 0
        user.locked_until = None
        changed = True
    if bootstrap_legacy_credits(user, current_app.config):
        changed = True
    if _enforce_admin_account_profile(user):
        changed = True
    if _ensure_user_org(user):
        changed = True
    if changed:
        db.session.commit()

    active_org = None
    try:
        active_org, _membership = resolve_active_org_for_user(user)
    except Exception:
        active_org = Organization.query.filter_by(id=user.active_organization_id).first()
    if active_org and mfa_policy_for_org(active_org) == MFA_POLICY_REQUIRED and not user.mfa_enabled:
        if _has_mfa_secret(user):
            _audit_auth_event('auth.login.succeeded', actor=user, target_user=user, details={'mfa_required': True})
            pending_token = _create_user_access_token(
                user,
                expires_delta=timedelta(minutes=5),
                additional_claims={"mfa_pending": True},
            )
            return jsonify({
                "mfa_required": True,
                "mfa_setup_required": False,
                "pending_token": pending_token,
                "organization_id": str(active_org.id),
                "organization_name": active_org.name,
            }), 200
        return jsonify(
            message='MFA setup is required for your organization.',
            mfa_required=True,
            mfa_setup_required=True,
            organization_id=str(active_org.id),
            organization_name=active_org.name,
        ), 403

    if user.mfa_enabled:
        _audit_auth_event('auth.login.succeeded', actor=user, target_user=user, details={'mfa_required': True})
        pending_token = _create_user_access_token(
            user,
            expires_delta=timedelta(minutes=5),
            additional_claims={"mfa_pending": True},
        )
        return jsonify({
            "mfa_required": True,
            "pending_token": pending_token,
        }), 200

    token = _create_user_access_token(user)
    resp = jsonify(
        token=token,
        user=_user_payload(user),
    )
    resp.status_code = 200
    _audit_auth_event('auth.login.succeeded', actor=user, target_user=user, details={'mfa_required': False})
    return _attach_auth_cookie(resp, token)


@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def get_current_user():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return jsonify(error='User not found'), 404
    if user.deactivated_at is not None:
        return jsonify(_deactivated_account_payload()), 403

    changed = bootstrap_legacy_credits(user, current_app.config)
    if _enforce_admin_account_profile(user):
        changed = True
    if _ensure_user_org(user):
        changed = True
    if changed:
        db.session.commit()

    return jsonify(**_user_payload(user)), 200


@auth_bp.route('/password/change', methods=['POST'])
@jwt_required()
@limiter.limit("5 per minute")
def change_password():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return jsonify(message='User not found'), 404

    data = request.get_json(silent=True) or {}
    current_password = str(data.get('current_password') or '')
    new_password = str(data.get('new_password') or '')

    if not current_password or not new_password:
        return jsonify(message='Current password and new password are required.'), 400
    if not check_password_hash(user.password_hash, current_password):
        return jsonify(message='Current password is incorrect.'), 401
    if check_password_hash(user.password_hash, new_password):
        return jsonify(message='Choose a different password.'), 400

    pw_valid, pw_error = _validate_password(new_password)
    if not pw_valid:
        return jsonify(message=pw_error), 400

    user.password_hash = generate_password_hash(new_password)
    user.failed_login_attempts = 0
    user.locked_until = None
    user.auth_token_version = int(user.auth_token_version or 0) + 1
    user.password_reset_version = int(user.password_reset_version or 0) + 1
    db.session.commit()

    token = _create_user_access_token(user)
    resp = jsonify(
        message='Password updated successfully.',
        token=token,
        user=_user_payload(user),
    )
    _audit_auth_event('auth.password.changed', actor=user, target_user=user)
    return _attach_auth_cookie(resp, token), 200


@auth_bp.route('/forgot-password', methods=['POST'])
@limiter.limit("3 per minute")
def forgot_password():
    data = request.get_json(silent=True) or {}
    email = str(data.get('email') or '').strip().lower()
    if not email:
        return jsonify(message='Email is required.'), 400

    user = User.query.filter_by(email=email).first()
    if user and user.deactivated_at is None:
        try:
            _send_password_reset_email(user)
            db.session.commit()
            _audit_auth_event('auth.password_reset.requested', target_user=user)
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Failed to send password reset email for %s', email)

    return jsonify(message='If that account exists, we’ll send a password reset link shortly.'), 200


@auth_bp.route('/reset-password', methods=['POST'])
@limiter.limit("5 per minute")
def reset_password():
    data = request.get_json(silent=True) or {}
    token = str(data.get('token') or '').strip()
    new_password = str(data.get('new_password') or '')

    if not token or not new_password:
        return jsonify(message='Reset token and new password are required.'), 400

    try:
        user = _load_user_from_password_reset_token(token)
    except SignatureExpired:
        return jsonify(message='That reset link has expired.'), 400
    except BadSignature:
        return jsonify(message='That reset link is invalid.'), 400

    pw_valid, pw_error = _validate_password(new_password)
    if not pw_valid:
        return jsonify(message=pw_error), 400
    if check_password_hash(user.password_hash, new_password):
        return jsonify(message='Choose a different password.'), 400

    user.password_hash = generate_password_hash(new_password)
    user.failed_login_attempts = 0
    user.locked_until = None
    user.auth_token_version = int(user.auth_token_version or 0) + 1
    user.password_reset_version = int(user.password_reset_version or 0) + 1
    db.session.commit()

    _audit_auth_event('auth.password_reset.completed', target_user=user)
    return jsonify(message='Your password has been updated. You can sign in now.'), 200


@auth_bp.route('/mfa/setup', methods=['POST'])
@jwt_required()
@limiter.limit("3 per minute")
def mfa_setup():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return jsonify(message='User not found'), 404
    if user.mfa_enabled:
        return jsonify(message='MFA is already enabled.'), 400

    secret = pyotp.random_base32()
    user.mfa_secret = _encrypt_mfa_secret(secret)
    db.session.commit()

    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=user.email, issuer_name='Jaspen')

    img = qrcode.make(provisioning_uri)
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    qr_base64 = base64.b64encode(buffer.getvalue()).decode()

    return jsonify({
        'secret': secret,
        'qr_code': f'data:image/png;base64,{qr_base64}',
        'provisioning_uri': provisioning_uri,
    }), 200


@auth_bp.route('/mfa/verify', methods=['POST'])
@jwt_required()
@limiter.limit("10 per minute")
def mfa_verify():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return jsonify(message='User not found'), 404

    data = request.get_json(silent=True) or {}
    code = str(data.get('code') or '').strip()

    if not user.mfa_secret:
        return jsonify(message='MFA setup not initiated.'), 400

    secret = _decrypt_mfa_secret(user.mfa_secret)
    if not secret:
        return jsonify(message='MFA setup not initiated.'), 400
    totp = pyotp.TOTP(secret)
    if not totp.verify(code, valid_window=1):
        return jsonify(message='Invalid code. Please try again.'), 400

    backup_codes = [pyotp.random_base32()[:8] for _ in range(10)]
    user.mfa_backup_codes = [generate_password_hash(item.upper()) for item in backup_codes]
    user.mfa_enabled = True
    user.mfa_secret = _encrypt_mfa_secret(secret)
    db.session.commit()

    return jsonify({
        'mfa_enabled': True,
        'backup_codes': backup_codes,
        'message': 'MFA enabled successfully. Save your backup codes.',
    }), 200


@auth_bp.route('/mfa/challenge', methods=['POST'])
@limiter.limit("10 per minute")
def mfa_challenge():
    data = request.get_json(silent=True) or {}
    pending_token = str(data.get('pending_token') or '').strip()
    code = str(data.get('code') or '').strip()

    try:
        decoded = decode_token(pending_token)
        if not decoded.get('mfa_pending'):
            return jsonify(message='Invalid or expired token.'), 401
        user_id = decoded.get('sub')
    except Exception:
        return jsonify(message='Invalid or expired token.'), 401

    user = User.query.get(user_id)
    if not user:
        return jsonify(message='MFA not enabled.'), 400

    secret = _decrypt_mfa_secret(user.mfa_secret)
    totp = pyotp.TOTP(secret or '')
    if secret and totp.verify(code, valid_window=1):
        if not user.mfa_enabled:
            user.mfa_enabled = True
            user.mfa_secret = _encrypt_mfa_secret(secret)
            db.session.commit()
        access_token = _create_user_access_token(user)
        resp = jsonify({"token": access_token, "user": _user_payload(user)})
        _audit_auth_event('auth.login.succeeded', actor=user, target_user=user, details={'mfa_method': 'totp'})
        return _attach_auth_cookie(resp, access_token), 200

    if user.mfa_backup_codes:
        if _verify_mfa_code(user, code):
            if not user.mfa_enabled:
                user.mfa_enabled = True
                user.mfa_secret = _encrypt_mfa_secret(secret)
                db.session.commit()
            access_token = _create_user_access_token(user)
            resp = jsonify({"token": access_token, "user": _user_payload(user)})
            _audit_auth_event('auth.login.succeeded', actor=user, target_user=user, details={'mfa_method': 'backup_code'})
            return _attach_auth_cookie(resp, access_token), 200

    _audit_auth_event('auth.login.failed', target_user=user, details={'reason': 'invalid_mfa_code'})
    return jsonify(message='Invalid MFA code.'), 401


@auth_bp.route('/mfa/disable', methods=['POST'])
@jwt_required()
@limiter.limit("3 per minute")
def mfa_disable():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return jsonify(message='User not found'), 404
    if not user.mfa_enabled:
        return jsonify(message='MFA is not enabled.'), 400

    data = request.get_json(silent=True) or {}
    current_password = str(data.get('current_password') or '')
    code = str(data.get('code') or '').strip()

    if not current_password or not code:
        return jsonify(message='Current password and MFA code are required.'), 400
    if not check_password_hash(user.password_hash, current_password):
        return jsonify(message='Current password is incorrect.'), 401

    if not _verify_mfa_code(user, code):
        return jsonify(message='Invalid MFA code.'), 401

    user.mfa_enabled = False
    user.mfa_secret = None
    user.mfa_backup_codes = []
    db.session.commit()

    _audit_auth_event('auth.mfa.disabled', actor=user, target_user=user)
    return jsonify(message='MFA disabled.'), 200


@auth_bp.route('/verify-email', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def verify_email():
    token = ''
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        token = str(data.get('token') or '').strip()
    else:
        token = str(request.args.get('token') or '').strip()

    if not token:
        if request.method == 'GET':
            return redirect(_verification_result_url('email_verification_missing_token'), code=302)
        return jsonify(message='Verification token is required.'), 400

    try:
        user = _load_user_from_verification_token(token)
    except SignatureExpired:
        if request.method == 'GET':
            return redirect(_verification_result_url('email_verification_expired'), code=302)
        return jsonify(message='That verification link has expired.'), 400
    except BadSignature:
        if request.method == 'GET':
            return redirect(_verification_result_url('email_verification_invalid'), code=302)
        return jsonify(message='That verification link is invalid.'), 400

    _mark_user_email_verified(user)
    db.session.commit()

    if request.method == 'GET':
        return redirect(_verification_result_url('verified'), code=302)
    return jsonify(
        message='Email verified successfully.',
        verified=True,
        user=_user_payload(user),
    ), 200


@auth_bp.route('/resend-verification', methods=['POST'])
@limiter.limit("3 per minute")
def resend_verification():
    data = request.get_json(silent=True) or {}
    email = str(data.get('email') or '').strip().lower()
    if not email:
        return jsonify(message='Email is required.'), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify(message='If that account exists, we’ll send a verification email shortly.'), 200
    if bool(user.email_verified):
        return jsonify(message='This email is already verified.', verified=True), 200

    try:
        _send_email_verification_email(user)
        db.session.commit()
    except Exception:
        current_app.logger.exception('Failed to resend verification email for %s', email)
        return jsonify(message='We could not send the verification email right now. Please try again shortly.'), 500

    return jsonify(message='Verification email sent.'), 200


@auth_bp.route('/google/start', methods=['GET'])
@limiter.limit("10 per minute")
def google_start():
    client_id = str(current_app.config.get('GOOGLE_CLIENT_ID') or '').strip()
    client_secret = str(current_app.config.get('GOOGLE_CLIENT_SECRET') or '').strip()
    if not client_id or not client_secret:
        current_app.logger.error('Google OAuth requested but GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET are not configured')
        return redirect(_frontend_login_error_url('google_not_configured'), code=302)

    next_path = _safe_next_path(request.args.get('next') or '/new')
    referral_code = _normalize_referral_code(
        request.args.get('referral_code')
        or request.args.get('invite_code')
        or request.args.get('ref')
        or request.args.get('invite')
    )
    state_payload = {'next': next_path}
    if referral_code:
        state_payload['referral_code'] = referral_code
    state = _google_state_serializer().dumps(state_payload)
    auth_query = urlencode({
        'client_id': client_id,
        'redirect_uri': _google_callback_url(),
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'prompt': 'select_account',
    })
    return redirect(f'{GOOGLE_AUTH_URL}?{auth_query}', code=302)


@auth_bp.route('/google/callback', methods=['GET'])
@limiter.limit("20 per minute")
def google_callback():
    if request.args.get('error'):
        return redirect(_frontend_login_error_url('google_access_denied'), code=302)

    code = request.args.get('code')
    state_token = request.args.get('state')
    if not code or not state_token:
        return redirect(_frontend_login_error_url('google_missing_code_or_state'), code=302)

    try:
        state_ttl_seconds = int(current_app.config.get('GOOGLE_OAUTH_STATE_TTL_SECONDS') or 900)
        state_data = _google_state_serializer().loads(state_token, max_age=state_ttl_seconds)
    except SignatureExpired:
        return redirect(_frontend_login_error_url('google_state_expired'), code=302)
    except BadSignature:
        return redirect(_frontend_login_error_url('google_invalid_state'), code=302)

    next_path = _safe_next_path((state_data or {}).get('next') or '/new')
    referral_code = _normalize_referral_code((state_data or {}).get('referral_code'))

    client_id = str(current_app.config.get('GOOGLE_CLIENT_ID') or '').strip()
    client_secret = str(current_app.config.get('GOOGLE_CLIENT_SECRET') or '').strip()
    if not client_id or not client_secret:
        return redirect(_frontend_login_error_url('google_not_configured'), code=302)

    try:
        token_response = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                'code': code,
                'client_id': client_id,
                'client_secret': client_secret,
                'redirect_uri': _google_callback_url(),
                'grant_type': 'authorization_code',
            },
            timeout=10,
        )
        token_payload = token_response.json() if token_response.content else {}
    except Exception:
        current_app.logger.exception('Failed exchanging Google authorization code')
        return redirect(_frontend_login_error_url('google_token_exchange_failed'), code=302)

    if not token_response.ok:
        current_app.logger.error('Google token exchange failed: status=%s payload=%s', token_response.status_code, token_payload)
        return redirect(_frontend_login_error_url('google_token_exchange_failed'), code=302)

    access_token = str((token_payload or {}).get('access_token') or '').strip()
    if not access_token:
        return redirect(_frontend_login_error_url('google_missing_access_token'), code=302)

    try:
        profile_response = requests.get(
            GOOGLE_USERINFO_URL,
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=10,
        )
        profile_payload = profile_response.json() if profile_response.content else {}
    except Exception:
        current_app.logger.exception('Failed loading Google user profile')
        return redirect(_frontend_login_error_url('google_profile_fetch_failed'), code=302)

    if not profile_response.ok:
        current_app.logger.error('Google profile fetch failed: status=%s payload=%s', profile_response.status_code, profile_payload)
        return redirect(_frontend_login_error_url('google_profile_fetch_failed'), code=302)

    email = str((profile_payload or {}).get('email') or '').strip().lower()
    email_verified = bool((profile_payload or {}).get('email_verified'))
    if not email or not email_verified:
        return redirect(_frontend_login_error_url('google_email_unverified'), code=302)

    display_name = (
        str((profile_payload or {}).get('name') or '').strip()
        or (email.split('@')[0] if '@' in email else 'Jaspen User')
    )

    user = User.query.filter_by(email=email).first()
    changed = False

    if not user:
        controls, referring_user, gate_payload, _ = _effective_signup_gate(referral_code)
        if gate_payload:
            error_code = 'invite_required'
            if gate_payload.get('signup_closed'):
                error_code = 'signup_closed'
            elif gate_payload.get('invite_invalid'):
                error_code = 'invite_invalid'
            return redirect(_frontend_login_error_url(error_code), code=302)
        user = User(
            name=display_name,
            email=email,
            password_hash=generate_password_hash(secrets.token_urlsafe(32)),
            seat_limit=1,
            max_seats=1,
            email_verified=True,
            email_verified_at=datetime.utcnow(),
        )
        if controls.get('require_admin_approval'):
            user.access_approval_status = APPROVAL_PENDING
            user.access_approved_at = None
        else:
            user.access_approval_status = APPROVAL_APPROVED
            user.access_approved_at = datetime.utcnow()
        if referring_user and str(referring_user.email or '').strip().lower() != email:
            user.referred_by_user_id = referring_user.id
            user.signup_referral_code_used = referring_user.referral_code
            referring_user.referrals_earned = int(referring_user.referrals_earned or 0) + 1
        apply_plan_to_user(user, 'free', current_app.config, reset_credits=True)
        _enforce_admin_account_profile(user)
        db.session.add(user)
        db.session.commit()
        if _ensure_user_org(user):
            db.session.commit()
    else:
        if user.deactivated_at is not None:
            return redirect(_frontend_login_error_url('account_deactivated'), code=302)
        changed = bootstrap_legacy_credits(user, current_app.config)
        if _mark_user_email_verified(user):
            changed = True
        if _enforce_admin_account_profile(user):
            changed = True
        if _ensure_user_org(user):
            changed = True
        if changed:
            db.session.commit()

    approval_status = str(user.access_approval_status or APPROVAL_APPROVED).strip().lower()
    if approval_status == APPROVAL_REJECTED:
        return redirect(_frontend_login_error_url('access_rejected'), code=302)
    if _access_controls().get('require_admin_approval') and approval_status == APPROVAL_PENDING:
        return redirect(_frontend_login_error_url('access_pending'), code=302)

    token = _create_user_access_token(user)
    resp = redirect(_frontend_callback_url(next_path), code=302)
    return _attach_auth_cookie(resp, token)


@auth_bp.route('/me', methods=['PATCH'])
@jwt_required()
def update_current_user():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return jsonify(error='User not found'), 404

    data = request.get_json() or {}
    name = str(data.get('name') or '').strip()
    if not name:
        return jsonify(error='name is required'), 400
    if len(name) > 255:
        return jsonify(error='name is too long'), 400

    user.name = name
    db.session.commit()

    if _ensure_user_org(user):
        db.session.commit()
    return jsonify(**_user_payload(user)), 200


@auth_bp.route('/logout', methods=['POST'])
def logout():
    """Clear auth cookies for logout."""
    user = None
    try:
        user_id = get_jwt_identity()
        if user_id:
            user = User.query.get(user_id)
    except Exception:
        user = None
    if user:
        _audit_auth_event('auth.logout', actor=user, target_user=user)
    resp = jsonify(message='Logged out')
    unset_jwt_cookies(resp)
    return resp, 200


@auth_bp.route('/logout/all', methods=['POST'])
@jwt_required()
def logout_all_sessions():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return jsonify(message='User not found'), 404
    user.auth_token_version = int(user.auth_token_version or 0) + 1
    db.session.commit()
    resp = jsonify(message='All sessions have been revoked.')
    _audit_auth_event('auth.logout_all', actor=user, target_user=user)
    unset_jwt_cookies(resp)
    return resp, 200


@auth_bp.route('/me-cookie', methods=['GET'])
def get_current_user_from_cookie():
    token = request.cookies.get('jaspen_access')
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

    changed = bootstrap_legacy_credits(user, current_app.config)
    if _enforce_admin_account_profile(user):
        changed = True
    if _ensure_user_org(user):
        changed = True
    if changed:
        db.session.commit()

    return jsonify(**_user_payload(user)), 200
