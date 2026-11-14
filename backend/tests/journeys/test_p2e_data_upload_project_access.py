"""P2e: data uploads write only an authorized canonical project."""

import ast
import copy
import inspect
import io
import textwrap

import pytest

from app import db as _db
from app.models import OrganizationMember, OrgAccessShadowEvent, UserSession
from tests.journeys.test_conversation_turn_lifecycle import _headers, solo  # noqa: F401
from tests.journeys.test_p2b_workspace_project_access import (  # noqa: F401
    HIST, KIT, MARKER, _no_rate_limits, team,
)
from tests.journeys.test_p2c_distribution_project_access import dist  # noqa: F401


ACTORS = ["owner", "administrator", "editor", "viewer", "creator-now-viewer",
          "former-member", "other-org"]
WRITERS = {"owner", "administrator", "editor"}
INSIGHT_TEXT = "Recorded insight"


@pytest.fixture(autouse=True)
def _enforce_former_member_matrix(request, monkeypatch):
    params = getattr(getattr(request.node, "callspec", None), "params", {})
    if params.get("actor") == "former-member":
        monkeypatch.setenv("ORG_ACCESS_ENFORCEMENT", "enforce")


@pytest.fixture
def model_calls(monkeypatch):
    from app.routes import ai_agent
    calls = []

    def _record(summary, prompt, **kwargs):
        calls.append({"summary": summary, "prompt": prompt, **kwargs})
        return INSIGHT_TEXT, "test"

    monkeypatch.setattr(ai_agent, "_llm_data_insight_text", _record)
    return calls


def _upload(client, fixture, actor, *, thread_id="t-shared", location="form",
            extra_headers=None):
    headers = _headers(fixture["app"], fixture["users"][actor])
    headers.update(extra_headers or {})
    path = "/api/v1/ai-agent/analyze-data"
    data = {"file": (io.BytesIO(b"month,value\nJan,10\nFeb,12\n"), "trend.csv")}
    if thread_id is not None:
        if location == "query":
            path += f"?thread_id={thread_id}"
        else:
            data["thread_id"] = thread_id
    return client.post(path, headers=headers, data=data, content_type="multipart/form-data")


def _row(thread_id):
    _db.session.expire_all()
    return UserSession.query.filter_by(session_id=thread_id).one()


def _row_snapshot(thread_id):
    row = _row(thread_id)
    return {
        "id": row.id, "user_id": row.user_id,
        "organization_id": row.organization_id,
        "created_by_user_id": row.created_by_user_id,
        "last_edited_by_user_id": row.last_edited_by_user_id,
        "name": row.name, "status": row.status, "visibility": row.visibility,
        "shared_with_user_ids": copy.deepcopy(row.shared_with_user_ids),
        "payload": copy.deepcopy(row.payload),
        "scenarios_json": copy.deepcopy(row.scenarios_json),
        "revision": int(row.revision or 1),
        "created_at": row.created_at, "updated_at": row.updated_at,
    }


def _assert_one_append(before, after, actor_id):
    old_payload, new_payload = before["payload"], after["payload"]
    old_insights = old_payload.get("ai_insights") or []
    new_insights = new_payload.get("ai_insights") or []
    assert len(new_insights) == len(old_insights) + 1
    assert new_insights[1:] == old_insights
    assert new_insights[0]["summary"] == INSIGHT_TEXT
    assert len(new_payload["chat_history"]) == len(old_payload["chat_history"]) + 1
    assert new_payload["chat_history"][:-1] == old_payload["chat_history"]
    assert new_payload["chat_history"][-1]["content"] == f"[AI Data Insights] {INSIGHT_TEXT}"
    assert after["last_edited_by_user_id"] == str(actor_id)
    assert after["revision"] == before["revision"] + 1


@pytest.mark.parametrize("location", ["form", "query"])
@pytest.mark.parametrize("actor", ACTORS)
def test_upload_access_matrix(client, dist, model_calls, actor, location):
    thread_id, _card_id = dist["projects"][actor]
    before = _row_snapshot(thread_id)
    response = _upload(client, dist, actor, thread_id=thread_id, location=location)

    if actor in WRITERS:
        assert response.status_code == 200, response.get_data(as_text=True)
        assert response.get_json()["persisted"] is True
        assert len(model_calls) == 1
        _assert_one_append(before, _row_snapshot(thread_id), dist["users"][actor].id)
    else:
        expected = 403 if actor in {"viewer", "creator-now-viewer"} else 404
        assert response.status_code == expected, response.get_data(as_text=True)
        assert response.get_json()["code"] == ("forbidden" if expected == 403 else "not_found")
        assert model_calls == []
        assert _row_snapshot(thread_id) == before
        if actor == "other-org":
            outsider = dist["users"][actor]
            assert UserSession.query.filter_by(user_id=outsider.id, session_id=thread_id).count() == 0


@pytest.mark.parametrize("actor", ["editor", "administrator"])
def test_collaborator_upload_preserves_all_other_project_state(client, dist, model_calls, actor):
    row = _row("t-shared")
    row.shared_with_user_ids = [str(dist["users"]["viewer"].id)]
    payload = dict(row.payload)
    payload["shared_with_user_ids"] = list(row.shared_with_user_ids)
    payload["decision_kit_context"] = {"source": MARKER, "approved": True}
    payload["scorecard_snapshots"] = [{"id": "snapshot-1", "marker": MARKER}]
    row.payload = payload
    _db.session.commit()
    before = _row_snapshot("t-shared")

    response = _upload(client, dist, actor)

    assert response.status_code == 200
    after = _row_snapshot("t-shared")
    for field in ("name", "visibility", "shared_with_user_ids", "status", "user_id",
                  "created_by_user_id", "organization_id", "scenarios_json"):
        assert after[field] == before[field], field
    for field in ("decision_kit", "decision_kit_context", "result", "scorecard_snapshots"):
        assert after["payload"].get(field) == before["payload"].get(field), field
    assert after["payload"]["chat_history"][:-1] == before["payload"]["chat_history"]
    _assert_one_append(before, after, dist["users"][actor].id)
    assert UserSession.query.filter_by(session_id="t-shared").count() == 1


def test_owner_response_and_event_shape_remain_compatible(client, dist, model_calls):
    response = _upload(client, dist, "owner")
    assert response.status_code == 200
    body = response.get_json()
    assert set(body) == {"success", "thread_id", "insight", "preview_rows", "persisted",
                         "persisted_event"}
    assert set(body["persisted_event"]) == {"id", "timestamp", "file_name", "summary", "insight"}
    assert body["persisted_event"]["file_name"] == "trend.csv"
    assert body["persisted_event"]["summary"] == INSIGHT_TEXT
    assert body["persisted_event"]["insight"] == body["insight"]
    assert _row("t-shared").payload["ai_insights"][0] == body["persisted_event"]


def test_upload_does_not_resave_the_editors_other_project(client, dist, model_calls):
    from app.routes.sessions import save_user_sessions
    editor = dist["users"]["editor"]
    assert save_user_sessions(editor.id, {"editor-other": {
        "session_id": "editor-other", "name": "Editor's untouched project",
        "chat_history": [{"role": "user", "content": "Keep exactly"}],
    }})
    before = _row_snapshot("editor-other")
    response = _upload(client, dist, "editor")
    assert response.status_code == 200
    assert _row_snapshot("editor-other") == before


@pytest.mark.parametrize("header_value", ["web-fresh-browser-id", "t-shared"])
def test_no_project_id_ignores_x_session_id(client, dist, model_calls, header_value):
    before = _row_snapshot("t-shared")
    response = _upload(client, dist, "editor", thread_id=None,
                       extra_headers={"X-Session-ID": header_value})
    assert response.status_code == 200
    body = response.get_json()
    assert body["thread_id"] is None
    assert body["persisted"] is False
    assert body["persisted_event"] is None
    assert len(model_calls) == 1
    assert _row_snapshot("t-shared") == before
    assert UserSession.query.filter_by(session_id=header_value).count() == (
        1 if header_value == "t-shared" else 0
    )


def test_unknown_project_is_refused_before_the_model(client, dist, model_calls):
    response = _upload(client, dist, "owner", thread_id="unknown-upload-project")
    assert response.status_code == 404
    assert response.get_json()["code"] == "not_found"
    assert model_calls == []
    assert UserSession.query.filter_by(session_id="unknown-upload-project").count() == 0


def test_report_mode_former_creator_upload_is_audited(client, dist, model_calls, monkeypatch):
    from app import org_access
    monkeypatch.setenv("ORG_ACCESS_ENFORCEMENT", "report")
    org_access.reset_dedup()
    former = dist["users"]["former-member"]
    before = _row_snapshot("t-former")
    response = _upload(client, dist, "former-member", thread_id="t-former")
    assert response.status_code == 200
    assert response.get_json()["persisted"] is True
    assert len(model_calls) == 1
    _assert_one_append(before, _row_snapshot("t-former"), former.id)
    assert OrgAccessShadowEvent.query.filter_by(
        user_id=former.id, mode="report", resource_id="t-former"
    ).count() >= 1


def _competitor_save(original_save, owner, thread_id, *, name, chat_text):
    current = _row_snapshot(thread_id)
    staged = copy.deepcopy(current["payload"])
    staged["name"] = name
    staged["chat_history"] = list(staged.get("chat_history") or []) + [
        {"role": "user", "content": chat_text}
    ]
    staged["base_revision"] = current["revision"]
    assert original_save(owner.id, {thread_id: staged})


def test_teammate_edit_during_model_call_is_preserved(client, dist, monkeypatch):
    from app.routes import ai_agent
    from app.routes.sessions import save_user_sessions
    calls = []
    owner = dist["users"]["owner"]

    def _model(*_args, **_kwargs):
        calls.append(True)
        _competitor_save(save_user_sessions, owner, "t-shared",
                         name="Owner renamed during model", chat_text="Owner note during model")
        return INSIGHT_TEXT, "test"

    monkeypatch.setattr(ai_agent, "_llm_data_insight_text", _model)
    response = _upload(client, dist, "editor")
    assert response.status_code == 200
    assert response.get_json()["persisted"] is True
    after = _row_snapshot("t-shared")
    assert after["name"] == "Owner renamed during model"
    assert any(m.get("content") == "Owner note during model" for m in after["payload"]["chat_history"])
    assert after["payload"]["ai_insights"][0]["summary"] == INSIGHT_TEXT
    assert calls == [True]


def test_lost_race_at_save_reloads_and_retries_once(client, dist, model_calls, monkeypatch):
    from app.routes import ai_agent
    original_save = ai_agent.save_user_sessions
    owner = dist["users"]["owner"]
    attempts = []

    def _racing_save(user_id, sessions, *args, **kwargs):
        attempts.append(True)
        if len(attempts) == 1:
            _competitor_save(original_save, owner, "t-shared",
                             name="Owner won first save race", chat_text="Owner race entry")
        return original_save(user_id, sessions, *args, **kwargs)

    monkeypatch.setattr(ai_agent, "save_user_sessions", _racing_save)
    response = _upload(client, dist, "editor")
    assert response.status_code == 200
    assert response.get_json()["persisted"] is True
    after = _row_snapshot("t-shared")
    assert after["name"] == "Owner won first save race"
    assert any(m.get("content") == "Owner race entry" for m in after["payload"]["chat_history"])
    assert after["payload"]["ai_insights"][0]["summary"] == INSIGHT_TEXT
    assert len(attempts) == 2
    assert len(model_calls) == 1


def test_every_save_attempt_loses_without_overwriting(client, dist, model_calls, monkeypatch):
    from app.routes import ai_agent
    original_save = ai_agent.save_user_sessions
    owner = dist["users"]["owner"]
    attempts = []

    def _always_racing_save(user_id, sessions, *args, **kwargs):
        attempt = len(attempts) + 1
        attempts.append(attempt)
        _competitor_save(original_save, owner, "t-shared", name=f"Competitor version {attempt}",
                         chat_text=f"Competitor entry {attempt}")
        return original_save(user_id, sessions, *args, **kwargs)

    monkeypatch.setattr(ai_agent, "save_user_sessions", _always_racing_save)
    response = _upload(client, dist, "editor")
    assert response.status_code == 200
    assert response.get_json()["persisted"] is False
    assert response.get_json()["persisted_event"] is None
    after = _row_snapshot("t-shared")
    assert after["name"] == "Competitor version 3"
    assert after["payload"]["chat_history"][-1]["content"] == "Competitor entry 3"
    assert after["payload"].get("ai_insights") in (None, [])
    assert attempts == [1, 2, 3]
    assert len(model_calls) == 1


def test_role_removed_during_model_call_returns_unpersisted(client, dist, monkeypatch):
    from app.routes import ai_agent
    editor = dist["users"]["editor"]
    before = _row_snapshot("t-shared")
    calls = []

    def _remove_role(*_args, **_kwargs):
        calls.append(True)
        membership = OrganizationMember.query.filter_by(
            organization_id=dist["org"].id, user_id=editor.id
        ).one()
        membership.role = "viewer"
        _db.session.commit()
        return INSIGHT_TEXT, "test"

    monkeypatch.setattr(ai_agent, "_llm_data_insight_text", _remove_role)
    response = _upload(client, dist, "editor")
    assert response.status_code == 200
    assert response.get_json()["persisted"] is False
    assert response.get_json()["persisted_event"] is None
    assert _row_snapshot("t-shared") == before
    assert calls == [True]


def _guard_offenders(source):
    tree = ast.parse(textwrap.dedent(source))
    functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    offenders = []
    for name in ("_persist_thread_insight", "analyze_data"):
        function = functions.get(name)
        if function is None:
            continue
        for node in ast.walk(function):
            if isinstance(node, ast.Call):
                called = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if called == "load_user_sessions":
                    offenders.append((name, "load_user_sessions"))
                if name == "_persist_thread_insight" and called == "_new_session":
                    offenders.append((name, "_new_session"))
            if name == "analyze_data" and isinstance(node, ast.Constant) and node.value == "X-Session-ID":
                offenders.append((name, "X-Session-ID"))
    return offenders


def test_data_upload_project_code_has_no_personal_lookup_creation_or_browser_header():
    from app.routes import ai_agent
    source = "\n\n".join([inspect.getsource(ai_agent._persist_thread_insight),
                            inspect.getsource(ai_agent.analyze_data)])
    assert _guard_offenders(source) == []


@pytest.mark.parametrize(("source", "expected"), [
    ("""\n    def _persist_thread_insight():\n        return load_user_sessions('u')\n    """,
     ("_persist_thread_insight", "load_user_sessions")),
    ("""\n    def _persist_thread_insight():\n        return _new_session('u', 't', 'name')\n    """,
     ("_persist_thread_insight", "_new_session")),
    ("""\n    def analyze_data():\n        return request.headers.get('X-Session-ID')\n    """,
     ("analyze_data", "X-Session-ID")),
])
def test_data_upload_guard_catches_each_forbidden_pattern(source, expected):
    assert expected in _guard_offenders(source)
