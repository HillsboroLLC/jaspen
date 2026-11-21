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
    """Both requests read the project, then meet before either writes.

    Before the P3 remediation the two met inside the compare-and-swap. Every
    project writer now locks the row first (session_access.lock_project_row),
    so two transactions can no longer both be past the lock; they meet right
    before it instead, each holding the same stale basis, and then take turns.
    """
    import app.routes.sessions as sessions_mod
    import app.scenarios_store as scenarios_store

    originals = {
        sessions_mod: sessions_mod.lock_project_row,
        scenarios_store: scenarios_store.lock_project_row,
    }
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    arrivals = []
    seen = set()

    def make(original):
        def overlapped(row):
            me = threading.get_ident()
            with lock:
                first = me not in seen and len(seen) < 2
                if first:
                    seen.add(me)
                    arrivals.append(me)
            if first:
                barrier.wait(timeout=10)
            return original(row)
        return overlapped

    for module, original in originals.items():
        monkeypatch.setattr(module, "lock_project_row", make(original))
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda request: request(), requests))
    assert len(arrivals) >= 2
    assert len(set(arrivals[:2])) == 2
    for module, original in originals.items():
        monkeypatch.setattr(module, "lock_project_row", original)
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
    user_id = str(test_user.id)
    tid = "postgres-different-plans"
    _seed(test_user, db, tid)
    save_project_scenarios_data(user_id, tid, {
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
    stored = load_scenarios_data(user_id)[tid]
    assert stored["wbs_by_scorecard"]["plan-a"]["tasks"][0]["title"] == "new-plan-a"
    assert stored["wbs_by_scorecard"]["plan-b"]["tasks"][0]["title"] == "new-plan-b"


def test_different_scenario_delta_edits_save_without_false_conflicts(
    app, db, test_user, auth_headers, monkeypatch,
):
    user_id = str(test_user.id)
    tid = "postgres-different-scenario-deltas"
    _seed(test_user, db, tid)
    save_project_scenarios_data(user_id, tid, {
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
    stored = load_scenarios_data(user_id)[tid]
    assert stored["scenarios"]["scenario-a"]["deltas"] == {"revenue": 10}
    assert stored["scenarios"]["scenario-b"]["deltas"] == {"revenue": 20}


def test_different_scenario_label_edits_preserve_each_winner(
    app, db, test_user, auth_headers, monkeypatch,
):
    user_id = str(test_user.id)
    tid = "postgres-different-scenario-labels"
    _seed(test_user, db, tid)
    save_project_scenarios_data(user_id, tid, {
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

    # P3 closes backlog 14: the loser of the compare-and-swap re-runs its
    # whole unit on fresh data, so both edits are saved.
    assert [status for status, _body in results] == [200, 200], results

    app_db.session.remove()
    stored = load_scenarios_data(user_id)[tid]
    for key in keys:
        assert stored["scenarios"][key]["label"] == f"new-{key}"


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


# ---------------------------------------------------------------------------
# P3: natural-timing rounds (no forced interleaving), PostgreSQL only.
# Acceptance: zero false conflicts across 30 rounds for different objects, and
# exactly one winner for the same object.
# ---------------------------------------------------------------------------

NATURAL_ROUNDS = 30


def _concurrently(requests):
    with ThreadPoolExecutor(max_workers=len(requests)) as executor:
        return list(executor.map(lambda request: request(), requests))


def test_p3_natural_timing_different_objects_have_no_false_conflicts(
    app, db, test_user, auth_headers,
):
    """Each round sends, at the same moment, edits to different objects of one
    project across the write families: two scorecard renames, a chat note and
    a project rename, and two scenario edits. Every edit must be saved."""
    from app.routes.sessions import load_user_sessions

    user_id = str(test_user.id)
    tid = "postgres-p3-natural"
    card_a = {**CARD, "id": "card-a", "project_name": "Option A"}
    card_b = {**CARD, "id": "card-b", "project_name": "Option B"}
    _seed(test_user, db, tid, [CARD, card_a, card_b])
    save_project_scenarios_data(user_id, tid, {
        "scenarios": {
            "scenario-a": {"scenario_id": "scenario-a", "label": "a-0", "deltas": {}, "updated_at": "a-0"},
            "scenario-b": {"scenario_id": "scenario-b", "label": "b-0", "deltas": {}, "updated_at": "b-0"},
        },
    })
    app_db.session.remove()
    # The seeded snapshots have the legacy shape (no label or createdAt). The
    # first rename normalizes every item and fills those defaults; do it once,
    # alone, as the first real edit of such a project would. (Two FIRST edits
    # of a legacy list at the same moment both fill the defaults differently
    # and one is refused once; recorded as a P3 residual.)
    with app.test_client() as warm_up:
        assert warm_up.patch(
            f"/api/v1/strategy/threads/{tid}/scorecard-snapshots/card-a",
            headers=auth_headers, json={"label": "A round 0"},
        ).status_code == 200
    app_db.session.remove()

    false_conflicts = []
    for n in range(1, NATURAL_ROUNDS + 1):
        scenarios = load_scenarios_data(user_id)[tid]["scenarios"]
        app_db.session.remove()
        requests = [
            _request(app, auth_headers, "PATCH",
                     f"/api/v1/strategy/threads/{tid}/scorecard-snapshots/card-a",
                     {"label": f"A round {n}"}),
            _request(app, auth_headers, "PATCH",
                     f"/api/v1/strategy/threads/{tid}/scorecard-snapshots/card-b",
                     {"label": f"B round {n}"}),
            _request(app, auth_headers, "POST", f"/api/v1/ai-agent/threads/{tid}/messages",
                     {"messages": [{"role": "user", "content": f"note {n}"}]}),
            _request(app, auth_headers, "PATCH", f"/api/v1/ai-agent/threads/{tid}",
                     {"name": f"Project round {n}"}),
            _request(app, auth_headers, "PATCH", f"/api/v1/strategy/scenarios/scenario-a?thread_id={tid}",
                     {"label": f"a-{n}", "expected_updated_at": scenarios["scenario-a"]["updated_at"]}),
            _request(app, auth_headers, "PATCH", f"/api/v1/strategy/scenarios/scenario-b?thread_id={tid}",
                     {"deltas": {"revenue": n}, "expected_updated_at": scenarios["scenario-b"]["updated_at"]}),
        ]
        results = _concurrently(requests)
        statuses = [status for status, _body in results]
        if statuses != [200] * len(requests):
            false_conflicts.append((n, statuses, [b for s, b in results if s != 200][:1]))
            continue

        app_db.session.remove()
        session = load_user_sessions(user_id)[tid]
        labels = {
            s.get("id"): s.get("label")
            for s in (session.get("result") or {}).get("scorecard_snapshots") or []
        }
        stored = load_scenarios_data(user_id)[tid]["scenarios"]
        app_db.session.remove()
        assert labels.get("card-a") == f"A round {n}", (n, labels)
        assert labels.get("card-b") == f"B round {n}", (n, labels)
        assert session["name"] == f"Project round {n}"
        assert any(m.get("content") == f"note {n}" for m in session.get("chat_history") or [])
        assert stored["scenario-a"]["label"] == f"a-{n}"
        assert stored["scenario-b"]["deltas"] == {"revenue": n}

    assert false_conflicts == [], false_conflicts


def test_p3_natural_timing_same_object_is_never_silently_overwritten(
    app, db, test_user, auth_headers,
):
    """Two people rename the same scorecard at the same moment. When the two
    overlap, one is refused with the approved sentence; when they happen to run
    one after the other, the later is a new edit on fresh data. Either way the
    stored name is one a successful request wrote, never a lost write."""
    from app.routes.sessions import load_user_sessions

    user_id = str(test_user.id)
    tid = "postgres-p3-same-object"
    card_a = {**CARD, "id": "card-a", "project_name": "Option A"}
    _seed(test_user, db, tid, [CARD, card_a])
    app_db.session.remove()

    refusals = 0
    for n in range(1, NATURAL_ROUNDS + 1):
        requests = [
            _request(app, auth_headers, "PATCH",
                     f"/api/v1/strategy/threads/{tid}/scorecard-snapshots/card-a",
                     {"label": f"round {n} {writer}"})
            for writer in ("x", "y")
        ]
        results = _concurrently(requests)
        winners = {f"round {n} {w}" for w, (status, _b) in zip(("x", "y"), results) if status == 200}
        assert winners, (n, results)
        for status, body in results:
            assert status in {200, 409}, (n, results)
            if status == 409:
                refusals += 1
                assert body["code"] == "revision_conflict" and body["error"] == CONFLICT, body
        app_db.session.remove()
        session = load_user_sessions(user_id)[tid]
        app_db.session.remove()
        labels = {
            s.get("id"): s.get("label")
            for s in (session.get("result") or {}).get("scorecard_snapshots") or []
        }
        assert labels.get("card-a") in winners, (n, labels, results)
    print(f"same-object natural rounds: {NATURAL_ROUNDS}, refusals: {refusals}")


# ---------------------------------------------------------------------------
# Acceptance remediation D1: writers take turns on the project row
# ---------------------------------------------------------------------------
#
# Real transactions on separate connections. One writer is paused while it
# holds the project lock; the other must wait (it cannot commit inside the
# window), and when it runs it builds on the first writer's committed work.

from tests.journeys.test_p3_one_project_writes import team_project  # noqa: E402,F401

HOLD_SECONDS = 0.5


def _hold_inside(monkeypatch, module, name, *, after_original=False):
    """Pause the first call of module.name while its transaction holds the lock."""
    original = getattr(module, name)
    held, release = threading.Event(), threading.Event()
    state = {"fired": False}
    guard = threading.Lock()

    def paused(*args, **kwargs):
        with guard:
            first = not state["fired"]
            state["fired"] = True
        if first and not after_original:
            held.set()
            assert release.wait(10)
        result = original(*args, **kwargs)
        if first and after_original:
            held.set()
            assert release.wait(10)
        return result

    monkeypatch.setattr(module, name, paused)
    return held, release


def _in_thread(target):
    box = {}

    def run():
        try:
            box["result"] = target()
        except Exception as exc:  # noqa: BLE001 - reported to the test
            box["error"] = exc
        finally:
            app_db.session.remove()

    thread = threading.Thread(target=run)
    thread.start()
    return thread, box


def _owner_saves_note(app, owner_id):
    from app.routes.sessions import load_user_sessions, save_project_session

    def save():
        with app.app_context():
            sessions = load_user_sessions(owner_id)
            sessions["team-p3"]["notes"] = {"owner": "note"}
            return save_project_session(owner_id, "team-p3", sessions["team-p3"])
    return save


def _route(app, method, path, headers, body):
    def call():
        with app.test_client() as client:
            response = client.open(path, method=method, headers=headers, json=body)
            return response.status_code
    return call


def _stored_team_project():
    app_db.session.remove()
    row = UserSession.query.filter_by(session_id="team-p3").one()
    app_db.session.remove()
    return row


def test_d1_comment_during_a_save_waits_and_is_kept(app, db, team_project, monkeypatch):
    import app.routes.sessions as sessions_mod

    owner, _member, _org, headers = team_project
    owner_id = str(owner.id)
    app_db.session.remove()
    held, release = _hold_inside(monkeypatch, sessions_mod, "_apply_to_current")
    saver, saved = _in_thread(_owner_saves_note(app, owner_id))
    assert held.wait(10)
    commenter, commented = _in_thread(_route(
        app, "POST", "/api/v1/team/projects/team-p3/comments", headers["member"], {"body": "Looks good"}))
    commenter.join(HOLD_SECONDS)
    assert commenter.is_alive(), "the comment committed inside the save's locked window"
    release.set()
    saver.join(10)
    commenter.join(10)
    assert saved == {"result": True}, saved
    assert commented == {"result": 201}, commented
    row = _stored_team_project()
    assert row.payload["notes"] == {"owner": "note"}
    assert [c["body"] for c in row.payload.get("comments") or []] == ["Looks good"]


def test_d1_save_during_a_comment_waits_and_keeps_it(app, db, team_project, monkeypatch):
    import app.routes.team as team_mod

    owner, _member, _org, headers = team_project
    owner_id = str(owner.id)
    app_db.session.remove()
    held, release = _hold_inside(monkeypatch, team_mod, "_locked_payload", after_original=True)
    commenter, commented = _in_thread(_route(
        app, "POST", "/api/v1/team/projects/team-p3/comments", headers["member"], {"body": "First"}))
    assert held.wait(10)
    saver, saved = _in_thread(_owner_saves_note(app, owner_id))
    saver.join(HOLD_SECONDS)
    assert saver.is_alive(), "the save committed inside the comment's locked window"
    release.set()
    commenter.join(10)
    saver.join(10)
    assert commented == {"result": 201}, commented
    assert saved == {"result": True}, saved
    row = _stored_team_project()
    assert row.payload["notes"] == {"owner": "note"}
    assert [c["body"] for c in row.payload.get("comments") or []] == ["First"]


def test_d1_unshare_during_an_unrelated_save_stays_unshared(app, db, team_project, monkeypatch):
    import app.routes.sessions as sessions_mod

    owner, _member, _org, headers = team_project
    owner_id = str(owner.id)
    app_db.session.remove()
    held, release = _hold_inside(monkeypatch, sessions_mod, "_apply_to_current")
    saver, saved = _in_thread(_owner_saves_note(app, owner_id))
    assert held.wait(10)
    sharer, shared = _in_thread(_route(
        app, "PATCH", "/api/v1/team/projects/team-p3/sharing", headers["owner"], {"visibility": "private"}))
    sharer.join(HOLD_SECONDS)
    assert sharer.is_alive(), "the unshare committed inside the save's locked window"
    release.set()
    saver.join(10)
    sharer.join(10)
    assert saved == {"result": True}, saved
    assert shared == {"result": 200}, shared
    row = _stored_team_project()
    assert (row.visibility, row.payload.get("visibility")) == ("private", "private")
    assert row.payload["notes"] == {"owner": "note"}


def test_d1_member_save_behind_an_unshare_is_refused(app, db, team_project, monkeypatch):
    import app.routes.team as team_mod
    from app.routes.sessions import load_sessions_for_thread, save_project_session
    from app.session_access import SessionAccessError

    owner, member, _org, headers = team_project
    member_id = str(member.id)
    app_db.session.remove()
    loaded, go = threading.Event(), threading.Event()

    def member_saves():
        with app.app_context():
            from app.models import User
            sessions = load_sessions_for_thread(app_db.session.get(User, member_id), "team-p3")
            sessions["team-p3"]["notes"] = {"member": "note"}
            loaded.set()
            assert go.wait(10)
            return save_project_session(member_id, "team-p3", sessions["team-p3"])

    held, release = _hold_inside(monkeypatch, team_mod, "_locked_payload", after_original=True)
    saver, saved = _in_thread(member_saves)
    assert loaded.wait(10)
    sharer, shared = _in_thread(_route(
        app, "PATCH", "/api/v1/team/projects/team-p3/sharing", headers["owner"], {"visibility": "private"}))
    assert held.wait(10)
    go.set()
    saver.join(HOLD_SECONDS)
    assert saver.is_alive(), "the member's save did not wait for the unshare"
    release.set()
    sharer.join(10)
    saver.join(10)
    assert shared == {"result": 200}, shared
    assert isinstance(saved.get("error"), SessionAccessError), saved
    row = _stored_team_project()
    assert row.visibility == "private"
    assert "member" not in (row.payload.get("notes") or {})


# ---------------------------------------------------------------------------
# Acceptance remediation D2: legacy-shaped first edits, no warm-up
# ---------------------------------------------------------------------------

LEGACY_ROUNDS = 10


def test_d2_concurrent_first_edits_of_legacy_snapshots_never_lose_an_edit(
    app, db, test_user, auth_headers,
):
    """Fresh legacy-shaped projects (snapshots without label or createdAt),
    each first edited by two renames of different scorecards at the same
    moment. Every rename that is answered 200 is stored; a rename that is not
    stored was refused with the approved sentence."""
    from app.routes.sessions import load_user_sessions

    user_id = str(test_user.id)
    refusals = 0
    for n in range(LEGACY_ROUNDS):
        tid = f"postgres-d2-legacy-{n}"
        card_a = {**CARD, "id": "card-a", "project_name": "Option A"}
        card_b = {**CARD, "id": "card-b", "project_name": "Option B"}
        from app.models import User
        _seed(app_db.session.get(User, user_id), db, tid, [CARD, card_a, card_b])
        app_db.session.remove()
        requests = [
            _request(app, auth_headers, "PATCH",
                     f"/api/v1/strategy/threads/{tid}/scorecard-snapshots/{card}",
                     {"label": f"{card} first {n}"})
            for card in ("card-a", "card-b")
        ]
        results = _concurrently(requests)
        app_db.session.remove()
        session = load_user_sessions(user_id)[tid]
        app_db.session.remove()
        labels = {
            s.get("id"): s.get("label")
            for s in (session.get("result") or {}).get("scorecard_snapshots") or []
        }
        for card, (status, body) in zip(("card-a", "card-b"), results):
            assert status in {200, 409}, (n, results)
            if status == 200:
                assert labels.get(card) == f"{card} first {n}", (n, card, labels, results)
            else:
                refusals += 1
                assert body["code"] == "revision_conflict" and body["error"] == CONFLICT, body
    print(f"legacy first-edit rounds: {LEGACY_ROUNDS}, refusals: {refusals}")


def test_p3_natural_timing_same_scenario_from_one_basis_has_exactly_one_winner(
    app, db, test_user, auth_headers,
):
    """Two edits of the same scenario sent at the same moment from the same
    basis (natural timing, nothing forced). However they interleave, one is
    saved and the other refused: never both answered 200 with one of them lost."""
    user_id = str(test_user.id)
    tid = "postgres-p3-same-scenario"
    _seed(test_user, db, tid)
    save_project_scenarios_data(user_id, tid, {
        "scenarios": {"scenario": {"scenario_id": "scenario", "label": "s-0", "deltas": {}, "updated_at": "s-0"}},
    })
    app_db.session.remove()
    for n in range(1, NATURAL_ROUNDS + 1):
        basis = load_scenarios_data(user_id)[tid]["scenarios"]["scenario"]["updated_at"]
        app_db.session.remove()
        requests = [
            _request(app, auth_headers, "PATCH", f"/api/v1/strategy/scenarios/scenario?thread_id={tid}",
                     {"label": f"s-{n}-{writer}", "expected_updated_at": basis})
            for writer in ("x", "y")
        ]
        results = _concurrently(requests)
        assert sorted(status for status, _b in results) == [200, 409], (n, results)
        winner = next(w for w, (status, _b) in zip(("x", "y"), results) if status == 200)
        app_db.session.remove()
        stored = load_scenarios_data(user_id)[tid]["scenarios"]["scenario"]["label"]
        app_db.session.remove()
        assert stored == f"s-{n}-{winner}", (n, stored, results)
