import logging
import os
from datetime import datetime, timedelta
import json
import click
from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import stripe
import sentry_sdk
from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from pythonjsonlogger import jsonlogger
from sentry_sdk.integrations.flask import FlaskIntegration
from sqlalchemy import text
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail

from app.rate_limits import (
    assert_rate_limit_storage_available,
    resolve_rate_limit_storage_uri,
)

load_dotenv()  # pull in .env

# initialize extensions
db  = SQLAlchemy()
jwt = JWTManager()
mail = Mail()
limiter = None


def rate_limit_key():
    from flask_jwt_extended import get_jwt_identity

    try:
        user_id = get_jwt_identity()
        return f"user:{user_id}" if user_id else get_remote_address()
    except Exception:
        return get_remote_address()


def _as_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def _derive_cors_origins(frontend_base_url):
    raw = os.getenv('CORS_ORIGINS')
    if raw:
        return [item.strip() for item in raw.split(',') if item.strip()]

    base = (frontend_base_url or 'http://localhost:3000').rstrip('/')
    origins = {base, 'http://localhost:3000', 'http://127.0.0.1:3000'}

    if '://www.' in base:
        origins.add(base.replace('://www.', '://', 1))
    elif '://' in base:
        scheme, host = base.split('://', 1)
        origins.add(f"{scheme}://www.{host}")

    return sorted(origins)


def _should_enable_flask_cors(frontend_base_url):
    # Production environments commonly terminate CORS at Nginx/edge.
    # Default Flask CORS to local dev only unless explicitly enabled.
    explicit = os.getenv('ENABLE_FLASK_CORS')
    if explicit is not None:
        return _as_bool(explicit, default=False)

    base = (frontend_base_url or '').lower().strip()
    if base:
        return base.startswith('http://localhost') or base.startswith('http://127.0.0.1')

    app_env = (
        os.getenv('APP_ENV')
        or os.getenv('ENV')
        or os.getenv('FLASK_ENV')
        or ''
    ).strip().lower()
    return app_env in ('development', 'dev', 'local')


def _format_retry_after(seconds):
    try:
        seconds = max(1, int(seconds or 0))
    except Exception:
        return "a short while"
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    minutes, rem = divmod(seconds, 60)
    if rem == 0:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    return f"{minutes} minute{'s' if minutes != 1 else ''} {rem} second{'s' if rem != 1 else ''}"


def _setup_logging(app):
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        fmt='%(asctime)s %(name)s %(levelname)s %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S',
    )
    handler.setFormatter(formatter)
    app.logger.handlers = [handler]
    app.logger.setLevel(logging.INFO)
    logging.root.handlers = [handler]
    logging.root.setLevel(logging.WARNING)


def _setup_sentry(app):
    dsn = str(os.getenv('SENTRY_DSN') or '').strip()
    if not dsn:
        return

    traces_sample_rate_raw = os.getenv('SENTRY_TRACES_SAMPLE_RATE', '0')
    try:
        traces_sample_rate = float(traces_sample_rate_raw)
    except (TypeError, ValueError):
        traces_sample_rate = 0.0

    sentry_sdk.init(
        dsn=dsn,
        integrations=[FlaskIntegration()],
        environment=(
            os.getenv('SENTRY_ENVIRONMENT')
            or os.getenv('APP_ENV')
            or os.getenv('ENV')
            or os.getenv('FLASK_ENV')
            or 'development'
        ),
        release=os.getenv('SENTRY_RELEASE') or None,
        traces_sample_rate=traces_sample_rate,
        send_default_pii=False,
    )
    app.logger.info('Sentry initialized')


def create_app():
    global limiter

    frontend_base_raw = os.getenv('FRONTEND_BASE_URL')
    frontend_base = frontend_base_raw or 'http://localhost:3000'
    app = Flask(__name__, instance_relative_config=False)
    _setup_logging(app)
    _setup_sentry(app)
    app.config.from_mapping(
        SECRET_KEY                     = os.getenv('SECRET_KEY'),
        SQLALCHEMY_DATABASE_URI        = os.getenv('DATABASE_URL'),
        SQLALCHEMY_TRACK_MODIFICATIONS = False,
        SQLALCHEMY_ENGINE_OPTIONS      = {
            "pool_size": int(os.getenv("DB_POOL_SIZE", "10")),
            "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "20")),
            "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "300")),
            "pool_pre_ping": True,
            "pool_timeout": int(os.getenv("DB_POOL_TIMEOUT", "30")),
        },
        MAX_CONTENT_LENGTH             = int(os.getenv('MAX_CONTENT_LENGTH', 10 * 1024 * 1024)),

        # Stripe
        STRIPE_SECRET_KEY              = os.getenv('STRIPE_SECRET_KEY'),
        STRIPE_WEBHOOK_SECRET          = os.getenv('STRIPE_WEBHOOK_SECRET'),
        # Publishable key is safe to expose to the browser (served via /billing/config)
        # so the embedded Payment Element can load Stripe.js. Test or live, mirrors the
        # secret key's mode.
        STRIPE_PUBLISHABLE_KEY         = os.getenv('STRIPE_PUBLISHABLE_KEY'),

        # Anthropic
        ANTHROPIC_API_KEY              = os.getenv('ANTHROPIC_API_KEY') or os.getenv('CLAUDE_API_KEY'),
        # Backward-compatible alias for old references.
        CLAUDE_API_KEY                 = os.getenv('CLAUDE_API_KEY') or os.getenv('ANTHROPIC_API_KEY'),
        # Google OAuth
        GOOGLE_CLIENT_ID               = os.getenv('GOOGLE_CLIENT_ID'),
        GOOGLE_CLIENT_SECRET           = os.getenv('GOOGLE_CLIENT_SECRET'),
        GOOGLE_REDIRECT_URI            = os.getenv('GOOGLE_REDIRECT_URI'),
        GOOGLE_OAUTH_STATE_TTL_SECONDS = int(os.getenv('GOOGLE_OAUTH_STATE_TTL_SECONDS', '900')),
        REQUIRE_EMAIL_VERIFICATION     = _as_bool(os.getenv('REQUIRE_EMAIL_VERIFICATION'), default=True),
        EMAIL_VERIFICATION_TOKEN_TTL_SECONDS = int(os.getenv('EMAIL_VERIFICATION_TOKEN_TTL_SECONDS', '86400')),

        # JWT
        JWT_SECRET_KEY                 = os.getenv('JWT_SECRET_KEY'),
        JWT_TOKEN_LOCATION             = ['cookies', 'headers'],
        JWT_ACCESS_TOKEN_EXPIRES       = timedelta(hours=int(os.getenv('JWT_ACCESS_TOKEN_EXPIRES_HOURS', '2'))),
        JWT_ACCESS_COOKIE_NAME         = os.getenv('JWT_ACCESS_COOKIE_NAME', 'jaspen_access'),
        JWT_COOKIE_SECURE              = _as_bool(os.getenv('JWT_COOKIE_SECURE'), default=True),
        JWT_COOKIE_SAMESITE            = os.getenv('JWT_COOKIE_SAMESITE', 'Lax'),
        JWT_COOKIE_CSRF_PROTECT        = _as_bool(os.getenv('JWT_COOKIE_CSRF_PROTECT'), default=True),
        JWT_COOKIE_DOMAIN              = os.getenv('JWT_COOKIE_DOMAIN') or None,

        # Mailer
        MAIL_SERVER                    = os.getenv('MAIL_SERVER', 'smtp.example.com'),
        MAIL_PORT                      = int(os.getenv('MAIL_PORT', 587)),
        MAIL_USE_TLS                   = os.getenv('MAIL_USE_TLS', 'true').lower() in ('true','1','yes'),
        MAIL_USE_SSL                   = os.getenv('MAIL_USE_SSL', 'false').lower() in ('true','1','yes'),
        MAIL_USERNAME                  = os.getenv('MAIL_USERNAME'),
        MAIL_PASSWORD                  = os.getenv('MAIL_PASSWORD'),
        MAIL_DEFAULT_SENDER            = os.getenv('MAIL_DEFAULT_SENDER'),
        SALES_NOTIFICATION_EMAIL       = os.getenv('SALES_NOTIFICATION_EMAIL', 'sales@jaspen.ai'),
        LEAD_TOOLKIT_LINK_TTL_SECONDS  = int(os.getenv('LEAD_TOOLKIT_LINK_TTL_SECONDS', str(60 * 60 * 24 * 30))),
    )

    # —— Stripe setup —— #
    stripe_key = app.config['STRIPE_SECRET_KEY']
    if not stripe_key:
        raise RuntimeError("STRIPE_SECRET_KEY not set in environment")
    is_production_env = str(os.getenv('FLASK_ENV') or '').strip().lower() == 'production'
    if is_production_env and str(stripe_key).startswith('sk_test_'):
        raise RuntimeError("Refusing to start in production with a Stripe test secret key (sk_test_...).")
    stripe.api_key = stripe_key

    def _stripe_price_id_from_env(*names):
        for name in names:
            value = str(os.getenv(name) or '').strip().strip('"').strip("'")
            if not value:
                continue
            while value.startswith('price_price_'):
                value = value[len('price_'):]
            return value
        return None

    # —— Map plan_keys to Stripe Price IDs —— #
    app.config['STRIPE_PRICE_IDS'] = {
        'free':            None,
        'starter':         _stripe_price_id_from_env('PRICE_ID_STARTER'),
        'essential':       _stripe_price_id_from_env('PRICE_ID_ESSENTIAL'),
        # Legacy fallback: allow existing env values to keep working.
        'team':            _stripe_price_id_from_env('PRICE_ID_TEAM', 'PRICE_ID_GROWTH'),
        # Business is canonical. The legacy Enterprise env name remains a
        # fallback because Stripe uses the same existing price ID.
        'business':      _stripe_price_id_from_env('PRICE_ID_BUSINESS', 'PRICE_ID_ENTERPRISE', 'PRICE_ID_TRANSFORM_BASIC'),
    }
    app.config['STRIPE_CREDIT_PACK_PRICE_IDS'] = {
        'credits_3000':    _stripe_price_id_from_env('PRICE_ID_CREDITS_3000', 'PRICE_ID_OVERAGE_1000'),
        'credits_8000':    _stripe_price_id_from_env('PRICE_ID_CREDITS_8000', 'PRICE_ID_OVERAGE_5000'),
        'credits_18000':   _stripe_price_id_from_env('PRICE_ID_CREDITS_18000', 'PRICE_ID_OVERAGE_20000'),
    }
    app.config['STRIPE_ANNUAL_PRICE_IDS'] = {
        'starter': _stripe_price_id_from_env('PRICE_ID_STARTER_ANNUAL'),
        'essential': _stripe_price_id_from_env('PRICE_ID_ESSENTIAL_ANNUAL'),
        'team': _stripe_price_id_from_env('PRICE_ID_TEAM_ANNUAL'),
        'business': _stripe_price_id_from_env('PRICE_ID_BUSINESS_ANNUAL'),
    }
    app.config['STRIPE_ADDITIONAL_SEAT_PRICE_IDS'] = {
        'team': _stripe_price_id_from_env('PRICE_ID_TEAM_ADDITIONAL_SEAT', 'PRICE_ID_TEAM_SEAT'),
        'business': _stripe_price_id_from_env(
            'PRICE_ID_BUSINESS_ADDITIONAL_SEAT',
            'PRICE_ID_BUSINESS_SEAT',
            'PRICE_ID_ENTERPRISE_SEAT',
        ),
    }
    app.config['STRIPE_ANNUAL_ADDITIONAL_SEAT_PRICE_IDS'] = {
        'team': _stripe_price_id_from_env('PRICE_ID_TEAM_SEAT_ANNUAL'),
        'business': _stripe_price_id_from_env('PRICE_ID_BUSINESS_SEAT_ANNUAL'),
    }
    # Backward-compatible alias used by legacy code paths.
    app.config['STRIPE_OVERAGE_PACK_PRICE_IDS'] = app.config['STRIPE_CREDIT_PACK_PRICE_IDS']

    # —— The Jaspen Advantage (/thinking-power landing pages) —— #
    # Configure this as a one-time $999 Stripe Price. The offer is intentionally
    # independent of every recurring plan and does not start an Essential subscription.
    app.config['STRIPE_JASPEN_ADVANTAGE_PRICE_ID'] = _stripe_price_id_from_env(
        'PRICE_ID_JASPEN_ADVANTAGE'
    )
    # 300,000 non-expiring usage credits, stored in internal units
    # (TOKENS_PER_CREDIT = 1000). Granted only after Stripe confirms payment.
    app.config['JASPEN_ADVANTAGE_CREDIT_TOKENS'] = 300_000_000

    required_stripe_values = {
        'PRICE_ID_ESSENTIAL': app.config['STRIPE_PRICE_IDS'].get('essential'),
        'PRICE_ID_CREDITS_3000': app.config['STRIPE_CREDIT_PACK_PRICE_IDS'].get('credits_3000'),
        'PRICE_ID_CREDITS_8000': app.config['STRIPE_CREDIT_PACK_PRICE_IDS'].get('credits_8000'),
        'PRICE_ID_CREDITS_18000': app.config['STRIPE_CREDIT_PACK_PRICE_IDS'].get('credits_18000'),
        'STRIPE_WEBHOOK_SECRET': app.config.get('STRIPE_WEBHOOK_SECRET'),
    }
    optional_stripe_values = {
        'PRICE_ID_STARTER': app.config['STRIPE_PRICE_IDS'].get('starter'),
        'PRICE_ID_TEAM': app.config['STRIPE_PRICE_IDS'].get('team'),
        'PRICE_ID_BUSINESS': app.config['STRIPE_PRICE_IDS'].get('business'),
        'PRICE_ID_JASPEN_ADVANTAGE': app.config.get('STRIPE_JASPEN_ADVANTAGE_PRICE_ID'),
    }
    missing_required_stripe = [key for key, value in required_stripe_values.items() if not str(value or '').strip()]
    missing_optional_stripe = [key for key, value in optional_stripe_values.items() if not str(value or '').strip()]
    if missing_required_stripe:
        current_app_logger = logging.getLogger(__name__)
        current_app_logger.warning(
            "Stripe configuration warnings: missing %s",
            ", ".join(missing_required_stripe),
        )
        if is_production_env:
            raise RuntimeError(
                "Missing required Stripe production configuration: "
                + ", ".join(missing_required_stripe)
            )
    if missing_optional_stripe:
        logging.getLogger(__name__).warning(
            "Stripe optional price IDs missing (sales-led plans may be unaffected): %s",
            ", ".join(missing_optional_stripe),
        )

    # —— Live-mode price-ID sanity check —— #
    # A live secret key paired with a test-mode price ID starts up fine but fails
    # at checkout with a confusing Stripe error. When running in production with a
    # live key, retrieve a representative price and assert it's live-mode so the
    # mismatch surfaces at boot instead of at a customer's first checkout. We only
    # FAIL on a confirmed mismatch — Stripe network/availability errors are logged
    # and tolerated so an outage can never block the app from starting.
    if is_production_env and str(stripe_key).startswith('sk_live_'):
        _stripe_logger = logging.getLogger(__name__)
        _price_ids_to_verify = {
            'PRICE_ID_STARTER': app.config['STRIPE_PRICE_IDS'].get('starter'),
            'PRICE_ID_ESSENTIAL': app.config['STRIPE_PRICE_IDS'].get('essential'),
            'PRICE_ID_CREDITS_3000': app.config['STRIPE_CREDIT_PACK_PRICE_IDS'].get('credits_3000'),
        }
        for _price_label, _price_id in _price_ids_to_verify.items():
            _price_id = str(_price_id or '').strip()
            if not _price_id:
                continue
            try:
                _price = stripe.Price.retrieve(_price_id)
            except Exception as _price_err:  # noqa: BLE001 - tolerate Stripe outages at boot
                _stripe_logger.warning(
                    "Could not verify Stripe price live-mode for %s (%s): %s",
                    _price_label, _price_id, _price_err,
                )
                continue
            if not bool(_price.get('livemode')):
                raise RuntimeError(
                    "Stripe live/test mode mismatch: secret key is live (sk_live_...) but "
                    f"{_price_label}={_price_id} is a TEST-mode price. Update {_price_label} "
                    "to the live-mode price ID from the Stripe dashboard."
                )
    app.config['LLM_PROVIDER_MODELS'] = {
        'claude_haiku': (
            os.getenv('MODEL_CLAUDE_HAIKU')
            or os.getenv('ANTHROPIC_MODEL_PLUTO')
            or os.getenv('MODEL_PLUTO_ID')
            or 'claude-haiku-4-5'
        ),
        'claude_sonnet': (
            os.getenv('MODEL_CLAUDE_SONNET')
            or os.getenv('ANTHROPIC_MODEL_ORBIT')
            or os.getenv('MODEL_ORBIT_ID')
            or 'claude-sonnet-4-6'
        ),
        'claude_opus': (
            os.getenv('MODEL_CLAUDE_OPUS')
            or os.getenv('ANTHROPIC_MODEL_TITAN')
            or os.getenv('MODEL_TITAN_ID')
            or 'claude-opus-4-8'
        ),
        'gemini_flash': os.getenv('GEMINI_MODEL_FLASH') or 'gemini-2.5-flash',
        'gemini_pro': os.getenv('GEMINI_MODEL_PRO') or 'gemini-2.5-pro',
    }
    app.config['MODEL_TYPE_BACKING_IDS'] = {
        'pluto': os.getenv('MODEL_PLUTO_ID') or os.getenv('ANTHROPIC_MODEL_PLUTO') or app.config['LLM_PROVIDER_MODELS']['claude_haiku'],
        'orbit': os.getenv('MODEL_ORBIT_ID') or os.getenv('ANTHROPIC_MODEL_ORBIT') or app.config['LLM_PROVIDER_MODELS']['claude_sonnet'],
        'titan': os.getenv('MODEL_TITAN_ID') or os.getenv('ANTHROPIC_MODEL_TITAN') or app.config['LLM_PROVIDER_MODELS']['claude_opus'],
    }
    app.config['GEMINI_API_KEY'] = os.getenv('GEMINI_API_KEY', '')
    app.config['AI_AGENT_ANTHROPIC_MODEL'] = os.getenv('AI_AGENT_ANTHROPIC_MODEL') or app.config['LLM_PROVIDER_MODELS']['claude_sonnet']
    app.config['AI_AGENT_MAX_OUTPUT_TOKENS'] = int(os.getenv('AI_AGENT_MAX_OUTPUT_TOKENS', '1500'))
    app.config['AI_AGENT_TEMPERATURE'] = float(os.getenv('AI_AGENT_TEMPERATURE', '0.2'))
    app.config['AI_AGENT_CREDITS_PER_1K_TOKENS'] = float(os.getenv('AI_AGENT_CREDITS_PER_1K_TOKENS', '1.0'))
    app.config['AI_AGENT_MIN_CREDIT_CHARGE'] = int(os.getenv('AI_AGENT_MIN_CREDIT_CHARGE', '1'))
    app.config['AI_AGENT_CREDIT_MULTIPLIERS'] = os.getenv('AI_AGENT_CREDIT_MULTIPLIERS_JSON', '')
    app.config['FEEDBACK_DIGEST_RECIPIENTS'] = os.getenv('FEEDBACK_DIGEST_RECIPIENTS', '')
    app.config['FEEDBACK_DIGEST_USE_AI'] = _as_bool(os.getenv('FEEDBACK_DIGEST_USE_AI'), default=True)
    app.config['FEEDBACK_DIGEST_ANTHROPIC_MODEL'] = os.getenv('FEEDBACK_DIGEST_ANTHROPIC_MODEL', '')
    app.config['ADMIN_USER_IDS'] = os.getenv('ADMIN_USER_IDS', '')
    app.config['ADMIN_EMAILS'] = os.getenv('ADMIN_EMAILS', '')
    app.config['ADMIN_BLOCKED_EMAILS'] = os.getenv('ADMIN_BLOCKED_EMAILS', '')
    app.config['JIRA_BASE_URL'] = os.getenv('JIRA_BASE_URL', '')
    app.config['JIRA_EMAIL'] = os.getenv('JIRA_EMAIL', '')
    app.config['JIRA_API_TOKEN'] = os.getenv('JIRA_API_TOKEN', '')
    app.config['JIRA_DEFAULT_PROJECT_KEY'] = os.getenv('JIRA_DEFAULT_PROJECT_KEY', '')
    app.config['JIRA_DEFAULT_ISSUE_TYPE'] = os.getenv('JIRA_DEFAULT_ISSUE_TYPE', 'Task')
    app.config['JIRA_WEBHOOK_SECRET'] = os.getenv('JIRA_WEBHOOK_SECRET', '')
    app.config['WORKFRONT_BASE_URL'] = os.getenv('WORKFRONT_BASE_URL', '')
    app.config['WORKFRONT_PROJECT_ID'] = os.getenv('WORKFRONT_PROJECT_ID', '')
    app.config['WORKFRONT_API_TOKEN'] = os.getenv('WORKFRONT_API_TOKEN', '')
    app.config['WORKFRONT_WEBHOOK_SECRET'] = os.getenv('WORKFRONT_WEBHOOK_SECRET', '')
    app.config['SMARTSHEET_BASE_URL'] = os.getenv('SMARTSHEET_BASE_URL', 'https://api.smartsheet.com')
    app.config['SMARTSHEET_SHEET_ID'] = os.getenv('SMARTSHEET_SHEET_ID', '')
    app.config['SMARTSHEET_API_TOKEN'] = os.getenv('SMARTSHEET_API_TOKEN', '')
    app.config['SMARTSHEET_WEBHOOK_SECRET'] = os.getenv('SMARTSHEET_WEBHOOK_SECRET', '')
    app.config['SALESFORCE_AUTH_BASE_URL'] = os.getenv('SALESFORCE_AUTH_BASE_URL', 'https://login.salesforce.com')
    _sf_redirect = os.getenv('SALESFORCE_REDIRECT_URI', '').strip()
    if not _sf_redirect:
        _api_base = frontend_base.replace('://www.', '://').rstrip('/')
        if _api_base and not _api_base.startswith('http://localhost'):
            _sf_redirect = f"{_api_base}/api/v1/connectors/salesforce/oauth/callback"
    app.config['SALESFORCE_REDIRECT_URI'] = _sf_redirect
    app.config['SNOWFLAKE_PRIVATE_KEY_PASSPHRASE'] = os.getenv('SNOWFLAKE_PRIVATE_KEY_PASSPHRASE', '')
    app.config['CONNECTOR_ENCRYPTION_KEY'] = os.getenv('CONNECTOR_ENCRYPTION_KEY', '')
    app.config['CONNECTOR_CREDENTIALS_SECRET'] = os.getenv('CONNECTOR_CREDENTIALS_SECRET', '')
    connector_encryption_key = str(app.config.get('CONNECTOR_ENCRYPTION_KEY') or '').strip()
    if not connector_encryption_key:
        if is_production_env:
            raise RuntimeError("CONNECTOR_ENCRYPTION_KEY must be set in production")
        logging.getLogger(__name__).warning(
            "CONNECTOR_ENCRYPTION_KEY not set. Connector credentials may not be encrypted with a dedicated key."
        )
    # —— Frontend base URL for success/cancel links —— #
    app.config['FRONTEND_BASE_URL'] = frontend_base

    # —— Database setup —— #
    db.init_app(app)

    # —— JWT setup —— #
    if not app.config['JWT_SECRET_KEY']:
        raise RuntimeError("JWT_SECRET_KEY not set in environment")
    jwt.init_app(app)

    @jwt.token_in_blocklist_loader
    def _jwt_token_version_mismatch(jwt_header, jwt_payload):
        from .models import User, UserAuthSession

        user_id = str(jwt_payload.get('sub') or '').strip()
        if not user_id:
            return True
        user = db.session.get(User, user_id)
        if not user:
            return True
        token_version = int(jwt_payload.get('token_version') or 0)
        current_version = int(getattr(user, 'auth_token_version', 0) or 0)
        if token_version != current_version:
            return True

        # Pending MFA tokens are short-lived and intentionally not tracked in
        # user_auth_sessions. Validate only token_version for these.
        if bool(jwt_payload.get('mfa_pending')):
            return False

        jti = str(jwt_payload.get('jti') or '').strip()
        if not jti:
            return False

        auth_session = (
            UserAuthSession.query
            .filter(UserAuthSession.user_id == user_id, UserAuthSession.token_jti == jti)
            .first()
        )
        if not auth_session:
            # Backward-compatible: allow older tokens issued before auth-session
            # tracking existed, as long as token_version still matches.
            return False
        if auth_session.revoked_at is not None:
            return True
        return False

    @jwt.revoked_token_loader
    def _revoked_token_response(jwt_header, jwt_payload):
        return jsonify({"error": "Unauthorized", "message": "Your session is no longer valid. Please sign in again."}), 401

    limiter = Limiter(
        key_func=rate_limit_key,
        default_limits=["200 per minute"],
        storage_uri=resolve_rate_limit_storage_uri(),
        in_memory_fallback_enabled=False,
        swallow_errors=False,
    )
    limiter.init_app(app)
    assert_rate_limit_storage_available(limiter)

    # —— Mail setup —— #
    mail.init_app(app)

    # —— CORS —— #
    enable_flask_cors = _should_enable_flask_cors(frontend_base_raw)
    if enable_flask_cors:
        cors_origins = _derive_cors_origins(frontend_base)
        CORS(
            app,
            supports_credentials=True,
            resources={r"/api/v1/*": {"origins": cors_origins}},
        )
    else:
        # Ensure upstream app does not emit CORS headers when edge (e.g., Nginx)
        # is responsible for CORS, preventing duplicate ACAO values.
        @app.after_request
        def _strip_cors_headers(resp):
            for key in (
                'Access-Control-Allow-Origin',
                'Access-Control-Allow-Credentials',
                'Access-Control-Allow-Headers',
                'Access-Control-Allow-Methods',
                'Access-Control-Expose-Headers',
                'Access-Control-Max-Age',
            ):
                resp.headers.pop(key, None)
            return resp

    # —— Security response headers —— #
    @app.after_request
    def _set_security_headers(resp):
        resp.headers['X-Content-Type-Options'] = 'nosniff'
        resp.headers['X-Frame-Options'] = 'DENY'
        resp.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        resp.headers['X-XSS-Protection'] = '0'
        resp.headers['Permissions-Policy'] = (
            'camera=(), microphone=(), geolocation=(), interest-cohort=()'
        )
        if app.config.get('JWT_COOKIE_SECURE'):
            resp.headers['Strict-Transport-Security'] = (
                'max-age=31536000; includeSubDomains'
            )
        return resp

    # —— Register blueprints —— #
    from .routes.auth      import auth_bp
    from .routes.admin     import admin_bp
    from .routes.chat      import chat_bp
    from .routes.billing   import billing_bp
    from .routes.connectors import connectors_bp
    from .routes.dashboard import dashboard_bp
    from .routes.ai_agent  import ai_agent_bp
    from .routes.insights import insights_bp
    from .routes.activity import activity_bp
    from .routes.export import export_bp
    from .routes.reports import reports_bp
    from .routes.starters import starters_bp
    from .routes.team import team_bp
    from .routes.teams import teams_bp
    from .routes.monitoring import monitoring_bp
    from .routes.strategy import strategy_bp, analyze_project
    from .routes.studio import studio_bp
    from .routes.public_intake import public_intake_bp
    from .routes.leads import leads_bp
    from .routes.decision_records import decision_records_bp
    from .routes.decision_profile import decision_profile_bp
    from .routes.tools import tools_bp
    from . import models_studio  # noqa: F401  register Studio tables with SQLAlchemy
    from . import models_decision_record  # noqa: F401  register DecisionRecord table with SQLAlchemy

    app.register_blueprint(auth_bp,      url_prefix='/api/v1/auth')
    app.register_blueprint(admin_bp,     url_prefix='/api/v1/admin')
    app.register_blueprint(chat_bp,      url_prefix='/api/v1/chat')
    app.register_blueprint(billing_bp,   url_prefix='/api/v1/billing')
    app.register_blueprint(connectors_bp, url_prefix='/api/v1/connectors')
    app.register_blueprint(dashboard_bp, url_prefix='/api/v1/dashboard')
    app.register_blueprint(ai_agent_bp,  url_prefix='/api/v1/ai-agent')
    app.register_blueprint(insights_bp,  url_prefix='/api/v1/insights')
    app.register_blueprint(activity_bp,  url_prefix='/api/v1/activity')
    app.register_blueprint(export_bp,    url_prefix='/api/v1/export')
    app.register_blueprint(reports_bp,   url_prefix='/api/v1/reports')
    app.register_blueprint(starters_bp,  url_prefix='/api/v1/starters')
    app.register_blueprint(team_bp, url_prefix='/api/v1/team')
    app.register_blueprint(teams_bp, url_prefix='/api/v1/teams')
    app.register_blueprint(monitoring_bp, url_prefix='/api/v1/monitoring')
    app.register_blueprint(strategy_bp, url_prefix='/api/v1/strategy')
    app.register_blueprint(studio_bp, url_prefix='/api/v1/studio')
    app.register_blueprint(public_intake_bp, url_prefix='/api/v1/public/intake')
    app.register_blueprint(leads_bp, url_prefix='/api/v1/public')
    app.register_blueprint(decision_records_bp, url_prefix='/api/v1/decision-records')
    app.register_blueprint(decision_profile_bp, url_prefix='/api/v1/decision-profile')
    app.register_blueprint(tools_bp, url_prefix='/api/v1/tools')
    app.add_url_rule(
        '/api/v1/ai-agent/analyze',
        endpoint='ai_agent_analyze',
        view_func=analyze_project,
        methods=['POST'],
    )

    # Optional sessions blueprint
    try:
        from .routes.sessions import sessions_bp
        app.register_blueprint(sessions_bp, url_prefix='/api/v1/sessions')
    except ImportError:
        app.logger.warning("sessions blueprint not found; session saving will not work")

    # Jaspen strategy blueprint
    app.logger.info("Jaspen strategy API registered successfully at /api/v1/strategy")

    # Statistical Analysis blueprint
    app.logger.info("About to register statistical analysis blueprint")
    try:
        app.logger.info("Attempting statistical analysis blueprint import")
        from .statistical_analysis_api import statistical_bp
        app.logger.info("Statistical analysis blueprint import successful; registering blueprint")
        app.register_blueprint(statistical_bp, url_prefix='/api/v1/statistical-analysis')
        app.logger.info("Statistical Analysis API registered successfully")
    except ImportError as e:
        app.logger.warning("Statistical analysis blueprint import failed: %s", e)
    except Exception as e:
        app.logger.exception("Unexpected error registering statistical analysis blueprint: %s", e)

    @app.errorhandler(400)
    def handle_400(e):
        return jsonify({"error": "Bad request", "message": str(e)}), 400

    @app.errorhandler(401)
    def handle_401(e):
        return jsonify({"error": "Unauthorized"}), 401

    @app.errorhandler(403)
    def handle_403(e):
        return jsonify({"error": "Forbidden"}), 403

    @app.errorhandler(404)
    def handle_404(e):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(405)
    def handle_405(e):
        return jsonify({"error": "Method not allowed"}), 405

    @app.errorhandler(429)
    def handle_429(e):
        retry_after = None
        limit_value = getattr(getattr(e, "limit", None), "limit", None)
        if limit_value is not None and hasattr(limit_value, "get_expiry"):
            try:
                retry_after = int(limit_value.get_expiry())
            except Exception:
                retry_after = None
        retry_after = retry_after or 60
        retry_after_human = _format_retry_after(retry_after)
        payload = {
            "error": "Too many requests",
            "code": "rate_limit_exceeded",
            "message": (
                f"You've hit a temporary request limit. Please try again in about {retry_after_human}. "
                "If you need higher throughput, you can upgrade your plan or add credits from Account."
            ),
            "retry_after_seconds": retry_after,
            "retry_after_human": retry_after_human,
            "upgrade_hint": "Upgrade your plan or add credits from Account for more capacity.",
        }
        response = jsonify(payload)
        response.status_code = 429
        response.headers["Retry-After"] = str(retry_after)
        return response

    @app.errorhandler(500)
    def handle_500(e):
        app.logger.exception("Unhandled server error")
        return jsonify({"error": "Internal server error"}), 500

    @app.errorhandler(Exception)
    def handle_exception(e):
        app.logger.exception("Unhandled exception: %s", e)
        return jsonify({"error": "Internal server error"}), 500

    @app.route('/health', methods=['GET'])
    def health_check():
        try:
            db.session.execute(text('SELECT 1'))
            db_status = "ok"
        except Exception:
            db_status = "unavailable"
        return jsonify({
            "status": "ok" if db_status == "ok" else "degraded",
            "database": db_status,
        }), 200 if db_status == "ok" else 503

    @app.cli.group("credits")
    def credits_cli():
        """Credit maintenance commands."""

    @credits_cli.command("reset-monthly")
    @click.option("--dry-run", is_flag=True, help="Calculate resets without committing.")
    def reset_monthly_credits_cli(dry_run):
        """Reset monthly credits for due free/starter/essential/team users."""
        from scripts.reset_monthly_credits import reset_monthly_credits

        updated, skipped = reset_monthly_credits(dry_run=dry_run)
        click.echo(json.dumps({
            "dry_run": bool(dry_run),
            "credits_reset": int(updated),
            "credits_skipped": int(skipped),
        }))

    @app.cli.group("feedback")
    def feedback_cli():
        """Feedback maintenance commands."""

    @feedback_cli.command("digest-monthly")
    @click.option("--dry-run", is_flag=True, help="Build the digest without sending email.")
    @click.option("--no-ai", is_flag=True, help="Skip AI synthesis and use deterministic summary text.")
    @click.option("--recipient", multiple=True, help="Email recipient. Can be passed more than once.")
    @click.option("--start-date", default=None, help="Inclusive start date in YYYY-MM-DD format.")
    @click.option("--end-date", default=None, help="Exclusive end date in YYYY-MM-DD format.")
    def monthly_feedback_digest_cli(dry_run, no_ai, recipient, start_date, end_date):
        """Email a monthly digest of assistant message feedback."""
        from app.feedback_digest import build_feedback_digest, previous_month_range, send_feedback_digest

        start_at, end_at = previous_month_range()
        if start_date:
            start_at = datetime.fromisoformat(start_date)
        if end_date:
            end_at = datetime.fromisoformat(end_date)
        use_ai = bool(app.config.get("FEEDBACK_DIGEST_USE_AI", True)) and not no_ai
        digest = build_feedback_digest(start_at, end_at, use_ai=use_ai)
        result = send_feedback_digest(
            digest,
            recipients=list(recipient) if recipient else None,
            dry_run=dry_run,
        )
        click.echo(json.dumps({
            "dry_run": bool(dry_run),
            "sent": bool(result.get("sent")),
            "recipients": result.get("recipients", []),
            "subject": result.get("subject"),
            "period_start": digest["start_at"].date().isoformat(),
            "period_end_exclusive": digest["end_at"].date().isoformat(),
            "feedback_total": int(digest["summary"].get("total") or 0),
            "up_count": int(digest["summary"].get("up_count") or 0),
            "down_count": int(digest["summary"].get("down_count") or 0),
            "note_count": int(digest["summary"].get("note_count") or 0),
            "used_ai": bool(use_ai),
            "body_preview": result.get("body", "")[:1200] if dry_run else None,
        }, default=str))

    return app
