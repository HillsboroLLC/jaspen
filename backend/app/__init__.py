import logging
import os
from datetime import timedelta
from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import stripe
from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from pythonjsonlogger import jsonlogger
from sqlalchemy import text
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail

load_dotenv()  # pull in .env

# initialize extensions
db  = SQLAlchemy()
jwt = JWTManager()
mail = Mail()
limiter = None


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


def create_app():
    global limiter

    frontend_base_raw = os.getenv('FRONTEND_BASE_URL')
    frontend_base = frontend_base_raw or 'http://localhost:3000'
    app = Flask(__name__, instance_relative_config=False)
    _setup_logging(app)
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

        # Anthropic
        ANTHROPIC_API_KEY              = os.getenv('ANTHROPIC_API_KEY') or os.getenv('CLAUDE_API_KEY'),
        # Backward-compatible alias for old references.
        CLAUDE_API_KEY                 = os.getenv('CLAUDE_API_KEY') or os.getenv('ANTHROPIC_API_KEY'),
        # Google OAuth
        GOOGLE_CLIENT_ID               = os.getenv('GOOGLE_CLIENT_ID'),
        GOOGLE_CLIENT_SECRET           = os.getenv('GOOGLE_CLIENT_SECRET'),
        GOOGLE_REDIRECT_URI            = os.getenv('GOOGLE_REDIRECT_URI'),
        GOOGLE_OAUTH_STATE_TTL_SECONDS = int(os.getenv('GOOGLE_OAUTH_STATE_TTL_SECONDS', '900')),

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
    )

    # —— Stripe setup —— #
    stripe_key = app.config['STRIPE_SECRET_KEY']
    if not stripe_key:
        raise RuntimeError("STRIPE_SECRET_KEY not set in environment")
    stripe.api_key = stripe_key

    # —— Map plan_keys to Stripe Price IDs —— #
    app.config['STRIPE_PRICE_IDS'] = {
        'free':            None,
        'essential':       os.getenv('PRICE_ID_ESSENTIAL'),
        # Legacy fallback: allow existing env values to keep working.
        'team':            os.getenv('PRICE_ID_TEAM') or os.getenv('PRICE_ID_GROWTH'),
        'enterprise':      os.getenv('PRICE_ID_ENTERPRISE') or os.getenv('PRICE_ID_TRANSFORM_BASIC'),
    }
    app.config['STRIPE_OVERAGE_PACK_PRICE_IDS'] = {
        'pack_1000':       os.getenv('PRICE_ID_OVERAGE_1000'),
        'pack_5000':       os.getenv('PRICE_ID_OVERAGE_5000'),
        'pack_20000':      os.getenv('PRICE_ID_OVERAGE_20000'),
    }
    app.config['MODEL_TYPE_BACKING_IDS'] = {
        'pluto': os.getenv('MODEL_PLUTO_ID') or os.getenv('ANTHROPIC_MODEL_PLUTO') or 'claude-3-5-haiku-latest',
        'orbit': os.getenv('MODEL_ORBIT_ID') or os.getenv('ANTHROPIC_MODEL_ORBIT') or 'claude-3-7-sonnet-latest',
        'titan': os.getenv('MODEL_TITAN_ID') or os.getenv('ANTHROPIC_MODEL_TITAN') or 'claude-3-7-sonnet-latest',
    }
    app.config['AI_AGENT_ANTHROPIC_MODEL'] = os.getenv('AI_AGENT_ANTHROPIC_MODEL') or 'claude-3-7-sonnet-latest'
    app.config['AI_AGENT_MAX_OUTPUT_TOKENS'] = int(os.getenv('AI_AGENT_MAX_OUTPUT_TOKENS', '260'))
    app.config['AI_AGENT_TEMPERATURE'] = float(os.getenv('AI_AGENT_TEMPERATURE', '0.2'))
    app.config['AI_AGENT_CREDITS_PER_1K_TOKENS'] = float(os.getenv('AI_AGENT_CREDITS_PER_1K_TOKENS', '1.0'))
    app.config['AI_AGENT_MIN_CREDIT_CHARGE'] = int(os.getenv('AI_AGENT_MIN_CREDIT_CHARGE', '1'))
    app.config['AI_AGENT_CREDIT_MULTIPLIERS'] = os.getenv('AI_AGENT_CREDIT_MULTIPLIERS_JSON', '')
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
    app.config['SALESFORCE_REDIRECT_URI'] = os.getenv('SALESFORCE_REDIRECT_URI', '')
    app.config['SNOWFLAKE_PRIVATE_KEY_PASSPHRASE'] = os.getenv('SNOWFLAKE_PRIVATE_KEY_PASSPHRASE', '')
    app.config['CONNECTOR_ENCRYPTION_KEY'] = os.getenv('CONNECTOR_ENCRYPTION_KEY', '')
    app.config['CONNECTOR_CREDENTIALS_SECRET'] = os.getenv('CONNECTOR_CREDENTIALS_SECRET', '')
    # —— Frontend base URL for success/cancel links —— #
    app.config['FRONTEND_BASE_URL'] = frontend_base

    # —— Database setup —— #
    db.init_app(app)

    # —— JWT setup —— #
    if not app.config['JWT_SECRET_KEY']:
        raise RuntimeError("JWT_SECRET_KEY not set in environment")
    jwt.init_app(app)

    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=["200 per minute"],
        storage_uri=os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
    )
    limiter.init_app(app)

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
    from .routes.reports import reports_bp
    from .routes.starters import starters_bp
    from .routes.team import team_bp
    from .routes.teams import teams_bp
    from .routes.monitoring import monitoring_bp
    from .routes.strategy import strategy_bp, analyze_project

    app.register_blueprint(auth_bp,      url_prefix='/api/v1/auth')
    app.register_blueprint(admin_bp,     url_prefix='/api/v1/admin')
    app.register_blueprint(chat_bp,      url_prefix='/api/v1/chat')
    app.register_blueprint(billing_bp,   url_prefix='/api/v1/billing')
    app.register_blueprint(connectors_bp, url_prefix='/api/v1/connectors')
    app.register_blueprint(dashboard_bp, url_prefix='/api/v1/dashboard')
    app.register_blueprint(ai_agent_bp,  url_prefix='/api/v1/ai-agent')
    app.register_blueprint(insights_bp,  url_prefix='/api/v1/insights')
    app.register_blueprint(activity_bp,  url_prefix='/api/v1/activity')
    app.register_blueprint(reports_bp,   url_prefix='/api/v1/reports')
    app.register_blueprint(starters_bp,  url_prefix='/api/v1/starters')
    app.register_blueprint(team_bp, url_prefix='/api/v1/team')
    app.register_blueprint(teams_bp, url_prefix='/api/v1/teams')
    app.register_blueprint(monitoring_bp, url_prefix='/api/v1/monitoring')
    app.register_blueprint(strategy_bp, url_prefix='/api/v1/strategy')
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
        return jsonify({"error": "Too many requests", "message": "Rate limit exceeded. Please try again shortly."}), 429

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

    return app
