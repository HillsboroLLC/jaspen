# backend/scripts/init_dev_db.py
#
# Bootstrap a LOCAL development database (idempotent, safe to re-run).
#
# Historical migrations contain PostgreSQL constraint operations that cannot be
# replayed on SQLite. create_all() remains the supported local bootstrap.
# --fresh-baseline additionally verifies the schema and records the current
# Alembic head, but ONLY for a brand-new SQLite file. Existing databases are
# never stamped by this script; ordinary mode keeps its previous behavior.
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
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

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


def reserve_fresh_database(engine):
    """Reserve a new SQLite file exclusively; never adopt an existing schema."""
    if engine.url.get_backend_name() != "sqlite" or not engine.url.database or engine.url.database == ":memory:":
        raise SystemExit("--fresh-baseline requires a new local SQLite file")
    path = Path(engine.url.database)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.touch(mode=0o600, exist_ok=False)
    except FileExistsError:
        raise SystemExit("--fresh-baseline refuses an existing database; choose a new file")


def record_verified_baseline(engine):
    """Mark only a freshly initialized, schema-verified database as current."""
    migrations = Path(__file__).resolve().parents[1] / "migrations"
    head = ScriptDirectory(str(migrations)).get_current_head()
    if not head:
        raise RuntimeError("A single migration head is required")
    with engine.begin() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, db.metadata)
        if differences:
            raise RuntimeError(f"Fresh schema differs from current models: {differences}")
        # MigrationContext.stamp records this verified schema; it does not replay
        # historical data migrations. The new database contains only dev seeds.
        context.stamp(ScriptDirectory(str(migrations)), head)
    print(f"Verified fresh schema; Alembic baseline: {head}")


def main():
    fresh_baseline = "--fresh-baseline" in sys.argv
    allow_non_sqlite = "--allow-non-sqlite" in sys.argv[1:]
    app = create_app()
    with app.app_context():
        assert_local_database(
            app.config["SQLALCHEMY_DATABASE_URI"],
            allow_non_sqlite=allow_non_sqlite,
        )

        if fresh_baseline:
            reserve_fresh_database(db.engine)

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

        if fresh_baseline:
            record_verified_baseline(db.engine)

        print("\nDev database ready:", app.config["SQLALCHEMY_DATABASE_URI"])


if __name__ == "__main__":
    main()
