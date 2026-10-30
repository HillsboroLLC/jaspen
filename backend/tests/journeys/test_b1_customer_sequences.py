"""B1 continuous customer sequences from independent verification probes."""

import copy

import pytest

from app.models import UserSession
import app.scenarios_store as store
from app.scenarios_store import load_scenarios_data, save_project_scenarios_data
from tests.journeys.test_b1_plan_interleavings import CARD, CONFLICT, _build, _seed, _status
from tests.test_decision_flow_stabilization import mock_accounting
from tests.test_plan_build_jobs import _ai_plan


class Browser:
    """Mimic JaspenClient remembering each plan/scenario basis from responses."""

    def __init__(self, client, headers, thread_id):
        self.client = client
        self.headers = headers
        self.thread_id = thread_id
        self.plan_basis = None
        self.scenarios = {}

    def _plan(self, response):
        assert response.status_code == 200, response.get_json()
        body = response.get_json()
        self.plan_basis = (body.get("project_wbs") or {}).get("updated_at") or self.plan_basis
        return body["project_wbs"]

    def load_plan(self):
        return self._plan(
            self.client.get(
                f"/api/v1/strategy/threads/{self.thread_id}/wbs?scorecard_id=planner-card",
                headers=self.headers,
            )
        )

    def save_plan(self, plan):
        return self._plan(
            self.client.put(
                f"/api/v1/strategy/threads/{self.thread_id}/wbs",
                headers=self.headers,
                json={
                    "scorecard_id": "planner-card",
                    "project_wbs": plan,
                    "expected_updated_at": self.plan_basis,
                },
            )
        )

    def start_date(self, date):
        return self._plan(
            self.client.post(
                f"/api/v1/strategy/threads/{self.thread_id}/wbs/start-date",
                headers=self.headers,
                json={
                    "scorecard_id": "planner-card",
                    "start_date": date,
                    "expected_updated_at": self.plan_basis,
                },
            )
        )

    def chat(self, text):
        response = self.client.post(
            f"/api/v1/ai-agent/threads/{self.thread_id}/messages",
            headers=self.headers,
            json={"messages": [{"role": "user", "content": text}]},
        )
        assert response.status_code == 200, response.get_json()

    def take_scenario(self, scenario_id, response, *keys):
        assert response.status_code in (200, 201), response.get_json()
        body = response.get_json()
        for key in keys:
            if body.get(key):
                self.scenarios[scenario_id] = body[key]
                break
        return body


def test_plan_lifecycle_sequence(
    client,
    db,
    test_user,
    auth_headers,
    monkeypatch,
    inline_plan_jobs,
    scripted_plan_provider,
):
    thread_id = "probe-seq1"
    _seed(test_user, db, thread_id)
    mock_accounting(monkeypatch)
    scripted_plan_provider(_ai_plan())
    job_id = _build(client, auth_headers, thread_id).get_json()["job_id"]
    assert _status(client, auth_headers, thread_id, job_id)["status"] == "done"

    browser = Browser(client, auth_headers, thread_id)
    held = browser.load_plan()
    before_edits = copy.deepcopy(held["tasks"])
    held["tasks"][0]["title"] = "Edit 1"
    browser.save_plan(held)
    held["tasks"][1]["title"] = "Edit 2"
    browser.save_plan(held)
    after_start_date = browser.start_date("2027-01-04")
    held = after_start_date
    browser.chat("Keep going on the plan.")
    title_before_third_edit = held["tasks"][2]["title"]
    held["tasks"][2]["title"] = "Edit 3"
    browser.save_plan(held)
    undo = copy.deepcopy(held)
    undo["tasks"][2]["title"] = title_before_third_edit
    final = browser.save_plan(undo)

    titles = [task["title"] for task in final["tasks"]]
    assert titles[0] == "Edit 1"
    assert titles[1] == "Edit 2"
    assert titles[2] == title_before_third_edit
    assert final["tasks"][0].get("start_date") == after_start_date["tasks"][0].get("start_date")
    assert len(final["tasks"]) == len(before_edits)


def test_two_tabs_conflict_then_reload(
    client,
    db,
    test_user,
    auth_headers,
    monkeypatch,
    inline_plan_jobs,
    scripted_plan_provider,
):
    thread_id = "probe-seq3"
    _seed(test_user, db, thread_id)
    mock_accounting(monkeypatch)
    scripted_plan_provider(_ai_plan())
    job_id = _build(client, auth_headers, thread_id).get_json()["job_id"]
    _status(client, auth_headers, thread_id, job_id)

    first_tab = Browser(client, auth_headers, thread_id)
    second_tab = Browser(client, auth_headers, thread_id)
    first_plan = first_tab.load_plan()
    second_plan = second_tab.load_plan()
    first_plan["tasks"][0]["title"] = "Tab A"
    first_tab.save_plan(first_plan)
    second_plan["tasks"][0]["title"] = "Tab B"
    response = client.put(
        f"/api/v1/strategy/threads/{thread_id}/wbs",
        headers=auth_headers,
        json={
            "scorecard_id": "planner-card",
            "project_wbs": second_plan,
            "expected_updated_at": second_tab.plan_basis,
        },
    )
    assert response.status_code == 409
    assert response.get_json()["error"] == CONFLICT
    assert second_tab.load_plan()["tasks"][0]["title"] == "Tab A"
    second_plan = second_tab.load_plan()
    second_plan["tasks"][1]["title"] = "Tab B after reload"
    assert second_tab.save_plan(second_plan)["tasks"][0]["title"] == "Tab A"


def test_scenario_lifecycle_sequence(client, db, test_user, auth_headers):
    thread_id = "probe-seq5"
    _seed(test_user, db, thread_id)
    browser = Browser(client, auth_headers, thread_id)
    created = browser.take_scenario(
        "new",
        client.post(
            f"/api/v1/strategy/threads/{thread_id}/scenarios",
            headers=auth_headers,
            json={"label": "S1", "deltas": {}, "baseline": CARD},
        ),
        "updated_at",
    )
    scenario_id = created["scenario_id"]
    browser.scenarios[scenario_id] = browser.scenarios.pop("new")

    for label in ("S1 v2", "S1 v3"):
        browser.take_scenario(
            scenario_id,
            client.patch(
                f"/api/v1/strategy/scenarios/{scenario_id}?thread_id={thread_id}",
                headers=auth_headers,
                json={
                    "label": label,
                    "deltas": {},
                    "expected_updated_at": browser.scenarios[scenario_id],
                },
            ),
            "updated_at",
        )
    browser.take_scenario(
        scenario_id,
        client.post(
            f"/api/v1/strategy/scenarios/{scenario_id}/apply?thread_id={thread_id}",
            headers=auth_headers,
            json={"expected_updated_at": browser.scenarios[scenario_id]},
        ),
        "scenario_updated_at",
    )
    browser.take_scenario(
        scenario_id,
        client.post(
            f"/api/v1/strategy/scenarios/{scenario_id}/adopt?thread_id={thread_id}",
            headers=auth_headers,
            json={
                "thread_id": thread_id,
                "expected_updated_at": browser.scenarios[scenario_id],
            },
        ),
        "scenario_updated_at",
    )
    row = UserSession.query.filter_by(session_id=thread_id).one()
    response = client.patch(
        f"/api/v1/strategy/threads/{thread_id}",
        headers=auth_headers,
        json={"name": "Renamed", "base_revision": row.revision},
    )
    assert response.status_code == 200, response.get_json()
    last = client.patch(
        f"/api/v1/strategy/scenarios/{scenario_id}?thread_id={thread_id}",
        headers=auth_headers,
        json={
            "label": "S1 after rename",
            "deltas": {},
            "expected_updated_at": browser.scenarios[scenario_id],
        },
    )
    assert last.status_code == 200, last.get_json()
    scenarios = load_scenarios_data(test_user.id)[thread_id]["scenarios"]
    assert len(scenarios) == 1, list(scenarios)


@pytest.mark.parametrize("operation", ["delete_score", "adopt"])
def test_lost_race_is_all_or_nothing(
    client,
    db,
    test_user,
    auth_headers,
    monkeypatch,
    operation,
):
    thread_id = f"probe-seq6-{operation}"
    _seed(test_user, db, thread_id)
    save_project_scenarios_data(
        test_user.id,
        thread_id,
        {
            "baseline": CARD,
            "scenarios": {
                "planner-card": {
                    "scenario_id": "planner-card",
                    "label": "S",
                    "deltas": {},
                    "updated_at": "basis",
                    "result": CARD,
                }
            },
        },
    )
    db.session.expire_all()
    before = UserSession.query.filter_by(session_id=thread_id).one()
    before_payload = copy.deepcopy(before.payload)
    before_scenarios = copy.deepcopy(before.scenarios_json)
    monkeypatch.setattr(store, "_compare_and_swap", lambda *args, **kwargs: 0)

    if operation == "delete_score":
        response = client.delete(
            f"/api/v1/strategy/scores/{thread_id}/planner-card",
            headers=auth_headers,
        )
    else:
        response = client.post(
            f"/api/v1/strategy/scenarios/planner-card/adopt?thread_id={thread_id}",
            headers=auth_headers,
            json={"thread_id": thread_id, "expected_updated_at": "basis"},
        )

    db.session.expire_all()
    after = UserSession.query.filter_by(session_id=thread_id).one()
    assert response.status_code == 409, (response.status_code, response.get_json())
    assert after.payload == before_payload
    assert after.scenarios_json == before_scenarios
