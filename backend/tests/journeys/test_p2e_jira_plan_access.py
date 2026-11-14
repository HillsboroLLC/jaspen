"""P2e: Jira plan access follows the organization's canonical project."""

import ast
import copy
import inspect
import textwrap

import pytest

from app import db
from app.connector_store import get_thread_sync_profile
from app.models import OrgAccessShadowEvent, UserSession
from app.models_pm_sync import PmSyncBinding, PmSyncLink
from app.pm_sync.reconciliation import FIELDS
from app.scenarios_store import save_project_scenarios_data
from tests.journeys.test_conversation_turn_lifecycle import _headers, solo  # noqa: F401
from tests.journeys.test_p2b_workspace_project_access import team  # noqa: F401
from tests.journeys.test_p2c_distribution_project_access import (  # noqa: F401
    MARKER,
    dist,
)


ACTORS = ["owner", "administrator", "editor", "viewer", "creator-now-viewer",
          "former-member", "other-org"]
READERS = {"owner", "administrator", "editor", "viewer", "creator-now-viewer"}
WRITERS = {"owner", "administrator", "editor"}
PLAN_KEY = "score-jira-access"
OTHER_PLAN_KEY = "score-other"
THREAD_ID = "t-shared"


@pytest.fixture(autouse=True)
def _enforce_removed_members(request, monkeypatch):
    params = getattr(getattr(request.node, "callspec", None), "params", {})
    if params.get("actor") == "former-member":
        monkeypatch.setenv("ORG_ACCESS_ENFORCEMENT", "enforce")


def _plan(marker=MARKER):
    phases = [f"Discover {marker}", f"Design {marker}", f"Deliver {marker}", f"Verify {marker}"]
    return {
        "scorecard_id": PLAN_KEY,
        "name": f"Jira access plan {marker}",
        "phases": phases,
        "tasks": [
            {
                "id": f"task-{index}",
                "title": f"Task {index} {marker}",
                "description": f"Work item {index}",
                "status": "todo",
                "phase": phases[(index - 1) % len(phases)],
                "depends_on": [] if index == 1 else [f"task-{index - 1}"],
                "lineage": [{"type": "requirement", "ref": f"req-{index}", "label": f"Requirement {index}"}],
            }
            for index in range(1, 11)
        ],
    }


def _set_project_plans(user, thread_id):
    plan = _plan()
    other = {
        "scorecard_id": OTHER_PLAN_KEY,
        "name": "Unrelated owner plan",
        "phases": ["Keep"],
        "tasks": [{"id": "other-task", "title": "Do not change", "phase": "Keep", "status": "todo"}],
    }

    def update(data):
        data["project_wbs"] = copy.deepcopy(plan)
        data["wbs_by_scorecard"] = {PLAN_KEY: copy.deepcopy(plan), OTHER_PLAN_KEY: copy.deepcopy(other)}
        data["active_execution_scorecard_id"] = PLAN_KEY
        return data

    save_project_scenarios_data(user.id, thread_id, updater=update)
    db.session.expire_all()


@pytest.fixture
def jira_project(dist):
    _set_project_plans(dist["users"]["owner"], THREAD_ID)
    return dist


def _request(client, project, actor, method, path, body=None):
    return client.open(
        path,
        method=method,
        headers=_headers(project["app"], project["users"][actor]),
        json=body,
    )


def _bind_payload(thread_id=THREAD_ID):
    return {
        "thread_id": thread_id,
        "plan_key": PLAN_KEY,
        "project_key": "JPT",
        "mode": "push_only",
        "conflict_policy": "manual_review",
        "config": {"group_under_epics": False},
    }


@pytest.fixture
def jira_recorder(monkeypatch):
    calls = []

    def connected(user_id, project_key):
        calls.append(("assert_connected", str(user_id), project_key))
        return {"base_url": "https://example.atlassian.net"}

    def discover(_config):
        calls.append(("discover_start_date_field",))
        return None

    def push(binding, plan, trigger="send", **_kwargs):
        calls.append(("push", str(binding.user_id), binding.thread_id, binding.plan_key, trigger))
        return {
            "success": True,
            "created": len(plan.get("tasks") or []),
            "updated": 0,
            "dependencies": 0,
            "failed": 0,
            "missing": 0,
            "errors": [],
        }

    monkeypatch.setattr("app.pm_sync.service.jira_adapter.assert_connected", connected)
    monkeypatch.setattr("app.pm_sync.service.jira_adapter.discover_start_date_field", discover)
    monkeypatch.setattr("app.routes.pm_sync.push_binding", push)
    return calls


@pytest.mark.parametrize("actor", ACTORS)
def test_preview_follows_read_access_without_contacting_jira(client, jira_project, jira_recorder, actor):
    response = _request(
        client, jira_project, actor, "GET",
        f"/api/v1/pm-sync/preview?thread_id={THREAD_ID}&plan_key={PLAN_KEY}",
    )

    if actor in READERS:
        assert response.status_code == 200
        assert response.get_json()["preview"]["issues"] == 10
        assert response.get_json()["preview"]["structure"].count("Creates epic") == 4
        assert MARKER.encode() in response.data
    else:
        assert response.status_code == 404
        assert response.get_json()["code"] == "not_found"
        assert MARKER.encode() not in response.data
    assert jira_recorder == []


@pytest.mark.parametrize("actor", ACTORS)
def test_bind_and_send_requires_current_edit_role(client, jira_project, jira_recorder, actor):
    response = _request(client, jira_project, actor, "POST", "/api/v1/pm-sync/bindings", _bind_payload())
    rows = PmSyncBinding.query.filter_by(thread_id=THREAD_ID, plan_key=PLAN_KEY).all()

    if actor in WRITERS:
        assert response.status_code == 201
        assert len(rows) == 1
        assert rows[0].user_id == jira_project["users"][actor].id
        assert rows[0].organization_id == jira_project["org"].id
        assert rows[0].plan_key == PLAN_KEY
        assert [call[0] for call in jira_recorder] == [
            "assert_connected", "discover_start_date_field", "push",
        ]
    else:
        expected = 403 if actor in READERS else 404
        assert response.status_code == expected
        assert response.get_json()["code"] == ("forbidden" if expected == 403 else "not_found")
        assert rows == []
        assert jira_recorder == []


def _insert_binding(project, actor="editor", *, mode="push_only", thread_id=THREAD_ID):
    user = project["users"][actor]
    binding = PmSyncBinding(
        user_id=user.id,
        organization_id=project["org"].id,
        thread_id=thread_id,
        plan_key=PLAN_KEY,
        connector_id="jira_sync",
        external_container_id="JPT",
        external_container_url="https://example.atlassian.net/browse/JPT",
        mode=mode,
        conflict_policy="prefer_external",
        policy_set_by_user_id=user.id,
        field_policy_overrides={},
        config={"task_issue_type": "Task", "group_under_epics": False, "start_date_field_id": ""},
        user_map={},
        status="active",
    )
    db.session.add(binding)
    db.session.commit()
    return binding


class _PullProvider:
    def __init__(self, tasks, calls):
        self.tasks = {f"JPT-{index}": copy.deepcopy(task) for index, task in enumerate(tasks, 1)}
        self.calls = calls

    def assert_connected(self, user_id, container_id):
        self.calls.append(("provider.assert_connected", str(user_id), container_id))
        return {"base_url": "https://example.atlassian.net"}

    def find_missing_items(self, _config, _binding, external_ids):
        self.calls.append(("provider.find_missing_items", tuple(sorted(external_ids))))
        return set()

    def ensure_recovery_identity(self, _config, _binding, external_id, jaspen_id):
        self.calls.append(("provider.ensure_identity", external_id, jaspen_id))

    def set_identity(self, *_args):
        self.calls.append(("provider.set_identity",))

    def get_item(self, _config, _binding, external_id):
        self.calls.append(("provider.get_item", external_id))
        task = self.tasks[external_id]
        values = {field: task.get(field) for field in FIELDS}
        changed_at = {}
        if external_id == "JPT-1":
            values["status"] = "done"
            changed_at["status"] = "2026-11-14T15:00:00+00:00"
        return {
            "deleted": False,
            "values": values,
            "changed_at": changed_at,
            "version": "2026-11-14T15:00:00+00:00",
            "supported_fields": list(FIELDS),
        }

    def update_item(self, _config, _binding, external_id, changes, _task=None):
        self.calls.append(("provider.update_item", external_id, copy.deepcopy(changes)))
        return {"status_mapped": True}


def _base_snapshot(task):
    base = {field: task.get(field) for field in FIELDS}
    base["_synced_fields"] = list(FIELDS)
    return base


def test_editors_personal_binding_syncs_owners_plan_and_saves_canonical_row(
    client, jira_project, monkeypatch,
):
    binding = _insert_binding(jira_project)
    row = UserSession.query.filter_by(session_id=THREAD_ID).one()
    other_before = copy.deepcopy(row.scenarios_json["wbs_by_scorecard"][OTHER_PLAN_KEY])
    tasks = row.scenarios_json["wbs_by_scorecard"][PLAN_KEY]["tasks"]
    for index, task in enumerate(tasks, 1):
        db.session.add(PmSyncLink(
            binding_id=binding.id,
            entity_type="task",
            jaspen_id=task["id"],
            external_id=f"JPT-{index}",
            base_snapshot=_base_snapshot(task),
            state="active",
        ))
    db.session.commit()

    calls = []

    def push_only(current_binding, plan=None, trigger="send", **_kwargs):
        from app.pm_sync.service import _persist_task_commitments, get_plan
        loaded, _key = get_plan(current_binding.user_id, current_binding.thread_id, current_binding.plan_key)
        loaded["tasks"][0]["commitment"] = {"connector_id": "jira_sync", "external_ref": "JPT-1"}
        _persist_task_commitments(current_binding, loaded)
        calls.append(("push_only", loaded["tasks"][0]["title"], trigger))
        return {"success": True, "created": 0, "updated": 10, "failed": 0, "errors": []}

    monkeypatch.setattr("app.pm_sync.reconciliation.push_binding", push_only)
    push_response = _request(
        client, jira_project, "editor", "POST", f"/api/v1/pm-sync/bindings/{binding.id}/sync", {},
    )
    assert push_response.status_code == 200
    assert calls == [("push_only", f"Task 1 {MARKER}", "sync_now")]
    db.session.expire_all()
    pushed_row = UserSession.query.filter_by(session_id=THREAD_ID).one()
    assert pushed_row.scenarios_json["wbs_by_scorecard"][PLAN_KEY]["tasks"][0]["commitment"] == {
        "connector_id": "jira_sync", "external_ref": "JPT-1",
    }
    assert UserSession.query.filter_by(
        session_id=THREAD_ID, user_id=jira_project["users"]["editor"].id,
    ).count() == 0

    binding.mode = "two_way"
    db.session.commit()
    provider = _PullProvider(tasks, calls)
    monkeypatch.setattr("app.pm_sync.reconciliation.get_provider", lambda _connector: provider)
    pull_response = _request(
        client, jira_project, "editor", "POST", f"/api/v1/pm-sync/bindings/{binding.id}/sync", {},
    )
    assert pull_response.status_code == 200
    assert any(call[0] == "provider.get_item" for call in calls)

    db.session.expire_all()
    stored = UserSession.query.filter_by(session_id=THREAD_ID).one()
    assert stored.scenarios_json["wbs_by_scorecard"][PLAN_KEY]["tasks"][0]["status"] == "done"
    assert stored.scenarios_json["project_wbs"]["tasks"][0]["status"] == "done"
    assert stored.scenarios_json["wbs_by_scorecard"][OTHER_PLAN_KEY] == other_before
    assert stored.last_edited_by_user_id == jira_project["users"]["editor"].id
    assert UserSession.query.filter_by(session_id=THREAD_ID, user_id=jira_project["users"]["editor"].id).count() == 0


def test_existing_owner_binding_refuses_editor_before_jira(client, jira_project, jira_recorder):
    binding = _insert_binding(jira_project, actor="owner")
    before = copy.deepcopy(binding.to_dict())

    response = _request(client, jira_project, "editor", "POST", "/api/v1/pm-sync/bindings", _bind_payload())

    assert response.status_code == 400
    assert response.get_json() == {"error": "This execution plan is already bound to Jira.", "code": "PM_SYNC_ERROR"}
    assert jira_recorder == []
    db.session.expire_all()
    assert PmSyncBinding.query.get(binding.id).to_dict() == before


@pytest.mark.parametrize("actor", ["viewer", "creator-now-viewer", "former-member", "other-org", "editor"])
def test_legacy_import_checks_access_before_external_work(
    client, jira_project, monkeypatch, actor,
):
    calls = []
    monkeypatch.setattr(
        "app.routes.connectors.get_connector_settings",
        lambda user_id, connector_id: calls.append(("settings", str(user_id), connector_id)) or {"lifecycle_status": "connected"},
    )
    monkeypatch.setattr(
        "app.routes.connectors.get_thread_sync_profile",
        lambda user_id, thread_id: {"preferred_pm_tool": "jira_sync", "conflict_policy": "prefer_external"},
    )
    monkeypatch.setattr(
        "app.routes.connectors.import_tasks_from_jira",
        lambda user_id, thread_id: calls.append(("jira_import", str(user_id), thread_id)) or {
            "success": True,
            "tasks": [{"id": "imported-task", "title": f"Imported {MARKER}", "status": "todo"}],
            "external_id_map": {"imported-task": "JPT-99"},
        },
    )

    response = _request(
        client, jira_project, actor, "POST", f"/api/v1/connectors/threads/{THREAD_ID}/jira_sync/import", {},
    )

    if actor == "editor":
        assert response.status_code == 200
        assert [call[0] for call in calls] == ["settings", "jira_import"]
        db.session.expire_all()
        row = UserSession.query.filter_by(session_id=THREAD_ID).one()
        assert any(task.get("title") == f"Imported {MARKER}" for task in row.scenarios_json["project_wbs"]["tasks"])
        assert row.last_edited_by_user_id == jira_project["users"]["editor"].id
        assert UserSession.query.filter_by(session_id=THREAD_ID, user_id=jira_project["users"]["editor"].id).count() == 0
    else:
        expected = 403 if actor in READERS else 404
        assert response.status_code == expected
        assert calls == []


@pytest.mark.parametrize("actor", ["viewer", "creator-now-viewer", "former-member", "other-org"])
def test_legacy_smartsheet_send_refuses_before_call_or_sync_lock(
    client, jira_project, monkeypatch, actor,
):
    user = jira_project["users"][actor]
    before = get_thread_sync_profile(user.id, THREAD_ID)
    calls = []
    monkeypatch.setattr(
        "app.routes.connectors.sync_wbs_to_smartsheet",
        lambda *_args, **_kwargs: calls.append("smartsheet") or {"success": True},
    )

    response = _request(
        client, jira_project, actor, "POST", f"/api/v1/connectors/threads/{THREAD_ID}/smartsheet/sync", {},
    )

    assert response.status_code == (403 if actor in READERS else 404)
    assert calls == []
    assert get_thread_sync_profile(user.id, THREAD_ID) == before
    assert get_thread_sync_profile(user.id, THREAD_ID)["sync_lock_acquired_at"] is None


@pytest.mark.parametrize("actor", ["owner", "administrator", "editor", "viewer", "creator-now-viewer", "other-org"])
def test_readiness_uses_the_readable_projects_plan(client, jira_project, actor):
    response = _request(
        client, jira_project, actor, "GET", f"/api/v1/connectors/threads/{THREAD_ID}/sync",
    )
    body = response.get_json()

    assert response.status_code == 200
    assert body["wbs_exists"] is (actor != "other-org")
    assert set(body) == {
        "thread_id", "preferred_pm_tool", "thread_sync_status", "wbs_exists", "sync_enabled",
        "connected_pm_tools", "available_pm_tools", "message", "thread_sync",
        "execution_connectors", "connected_execution_connectors",
    }


def test_owner_preview_and_bind_keep_the_existing_contract(client, jira_project, jira_recorder):
    preview = _request(
        client, jira_project, "owner", "GET",
        f"/api/v1/pm-sync/preview?thread_id={THREAD_ID}&plan_key={PLAN_KEY}&group_under_epics=false",
    )
    assert preview.status_code == 200
    assert preview.get_json() == {
        "thread_id": THREAD_ID,
        "plan_key": PLAN_KEY,
        "preview": {
            "epics": 0,
            "issues": 10,
            "dependencies": 9,
            "unmapped_owners": 0,
            "tasks_without_start_date": 10,
            "structure": "Creates 10 tasks without epics, 9 'Blocks' links.",
        },
    }

    response = _request(client, jira_project, "owner", "POST", "/api/v1/pm-sync/bindings", _bind_payload())
    assert response.status_code == 201
    binding = PmSyncBinding.query.one()
    assert binding.user_id == jira_project["users"]["owner"].id
    assert binding.organization_id == jira_project["org"].id
    assert binding.thread_id == THREAD_ID
    assert binding.plan_key == PLAN_KEY
    assert binding.external_container_id == "JPT"
    assert [call[0] for call in jira_recorder] == ["assert_connected", "discover_start_date_field", "push"]


@pytest.mark.parametrize("route", ["preview", "bind"])
def test_unknown_thread_is_not_found_before_jira(client, jira_project, jira_recorder, route):
    if route == "preview":
        response = _request(
            client, jira_project, "owner", "GET",
            f"/api/v1/pm-sync/preview?thread_id=unknown-jira-thread&plan_key={PLAN_KEY}",
        )
    else:
        response = _request(
            client, jira_project, "owner", "POST", "/api/v1/pm-sync/bindings",
            _bind_payload("unknown-jira-thread"),
        )

    assert response.status_code == 404
    assert response.get_json()["code"] == "not_found"
    assert jira_recorder == []
    assert PmSyncBinding.query.filter_by(thread_id="unknown-jira-thread").count() == 0


def test_report_mode_former_creator_binding_is_allowed_and_audited(
    client, jira_project, jira_recorder, monkeypatch,
):
    from app import org_access

    monkeypatch.setenv("ORG_ACCESS_ENFORCEMENT", "report")
    org_access.reset_dedup()
    _set_project_plans(jira_project["users"]["former-member"], "t-former")
    org_access.reset_dedup()
    response = _request(
        client, jira_project, "former-member", "POST", "/api/v1/pm-sync/bindings", _bind_payload("t-former"),
    )

    assert response.status_code == 201
    assert [call[0] for call in jira_recorder] == ["assert_connected", "discover_start_date_field", "push"]
    assert OrgAccessShadowEvent.query.filter_by(
        user_id=jira_project["users"]["former-member"].id,
        mode="report",
        resource_id="t-former",
    ).count() >= 1


def _thread_scoped_load_scenario_calls(source):
    tree = ast.parse(textwrap.dedent(inspect.getsource(source)))
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        names = {arg.arg for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)}
        has_thread_scope = "thread_id" in names or "binding" in names
        if not has_thread_scope:
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            called = child.func.id if isinstance(child.func, ast.Name) else (
                child.func.attr if isinstance(child.func, ast.Attribute) else None
            )
            if called == "load_scenarios_data":
                violations.append(node.name)
    return sorted(set(violations))


def test_thread_scoped_pm_functions_never_load_personal_scenarios():
    from app.pm_sync import reconciliation, service
    from app.routes import connectors

    assert _thread_scoped_load_scenario_calls(service) == []
    assert _thread_scoped_load_scenario_calls(reconciliation) == []
    assert _thread_scoped_load_scenario_calls(connectors) == []


def test_thread_scoped_load_guard_catches_a_regression():
    def regressed(thread_id):
        return load_scenarios_data("actor").get(thread_id)  # noqa: F821

    assert _thread_scoped_load_scenario_calls(regressed) == ["regressed"]
