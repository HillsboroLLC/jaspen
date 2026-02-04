from dotenv import load_dotenv; load_dotenv()
# ============================================================================
# File: backend/wsgi.py
# Purpose:
#   Gunicorn WSGI entrypoint.
#
# WHY THIS FILE EXISTS:
#   In your current deployment, this file wires process-boundary concerns that
#   historically lived here:
#   - dotenv load
#   - migrations initialization
#   - per-user limiter binding
#   - a couple of "support" blueprints (help) and MIQ analyze registration
#
# Phase 3 Stabilization Guard:
#   Avoid duplicate blueprint registration crashes by registering only if the
#   blueprint name is not already present on the app.
# ============================================================================

from flask_migrate import Migrate

from app import create_app, db
from app.middleware.rl_bind_once import bind_per_user_limits


# Initialize Flask app and database migrations
app = create_app()
migrate = Migrate(app, db)

# bind per-user limiter (kept from original)
bind_per_user_limits(app)


# ----------------------------------------------------------------------------
# WHY: Preserve existing callable routes while preventing "already registered"
#      boot failures if these blueprints are (now or later) registered inside
#      create_app().
# ----------------------------------------------------------------------------

# MIQ analyze blueprint (register only if not already registered elsewhere)
try:
    from app.routes.market_iq_analyze import market_iq_analyze_bp

    if "market_iq_analyze" not in app.blueprints:
        app.register_blueprint(market_iq_analyze_bp, url_prefix="/api/market-iq")
except Exception:
    # Keep startup resilient if module absent or import fails in some env.
    pass

# Help blueprint (register only if not already registered elsewhere)
try:
    from app.routes.help import help_bp

    if "help" not in app.blueprints:
        app.register_blueprint(help_bp, url_prefix="/api/help")
except Exception:
    pass


# WSGI entry (dev-only; Gunicorn uses `app` directly)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
