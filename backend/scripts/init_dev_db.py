# backend/scripts/init_dev_db.py
#
# Bootstrap a LOCAL development database (idempotent, safe to re-run).
#
# Why db.create_all() instead of `flask db upgrade`: the Alembic history
# currently has multiple heads (see docs/NEXT_STEPS.md item C13), which makes
# `upgrade` ambiguous. create_all() only creates MISSING tables — it never
# alters, drops, or touches existing tables or data. Once the migration heads
# are merged, this script can switch to running migrations.
#
# Guard: refuses to run against anything that is not SQLite. A localhost
# Postgres is allowed ONLY with --allow-non-sqlite (substring tricks and SSH
# tunnels can make a remote database look local, so SQLite-only is the default).
#
# Run from backend/ with the venv active:
#   python scripts/init_dev_db.py
#   python scripts/init_dev_db.py --allow-non-sqlite   # localhost Postgres etc.
#
# Creates two login-ready users (password for both: jaspen-dev-password):
#   dev@jaspen.local        — regular user, essential-style credits
#   dev-admin@jaspen.local  — admin (listed in ADMIN_EMAILS in backend/.env)

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.security import generate_password_hash

from app import create_app, db
from app import models_studio  # noqa: F401  register Studio tables
from app.models import User

DEV_PASSWORD = "jaspen-dev-password"

SEED_USERS = [
    {
        "email": "dev@jaspen.local",
        "name": "Dev User",
        "subscription_plan": "essential",
        "credits_remaining": 5000,
    },
    {
        "email": "dev-admin@jaspen.local",
        "name": "Dev Admin",
        "subscription_plan": "enterprise",
        "credits_remaining": 50000,
    },
]


def assert_local_database(uri, allow_non_sqlite=False):
    from sqlalchemy.engine import make_url

    url = make_url(str(uri or ""))

    if url.drivername.startswith("sqlite"):
        return

    if not allow_non_sqlite:
        raise SystemExit(
            "REFUSING to run: this script bootstraps SQLite dev databases only.\n"
            f"  DATABASE_URL uses driver '{url.drivername}' (host={url.host!r})\n"
            "If you really mean a LOCAL non-SQLite database, re-run with\n"
            "--allow-non-sqlite. Beware: an SSH tunnel to production also looks\n"
            "like localhost — double-check what the port actually points at."
        )

    if url.host not in ("localhost", "127.0.0.1", "::1"):
        raise SystemExit(
            "REFUSING to run even with --allow-non-sqlite: host is not localhost.\n"
            f"  DATABASE_URL host={url.host!r}\n"
            "This script must never point at a remote database."
        )


def main():
    allow_non_sqlite = "--allow-non-sqlite" in sys.argv[1:]
    app = create_app()
    with app.app_context():
        assert_local_database(
            app.config["SQLALCHEMY_DATABASE_URI"],
            allow_non_sqlite=allow_non_sqlite,
        )

        before = set(db.inspect(db.engine).get_table_names())
        db.create_all()
        after = set(db.inspect(db.engine).get_table_names())
        created = sorted(after - before)
        print(f"Tables created: {created or '(none — schema already present)'}")
        print(f"Total tables: {len(after)}")

        for spec in SEED_USERS:
            existing = User.query.filter_by(email=spec["email"]).first()
            if existing:
                print(f"Seed user exists: {spec['email']}")
                continue
            user = User(
                email=spec["email"],
                name=spec["name"],
                password_hash=generate_password_hash(DEV_PASSWORD),
                subscription_plan=spec["subscription_plan"],
                credits_remaining=spec["credits_remaining"],
                email_verified=True,
                access_approval_status="approved",
            )
            db.session.add(user)
            print(f"Seed user created: {spec['email']} (password: {DEV_PASSWORD})")
        db.session.commit()

        print("\nDev database ready:", app.config["SQLALCHEMY_DATABASE_URI"])


if __name__ == "__main__":
    main()
