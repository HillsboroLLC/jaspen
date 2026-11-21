"""Conversation-turn lifecycle: characterization and defect probes.

One chat turn is: load the project, reserve credits, generate, settle, save.
Three routes run it (start, continue, regenerate), each streamed and not.

This file has two kinds of test:

* CHARACTERIZATION tests pin what production does today so the shared
  lifecycle (``app/conversation_turn.py``) can replace six hand-copied blocks
  without changing an outcome. They must pass before and after.
* PROBES assert the behaviour Jaspen promises (Product Contract section 7:
  no lost work, never charged for a failure). A probe marked
  ``xfail(strict=True)`` is a CONFIRMED DEFECT in today's behaviour. It is
  left failing on purpose: fixing it changes saving or live charging, and
  those changes are approved separately. When a fix lands the strict marker
  turns the unexpected pass into a failure, so the marker has to be removed
  deliberately.

No provider is called. Generation is replaced with a scripted reply.
"""

import json
import uuid

import pytest
from werkzeug.security import generate_password_hash

from app import db as _db
from app.models import AIOperation, Organization, OrganizationMember, UsageEvent, User, UserSession


CONTINUE_URL = "/api/v1/ai-agent/conversation/continue"
START_URL = "/api/v1/ai-agent/conversation/start"
REGENERATE_URL = "/api/v1/ai-agent/conversation/regenerate"

REPLY = "What outcome and time horizon should guide this decision?"
TURN_TOKENS = 120
STARTING_CREDITS = 1_000_000


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


def _usage():
    return {
        "provider": "test", "model": None,
        "input_tokens": 100, "output_tokens": 20, "total_tokens": TURN_TOKENS,
    }


def _mk_user(email, *, plan="free", credits=STARTING_CREDITS):
    user = User(
        email=email,
        name=email.split("@")[0].title(),
        password_hash=generate_password_hash("ValidPass1", method="pbkdf2:sha256"),
        subscription_plan=plan,
        subscription_status="active",
        credits_remaining=credits,
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
    """The first metered action aligns a new account to its plan allowance.
    Do that up front so each test measures only its own turn."""
    from app.billing_config import consume_credits, release_consumed_credits
    ok, _ = consume_credits(user, 1)
    assert ok
    release_consumed_credits(user, 1)
    _db.session.commit()


def _headers(app, user):
    from flask_jwt_extended import create_access_token
    with app.app_context():
        return {"Authorization": f"Bearer {create_access_token(identity=str(user.id))}"}


def _seed(user, thread_id, history=None, name="Project"):
    from app.routes.sessions import save_user_sessions
    assert save_user_sessions(user.id, {thread_id: {
        "session_id": thread_id, "user_id": user.id, "name": name,
        "status": "in_progress", "chat_history": list(history or []),
    }})


def _stored(thread_id):
    _db.session.expire_all()
    row = UserSession.query.filter_by(session_id=thread_id).one()
    return row.payload or {}


def _balance(user):
    """The balance a NEW request would see: only what was committed."""
    _db.session.rollback()
    _db.session.expire_all()
    return User.query.get(user.id).credits_remaining


def _sse_events(response):
    return [
        json.loads(line[6:])
        for line in response.get_data(as_text=True).splitlines()
        if line.startswith("data: ")
    ]


def _roles(payload):
    return [str(m.get("role")) for m in payload.get("chat_history") or []]


def _script_generation(
    monkeypatch, *, during=None, fail_with=None, calls=None, captured=None,
    result_factory=None,
):
    """Replace both generation entry points with a scripted reply.

    ``during`` runs in the middle of generation, where a real turn spends its
    seconds; ``fail_with`` raises instead of replying.
    """
    agent = _agent()

    def result():
        if result_factory is not None:
            return result_factory()
        return REPLY, _usage(), [], [], None

    def generate(*_args, **_kwargs):
        if calls is not None:
            calls.append("generate")
        if captured is not None:
            captured.append({"kind": "json", "args": _args, "kwargs": _kwargs})
        if during is not None:
            during()
        if fail_with is not None:
            raise fail_with
        return result()

    def stream(*_args, state=None, **_kwargs):
        if calls is not None:
            calls.append("stream")
        if captured is not None:
            captured.append({"kind": "stream", "args": _args, "kwargs": {**_kwargs, "state": state}})
        yield {"type": "delta", "text": REPLY[:10]}
        if during is not None:
            during()
        if fail_with is not None:
            raise fail_with
        yield {"type": "delta", "text": REPLY[10:]}
        reply, usage, actions, mutations, undo_snapshot = result()
        state["reply"] = reply
        state["usage"] = usage
        state["actions"] = actions
        state["mutations"] = mutations
        state["undo_snapshot"] = undo_snapshot

    monkeypatch.setattr(agent, "_generate_assistant_reply", generate)
    monkeypatch.setattr(agent, "_stream_assistant_reply_events", stream)
    monkeypatch.setattr(agent, "_classify_decision_kit", lambda *_a, **_k: {
        "kit": "none", "confidence": "high", "evidence_quote": "",
    })


@pytest.fixture
def solo(app, db):
    """A single-user organization: the smallest customer Jaspen has."""
    user = _mk_user(f"solo-{uuid.uuid4().hex[:8]}@example.test")
    org = _mk_org(user, f"Solo{uuid.uuid4().hex[:6]}")
    _settle_meter(user)
    return {"user": user, "org": org, "headers": _headers(app, user)}


def _post_turn(client, url, headers, body, *, stream):
    target = f"{url}?stream=1" if stream else url
    response = client.post(target, headers=headers, json=body)
    if not stream:
        return response.status_code, response.get_json()
    events = _sse_events(response)
    final = events[-1] if events else {}
    return response.status_code, final


# --------------------------------------------------------------------------
# CHARACTERIZATION: outcomes the shared lifecycle must preserve
# --------------------------------------------------------------------------

@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_continue_charges_actual_usage_and_saves_the_turn(client, db, solo, monkeypatch, stream):
    _script_generation(monkeypatch)
    _seed(solo["user"], "t-cont")
    before = _balance(solo["user"])

    status, payload = _post_turn(
        client, CONTINUE_URL, solo["headers"],
        {"thread_id": "t-cont", "message": "Should we bid?"}, stream=stream,
    )

    assert status == 200, payload
    assert payload["reply"] == REPLY
    assert payload["credits"]["charged"] > 0  # shown in display units
    assert before - _balance(solo["user"]) == TURN_TOKENS
    assert _roles(_stored("t-cont")) == ["user", "assistant"]
    assert payload["assistant_message_index"] == 1
    assert payload["organization_id"] == solo["org"].id


@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_start_charges_actual_usage_and_creates_the_org_owned_thread(client, db, solo, monkeypatch, stream):
    _script_generation(monkeypatch)
    thread_id = f"thread_{uuid.uuid4().hex[:16]}"
    before = _balance(solo["user"])

    status, payload = _post_turn(
        client, START_URL, solo["headers"],
        {"thread_id": thread_id, "message": "Should we bid on the Westminster project?"},
        stream=stream,
    )

    assert status == 200, payload
    assert payload["reply"] == REPLY
    assert payload["credits"]["charged"] > 0  # shown in display units
    assert before - _balance(solo["user"]) == TURN_TOKENS
    assert _roles(_stored(thread_id)) == ["user", "assistant"]
    row = UserSession.query.filter_by(session_id=thread_id).one()
    assert row.organization_id == solo["org"].id
    assert row.created_by_user_id == solo["user"].id


@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_regenerate_charges_once_and_keeps_the_old_reply_as_an_alternative(client, db, solo, monkeypatch, stream):
    _script_generation(monkeypatch)
    _seed(solo["user"], "t-regen", history=[
        {"role": "user", "content": "Should we bid?"},
        {"role": "assistant", "content": "First answer."},
    ])
    before = _balance(solo["user"])

    status, payload = _post_turn(
        client, REGENERATE_URL, solo["headers"], {"thread_id": "t-regen"}, stream=stream,
    )

    assert status == 200, payload
    assert payload["regenerated"] is True
    assert payload["alternatives_count"] == 1
    assert before - _balance(solo["user"]) == TURN_TOKENS
    history = _stored("t-regen")["chat_history"]
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[-1]["content"] == REPLY
    assert history[-1]["alternatives"][0]["content"] == "First answer."


@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_failed_generation_is_free_and_keeps_the_user_message(client, db, solo, monkeypatch, stream):
    _script_generation(monkeypatch, fail_with=RuntimeError("provider exploded"))
    _seed(solo["user"], "t-fail")
    before = _balance(solo["user"])

    target = f"{CONTINUE_URL}?stream=1" if stream else CONTINUE_URL
    try:
        response = client.post(target, headers=solo["headers"], json={
            "thread_id": "t-fail", "message": "Should we bid?",
        })
    except RuntimeError:
        response = None  # the JSON route re-raises; Flask's test client propagates it

    if stream:
        assert _sse_events(response)[-1] == {"type": "error", "error": "Streaming failed"}
    assert _balance(solo["user"]) == before
    # A partial reply is never saved as if it were the answer.
    assert _roles(_stored("t-fail")) == ["user"]


@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_retry_with_the_same_idempotency_key_replays_without_a_second_charge(client, db, solo, monkeypatch, stream):
    calls = []
    _script_generation(monkeypatch, calls=calls)
    _seed(solo["user"], "t-idem")
    headers = {**solo["headers"], "X-Jaspen-Idempotency-Key": f"k-{uuid.uuid4().hex}"}
    body = {"thread_id": "t-idem", "message": "Should we bid?"}
    before = _balance(solo["user"])

    first_status, first = _post_turn(client, CONTINUE_URL, headers, body, stream=stream)
    second_status, second = _post_turn(client, CONTINUE_URL, headers, body, stream=stream)

    assert (first_status, second_status) == (200, 200)
    assert second.get("idempotent_replay") is True
    assert second["reply"] == first["reply"]
    assert len(calls) == 1
    assert before - _balance(solo["user"]) == TURN_TOKENS
    assert _roles(_stored("t-idem")) == ["user", "assistant"]


def test_same_idempotency_key_with_a_different_request_is_refused(client, db, solo, monkeypatch):
    _script_generation(monkeypatch)
    _seed(solo["user"], "t-idem2")
    headers = {**solo["headers"], "X-Jaspen-Idempotency-Key": f"k-{uuid.uuid4().hex}"}

    first = client.post(CONTINUE_URL, headers=headers, json={"thread_id": "t-idem2", "message": "One"})
    second = client.post(CONTINUE_URL, headers=headers, json={"thread_id": "t-idem2", "message": "Two"})

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.get_json()["code"] == "idempotency_conflict"


# --------------------------------------------------------------------------
# ORGANIZATION ISOLATION
# --------------------------------------------------------------------------

@pytest.mark.parametrize("url,body", [
    (CONTINUE_URL, {"thread_id": "t-private", "message": "Let me in"}),
    (REGENERATE_URL, {"thread_id": "t-private"}),
], ids=["continue", "regenerate"])
def test_another_organization_cannot_reach_or_change_a_thread(client, app, db, solo, monkeypatch, url, body):
    calls = []
    _script_generation(monkeypatch, calls=calls)
    history = [
        {"role": "user", "content": "Confidential bid question"},
        {"role": "assistant", "content": "Confidential answer"},
    ]
    _seed(solo["user"], "t-private", history=history)
    outsider = _mk_user(f"outsider-{uuid.uuid4().hex[:8]}@other.test")
    _mk_org(outsider, f"Other{uuid.uuid4().hex[:6]}")
    _settle_meter(outsider)
    outsider_before = _balance(outsider)
    owner_before = _balance(solo["user"])

    response = client.post(url, headers=_headers(app, outsider), json=body)

    assert response.status_code == 404
    assert "Confidential" not in response.get_data(as_text=True)
    assert calls == []
    assert _stored("t-private")["chat_history"] == history
    assert _balance(outsider) == outsider_before
    assert _balance(solo["user"]) == owner_before
    assert UserSession.query.filter_by(session_id="t-private").count() == 1


def test_usage_is_charged_to_the_caller_never_to_another_member(client, app, db, solo, monkeypatch):
    """A second member's turn must not move the first member's balance."""
    _script_generation(monkeypatch)
    teammate = _mk_user(f"mate-{uuid.uuid4().hex[:8]}@example.test")
    _db.session.add(OrganizationMember(
        organization_id=solo["org"].id, user_id=teammate.id, role="collaborator", status="active",
    ))
    teammate.active_organization_id = solo["org"].id
    _db.session.commit()
    _settle_meter(teammate)
    _seed(teammate, "t-mate")
    owner_before = _balance(solo["user"])
    mate_before = _balance(teammate)

    response = client.post(CONTINUE_URL, headers=_headers(app, teammate), json={
        "thread_id": "t-mate", "message": "Should we bid?",
    })

    assert response.status_code == 200, response.get_json()
    assert mate_before - _balance(teammate) == TURN_TOKENS
    assert _balance(solo["user"]) == owner_before


# --------------------------------------------------------------------------
# PROBES: promised behaviour. xfail(strict) = confirmed defect today.
# --------------------------------------------------------------------------

def _other_tab_adds_a_turn(user, thread_id, text):
    """What a second tab, or the sidebar, commits while this turn generates."""
    from app.routes.sessions import save_user_sessions

    def write():
        row = UserSession.query.filter_by(session_id=thread_id).one()
        payload = dict(row.payload or {})
        payload["chat_history"] = list(payload.get("chat_history") or []) + [
            {"role": "user", "content": text},
        ]
        assert save_user_sessions(user.id, {thread_id: payload})
    return write


# Fixed (stabilization B2, chat): a turn used to save every project it loaded
# at the start, reverting a turn another tab or the sidebar had saved to a
# DIFFERENT project while this one was generating.
@pytest.mark.parametrize("url,stream", [
    (CONTINUE_URL, False), (CONTINUE_URL, True), (REGENERATE_URL, False), (REGENERATE_URL, True),
], ids=["continue-json", "continue-stream", "regenerate-json", "regenerate-stream"])
def test_turn_does_not_revert_another_project(client, db, solo, monkeypatch, url, stream):
    user = solo["user"]
    _seed(user, "t-a", history=[
        {"role": "user", "content": "Question A"},
        {"role": "assistant", "content": "Answer A"},
    ])
    _seed(user, "t-b", name="Other project")
    _script_generation(monkeypatch, during=_other_tab_adds_a_turn(user, "t-b", "Turn from the sidebar"))
    body = {"thread_id": "t-a"} if url == REGENERATE_URL else {"thread_id": "t-a", "message": "More on A"}

    status, payload = _post_turn(client, url, solo["headers"], body, stream=stream)

    assert status == 200, payload
    assert [m["content"] for m in _stored("t-b")["chat_history"]] == ["Turn from the sidebar"]


@pytest.mark.xfail(strict=True, reason=(
    "CONFIRMED DEFECT: when the reply cannot be saved, the JSON routes have "
    "already committed the charge, so the customer pays for a reply they "
    "never received (Product Contract 7.5)."
))
@pytest.mark.parametrize("url", [CONTINUE_URL, REGENERATE_URL], ids=["continue", "regenerate"])
def test_probe_json_turn_is_free_when_the_reply_cannot_be_saved(client, db, solo, monkeypatch, url):
    agent = _agent()
    _script_generation(monkeypatch)
    _seed(solo["user"], "t-save", history=[
        {"role": "user", "content": "Question"},
        {"role": "assistant", "content": "Answer"},
    ])
    before = _balance(solo["user"])
    real_save = agent._save_turn_project
    state = {"generated": False}
    monkeypatch.setattr(agent, "_generate_assistant_reply", lambda *a, **k: (
        state.update(generated=True) or (REPLY, _usage(), [], [], None)
    ))

    def failing_save(*args, **kwargs):
        if state["generated"]:
            _db.session.rollback()  # what the project store does when it fails
            return False
        return real_save(*args, **kwargs)

    monkeypatch.setattr(agent, "_save_turn_project", failing_save)
    body = {"thread_id": "t-save"} if url == REGENERATE_URL else {"thread_id": "t-save", "message": "More"}

    response = client.post(url, headers=solo["headers"], json=body)

    assert response.status_code == 500
    assert _balance(solo["user"]) == before


@pytest.mark.xfail(strict=True, reason=(
    "CONFIRMED DEFECT: a streamed turn has no cleanup for a dropped "
    "connection. If anything committed during generation (a tool call or a "
    "save does), the reservation is kept and never released."
))
@pytest.mark.parametrize("url", [CONTINUE_URL, REGENERATE_URL], ids=["continue", "regenerate"])
def test_probe_disconnect_mid_stream_releases_the_reservation(client, db, solo, monkeypatch, url):
    # A tool call or project save commits mid-turn; model that with a commit.
    committed = []

    def tool_commits():
        _db.session.commit()
        committed.append(True)

    _script_generation(monkeypatch, during=tool_commits)
    _seed(solo["user"], "t-drop", history=[
        {"role": "user", "content": "Question"},
        {"role": "assistant", "content": "Answer"},
    ])
    before = _balance(solo["user"])
    body = {"thread_id": "t-drop"} if url == REGENERATE_URL else {"thread_id": "t-drop", "message": "More"}

    response = client.post(f"{url}?stream=1", headers=solo["headers"], json=body, buffered=False)
    chunks = iter(response.response)
    while not committed:
        next(chunks)      # read until the mid-generation commit has happened
    response.close()      # the browser tab closes

    assert _balance(solo["user"]) == before


def test_disconnect_before_anything_commits_costs_nothing(client, db, solo, monkeypatch):
    """Characterization of the lucky case: with no commit during generation
    the reservation was never written, so the request teardown discards it."""
    _script_generation(monkeypatch)
    _seed(solo["user"], "t-drop2")
    before = _balance(solo["user"])

    response = client.post(
        f"{CONTINUE_URL}?stream=1", headers=solo["headers"],
        json={"thread_id": "t-drop2", "message": "More"}, buffered=False,
    )
    next(iter(response.response))
    response.close()

    assert _balance(solo["user"]) == before
    assert _roles(_stored("t-drop2")) == ["user"]


def test_streamed_turn_is_free_when_the_reply_cannot_be_saved(client, db, solo, monkeypatch):
    """Characterization: start/continue streams settle in memory and commit
    with the save, so a failed save takes the charge down with it. (Regenerate
    streams commit the charge first; see the JSON probe above.)"""
    agent = _agent()
    _script_generation(monkeypatch)
    _seed(solo["user"], "t-save2")
    before = _balance(solo["user"])
    real_save = agent._save_turn_project
    saves = {"n": 0}

    def failing_save(*args, **kwargs):
        saves["n"] += 1
        if saves["n"] >= 2:
            _db.session.rollback()
            return False
        return real_save(*args, **kwargs)

    monkeypatch.setattr(agent, "_save_turn_project", failing_save)

    response = client.post(f"{CONTINUE_URL}?stream=1", headers=solo["headers"], json={
        "thread_id": "t-save2", "message": "More",
    })

    assert _sse_events(response)[-1] == {"type": "error", "error": "Failed to persist conversation state"}
    assert _balance(solo["user"]) == before
    assert _roles(_stored("t-save2")) == ["user"]


# --------------------------------------------------------------------------
# PROJECT-SCOPED SAVING: more of the same guarantee
# --------------------------------------------------------------------------

@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_starting_a_new_thread_does_not_revert_another_project(client, db, solo, monkeypatch, stream):
    user = solo["user"]
    _seed(user, "t-existing", name="Existing project")
    _script_generation(monkeypatch, during=_other_tab_adds_a_turn(user, "t-existing", "Typed in the other tab"))
    thread_id = f"thread_{uuid.uuid4().hex[:16]}"

    status, payload = _post_turn(
        client, START_URL, solo["headers"],
        {"thread_id": thread_id, "message": "A brand new decision"}, stream=stream,
    )

    assert status == 200, payload
    assert [m["content"] for m in _stored("t-existing")["chat_history"]] == ["Typed in the other tab"]
    assert _roles(_stored(thread_id)) == ["user", "assistant"]


@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_provider_outage_keeps_the_message_without_reverting_another_project(client, db, solo, monkeypatch, stream):
    """The outage path saves too. It must use the same one-project boundary."""
    agent = _agent()
    user = solo["user"]
    _seed(user, "t-out")
    _seed(user, "t-other", name="Other project")
    outage = agent.ConversationProviderUnavailable("all providers down")
    _script_generation(
        monkeypatch, fail_with=outage,
        during=_other_tab_adds_a_turn(user, "t-other", "Saved during the outage"),
    )
    before = _balance(user)

    status, payload = _post_turn(
        client, CONTINUE_URL, solo["headers"],
        {"thread_id": "t-out", "message": "Should we bid?"}, stream=stream,
    )

    assert payload["code"] == "analysis_unavailable"
    assert payload["message_saved"] is True
    stored = _stored("t-out")
    assert _roles(stored) == ["user"]
    assert stored["pending_ai_retry"] == {"message": "Should we bid?"}
    assert [m["content"] for m in _stored("t-other")["chat_history"]] == ["Saved during the outage"]
    assert _balance(user) == before


def _add_member(org, user, role="collaborator"):
    _db.session.add(OrganizationMember(
        organization_id=org.id, user_id=user.id, role=role, status="active",
    ))
    user.active_organization_id = org.id
    _db.session.commit()
    _settle_meter(user)


def _seed_team_thread(owner, org, thread_id, history=None):
    from app.routes.sessions import save_user_sessions
    assert save_user_sessions(owner.id, {thread_id: {
        "session_id": thread_id, "user_id": owner.id, "name": "Shared project",
        "status": "in_progress", "organization_id": org.id, "visibility": "team",
        "chat_history": list(history or []),
    }})


def test_a_colleagues_turn_lands_in_the_organizations_one_project(client, app, db, solo, monkeypatch):
    """Two members, one organization-owned project: the colleague's turn
    updates the single canonical row, is charged to the colleague, and leaves
    the owner's other project (changed meanwhile) alone."""
    owner, org = solo["user"], solo["org"]
    colleague = _mk_user(f"colleague-{uuid.uuid4().hex[:8]}@example.test")
    _add_member(org, colleague)
    _seed_team_thread(owner, org, "t-shared", history=[
        {"role": "user", "content": "Owner's question"},
        {"role": "assistant", "content": "First answer"},
    ])
    _seed(owner, "t-owner-private", name="Owner only")
    _seed(colleague, "t-colleague-own", name="Colleague only")
    _script_generation(monkeypatch, during=lambda: (
        _other_tab_adds_a_turn(owner, "t-owner-private", "Owner kept working")(),
        _other_tab_adds_a_turn(colleague, "t-colleague-own", "Colleague's other tab")(),
    ))
    owner_before, colleague_before = _balance(owner), _balance(colleague)

    response = client.post(CONTINUE_URL, headers=_headers(app, colleague), json={
        "thread_id": "t-shared", "message": "Colleague's follow-up",
    })

    assert response.status_code == 200, response.get_json()
    rows = UserSession.query.filter_by(session_id="t-shared").all()
    assert len(rows) == 1, "the colleague must not fork the organization's project"
    row = rows[0]
    assert row.organization_id == org.id
    assert row.user_id == owner.id and row.created_by_user_id == owner.id
    assert row.last_edited_by_user_id == colleague.id
    assert [m["content"] for m in row.payload["chat_history"]][-2:] == ["Colleague's follow-up", REPLY]
    assert [m["content"] for m in _stored("t-owner-private")["chat_history"]] == ["Owner kept working"]
    assert [m["content"] for m in _stored("t-colleague-own")["chat_history"]] == ["Colleague's other tab"]
    assert colleague_before - _balance(colleague) == TURN_TOKENS
    assert _balance(owner) == owner_before


def test_a_viewer_cannot_add_a_turn_to_the_organizations_project(client, app, db, solo, monkeypatch):
    calls = []
    _script_generation(monkeypatch, calls=calls)
    owner, org = solo["user"], solo["org"]
    viewer = _mk_user(f"viewer-{uuid.uuid4().hex[:8]}@example.test")
    _add_member(org, viewer, role="viewer")
    history = [{"role": "user", "content": "Owner's question"}]
    _seed_team_thread(owner, org, "t-readonly", history=history)
    before = _balance(viewer)

    response = client.post(CONTINUE_URL, headers=_headers(app, viewer), json={
        "thread_id": "t-readonly", "message": "Let me write",
    })

    assert response.status_code == 403
    assert calls == []
    assert _stored("t-readonly")["chat_history"] == history
    assert _balance(viewer) == before


def test_a_turn_advances_the_projects_revision_once_per_content_change(client, db, solo, monkeypatch):
    """Revision protection is the store's. A turn must keep feeding it."""
    _script_generation(monkeypatch)
    _seed(solo["user"], "t-rev")
    _seed(solo["user"], "t-untouched")
    row = UserSession.query.filter_by(session_id="t-rev").one()
    untouched = UserSession.query.filter_by(session_id="t-untouched").one()
    rev_before, untouched_before = int(row.revision or 1), int(untouched.revision or 1)

    response = client.post(CONTINUE_URL, headers=solo["headers"], json={
        "thread_id": "t-rev", "message": "Should we bid?",
    })

    assert response.status_code == 200
    _db.session.expire_all()
    assert int(UserSession.query.filter_by(session_id="t-rev").one().revision) > rev_before
    assert int(UserSession.query.filter_by(session_id="t-untouched").one().revision) == untouched_before


# --------------------------------------------------------------------------
# FINAL F1 ACCEPTANCE: full route seams
# --------------------------------------------------------------------------

@pytest.mark.parametrize("route", ["start", "continue"])
@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_real_tool_change_saves_its_project_without_overwriting_another_project(
    client, db, solo, monkeypatch, route, stream,
):
    """Exercise a real mutation tool, not a fabricated action payload.

    The tool commits the target project's rubric during generation. Another
    tab then commits a turn to a different project. Final turn persistence
    must retain both changes and expose the real tool result to the caller.
    """
    agent = _agent()
    user = solo["user"]
    target = f"t-tool-{route}-{uuid.uuid4().hex[:6]}"
    other = f"t-tool-other-{uuid.uuid4().hex[:6]}"
    if route == "continue":
        _seed(user, target, name="Tool target")
    _seed(user, other, name="Other project")
    result_holder = {}
    user_message = "Use delivery confidence at 60% and cost at 40%."

    def run_real_tool_then_other_tab():
        result_holder["result"] = agent._execute_mutation_tool(
            "set_scoring_rubric",
            {"criteria": [
                {"label": "Delivery confidence", "weight": 60},
                {"label": "Cost", "weight": 40},
            ]},
            user=user,
            user_id=user.id,
            thread_id=target,
            user_message=user_message,
        )
        assert result_holder["result"]["ok"] is True
        _other_tab_adds_a_turn(user, other, "Saved in the other tab")()

    def generated_result():
        result = result_holder["result"]
        action = {
            "tool": "set_scoring_rubric",
            "input": {"criteria": [
                {"label": "Delivery confidence", "weight": 60},
                {"label": "Cost", "weight": 40},
            ]},
            "result": result,
        }
        mutation = {
            "tool": "set_scoring_rubric",
            "success": True,
            "result_summary": agent._mutation_result_summary("set_scoring_rubric", result),
            "error": None,
            "code": None,
        }
        return REPLY, _usage(), [action], [mutation], None

    _script_generation(
        monkeypatch,
        during=run_real_tool_then_other_tab,
        result_factory=generated_result,
    )
    url = START_URL if route == "start" else CONTINUE_URL
    body = {"thread_id": target, "message": user_message}

    status, payload = _post_turn(client, url, solo["headers"], body, stream=stream)

    assert status == 200, payload
    assert payload["actions"][0]["tool"] == "set_scoring_rubric"
    assert payload["actions"][0]["result"]["ok"] is True
    assert payload["mutations"] == payload["tool_results"]
    assert payload["mutations"][0]["success"] is True
    target_payload = _stored(target)
    assert [item["label"] for item in target_payload["scoring_rubric"]["criteria"]] == [
        "Delivery confidence", "Cost",
    ]
    assert [item["content"] for item in _stored(other)["chat_history"]] == ["Saved in the other tab"]


@pytest.mark.parametrize("route", ["start", "continue", "regenerate"])
@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_settlement_refusal_is_returned_without_saving_a_reply_or_audit(
    client, db, solo, monkeypatch, route, stream,
):
    agent = _agent()
    _script_generation(monkeypatch)
    refusal = {
        "error": "Out of Thinking Power",
        "code": "thinking_power_exhausted",
        "required": TURN_TOKENS,
    }
    monkeypatch.setattr(agent, "_settle_reserved_credits", lambda *_a, **_k: {
        "ok": False,
        "charged": 0,
        "remaining": 0,
        "payload": refusal,
    })
    thread_id = f"t-settle-{route}-{uuid.uuid4().hex[:6]}"
    if route != "start":
        _seed(solo["user"], thread_id, history=_TWO_TURNS if route == "regenerate" else None)
    before = _balance(solo["user"])
    url = {"start": START_URL, "continue": CONTINUE_URL, "regenerate": REGENERATE_URL}[route]
    body = {"thread_id": thread_id}
    if route != "regenerate":
        body["message"] = "More evidence"

    status, payload = _post_turn(client, url, solo["headers"], body, stream=stream)

    if stream:
        assert status == 200
        assert payload == {"type": "error", **refusal}
    else:
        assert status == 402
        assert payload == refusal
    assert _balance(solo["user"]) == before
    assert _roles(_stored(thread_id)) == (
        ["user", "assistant"] if route == "regenerate" else ["user"]
    )
    assert UsageEvent.query.filter_by(thread_id=thread_id).count() == 0
    # P4.0 (authorized evidence change): the refused turn keeps its one
    # claimed operation, closed as a failure that charged nothing. Before
    # P4.0 a refused turn left no operation at all.
    operation = AIOperation.query.filter_by(thread_id=thread_id).one()
    assert operation.status == "failed"
    assert operation.error_code == "thinking_power_exhausted"
    assert operation.charged_credits == 0
    assert operation.metadata_json["turn_lifecycle"]["outcome"] == "refused_at_settle"


@pytest.mark.parametrize("route", ["start", "continue", "regenerate"])
@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_generation_receives_the_exact_route_arguments(
    client, db, solo, monkeypatch, route, stream,
):
    captured = []
    _script_generation(monkeypatch, captured=captured)
    thread_id = f"t-args-{route}-{uuid.uuid4().hex[:6]}"
    if route != "start":
        _seed(solo["user"], thread_id, history=_TWO_TURNS if route == "regenerate" else None)
    url = {"start": START_URL, "continue": CONTINUE_URL, "regenerate": REGENERATE_URL}[route]
    body = {"thread_id": thread_id}
    if route != "regenerate":
        body["message"] = "Exact generation input"

    status, payload = _post_turn(client, url, solo["headers"], body, stream=stream)

    assert status == 200, payload
    assert len(captured) == 1
    call = captured[0]
    assert call["kind"] == ("stream" if stream else "json")
    args, kwargs = call["args"], call["kwargs"]
    expected_message = "Owner's question" if route == "regenerate" else "Exact generation input"
    assert args[0] == expected_message
    assert [item["role"] for item in args[1]] == ["user"]
    assert args[1][-1]["content"] == expected_message
    assert args[2] == kwargs["session"]["readiness"]
    assert args[3]["model_type"] == payload["model_type"]
    assert args[3]["allowed_model_types"] == payload["allowed_model_types"]
    assert kwargs["user"] is solo["user"]
    assert kwargs["user_id"] == solo["user"].id
    assert kwargs["thread_id"] == thread_id
    assert kwargs["session"]["session_id"] == thread_id
    assert kwargs["intake_context"] == kwargs["session"].get("intake_context")
    assert kwargs["view_context"] == kwargs["session"].get("view_context")
    assert kwargs["context_budget"] == {
        "recent_turns": 16,
        "include_rolling_summary": True,
    }
    expected_keys = {
        "context_budget", "session", "user", "user_id", "thread_id",
        "intake_context", "view_context",
    }
    if route == "regenerate":
        expected_keys.add("disable_mutations")
        assert kwargs["disable_mutations"] is True
    else:
        expected_keys.add("attachments")
        assert kwargs["attachments"] == []
    # P2a: every turn route hands generation the project it authorized, so
    # tools and context inside the turn act on exactly that project.
    expected_keys.add("project")
    assert kwargs["project"].project_id == thread_id
    assert kwargs["project"].actor_user_id == str(solo["user"].id)
    assert kwargs["project"].can_write is True
    if stream:
        expected_keys.add("state")
        assert isinstance(kwargs["state"], dict)
    assert set(kwargs) == expected_keys


@pytest.mark.parametrize("route", ["start", "continue", "regenerate"])
@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_each_route_persists_one_usage_event_and_one_ai_operation_audit(
    client, db, solo, monkeypatch, route, stream,
):
    _script_generation(monkeypatch)
    thread_id = f"t-audit-{route}-{uuid.uuid4().hex[:6]}"
    if route != "start":
        _seed(solo["user"], thread_id, history=_TWO_TURNS if route == "regenerate" else None)
    url = {"start": START_URL, "continue": CONTINUE_URL, "regenerate": REGENERATE_URL}[route]
    body = {"thread_id": thread_id}
    if route != "regenerate":
        body["message"] = "Record this turn"

    status, payload = _post_turn(client, url, solo["headers"], body, stream=stream)

    assert status == 200, payload
    usage = UsageEvent.query.filter_by(thread_id=thread_id).one()
    operation = AIOperation.query.filter_by(thread_id=thread_id).one()
    expected_operation_type = "chat_revision" if route == "regenerate" else "framing_clarification"
    assert usage.user_id == solo["user"].id
    assert usage.organization_id == solo["org"].id
    assert usage.endpoint == "ai.conversation"
    assert usage.operation_type == expected_operation_type
    assert (usage.input_tokens, usage.output_tokens, usage.total_tokens) == (100, 20, TURN_TOKENS)
    assert usage.credits_charged == TURN_TOKENS
    assert usage.success is True
    assert operation.user_id == solo["user"].id
    assert operation.organization_id == solo["org"].id
    assert operation.operation_type == expected_operation_type
    assert operation.status == "succeeded"
    assert operation.charged_credits == TURN_TOKENS


@pytest.mark.parametrize("case", [
    "start-viewer", "continue-viewer", "regenerate-outsider",
    "regenerate-viewer", "regenerate-creator-now-viewer",
])
@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_authorization_refusal_precedes_reservation_and_generation(
    client, app, db, solo, monkeypatch, case, stream,
):
    agent = _agent()
    generation_calls = []
    reservation_calls = []
    _script_generation(monkeypatch, calls=generation_calls)
    monkeypatch.setattr(agent, "_reserve_preflight_credits", lambda *args, **kwargs: (
        reservation_calls.append((args, kwargs)) or {
            "ok": True, "required": 1, "reserved": 1, "remaining": 999,
        }
    ))

    owner, org = solo["user"], solo["org"]
    thread_id = f"t-auth-{uuid.uuid4().hex[:6]}"
    if case == "regenerate-outsider":
        _seed(owner, thread_id, history=_TWO_TURNS)
        actor = _mk_user(f"outsider-{uuid.uuid4().hex[:8]}@other.test")
        _mk_org(actor, f"Other{uuid.uuid4().hex[:6]}")
        _settle_meter(actor)
        url, body, expected_status = REGENERATE_URL, {"thread_id": thread_id}, 404
    elif case == "regenerate-viewer":
        actor = _mk_user(f"viewer-{uuid.uuid4().hex[:8]}@example.test")
        _add_member(org, actor, role="viewer")
        _seed_team_thread(owner, org, thread_id, history=_TWO_TURNS)
        url, body, expected_status = REGENERATE_URL, {"thread_id": thread_id}, 403
    elif case == "regenerate-creator-now-viewer":
        actor = _mk_user(f"demoted-{uuid.uuid4().hex[:8]}@example.test")
        _add_member(org, actor)
        _seed_team_thread(actor, org, thread_id, history=_TWO_TURNS)
        membership = OrganizationMember.query.filter_by(organization_id=org.id, user_id=actor.id).one()
        membership.role = "viewer"
        _db.session.commit()
        url, body, expected_status = REGENERATE_URL, {"thread_id": thread_id}, 403
    else:
        actor = _mk_user(f"viewer-{uuid.uuid4().hex[:8]}@example.test")
        _add_member(org, actor, role="viewer")
        if case == "continue-viewer":
            _seed_team_thread(owner, org, thread_id, history=_TWO_TURNS)
            url, body = CONTINUE_URL, {"thread_id": thread_id, "message": "Let me write"}
        else:
            url, body = START_URL, {"thread_id": thread_id, "message": "Let me start"}
        expected_status = 403

    target = f"{url}?stream=1" if stream else url
    response = client.post(target, headers=_headers(app, actor), json=body)
    response.get_data()

    assert response.status_code == expected_status
    assert reservation_calls == []
    assert generation_calls == []
    if case == "start-viewer":
        assert UserSession.query.filter_by(session_id=thread_id).count() == 0


# --------------------------------------------------------------------------
# PROBES: the reservation is not durable (evidence for the F2/F3 decision)
#
# A reservation is only an unsaved change to the balance until something
# commits. Several steps inside generation ROLL BACK the database session when
# they hit an error (the capture step, the decision-capture tool, mutation
# tools). A rollback silently discards the reservation; the turn then "gives
# back" or "settles against" credits that were never taken.
# --------------------------------------------------------------------------

@pytest.mark.xfail(strict=True, reason=(
    "CONFIRMED DEFECT (F4): a rollback inside generation discards the unsaved "
    "reservation, and the failure path then releases it anyway, so the "
    "customer's balance goes UP by the reserved amount."
))
@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_probe_failed_turn_after_an_internal_rollback_does_not_add_credits(client, db, solo, monkeypatch, stream):
    _script_generation(monkeypatch, during=_db.session.rollback, fail_with=RuntimeError("provider exploded"))
    _seed(solo["user"], "t-rb")
    before = _balance(solo["user"])

    target = f"{CONTINUE_URL}?stream=1" if stream else CONTINUE_URL
    try:
        response = client.post(target, headers=solo["headers"], json={"thread_id": "t-rb", "message": "Should we bid?"})
        response.get_data()  # a stream only runs when it is read
    except RuntimeError:
        pass

    assert _balance(solo["user"]) == before


@pytest.mark.xfail(strict=True, reason=(
    "CONFIRMED DEFECT (F4): after a rollback inside generation the turn "
    "settles against a reservation that no longer exists, so a successful "
    "reply is not charged its actual usage."
))
@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_probe_successful_turn_after_an_internal_rollback_is_charged_its_usage(client, db, solo, monkeypatch, stream):
    _script_generation(monkeypatch, during=_db.session.rollback)
    _seed(solo["user"], "t-rb2")
    before = _balance(solo["user"])

    status, payload = _post_turn(
        client, CONTINUE_URL, solo["headers"],
        {"thread_id": "t-rb2", "message": "Should we bid?"}, stream=stream,
    )

    assert status == 200, payload
    assert before - _balance(solo["user"]) == TURN_TOKENS


# --------------------------------------------------------------------------
# Regenerate follows the organization access model (ORG-1, ORG-2; P1)
#
# conversation/regenerate resolves the organization's canonical project and
# requires write access exactly as conversation/continue does
# (app/session_access.py: can_write_session). These were strict-xfail probes
# until P1 corrected them; they now pin the approved boundary: editors gain
# regenerate on shared projects, viewers lose it even on work they created.
# --------------------------------------------------------------------------

_TWO_TURNS = [
    {"role": "user", "content": "Owner's question"},
    {"role": "assistant", "content": "First answer"},
]


@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_probe_an_editor_can_regenerate_on_the_organizations_project(client, app, db, solo, monkeypatch, stream):
    _script_generation(monkeypatch)
    owner, org = solo["user"], solo["org"]
    editor = _mk_user(f"editor-{uuid.uuid4().hex[:8]}@example.test")
    _add_member(org, editor)
    _seed_team_thread(owner, org, "t-org-regen", history=_TWO_TURNS)
    owner_before, editor_before = _balance(owner), _balance(editor)

    status, payload = _post_turn(
        client, REGENERATE_URL, _headers(app, editor), {"thread_id": "t-org-regen"}, stream=stream,
    )

    assert status == 200, payload
    rows = UserSession.query.filter_by(session_id="t-org-regen").all()
    assert len(rows) == 1, "the editor must not fork the organization's project"
    row = rows[0]
    assert row.user_id == owner.id and row.created_by_user_id == owner.id
    assert row.last_edited_by_user_id == editor.id
    history = row.payload["chat_history"]
    assert [m["content"] for m in history] == ["Owner's question", REPLY]
    assert history[-1]["alternatives"][0]["content"] == "First answer"
    # Charged to the member who regenerates, never to the project's owner.
    assert editor_before - _balance(editor) == TURN_TOKENS
    assert _balance(owner) == owner_before


def test_probe_a_viewer_cannot_regenerate_even_on_a_project_they_created(client, app, db, solo, monkeypatch):
    calls = []
    _script_generation(monkeypatch, calls=calls)
    org = solo["org"]
    member = _mk_user(f"demoted-{uuid.uuid4().hex[:8]}@example.test")
    _add_member(org, member)
    _seed_team_thread(member, org, "t-demoted", history=_TWO_TURNS)
    membership = OrganizationMember.query.filter_by(organization_id=org.id, user_id=member.id).one()
    membership.role = "viewer"
    _db.session.commit()
    headers = _headers(app, member)

    blocked_continue = client.post(CONTINUE_URL, headers=headers, json={"thread_id": "t-demoted", "message": "More"})
    assert blocked_continue.status_code == 403  # the model, as continue applies it

    before = _balance(member)

    response = client.post(REGENERATE_URL, headers=headers, json={"thread_id": "t-demoted"})

    assert response.status_code == 403
    assert response.get_json()["code"] == "forbidden"
    assert calls == []
    assert _balance(member) == before
    assert _stored("t-demoted")["chat_history"] == _TWO_TURNS


# --------------------------------------------------------------------------
# A read-only member starting a new thread (independent review finding)
#
# Starting a thread writes a project into the organization, which needs an
# editing role. The refusal must come BEFORE anything is reserved or
# generated, so a viewer is never charged for a turn that cannot be saved.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
@pytest.mark.parametrize("has_earlier_project", [True, False], ids=["earlier-project", "no-projects"])
def test_a_viewer_starting_a_thread_is_refused_before_any_charge(
    client, app, db, solo, monkeypatch, stream, has_earlier_project,
):
    calls = []
    _script_generation(monkeypatch, calls=calls)
    org = solo["org"]
    viewer = _mk_user(f"viewer-{uuid.uuid4().hex[:8]}@example.test")
    _add_member(org, viewer)
    if has_earlier_project:
        _seed_team_thread(viewer, org, f"t-earlier-{uuid.uuid4().hex[:6]}")
    membership = OrganizationMember.query.filter_by(organization_id=org.id, user_id=viewer.id).one()
    membership.role = "viewer"
    _db.session.commit()
    before = _balance(viewer)
    thread_id = f"thread_{uuid.uuid4().hex[:16]}"

    target = f"{START_URL}?stream=1" if stream else START_URL
    response = client.post(target, headers=_headers(app, viewer), json={
        "thread_id": thread_id, "message": "A new decision",
    })
    response.get_data()

    assert response.status_code == 403
    assert calls == []
    assert _balance(viewer) == before
    assert UserSession.query.filter_by(session_id=thread_id).count() == 0


# --------------------------------------------------------------------------
# Response contract and refusals (added after independent review)
# --------------------------------------------------------------------------

_COMMON_KEYS = {
    "thread_id", "session_id", "reply", "message", "assistant_message_index",
    "model_type", "allowed_model_types", "mutations", "tool_results", "usage",
    "context_budget", "credits", "readiness", "strategy_objective",
    "objective_explicitly_set", "intake_context", "organization_id", "visibility",
}
_TURN_KEYS = _COMMON_KEYS | {
    "actions", "artifact_messages", "undo_available", "status", "objective_options",
}
_START_KEYS = _TURN_KEYS | {"decision_kit", "decision_kit_family", "decision_kit_suggestion"}
_REGENERATE_KEYS = _COMMON_KEYS | {"regenerated", "alternatives_count"}


@pytest.mark.parametrize("route,expected", [
    ("start", _START_KEYS), ("continue", _TURN_KEYS), ("regenerate", _REGENERATE_KEYS),
])
@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_response_carries_exactly_the_documented_fields(client, db, solo, monkeypatch, route, expected, stream):
    _script_generation(monkeypatch)
    thread_id = f"thread_{uuid.uuid4().hex[:16]}"
    if route == "start":
        url, body = START_URL, {"thread_id": thread_id, "message": "A new decision"}
    else:
        _seed(solo["user"], thread_id, history=_TWO_TURNS if route == "regenerate" else None)
        url = REGENERATE_URL if route == "regenerate" else CONTINUE_URL
        body = {"thread_id": thread_id} if route == "regenerate" else {"thread_id": thread_id, "message": "More"}

    status, payload = _post_turn(client, url, solo["headers"], body, stream=stream)

    assert status == 200, payload
    assert set(payload) == (expected | {"type"} if stream else expected)
    if stream:
        assert payload["type"] == "done"
    assert payload["mutations"] == [] and payload["tool_results"] == []
    if route != "regenerate":
        assert payload["status"] == "gathering_info"
        assert _stored(thread_id)["status"] == "in_progress"


@pytest.mark.parametrize("url", [START_URL, CONTINUE_URL, REGENERATE_URL], ids=["start", "continue", "regenerate"])
def test_a_refused_reservation_stops_the_turn_before_generation(client, db, solo, monkeypatch, url):
    agent = _agent()
    calls = []
    _script_generation(monkeypatch, calls=calls)
    refusal = {"error": "Out of Thinking Power", "code": "thinking_power_exhausted"}
    monkeypatch.setattr(agent, "_reserve_preflight_credits", lambda *a, **k: {
        "ok": False, "required": 2500, "reserved": 0, "remaining": 0, "payload": refusal,
    })
    thread_id = f"thread_{uuid.uuid4().hex[:16]}"
    if url != START_URL:
        _seed(solo["user"], thread_id, history=_TWO_TURNS)
    before = _balance(solo["user"])
    body = {"thread_id": thread_id} if url == REGENERATE_URL else {"thread_id": thread_id, "message": "More"}

    response = client.post(url, headers=solo["headers"], json=body)

    assert response.status_code == 402
    assert response.get_json() == refusal
    assert calls == []
    assert _balance(solo["user"]) == before


def test_provider_outage_answers_503_on_the_json_route(client, db, solo, monkeypatch):
    agent = _agent()
    _script_generation(monkeypatch, fail_with=agent.ConversationProviderUnavailable("down"))
    _seed(solo["user"], "t-503")

    response = client.post(CONTINUE_URL, headers=solo["headers"], json={"thread_id": "t-503", "message": "Hi"})

    assert response.status_code == 503
    assert response.get_json()["code"] == "analysis_unavailable"
