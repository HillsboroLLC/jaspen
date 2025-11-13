from dotenv import load_dotenv; load_dotenv()
# wsgi.py — updated with sessions and help blueprints

from flask_migrate import Migrate
from app import create_app, db
from app.routes.market_iq_analyze import market_iq_analyze_bp
from app.routes.help import help_bp
from app.middleware.rl_bind_once import bind_per_user_limits

# Initialize Flask app and database migrations
app = create_app()
migrate = Migrate(app, db)

# Blueprints
app.register_blueprint(market_iq_analyze_bp, url_prefix='/api/market-iq')
app.register_blueprint(help_bp, url_prefix='/api/help')

# bind per-user limiter
bind_per_user_limits(app)

# WSGI entry
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
