import json
from datetime import datetime

from flask import current_app

from app import create_app, db
from app.models import User
from app.billing_config import reset_user_monthly_credits


def reset_monthly_credits(*, dry_run=False):
    updated = 0
    skipped = 0
    now = datetime.utcnow()
    users = User.query.all()
    for user in users:
        if reset_user_monthly_credits(user, current_app.config, now):
            updated += 1
        else:
            skipped += 1
    if dry_run:
        db.session.rollback()
    else:
        db.session.commit()
    return updated, skipped


def main():
    app = create_app()
    with app.app_context():
        updated, skipped = reset_monthly_credits()
        print(
            json.dumps(
                {
                    "timestamp_utc": datetime.utcnow().isoformat() + "Z",
                    "credits_reset": updated,
                    "credits_skipped": skipped,
                    "dry_run": False,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
