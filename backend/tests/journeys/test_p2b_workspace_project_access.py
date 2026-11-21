"""P2b: workspace and scoring routes follow the organization's project.

Every ``strategy.py`` route that takes a ``<thread_id>`` resolves the project
through the project access seam (``session_access``) and reads its content
from the organization's canonical row:

* owner and editor get the project's real content, or reach the route logic;
* a viewer reads, and is refused every write with 403;
* a creator who is now a viewer is treated exactly as a viewer;
* a member of another organization gets 404 on reads and changes nothing.

Assertions are on content (a marker stored in the project), not only status.
No provider is called: the routes that generate are given a stand-in model
that records whether it was reached.

Journeys (blueprint acceptance matrix): B2, B6 to B9, A4 to A8, C2, C3, I.
"""

import ast
import inspect
import json
import textwrap
import uuid

import pytest

from app import db as _db
from app.models import OrganizationMember, Scorecard, UserSession
from tests.journeys.test_conversation_turn_lifecycle import (  # noqa: F401 (fixture)
    _add_member,
    _headers,
    _mk_org,
    _mk_user,
    _settle_meter,
    solo,
)

MARKER = "MARKER-P2B-7Q"
KIT = "rfp_vendor_selection"
HIST = [
    {"role": "user", "content": f"Compare the vendors {MARKER}"},
    {"role": "assistant", "content": f"Here is the comparison {MARKER}"},
]
ACTORS = ["owner", "editor", "viewer", "creator-now-viewer", "other-org"]
READERS = {"owner", "editor", "viewer", "creator-now-viewer"}
WRITERS = {"owner", "editor"}


@pytest.fixture(autouse=True)
def _no_rate_limits():
    from app import limiter
    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


@pytest.fixture
def model_calls(monkeypatch):
    """Stand-in for every model entry point strategy.py uses. Records the call
    and stops the request there, so nothing is generated or charged."""
    from app.routes import strategy

    calls = []

    class _ModelReached(RuntimeError):
        pass

    def _reached(*_args, **_kwargs):
        calls.append(True)
        raise _ModelReached("stand-in model reached")

    for name in ("execute_customer_operation", "execute_customer_text_operation", "get_llm_client"):
        monkeypatch.setattr(strategy, name, _reached, raising=False)
    return calls


# --- Fixture project ---------------------------------------------------------

def _card(card_id, thread_id, name):
    return {
        "id": card_id, "analysis_id": card_id, "thread_id": thread_id,
        "project_name": name, "name": name, "label": name,
        "jaspen_score": 72, "overall_score": 72,
        "executive_summary": f"Summary {MARKER}",
        "attributes": {"note": {"value": MARKER, "source": "user"}},
        "display_overrides": {"title": f"Title {MARKER}"},
    }


def _seed_project(creator, org, thread_id):
    """One organization project with conversation, a scorecard (session
    result and native index row), a plan and a scenario, all carrying MARKER."""
    from app.routes.sessions import save_user_sessions
    from app.scenarios_store import save_project_scenarios_data
    from app.scorecards import upsert_scorecard

    base_id = f"{thread_id}-card"
    base = _card(base_id, thread_id, f"Vendor A {MARKER}")
    assert save_user_sessions(creator.id, {thread_id: {
        "session_id": thread_id, "user_id": creator.id, "name": f"Shared {MARKER}",
        "status": "completed", "organization_id": org.id, "visibility": "team",
        "chat_history": list(HIST),
        "decision_kit": KIT, "decision_kit_version": 1,
        "result": {**base, "_baseline_scorecard": dict(base), "scorecard_snapshots": [],
                   "selected_scorecard_id": base_id},
    }})
    upsert_scorecard(
        user_id=creator.id, thread_id=thread_id, payload=dict(base),
        organization_id=org.id, session_id=thread_id, source="native",
    )
    _db.session.commit()
    save_project_scenarios_data(creator.id, thread_id, {
        "baseline": dict(base),
        "scenarios": {"scn-1": {"scenario_id": "scn-1", "label": f"Scenario {MARKER}",
                                "created_at": "2026-11-01T00:00:00", "deltas": {}}},
        "project_wbs": {"name": f"Plan {MARKER}", "tasks": [], "phases": []},
        "workspace_chats": {"__execution__": [{"role": "user", "text": f"Plan chat {MARKER}"}]},
    })
    _db.session.expire_all()
    return base_id


@pytest.fixture
def team(app, db, solo):
    owner, org = solo["user"], solo["org"]

    def mk(label):
        return _mk_user(f"{label}-{uuid.uuid4().hex[:8]}@example.test")

    editor, viewer, demoted, outsider = mk("editor"), mk("viewer"), mk("demoted"), mk("outsider")
    _add_member(org, editor)
    _add_member(org, viewer, role="viewer")
    _add_member(org, demoted)
    _mk_org(outsider, f"Other{uuid.uuid4().hex[:6]}")
    _settle_meter(outsider)

    shared_card = _seed_project(owner, org, "t-shared")
    demoted_card = _seed_project(demoted, org, "t-demoted")
    membership = OrganizationMember.query.filter_by(
        organization_id=org.id, user_id=demoted.id,
    ).one()
    membership.role = "viewer"
    _db.session.commit()

    users = {"owner": owner, "editor": editor, "viewer": viewer,
             "creator-now-viewer": demoted, "other-org": outsider}
    projects = {name: ("t-demoted", demoted_card) if name == "creator-now-viewer"
                else ("t-shared", shared_card) for name in ACTORS}
    return {"org": org, "users": users, "projects": projects, "app": app}


def _project_state(thread_id):
    """Everything stored for this project id, for "nothing changed" checks."""
    _db.session.expire_all()
    rows = [
        (r.id, r.user_id, r.organization_id, int(r.revision or 1), r.last_edited_by_user_id,
         json.dumps(r.payload, sort_keys=True, default=str),
         json.dumps(r.scenarios_json, sort_keys=True, default=str), r.archived_at)
        for r in UserSession.query.filter_by(session_id=thread_id).order_by(UserSession.id).all()
    ]
    cards = [
        (c.id, c.user_id, c.organization_id, json.dumps(c.data, sort_keys=True, default=str),
         c.archived_at, c.execution_plan_ref)
        for c in Scorecard.query.filter_by(thread_id=thread_id).order_by(Scorecard.id).all()
    ]
    return rows, cards


def _call(client, team, actor, method, path, body=None):
    user = team["users"][actor]
    return client.open(path, method=method, headers=_headers(team["app"], user), json=body)


# --- Reads ---------------------------------------------------------------

READ_ROUTES = {
    "bundle": ("GET", "/api/v1/strategy/threads/{t}/bundle", None),
    "wbs": ("GET", "/api/v1/strategy/threads/{t}/wbs", None),
    "scorecard": ("GET", "/api/v1/strategy/threads/{t}/scorecards/{c}", None),
    "overrides": ("GET", "/api/v1/strategy/threads/{t}/scorecards/{c}/overrides", None),
    "attributes": ("GET", "/api/v1/strategy/threads/{t}/scorecards/{c}/attributes", None),
    "workspace-chat": ("GET", "/api/v1/strategy/threads/{t}/workspace-chat/__execution__", None),
    "scenarios": ("GET", "/api/v1/strategy/threads/{t}/scenarios", None),
}


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("route", sorted(READ_ROUTES))
def test_read_routes_follow_read_access(client, team, actor, route):
    method, template, body = READ_ROUTES[route]
    thread_id, card_id = team["projects"][actor]
    before = _project_state(thread_id)

    response = _call(client, team, actor, method, template.format(t=thread_id, c=card_id), body)

    if actor in READERS:
        assert response.status_code == 200, (route, actor, response.get_data(as_text=True)[:400])
        assert MARKER.encode() in response.data, (route, actor)
    else:
        assert response.status_code == 404, (route, actor, response.status_code)
        assert MARKER.encode() not in response.data
    # A read never writes, for anyone.
    assert _project_state(thread_id) == before, (route, actor)


def test_bundle_returns_the_projects_scorecards_to_every_member(client, team):
    """ORG-4: a teammate opening a shared project sees its scorecard."""
    owner_body = _call(client, team, "owner", "GET", "/api/v1/strategy/threads/t-shared/bundle").get_json()
    for actor in ("editor", "viewer"):
        body = _call(client, team, actor, "GET", "/api/v1/strategy/threads/t-shared/bundle").get_json()
        assert [c["id"] for c in body["peer_scorecards"]] == [c["id"] for c in owner_body["peer_scorecards"]]
        assert body["peer_scorecards"], "the shared project's scorecard is missing"
        assert body["project_wbs"]["name"] == f"Plan {MARKER}"
        assert body["messages"] == owner_body["messages"]


def test_bundle_never_writes_even_when_it_computes_levers(client, team):
    """ORG-5: GET bundle used to save the lever catalog, so a read-only member
    got a 500. It now computes it for the response only."""
    before = _project_state("t-shared")
    for actor in ("owner", "viewer", "creator-now-viewer"):
        thread_id, _card_id = team["projects"][actor]
        response = _call(client, team, actor, "GET", f"/api/v1/strategy/threads/{thread_id}/bundle")
        assert response.status_code == 200, actor
        assert response.get_json()["lever_catalog"], "levers are still computed on read"
    assert _project_state("t-shared") == before


# --- Writes --------------------------------------------------------------

WRITE_ROUTES = {
    "scorecard-patch": ("PATCH", "/api/v1/strategy/threads/{t}/scorecard-patch",
                        {"executive_summary": "Edited by the team"}),
    "snapshot-rename": ("PATCH", "/api/v1/strategy/threads/{t}/scorecard-snapshots/{c}",
                        {"label": "Renamed by the team"}),
    "snapshot-delete": ("DELETE", "/api/v1/strategy/threads/{t}/scorecard-snapshots/{c}", None),
    "score-delete": ("DELETE", "/api/v1/strategy/scores/{t}/{c}", None),
    "attributes": ("PATCH", "/api/v1/strategy/threads/{t}/scorecards/{c}/attributes",
                   {"attributes": {"note": {"value": 1, "source": "not-a-source"}}}),
    "recompute": ("POST", "/api/v1/strategy/threads/{t}/scorecards/{c}/recommendation/recompute", {}),
    "overrides": ("PATCH", "/api/v1/strategy/threads/{t}/scorecards/{c}/overrides",
                  {"display_overrides": {"title": "Team title"}}),
    "adopt": ("POST", "/api/v1/strategy/threads/{t}/adopt", {"analysis_id": "scn-1"}),
    "score-next": ("POST", "/api/v1/strategy/threads/{t}/score-next", {"name": "Not queued"}),
    "score-batch": ("POST", "/api/v1/strategy/threads/{t}/score-batch", {"ideas": []}),
    "selection": ("POST", "/api/v1/strategy/threads/{t}/selection", {"constraints": []}),
    "wbs-save": ("PUT", "/api/v1/strategy/threads/{t}/wbs",
                 {"project_wbs": {"name": "Team plan", "tasks": [], "phases": []}}),
    "wbs-start-date": ("POST", "/api/v1/strategy/threads/{t}/wbs/start-date", {"start_date": "2027-01-04"}),
    "workspace-chat-save": ("PUT", "/api/v1/strategy/threads/{t}/workspace-chat/__execution__",
                            {"messages": [{"role": "user", "text": "Team note"}]}),
    "scenario-create": ("POST", "/api/v1/strategy/threads/{t}/scenarios",
                        {"label": "Team scenario", "deltas": {"initial_investment": 10}}),
    "scenario-update": ("PATCH", "/api/v1/strategy/scenarios/scn-1?thread_id={t}",
                        {"label": "Renamed scenario", "deltas": {"initial_investment": 10}}),
    "scenario-delete": ("DELETE", "/api/v1/strategy/scenarios/scn-1?thread_id={t}", None),
    "scenario-apply": ("POST", "/api/v1/strategy/scenarios/scn-1/apply?thread_id={t}", {}),
    "scenario-adopt": ("POST", "/api/v1/strategy/scenarios/scn-1/adopt?thread_id={t}", {}),
}
# Each write that reaches its logic answers this way for an allowed member.
# (A refused member never gets here.)
REACHED = {
    "scorecard-patch": {200},
    "snapshot-rename": {200},
    "snapshot-delete": {200},
    "score-delete": {200},
    "attributes": {400},      # the logic validated the (deliberately bad) source
    "recompute": {200, 409},  # 409 = facts changed, holistic re-score required
    "overrides": {200},
    "adopt": {200},
    "score-next": {200},      # nothing queued: the logic answered "done"
    "score-batch": {200},     # nothing queued: answered without generating
    "selection": {200},
    "wbs-save": {200},
    "wbs-start-date": {404},  # the logic answered: the seeded plan has no tasks to move
    "workspace-chat-save": {200},
    "scenario-create": {201},
    "scenario-update": {200},
    "scenario-delete": {200},
    "scenario-apply": {200},
    "scenario-adopt": {200},
}


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("route", sorted(WRITE_ROUTES))
def test_write_routes_require_an_editing_role(client, team, actor, route):
    method, template, body = WRITE_ROUTES[route]
    thread_id, card_id = team["projects"][actor]
    before = _project_state(thread_id)

    response = _call(client, team, actor, method, template.format(t=thread_id, c=card_id), body)

    if actor in WRITERS:
        assert response.status_code in REACHED[route], (
            route, actor, response.status_code, response.get_data(as_text=True)[:400],
        )
        if route == "wbs-start-date":
            assert b"No execution plan found for this idea" in response.data
        rows, _cards = _project_state(thread_id)
        assert len(rows) == 1, "the project still has exactly one row"
    else:
        expected = 403 if actor in READERS else 404
        assert response.status_code == expected, (route, actor, response.status_code)
        assert MARKER.encode() not in response.data
        assert _project_state(thread_id) == before, f"{actor} changed the project via {route}"


AI_ROUTES = {
    "scorecard-assistant": ("/api/v1/strategy/threads/{t}/scorecard-assistant",
                            {"instruction": "Tighten the summary"}),
    "execution-assistant": ("/api/v1/strategy/threads/{t}/execution-assistant",
                            {"instruction": "Add a kickoff task"}),
    "plan-build": ("/api/v1/strategy/threads/{t}/ai-wbs", {"commit": True}),
    "plan-preview": ("/api/v1/strategy/threads/{t}/ai-wbs", {"commit": False}),
    "ai-scenario": ("/api/v1/strategy/threads/{t}/ai-scenario", {"instruction": "Lower the cost"}),
    "analyze": ("/api/v1/strategy/analyze", None),
}


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("route", sorted(AI_ROUTES))
def test_generating_routes_refuse_before_any_model_call(client, team, model_calls, actor, route):
    template, body = AI_ROUTES[route]
    thread_id, _card_id = team["projects"][actor]
    if route == "analyze":
        body = {"thread_id": thread_id, "name": "Vendor B"}
    user = team["users"][actor]
    _db.session.refresh(user)
    balance = user.credits_remaining
    before = _project_state(thread_id)

    response = _call(client, team, actor, "POST", template.format(t=thread_id), body)

    if actor in WRITERS:
        assert model_calls, f"{route}: an editor never reached generation ({response.status_code})"
    else:
        assert not model_calls, f"{route}: generation started for {actor}"
        assert response.status_code == (403 if actor in READERS else 404), (route, actor)
        assert _project_state(thread_id) == before
        _db.session.refresh(user)
        assert user.credits_remaining == balance, "a refused member was charged"


@pytest.mark.parametrize("actor,allowed", [("editor", True), ("viewer", False)])
def test_analyze_may_create_a_new_project_only_for_an_editing_role(client, team, model_calls, actor, allowed):
    """OD-6: /analyze is the route meant to create a project, so a new id is
    allowed; creating organization work still needs an editing role, checked
    before anything is sealed or generated."""
    response = _call(client, team, actor, "POST", "/api/v1/strategy/analyze",
                     {"thread_id": "t-brand-new", "description": "A new vendor option", "name": "New"})
    if allowed:
        assert model_calls, response.get_data(as_text=True)[:300]
    else:
        assert response.status_code == 403
        assert not model_calls
        assert UserSession.query.filter_by(session_id="t-brand-new").count() == 0


# --- Corrections from the P2b acceptance review -----------------------------

def test_selection_returns_the_projects_options_to_an_editor(client, team):
    """Selection is an editing action (spec 2.3); an editor gets the project's
    options in it."""
    thread_id, card_id = team["projects"]["editor"]
    response = _call(client, team, "editor", "POST",
                     f"/api/v1/strategy/threads/{thread_id}/selection", {"constraints": []})
    assert response.status_code == 200
    assert card_id.encode() in response.data


def _seed_populated_plan(thread_id, card_id, owner):
    """A plan with tasks under a wrong key and a stale name, a chat history with
    an execution-plan artifact for an id that has no plan, and a chat under the
    legacy key: everything the old GET routes used to rewrite on read."""
    from sqlalchemy.orm.attributes import flag_modified
    from app.scenarios_store import save_project_scenarios_data

    plan = {
        "name": "Execution Plan", "scorecard_id": "stale-id", "scorecard_name": "Old idea",
        "phases": [],
        "tasks": [{"id": "t1", "title": f"Kickoff for Title {MARKER}", "status": "todo"}],
    }

    def _populate(td):
        td["wbs_by_scorecard"] = {"stale-id": plan}
        td["project_wbs"] = plan
        td["workspace_chats"] = {"__execution__": [{"role": "user", "text": f"Legacy chat {MARKER}"}]}
        td.pop("active_execution_scorecard_id", None)
        return td

    save_project_scenarios_data(owner.id, thread_id, updater=_populate)
    row = UserSession.query.filter_by(session_id=thread_id, user_id=owner.id).one()
    payload = dict(row.payload)
    payload["chat_history"] = list(HIST) + [{
        "role": "assistant", "content": "Plan",
        "artifact": {"type": "execution_plan", "data": {"scorecard_id": "orphan-id"}},
    }]
    row.payload = payload
    flag_modified(row, "payload")
    _db.session.commit()
    _db.session.expire_all()


@pytest.mark.parametrize("actor", ["owner", "editor", "viewer"])
def test_plan_read_never_writes_on_a_populated_project(client, team, actor):
    """WBS GET used to save the open plan id, re-key and re-name legacy plans,
    register an artifact and prune orphan artifacts. It is a read now: rows
    and revisions are unchanged for every role, and the response still names
    the idea the plan was built from."""
    owner = team["users"]["owner"]
    _seed_populated_plan("t-shared", team["projects"]["owner"][1], owner)
    before = _project_state("t-shared")

    response = _call(client, team, actor, "GET",
                     "/api/v1/strategy/threads/t-shared/wbs?scorecard_id=stale-id")

    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    plan = response.get_json()["project_wbs"]
    assert plan["scorecard_name"] == f"Title {MARKER}"
    assert plan["name"] == f"Title {MARKER} — Execution Plan"
    assert _project_state("t-shared") == before


@pytest.mark.parametrize("actor", ["owner", "editor", "viewer"])
def test_a_legacy_plan_opens_through_its_options_canonical_id(client, team, actor):
    """A8/B6: a plan stored under a stale key is found when the option is
    opened by its real id, read-only, with the corrected name."""
    owner = team["users"]["owner"]
    card_id = team["projects"]["owner"][1]
    _seed_populated_plan("t-shared", card_id, owner)
    before = _project_state("t-shared")

    response = _call(client, team, actor, "GET",
                     f"/api/v1/strategy/threads/t-shared/wbs?scorecard_id={card_id}")

    assert response.status_code == 200
    body = response.get_json()
    assert body["scorecard_id"] == card_id
    plan = body["project_wbs"]
    assert plan and plan["tasks"][0]["title"] == f"Kickoff for Title {MARKER}"
    assert plan["scorecard_id"] == card_id
    assert _project_state("t-shared") == before


@pytest.mark.parametrize("actor", ["owner", "editor"])
def test_a_legacy_plan_edit_lands_on_the_options_own_key(client, team, actor):
    """Revisit and edit: the save moves the legacy plan to the option's id, so
    there is one plan for the option afterwards and no stale copy."""
    owner = team["users"]["owner"]
    card_id = team["projects"]["owner"][1]
    _seed_populated_plan("t-shared", card_id, owner)
    opened = _call(client, team, actor, "GET",
                   f"/api/v1/strategy/threads/t-shared/wbs?scorecard_id={card_id}").get_json()["project_wbs"]
    edited = dict(opened, tasks=opened["tasks"] + [{"id": "t2", "title": "Team follow-up", "status": "todo"}])

    response = _call(client, team, actor, "PUT", "/api/v1/strategy/threads/t-shared/wbs", {
        "scorecard_id": card_id, "project_wbs": edited, "expected_updated_at": opened.get("updated_at"),
    })

    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    _db.session.expire_all()
    td = UserSession.query.filter_by(session_id="t-shared").one().scenarios_json
    assert sorted(td["wbs_by_scorecard"]) == [card_id]
    titles = [t["title"] for t in td["wbs_by_scorecard"][card_id]["tasks"]]
    assert titles == [f"Kickoff for Title {MARKER}", "Team follow-up"]
    reopened = _call(client, team, actor, "GET",
                     f"/api/v1/strategy/threads/t-shared/wbs?scorecard_id={card_id}").get_json()["project_wbs"]
    assert [t["title"] for t in reopened["tasks"]] == titles


def test_a_legacy_plan_is_never_given_to_an_option_it_does_not_name(client, team):
    """Deterministic and safe: a stale plan goes only to the option its content
    names, and never replaces a plan another option already has."""
    owner = team["users"]["owner"]
    card_id = team["projects"]["owner"][1]
    _seed_populated_plan("t-shared", card_id, owner)
    response = _call(client, team, "owner", "GET",
                     "/api/v1/strategy/threads/t-shared/wbs?scorecard_id=some-other-option")
    assert response.status_code == 200
    assert response.get_json()["project_wbs"] is None


@pytest.mark.parametrize("actor", ["owner", "viewer"])
def test_workspace_chat_read_returns_a_legacy_chat_without_moving_it(client, team, actor):
    owner = team["users"]["owner"]
    card_id = team["projects"]["owner"][1]
    _seed_populated_plan("t-shared", card_id, owner)
    before = _project_state("t-shared")

    response = _call(client, team, actor, "GET",
                     f"/api/v1/strategy/threads/t-shared/workspace-chat/__execution__::{card_id}")

    assert response.status_code == 200
    assert f"Legacy chat {MARKER}" in json.dumps(response.get_json()["messages"])
    assert _project_state("t-shared") == before


def test_workspace_chat_save_writes_the_organizations_project(client, team):
    response = _call(client, team, "editor", "PUT",
                     "/api/v1/strategy/threads/t-shared/workspace-chat/__execution__",
                     {"messages": [{"role": "user", "text": "Editor note"}]})
    assert response.status_code == 200
    rows, _cards = _project_state("t-shared")
    assert len(rows) == 1
    _db.session.expire_all()
    row = UserSession.query.filter_by(session_id="t-shared").one()
    assert row.user_id == team["users"]["owner"].id
    assert row.scenarios_json["workspace_chats"]["__execution__"] == [{"role": "user", "text": "Editor note"}]


@pytest.fixture
def jira_calls(monkeypatch):
    """The project's plan is set to sync to Jira; record every Jira contact."""
    from app.routes import strategy

    calls = []
    monkeypatch.setattr(strategy, "get_thread_sync_profile",
                        lambda *_a, **_k: {"connector_ids": ["jira_sync"], "sync_mode": "push"})

    def _sync(**kwargs):
        calls.append(kwargs.get("thread_id"))
        return {"success": True, "skipped": True}

    monkeypatch.setattr(strategy, "sync_wbs_to_jira", _sync)
    return calls


@pytest.mark.parametrize("actor", ACTORS)
def test_plan_save_authorizes_the_project_before_jira_is_contacted(client, team, jira_calls, actor):
    thread_id, _card_id = team["projects"][actor]
    before = _project_state(thread_id)

    response = _call(client, team, actor, "PUT", f"/api/v1/strategy/threads/{thread_id}/wbs",
                     {"project_wbs": {"name": "Team plan", "tasks": [], "phases": []}})

    if actor in WRITERS:
        assert response.status_code == 200, response.get_data(as_text=True)[:300]
        assert jira_calls == [thread_id]
    else:
        assert response.status_code == (403 if actor in READERS else 404)
        assert jira_calls == [], f"Jira was contacted for {actor}"
        assert _project_state(thread_id) == before


def test_a_scorecard_with_no_project_is_not_reachable(client, team):
    """OD-6 A: a scorecard never stands on its own outside a project. A card
    indexed under an id that has no project row is not found, and nothing is
    created for it."""
    from app.scorecards import upsert_scorecard

    owner = team["users"]["owner"]
    upsert_scorecard(user_id=owner.id, thread_id="t-orphan", payload=_card("orphan-card", "t-orphan", "Orphan"),
                     organization_id=team["org"].id, source="native")
    _db.session.commit()
    before = _project_state("t-orphan")
    for method, path, body in [
        ("GET", "/api/v1/strategy/threads/t-orphan/scorecards/orphan-card", None),
        ("GET", "/api/v1/strategy/threads/t-orphan/scorecards/orphan-card/overrides", None),
        ("PATCH", "/api/v1/strategy/threads/t-orphan/scorecards/orphan-card/overrides",
         {"display_overrides": {"title": "x"}}),
        ("GET", "/api/v1/strategy/threads/t-orphan/scorecards/orphan-card/attributes", None),
    ]:
        response = _call(client, team, "owner", method, path, body)
        assert response.status_code == 404, (path, response.status_code)
    assert _project_state("t-orphan") == before


def test_every_thread_route_reports_an_unknown_project_and_creates_nothing(
    client, team, model_calls, jira_calls,
):
    """OD-6 A across the whole H-2b surface plus the plan and chat writes:
    404, no project row, no model call, no Jira contact. Only /analyze may
    create a project (tested above)."""
    routes = [(m, t, b) for m, t, b in READ_ROUTES.values()]
    routes += [(m, t, b) for m, t, b in WRITE_ROUTES.values()]
    routes += [("POST", t, b) for t, b in AI_ROUTES.values() if "{t}" in t]
    for method, template, body in routes:
        path = template.format(t="t-missing", c="c-missing")
        response = _call(client, team, "owner", method, path, body)
        assert response.status_code == 404, (path, response.status_code)
    assert UserSession.query.filter_by(session_id="t-missing").count() == 0
    assert Scorecard.query.filter_by(thread_id="t-missing").count() == 0
    assert not model_calls
    assert jira_calls == []


def test_scenario_apply_does_not_depend_on_a_read_having_saved_lever_inputs(client, team):
    """Bundle no longer saves lever inputs. Apply derives them from the project
    the same way, so a project nobody has opened computes exactly what a
    project whose inputs were saved (as P2a's bundle did) computes."""
    from app.routes.strategy import _build_scenario_lever_catalog, _extract_baseline_inputs
    from app.scenarios_store import save_project_scenarios_data

    owner = team["users"]["owner"]
    _seed_project(owner, team["org"], "t-stored")

    def _store_inputs(td):
        base = td["baseline"]
        td["baseline_inputs"], td["lever_catalog"] = _build_scenario_lever_catalog(base, _extract_baseline_inputs(base))
        return td

    save_project_scenarios_data(owner.id, "t-stored", updater=_store_inputs)
    results = {}
    for thread_id in ("t-shared", "t-stored"):
        assert "baseline_inputs" not in (UserSession.query.filter_by(session_id="t-shared").one().scenarios_json or {})
        edit = _call(client, team, "editor", "PATCH", f"/api/v1/strategy/scenarios/scn-1?thread_id={thread_id}",
                     {"deltas": {"initial_investment": 25}})
        assert edit.status_code == 200, edit.get_data(as_text=True)[:300]
        applied = _call(client, team, "editor", "POST", f"/api/v1/strategy/scenarios/scn-1/apply?thread_id={thread_id}",
                        {"expected_updated_at": edit.get_json()["updated_at"]})
        assert applied.status_code == 200, applied.get_data(as_text=True)[:300]
        body = applied.get_json()
        results[thread_id] = (body["jaspen_score"], body["component_scores"], body["financial_impact"])
        assert edit.get_json()["result"]["jaspen_score"] == body["jaspen_score"]
    assert results["t-shared"] == results["t-stored"]


def test_scenario_list_returns_the_projects_scenarios_to_a_teammate(client, team):
    owner_body = _call(client, team, "owner", "GET", "/api/v1/strategy/threads/t-shared/scenarios").get_json()
    viewer_body = _call(client, team, "viewer", "GET", "/api/v1/strategy/threads/t-shared/scenarios").get_json()
    assert [x["scenario_id"] for x in viewer_body["scenarios"]] == ["scn-1"]
    assert viewer_body == owner_body


def test_scenario_writes_land_on_the_organizations_project(client, team):
    response = _call(client, team, "editor", "POST", "/api/v1/strategy/threads/t-shared/scenarios",
                     {"label": "Editor scenario", "deltas": {}})
    assert response.status_code == 201
    _db.session.expire_all()
    rows = UserSession.query.filter_by(session_id="t-shared").all()
    assert len(rows) == 1 and rows[0].user_id == team["users"]["owner"].id
    labels = sorted(x["label"] for x in rows[0].scenarios_json["scenarios"].values())
    assert labels == ["Editor scenario", f"Scenario {MARKER}"]


def test_a_legacy_plan_choice_is_deterministic_when_two_stale_plans_name_the_option(client, team):
    from app.scenarios_store import save_project_scenarios_data

    owner = team["users"]["owner"]
    card_id = team["projects"]["owner"][1]

    def _two(td):
        task = [{"id": "t1", "title": f"Kickoff for Title {MARKER}", "status": "todo"}]
        td["wbs_by_scorecard"] = {
            "stale-a": {"name": "A", "tasks": task, "updated_at": "2026-10-01T00:00:00"},
            "stale-b": {"name": "B", "tasks": task, "updated_at": "2026-10-05T00:00:00"},
        }
        return td

    save_project_scenarios_data(owner.id, "t-shared", updater=_two)
    names = {
        _call(client, team, "owner", "GET",
              f"/api/v1/strategy/threads/t-shared/wbs?scorecard_id={card_id}").get_json()["project_wbs"]["updated_at"]
        for _ in range(3)
    }
    assert names == {"2026-10-05T00:00:00"}


# --- Attribution: a teammate's edit never moves ownership ------------------

def test_editor_changes_to_the_owners_card_keep_the_owners_attribution(client, team):
    owner, editor = team["users"]["owner"], team["users"]["editor"]
    _thread_id, card_id = team["projects"]["editor"]

    response = _call(client, team, "editor", "PATCH",
                     f"/api/v1/strategy/threads/t-shared/scorecard-snapshots/{card_id}",
                     {"label": "Renamed by the editor"})
    assert response.status_code == 200, response.get_data(as_text=True)

    _db.session.expire_all()
    cards = Scorecard.query.filter_by(id=card_id).all()
    assert len(cards) == 1
    assert cards[0].user_id == owner.id
    assert cards[0].data["label"] == "Renamed by the editor"

    response = _call(client, team, "editor", "PATCH", "/api/v1/strategy/threads/t-shared/scorecard-patch",
                     {"executive_summary": "Edited by the editor"})
    assert response.status_code == 200, response.get_data(as_text=True)
    _db.session.expire_all()
    row = UserSession.query.filter_by(session_id="t-shared").one()
    assert row.user_id == owner.id and row.created_by_user_id == owner.id
    assert row.last_edited_by_user_id == editor.id
    assert row.payload["result"]["selected_scorecard_id"].endswith("__edited")

    response = _call(client, team, "editor", "DELETE", f"/api/v1/strategy/scores/t-shared/{card_id}")
    assert response.status_code == 200, response.get_data(as_text=True)
    _db.session.expire_all()
    card = Scorecard.query.filter_by(id=card_id).one()
    assert card.user_id == owner.id and card.archived_at is not None


def test_other_organizations_same_id_is_never_reached(client, team):
    """The other organization holding a project under the same id sees only
    its own, and the shared project stays untouched."""
    outsider = team["users"]["other-org"]
    from app.routes.sessions import save_user_sessions
    assert save_user_sessions(outsider.id, {"t-shared": {
        "session_id": "t-shared", "user_id": outsider.id, "name": "Outsider own",
        "status": "in_progress", "organization_id": outsider.active_organization_id,
        "chat_history": [{"role": "user", "content": "outsider words"}],
    }})
    before = _project_state("t-shared")
    response = _call(client, team, "other-org", "GET", "/api/v1/strategy/threads/t-shared/bundle")
    assert response.status_code == 200
    assert MARKER.encode() not in response.data
    assert b"outsider words" in response.data
    response = _call(client, team, "other-org", "PATCH", "/api/v1/strategy/threads/t-shared/scorecard-patch",
                     {"executive_summary": "outsider edit"})
    shared_rows = [r for r in _project_state("t-shared")[0] if r[2] == team["org"].id]
    assert shared_rows == [r for r in before[0] if r[2] == team["org"].id]


# --- Guards --------------------------------------------------------------

# Personal lookups: right for history lists, wrong for "this project".
_PERSONAL_SESSION_LOOKUPS = {"load_user_sessions"}
_PERSONAL_PROJECT_LOOKUPS = {"load_user_sessions", "_load_scenarios", "load_scenarios_data"}

# The H-2b routes and the helpers they read the project through. Scenario and
# plan data for these come from the canonical row as well.
_H2B_FUNCTIONS = {
    "get_thread_bundle", "get_thread_wbs", "decision_selection", "patch_thread_scorecard",
    "update_scorecard_snapshot", "delete_scorecard_snapshot", "scorecard_attributes",
    "recompute_decision_recommendation", "score_next_queued", "score_batch_queued",
    "analyze_project", "delete_score_entry", "scorecard_assistant", "execution_assistant",
    "adopt_analysis_for_thread", "get_scorecard_for_workspace", "scorecard_display_overrides",
    "_build_execution_plan", "_resolve_thread_baseline", "_find_scorecard_carrier",
    "_canonical_thread_peers", "_rename_snapshot_in_session", "_delete_snapshot_from_session",
    "_set_selected_snapshot_in_session", "_persist_scenario_snapshot_to_session",
    "_load_thread_conversation", "_load_thread_ai_insights", "_thread_user_corpus",
    "_thread_levers_for_scenario_ai", "_register_execution_plan_artifact",
    "upsert_thread_wbs", "reanchor_thread_wbs_start_date",
    "get_workspace_chat", "upsert_workspace_chat",
    "_create_scenario_record", "create_scenario", "list_scenarios", "update_scenario",
    "delete_scenario", "apply_scenario", "create_ai_scenario",
}


def _strategy_functions():
    from app.routes import strategy
    tree = ast.parse(inspect.getsource(strategy))
    return {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


def _personal_lookup_offenders(functions, names, lookups):
    offenders = []
    for name in sorted(names):
        for node in ast.walk(functions[name]):
            if isinstance(node, ast.Call):
                called = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if called in lookups:
                    offenders.append(f"{name} line {node.lineno}: {called}()")
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in lookups:
                        offenders.append(f"{name} line {node.lineno}: imports {alias.name}")
    return offenders


def _takes_thread_id(node):
    args = node.args
    names = [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]
    return "thread_id" in names


def test_guard_no_strategy_function_with_a_thread_id_uses_a_personal_session_lookup():
    functions = _strategy_functions()
    guarded = {name for name, node in functions.items() if _takes_thread_id(node)}
    offenders = _personal_lookup_offenders(functions, guarded, _PERSONAL_SESSION_LOOKUPS)
    assert not offenders, (
        "A strategy.py function that takes a thread_id looked the project up among the "
        "caller's own rows. Use _thread_scope / _thread_sessions instead:\n" + "\n".join(offenders)
    )


def test_guard_h2b_routes_read_scenario_data_from_the_project():
    functions = _strategy_functions()
    missing = _H2B_FUNCTIONS - set(functions)
    assert not missing, f"renamed or removed; update the guard list: {sorted(missing)}"
    offenders = _personal_lookup_offenders(functions, _H2B_FUNCTIONS, _PERSONAL_PROJECT_LOOKUPS)
    assert not offenders, (
        "An H-2b route or helper read scenario or session data from the caller's own rows. "
        "Use _thread_scenarios / _thread_sessions instead:\n" + "\n".join(offenders)
    )


def test_guard_catches_a_personal_lookup():
    """The guards must fail on the defect they exist to prevent, aliases included."""
    tree = ast.parse(textwrap.dedent('''
        def get_example(thread_id):
            from app.routes.sessions import load_user_sessions as _load
            return (_load("u") or {}).get(thread_id)
    '''))
    functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert _takes_thread_id(functions["get_example"])
    assert _personal_lookup_offenders(functions, {"get_example"}, _PERSONAL_SESSION_LOOKUPS)
