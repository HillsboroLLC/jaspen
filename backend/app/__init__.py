# ============================================================================
# File: backend/app/__init__.py
# Purpose:
#   Flask app factory + blueprint wiring.
#
#   Phase 3 Stabilization (Option A: MIQ is authoritative):
#   - Keep ALL currently-working routes callable (no breaking changes)
#   - Make MIQ (/api/market-iq/*) explicitly registered + documented as authoritative
#   - Preserve existing conversational + sessions + SSE surfaces for now
#   - Add an optional guard for legacy alias paths WITHOUT moving existing paths
#     (so nothing breaks while Phase 3 proceeds one file at a time)
#
# IMPORTANT:
#   market_iq_analyze_bp is currently registered in wsgi.py.
#   Until we consolidate registration ownership, DO NOT also register it here,
#   or Gunicorn will fail to boot due to duplicate blueprint registration.
# ============================================================================

from datetime import timedelta
import os

from dotenv import load_dotenv
from flask import Flask
from flask_jwt_extended import JWTManager
from flask_mail import Mail
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

import stripe

from .cookie_hooks import install_cookie_hooks


load_dotenv()  # pull in .env

# initialize extensions (MUST exist before route modules import "from app import db")
db = SQLAlchemy()
jwt = JWTManager()
mail = Mail()

# ----------------------------------------------------------------------------
# WHY: Optional guard for "legacy alias" paths.
#      IMPORTANT: We do NOT move existing endpoints by default (no breakage).
#      If enabled, we only add quarantined aliases under /api/legacy/*.
# ----------------------------------------------------------------------------
ENABLE_LEGACY_AGENT_ALIAS = os.getenv("ENABLE_LEGACY_AGENT_ALIAS", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)


def create_app():
    app = Flask(__name__, instance_relative_config=False)

    # =========================================================================
    # WHY: Minimal CORS for actual /api/* responses (preflight handled at Nginx).
    #      Kept local to avoid hidden global side effects.
    # =========================================================================
    @app.after_request
    def _cors_apply(resp):
        try:
            from flask import request

            if request.path.startswith("/api/"):
                origin = request.headers.get("Origin")
                if origin:
                    resp.headers["Access-Control-Allow-Origin"] = origin
                    resp.headers["Access-Control-Allow-Credentials"] = "true"
                    resp.headers["Vary"] = "Origin"
        except Exception:
            pass
        return resp

    # =========================================================================
    # WHY: Configuration must remain centralized and deterministic.
    # =========================================================================
    app.config.from_mapping(
        SECRET_KEY=os.getenv("SECRET_KEY"),
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        # Stripe
        STRIPE_SECRET_KEY=os.getenv("STRIPE_SECRET_KEY"),
        # OpenAI / Claude
        OPENAI_API_KEY=os.getenv("OPENAI_API_KEY"),
        CLAUDE_API_KEY=os.getenv("CLAUDE_API_KEY"),
        # JWT
        JWT_SECRET_KEY=os.getenv("JWT_SECRET_KEY"),
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(hours=8),
        # Mailer
        MAIL_SERVER=os.getenv("MAIL_SERVER", "smtp.example.com"),
        MAIL_PORT=int(os.getenv("MAIL_PORT", 587)),
        MAIL_USE_TLS=os.getenv("MAIL_USE_TLS", "true").lower() in ("true", "1", "yes"),
        MAIL_USE_SSL=os.getenv("MAIL_USE_SSL", "false").lower() in ("true", "1", "yes"),
        MAIL_USERNAME=os.getenv("MAIL_USERNAME"),
        MAIL_PASSWORD=os.getenv("MAIL_PASSWORD"),
        MAIL_DEFAULT_SENDER=os.getenv("MAIL_DEFAULT_SENDER"),
    )

    # =========================================================================
    # WHY: Stripe config must fail safe (disable features) rather than crash.
    # =========================================================================
    stripe_key = app.config["STRIPE_SECRET_KEY"]
    if not stripe_key:
        app.logger.warning("STRIPE_SECRET_KEY not set; Stripe features disabled.")
        app.config["STRIPE_SECRET_KEY"] = None
    stripe.api_key = stripe_key

    app.config["STRIPE_PRICE_IDS"] = {
        "essential": os.getenv("PRICE_ID_ESSENTIAL"),
        "growth": os.getenv("PRICE_ID_GROWTH"),
        "transform_basic": os.getenv("PRICE_ID_TRANSFORM_BASIC"),
        "founder": os.getenv("PRICE_ID_FOUNDER"),
        "enterprise": os.getenv("PRICE_ID_ENTERPRISE"),
    }

    app.config["FRONTEND_BASE_URL"] = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000")

    # =========================================================================
    # WHY: Extension initialization order must be consistent across deployments.
    # =========================================================================
    db.init_app(app)

    if not app.config["JWT_SECRET_KEY"]:
        raise RuntimeError("JWT_SECRET_KEY not set in environment")
    jwt.init_app(app)

    mail.init_app(app)

    # =========================================================================
    # WHY: Import blueprints *inside* create_app() so "db" is fully initialized
    #      before any route module does "from app import db".
    # =========================================================================

    # Core blueprints (non-agent domain)
    from app.routes.discuss import discuss_bp
    from app.routes.scenario import scenario_bp
    from app.statistical_analysis_api import statistical_bp  # stats API
    from app.routes.projects import projects_bp

    # MIQ core (authoritative agent surface)
    from app.routes.market_iq import market_iq_bp

    app.register_blueprint(discuss_bp)
    app.register_blueprint(scenario_bp, url_prefix="/api/scenario")
    app.register_blueprint(projects_bp)
    app.register_blueprint(statistical_bp)

    # =========================================================================
    # WHY: Authoritative AI Agent surface (MIQ) must be explicitly registered.
    #      Keep the existing path (/api/market-iq) unchanged.
    # =========================================================================
    app.register_blueprint(market_iq_bp, url_prefix="/api/market-iq")

    # =========================================================================
    # WHY: Register non-agent application APIs (auth/billing/dashboard/db tools).
    # =========================================================================
    from app.routes.db_oracle import db_oracle_bp
    from app.routes.auth import auth_bp
    from app.routes.billing import billing_bp
    from app.routes.dashboard import dashboard_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(billing_bp, url_prefix="/api/billing")
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(db_oracle_bp, url_prefix="/api/db/oracle")
    
    # =========================================================================
    # WHY: AI Agent system (consolidated: conversation + scoring + analysis)
    # =========================================================================
    from app.routes.ai_agent import ai_agent_bp
    from app.routes.ai_agent_scenarios import ai_agent_scenarios_bp
    app.register_blueprint(ai_agent_bp, url_prefix="/api/ai-agent")
    app.register_blueprint(ai_agent_scenarios_bp, url_prefix="/api/ai-agent")

    # =========================================================================
    # WHY: Sessions surface is currently used by the frontend; keep it callable.
    # =========================================================================
    try:
        from app.routes.sessions import sessions_bp
        app.register_blueprint(sessions_bp, url_prefix="/api/sessions")
    except ImportError:
        print("Warning: sessions blueprint not found. Session saving will not work.")

    # =========================================================================
    # WHY: Cookie hooks provide a controlled bridge between cookies and
    #      Authorization without forcing a single client auth strategy.
    # =========================================================================
    install_cookie_hooks(app)

    # =========================================================================
    # WHY: SSE chat stream route currently binds to /api/chat/stream inside
    #      the blueprint. DO NOT add a url_prefix here, or it will double-prefix.
    # =========================================================================
    try:
        from app.routes.chat_stream import chat_stream_bp
        app.register_blueprint(chat_stream_bp)
    except Exception as e:
        print(f"DEBUG: SSE register failed: {e}")

    # =========================================================================
    # WHY: Conversational surface is currently used by the frontend (/api/chat).
    #      Keep it callable for now (no breaking changes).
    # =========================================================================
    from app.routes.conversational_ai import conversational_ai_bp
    app.register_blueprint(conversational_ai_bp, url_prefix="/api")

    # =========================================================================
    # WHY: MIQ threads/bundles/adoption surface (blueprint defines its own prefix).
    # =========================================================================
    from app.routes.market_iq_threads import market_iq_threads_bp
    app.register_blueprint(market_iq_threads_bp)

    # =========================================================================
    # WHY: Optional quarantined legacy aliases, WITHOUT moving existing paths.
    #      This allows a safe migration path while keeping production stable.
    #
    #      IMPORTANT: Flask does not allow registering the same Blueprint twice
    #      under the same name. Alias registrations therefore use unique names.
    # =========================================================================
    if ENABLE_LEGACY_AGENT_ALIAS:
        try:
            app.register_blueprint(
                conversational_ai_bp,
                url_prefix="/api/legacy",
                name="conversational_ai_legacy",
            )
        except Exception as e:
            print(f"[WARN] Legacy conversational alias not registered: {e}")

        try:
            from app.routes.sessions import sessions_bp as _sessions_bp
            app.register_blueprint(
                _sessions_bp,
                url_prefix="/api/legacy/sessions",
                name="sessions_legacy",
            )
        except Exception as note:
            print(f"[WARN] Legacy sessions alias not registered: {note}")

        print("[INFO] Legacy agent aliases enabled (ENABLE_LEGACY_AGENT_ALIAS=true).")
    else:
        print("[INFO] Legacy agent aliases disabled (ENABLE_LEGACY_AGENT_ALIAS=false).")

    # =========================================================================
    # WHY: Init Alembic/Flask-Migrate once.
    # =========================================================================
    try:
        Migrate(app, db)
    except Exception:
        pass

    return app
