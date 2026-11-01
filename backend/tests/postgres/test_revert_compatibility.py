import os
import subprocess
import sys

from app import db as app_db
from app.scenarios_store import load_scenarios_data, save_project_scenarios_data
from tests.journeys.test_b1_plan_interleavings import _seed


def test_data_written_by_b1_is_read_and_edited_by_pre_b1_code(
    app, db, test_user, tmp_path,
):
    tid = "postgres-revert-compatibility"
    _seed(test_user, db, tid)
    save_project_scenarios_data(test_user.id, tid, {
        "wbs_by_scorecard": {
            "planner-card": {
                "scorecard_id": "planner-card",
                "tasks": [{"id": "task", "title": "written by B1"}],
            },
        },
        "scenarios": {
            "scenario": {
                "scenario_id": "scenario",
                "label": "written by B1",
                "deltas": {},
            },
        },
    })

    archive = tmp_path / "pre-b1.tar"
    checkout = tmp_path / "pre-b1"
    checkout.mkdir()
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    subprocess.run(
        ["git", "archive", "--format=tar", f"--output={archive}", "e32bfe11"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["tar", "-xf", str(archive), "-C", str(checkout)],
        check=True,
        capture_output=True,
        text=True,
    )

    script = r"""
import os
import sys

sys.path.insert(0, os.path.join(sys.argv[1], "backend"))
from app import create_app
from app.scenarios_store import load_scenarios_data, save_scenarios_data

app = create_app()
with app.app_context():
    data = load_scenarios_data(sys.argv[2])
    thread = data[sys.argv[3]]
    assert thread["wbs_by_scorecard"]["planner-card"]["tasks"][0]["title"] == "written by B1"
    assert thread["scenarios"]["scenario"]["label"] == "written by B1"
    thread["wbs_by_scorecard"]["planner-card"]["tasks"][0]["title"] = "edited by pre-B1"
    thread["scenarios"]["scenario"]["label"] = "edited by pre-B1"
    assert save_scenarios_data(sys.argv[2], data)
"""
    env = os.environ.copy()
    env.pop("TEST_DATABASE_URL", None)
    env["DATABASE_URL"] = app.config["SQLALCHEMY_DATABASE_URI"]
    env["APP_ENV"] = "test"
    env["JWT_SECRET_KEY"] = "test-secret-key"
    env["SECRET_KEY"] = "test-secret"
    env["STRIPE_SECRET_KEY"] = "sk_test_123"
    subprocess.run(
        [sys.executable, "-c", script, str(checkout), str(test_user.id), tid],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    app_db.session.remove()
    stored = load_scenarios_data(test_user.id)[tid]
    assert stored["wbs_by_scorecard"]["planner-card"]["tasks"][0]["title"] == "edited by pre-B1"
    assert stored["scenarios"]["scenario"]["label"] == "edited by pre-B1"
