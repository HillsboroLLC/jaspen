"""Undo of an AI turn's changes follows the organization rule (P1, ORG-3).

Undo changes a project, so it is a write: it resolves the organization's
canonical project and requires an editing role, exactly as
conversation/continue does. Any member who may write the project may undo its
latest AI turn, including a colleague's (OD-2, option A); the audit event
records who undid it.

Undo writes ONE project, through the project-scoped scenario store, in one
transaction with the chat record. It reverts only what the turn changed, keeps
every change made since by anyone else, and refuses with the standard
newer-changes conflict (leaving the undo available) when someone has since
changed something the turn changed.

No provider is called. Generation is replaced with a scripted reply.
"""

import copy
import json
import uuid

import pytest
from werkzeug.security import generate_password_hash

from app import db as _db
from app.models import Organization, OrganizationMember, User, UserSession


CONTINUE_URL = "/api/v1/ai-agent/conversation/continue"
UNDO_URL = "/api/v1/ai-agent/conversation/undo-mutations"
PENDING_KEY = "pending_mutation_undo"

REPLY = "I updated the plan's first task."
TURN_TOKENS = 120
STARTING_CREDITS = 1_000_000

CONFIDENTIAL = "Confidential acquisition plan"

PLAN_BEFORE = {
    "project_wbs": {
        "name": CONFIDENTIAL,
        "jira_sync": {"project_key": "JST", "status": "linked"},
        "tasks": [
            {"id": "t1", "title": "Assess vendors", "jira_issue_key": "JST-1"},
            {"id": "t2", "title": "Negotiate terms", "jira_issue_key": "JST-2"},
        ],
    },
    "strategy_objective": "balanced",
}


def _plan_after():
    """What the AI turn changed: the first task's title and a new task."""
    after = copy.deepcopy(PLAN_BEFORE)
    after["project_wbs"]["tasks"][0]["title"] = "Assess vendors (AI revised)"
    after["project_wbs"]["tasks"].append({"id": "t3", "title": "AI-added task"})
    return after


@pytest.fixture(autouse=True)
def _disable_rate_limiting_for_this_file():
    from app import limiter
    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _agent():
    from app.routes import ai_agent
    return ai_agent


def _mk_user(email):
    user = User(
        email=email,
        name=email.split("@")[0].title(),
        password_hash=generate_password_hash("ValidPass1", method="pbkdf2:sha256"),
        subscription_plan="free",
        subscription_status="active",
        credits_remaining=STARTING_CREDITS,
        seat_limit=5,
        max_seats=5,
    )
    _db.session.add(user)
    _db.session.commit()
    return user


def _mk_org(owner, name):
    org = Organization(
        name=name, slug=f"{name.lower()}-{owner.id[:6]}",
        owner_user_id=owner.id, plan_key="free",
    )
    _db.session.add(org)
    _db.session.flush()
    _db.session.add(OrganizationMember(
        organization_id=org.id, user_id=owner.id, role="owner", status="active",
    ))
    owner.active_organization_id = org.id
    _db.session.commit()
    return org


def _settle_meter(user):
    from app.billing_config import consume_credits, release_consumed_credits
    ok, _ = consume_credits(user, 1)
    assert ok
    release_consumed_credits(user, 1)
    _db.session.commit()


def _add_member(org, user, role):
    _db.session.add(OrganizationMember(
        organization_id=org.id, user_id=user.id, role=role, status="active",
    ))
    user.active_organization_id = org.id
    _db.session.commit()
    _settle_meter(user)


def _set_role(org, user, role):
    membership = OrganizationMember.query.filter_by(organization_id=org.id, user_id=user.id).one()
    membership.role = role
    _db.session.commit()


def _headers(app, user):
    from flask_jwt_extended import create_access_token
    with app.app_context():
        return {"Authorization": f"Bearer {create_access_token(identity=str(user.id))}"}


def _balance(user):
    _db.session.rollback()
    _db.session.expire_all()
    return User.query.get(user.id).credits_remaining


def _row(thread_id):
    _db.session.expire_all()
    rows = UserSession.query.filter_by(session_id=thread_id).all()
    assert len(rows) == 1, f"expected one row for {thread_id}, found {len(rows)}"
    return rows[0]


def _seed_project(creator, org, thread_id, *, history=None, visibility="team", scenarios=None):
    from app.routes.sessions import save_user_sessions
    from app.scenarios_store import save_project_scenarios_data
    assert save_user_sessions(creator.id, {thread_id: {
        "session_id": thread_id, "user_id": creator.id, "name": "Shared project",
        "status": "in_progress", "organization_id": org.id if org else None,
        "visibility": visibility, "chat_history": list(history or []),
    }})
    if scenarios is not None:
        save_project_scenarios_data(creator.id, thread_id, copy.deepcopy(scenarios))


def _seed_undoable_turn(creator, org, thread_id, *, turn_author=None, visibility="team",
                        before=None, after=None, record_after=True):
    """A project whose latest assistant turn changed its plan and offers Undo.

    Mirrors what a mutation turn leaves behind: the scenario data as the turn
    left it, the assistant message marked undoable, and the pending undo
    record with the before (and after) state.
    """
    from app.routes.sessions import save_user_sessions
    before = copy.deepcopy(PLAN_BEFORE if before is None else before)
    after = copy.deepcopy(_plan_after() if after is None else after)
    _seed_project(creator, org, thread_id, visibility=visibility, scenarios=after)
    row = _row(thread_id)
    payload = copy.deepcopy(row.payload)
    payload["chat_history"] = [
        {"role": "user", "content": "Revise the first task and add one", "user_id": (turn_author or creator).id},
        {
            "role": "assistant", "content": REPLY,
            "mutations": [{"tool": "update_wbs_task", "success": True}],
            "undo": {"available": True},
        },
    ]
    snapshot = {"thread_id": thread_id, "thread_data": before, "captured_at": "2026-11-13T00:00:00"}
    if record_after:
        snapshot["thread_data_after"] = after
    payload[PENDING_KEY] = {"message_index": 1, "snapshot": snapshot}
    payload.pop("revision", None)
    assert save_user_sessions(creator.id, {thread_id: payload})


def _undo(client, app, actor, thread_id):
    return client.post(UNDO_URL, headers=_headers(app, actor), json={"thread_id": thread_id})


def _assert_undo_applied(thread_id, *, actor, creator):
    row = _row(thread_id)
    assert row.scenarios_json == PLAN_BEFORE
    assert row.user_id == creator.id and row.created_by_user_id == creator.id
    assert row.last_edited_by_user_id == actor.id
    last = row.payload["chat_history"][-1]
    assert last["undo"]["applied"] is True and last["undo"]["available"] is False
    assert PENDING_KEY not in row.payload


def _assert_nothing_changed(thread_id, revision_before):
    row = _row(thread_id)
    assert row.scenarios_json == _plan_after()
    assert int(row.revision) == revision_before
    assert row.payload["chat_history"][-1]["undo"] == {"available": True}
    assert PENDING_KEY in row.payload


@pytest.fixture
def team(app, db):
    """A multi-member organization: owner, administrator, editor, viewer."""
    owner = _mk_user(f"owner-{uuid.uuid4().hex[:8]}@example.test")
    org = _mk_org(owner, f"Team{uuid.uuid4().hex[:6]}")
    _settle_meter(owner)
    members = {"owner": owner}
    for role, key in (("admin", "administrator"), ("collaborator", "editor"), ("viewer", "viewer")):
        member = _mk_user(f"{key}-{uuid.uuid4().hex[:8]}@example.test")
        _add_member(org, member, role)
        members[key] = member
    return {"org": org, **members}


# --------------------------------------------------------------------------
# Role matrix (JASPEN_END_TO_END_ACCEPTANCE_MATRIX section 4; B5, B8, B9)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("actor_key", ["owner", "administrator", "editor"])
def test_an_editing_member_can_undo_the_organizations_latest_ai_turn(client, app, team, actor_key):
    owner, actor = team["owner"], team[actor_key]
    _seed_undoable_turn(owner, team["org"], "t-undo-ok")

    response = _undo(client, app, actor, "t-undo-ok")

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["undo_applied"] is True
    _assert_undo_applied("t-undo-ok", actor=actor, creator=owner)


def test_an_editor_can_undo_a_colleagues_turn_and_the_audit_names_the_editor(client, app, team, monkeypatch):
    agent = _agent()
    audited = []
    monkeypatch.setattr(agent, "_audit_ai_agent_event", lambda event, **kwargs: audited.append((event, kwargs)))
    owner, editor = team["owner"], team["editor"]
    _seed_undoable_turn(owner, team["org"], "t-undo-colleague", turn_author=owner)

    response = _undo(client, app, editor, "t-undo-colleague")

    assert response.status_code == 200, response.get_json()
    _assert_undo_applied("t-undo-colleague", actor=editor, creator=owner)
    assert [event for event, _ in audited] == ["message.mutations_undone"]
    assert audited[0][1]["user"].id == editor.id


def test_a_viewer_cannot_undo(client, app, team):
    _seed_undoable_turn(team["owner"], team["org"], "t-undo-viewer")
    revision_before = int(_row("t-undo-viewer").revision)

    response = _undo(client, app, team["viewer"], "t-undo-viewer")

    assert response.status_code == 403
    assert response.get_json()["code"] == "forbidden"
    _assert_nothing_changed("t-undo-viewer", revision_before)


def test_a_creator_who_is_now_a_viewer_cannot_undo_their_own_project(client, app, team):
    creator = _mk_user(f"demoted-{uuid.uuid4().hex[:8]}@example.test")
    _add_member(team["org"], creator, "collaborator")
    _seed_undoable_turn(creator, team["org"], "t-undo-demoted")
    _set_role(team["org"], creator, "viewer")
    revision_before = int(_row("t-undo-demoted").revision)

    response = _undo(client, app, creator, "t-undo-demoted")

    assert response.status_code == 403
    _assert_nothing_changed("t-undo-demoted", revision_before)


@pytest.mark.parametrize("outsider_kind", ["non-member", "other-organization"])
def test_someone_outside_the_organization_gets_404_and_learns_nothing(client, app, team, outsider_kind):
    _seed_undoable_turn(team["owner"], team["org"], "t-undo-private")
    revision_before = int(_row("t-undo-private").revision)
    outsider = _mk_user(f"outsider-{uuid.uuid4().hex[:8]}@other.test")
    if outsider_kind == "other-organization":
        _mk_org(outsider, f"Other{uuid.uuid4().hex[:6]}")

    response = _undo(client, app, outsider, "t-undo-private")

    assert response.status_code == 404
    body = response.get_data(as_text=True)
    assert CONFIDENTIAL not in body and "JST-" not in body
    _assert_nothing_changed("t-undo-private", revision_before)


def test_solo_owner_undo_is_unchanged(client, app, db):
    """The smallest customer: one member, a private project."""
    user = _mk_user(f"solo-{uuid.uuid4().hex[:8]}@example.test")
    org = _mk_org(user, f"Solo{uuid.uuid4().hex[:6]}")
    _seed_undoable_turn(user, org, "t-undo-solo", visibility="private")

    response = _undo(client, app, user, "t-undo-solo")

    assert response.status_code == 200, response.get_json()
    _assert_undo_applied("t-undo-solo", actor=user, creator=user)


def test_undo_records_written_before_the_after_state_still_restore(client, app, team):
    """Undo records saved by the previous release carry no after-state."""
    _seed_undoable_turn(team["owner"], team["org"], "t-undo-legacy", record_after=False)

    response = _undo(client, app, team["owner"], "t-undo-legacy")

    assert response.status_code == 200, response.get_json()
    _assert_undo_applied("t-undo-legacy", actor=team["owner"], creator=team["owner"])


# --------------------------------------------------------------------------
# One project, nothing lost (C6; stabilization Probe 1 idiom)
# --------------------------------------------------------------------------

def test_undo_of_one_project_does_not_revert_a_concurrent_change_to_another(client, app, team, monkeypatch):
    owner, editor = team["owner"], team["editor"]
    _seed_undoable_turn(owner, team["org"], "t-undo-x")
    _seed_project(editor, team["org"], "t-other-y", history=[{"role": "user", "content": "Y v1"}])
    agent = _agent()
    real_load = agent._authorized_thread_session_for_write

    def load_then_y_changes(user, thread_id):
        # Undo has loaded the caller's projects (Y included); another tab
        # then saves project Y before undo writes anything.
        loaded = real_load(user, thread_id)
        assert "t-other-y" in loaded[0]
        from app.routes.sessions import load_user_sessions, save_user_sessions
        y = load_user_sessions(editor.id)["t-other-y"]
        y["chat_history"] = [{"role": "user", "content": "Y v2 from another tab"}]
        y.pop("revision", None)
        assert save_user_sessions(editor.id, {"t-other-y": y})
        return loaded

    monkeypatch.setattr(agent, "_authorized_thread_session_for_write", load_then_y_changes)

    response = _undo(client, app, editor, "t-undo-x")

    assert response.status_code == 200, response.get_json()
    _assert_undo_applied("t-undo-x", actor=editor, creator=owner)
    assert [m["content"] for m in _row("t-other-y").payload["chat_history"]] == ["Y v2 from another tab"]


def test_undo_refuses_when_a_colleague_changed_what_the_turn_changed(client, app, team):
    from app.scenarios_store import save_project_scenarios_data
    owner, editor = team["owner"], team["editor"]
    _seed_undoable_turn(owner, team["org"], "t-undo-conflict")

    def colleague_edits_the_same_task(current):
        current["project_wbs"]["tasks"][0]["title"] = "Colleague's newer title"
        return current

    save_project_scenarios_data(owner.id, "t-undo-conflict", updater=colleague_edits_the_same_task)
    colleague_state = copy.deepcopy(_row("t-undo-conflict").scenarios_json)
    revision_before = int(_row("t-undo-conflict").revision)

    response = _undo(client, app, editor, "t-undo-conflict")

    assert response.status_code == 409
    body = response.get_json()
    assert body["code"] == "revision_conflict"
    assert body["current_revision"] == revision_before
    assert body["undo_available"] is True
    row = _row("t-undo-conflict")
    assert row.scenarios_json == colleague_state, "the colleague's newer edit must survive"
    assert int(row.revision) == revision_before
    assert row.payload["chat_history"][-1]["undo"] == {"available": True}
    assert PENDING_KEY in row.payload


def test_undo_keeps_a_colleagues_unrelated_later_change(client, app, team):
    from app.scenarios_store import save_project_scenarios_data
    owner, editor = team["owner"], team["editor"]
    _seed_undoable_turn(owner, team["org"], "t-undo-merge")

    # Lists are atomic (the store's rule): a change to another task in the
    # list the turn changed is a conflict (previous test). Changes outside
    # what the turn touched are kept.
    def colleague_changes_something_else(current):
        current["project_wbs"]["owner_note"] = "Colleague's note"
        current["strategy_objective"] = "growth"
        return current

    save_project_scenarios_data(owner.id, "t-undo-merge", updater=colleague_changes_something_else)

    response = _undo(client, app, editor, "t-undo-merge")

    assert response.status_code == 200, response.get_json()
    expected = copy.deepcopy(PLAN_BEFORE)
    expected["project_wbs"]["owner_note"] = "Colleague's note"
    expected["strategy_objective"] = "growth"
    assert _row("t-undo-merge").scenarios_json == expected


def test_undo_restores_a_jira_linked_plan_exactly(client, app, team):
    _seed_undoable_turn(team["owner"], team["org"], "t-undo-jira")

    response = _undo(client, app, team["editor"], "t-undo-jira")

    assert response.status_code == 200, response.get_json()
    wbs = _row("t-undo-jira").scenarios_json["project_wbs"]
    assert wbs["jira_sync"] == {"project_key": "JST", "status": "linked"}
    assert [(t["id"], t["title"], t.get("jira_issue_key")) for t in wbs["tasks"]] == [
        ("t1", "Assess vendors", "JST-1"),
        ("t2", "Negotiate terms", "JST-2"),
    ]


def test_a_failed_restore_leaves_the_undo_available(client, app, team, monkeypatch):
    agent = _agent()
    _seed_undoable_turn(team["owner"], team["org"], "t-undo-fail")
    revision_before = int(_row("t-undo-fail").revision)

    def broken_restore(*_args, **_kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr(agent, "_restore_thread_mutation_snapshot", broken_restore)

    response = _undo(client, app, team["editor"], "t-undo-fail")

    assert response.status_code == 500
    _assert_nothing_changed("t-undo-fail", revision_before)


# --------------------------------------------------------------------------
# End to end: an editor's real turn on a shared project, then undo
# --------------------------------------------------------------------------

@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_an_editors_turn_on_a_shared_project_can_be_undone_exactly(client, app, team, monkeypatch, stream):
    """The snapshot is taken from the organization's project, not from an
    empty personal copy, so the editor's undo restores the real prior state."""
    from app.scenarios_store import save_project_scenarios_data
    agent = _agent()
    owner, editor = team["owner"], team["editor"]
    _seed_project(owner, team["org"], "t-e2e", scenarios=PLAN_BEFORE, history=[
        {"role": "user", "content": "Owner's question"},
        {"role": "assistant", "content": "First answer"},
    ])
    holder = {}

    def tool_changes_the_plan(user_id, thread_id):
        holder["snapshot"] = agent._maybe_capture_turn_undo_snapshot(
            None, tool_name="update_wbs_task", user_id=user_id, thread_id=thread_id,
        )
        after = _plan_after()
        save_project_scenarios_data(user_id, thread_id, updater=lambda _current: copy.deepcopy(after))

    def result():
        return REPLY, {
            "provider": "test", "model": None,
            "input_tokens": 100, "output_tokens": 20, "total_tokens": TURN_TOKENS,
        }, [], [{"tool": "update_wbs_task", "success": True}], holder["snapshot"]

    def generate(*_args, **kwargs):
        tool_changes_the_plan(kwargs["user_id"], kwargs["thread_id"])
        return result()

    def stream_events(*_args, state=None, **kwargs):
        yield {"type": "delta", "text": REPLY}
        tool_changes_the_plan(kwargs["user_id"], kwargs["thread_id"])
        reply, usage, actions, mutations, snapshot = result()
        state.update(reply=reply, usage=usage, actions=actions, mutations=mutations, undo_snapshot=snapshot)

    monkeypatch.setattr(agent, "_generate_assistant_reply", generate)
    monkeypatch.setattr(agent, "_stream_assistant_reply_events", stream_events)
    monkeypatch.setattr(agent, "_classify_decision_kit", lambda *_a, **_k: {
        "kit": "none", "confidence": "high", "evidence_quote": "",
    })

    url = f"{CONTINUE_URL}?stream=1" if stream else CONTINUE_URL
    turn = client.post(url, headers=_headers(app, editor), json={
        "thread_id": "t-e2e", "message": "Revise the first task and add one",
    })
    turn.get_data()
    assert turn.status_code == 200
    row = _row("t-e2e")
    assert row.scenarios_json == _plan_after()
    pending = row.payload[PENDING_KEY]["snapshot"]
    assert pending["thread_data"] == PLAN_BEFORE
    assert pending["thread_data_after"] == _plan_after()

    response = _undo(client, app, editor, "t-e2e")

    assert response.status_code == 200, response.get_json()
    _assert_undo_applied("t-e2e", actor=editor, creator=owner)
    assert UserSession.query.filter_by(session_id="t-e2e").count() == 1
    assert json.dumps(_row("t-e2e").scenarios_json, sort_keys=True) == json.dumps(PLAN_BEFORE, sort_keys=True)


# --------------------------------------------------------------------------
# H-1R remediation 1: undo never erases a newer chat turn
# --------------------------------------------------------------------------

def _commit_from_another_connection(thread_id, mutate):
    """Commit a change to the project's row the way a second server process
    would: on its own connection, invisible to this request's session until
    it re-reads. ``mutate(payload) -> payload``."""
    from sqlalchemy import select, update
    table = UserSession.__table__
    with _db.engine.begin() as conn:
        row_id, payload = conn.execute(
            select(table.c.id, table.c.payload).where(table.c.session_id == thread_id)
        ).one()
        payload = json.loads(payload) if isinstance(payload, str) else copy.deepcopy(payload)
        payload = mutate(payload)
        conn.execute(
            update(table).where(table.c.id == row_id).values(
                payload=payload, revision=table.c.revision + 1,
            )
        )


def _newer_turn(payload):
    payload["chat_history"] = list(payload.get("chat_history") or []) + [
        {"role": "user", "content": "Colleague's newer question"},
        {"role": "assistant", "content": "Colleague's newer answer"},
    ]
    return payload


@pytest.mark.parametrize("actor_key", ["owner", "editor"])
def test_a_newer_turn_saved_between_undos_read_and_write_survives(client, app, team, monkeypatch, actor_key):
    owner, actor = team["owner"], team[actor_key]
    _seed_undoable_turn(owner, team["org"], "t-undo-race")
    revision_loaded = int(_row("t-undo-race").revision)
    agent = _agent()
    real_load = agent._authorized_thread_session_for_write

    def load_then_a_newer_turn_lands(user, thread_id):
        loaded = real_load(user, thread_id)
        assert loaded[2]["revision"] == revision_loaded
        _commit_from_another_connection("t-undo-race", _newer_turn)
        return loaded

    monkeypatch.setattr(agent, "_authorized_thread_session_for_write", load_then_a_newer_turn_lands)

    response = _undo(client, app, actor, "t-undo-race")

    assert response.status_code == 409, response.get_json()
    body = response.get_json()
    assert body["code"] == "revision_conflict"
    assert body["current_revision"] == revision_loaded + 1
    assert body["undo_available"] is True
    row = _row("t-undo-race")
    assert [m["content"] for m in row.payload["chat_history"]][-2:] == [
        "Colleague's newer question", "Colleague's newer answer",
    ], "the newer turn must survive"
    assert row.scenarios_json == _plan_after(), "no partial restoration"
    assert int(row.revision) == revision_loaded + 1
    assert row.payload[PENDING_KEY]["snapshot"]["thread_data"] == PLAN_BEFORE, "undo record kept"
    assert row.payload["chat_history"][1]["undo"] == {"available": True}


def test_undo_succeeds_on_a_fresh_retry_after_a_conflict(client, app, team, monkeypatch):
    """A concurrent change to the project's session (a rename) refuses the
    first attempt; nothing is lost, and a fresh request then succeeds."""
    owner, editor = team["owner"], team["editor"]
    _seed_undoable_turn(owner, team["org"], "t-undo-retry")
    agent = _agent()
    real_load = agent._authorized_thread_session_for_write
    calls = {"n": 0}

    def rename_during_the_first_attempt(user, thread_id):
        loaded = real_load(user, thread_id)
        calls["n"] += 1
        if calls["n"] == 1:
            def rename(payload):
                payload["notes"] = {"colleague": "Added while undo was in flight"}
                return payload
            _commit_from_another_connection("t-undo-retry", rename)
        return loaded

    monkeypatch.setattr(agent, "_authorized_thread_session_for_write", rename_during_the_first_attempt)

    first = _undo(client, app, editor, "t-undo-retry")
    assert first.status_code == 409
    assert _row("t-undo-retry").scenarios_json == _plan_after()

    second = _undo(client, app, editor, "t-undo-retry")

    assert second.status_code == 200, second.get_json()
    _assert_undo_applied("t-undo-retry", actor=editor, creator=owner)
    assert _row("t-undo-retry").payload["notes"] == {"colleague": "Added while undo was in flight"}


# --------------------------------------------------------------------------
# H-1R remediation 2: Undo's evidence can never fail a charged turn
# --------------------------------------------------------------------------

START_URL = "/api/v1/ai-agent/conversation/start"


def _script_plan_changing_turn(monkeypatch):
    """A turn whose tool changes the plan (committed through the store)."""
    from app.scenarios_store import save_project_scenarios_data
    agent = _agent()
    holder = {}

    def tool_changes_the_plan(user_id, thread_id):
        holder["snapshot"] = agent._maybe_capture_turn_undo_snapshot(
            None, tool_name="update_wbs_task", user_id=user_id, thread_id=thread_id,
        )
        after = _plan_after()
        save_project_scenarios_data(user_id, thread_id, updater=lambda _current: copy.deepcopy(after))

    def result():
        return REPLY, {
            "provider": "test", "model": None,
            "input_tokens": 100, "output_tokens": 20, "total_tokens": TURN_TOKENS,
        }, [], [{"tool": "update_wbs_task", "success": True}], holder["snapshot"]

    def generate(*_args, **kwargs):
        tool_changes_the_plan(kwargs["user_id"], kwargs["thread_id"])
        return result()

    def stream_events(*_args, state=None, **kwargs):
        yield {"type": "delta", "text": REPLY}
        tool_changes_the_plan(kwargs["user_id"], kwargs["thread_id"])
        reply, usage, actions, mutations, snapshot = result()
        state.update(reply=reply, usage=usage, actions=actions, mutations=mutations, undo_snapshot=snapshot)

    monkeypatch.setattr(agent, "_generate_assistant_reply", generate)
    monkeypatch.setattr(agent, "_stream_assistant_reply_events", stream_events)
    monkeypatch.setattr(agent, "_classify_decision_kit", lambda *_a, **_k: {
        "kit": "none", "confidence": "high", "evidence_quote": "",
    })


def _post(client, app, actor, url, body, stream):
    response = client.post(f"{url}?stream=1" if stream else url, headers=_headers(app, actor), json=body)
    if not stream:
        return response.status_code, response.get_json()
    events = [
        json.loads(line[6:]) for line in response.get_data(as_text=True).splitlines()
        if line.startswith("data: ")
    ]
    return response.status_code, (events[-1] if events else {})


@pytest.mark.parametrize("route", ["start", "continue"])
@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_a_failed_after_state_read_never_fails_a_charged_turn(client, app, team, monkeypatch, route, stream):
    """Fault injection: the after-state read raises a real database error.
    The turn still saves its reply and is charged exactly once; it simply does
    not offer Undo. The failure is on its own connection, so the turn's
    transaction (and its unsaved reservation) is untouched."""
    from sqlalchemy import text
    agent = _agent()
    owner = team["owner"]
    thread_id = f"t-fault-{route}-{uuid.uuid4().hex[:6]}"
    if route == "continue":
        _seed_project(owner, team["org"], thread_id, scenarios=PLAN_BEFORE, history=[
            {"role": "user", "content": "Owner's question"},
            {"role": "assistant", "content": "First answer"},
        ])
    _script_plan_changing_turn(monkeypatch)
    attempts = []

    def failing_read(conn, **_kwargs):
        attempts.append(1)
        conn.execute(text("SELECT no_such_column FROM no_such_table"))

    monkeypatch.setattr(agent, "_committed_project_scenarios_row", failing_read)
    before = _balance(owner)

    status, payload = _post(client, app, owner, START_URL if route == "start" else CONTINUE_URL, {
        "thread_id": thread_id, "message": "Revise the first task and add one",
    }, stream)

    assert attempts == [1], "the fault must actually have been injected"
    assert status == 200, payload
    assert payload["undo_available"] is False
    row = _row(thread_id)
    assert row.payload["chat_history"][-1]["content"] == REPLY, "the charged reply is saved"
    assert PENDING_KEY not in row.payload
    assert row.scenarios_json == _plan_after(), "the tool's change stands"
    assert before - _balance(owner) == TURN_TOKENS, "charged exactly once"


@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_a_turn_that_creates_the_project_records_its_after_state(client, app, team, monkeypatch, stream):
    """conversation/start: the turn's own project gets its after-state, and
    undo reverts the turn's plan change on it."""
    owner = team["owner"]
    thread_id = f"t-start-{uuid.uuid4().hex[:6]}"
    _script_plan_changing_turn(monkeypatch)

    status, payload = _post(client, app, owner, START_URL, {
        "thread_id": thread_id, "message": "Revise the first task and add one",
    }, stream)

    assert status == 200, payload
    assert payload["undo_available"] is True
    snapshot = _row(thread_id).payload[PENDING_KEY]["snapshot"]
    assert snapshot["row_id"] == _row(thread_id).id and snapshot["thread_data"] is None
    assert snapshot["thread_data_after"] == _plan_after()

    response = _undo(client, app, owner, thread_id)

    assert response.status_code == 200, response.get_json()
    assert not _row(thread_id).scenarios_json


def test_after_state_resolves_the_canonical_row_when_no_row_id_was_captured(app, team):
    """Capture found no row (the project did not exist yet): the after-state
    read resolves the organization's canonical row on its own connection."""
    agent = _agent()
    owner, editor = team["owner"], team["editor"]
    _seed_project(owner, team["org"], "t-late-row", scenarios=_plan_after())
    snapshot = {"thread_id": "t-late-row", "row_id": None, "thread_data": None, "captured_at": "x"}

    completed = agent._complete_turn_undo_snapshot(
        snapshot, user_id=editor.id, organization_id=team["org"].id,
    )

    assert completed["thread_data_after"] == _plan_after()
    assert agent._complete_turn_undo_snapshot(
        {**snapshot, "thread_id": "t-does-not-exist"}, user_id=editor.id, organization_id=team["org"].id,
    ) is None
