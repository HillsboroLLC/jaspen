import os
from flask import Flask
from flask_cors import CORS
from dotenv import load_dotenv
import stripe
from flask_jwt_extended import JWTManager
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail

load_dotenv()  # pull in .env

# initialize extensions
db  = SQLAlchemy()
jwt = JWTManager()
mail = Mail()


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


def create_app():
    frontend_base_raw = os.getenv('FRONTEND_BASE_URL')
    frontend_base = frontend_base_raw or 'http://localhost:3000'
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_mapping(
        SECRET_KEY                     = os.getenv('SECRET_KEY'),
        SQLALCHEMY_DATABASE_URI        = os.getenv('DATABASE_URL'),
        SQLALCHEMY_TRACK_MODIFICATIONS = False,

        # Stripe
        STRIPE_SECRET_KEY              = os.getenv('STRIPE_SECRET_KEY'),
        STRIPE_WEBHOOK_SECRET          = os.getenv('STRIPE_WEBHOOK_SECRET'),

        # OpenAI / Claude
        OPENAI_API_KEY                 = os.getenv('OPENAI_API_KEY'),
        ANTHROPIC_API_KEY              = os.getenv('ANTHROPIC_API_KEY') or os.getenv('CLAUDE_API_KEY'),
        # Backward-compatible alias for old references.
        CLAUDE_API_KEY                 = os.getenv('CLAUDE_API_KEY') or os.getenv('ANTHROPIC_API_KEY'),

        # JWT
        JWT_SECRET_KEY                 = os.getenv('JWT_SECRET_KEY'),
        JWT_TOKEN_LOCATION             = ['cookies', 'headers'],
        JWT_ACCESS_COOKIE_NAME         = os.getenv('JWT_ACCESS_COOKIE_NAME', 'jaspen_access'),
        JWT_COOKIE_SECURE              = _as_bool(os.getenv('JWT_COOKIE_SECURE'), default=False),
        JWT_COOKIE_SAMESITE            = os.getenv('JWT_COOKIE_SAMESITE', 'Lax'),
        JWT_COOKIE_CSRF_PROTECT        = _as_bool(os.getenv('JWT_COOKIE_CSRF_PROTECT'), default=False),
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
        'pluto': os.getenv('MODEL_PLUTO_ID') or os.getenv('OPENAI_MODEL_PLUTO') or 'gpt-4o-mini',
        'orbit': os.getenv('MODEL_ORBIT_ID') or os.getenv('OPENAI_MODEL_ORBIT') or 'gpt-4o',
        'titan': os.getenv('MODEL_TITAN_ID') or os.getenv('OPENAI_MODEL_TITAN') or 'gpt-4',
    }
    app.config['AI_AGENT_ANTHROPIC_MODEL'] = os.getenv('AI_AGENT_ANTHROPIC_MODEL') or 'claude-3-5-sonnet-latest'
    app.config['AI_AGENT_MAX_OUTPUT_TOKENS'] = int(os.getenv('AI_AGENT_MAX_OUTPUT_TOKENS', '260'))
    app.config['AI_AGENT_TEMPERATURE'] = float(os.getenv('AI_AGENT_TEMPERATURE', '0.2'))
    app.config['AI_AGENT_CREDITS_PER_1K_TOKENS'] = float(os.getenv('AI_AGENT_CREDITS_PER_1K_TOKENS', '1.0'))
    app.config['AI_AGENT_MIN_CREDIT_CHARGE'] = int(os.getenv('AI_AGENT_MIN_CREDIT_CHARGE', '1'))
    app.config['AI_AGENT_CREDIT_MULTIPLIERS'] = os.getenv('AI_AGENT_CREDIT_MULTIPLIERS_JSON', '')
    app.config['JIRA_BASE_URL'] = os.getenv('JIRA_BASE_URL', '')
    app.config['JIRA_EMAIL'] = os.getenv('JIRA_EMAIL', '')
    app.config['JIRA_API_TOKEN'] = os.getenv('JIRA_API_TOKEN', '')
    app.config['JIRA_DEFAULT_PROJECT_KEY'] = os.getenv('JIRA_DEFAULT_PROJECT_KEY', '')
    app.config['JIRA_DEFAULT_ISSUE_TYPE'] = os.getenv('JIRA_DEFAULT_ISSUE_TYPE', 'Task')
    app.config['JIRA_WEBHOOK_SECRET'] = os.getenv('JIRA_WEBHOOK_SECRET', '')
    # —— Frontend base URL for success/cancel links —— #
    app.config['FRONTEND_BASE_URL'] = frontend_base

    # —— Database setup —— #
    db.init_app(app)

    # —— JWT setup —— #
    if not app.config['JWT_SECRET_KEY']:
        raise RuntimeError("JWT_SECRET_KEY not set in environment")
    jwt.init_app(app)

    # —— Mail setup —— #
    mail.init_app(app)

    # —— CORS —— #
    enable_flask_cors = _should_enable_flask_cors(frontend_base_raw)
    if enable_flask_cors:
        cors_origins = _derive_cors_origins(frontend_base)
        CORS(
            app,
            supports_credentials=True,
            resources={r"/api/*": {"origins": cors_origins}},
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
    from .routes.chat      import chat_bp
    from .routes.billing   import billing_bp
    from .routes.connectors import connectors_bp
    from .routes.dashboard import dashboard_bp
    from .routes.ai_agent  import ai_agent_bp
    from .routes.market_iq import market_iq_bp, analyze_project

    app.register_blueprint(auth_bp,      url_prefix='/api/auth')
    app.register_blueprint(chat_bp,      url_prefix='/api/chat')
    app.register_blueprint(billing_bp,   url_prefix='/api/billing')
    app.register_blueprint(connectors_bp, url_prefix='/api/connectors')
    app.register_blueprint(dashboard_bp)  # includes its own /api/dashboard path
    app.register_blueprint(ai_agent_bp,  url_prefix='/api/ai-agent')
    app.register_blueprint(market_iq_bp, url_prefix='/api/market-iq')
    app.add_url_rule(
        '/api/ai-agent/analyze',
        endpoint='ai_agent_analyze',
        view_func=analyze_project,
        methods=['POST'],
    )

    # Optional sessions blueprint
    try:
        from .routes.sessions import sessions_bp
        app.register_blueprint(sessions_bp, url_prefix='/api/sessions')
    except ImportError:
        print("Warning: sessions blueprint not found. Session saving will not work.")

    # Jaspen strategy blueprint
    print("DEBUG: Jaspen strategy API registered successfully at /api/market-iq")

    # Statistical Analysis blueprint
    print("DEBUG: About to register statistical analysis blueprint")
    try:
        print("DEBUG: Attempting import...")
        from .statistical_analysis_api import statistical_bp
        print("DEBUG: Import successful, registering blueprint...")
        app.register_blueprint(statistical_bp, url_prefix='/api/statistical-analysis')
        print("DEBUG: Statistical Analysis API registered successfully")
    except ImportError as e:
        print(f"DEBUG: Import error: {e}")
    except Exception as e:
        print(f"DEBUG: Other error: {e}")
        import traceback
        traceback.print_exc()

    return app
