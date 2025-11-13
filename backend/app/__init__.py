from datetime import timedelta
from .cookie_hooks import install_cookie_hooks
import os
from flask import Flask
from app.routes.discuss import discuss_bp
from app.routes.scenario import scenario_bp


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

def create_app():
    app = Flask(__name__, instance_relative_config=False)

    app.register_blueprint(discuss_bp)
    app.register_blueprint(scenario_bp, url_prefix='/api/scenario')

    # --- App-level CORS for /api/* (no NGINX dependence) ---
    ALLOWED_ORIGINS = {"https://sekki.io"}  # add "https://www.sekki.io" if needed

    def _origin_allowed(origin: str | None) -> bool:
        return bool(origin) and origin in ALLOWED_ORIGINS

    @app.before_request
    def _cors_preflight():
        # Short-circuit preflight for any /api/* route
        from flask import request, make_response
        if request.method == "OPTIONS" and request.path.startswith("/api/"):
            origin = request.headers.get("Origin")
            resp = make_response("", 204)
            if _origin_allowed(origin):
                resp.headers["Access-Control-Allow-Origin"] = origin
                resp.headers["Access-Control-Allow-Credentials"] = "true"
                resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
                resp.headers["Access-Control-Allow-Headers"] = request.headers.get("Access-Control-Request-Headers", "Content-Type, Authorization, X-Requested-With, X-Session-ID")
                resp.headers["Access-Control-Max-Age"] = "86400"
                resp.headers["Vary"] = "Origin"
            return resp

    @app.after_request
    def _cors_apply(resp):
        # Add CORS headers to all /api/* responses
        try:
            from flask import request
            if request.path.startswith("/api/"):
                origin = request.headers.get("Origin")
                if _origin_allowed(origin):
                    resp.headers["Access-Control-Allow-Origin"] = origin
                    resp.headers["Access-Control-Allow-Credentials"] = "true"
                    resp.headers["Vary"] = "Origin"
        except Exception:
            pass  # do not interfere with primary response
        return resp

    # Accept JWT via headers AND cookies; use our login cookie name.
    app.config.setdefault('JWT_TOKEN_LOCATION', ['headers', 'cookies'])
    app.config.setdefault('JWT_ACCESS_COOKIE_NAME', 'sekki_access')
    app.config.setdefault('JWT_COOKIE_DOMAIN', '.sekki.io')
    # Allow cookie auth without CSRF double-submit (adjust later if you want CSRF)
    app.config.setdefault('JWT_COOKIE_CSRF_PROTECT', False)
    app.config.setdefault('JWT_COOKIE_DOMAIN', '.sekki.io')
    # Cross-subdomain, HTTPS-friendly cookie behavior
    app.config.setdefault('JWT_COOKIE_SECURE', True)
    app.config.setdefault('JWT_COOKIE_DOMAIN', '.sekki.io')
    app.config.setdefault('JWT_COOKIE_SAMESITE', 'None')
    app.config.setdefault('JWT_COOKIE_DOMAIN', '.sekki.io')

    # Inject Authorization header from JWT cookie when client only sends cookies.
    @app.before_request
    def inject_auth_from_cookie():
        # WHY: Many endpoints expect Authorization: Bearer <jwt>,
        # but the frontend uses the 'sekki_access' cookie from /auth/login.
        try:
            from flask import request
            if 'Authorization' not in request.headers:
                tok = request.cookies.get('sekki_access')
                if tok:
                    # Make it look like a normal Bearer token for jwt decorators
                    request.environ['HTTP_AUTHORIZATION'] = f'Bearer {tok}'
        except Exception:
            pass

    app.config.from_mapping(
        SECRET_KEY                     = os.getenv('SECRET_KEY'),
        SQLALCHEMY_DATABASE_URI        = os.getenv('DATABASE_URL'),
        SQLALCHEMY_TRACK_MODIFICATIONS = False,

        # Stripe
        STRIPE_SECRET_KEY              = os.getenv('STRIPE_SECRET_KEY'),

        # OpenAI / Claude
        OPENAI_API_KEY                 = os.getenv('OPENAI_API_KEY'),
        CLAUDE_API_KEY                 = os.getenv('CLAUDE_API_KEY'),

        # JWT
        JWT_SECRET_KEY                 = os.getenv('JWT_SECRET_KEY'),
          JWT_ACCESS_TOKEN_EXPIRES        = timedelta(hours=8),

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
        current_app.logger.warning("STRIPE_SECRET_KEY not set; Stripe features disabled."); app.config["STRIPE_SECRET_KEY"] = None
    stripe.api_key = stripe_key

    # —— Map plan_keys to Stripe Price IDs —— #
    app.config['STRIPE_PRICE_IDS'] = {
        'essential':       os.getenv('PRICE_ID_ESSENTIAL'),
        'growth':          os.getenv('PRICE_ID_GROWTH'),
        'transform_basic': os.getenv('PRICE_ID_TRANSFORM_BASIC'),
        'founder':         os.getenv('PRICE_ID_FOUNDER'),
        'enterprise':      os.getenv('PRICE_ID_ENTERPRISE'),
    }
    # —— Frontend base URL for success/cancel links —— #
    app.config['FRONTEND_BASE_URL'] = os.getenv('FRONTEND_BASE_URL', 'http://localhost:3000' )

    # —— Database setup —— #
    db.init_app(app)

    # —— JWT setup —— #
    if not app.config['JWT_SECRET_KEY']:
        raise RuntimeError("JWT_SECRET_KEY not set in environment")
    jwt.init_app(app)

    # —— Mail setup —— #
    mail.init_app(app)

    # —— CORS —— #
# (disabled)     CORS(app, origins=["https://sekki.io"], supports_credentials=True )

    # —— Register blueprints —— #
    from .routes.db_oracle import db_oracle_bp
    from .routes.auth      import auth_bp
    from .routes.chat      import chat_bp
    from .routes.billing   import billing_bp
    from .routes.dashboard import dashboard_bp
    from .routes.market_iq import market_iq_bp

    app.register_blueprint(auth_bp,      url_prefix='/api/auth')
    # app.register_blueprint(chat_disabled,      url_prefix='/api/chat')
    app.register_blueprint(billing_bp,   url_prefix='/api/billing')
    app.register_blueprint(dashboard_bp)  # includes its own /api/dashboard path
    app.register_blueprint(db_oracle_bp, url_prefix='/api/db/oracle')
    # app.register_blueprint(market_iq_disabled, url_prefix="/api/market-iq")
    from app.routes.conversational_ai import conversational_ai_bp
    # app.register_blueprint(conversational_ai_bp, url_prefix='/api/market-iq')

    # Optional sessions blueprint
    try:
        from .routes.sessions import sessions_bp
        app.register_blueprint(sessions_bp, url_prefix='/api/sessions')
    except ImportError:
        print("Warning: sessions blueprint not found. Session saving will not work.")

    # Statistical Analysis blueprint
    print("DEBUG: About to register statistical analysis blueprint")
    try:
        print("DEBUG: Attempting import...")
        from .statistical_analysis_api import statistical_bp
        print("DEBUG: Import successful, registering blueprint...")
        app.register_blueprint(statistical_bp, url_prefix='/api/statistical-analysis')
        print("DEBUG: Statistical Analysis API registered successfully")
    except ImportError as e:
        pass  # silenced
    except Exception as e:
        print(f"DEBUG: Other error: {e}")
        import traceback
        traceback.print_exc()

    # Install cookie <-> Authorization bridge (safe, optional)
    install_cookie_hooks(app)
    # SSE chat stream route (Claude)
    try:
        from app.routes.chat_stream import chat_stream_bp
        app.register_blueprint(chat_stream_bp)
    except Exception as e:
        print(f"DEBUG: SSE register failed: {e}")

    # Register Claude conversational blueprint after app exists
    try:
        from app.routes.conversational_ai import conversational_ai_bp  # local import avoids early import issues
        app.register_blueprint(conversational_ai_bp, url_prefix="/api")  # exposes /api/chat
    except Exception as e:
        print(f"DEBUG: failed to register conversational_ai_bp: {e}")
        app.register_blueprint(conversation_bp, url_prefix="/api/conversation")
        app.register_blueprint(market_iq_analyze_bp, url_prefix="/api/market-iq")
    return app

# app.register_blueprint(conversational_ai_bp, url_prefix='/api/market-iq')
