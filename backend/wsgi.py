# wsgi.py

from database_secret import load_database_url_secret

# Load the protected database connection before importing the application. This
# keeps production credentials out of systemd's inspectable Environment data.
load_database_url_secret()

# Production rollout begins in observation-only mode. These explicit process
# defaults preserve any deliberate environment override for a later, separately
# authorized activation while ensuring an unset service can never activate.
import os  # noqa: E402

os.environ.setdefault("JASPEN_AI_ROUTER_MODE", "shadow")
os.environ.setdefault("JASPEN_CREDIT_POLICY_MODE", "shadow")

from flask_migrate import Migrate  # noqa: E402
from app import create_app, db  # noqa: E402

# Initialize Flask app and database migrations
app = create_app()
migrate = Migrate(app, db)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
# This file is the entry point for the WSGI server to run the Flask application.
