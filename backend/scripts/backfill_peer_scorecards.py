"""Idempotently backfill standalone scorecards from legacy session/scenario JSON."""

from app import create_app, db
from app.models import UserSession
from app.scorecards import backfill_legacy_scorecards


def run():
    app = create_app()
    created = 0
    with app.app_context():
        for row in UserSession.query.filter(UserSession.archived_at.is_(None)).yield_per(100):
            created += backfill_legacy_scorecards(
                user_id=row.user_id,
                thread_id=row.session_id,
                legacy_session=row.payload,
                legacy_thread_data=row.scenarios_json,
                organization_id=row.organization_id,
            )
        db.session.commit()
    return created


if __name__ == '__main__':
    print(f'Backfilled {run()} peer scorecards.')
