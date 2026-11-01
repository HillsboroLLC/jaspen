import copy
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import db as app_db
from app.models import Scorecard, UserSession
from app.scenarios_store import load_scenarios_data, save_project_scenarios_data
from tests.journeys.test_b1_plan_interleavings import CARD, _seed


CONFLICT = "This project has newer changes. Reload to get the latest version. Your changes weren't saved."


def _overlap_compare_and_swap(monkeypatch, requests):
    import app.scenarios_store as scenarios_store

    original = scenarios_store._compare_and_swap
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    arrivals = []
    count = 0

    def overlapped(*args, **kwargs):
        nonlocal count
        with lock:
            count += 1
            call_number = count
            arrivals.append(threading.get_ident())
        if call_number <= 2:
            barrier.wait(timeout=10)
        return original(*args, **kwargs)

    monkeypatch.setattr(scenarios_store, "_compare_and_swap", overlapped)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda request: request(), requests))
    assert len(arrivals) >= 2
    assert len(set(arrivals[:2])) == 2
    monkeypatch.setattr(scenarios_store, "_compare_and_swap", original)
    return results


def _request(app, auth_headers, method, path, payload):
    def call():
        with app.test_client() as client:
            response = client.open(path, method=method, headers=auth_headers, json=payload)
            return response.status_code, response.get_json()

    return call


@pytest.mark.parametrize("object_kind", ["plan", "scenario"])
def test_same_object_concurrent_writes_have_one_winner_for_twenty_rounds(
    app, db, test_user, auth_headers, monkeypatch, object_kind,
):
    tid = f"postgres-same-{object_kind}"
    _seed(test_user, db, tid)

    if object_kind == "plan":
        initial = {
            "scorecard_id": "planner-card",
            "tasks": [{"id": "task", "title": "initial", "status": "todo"}],
        }
        with app.test_client() as client:
            response = client.patch(
                f"/api/v1/strategy/threads/{tid}/wbs",
                headers=auth_headers,
                json={"scorecard_id": "planner-card", "project_wbs": initial},
            )
        assert response.status_code == 200, response.get_json()
    else:
        save_project_scenarios_data(test_user.id, tid, {
            "baseline": CARD,
            "baseline_inputs": {},
            "scenarios": {
                "scenario": {
                    "scenario_id": "scenario",
                    "label": "initial",
                    "deltas": {},
                    "result": CARD,
                    "updated_at": "initial-basis",
                },
            },
        })

    for round_number in range(20):
        if object_kind == "plan":
            current = load_scenarios_data(test_user.id)[tid]["wbs_by_scorecard"]["planner-card"]
            bodies = []
            for writer in ("a", "b"):
                plan = copy.deepcopy(current)
                plan["tasks"][0]["title"] = f"round-{round_number}-{writer}"
                bodies.append({"scorecard_id": "planner-card", "project_wbs": plan})
            path = f"/api/v1/strategy/threads/{tid}/wbs"
            requests = [
                _request(app, auth_headers, "PATCH", path, body) for body in bodies
            ]
        else:
            current = load_scenarios_data(test_user.id)[tid]["scenarios"]["scenario"]
            path = f"/api/v1/strategy/scenarios/scenario?thread_id={tid}"
            requests = [
                _request(app, auth_headers, "PATCH", path, {
                    "label": f"round-{round_number}-{writer}",
                    "expected_updated_at": current["updated_at"],
                })
                for writer in ("a", "b")
            ]

        results = _overlap_compare_and_swap(monkeypatch, requests)
        assert sorted(status for status, _body in results) == [200, 409], results
        winner = next(body for status, body in results if status == 200)
        loser = next(body for status, body in results if status == 409)
        assert loser["code"] == "revision_conflict"

        app_db.session.remove()
        stored = load_scenarios_data(test_user.id)[tid]
        if object_kind == "plan":
            title = stored["wbs_by_scorecard"]["planner-card"]["tasks"][0]["title"]
            assert title == winner["project_wbs"]["tasks"][0]["title"]
        else:
            assert stored["scenarios"]["scenario"]["label"] == winner["label"]


def test_different_plans_save_without_false_conflicts(
    app, db, test_user, auth_headers, monkeypatch,
):
    tid = "postgres-different-plans"
    _seed(test_user, db, tid)
    save_project_scenarios_data(test_user.id, tid, {
        "wbs_by_scorecard": {
            "plan-a": {"scorecard_id": "plan-a", "tasks": [{"id": "a", "title": "old-a"}]},
            "plan-b": {"scorecard_id": "plan-b", "tasks": [{"id": "b", "title": "old-b"}]},
        },
    })

    plan_requests = [
        _request(app, auth_headers, "PATCH", f"/api/v1/strategy/threads/{tid}/wbs", {
            "scorecard_id": key,
            "project_wbs": {"scorecard_id": key, "tasks": [{"id": key, "title": f"new-{key}"}]},
        })
        for key in ("plan-a", "plan-b")
    ]
    plan_results = _overlap_compare_and_swap(monkeypatch, plan_requests)
    assert [status for status, _body in plan_results] == [200, 200], plan_results

    app_db.session.remove()
    stored = load_scenarios_data(test_user.id)[tid]
    assert stored["wbs_by_scorecard"]["plan-a"]["tasks"][0]["title"] == "new-plan-a"
    assert stored["wbs_by_scorecard"]["plan-b"]["tasks"][0]["title"] == "new-plan-b"


def test_different_scenario_delta_edits_save_without_false_conflicts(
    app, db, test_user, auth_headers, monkeypatch,
):
    tid = "postgres-different-scenario-deltas"
    _seed(test_user, db, tid)
    save_project_scenarios_data(test_user.id, tid, {
        "scenarios": {
            "scenario-a": {"scenario_id": "scenario-a", "label": "old-a", "deltas": {}, "updated_at": "basis-a"},
            "scenario-b": {"scenario_id": "scenario-b", "label": "old-b", "deltas": {}, "updated_at": "basis-b"},
        },
    })

    scenario_requests = [
        _request(app, auth_headers, "PATCH", f"/api/v1/strategy/scenarios/{key}?thread_id={tid}", {
            "deltas": {"revenue": value}, "expected_updated_at": basis,
        })
        for key, basis, value in (
            ("scenario-a", "basis-a", 10), ("scenario-b", "basis-b", 20),
        )
    ]
    scenario_results = _overlap_compare_and_swap(monkeypatch, scenario_requests)
    assert [status for status, _body in scenario_results] == [200, 200], scenario_results

    app_db.session.remove()
    stored = load_scenarios_data(test_user.id)[tid]
    assert stored["scenarios"]["scenario-a"]["deltas"] == {"revenue": 10}
    assert stored["scenarios"]["scenario-b"]["deltas"] == {"revenue": 20}


def test_different_scenario_label_edits_preserve_each_winner(
    app, db, test_user, auth_headers, monkeypatch,
):
    tid = "postgres-different-scenario-labels"
    _seed(test_user, db, tid)
    save_project_scenarios_data(test_user.id, tid, {
        "scenarios": {
            "scenario-a": {"scenario_id": "scenario-a", "label": "old-a", "updated_at": "basis-a"},
            "scenario-b": {"scenario_id": "scenario-b", "label": "old-b", "updated_at": "basis-b"},
        },
    })

    keys = ("scenario-a", "scenario-b")
    requests = [
        _request(app, auth_headers, "PATCH", f"/api/v1/strategy/scenarios/{key}?thread_id={tid}", {
            "label": f"new-{key}", "expected_updated_at": basis,
        })
        for key, basis in zip(keys, ("basis-a", "basis-b"))
    ]
    results = _overlap_compare_and_swap(monkeypatch, requests)

    # Awaiting Lydia's decision recorded in B1_REVIEW.md; assert only the safe invariant.
    assert any(status == 200 for status, _body in results), results
    for status, body in results:
        assert status in {200, 409}, results
        if status == 409:
            assert body["code"] == "revision_conflict"
            assert body["error"] == CONFLICT

    app_db.session.remove()
    stored = load_scenarios_data(test_user.id)[tid]
    for key, (status, _body) in zip(keys, results):
        expected = f"new-{key}" if status == 200 else f"old-{key[-1]}"
        assert stored["scenarios"][key]["label"] == expected


@pytest.mark.parametrize("operation", ["rename", "delete_score", "adopt_scenario"])
def test_compound_writes_rollback_both_halves_after_lost_compare_and_swap(
    client, db, test_user, auth_headers, monkeypatch, operation,
):
    import app.scenarios_store as scenarios_store

    tid = f"postgres-atomic-{operation}"
    _seed(test_user, db, tid)
    scenario_id = "planner-card" if operation == "delete_score" else "scenario"
    save_project_scenarios_data(test_user.id, tid, {
        "baseline": {**CARD, "project_name": "Old name"},
        "baseline_inputs": {},
        "adopted_scenario_id": None,
        "scenarios": {
            scenario_id: {
                "scenario_id": scenario_id,
                "label": "Original scenario",
                "deltas": {},
                "result": CARD,
                "updated_at": "basis",
            },
        },
    })
    before = UserSession.query.filter_by(session_id=tid).one()
    before_payload = copy.deepcopy(before.payload)
    before_scenarios = copy.deepcopy(before.scenarios_json)
    before_revision = before.revision
    monkeypatch.setattr(scenarios_store, "_compare_and_swap", lambda *_args, **_kwargs: 0)

    if operation == "rename":
        response = client.patch(
            f"/api/v1/strategy/threads/{tid}", headers=auth_headers,
            json={"name": "Unsaved name", "base_revision": before_revision},
        )
    elif operation == "delete_score":
        response = client.delete(
            f"/api/v1/strategy/scores/{tid}/planner-card", headers=auth_headers,
        )
    else:
        response = client.post(
            f"/api/v1/strategy/scenarios/scenario/adopt", headers=auth_headers,
            json={"thread_id": tid, "expected_updated_at": "basis"},
        )

    assert response.status_code == 409, response.get_json()
    assert response.get_json()["code"] == "revision_conflict"
    db.session.remove()
    after = UserSession.query.filter_by(session_id=tid).one()
    assert after.payload == before_payload
    assert after.scenarios_json == before_scenarios
    assert after.revision == before_revision
    if operation == "delete_score":
        assert Scorecard.query.filter_by(thread_id=tid, id="planner-card").one().archived_at is None


def test_legacy_plan_and_scenario_without_updated_at_can_each_be_edited_twice(
    client, db, test_user, auth_headers,
):
    tid = "postgres-legacy-no-updated-at"
    _seed(test_user, db, tid)
    save_project_scenarios_data(test_user.id, tid, {
        "wbs_by_scorecard": {
            "planner-card": {"scorecard_id": "planner-card", "tasks": [{"id": "task", "title": "old"}]},
        },
        "scenarios": {
            "scenario": {"scenario_id": "scenario", "label": "old", "deltas": {}},
        },
    })

    plan = {"scorecard_id": "planner-card", "tasks": [{"id": "task", "title": "first"}]}
    first_plan = client.patch(
        f"/api/v1/strategy/threads/{tid}/wbs", headers=auth_headers,
        json={"scorecard_id": "planner-card", "project_wbs": plan},
    )
    assert first_plan.status_code == 200, first_plan.get_json()
    plan = first_plan.get_json()["project_wbs"]
    plan["tasks"][0]["title"] = "second"
    second_plan = client.patch(
        f"/api/v1/strategy/threads/{tid}/wbs", headers=auth_headers,
        json={"scorecard_id": "planner-card", "project_wbs": plan},
    )
    assert second_plan.status_code == 200, second_plan.get_json()

    first_scenario = client.patch(
        f"/api/v1/strategy/scenarios/scenario?thread_id={tid}", headers=auth_headers,
        json={"label": "first"},
    )
    assert first_scenario.status_code == 200, first_scenario.get_json()
    second_scenario = client.patch(
        f"/api/v1/strategy/scenarios/scenario?thread_id={tid}", headers=auth_headers,
        json={"label": "second", "expected_updated_at": first_scenario.get_json()["updated_at"]},
    )
    assert second_scenario.status_code == 200, second_scenario.get_json()
