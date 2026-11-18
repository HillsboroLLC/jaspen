"""P3 (H-3): every save writes one project, against the version it read.

Acceptance (roadmap P3, architecture section 8, backlog 14):

* Stabilization baseline B2 / Probe 1, verbatim at the store and as a route
  test for each write family: another save that lands while a route is
  working survives the route's save.
* Different objects changed at the same time: both changes are kept.
* The same object changed by two people: the approved refusal, and the
  stored value is the first writer's, never overwritten.
* Guard: no route reaches the store with more than one project.
* Lost races re-run the whole unit; asserted conflicts are never retried.
* The per-option scorecard, ``payload.result`` and the ``Scorecard`` index
  agree after an overlapping write.
* Authorization and tenant isolation are unchanged at the store.

Journeys (acceptance matrix): C1 (two projects, neither reverts the other),
C7 (same-object conflict), C8 (different-object overlap). A8, E1 and the plan,
rename-during-scoring and undo sequences are covered by the existing journey
files, run with this one.
"""
import ast
import copy
import pathlib

import pytest
from flask_jwt_extended import create_access_token

from app.models import Scorecard, UserSession
from app.project_changes import ConflictingChange, apply_request_changes
from app.routes import sessions as sessions_mod
from app.routes.sessions import (
    load_user_sessions,
    run_project_write,
    save_project_session,
    save_user_sessions,
)
from app.scorecards import upsert_scorecard
from app.session_access import LostRace, RevisionConflict, SessionForbidden
from tests.test_decision_flow_stabilization import mock_accounting, seed_thread
from tests.test_plan_build_jobs import CARD
from tests.test_session_org_ownership import _add_member, _mk_org, _mk_user, _seed_project


CONFLICT = "This project has newer changes. Reload to get the latest version. Your changes weren't saved."
ROUTES_DIR = pathlib.Path(__file__).resolve().parents[2] / "app" / "routes"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row(session_id):
    return UserSession.query.filter_by(session_id=session_id).one()


def _other_member_saves(session_id, key="p3_other_member_note", value="kept", **changes):
    """Another member's committed save: changes the stored project, bumps its
    revision, and is invisible to the in-flight request's loaded copy."""
    row = _row(session_id)
    payload = copy.deepcopy(row.payload or {})
    if key is not None:
        payload[key] = value
    payload.update(changes)
    values = {
        UserSession.payload: payload,
        UserSession.revision: UserSession.revision + 1,
    }
    if "name" in payload and payload.get("name") != row.name:
        values[UserSession.name] = payload["name"]
    UserSession.query.filter_by(id=row.id).update(values, synchronize_session=False)


@pytest.fixture
def lands_during_save(monkeypatch, db):
    """Make another member's save land right before a route's first project
    write, i.e. after the route read the project and before it writes."""
    db_session = db.session

    def arm(session_id, **change):
        original = sessions_mod._write_one_project
        state = {"fired": False}

        def interleaved(actor, user_id, key, payload):
            sid = str(payload.get("session_id") or key or "")
            if not state["fired"] and sid == session_id:
                state["fired"] = True
                _other_member_saves(session_id, **change)
                # Another member's save is its own committed transaction.
                db_session.commit()
            return original(actor, user_id, key, payload)

        monkeypatch.setattr(sessions_mod, "_write_one_project", interleaved)
        return state
    return arm


def _seed(user, db, tid, cards=None, **extra):
    seed_thread(user, tid, cards if cards is not None else [CARD])
    for card in cards if cards is not None else [CARD]:
        upsert_scorecard(user_id=user.id, thread_id=tid, payload=card)
    if extra:
        row = _row(tid)
        payload = copy.deepcopy(row.payload)
        payload.update(extra)
        row.payload = payload
    db.session.commit()


# ---------------------------------------------------------------------------
# Probe 1, verbatim (stabilization baseline B2), at the store
# ---------------------------------------------------------------------------

def test_probe_1_stale_whole_dict_save_keeps_other_session(app, db):
    u = _mk_user(db, "stale-probe@example.test", plan="free")
    _mk_org(db, u, name="StaleProbe", plan="free")
    with app.test_request_context():
        assert save_user_sessions(u.id, {
            "s-x": {"session_id": "s-x", "name": "X", "chat_history": []},
            "s-y": {"session_id": "s-y", "name": "Y", "chat_history": []},
        })
        req_a = copy.deepcopy(load_user_sessions(u.id))
        req_b = copy.deepcopy(load_user_sessions(u.id))
        req_b["s-y"]["chat_history"] = [{"role": "user", "content": "B's turn"}]
        assert save_user_sessions(u.id, req_b)
        req_a["s-x"]["chat_history"] = [{"role": "user", "content": "A's turn"}]
        assert save_user_sessions(u.id, req_a)
        y = UserSession.query.filter_by(session_id="s-y").one()
        assert y.payload.get("chat_history") == [{"role": "user", "content": "B's turn"}]
        x = UserSession.query.filter_by(session_id="s-x").one()
        assert x.payload.get("chat_history") == [{"role": "user", "content": "A's turn"}]


def _two_requests(app, user_id, session_id, change_b, change_a):
    """Request A reads, request B reads, changes and saves, then A saves.
    Each request has its own application context (its own read record)."""
    with app.app_context():
        a = copy.deepcopy(load_user_sessions(user_id)[session_id])
        with app.app_context():
            b = copy.deepcopy(load_user_sessions(user_id)[session_id])
            change_b(b)
            assert save_project_session(user_id, session_id, b)
        change_a(a)
        return save_project_session(user_id, session_id, a)


def test_probe_1_same_project_different_fields_both_kept(app, db, test_user):
    with app.app_context():
        assert save_project_session(test_user.id, "p-1", {"session_id": "p-1", "chat_history": []})
    assert _two_requests(
        app, test_user.id, "p-1",
        lambda b: b.update(notes={"owner": "B's note"}),
        lambda a: a.update(chat_history=[{"role": "user", "content": "A's turn"}]),
    )
    stored = _row("p-1").payload
    assert stored["notes"] == {"owner": "B's note"}
    assert stored["chat_history"] == [{"role": "user", "content": "A's turn"}]


def test_probe_1_same_field_is_refused_and_first_writer_kept(app, db, test_user):
    with app.app_context():
        assert save_project_session(test_user.id, "p-2", {"session_id": "p-2", "name": "Start"})
    with pytest.raises(RevisionConflict) as caught:
        _two_requests(
            app, test_user.id, "p-2",
            lambda b: b.update(name="B's name"),
            lambda a: a.update(name="A's name"),
        )
    assert not isinstance(caught.value, LostRace)
    assert caught.value.to_response()[0]["error"] == CONFLICT
    db.session.expire_all()
    assert _row("p-2").name == "B's name"


def test_concurrent_chat_appends_to_one_project_both_kept(app, db, test_user):
    """Two turns on one project (two tabs): neither reply is lost."""
    start = [{"role": "user", "content": "start"}]
    with app.app_context():
        assert save_project_session(test_user.id, "p-3", {"session_id": "p-3", "chat_history": start})
    assert _two_requests(
        app, test_user.id, "p-3",
        lambda b: b.update(chat_history=start + [{"role": "assistant", "content": "B"}]),
        lambda a: a.update(chat_history=start + [{"role": "assistant", "content": "A"}]),
    )
    assert [m["content"] for m in _row("p-3").payload["chat_history"]] == ["start", "B", "A"]


def test_a_later_save_in_the_same_request_may_change_what_it_saved_earlier(app, db, test_user):
    """A tool saves the project mid-turn; the turn's own later save wins over
    the tool's value for the same field, as it always has, and what the tool
    added that the turn did not touch stays."""
    with app.app_context():
        assert save_project_session(test_user.id, "p-6", {"session_id": "p-6", "scoring_rubric": {"v": 0}})
    with app.app_context():
        turn = copy.deepcopy(load_user_sessions(test_user.id)["p-6"])
        tool = copy.deepcopy(load_user_sessions(test_user.id)["p-6"])
        tool["scoring_rubric"] = {"v": 2, "durable": True}
        assert save_project_session(test_user.id, "p-6", tool)
        turn["scoring_rubric"] = {"v": 1}
        assert save_project_session(test_user.id, "p-6", turn)
    assert _row("p-6").payload["scoring_rubric"] == {"v": 1, "durable": True}


def test_saved_copy_follows_its_own_revision_within_one_request(app, db, test_user):
    """One request saving the same project twice never conflicts with itself."""
    with app.app_context():
        assert save_project_session(test_user.id, "p-4", {"session_id": "p-4", "name": "One"})
        mine = load_user_sessions(test_user.id)["p-4"]
        mine["name"] = "Two"
        assert save_project_session(test_user.id, "p-4", mine)
        mine["name"] = "Three"
        assert save_project_session(test_user.id, "p-4", mine)
        assert _row("p-4").name == "Three"
        assert mine["revision"] == _row("p-4").revision


def test_a_declared_base_revision_is_the_starting_point(app, db, test_user):
    """A caller that declares the revision it builds on is checked against it
    (stale: refused) and otherwise written as given."""
    with app.app_context():
        assert save_project_session(test_user.id, "p-5", {"session_id": "p-5", "name": "One"})
        mine = {**load_user_sessions(test_user.id)["p-5"]}
    _other_member_saves("p-5")
    db.session.commit()
    with app.app_context():
        with pytest.raises(RevisionConflict):
            save_project_session(test_user.id, "p-5", {**mine, "base_revision": mine["revision"]})
        current = _row("p-5").revision
        assert save_project_session(test_user.id, "p-5", {**mine, "name": "Mine", "base_revision": current})
    assert _row("p-5").name == "Mine"


# ---------------------------------------------------------------------------
# Probe 1 at route level, one test per write family
# ---------------------------------------------------------------------------

def test_route_sessions_complete_keeps_overlapping_save(client, db, test_user, auth_headers, lands_during_save):
    _seed(test_user, db, "rt-complete", cards=[])
    state = lands_during_save("rt-complete")
    response = client.post("/api/v1/sessions/complete", headers=auth_headers, json={"session_id": "rt-complete"})
    assert response.status_code == 200, response.get_json()
    assert state["fired"]
    db.session.expire_all()
    stored = _row("rt-complete")
    assert stored.payload["status"] == "completed"
    assert stored.payload["p3_other_member_note"] == "kept"


def test_route_thread_rename_keeps_overlapping_save(client, db, test_user, auth_headers, lands_during_save):
    _seed(test_user, db, "rt-rename", cards=[])
    state = lands_during_save("rt-rename")
    response = client.patch("/api/v1/ai-agent/threads/rt-rename", headers=auth_headers, json={"name": "Renamed"})
    assert response.status_code == 200, response.get_json()
    assert state["fired"]
    db.session.expire_all()
    stored = _row("rt-rename")
    assert stored.name == "Renamed"
    assert stored.payload["p3_other_member_note"] == "kept"


def test_route_append_messages_keeps_overlapping_save(client, db, test_user, auth_headers, lands_during_save):
    _seed(test_user, db, "rt-append", cards=[])
    state = lands_during_save("rt-append")
    response = client.post(
        "/api/v1/ai-agent/threads/rt-append/messages", headers=auth_headers,
        json={"messages": [{"role": "user", "content": "Note for the team"}]},
    )
    assert response.status_code == 200, response.get_json()
    assert state["fired"]
    db.session.expire_all()
    stored = _row("rt-append").payload
    assert stored["chat_history"][-1]["content"] == "Note for the team"
    assert stored["p3_other_member_note"] == "kept"


def test_route_message_feedback_keeps_overlapping_save(client, db, test_user, auth_headers, lands_during_save):
    _seed(test_user, db, "rt-feedback", cards=[],
          chat_history=[{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}])
    state = lands_during_save("rt-feedback")
    response = client.post(
        "/api/v1/ai-agent/threads/rt-feedback/messages/1/feedback", headers=auth_headers,
        json={"value": "up"},
    )
    assert response.status_code == 200, response.get_json()
    assert state["fired"]
    db.session.expire_all()
    stored = _row("rt-feedback").payload
    assert stored["chat_history"][1].get("feedback")
    assert stored["p3_other_member_note"] == "kept"


def test_route_workspace_project_rename_keeps_overlapping_save(client, db, test_user, auth_headers, lands_during_save):
    _seed(test_user, db, "rt-ws-rename")
    state = lands_during_save("rt-ws-rename")
    response = client.patch("/api/v1/strategy/threads/rt-ws-rename", headers=auth_headers, json={"name": "New name"})
    assert response.status_code == 200, response.get_json()
    assert state["fired"]
    db.session.expire_all()
    stored = _row("rt-ws-rename")
    assert stored.name == "New name"
    assert stored.payload["p3_other_member_note"] == "kept"


def test_route_scorecard_snapshot_rename_keeps_overlapping_save(client, db, test_user, auth_headers, lands_during_save):
    other = {**CARD, "id": "other-card", "project_name": "Other"}
    _seed(test_user, db, "rt-snap", cards=[CARD, other])
    state = lands_during_save("rt-snap")
    response = client.patch(
        "/api/v1/strategy/threads/rt-snap/scorecard-snapshots/other-card", headers=auth_headers,
        json={"label": "Renamed option"},
    )
    assert response.status_code == 200, response.get_json()
    assert state["fired"]
    db.session.expire_all()
    stored = _row("rt-snap").payload
    assert stored["p3_other_member_note"] == "kept"
    labels = {s.get("id"): s.get("label") for s in stored["result"].get("scorecard_snapshots") or []}
    assert labels.get("other-card") == "Renamed option"


def test_route_scorecard_snapshot_delete_keeps_overlapping_save(client, db, test_user, auth_headers, lands_during_save):
    other = {**CARD, "id": "other-card", "project_name": "Other"}
    _seed(test_user, db, "rt-snap-del", cards=[CARD, other])
    state = lands_during_save("rt-snap-del")
    response = client.delete(
        "/api/v1/strategy/threads/rt-snap-del/scorecard-snapshots/other-card", headers=auth_headers,
    )
    assert response.status_code == 200, response.get_json()
    assert state["fired"]
    db.session.expire_all()
    stored = _row("rt-snap-del").payload
    assert stored["p3_other_member_note"] == "kept"
    assert "other-card" not in {s.get("id") for s in stored["result"].get("scorecard_snapshots") or []}


def test_data_insight_keeps_overlapping_save(app, db, test_user, lands_during_save):
    from app.routes.ai_agent import _persist_thread_insight
    _seed(test_user, db, "rt-insight", cards=[])
    state = lands_during_save("rt-insight")
    with app.test_request_context():
        event = _persist_thread_insight(test_user.id, "rt-insight", "data.csv", {"k": 1}, "Summary")
    assert event is not None
    assert state["fired"]
    db.session.expire_all()
    stored = _row("rt-insight").payload
    assert stored["ai_insights"][0]["id"] == event["id"]
    assert stored["p3_other_member_note"] == "kept"


def test_chat_turn_store_keeps_overlapping_save_and_refuses_two_projects(app, db, test_user, lands_during_save):
    from app.routes.ai_agent import _save_turn_project
    _seed(test_user, db, "rt-turn", cards=[])
    with app.test_request_context():
        sessions = load_user_sessions(test_user.id)
        session = sessions["rt-turn"]
        session["chat_history"] = [{"role": "assistant", "content": "the reply"}]
        state = lands_during_save("rt-turn")
        assert _save_turn_project(test_user.id, {"rt-turn": session})
        assert state["fired"]
        with pytest.raises(ValueError):
            _save_turn_project(test_user.id, {"a": {}, "b": {}})
    db.session.expire_all()
    stored = _row("rt-turn").payload
    assert stored["chat_history"] == [{"role": "assistant", "content": "the reply"}]
    assert stored["p3_other_member_note"] == "kept"


def test_c1_route_on_one_project_never_reverts_another(client, db, test_user, auth_headers, monkeypatch):
    """C1: a save in tab X while tab Y's project changed: Y is untouched."""
    _seed(test_user, db, "c1-x", cards=[])
    _seed(test_user, db, "c1-y", cards=[])
    original = sessions_mod._write_one_project

    def interleaved(actor, user_id, key, payload):
        _other_member_saves("c1-y", key="chat_history", value=[{"role": "user", "content": "Y's turn"}])
        return original(actor, user_id, key, payload)

    monkeypatch.setattr(sessions_mod, "_write_one_project", interleaved)
    response = client.patch("/api/v1/ai-agent/threads/c1-x", headers=auth_headers, json={"name": "X renamed"})
    assert response.status_code == 200, response.get_json()
    db.session.expire_all()
    assert _row("c1-y").payload["chat_history"] == [{"role": "user", "content": "Y's turn"}]
    assert _row("c1-x").name == "X renamed"


# ---------------------------------------------------------------------------
# C7: same object, two writers
# ---------------------------------------------------------------------------

def test_c7_same_object_rename_is_refused_with_the_approved_sentence(client, db, test_user, auth_headers, lands_during_save):
    _seed(test_user, db, "c7-name", cards=[])
    lands_during_save("c7-name", key="name", value="Colleague's name")
    response = client.patch("/api/v1/ai-agent/threads/c7-name", headers=auth_headers, json={"name": "My name"})
    assert response.status_code == 409, response.get_json()
    assert response.get_json()["code"] == "revision_conflict"
    assert response.get_json()["error"] == CONFLICT
    db.session.expire_all()
    assert _row("c7-name").payload["name"] == "Colleague's name"


# ---------------------------------------------------------------------------
# Team comments and sharing write the payload outside the store
# ---------------------------------------------------------------------------

@pytest.fixture
def team_project(app, db):
    owner = _mk_user(db, "p3-owner@example.test")
    org = _mk_org(db, owner, name="P3Team")
    member = _mk_user(db, "p3-member@example.test")
    _add_member(db, org, member, role="collaborator")
    owner.active_organization_id = org.id
    db.session.commit()
    _seed_project(db, org, owner, session_id="team-p3", visibility="team")
    with app.app_context():
        headers = {
            "owner": {"Authorization": f"Bearer {create_access_token(identity=str(owner.id))}"},
            "member": {"Authorization": f"Bearer {create_access_token(identity=str(member.id))}"},
        }
    return owner, member, org, headers


def test_comment_then_stale_project_save_keeps_the_comment(app, client, db, team_project):
    owner, member, _org, headers = team_project
    with app.test_request_context():
        stale = copy.deepcopy(load_user_sessions(owner.id)["team-p3"])
    response = client.post("/api/v1/team/projects/team-p3/comments", headers=headers["member"], json={"body": "Looks good"})
    assert response.status_code == 201, response.get_json()
    with app.test_request_context():
        sessions_mod._remember_read(copy.deepcopy(stale))
        stale["notes"] = {"owner": "Owner's note"}
        assert save_project_session(owner.id, "team-p3", stale)
    db.session.expire_all()
    stored = _row("team-p3").payload
    assert [c["body"] for c in stored.get("comments") or []] == ["Looks good"]
    assert stored["notes"] == {"owner": "Owner's note"}


def test_comment_reads_the_stored_project_not_an_earlier_copy(app, client, db, team_project, monkeypatch):
    owner, member, _org, headers = team_project
    import app.routes.team as team_mod
    original = team_mod._locked_payload

    def save_lands_first(row):
        _other_member_saves("team-p3")
        return original(row)

    monkeypatch.setattr(team_mod, "_locked_payload", save_lands_first)
    response = client.post("/api/v1/team/projects/team-p3/comments", headers=headers["member"], json={"body": "Second look"})
    assert response.status_code == 201, response.get_json()
    db.session.expire_all()
    stored = _row("team-p3").payload
    assert stored["p3_other_member_note"] == "kept"
    assert [c["body"] for c in stored.get("comments") or []] == ["Second look"]


# ---------------------------------------------------------------------------
# Scorecard consistency: per-option scorecard, payload.result, Scorecard index
# ---------------------------------------------------------------------------

def test_scorecard_stores_agree_after_overlapping_rename(client, db, test_user, auth_headers, lands_during_save):
    other = {**CARD, "id": "other-card", "project_name": "Other"}
    _seed(test_user, db, "rt-consistent", cards=[CARD, other])
    result = copy.deepcopy(_row("rt-consistent").payload["result"])
    result["p3_mirror_note"] = "kept"
    lands_during_save("rt-consistent", key="result", value=result)
    response = client.patch(
        "/api/v1/strategy/threads/rt-consistent/scorecard-snapshots/other-card", headers=auth_headers,
        json={"label": "Final label"},
    )
    assert response.status_code == 200, response.get_json()
    db.session.expire_all()
    stored = _row("rt-consistent").payload["result"]
    assert stored["p3_mirror_note"] == "kept"
    mirror = {s.get("id"): s.get("label") for s in stored.get("scorecard_snapshots") or []}
    index = Scorecard.query.filter_by(thread_id="rt-consistent", id="other-card").one()
    assert mirror["other-card"] == "Final label"
    assert (index.data or {}).get("label") == "Final label"
    peers = client.get("/api/v1/strategy/threads/rt-consistent/bundle", headers=auth_headers).get_json()
    peer_labels = {
        str(p.get("id")): p.get("label")
        for p in (peers.get("scorecard_snapshots") or peers.get("peer_scorecards") or [])
    }
    if peer_labels:
        assert peer_labels.get("other-card") == "Final label"


# ---------------------------------------------------------------------------
# Authorization and tenant isolation at the single-project entry
# ---------------------------------------------------------------------------

def test_store_enforces_project_access_for_single_project_saves(app, db):
    owner = _mk_user(db, "p3-auth-owner@example.test")
    org = _mk_org(db, owner, name="P3Auth")
    viewer = _mk_user(db, "p3-viewer@example.test")
    _add_member(db, org, viewer, role="viewer")
    collaborator = _mk_user(db, "p3-collab@example.test")
    _add_member(db, org, collaborator, role="collaborator")
    outsider = _mk_user(db, "p3-outsider@example.test")
    _mk_org(db, outsider, name="P3Other")
    _seed_project(db, org, owner, session_id="auth-p3", visibility="team")
    before = copy.deepcopy(_row("auth-p3").payload)

    with app.test_request_context():
        with pytest.raises(SessionForbidden):
            save_project_session(viewer.id, "auth-p3", {**before, "name": "viewer"})
    with app.app_context():
        outsider_headers = {"Authorization": f"Bearer {create_access_token(identity=str(outsider.id))}"}
    with app.test_client() as other_org:
        response = other_org.patch(
            "/api/v1/ai-agent/threads/auth-p3", headers=outsider_headers, json={"name": "outsider"},
        )
        assert response.status_code == 404, response.get_json()
    db.session.expire_all()
    assert _row("auth-p3").payload == before
    assert UserSession.query.filter_by(session_id="auth-p3").count() == 1

    with app.test_request_context():
        mine = load_user_sessions(collaborator.id)
        from app.routes.sessions import load_sessions_for_thread
        mine = load_sessions_for_thread(collaborator, "auth-p3")
        mine["auth-p3"]["notes"] = {"collaborator": "edit"}
        assert save_project_session(collaborator.id, "auth-p3", mine["auth-p3"])
    db.session.expire_all()
    row = _row("auth-p3")
    assert row.user_id == owner.id
    assert row.created_by_user_id == owner.id
    assert row.last_edited_by_user_id == collaborator.id
    assert UserSession.query.filter_by(session_id="auth-p3").count() == 1


# ---------------------------------------------------------------------------
# Retry runner: lost races re-run the unit; asserted conflicts never do
# ---------------------------------------------------------------------------

def test_run_project_write_reruns_only_lost_races(app, db):
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise LostRace(1, 2, session_id="x")
        return "done"

    with app.app_context():
        assert run_project_write(flaky) == "done"
    assert len(calls) == 3

    calls.clear()

    def always_lost():
        calls.append(1)
        raise LostRace(1, 2, session_id="x")

    with app.app_context(), pytest.raises(LostRace):
        run_project_write(always_lost)
    assert len(calls) == 3

    calls.clear()

    def asserted():
        calls.append(1)
        raise RevisionConflict(1, 2, session_id="x")

    with app.app_context(), pytest.raises(RevisionConflict):
        run_project_write(asserted)
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Guard: no route saves more than one project
# ---------------------------------------------------------------------------

def test_no_route_reaches_the_store_with_more_than_one_project():
    """Routes save one project (save_project_session / save_one_project) and
    delete through delete_user_sessions. The multi-project compatibility entry
    save_user_sessions may not be imported, aliased or called from a route."""
    offenders = []
    for path in sorted(ROUTES_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "save_user_sessions" and path.name != "sessions.py":
                        offenders.append(f"{path.name}:{node.lineno} imports save_user_sessions")
            elif isinstance(node, ast.Call):
                func = node.func
                name = getattr(func, "id", None) or getattr(func, "attr", None)
                if name != "save_user_sessions":
                    continue
                if path.name == "sessions.py":
                    first = node.args[1] if len(node.args) > 1 else None
                    if isinstance(first, ast.Dict) and not first.keys:
                        continue  # delete_user_sessions: deletes only
                offenders.append(f"{path.name}:{node.lineno} calls save_user_sessions")
    assert offenders == []


def test_turn_binding_saves_through_the_single_project_entry():
    source = (ROUTES_DIR / "ai_agent.py").read_text()
    assert "TurnStore(save=lambda *a, **k: _save_turn_project(*a, **k))" in source


# ---------------------------------------------------------------------------
# The change-merge rules
# ---------------------------------------------------------------------------

def test_merge_rules():
    o = {"a": 1, "b": {"x": 1, "y": 1}, "log": [1], "c": [3, 2, 1], "timestamp": "t0"}
    d = {"a": 2, "b": {"x": 1, "y": 2}, "log": [1, "d"], "c": ["d", 3, 2, 1], "timestamp": "t2"}
    c = {"a": 1, "b": {"x": 5, "y": 1}, "log": [1, "c"], "c": ["c", 3, 2, 1], "timestamp": "t1", "new": True}
    assert apply_request_changes(o, d, c) == {
        "a": 2, "b": {"x": 5, "y": 2}, "log": [1, "c", "d"], "c": ["d", "c", 3, 2, 1],
        "timestamp": "t2", "new": True,
    }
    with pytest.raises(ConflictingChange):
        apply_request_changes({"a": 1}, {"a": 2}, {"a": 3})
    with pytest.raises(ConflictingChange):
        apply_request_changes({"a": 1}, {}, {"a": 3})
    assert apply_request_changes({"a": 1, "b": 1}, {"b": 1}, {"a": 1, "b": 2}) == {"b": 2}
    # The same change from both writers is not a conflict.
    assert apply_request_changes({"a": 1}, {"a": 2}, {"a": 2}) == {"a": 2}
    # Identified items rebuilt in another shape by both writers: matched by id.
    assert apply_request_changes(
        {"s": [{"id": "base"}, {"id": "a", "label": "A"}, {"id": "b", "label": "B"}]},
        {"s": [{"id": "a", "label": "A", "norm": 1}, {"id": "b", "label": "B2", "norm": 1}]},
        {"s": [{"id": "a", "label": "A1", "norm": 1}, {"id": "b", "label": "B", "norm": 1}]},
    ) == {"s": [{"id": "a", "label": "A1", "norm": 1}, {"id": "b", "label": "B2", "norm": 1}]}
    with pytest.raises(ConflictingChange):
        apply_request_changes(
            {"s": [{"id": "a", "label": "A"}, {"id": "x"}]},
            {"s": [{"id": "a", "label": "A2"}]},
            {"s": [{"id": "a", "label": "A3"}]},
        )
    # Edits to different items of one list, nothing added.
    assert apply_request_changes(
        {"m": [{"t": "q"}, {"t": "a"}]},
        {"m": [{"t": "q"}, {"t": "a", "feedback": "up"}]},
        {"m": [{"t": "q", "edited": True}, {"t": "a"}]},
    ) == {"m": [{"t": "q", "edited": True}, {"t": "a", "feedback": "up"}]}


# ---------------------------------------------------------------------------
# Acceptance remediation (independent review D1, D2, retry state)
# ---------------------------------------------------------------------------
#
# D1: comments, sharing and the activity feed change the payload without a
# new revision, so the compare-and-swap cannot see them. Every project writer
# now locks the row before it reads it for its decision
# (session_access.lock_project_row). On PostgreSQL another transaction then
# either committed before the lock (kept, tested here) or waits for this save
# (tests/postgres/test_persistence_concurrency.py, real transactions).

def _commits_before_the_lock(monkeypatch, db, session_id, change):
    """Another transaction's write that commits right before a save takes its
    lock: the latest moment it can land once saves lock the row."""
    original = sessions_mod.lock_project_row
    state = {"fired": False}

    def lands_then_lock(row):
        if not state["fired"] and row.session_id == session_id:
            state["fired"] = True
            change(UserSession.query.filter_by(id=row.id).one())
            db.session.commit()
        return original(row)

    monkeypatch.setattr(sessions_mod, "lock_project_row", lands_then_lock)
    return state


def test_every_project_writer_locks_the_row_before_reading_it(app, db, test_user, monkeypatch):
    import app.scenarios_store as scenarios_store
    from app.scenarios_store import save_project_scenarios_data

    _seed(test_user, db, "lock-order")
    calls = []
    for module, name in (
        (sessions_mod, "lock_project_row"), (sessions_mod, "_apply_to_current"),
        (sessions_mod, "_upsert_session_row"), (scenarios_store, "lock_project_row"),
        (scenarios_store, "_compare_and_swap"),
    ):
        original = getattr(module, name)

        def spy(*args, _original=original, _name=f"{module.__name__.rsplit('.', 1)[-1]}.{name}", **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)
        monkeypatch.setattr(module, name, spy)

    with app.test_request_context():
        sessions = load_user_sessions(test_user.id)
        sessions["lock-order"]["notes"] = {"n": 1}
        assert save_project_session(test_user.id, "lock-order", sessions["lock-order"])
        save_project_scenarios_data(test_user.id, "lock-order", {"scenarios": {}})
    assert calls == [
        "sessions.lock_project_row", "sessions._apply_to_current", "sessions._upsert_session_row",
        "scenarios_store.lock_project_row", "scenarios_store._compare_and_swap",
    ], calls


def test_d1_comment_committed_before_the_save_locks_is_kept(app, db, team_project, monkeypatch):
    owner, _member, _org, _headers = team_project

    def comment(row):
        stored = copy.deepcopy(row.payload)
        stored["comments"] = [{"id": "c1", "body": "Looks good"}]
        # What add_project_comment commits: payload only, no new revision.
        row.payload = stored

    with app.test_request_context():
        sessions = load_user_sessions(owner.id)
        sessions["team-p3"]["notes"] = {"owner": "note"}
        state = _commits_before_the_lock(monkeypatch, db, "team-p3", comment)
        assert save_project_session(owner.id, "team-p3", sessions["team-p3"])
    assert state["fired"]
    db.session.expire_all()
    stored = _row("team-p3").payload
    assert stored["notes"] == {"owner": "note"}
    assert [c["body"] for c in stored.get("comments") or []] == ["Looks good"]


def test_d1_unshare_committed_before_an_unrelated_save_is_not_reversed(app, db, team_project, monkeypatch):
    owner, _member, _org, _headers = team_project

    def unshare(row):
        stored = copy.deepcopy(row.payload)
        stored["visibility"] = "private"
        stored["shared_with_user_ids"] = []
        # What update_project_sharing commits: columns and payload, no new revision.
        row.payload = stored
        row.visibility = "private"
        row.shared_with_user_ids = []

    with app.test_request_context():
        sessions = load_user_sessions(owner.id)
        assert sessions["team-p3"].get("visibility") == "team"
        sessions["team-p3"]["notes"] = {"owner": "note"}
        state = _commits_before_the_lock(monkeypatch, db, "team-p3", unshare)
        assert save_project_session(owner.id, "team-p3", sessions["team-p3"])
    assert state["fired"]
    db.session.expire_all()
    row = _row("team-p3")
    assert (row.visibility, row.payload.get("visibility")) == ("private", "private")
    assert row.payload["notes"] == {"owner": "note"}


def test_d1_member_unshared_before_the_lock_cannot_write(app, db, team_project, monkeypatch):
    owner, member, _org, _headers = team_project

    def unshare(row):
        stored = copy.deepcopy(row.payload)
        stored["visibility"] = "private"
        row.payload = stored
        row.visibility = "private"

    with app.test_request_context():
        sessions = sessions_mod.load_sessions_for_thread(member, "team-p3")
        assert "team-p3" in sessions
        sessions["team-p3"]["notes"] = {"member": "note"}
        _commits_before_the_lock(monkeypatch, db, "team-p3", unshare)
        with pytest.raises((SessionForbidden, sessions_mod.SessionNotFound)):
            save_project_session(member.id, "team-p3", sessions["team-p3"])
    db.session.expire_all()
    row = _row("team-p3")
    assert row.visibility == "private"
    assert "member" not in (row.payload.get("notes") or {})


def test_d1_comment_route_decides_access_on_the_locked_row(app, client, db, team_project, monkeypatch):
    owner, _member, _org, headers = team_project
    import app.routes.team as team_mod
    original = team_mod.lock_project_row

    def unshared_just_before(row):
        # The owner's unshare committed while this comment was on its way.
        UserSession.query.filter_by(id=row.id).update(
            {UserSession.visibility: "private"}, synchronize_session=False)
        db.session.commit()
        return original(row)

    monkeypatch.setattr(team_mod, "lock_project_row", unshared_just_before)
    response = client.post("/api/v1/team/projects/team-p3/comments",
                           headers=headers["member"], json={"body": "Late"})
    assert response.status_code == 403, response.get_json()
    db.session.expire_all()
    assert not (_row("team-p3").payload.get("comments") or [])


# D2: identified items are merged by identity before any positional rule.

SNAP_A = {"id": "card-a", "label": "A"}
SNAP_B = {"id": "card-b", "label": "B"}
SNAP_NEW = {"id": "card-new", "label": "New"}


def test_d2_front_insertion_and_an_edit_merge_by_id():
    merged = apply_request_changes(
        {"s": [SNAP_A, SNAP_B]},
        {"s": [{**SNAP_A, "label": "A2"}, SNAP_B]},
        {"s": [SNAP_NEW, SNAP_A, SNAP_B]},
    )
    assert merged == {"s": [SNAP_NEW, {**SNAP_A, "label": "A2"}, SNAP_B]}


def test_d2_snapshot_deactivation_is_not_undone():
    # Removed while someone else added one at the front.
    assert apply_request_changes(
        {"s": [SNAP_A, SNAP_B]}, {"s": [SNAP_B]}, {"s": [SNAP_NEW, SNAP_A, SNAP_B]},
    ) == {"s": [SNAP_NEW, SNAP_B]}
    # Marked inactive while someone else added one at the front.
    assert apply_request_changes(
        {"s": [SNAP_A, SNAP_B]},
        {"s": [{**SNAP_A, "active": False}, SNAP_B]},
        {"s": [SNAP_NEW, SNAP_A, SNAP_B]},
    ) == {"s": [SNAP_NEW, {**SNAP_A, "active": False}, SNAP_B]}
    # Removed while someone else renamed it: refused, never silently resolved.
    with pytest.raises(ConflictingChange):
        apply_request_changes(
            {"s": [SNAP_A, SNAP_B]}, {"s": [SNAP_B]}, {"s": [{**SNAP_A, "label": "A9"}, SNAP_B]},
        )


def test_d2_same_object_refused_and_independent_renames_kept():
    with pytest.raises(ConflictingChange):
        apply_request_changes(
            {"s": [SNAP_A, SNAP_B]},
            {"s": [{**SNAP_A, "label": "mine"}, SNAP_B]},
            {"s": [SNAP_NEW, {**SNAP_A, "label": "theirs"}, SNAP_B]},
        )
    assert apply_request_changes(
        {"s": [SNAP_A, SNAP_B]},
        {"s": [{**SNAP_A, "label": "A2"}, SNAP_B]},
        {"s": [SNAP_A, {**SNAP_B, "label": "B2"}]},
    ) == {"s": [{**SNAP_A, "label": "A2"}, {**SNAP_B, "label": "B2"}]}
    # Concurrent appends of identified items keep the stored order, then this request's.
    assert apply_request_changes(
        {"s": [SNAP_A]}, {"s": [SNAP_A, SNAP_B]}, {"s": [SNAP_A, SNAP_NEW]},
    ) == {"s": [SNAP_A, SNAP_NEW, SNAP_B]}


def test_d2_positional_merge_never_pairs_two_different_ids():
    # One item without an id disables identity matching for the list; the
    # positional rules must still not merge card-a's edit into card-new.
    plain = {"label": "no id"}
    merged = apply_request_changes(
        {"s": [SNAP_A, plain]},
        {"s": [{**SNAP_A, "label": "A2"}, plain]},
        {"s": [SNAP_NEW, SNAP_A, plain]},
    )
    assert merged == {"s": [SNAP_NEW, {**SNAP_A, "label": "A2"}, plain]}


def test_d2_front_insertion_and_rename_through_the_store(app, db, test_user, lands_during_save):
    card_a = {**CARD, "id": "card-a", "project_name": "Option A"}
    _seed(test_user, db, "d2-store", cards=[CARD, card_a])
    result = copy.deepcopy(_row("d2-store").payload["result"])
    result["scorecard_snapshots"] = [{**CARD, "id": "card-new", "project_name": "New"}] + result["scorecard_snapshots"]
    with app.test_request_context():
        sessions = load_user_sessions(test_user.id)
        mine = sessions["d2-store"]
        for snap in mine["result"]["scorecard_snapshots"]:
            if snap.get("id") == "card-a":
                snap["label"] = "Renamed A"
        lands_during_save("d2-store", key="result", value=result)
        assert save_project_session(test_user.id, "d2-store", mine)
    db.session.expire_all()
    snaps = _row("d2-store").payload["result"]["scorecard_snapshots"]
    by_id = {s["id"]: s for s in snaps}
    assert snaps[0]["id"] == "card-new"
    assert by_id["card-a"]["label"] == "Renamed A"
    assert by_id["card-a"]["project_name"] == "Option A"
    assert "label" not in by_id["card-new"] or by_id["card-new"]["label"] != "Renamed A"


# Retry state: what a rolled-back write recorded is forgotten.

def test_retry_forgets_what_a_rolled_back_attempt_wrote(app, db, test_user):
    _seed(test_user, db, "retry-state", notes={"v": "start"})
    attempts = []
    with app.test_request_context():
        sessions_mod._start_project_write_record()  # a fresh request's record
        def unit():
            attempts.append(1)
            project = load_user_sessions(test_user.id)["retry-state"]
            if len(attempts) == 1:
                project["notes"] = {"v": "first attempt"}
                assert save_project_session(test_user.id, "retry-state", project, commit=False)
                raise LostRace(1, 2, session_id="retry-state")
            # Another member changes the same notes after this attempt read them.
            _other_member_saves("retry-state", key="notes", value={"v": "theirs"})
            db.session.commit()
            project["notes"] = {"v": "second attempt"}
            return save_project_session(test_user.id, "retry-state", project)

        # The rolled-back first attempt must not make '/notes' this request's
        # own write: the second attempt's change to the same object is refused.
        with pytest.raises(RevisionConflict) as refused:
            run_project_write(unit)
        assert not isinstance(refused.value, LostRace)
    assert len(attempts) == 2
    db.session.expire_all()
    assert _row("retry-state").payload["notes"] == {"v": "theirs"}


def test_retry_writes_its_change_once_and_later_saves_still_follow_it(app, db, test_user):
    _seed(test_user, db, "retry-once")
    start = _row("retry-once").revision
    attempts = []
    with app.test_request_context():
        sessions_mod._start_project_write_record()  # a fresh request's record
        def unit():
            attempts.append(1)
            project = load_user_sessions(test_user.id)["retry-once"]
            project["chat_history"] = list(project.get("chat_history") or []) + [{"role": "user", "content": "once"}]
            assert save_project_session(test_user.id, "retry-once", project, commit=False)
            if len(attempts) == 1:
                raise LostRace(1, 2, session_id="retry-once")
            db.session.commit()
            return project

        project = run_project_write(unit)
        # A later save in the same request still builds on the committed write.
        project["notes"] = {"after": "retry"}
        assert save_project_session(test_user.id, "retry-once", project)
    assert len(attempts) == 2
    db.session.expire_all()
    row = _row("retry-once")
    assert [m["content"] for m in row.payload["chat_history"]] == ["once"]
    assert row.payload["notes"] == {"after": "retry"}
    assert row.revision == start + 2
