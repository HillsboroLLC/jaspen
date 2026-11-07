"""Exercise production-code reads and a plan save against a migrated test DB.

Run this from ``backend/`` in the production-code worktree, after the rehearsal
has seeded and upgraded a test database::

    APP_ENV=test DATABASE_URL=<test-url> PYTHONPATH=. \
      python <dev-worktree>/backend/scripts/verify_production_rollback_compatibility.py

The fixed identifiers belong only to the rehearsal's synthetic rows.  The
script refuses a database that is not explicitly configured as a test DB.
"""

import copy
import os

from sqlalchemy.engine import make_url


SESSION_ID = "thread-main"
RECORD_ID = "record-main"
TASK_ID = "task-score"
UPDATED_DUE_DATE = "2027-02-03"


def _require_test_database():
    if os.environ.get("APP_ENV") != "test":
        raise SystemExit("APP_ENV must be test")
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL must identify the migrated test database")
    url = make_url(database_url)
    if url.drivername.startswith("postgresql"):
        if "test" not in str(url.database or "").lower():
            raise SystemExit("PostgreSQL database name must contain 'test'")
    elif not url.drivername.startswith("sqlite"):
        raise SystemExit("Only PostgreSQL or SQLite test databases are supported")


def main():
    _require_test_database()

    from app import create_app, db
    from app.models import UserSession
    from app.models_decision_record import DecisionRecord

    app = create_app()
    with app.app_context():
        session = UserSession.query.filter_by(session_id=SESSION_ID).one()
        if session.user_id != "user-migration":
            raise SystemExit("Refusing to edit a non-rehearsal session")

        scenarios = copy.deepcopy(session.scenarios_json)
        tasks = scenarios["wbs_by_scorecard"]["card-score"]["tasks"]
        task = next(item for item in tasks if item.get("id") == TASK_ID)
        task["due_date"] = UPDATED_DUE_DATE
        session.scenarios_json = scenarios
        db.session.commit()

        db.session.expire_all()
        saved = UserSession.query.filter_by(session_id=SESSION_ID).one()
        saved_tasks = saved.scenarios_json["wbs_by_scorecard"]["card-score"]["tasks"]
        saved_task = next(item for item in saved_tasks if item.get("id") == TASK_ID)
        if saved_task.get("due_date") != UPDATED_DUE_DATE:
            raise SystemExit("Plan task due date did not persist")

        record = DecisionRecord.query.filter_by(id=RECORD_ID).one()
        if record.user_id != "user-migration":
            raise SystemExit("Loaded decision record is not rehearsal data")

        print(
            f"P8 passed: saved {TASK_ID} due date and loaded {record.id} "
            f"with production code"
        )


if __name__ == "__main__":
    main()
