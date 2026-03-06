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

def create_app():
    app = Flask(__name__, instance_relative_config=False)
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
        'essential':       os.getenv('PRICE_ID_ESSENTIAL'),
        'growth':          os.getenv('PRICE_ID_GROWTH'),
        'transform_basic': os.getenv('PRICE_ID_TRANSFORM_BASIC'),
        'founder':         os.getenv('PRICE_ID_FOUNDER'),
        'enterprise':      os.getenv('PRICE_ID_ENTERPRISE'),
    }
    # —— Frontend base URL for success/cancel links —— #
    app.config['FRONTEND_BASE_URL'] = os.getenv('FRONTEND_BASE_URL', 'http://localhost:3000')

    # —— Database setup —— #
    db.init_app(app)

    # —— JWT setup —— #
    if not app.config['JWT_SECRET_KEY']:
        raise RuntimeError("JWT_SECRET_KEY not set in environment")
    jwt.init_app(app)

    # —— Mail setup —— #
    mail.init_app(app)

    # —— CORS —— #
    CORS(app)

    # —— Register blueprints —— #
    from .routes.auth      import auth_bp
    from .routes.chat      import chat_bp
    from .routes.billing   import billing_bp
    from .routes.dashboard import dashboard_bp
    from .routes.ai_agent import ai_agent_bp

    app.register_blueprint(auth_bp,      url_prefix='/api/auth')
    app.register_blueprint(chat_bp,      url_prefix='/api/chat')
    app.register_blueprint(billing_bp,   url_prefix='/api/billing')
    app.register_blueprint(dashboard_bp)  # includes its own /api/dashboard path
    app.register_blueprint(ai_agent_bp,  url_prefix='/api/ai-agent')
    # Backward-compat: frontend still calls /api/market-iq/ for bundle, adopt, analyses
    app.register_blueprint(ai_agent_bp,  url_prefix='/api/market-iq', name='ai_agent_compat')

    # Optional sessions blueprint
    try:
        from .routes.sessions import sessions_bp
        app.register_blueprint(sessions_bp, url_prefix='/api/sessions')
    except ImportError:
        print("Warning: sessions blueprint not found. Session saving will not work.")

    print("DEBUG: AI Agent API registered at /api/ai-agent (compat alias at /api/market-iq)")

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
