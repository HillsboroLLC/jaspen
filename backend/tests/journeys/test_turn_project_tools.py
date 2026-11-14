"""P2a: tools inside an AI turn use the turn's authorized project.

The route authorizes the organization's canonical project before anything is
reserved or generated. Everything the model does inside that turn (read tools,
mutation tools, decision capture and the prompt context builders) must act on
that same project, for whichever member is driving the turn, and never on a
row looked up among the caller's own personal projects.

Journeys covered (blueprint acceptance matrix): A3 converse, B4 an editor's
turn uses a tool, I one access rule on every entrance.

No provider is called. The Anthropic client is replaced with a scripted model
that asks for real tools, so the real tool loop, the real executors and the
real store run exactly as in production.
"""

import ast
import inspect
import json
import textwrap
import types
import uuid

import pytest
from werkzeug.security import generate_password_hash

from app import db as _db
from app.models import Organization, OrganizationMember, User, UserSession
from app.session_access import SessionNotFound


CONTINUE_URL = "/api/v1/ai-agent/conversation/continue"
START_URL = "/api/v1/ai-agent/conversation/start"
REGENERATE_URL = "/api/v1/ai-agent/conversation/regenerate"
UNDO_URL = "/api/v1/ai-agent/conversation/undo-mutations"
FINAL_TEXT = "Here is where the rubric stands."
STARTING_CREDITS = 1_000_000

OWNER_RUBRIC = {
    "criteria": [
        {"key": "owner_value", "label": "Owner value", "weight": 0.7},
        {"key": "owner_risk", "label": "Owner risk", "weight": 0.3},
    ],
    "source": "jaspen_proposed",
    "approval_status": "proposed",
    "created_at": "2026-11-01T00:00:00Z",
}
NEW_CRITERIA = [
    {"label": "Delivery confidence", "weight": 60},
    {"label": "Cost", "weight": 40},
]


@pytest.fixture(autouse=True)
def _disable_rate_limiting_for_this_file():
    from app import limiter
    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


# --------------------------------------------------------------------------
# people, organizations, projects
# --------------------------------------------------------------------------

def _agent():
    from app.routes import ai_agent
    return ai_agent


def _mk_user(label):
    user = User(
        email=f"{label}-{uuid.uuid4().hex[:8]}@example.test",
        name=label.title(),
        password_hash=generate_password_hash("ValidPass1", method="pbkdf2:sha256"),
        subscription_plan="free",
        subscription_status="active",
        credits_remaining=STARTING_CREDITS,
        seat_limit=5,
        max_seats=5,
    )
    _db.session.add(user)
    _db.session.commit()
    _settle_meter(user)
    return user


def _settle_meter(user):
    from app.billing_config import consume_credits, release_consumed_credits
    ok, _ = consume_credits(user, 1)
    assert ok
    release_consumed_credits(user, 1)
    _db.session.commit()


def _mk_org(owner, label):
    org = Organization(
        name=label, slug=f"{label.lower()}-{uuid.uuid4().hex[:6]}",
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


def _add_member(org, user, role):
    _db.session.add(OrganizationMember(
        organization_id=org.id, user_id=user.id, role=role, status="active",
    ))
    user.active_organization_id = org.id
    _db.session.commit()


def _set_role(org, user, role):
    member = OrganizationMember.query.filter_by(
        organization_id=org.id, user_id=user.id,
    ).one()
    member.role = role
    _db.session.commit()


def _headers(app, user):
    from flask_jwt_extended import create_access_token
    with app.app_context():
        return {"Authorization": f"Bearer {create_access_token(identity=str(user.id))}"}


def _seed_project(creator, org, thread_id, *, visibility="team", rubric=None, name="Shared project"):
    from app.routes.sessions import save_user_sessions
    payload = {
        "session_id": thread_id, "user_id": creator.id, "name": name,
        "status": "in_progress", "organization_id": org.id if org else None,
        "visibility": visibility,
        "chat_history": [
            {"role": "user", "content": "Should we bid on the regional contract?"},
            {"role": "assistant", "content": "What matters most in this decision?"},
        ],
    }
    if rubric is not None:
        payload["scoring_rubric"] = json.loads(json.dumps(rubric))
    assert save_user_sessions(creator.id, {thread_id: payload})


def _rows(thread_id):
    _db.session.expire_all()
    return UserSession.query.filter_by(session_id=thread_id).all()


def _row(thread_id):
    rows = _rows(thread_id)
    assert len(rows) == 1, f"expected exactly one row for {thread_id}, found {len(rows)}"
    return rows[0]


def _rubric_labels(payload):
    """Criterion labels from a stored project payload or a rubric tool result."""
    payload = payload or {}
    rubric = payload.get("scoring_rubric") or payload.get("rubric") or {}
    return [item.get("label") for item in rubric.get("criteria") or []]


# --------------------------------------------------------------------------
# the scripted model
# --------------------------------------------------------------------------

def _tool_block(name, tool_input, block_id):
    return types.SimpleNamespace(type="tool_use", id=block_id, name=name, input=tool_input)


def _text_block(text):
    return types.SimpleNamespace(type="text", text=text)


def _response(blocks, stop_reason="end_turn"):
    return types.SimpleNamespace(
        content=list(blocks),
        stop_reason=stop_reason,
        usage=types.SimpleNamespace(input_tokens=50, output_tokens=10),
    )


class _ScriptedModel:
    """A model that asks for the listed tools, one per round, then answers."""

    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = []
        self.tool_results = []

    def create(self, client, *, model_name, stream=False, strict_model=False, **kwargs):
        assert not stream, "the scripted model only answers the JSON route"
        self.calls.append({"model": model_name, "system": kwargs.get("system"), "messages": kwargs.get("messages")})
        for message in kwargs.get("messages") or []:
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, list):
                for item in content:
                    if (
                        isinstance(item, dict) and item.get("type") == "tool_result"
                        and item.get("tool_use_id") not in {seen.get("tool_use_id") for seen in self.tool_results}
                    ):
                        self.tool_results.append(item)
        if "decision recorder" in str(kwargs.get("system") or ""):
            # The capture pass is its own call; it never consumes reply steps.
            return _response([_text_block("")]), model_name
        if self.steps:
            name, tool_input = self.steps.pop(0)
            return _response([_tool_block(name, tool_input, f"toolu_{len(self.calls)}")], "tool_use"), model_name
        return _response([_text_block(FINAL_TEXT)]), model_name


def _install_scripted_model(monkeypatch, steps):
    agent = _agent()
    model = _ScriptedModel(steps)
    monkeypatch.setattr(agent, "_anthropic_api_key", lambda: "test-key-not-real")
    monkeypatch.setattr(agent, "_gemini_api_key", lambda: "")
    monkeypatch.setattr(agent, "_anthropic_message_create", model.create)
    monkeypatch.setattr(agent, "_classify_decision_kit", lambda *_a, **_k: {
        "kit": "none", "confidence": "high", "evidence_quote": "",
    })
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: types.SimpleNamespace())
    return model


def _read_then_write_steps():
    return [
        ("show_scoring_rubric", {}),
        ("set_scoring_rubric", {"criteria": NEW_CRITERIA}),
    ]


def _tool_results_by_name(payload):
    return {item.get("tool"): item.get("result") for item in payload.get("actions") or []}



def _snapshot(thread_id):
    row = _row(thread_id)
    return json.loads(json.dumps(row.payload, sort_keys=True, default=str)), int(row.revision or 1)


def _balance(user):
    _db.session.rollback()
    _db.session.expire_all()
    return User.query.get(user.id).credits_remaining


def _spy_reservations(monkeypatch):
    calls = []
    agent = _agent()
    real = agent._reserve_preflight_credits

    def spy(*args, **kwargs):
        calls.append("reserve")
        return real(*args, **kwargs)

    monkeypatch.setattr(agent, "_reserve_preflight_credits", spy)
    return calls


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

@pytest.fixture
def team(app, db):
    owner = _mk_user("owner")
    org = _mk_org(owner, f"Team{uuid.uuid4().hex[:6]}")
    editor = _mk_user("editor")
    _add_member(org, editor, "collaborator")
    viewer = _mk_user("viewer")
    _add_member(org, viewer, "viewer")
    return {"owner": owner, "org": org, "editor": editor, "viewer": viewer}


@pytest.fixture
def outsider(app, db):
    """A member of a different organization."""
    user = _mk_user("outsider")
    org = _mk_org(user, f"Other{uuid.uuid4().hex[:6]}")
    return {"user": user, "org": org}


# --------------------------------------------------------------------------
# B4 / A3: a member's turn reads and changes the organization's project
# (STEP 0 PROBE, now permanent). Before P2a the editor's read tool returned
# "rubric_unavailable" and the mutation tool reported "saved" while writing
# nothing until the end-of-turn copy.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("actor", ["owner", "editor"])
def test_member_turn_reads_and_changes_the_organizations_project(
    client, app, db, team, monkeypatch, actor,
):
    owner, org = team["owner"], team["org"]
    member = team[actor]
    thread_id = f"t-b4-{actor}-{uuid.uuid4().hex[:6]}"
    other_thread = f"t-b4-other-{uuid.uuid4().hex[:6]}"
    own_thread = f"t-b4-own-{uuid.uuid4().hex[:6]}"
    _seed_project(owner, org, thread_id, rubric=OWNER_RUBRIC)
    _seed_project(owner, org, other_thread, rubric=OWNER_RUBRIC, name="Owner's other project")
    _seed_project(team["editor"], org, own_thread, visibility="private", name="Editor's own project")
    others_before = {tid: _snapshot(tid) for tid in (other_thread, own_thread)}
    revision_before = int(_row(thread_id).revision or 1)
    # Read, change, read again: the second read proves the change is already
    # on the canonical row while the turn is still running.
    model = _install_scripted_model(monkeypatch, [
        ("show_scoring_rubric", {}),
        ("set_scoring_rubric", {"criteria": NEW_CRITERIA}),
        ("show_scoring_rubric", {}),
    ])

    response = client.post(CONTINUE_URL, headers=_headers(app, member), json={
        "thread_id": thread_id,
        "message": "Show me the rubric, then use delivery confidence at 60% and cost at 40%.",
    })

    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    actions = payload["actions"]
    assert [item["tool"] for item in actions] == [
        "show_scoring_rubric", "set_scoring_rubric", "show_scoring_rubric",
    ]
    first_read, write, second_read = (item["result"] for item in actions)
    assert first_read["ok"] is True, first_read
    assert _rubric_labels(first_read) == ["Owner value", "Owner risk"]
    assert write["ok"] is True, write
    assert second_read["ok"] is True, second_read
    assert _rubric_labels(second_read) == ["Delivery confidence", "Cost"]

    # Response compatibility: the same result and turn fields as before.
    assert {"ok", "tool", "rubric", "confirmation", "artifact"} <= set(write)
    assert {"ok", "tool", "rubric", "confirmation", "artifact"} <= set(first_read)
    assert payload["mutations"] == payload["tool_results"]
    assert [item["tool"] for item in payload["mutations"]] == [item["tool"] for item in actions]
    assert payload["reply"]

    # Exactly the organization's one row changed, attributed to the member.
    rows = _rows(thread_id)
    assert len(rows) == 1
    row = rows[0]
    assert row.organization_id == org.id
    assert row.user_id == owner.id and row.created_by_user_id == owner.id
    assert row.last_edited_by_user_id == member.id
    assert int(row.revision) > revision_before
    assert _rubric_labels(row.payload) == ["Delivery confidence", "Cost"]
    if actor != "owner":
        assert UserSession.query.filter_by(user_id=member.id, session_id=thread_id).count() == 0

    # No other project was touched, the member's own or the owner's.
    for tid, before in others_before.items():
        assert _snapshot(tid) == before, tid

    # The model received the real tool results.
    assert len(model.tool_results) == 3
    assert json.loads(model.tool_results[0]["content"])["ok"] is True


def test_a_new_conversation_tool_change_lands_on_the_new_project(client, app, db, team, monkeypatch):
    """conversation/start: the project has no row until the turn saves it.
    The turn's project still resolves to that one new row."""
    editor, org = team["editor"], team["org"]
    thread_id = f"t-start-{uuid.uuid4().hex[:6]}"
    _install_scripted_model(monkeypatch, [
        ("set_scoring_rubric", {"criteria": NEW_CRITERIA}),
        ("show_scoring_rubric", {}),
    ])

    response = client.post(START_URL, headers=_headers(app, editor), json={
        "thread_id": thread_id, "message": "Use delivery confidence at 60% and cost at 40%.",
    })

    assert response.status_code == 200, response.get_json()
    results = [item["result"] for item in response.get_json()["actions"]]
    assert all(result["ok"] for result in results), results
    assert _rubric_labels(results[1]) == ["Delivery confidence", "Cost"]
    row = _row(thread_id)
    assert row.organization_id == org.id and row.created_by_user_id == editor.id
    assert _rubric_labels(row.payload) == ["Delivery confidence", "Cost"]


# --------------------------------------------------------------------------
# B8 / B9 / B11: refusals happen before anything is reserved or generated,
# and the project is unchanged.
# --------------------------------------------------------------------------

def _assert_refused_before_generation(client, app, user, thread_id, monkeypatch, expected_status):
    model = _install_scripted_model(monkeypatch, _read_then_write_steps())
    reservations = _spy_reservations(monkeypatch)
    before_rows = {row.id: (row.revision, json.dumps(row.payload, sort_keys=True, default=str))
                   for row in _rows(thread_id)}
    balance_before = _balance(user)

    response = client.post(CONTINUE_URL, headers=_headers(app, user), json={
        "thread_id": thread_id, "message": "Change the rubric to delivery confidence and cost.",
    })

    assert response.status_code == expected_status, response.get_json()
    assert model.calls == [], "the model must not be called"
    assert reservations == [], "nothing may be reserved"
    assert _balance(user) == balance_before
    after_rows = {row.id: (row.revision, json.dumps(row.payload, sort_keys=True, default=str))
                  for row in _rows(thread_id)}
    assert after_rows == before_rows
    return response


def test_a_viewer_is_refused_before_generation(client, app, db, team, monkeypatch):
    thread_id = f"t-viewer-{uuid.uuid4().hex[:6]}"
    _seed_project(team["owner"], team["org"], thread_id, rubric=OWNER_RUBRIC)

    response = _assert_refused_before_generation(
        client, app, team["viewer"], thread_id, monkeypatch, expected_status=403,
    )
    assert response.get_json()["error"] == "Your role on this project is read-only."


def test_a_creator_made_viewer_is_refused_before_generation(client, app, db, team, monkeypatch):
    creator, org = team["editor"], team["org"]
    thread_id = f"t-demoted-{uuid.uuid4().hex[:6]}"
    _seed_project(creator, org, thread_id, rubric=OWNER_RUBRIC, name="Creator's project")
    _set_role(org, creator, "viewer")

    _assert_refused_before_generation(client, app, creator, thread_id, monkeypatch, expected_status=403)


def test_a_creator_made_viewer_cannot_change_the_project_through_a_tool(app, db, team):
    """The tool-level rule, for any caller that runs a tool outside a turn."""
    agent = _agent()
    creator, org = team["editor"], team["org"]
    thread_id = f"t-demoted-tool-{uuid.uuid4().hex[:6]}"
    _seed_project(creator, org, thread_id, rubric=OWNER_RUBRIC, name="Creator's project")
    _set_role(org, creator, "viewer")
    before = _snapshot(thread_id)

    mutation = agent._execute_mutation_tool(
        "set_scoring_rubric", {"criteria": NEW_CRITERIA},
        user=creator, user_id=creator.id, thread_id=thread_id,
        user_message="Use delivery confidence at 60% and cost at 40%.",
    )
    capture = agent._execute_decision_capture_tool(
        "record_decision_context", {"notes": [{"text": "We prefer lower risk."}]},
        user=creator, user_id=creator.id, thread_id=thread_id,
        view_active_scorecard_id=None, user_message="We prefer lower risk.", plan_key="free",
    )

    assert mutation == {"ok": False, "code": "project_read_only", "error": "Your role on this project is read-only."}
    assert capture == mutation
    assert _snapshot(thread_id) == before
    # Read access is unchanged: the viewer still sees the project's content.
    project = agent._build_turn_project(creator, thread_id)
    assert project.can_read and not project.can_write and project.role == "viewer"
    assert _rubric_labels(agent._project_sessions(creator.id, thread_id)[thread_id]) == ["Owner value", "Owner risk"]


def test_another_organization_cannot_reach_the_project(client, app, db, team, outsider, monkeypatch):
    thread_id = f"t-isolated-{uuid.uuid4().hex[:6]}"
    _seed_project(team["owner"], team["org"], thread_id, rubric=OWNER_RUBRIC)

    _assert_refused_before_generation(
        client, app, outsider["user"], thread_id, monkeypatch, expected_status=404,
    )


def test_another_organizations_tools_and_context_see_nothing(app, db, team, outsider):
    agent = _agent()
    user = outsider["user"]
    thread_id = f"t-isolated-tool-{uuid.uuid4().hex[:6]}"
    _seed_project(team["owner"], team["org"], thread_id, rubric=OWNER_RUBRIC)
    before = _snapshot(thread_id)

    shown = agent._execute_mutation_tool(
        "show_scoring_rubric", {}, user=user, user_id=user.id, thread_id=thread_id,
    )
    agent._execute_mutation_tool(
        "set_scoring_rubric", {"criteria": NEW_CRITERIA},
        user=user, user_id=user.id, thread_id=thread_id, user_message="Change it.",
    )

    assert shown["ok"] is False
    assert "Owner value" not in json.dumps(shown)
    assert agent._project_sessions(user.id, thread_id) == {}
    assert dict(agent._project_scenarios(user.id, thread_id)) == {}
    assert agent._thread_user_corpus(user.id, thread_id) == ""
    assert agent._decision_kit_prompt_suffix(user.id, thread_id) == ""
    assert agent._load_capture_session(user.id, thread_id)[2] is None
    assert _snapshot(thread_id) == before
    assert len(_rows(thread_id)) == 1


# --------------------------------------------------------------------------
# Journey I: every context builder in the turn uses the same access rule, so a
# teammate's turn carries the project's context and never another project's.
# --------------------------------------------------------------------------

def test_a_teammates_turn_carries_the_projects_context(client, app, db, team, monkeypatch):
    owner, org, editor = team["owner"], team["org"], team["editor"]
    thread_id = f"t-ctx-{uuid.uuid4().hex[:6]}"
    other_thread = f"t-ctx-other-{uuid.uuid4().hex[:6]}"
    _seed_project(owner, org, thread_id, rubric=OWNER_RUBRIC)
    _seed_project(owner, org, other_thread, name="Unrelated harbor expansion")
    row = _row(thread_id)
    payload = dict(row.payload)
    payload["decision_kit"] = "rfp_bid"
    from app.routes.sessions import save_user_sessions
    assert save_user_sessions(owner.id, {thread_id: payload})
    model = _install_scripted_model(monkeypatch, [])

    response = client.post(CONTINUE_URL, headers=_headers(app, editor), json={
        "thread_id": thread_id, "message": "Where do we stand?",
    })

    assert response.status_code == 200, response.get_json()
    system = model.calls[0]["system"]
    assert "[DECISION KIT — " in system
    assert "Unrelated harbor expansion" not in system


def test_context_builders_give_a_teammate_the_same_project_as_the_owner(app, db, team):
    agent = _agent()
    owner, org, editor = team["owner"], team["org"], team["editor"]
    thread_id = f"t-builders-{uuid.uuid4().hex[:6]}"
    _seed_project(owner, org, thread_id, rubric=OWNER_RUBRIC)
    row = _row(thread_id)
    payload = dict(row.payload)
    payload["decision_kit"] = "rfp_bid"
    from app.routes.sessions import save_user_sessions
    assert save_user_sessions(owner.id, {thread_id: payload})

    for builder in (
        lambda uid: agent._decision_kit_prompt_suffix(uid, thread_id),
        lambda uid: agent._thread_user_corpus(uid, thread_id),
        lambda uid: agent._thread_scorecard_summary(uid, thread_id),
        lambda uid: agent._batch_promotion_prompt_suffix(uid, thread_id),
        lambda uid: agent._load_capture_session(uid, thread_id)[2]["session_id"],
    ):
        assert builder(editor.id) == builder(owner.id)
    assert "Should we bid on the regional contract?" in agent._thread_user_corpus(editor.id, thread_id)
    assert agent._decision_kit_prompt_suffix(editor.id, thread_id)


# --------------------------------------------------------------------------
# Guard: no project-specific tool executor, capture step or prompt builder
# may look the project up among the caller's personal rows again.
# --------------------------------------------------------------------------

# Functions that run inside a turn and act on the turn's project. Functions
# whose name starts with ``_execute_`` or ends with ``_prompt_suffix`` are
# included automatically.
_TURN_PROJECT_FUNCTIONS = {
    "_execute_local_tool_inner",
    "_execute_mutation_tool",
    "_execute_decision_capture_tool",
    "_dispatch_decision_capture_tool",
    "_execute_record_option_decision",
    "_execute_record_decision_context",
    "_execute_confirm_task_commitment",
    "_capture_record_and_option",
    "_load_capture_session",
    "_run_turn_capture",
    "_resolve_explicit_option_plan",
    "_resolve_option_plan",
    "_present_decision_kit_rubric",
    "_thread_scorecard_summary",
    "_criteria_card_after_scoring",
    "_thread_user_corpus",
    "_decision_kit_prompt_suffix",
    "_wbs_content_prompt_suffix",
    "_batch_promotion_prompt_suffix",
    "_organizational_memory_prompt_suffix",
    "_scenario_modeling_prompt_suffix",
}
# Personal lookups: the caller's own projects, or the caller's own scenario
# data. Each is the right tool for personal lists, and the wrong one for "this
# project".
_PERSONAL_LOOKUPS = {"load_user_sessions", "_load_scenarios", "load_scenarios_data"}


def _ai_agent_functions():
    source = inspect.getsource(_agent())
    tree = ast.parse(source)
    return {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


def test_guard_turn_project_code_never_uses_a_personal_project_lookup():
    functions = _ai_agent_functions()
    missing = _TURN_PROJECT_FUNCTIONS - set(functions)
    assert not missing, f"renamed or removed; update the guard list: {sorted(missing)}"
    guarded = set(_TURN_PROJECT_FUNCTIONS) | {
        name for name in functions
        if name.startswith("_execute_") or name.endswith("_prompt_suffix")
    }
    offenders = []
    for name in sorted(guarded):
        for node in ast.walk(functions[name]):
            if isinstance(node, ast.Call):
                called = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if called in _PERSONAL_LOOKUPS:
                    offenders.append(f"{name} line {node.lineno}: {called}()")
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in _PERSONAL_LOOKUPS:
                        offenders.append(f"{name} line {node.lineno}: imports {alias.name}")
    assert not offenders, (
        "A tool, capture step or prompt builder looked the project up among the "
        "caller's own rows. Use the turn's project (_turn_project / "
        "_project_sessions / _project_scenarios) instead:\n" + "\n".join(offenders)
    )


def test_guard_catches_a_personal_lookup():
    """The guard itself must fail on the defect it exists to prevent."""
    tree = ast.parse(textwrap.dedent('''
        def _execute_example_tool(user_id, thread_id):
            sessions = load_user_sessions(user_id) or {}
            return sessions.get(thread_id)
    '''))
    calls = [
        getattr(node.func, "id", None)
        for node in ast.walk(tree) if isinstance(node, ast.Call)
    ]
    assert "load_user_sessions" in calls and set(calls) & _PERSONAL_LOOKUPS


# ==========================================================================
# Remediation 1: conversation/start never overwrites an existing shared
# project. `start` re-opens only the caller's own thread (the homepage handoff
# retries the same id); an organization project found only through the access
# seam is refused before anything is saved, reserved or generated.
# ==========================================================================

def _row_bytes(thread_id):
    """Everything stored on every row with this id, for byte-for-byte checks."""
    _db.session.expire_all()
    return sorted(
        (
            str(row.id), str(row.organization_id), str(row.user_id), int(row.revision or 1),
            str(row.updated_at), str(row.last_edited_by_user_id),
            json.dumps(row.payload, sort_keys=True, default=str),
            json.dumps(row.scenarios_json, sort_keys=True, default=str),
        )
        for row in UserSession.query.filter_by(session_id=thread_id).all()
    )


def _refuse_reservations(monkeypatch):
    calls = []

    def refused(*_a, **_k):
        calls.append("reserve")
        return {
            "ok": False, "required": 2500, "reserved": 0, "remaining": 0,
            "payload": {"error": "Out of Thinking Power", "code": "thinking_power_exhausted"},
        }

    monkeypatch.setattr(_agent(), "_reserve_preflight_credits", refused)
    return calls


def _remove_member(org, user):
    member = OrganizationMember.query.filter_by(organization_id=org.id, user_id=user.id).one()
    member.status = "removed"
    _db.session.commit()


def test_start_on_an_existing_shared_thread_never_overwrites_it(client, app, db, team, monkeypatch):
    owner, org, editor = team["owner"], team["org"], team["editor"]
    thread_id = f"t-start-shared-{uuid.uuid4().hex[:6]}"
    _seed_project(owner, org, thread_id, rubric=OWNER_RUBRIC)
    before = _row_bytes(thread_id)
    model = _install_scripted_model(monkeypatch, [])
    reservations = _spy_reservations(monkeypatch)

    response = client.post(START_URL, headers=_headers(app, editor), json={
        "thread_id": thread_id, "message": "Let's start over.", "name": "Blank",
    })

    assert response.status_code == 409, response.get_json()
    assert response.get_json()["code"] == "thread_exists"
    assert response.get_json()["error"] == "This project already exists. Open it to continue."
    assert model.calls == [] and reservations == []
    assert _row_bytes(thread_id) == before
    history = _row(thread_id).payload["chat_history"]
    assert [m["content"] for m in history] == [
        "Should we bid on the regional contract?", "What matters most in this decision?",
    ]


@pytest.mark.parametrize("who", ["editor_out_of_credits", "viewer", "removed_member", "other_organization"])
def test_start_refusals_leave_the_shared_project_byte_for_byte(
    client, app, db, team, outsider, monkeypatch, who,
):
    owner, org = team["owner"], team["org"]
    thread_id = f"t-start-refused-{uuid.uuid4().hex[:6]}"
    _seed_project(owner, org, thread_id, rubric=OWNER_RUBRIC)
    if who == "removed_member":
        actor = team["editor"]
        _remove_member(org, actor)
    elif who == "other_organization":
        actor = outsider["user"]
    elif who == "viewer":
        actor = team["viewer"]
    else:
        actor = team["editor"]
    before = _row_bytes(thread_id)
    model = _install_scripted_model(monkeypatch, [])
    _refuse_reservations(monkeypatch)

    response = client.post(START_URL, headers=_headers(app, actor), json={
        "thread_id": thread_id, "message": "Start this.",
    })

    assert response.status_code in {402, 403, 404, 409}, response.get_json()
    assert model.calls == []
    org_rows = [r for r in _rows(thread_id) if r.organization_id == org.id]
    assert len(org_rows) == 1, "the organization's project must not fork"
    if who in {"other_organization", "removed_member"}:
        # Outside the organization the id space is the caller's own: whatever
        # they do with this id, the organization's row is untouched.
        assert [entry for entry in _row_bytes(thread_id) if entry[1] == str(org.id)] == \
            [entry for entry in before if entry[1] == str(org.id)]
    else:
        assert _row_bytes(thread_id) == before


def test_start_still_reopens_the_callers_own_thread(client, app, db, team, monkeypatch):
    """The homepage handoff retries conversation/start with the same id."""
    owner, org = team["owner"], team["org"]
    thread_id = f"t-start-own-{uuid.uuid4().hex[:6]}"
    _seed_project(owner, org, thread_id, rubric=OWNER_RUBRIC)
    _install_scripted_model(monkeypatch, [])

    response = client.post(START_URL, headers=_headers(app, owner), json={
        "thread_id": thread_id, "message": "Picking this back up.",
    })

    assert response.status_code == 200, response.get_json()
    contents = [m["content"] for m in _row(thread_id).payload["chat_history"]]
    assert contents[:3] == [
        "Should we bid on the regional contract?", "What matters most in this decision?",
        "Picking this back up.",
    ]
    assert len(_rows(thread_id)) == 1


# ==========================================================================
# Remediation 2: scorecard and decision-facts prompt context come from the
# turn's authorized project and organization only.
#
# Two organizations use the same thread id. A consultant belongs to both, is
# working in Alpha, and has scored a card in Bravo's project. Bravo's project
# is older, so an unscoped "oldest row with this id" lookup lands on Bravo.
# ==========================================================================

SAME_ID = "t-same-id"
ALPHA_CARD = {"id": "card-alpha", "option_key": "option-alpha", "project_name": "Alpha Harbor Option",
              "jaspen_score": 71, "score_category": "Strong"}
ALPHA_INDEX_ONLY = {"id": "card-alpha-index", "option_key": "option-alpha-index",
                    "project_name": "Alpha Index Only Option", "jaspen_score": 58, "score_category": "Promising"}
BRAVO_CARD = {"id": "card-bravo", "option_key": "option-bravo", "project_name": "Bravo Secret Option",
              "jaspen_score": 99, "score_category": "Strong"}
BRAVO_PLAN = {
    "name": "Bravo plan", "scorecard_id": ALPHA_CARD["id"],
    "tasks": [{"id": f"b{i}", "title": f"Bravo task {i}", "status": "todo"} for i in range(7)],
}


@pytest.fixture
def two_orgs(app, db):
    from app.routes.sessions import save_user_sessions
    from app.scorecards import upsert_scorecard

    bravo_owner = _mk_user("bravo-owner")
    bravo = _mk_org(bravo_owner, f"Bravo{uuid.uuid4().hex[:6]}")
    alpha_owner = _mk_user("alpha-owner")
    alpha = _mk_org(alpha_owner, f"Alpha{uuid.uuid4().hex[:6]}")
    alpha_editor = _mk_user("alpha-editor")
    _add_member(alpha, alpha_editor, "collaborator")
    consultant = _mk_user("consultant")
    _add_member(bravo, consultant, "collaborator")
    _add_member(alpha, consultant, "collaborator")   # active organization: Alpha

    def project(owner, org, cards):
        result = {**cards[0], "_baseline_scorecard": cards[0], "scorecard_snapshots": cards}
        assert save_user_sessions(owner.id, {SAME_ID: {
            "session_id": SAME_ID, "user_id": owner.id, "name": "Same id project",
            "status": "in_progress", "organization_id": org.id, "visibility": "team",
            "result": result,
            "chat_history": [{"role": "user", "content": "Which harbor option?"},
                             {"role": "assistant", "content": "Let's compare them."}],
        }})

    project(bravo_owner, bravo, [BRAVO_CARD])            # older row
    bravo_row = UserSession.query.filter_by(session_id=SAME_ID, organization_id=bravo.id).one()
    bravo_row.scenarios_json = {"wbs_by_scorecard": {ALPHA_CARD["id"]: BRAVO_PLAN}}
    _db.session.commit()
    project(alpha_owner, alpha, [ALPHA_CARD])
    upsert_scorecard(user_id=consultant.id, thread_id=SAME_ID, payload=BRAVO_CARD, organization_id=bravo.id)
    upsert_scorecard(user_id=alpha_owner.id, thread_id=SAME_ID, payload=ALPHA_CARD, organization_id=alpha.id)
    upsert_scorecard(user_id=alpha_owner.id, thread_id=SAME_ID, payload=ALPHA_INDEX_ONLY, organization_id=alpha.id)
    _db.session.commit()
    # Alpha's decision record, created the way a real turn creates it.
    result = _agent()._execute_mutation_tool(
        "record_option_decision",
        {"decisions": [{"option_key": "option-alpha", "disposition": "still_evaluating",
                        "user_request_quote": "still on the table"}]},
        user=alpha_owner, user_id=alpha_owner.id, thread_id=SAME_ID,
        user_message="Alpha Harbor is still on the table.",
    )
    assert result["ok"] is True, result
    return {
        "alpha": alpha, "bravo": bravo, "alpha_owner": alpha_owner, "alpha_editor": alpha_editor,
        "bravo_owner": bravo_owner, "consultant": consultant,
    }


def _reply_call(model):
    """The reply request (the capture pass, when it runs, is a separate call)."""
    calls = [call for call in model.calls if "decision recorder" not in str(call["system"])]
    assert calls, "no reply request was made"
    return calls[0]


def _assert_alpha_context_only(scorecards, facts, *, expect_index_card=True):
    assert "Alpha Harbor Option" in scorecards
    if expect_index_card:
        assert "Alpha Index Only Option" in scorecards
    assert "Bravo Secret Option" not in scorecards
    assert "Bravo Secret Option" not in facts and "Bravo task" not in facts
    assert '"tasks_total":7' not in facts
    assert "[DECISION STATE" in facts


@pytest.mark.parametrize("member", ["alpha_owner", "alpha_editor", "consultant"])
def test_each_member_gets_only_the_authorized_projects_scorecards_and_facts(
    client, app, db, two_orgs, monkeypatch, member,
):
    model = _install_scripted_model(monkeypatch, [])

    response = client.post(CONTINUE_URL, headers=_headers(app, two_orgs[member]), json={
        "thread_id": SAME_ID, "message": "Where do the options stand?",
    })

    assert response.status_code == 200, response.get_json()
    system = _reply_call(model)["system"]
    _assert_alpha_context_only(system, system)
    everything = json.dumps(model.calls, default=str)
    assert "Bravo Secret Option" not in everything and "Bravo task" not in everything


def test_the_other_organization_sees_only_its_own_same_id_project(client, app, db, two_orgs, monkeypatch):
    model = _install_scripted_model(monkeypatch, [])

    response = client.post(CONTINUE_URL, headers=_headers(app, two_orgs["bravo_owner"]), json={
        "thread_id": SAME_ID, "message": "Where do the options stand?",
    })

    assert response.status_code == 200, response.get_json()
    system = _reply_call(model)["system"]
    assert "Bravo Secret Option" in system
    assert "Alpha Harbor Option" not in system and "Alpha Index Only Option" not in system
    assert "Alpha Harbor Option" not in json.dumps(model.calls, default=str)


def test_removed_and_unauthorized_members_get_no_scorecards_or_facts(app, db, two_orgs, outsider):
    agent = _agent()
    removed = two_orgs["alpha_editor"]
    _remove_member(two_orgs["alpha"], removed)
    stranger = outsider["user"]

    for user in (removed, stranger):
        assert agent._project_sessions(user.id, SAME_ID) == {}
        assert agent._decision_facts_prompt_suffix(user.id, SAME_ID) == ""
    with pytest.raises(SessionNotFound):
        agent._build_turn_project(removed, SAME_ID)
    # The stranger's own organization has no such project; scorecard context
    # for it carries neither organization's cards.
    project = agent._build_turn_project(stranger, SAME_ID)
    assert not project.exists
    context = agent._scorecard_content_prompt_suffix(
        {"session_id": SAME_ID}, {}, user_id=stranger.id, thread_id=SAME_ID, project=project,
    )
    assert "Alpha" not in context and "Bravo" not in context


_PROVIDER_PATHS = [
    ("_generate_assistant_reply_anthropic", "anthropic", False),
    ("_stream_assistant_reply_events_anthropic", "anthropic", True),
    ("_generate_assistant_reply_gemini", "gemini", False),
    ("_stream_assistant_reply_events_gemini", "gemini", True),
]


@pytest.mark.parametrize("function_name,provider,streaming", _PROVIDER_PATHS,
                         ids=[p[0].replace("_assistant_reply", "") for p in _PROVIDER_PATHS])
def test_every_provider_path_builds_scorecard_and_facts_context_from_the_turns_project(
    app, db, two_orgs, monkeypatch, function_name, provider, streaming,
):
    """Scripted providers only: the first provider request is captured, then
    refused, so nothing leaves the process."""
    import anthropic

    agent = _agent()
    consultant = two_orgs["consultant"]
    project = agent._build_turn_project(consultant, SAME_ID)
    session = project.sessions()[SAME_ID]
    built = {}
    real_scorecards = agent._scorecard_content_prompt_suffix
    real_facts = agent._decision_facts_prompt_suffix

    def scorecards_spy(*args, **kwargs):
        built["scorecards_project"] = kwargs.get("project")
        built["scorecards"] = real_scorecards(*args, **kwargs)
        return built["scorecards"]

    def facts_spy(*args, **kwargs):
        built["facts_project"] = kwargs.get("project")
        built["facts"] = real_facts(*args, **kwargs)
        return built["facts"]

    def refuse_request(*_a, **kwargs):
        built["system"] = kwargs.get("system") or kwargs.get("system_prompt")
        raise RuntimeError("scripted provider: request captured")

    monkeypatch.setattr(agent, "_scorecard_content_prompt_suffix", scorecards_spy)
    monkeypatch.setattr(agent, "_decision_facts_prompt_suffix", facts_spy)
    monkeypatch.setattr(agent, "_anthropic_api_key", lambda: "test-key-not-real")
    monkeypatch.setattr(agent, "_gemini_api_key", lambda: "test-key-not-real")
    monkeypatch.setattr(agent, "_anthropic_message_create", refuse_request)
    monkeypatch.setattr(agent, "_gemini_openai_request", refuse_request)
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: types.SimpleNamespace())

    history = list(session.get("chat_history") or []) + [{"role": "user", "content": "Where do we stand?"}]
    readiness = agent._compute_readiness(history, "balanced")
    model = "gemini-2.5-flash" if provider == "gemini" else "claude-sonnet-4-5"
    kwargs = dict(
        session=session, user=consultant, user_id=consultant.id, thread_id=SAME_ID,
        intake_context=None, view_context={}, project=project,
    )
    function = getattr(agent, function_name)
    try:
        if streaming:
            list(function("Where do we stand?", history, readiness, {"model_type": "pluto", "llm_model": model},
                          state={}, **kwargs))
        else:
            function("Where do we stand?", history, readiness, {"model_type": "pluto", "llm_model": model},
                     **kwargs)
    except RuntimeError:
        pass

    assert built["scorecards_project"] is project
    assert built["facts_project"] is project
    _assert_alpha_context_only(built["scorecards"], built["facts"])
    assert built["scorecards"] in built["system"] and built["facts"] in built["system"]


# ==========================================================================
# Remediation 3: historical data cannot bypass the project boundary.
#
# (a) A member may still hold a personal "fork" row that shares an
#     organization project's thread id (rows written before Phase 1 resolved
#     saves by organization). The fork is never authoritative for that id:
#     start, continue and every single-thread route act on the canonical row,
#     and the fork itself is left exactly as it is.
# (b) Scorecards are selected for the authorized canonical project only, so a
#     member who authored same-id projects in two organizations never mixes
#     them, in decision records, decision tools or prompts.
# ==========================================================================

def _insert_row(*, user, session_id, organization_id, created_by=None, name, history, visibility="team",
                result=None):
    """A row as historical code wrote it, bypassing today's canonical save."""
    payload = {
        "session_id": session_id, "user_id": user.id, "name": name, "status": "in_progress",
        "chat_history": [{"role": "user", "content": text} for text in history],
    }
    if result is not None:
        payload["result"] = result
    row = UserSession(
        user_id=str(user.id), session_id=session_id, name=name, document_type="strategy",
        status="in_progress", organization_id=organization_id,
        created_by_user_id=str((created_by or user).id), revision=1, visibility=visibility,
        payload=payload, scenarios_json={},
    )
    _db.session.add(row)
    _db.session.commit()
    return row


def _canonical_bytes(org, thread_id):
    return [entry for entry in _row_bytes(thread_id) if entry[1] == str(org.id) and entry[0] == str(_canonical_id(org, thread_id))]


def _canonical_id(org, thread_id):
    _db.session.expire_all()
    return (
        UserSession.query.filter_by(session_id=thread_id, organization_id=org.id)
        .order_by(UserSession.created_at.asc(), UserSession.id.asc()).first().id
    )


@pytest.fixture
def forked(app, db, team, outsider):
    """The owner's canonical team project, plus legacy same-id forks held by
    the editor, the viewer, a removed member and another organization's user."""
    owner, org = team["owner"], team["org"]
    thread_id = f"t-forked-{uuid.uuid4().hex[:6]}"
    _seed_project(owner, org, thread_id, rubric=OWNER_RUBRIC)
    removed = _mk_user("removed")
    _add_member(org, removed, "collaborator")
    forks = {}
    for label, user, fork_org in (
        ("editor", team["editor"], org.id),
        ("viewer", team["viewer"], org.id),
        ("removed_member", removed, org.id),
        ("other_organization", outsider["user"], outsider["org"].id),
    ):
        forks[label] = _insert_row(
            user=user, session_id=thread_id, organization_id=fork_org,
            name=f"{label} legacy fork", history=[f"{label} fork message"],
        ).id
    _remove_member(org, removed)
    actors = {"editor": team["editor"], "viewer": team["viewer"], "removed_member": removed,
              "other_organization": outsider["user"]}
    return {"thread_id": thread_id, "forks": forks, "actors": actors}


def _fork_bytes(fork_id):
    _db.session.expire_all()
    row = UserSession.query.get(fork_id)
    return (int(row.revision or 1), str(row.updated_at), json.dumps(row.payload, sort_keys=True, default=str))


@pytest.mark.parametrize("who", ["editor", "viewer", "removed_member", "other_organization"])
@pytest.mark.parametrize("credits", ["available", "refused"])
def test_start_never_lets_a_legacy_fork_overwrite_the_canonical_project(
    client, app, db, team, forked, monkeypatch, who, credits,
):
    org, thread_id = team["org"], forked["thread_id"]
    actor = forked["actors"][who]
    if who == "removed_member":
        # With organization access enforced, a removed member reaches nothing.
        # (Report mode, today's production setting, is covered separately.)
        monkeypatch.setenv("ORG_ACCESS_ENFORCEMENT", "enforce")
    canonical_before = _canonical_bytes(org, thread_id)
    forks_before = {label: _fork_bytes(fid) for label, fid in forked["forks"].items()}
    rows_before = len(_rows(thread_id))
    model = _install_scripted_model(monkeypatch, [])
    if credits == "refused":
        _refuse_reservations(monkeypatch)

    response = client.post(START_URL, headers=_headers(app, actor), json={
        "thread_id": thread_id, "message": "Start this again.",
    })

    assert _canonical_bytes(org, thread_id) == canonical_before
    for label, fid in forked["forks"].items():
        if not (who == "other_organization" and label == who):
            assert _fork_bytes(fid) == forks_before[label], label
    if who != "other_organization":
        assert response.status_code in {403, 404, 409}, response.get_json()
        assert model.calls == []
        assert len(_rows(thread_id)) == rows_before
    else:
        # The other organization's row is that user's own project in their own
        # organization; start may re-open it, and nothing of ours changes.
        assert len(_rows(thread_id)) == rows_before


def test_in_report_mode_a_removed_member_still_cannot_touch_the_canonical_project(
    client, app, db, team, forked, monkeypatch,
):
    """Report mode (SEC-06) still lets a former member reach an organization
    row they authored when that row IS the organization's canonical project.
    This member's row is a historical fork, so the id resolves to the
    organization's original project, which they are not authorized to use:
    start and continue cannot read or change it, and the fork is never used
    in its place."""
    org, thread_id = team["org"], forked["thread_id"]
    canonical_before = _canonical_bytes(org, thread_id)
    rows_before = len(_rows(thread_id))
    _install_scripted_model(monkeypatch, [])
    _refuse_reservations(monkeypatch)

    client.post(START_URL, headers=_headers(app, forked["actors"]["removed_member"]), json={
        "thread_id": thread_id, "message": "Start this again.",
    })
    client.post(CONTINUE_URL, headers=_headers(app, forked["actors"]["removed_member"]), json={
        "thread_id": thread_id, "message": "Continue this.",
    })

    assert _canonical_bytes(org, thread_id) == canonical_before
    assert len(_rows(thread_id)) == rows_before


def test_continue_with_a_legacy_fork_writes_the_canonical_project_only(client, app, db, team, forked, monkeypatch):
    org, thread_id, editor = team["org"], forked["thread_id"], team["editor"]
    fork_before = _fork_bytes(forked["forks"]["editor"])
    model = _install_scripted_model(monkeypatch, [("show_scoring_rubric", {})])

    response = client.post(CONTINUE_URL, headers=_headers(app, editor), json={
        "thread_id": thread_id, "message": "Next question on the shared project.",
    })

    assert response.status_code == 200, response.get_json()
    canonical = UserSession.query.get(_canonical_id(org, thread_id))
    contents = [m["content"] for m in canonical.payload["chat_history"]]
    assert contents[:3] == [
        "Should we bid on the regional contract?", "What matters most in this decision?",
        "Next question on the shared project.",
    ]
    assert "editor fork message" not in json.dumps(canonical.payload)
    assert _rubric_labels(canonical.payload) == ["Owner value", "Owner risk"]
    assert _fork_bytes(forked["forks"]["editor"]) == fork_before
    # The model saw the canonical conversation, not the fork's.
    assert "editor fork message" not in json.dumps(model.calls, default=str)
    shown = response.get_json()["actions"][0]["result"]
    assert _rubric_labels(shown) == ["Owner value", "Owner risk"]


def test_single_thread_reads_resolve_the_canonical_project_over_a_fork(app, db, team, forked):
    from app.routes.sessions import load_sessions_for_thread

    thread_id = forked["thread_id"]
    for who, expect_canonical in (("editor", True), ("viewer", True), ("removed_member", False)):
        sessions = load_sessions_for_thread(forked["actors"][who], thread_id)
        session = sessions.get(thread_id)
        if expect_canonical:
            assert session is not None and "fork message" not in json.dumps(session), who
            assert _rubric_labels(session) == ["Owner value", "Owner risk"], who
        else:
            assert session is None, who


def test_report_mode_fork_cannot_cross_the_callers_active_organization(
    client, app, db, team, outsider, forked, monkeypatch,
):
    """A removed member's org-bound fork is not a fallback when another org
    is active; all turn routes refuse without reading or changing either row."""
    from app.routes.sessions import load_sessions_for_thread
    from app.session_access import canonical_row

    actor = forked["actors"]["removed_member"]
    org_a = team["org"]
    thread_id = forked["thread_id"]
    _mk_org(actor, f"EmptyOrg{uuid.uuid4().hex[:6]}")
    monkeypatch.setenv("ORG_ACCESS_ENFORCEMENT", "report")

    # The fork never stands for the project: the id resolves to Org A's
    # original row, which this removed member is not authorized to use.
    resolved = canonical_row(actor, thread_id)
    assert resolved is not None and resolved.id == _canonical_id(org_a, thread_id)
    assert resolved.id != forked["forks"]["removed_member"]
    assert thread_id not in load_sessions_for_thread(actor, thread_id)
    canonical_before = _canonical_bytes(org_a, thread_id)
    forks_before = {label: _fork_bytes(fid) for label, fid in forked["forks"].items()}
    rows_before = len(_rows(thread_id))
    model = _install_scripted_model(monkeypatch, [])
    reservations = _spy_reservations(monkeypatch)

    responses = [
        client.post(START_URL, headers=_headers(app, actor), json={
            "thread_id": thread_id, "message": "Start the old project again.",
        }),
        client.post(CONTINUE_URL, headers=_headers(app, actor), json={
            "thread_id": thread_id, "message": "Continue the old project.",
        }),
        client.post(REGENERATE_URL, headers=_headers(app, actor), json={
            "thread_id": thread_id,
        }),
        client.post(UNDO_URL, headers=_headers(app, actor), json={
            "thread_id": thread_id,
        }),
    ]

    assert all(response.status_code == 404 for response in responses), [
        response.get_json() for response in responses
    ]
    assert model.calls == [] and reservations == []
    assert _canonical_bytes(org_a, thread_id) == canonical_before
    assert len(_rows(thread_id)) == rows_before
    assert {label: _fork_bytes(fid) for label, fid in forked["forks"].items()} == forks_before


def test_the_owner_can_still_reopen_their_canonical_thread_with_start(client, app, db, team, forked, monkeypatch):
    org, thread_id = team["org"], forked["thread_id"]
    _install_scripted_model(monkeypatch, [])

    response = client.post(START_URL, headers=_headers(app, team["owner"]), json={
        "thread_id": thread_id, "message": "Owner picks it back up.",
    })

    assert response.status_code == 200, response.get_json()
    canonical = UserSession.query.get(_canonical_id(org, thread_id))
    assert [m["content"] for m in canonical.payload["chat_history"]][:3] == [
        "Should we bid on the regional contract?", "What matters most in this decision?",
        "Owner picks it back up.",
    ]


# --------------------------------------------------------------------------
# (b) one author, two organizations, the same thread id
# --------------------------------------------------------------------------

MULTI_ID = "t-multi-org-author"
ALPHA_A = {"id": "alpha-author-card", "option_key": "option-harbor", "project_name": "Alpha Authored Harbor",
           "jaspen_score": 70, "score_category": "Strong"}
BRAVO_B = {"id": "bravo-author-card", "option_key": "option-bravo-only", "project_name": "Bravo Authored Bridge",
           "jaspen_score": 90, "score_category": "Strong"}
PERSONAL_P = {"id": "personal-author-card", "option_key": "option-personal", "project_name": "Personal Authored Plan",
              "jaspen_score": 55, "score_category": "Promising"}


@pytest.fixture
def author_in_two_orgs(app, db):
    from app.scorecards import upsert_scorecard

    author = _mk_user("author")
    alpha = _mk_org(author, f"AlphaA{uuid.uuid4().hex[:6]}")
    bravo_owner = _mk_user("bravo-host")
    bravo = _mk_org(bravo_owner, f"BravoA{uuid.uuid4().hex[:6]}")
    _add_member(bravo, author, "collaborator")
    alpha_editor = _mk_user("alpha-colleague")
    _add_member(alpha, alpha_editor, "collaborator")
    author.active_organization_id = alpha.id
    _db.session.commit()

    def result(card):
        return {**card, "_baseline_scorecard": card, "scorecard_snapshots": [card]}

    # Bravo's project (a colleague's, and older) and Alpha's (the author's own)
    # share an id. The author scored cards in both.
    _insert_row(user=bravo_owner, session_id=MULTI_ID, organization_id=bravo.id, name="Bravo bridge decision",
                history=["Bravo bridge question"], result=result(BRAVO_B))
    _insert_row(user=author, session_id=MULTI_ID, organization_id=alpha.id, name="Alpha harbor decision",
                history=["Alpha harbor question"], result=result(ALPHA_A))
    upsert_scorecard(user_id=author.id, thread_id=MULTI_ID, payload=BRAVO_B, organization_id=bravo.id)
    upsert_scorecard(user_id=author.id, thread_id=MULTI_ID, payload=ALPHA_A, organization_id=alpha.id)
    _db.session.commit()
    return {"author": author, "alpha": alpha, "bravo": bravo, "alpha_editor": alpha_editor,
            "bravo_owner": bravo_owner}


def _use_org(user, org):
    user.active_organization_id = org.id
    _db.session.commit()


def _record_card_names(record):
    return sorted(card.get("name") for card in (record.record or {}).get("scorecards") or [])


def test_a_decision_record_holds_only_its_organizations_scorecards(app, db, author_in_two_orgs):
    from app.decision_records import create_or_refresh_record

    author = author_in_two_orgs["author"]
    alpha_record, _ = create_or_refresh_record(author, MULTI_ID)
    assert alpha_record.organization_id == author_in_two_orgs["alpha"].id
    assert _record_card_names(alpha_record) == ["Alpha Authored Harbor"]
    assert alpha_record.title == "Alpha harbor decision"

    # Bravo's record, refreshed by Bravo's own owner, holds Bravo's card even
    # though the author (not the owner) scored it.
    bravo_record, _ = create_or_refresh_record(author_in_two_orgs["bravo_owner"], MULTI_ID)
    assert bravo_record.id != alpha_record.id
    assert bravo_record.organization_id == author_in_two_orgs["bravo"].id
    assert _record_card_names(bravo_record) == ["Bravo Authored Bridge"]

    # Refreshing Alpha again (e.g. by a colleague) still reads only Alpha.
    _db.session.expire_all()
    refreshed, created = create_or_refresh_record(author_in_two_orgs["alpha_editor"], MULTI_ID)
    assert not created and refreshed.id == alpha_record.id
    assert _record_card_names(refreshed) == ["Alpha Authored Harbor"]


def test_a_legacy_personal_record_never_imports_organization_scorecards(app, db):
    from app.decision_records import create_or_refresh_record
    from app.scorecards import upsert_scorecard

    author = _mk_user("legacy-author")
    alpha = _mk_org(author, f"AlphaL{uuid.uuid4().hex[:6]}")
    thread_id = f"t-personal-{uuid.uuid4().hex[:6]}"
    # A personal (pre-organization) project; Alpha has no project with this id.
    _insert_row(user=author, session_id=thread_id, organization_id=None, name="Personal decision",
                history=["Personal question"], visibility="private",
                result={**PERSONAL_P, "_baseline_scorecard": PERSONAL_P, "scorecard_snapshots": [PERSONAL_P]})
    upsert_scorecard(user_id=author.id, thread_id=thread_id, payload=PERSONAL_P, organization_id=None)
    upsert_scorecard(user_id=author.id, thread_id=thread_id, payload={**ALPHA_A, "id": "alpha-stray"},
                     organization_id=alpha.id)
    _db.session.commit()

    record, _ = create_or_refresh_record(author, thread_id)

    assert record.organization_id is None
    assert _record_card_names(record) == ["Personal Authored Plan"]


def test_decision_tools_cannot_reach_the_other_organizations_option(app, db, author_in_two_orgs):
    from app.models_decision_record import OptionDecision

    agent = _agent()
    author = author_in_two_orgs["author"]
    message = "We're going ahead with the Bravo Authored Bridge."
    result = agent._execute_mutation_tool(
        "record_option_decision",
        {"decisions": [{"option_name": "Bravo Authored Bridge", "disposition": "pursue",
                        "user_request_quote": "going ahead with the Bravo Authored Bridge"}]},
        user=author, user_id=author.id, thread_id=MULTI_ID, user_message=message,
    )

    assert "Bravo Authored Bridge" not in [
        item.get("option_name") for item in (result.get("decisions") or []) if item.get("status") == "recorded"
    ], result
    assert OptionDecision.query.filter_by(option_key="option-bravo-only").count() == 0
    # The same tool on Alpha's own option still works.
    ok = agent._execute_mutation_tool(
        "record_option_decision",
        {"decisions": [{"option_key": "option-harbor", "disposition": "still_evaluating",
                        "user_request_quote": "still weighing the harbor"}]},
        user=author, user_id=author.id, thread_id=MULTI_ID,
        user_message="We're still weighing the harbor.",
    )
    assert ok["ok"] is True, ok
    facts = agent._decision_facts_prompt_suffix(author.id, MULTI_ID)
    assert "Alpha Authored Harbor" in facts or "option-harbor" in facts
    assert "Bravo Authored Bridge" not in facts and "option-bravo-only" not in facts
    record = OptionDecision.query.filter_by(option_key="option-harbor").one()
    assert record.disposition == "still_evaluating"


@pytest.mark.parametrize("member", ["author", "alpha_editor"])
def test_prompts_for_a_multi_org_author_carry_only_the_active_project(
    client, app, db, author_in_two_orgs, monkeypatch, member,
):
    model = _install_scripted_model(monkeypatch, [])

    response = client.post(CONTINUE_URL, headers=_headers(app, author_in_two_orgs[member]), json={
        "thread_id": MULTI_ID, "message": "Where do the options stand?",
    })

    assert response.status_code == 200, response.get_json()
    everything = json.dumps(model.calls, default=str)
    assert "Alpha Authored Harbor" in _reply_call(model)["system"]
    assert "Bravo Authored Bridge" not in everything and "Bravo bridge question" not in everything
    canonical = UserSession.query.filter_by(session_id=MULTI_ID, organization_id=author_in_two_orgs["alpha"].id).one()
    assert "Where do the options stand?" in json.dumps(canonical.payload)
    bravo_row = UserSession.query.filter_by(session_id=MULTI_ID, organization_id=author_in_two_orgs["bravo"].id).one()
    assert "Where do the options stand?" not in json.dumps(bravo_row.payload)


# ==========================================================================
# Final reconciliation: the turn's organization and project stay authoritative
# for the whole request; legacy organization access keeps its contract; record
# assembly uses the target project's organization.
# ==========================================================================

class _SwitchingModel(_ScriptedModel):
    """Scripted model that switches the member's active organization (as
    another tab would) during the first provider call."""

    def __init__(self, steps, *, user, switch_to):
        super().__init__(steps)
        self._user, self._switch_to, self._switched = user, switch_to, False

    def create(self, client, **kwargs):
        if not self._switched:
            self._switched = True
            fresh = User.query.get(self._user.id)
            fresh.active_organization_id = self._switch_to.id
            _db.session.commit()
        return super().create(client, **kwargs)


def _install_switching_model(monkeypatch, steps, *, user, switch_to):
    model = _install_scripted_model(monkeypatch, [])
    switching = _SwitchingModel(steps, user=user, switch_to=switch_to)
    monkeypatch.setattr(_agent(), "_anthropic_message_create", switching.create)
    return switching


def _org_row(org, thread_id):
    _db.session.expire_all()
    return UserSession.query.filter_by(session_id=thread_id, organization_id=org.id).one()


def test_an_organization_switch_mid_turn_cannot_move_the_turn_to_another_project(
    client, app, db, two_orgs, monkeypatch,
):
    consultant, alpha, bravo = two_orgs["consultant"], two_orgs["alpha"], two_orgs["bravo"]
    bravo_before = _row_bytes(SAME_ID)
    bravo_before = [entry for entry in bravo_before if entry[1] == str(bravo.id)]
    model = _install_switching_model(monkeypatch, [
        ("set_scoring_rubric", {"criteria": NEW_CRITERIA}),
        ("show_scoring_rubric", {}),
    ], user=consultant, switch_to=bravo)

    response = client.post(CONTINUE_URL, headers=_headers(app, consultant), json={
        "thread_id": SAME_ID, "message": "Use delivery confidence at 60% and cost at 40%.",
    })

    assert response.status_code == 200, response.get_json()
    assert User.query.get(consultant.id).active_organization_id == bravo.id   # the switch happened
    shown = response.get_json()["actions"][-1]["result"]
    assert _rubric_labels(shown) == ["Delivery confidence", "Cost"]
    alpha_row = _org_row(alpha, SAME_ID)
    assert _rubric_labels(alpha_row.payload) == ["Delivery confidence", "Cost"]
    assert "Use delivery confidence at 60%" in json.dumps(alpha_row.payload["chat_history"])
    assert [entry for entry in _row_bytes(SAME_ID) if entry[1] == str(bravo.id)] == bravo_before
    everything = json.dumps(model.calls, default=str)
    assert "Bravo Secret Option" not in everything and "Bravo task" not in everything


@pytest.mark.parametrize("variant", ["reopen_own_thread", "new_project"])
def test_start_keeps_its_organization_when_the_member_switches(
    client, app, db, author_in_two_orgs, monkeypatch, variant,
):
    """conversation/start authorizes Alpha; the member switches to Bravo while
    the turn's tools are saving. Neither the re-opened project nor a new one
    may land on, or read from, Bravo's same-id project, which this member could
    otherwise write as a Bravo collaborator."""
    from app.routes.sessions import save_user_sessions

    author, alpha, bravo = author_in_two_orgs["author"], author_in_two_orgs["alpha"], author_in_two_orgs["bravo"]
    if variant == "reopen_own_thread":
        thread_id = MULTI_ID
    else:
        thread_id = f"t-start-switch-{uuid.uuid4().hex[:6]}"
        bravo_owner = author_in_two_orgs["bravo_owner"]
        assert save_user_sessions(bravo_owner.id, {thread_id: {
            "session_id": thread_id, "user_id": bravo_owner.id, "name": "Bravo same-id project",
            "status": "in_progress", "organization_id": bravo.id, "visibility": "team",
            "chat_history": [{"role": "user", "content": "Bravo bridge question"}],
        }})
    bravo_before = [entry for entry in _row_bytes(thread_id) if entry[1] == str(bravo.id)]
    assert bravo_before, "Bravo's same-id project must exist for this test"
    model = _install_switching_model(monkeypatch, [
        ("set_scoring_rubric", {"criteria": NEW_CRITERIA}),
        ("show_scoring_rubric", {}),
    ], user=author, switch_to=bravo)

    response = client.post(START_URL, headers=_headers(app, author), json={
        "thread_id": thread_id, "message": "Use delivery confidence at 60% and cost at 40%.",
    })

    assert response.status_code == 200, response.get_json()
    assert User.query.get(author.id).active_organization_id == bravo.id   # the switch happened
    shown = response.get_json()["actions"][-1]["result"]
    assert _rubric_labels(shown) == ["Delivery confidence", "Cost"]
    alpha_row = _org_row(alpha, thread_id)
    assert _rubric_labels(alpha_row.payload) == ["Delivery confidence", "Cost"]
    assert "Use delivery confidence at 60%" in json.dumps(alpha_row.payload["chat_history"])
    assert [entry for entry in _row_bytes(thread_id) if entry[1] == str(bravo.id)] == bravo_before
    everything = json.dumps(model.calls, default=str)
    assert "Bravo Authored Bridge" not in everything and "Bravo bridge question" not in everything


def test_regenerate_keeps_its_organization_when_the_member_switches(
    client, app, db, two_orgs, monkeypatch,
):
    consultant, alpha, bravo = two_orgs["consultant"], two_orgs["alpha"], two_orgs["bravo"]
    bravo_before = [entry for entry in _row_bytes(SAME_ID) if entry[1] == str(bravo.id)]
    model = _install_switching_model(monkeypatch, [], user=consultant, switch_to=bravo)

    response = client.post(REGENERATE_URL, headers=_headers(app, consultant), json={"thread_id": SAME_ID})

    assert response.status_code == 200, response.get_json()
    system = _reply_call(model)["system"]
    assert "Alpha Harbor Option" in system and "Bravo Secret Option" not in system
    alpha_history = _org_row(alpha, SAME_ID).payload["chat_history"]
    assert alpha_history[-1]["content"] == FINAL_TEXT and alpha_history[-1].get("regenerated")
    assert [entry for entry in _row_bytes(SAME_ID) if entry[1] == str(bravo.id)] == bravo_before


def test_a_turns_project_is_its_authorized_row_not_the_active_organizations(app, db, two_orgs):
    agent = _agent()
    consultant, alpha, bravo = two_orgs["consultant"], two_orgs["alpha"], two_orgs["bravo"]
    project = agent._build_turn_project(consultant, SAME_ID)
    assert project.organization_id == alpha.id

    _use_org(consultant, bravo)

    row = project.row()
    assert row is not None and row.organization_id == alpha.id
    assert "Alpha Harbor Option" in json.dumps(project.sessions())
    assert "Bravo Secret Option" not in json.dumps(project.sessions())


def test_legacy_access_to_a_members_own_organization_row_is_unchanged_outside_that_org(app, db):
    """Report/off-mode contract: a member's own organization row still
    resolves when another organization is active (no duplicate row is ever
    created for it), while a fork never stands for someone else's project."""
    from app.scenarios_store import save_project_scenarios_data
    from app.session_access import canonical_row

    member = _mk_user("legacy-member")
    home = _mk_org(member, f"Home{uuid.uuid4().hex[:6]}")
    thread_id = f"t-legacy-own-{uuid.uuid4().hex[:6]}"
    own = _insert_row(user=member, session_id=thread_id, organization_id=home.id,
                      name="Own legacy project", history=["Own question"])
    _mk_org(member, f"Elsewhere{uuid.uuid4().hex[:6]}")      # now active elsewhere

    assert canonical_row(member, thread_id).id == own.id
    save_project_scenarios_data(member.id, thread_id, {"scenarios": {}, "note": "kept"})
    rows = _rows(thread_id)
    assert len(rows) == 1 and rows[0].id == own.id
    assert rows[0].scenarios_json.get("note") == "kept"


def test_a_record_is_assembled_for_the_target_projects_organization(app, db, author_in_two_orgs):
    from app.decision_records import create_or_refresh_record

    author, alpha, bravo = author_in_two_orgs["author"], author_in_two_orgs["alpha"], author_in_two_orgs["bravo"]
    alpha_row = _org_row(alpha, MULTI_ID)
    _use_org(author, bravo)      # the author is now working in Bravo

    record, _ = create_or_refresh_record(author, MULTI_ID, session_row=alpha_row)

    assert record.organization_id == alpha.id
    assert _record_card_names(record) == ["Alpha Authored Harbor"]
    assert record.title == "Alpha harbor decision"
