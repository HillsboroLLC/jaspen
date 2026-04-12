import json
from datetime import datetime

from flask import current_app

from app import create_app, db
from app.models import User
from app.billing_config import reset_user_monthly_credits


def reset_monthly_credits():
    updated = 0
    skipped = 0
    now = datetime.utcnow()
    users = User.query.all()
    for user in users:
        if reset_user_monthly_credits(user, current_app.config, now):
            updated += 1
        else:
            skipped += 1
    return updated, skipped


def main():
    app = create_app()
    with app.app_context():
        updated, skipped = reset_monthly_credits()
        db.session.commit()
        print(
            json.dumps(
                {
                    "credits_reset": updated,
                    "credits_skipped": skipped,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
