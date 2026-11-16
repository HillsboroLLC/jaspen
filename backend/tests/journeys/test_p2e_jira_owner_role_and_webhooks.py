"""P2e (H-2e-2b): Jira sync pauses when its owner loses editing rights, and the
legacy Jira and Smartsheet webhooks change a project only for a member who may
edit it now, through a link Jaspen itself recorded."""

import json
import uuid

import pytest

from app import db
from app.connector_store import (
    load_connector_state,
    update_connector_settings,
    update_thread_sync_profile,
)
from app.models import ConnectorSyncLog, OrganizationMember, OrgAccessShadowEvent, UserSession
from app.models_pm_sync import PmSyncBinding
from tests.journeys.test_conversation_turn_lifecycle import _headers, solo  # noqa: F401
from tests.journeys.test_p2b_workspace_project_access import team  # noqa: F401
from tests.journeys.test_p2c_distribution_project_access import dist  # noqa: F401
from tests.journeys.test_p2e_jira_plan_access import (
    THREAD_ID,
    _insert_binding,
    _set_project_plans,
    _thread_scoped_load_scenario_calls,
)

ACTORS = ["owner", "administrator", "editor", "viewer", "creator-now-viewer",
          "former-member", "other-org"]
WRITERS = {"owner", "administrator", "editor"}
SECRET = "test-webhook-secret"
JIRA_SITE = "https://acme.atlassian.net"
READ_ONLY = "sync_owner_read_only"


@pytest.fixture(autouse=True)
def _enforce_removed_members(request, monkeypatch):
    params = getattr(getattr(request.node, "callspec", None), "params", {})
    if params.get("actor") == "former-member":
        monkeypatch.setenv("ORG_ACCESS_ENFORCEMENT", "enforce")


@pytest.fixture
def project(dist):
    _set_project_plans(dist["users"]["owner"], THREAD_ID)
    return dist


def _request(client, project, actor, method, path, body=None):
    return client.open(path, method=method, headers=_headers(project["app"], project["users"][actor]), json=body)


def _project_state(thread_id):
    db.session.expire_all()
    return [
        (r.id, r.user_id, int(r.revision or 1), r.last_edited_by_user_id,
         json.dumps(r.scenarios_json, sort_keys=True, default=str))
        for r in UserSession.query.filter_by(session_id=thread_id).order_by(UserSession.id).all()
    ]


def _world(project, thread_id):
    """Every store an inbound event or a sync step could write."""
    return {
        "project": _project_state(thread_id),
        "sessions": UserSession.query.count(),
        "connector_state": {
            name: json.dumps(load_connector_state(user.id), sort_keys=True, default=str)
            for name, user in project["users"].items()
        },
        "sync_logs": ConnectorSyncLog.query.count(),
        "bindings": [b.to_dict() for b in PmSyncBinding.query.order_by(PmSyncBinding.id).all()],
    }


# --- Part 1: the binding owner loses editing rights ----------------------


@pytest.fixture
def jira_calls(monkeypatch):
    calls = []

    def connected(user_id, project_key):
        calls.append(("assert_connected", str(user_id), project_key))
        return {"base_url": JIRA_SITE}

    def provider(connector_id):
        calls.append(("get_provider", connector_id))
        raise AssertionError("Jira must not be contacted")

    monkeypatch.setattr("app.pm_sync.service.jira_adapter.assert_connected", connected)
    monkeypatch.setattr("app.pm_sync.reconciliation.get_provider", provider)
    return calls


def _demote(project, actor, role="viewer"):
    membership = OrganizationMember.query.filter_by(
        organization_id=project["org"].id, user_id=project["users"][actor].id,
    ).one()
    membership.role = role
    db.session.commit()


OWNER_OPS = {
    "sync_push_only": ("POST", "/api/v1/pm-sync/bindings/{id}/sync", None, "push_only"),
    "sync_two_way": ("POST", "/api/v1/pm-sync/bindings/{id}/sync", None, "two_way"),
    "recreate_missing": ("POST", "/api/v1/pm-sync/bindings/{id}/recreate-missing", None, "push_only"),
    "unlink": ("POST", "/api/v1/pm-sync/bindings/{id}/unlink", None, "push_only"),
    "legacy_alias": ("POST", f"/api/v1/connectors/threads/{THREAD_ID}/jira/sync", {}, "push_only"),
    "patch": ("PATCH", "/api/v1/pm-sync/bindings/{id}", {"mode": "two_way", "status": "active"}, "push_only"),
}


@pytest.mark.parametrize("op", sorted(OWNER_OPS))
def test_owner_made_viewer_is_refused_before_jira_and_binding_pauses(client, project, jira_calls, op):
    method, path, body, mode = OWNER_OPS[op]
    binding = _insert_binding(project, actor="editor", mode=mode)
    _demote(project, "editor")
    before = _project_state(THREAD_ID)

    response = _request(client, project, "editor", method, path.format(id=binding.id), body if body is not None else {})

    _assert_paused_answer(response, binding.id, READ_ONLY)
    assert jira_calls == []
    db.session.expire_all()
    stored = PmSyncBinding.query.get(binding.id)
    assert stored.status == "paused"
    assert stored.config["pause_reason"] == READ_ONLY
    assert stored.config["sync_warning_code"] == READ_ONLY
    assert stored.mode == mode
    assert _project_state(THREAD_ID) == before


def _assert_paused_answer(response, binding_id, reason):
    """F1: one structured refusal; the reason code is never the message text."""
    assert response.status_code == 409
    body = response.get_json()
    assert body["code"] == "PM_SYNC_PAUSED"
    assert body["pause_reason"] == reason
    assert body["error"] != reason and reason not in body["error"]
    assert body["binding"]["id"] == binding_id
    assert body["binding"]["status"] == "paused"
    assert body["binding"]["pause_reason"] == reason


def test_listing_marks_a_read_only_owners_binding_paused(client, project):
    binding = _insert_binding(project, actor="editor")
    _demote(project, "editor")

    response = _request(client, project, "editor", "GET", f"/api/v1/pm-sync/bindings?thread_id={THREAD_ID}")

    assert response.status_code == 200
    listed = {row["id"]: row for row in response.get_json()["bindings"]}
    assert listed[binding.id]["status"] == "paused"
    assert listed[binding.id]["pause_reason"] == READ_ONLY


def test_rights_restored_binding_stays_paused_until_owner_resumes(client, project, jira_calls, monkeypatch):
    binding = _insert_binding(project, actor="editor", mode="push_only")
    _demote(project, "editor")
    assert _request(client, project, "editor", "POST", f"/api/v1/pm-sync/bindings/{binding.id}/sync", {}).status_code >= 400
    _demote(project, "editor", role="collaborator")

    still_paused = _request(client, project, "editor", "POST", f"/api/v1/pm-sync/bindings/{binding.id}/sync", {})
    _assert_paused_answer(still_paused, binding.id, READ_ONLY)
    assert jira_calls == []
    db.session.expire_all()
    assert PmSyncBinding.query.get(binding.id).status == "paused"

    pushes = []
    monkeypatch.setattr(
        "app.pm_sync.reconciliation.push_binding",
        lambda current, trigger="send", **_kw: pushes.append((current.id, trigger)) or {"success": True, "errors": []},
    )
    resumed = _request(client, project, "editor", "PATCH", f"/api/v1/pm-sync/bindings/{binding.id}", {"status": "active"})
    assert resumed.status_code == 200
    synced = _request(client, project, "editor", "POST", f"/api/v1/pm-sync/bindings/{binding.id}/sync", {})
    assert synced.status_code == 200
    assert pushes == [(binding.id, "sync_now")]


@pytest.mark.parametrize("op", ["sync_two_way", "recreate_missing", "patch_mode", "legacy_alias"])
def test_paused_binding_never_reactivates_implicitly(client, project, jira_calls, op):
    """OD-23: rights restored, not resumed. Nothing but an explicit resume
    makes the binding active or reaches Jira."""
    mode = "two_way" if op == "sync_two_way" else "push_only"
    binding = _insert_binding(project, actor="editor", mode=mode)
    _demote(project, "editor")
    _request(client, project, "editor", "POST", f"/api/v1/pm-sync/bindings/{binding.id}/sync", {})
    _demote(project, "editor", role="collaborator")
    path = {
        "sync_two_way": ("POST", f"/api/v1/pm-sync/bindings/{binding.id}/sync", {}),
        "recreate_missing": ("POST", f"/api/v1/pm-sync/bindings/{binding.id}/recreate-missing", {}),
        "patch_mode": ("PATCH", f"/api/v1/pm-sync/bindings/{binding.id}", {"mode": "two_way"}),
        "legacy_alias": ("POST", f"/api/v1/connectors/threads/{THREAD_ID}/jira/sync", {}),
    }[op]

    response = _request(client, project, "editor", *path)

    if op == "patch_mode":
        assert response.status_code == 200
        assert response.get_json()["binding"]["status"] == "paused"
    else:
        _assert_paused_answer(response, binding.id, READ_ONLY)
    assert jira_calls == []
    db.session.expire_all()
    stored = PmSyncBinding.query.get(binding.id)
    assert (stored.status, stored.config["pause_reason"]) == ("paused", READ_ONLY)


def _set_jira_connection(user, connected=True):
    """The owner's stored Jira connection, as /pm-sync/jira/connect saves it."""
    update_connector_settings(user.id, "jira_sync", {
        "jira_base_url": JIRA_SITE, "jira_email": "owner@acme.test", "jira_api_token": "test-token",
        "connection_status": "connected" if connected else "disconnected",
        "lifecycle_status": "connected" if connected else "disconnected",
    })


def test_resume_is_explicit_owner_only_and_checked(client, project):
    """F2: POST .../resume by the owner, refused while the reason still applies."""
    _set_jira_connection(project["users"]["editor"])
    binding = _insert_binding(project, actor="editor", mode="push_only")
    path = f"/api/v1/pm-sync/bindings/{binding.id}/resume"
    _demote(project, "editor")

    _assert_paused_answer(_request(client, project, "editor", "POST", path, {}), binding.id, READ_ONLY)
    db.session.expire_all()
    assert PmSyncBinding.query.get(binding.id).status == "paused"

    _demote(project, "editor", role="collaborator")
    for other in ("owner", "administrator", "viewer", "other-org"):
        assert _request(client, project, other, "POST", path, {}).status_code == 404
    db.session.expire_all()
    assert PmSyncBinding.query.get(binding.id).status == "paused"

    resumed = _request(client, project, "editor", "POST", path, {})
    assert resumed.status_code == 200
    assert resumed.get_json()["binding"]["status"] == "active"
    db.session.expire_all()
    stored = PmSyncBinding.query.get(binding.id)
    assert stored.status == "active"
    assert "pause_reason" not in stored.config and "sync_warning_code" not in stored.config

    again = _request(client, project, "editor", "POST", path, {})
    assert again.status_code == 200 and again.get_json()["binding"]["status"] == "active"


def test_resume_does_not_bypass_a_credential_pause(client, project):
    from app.pm_sync.access import mark_binding

    binding = _insert_binding(project, actor="editor", mode="push_only")
    mark_binding(binding, status="paused", warning_code="credential_disconnected", pause_reason="credential_disconnected")
    db.session.commit()

    response = _request(client, project, "editor", "POST", f"/api/v1/pm-sync/bindings/{binding.id}/resume", {})

    _assert_paused_answer(response, binding.id, "credential_disconnected")


def test_patch_status_active_is_the_same_checked_resume(client, project):
    _set_jira_connection(project["users"]["editor"])
    binding = _insert_binding(project, actor="editor", mode="push_only")
    _demote(project, "editor")
    path = f"/api/v1/pm-sync/bindings/{binding.id}"
    _assert_paused_answer(_request(client, project, "editor", "PATCH", path, {"status": "active"}), binding.id, READ_ONLY)

    _demote(project, "editor", role="collaborator")
    response = _request(client, project, "editor", "PATCH", path, {"status": "active"})

    assert response.status_code == 200
    db.session.expire_all()
    stored = PmSyncBinding.query.get(binding.id)
    assert stored.status == "active" and "pause_reason" not in stored.config


def test_private_visibility_change_pauses_the_owners_binding(client, project, jira_calls):
    binding = _insert_binding(project, actor="editor", mode="push_only")
    row = UserSession.query.filter_by(session_id=THREAD_ID).one()
    row.visibility = "private"
    db.session.commit()

    response = _request(client, project, "editor", "POST", f"/api/v1/pm-sync/bindings/{binding.id}/sync", {})

    _assert_paused_answer(response, binding.id, READ_ONLY)
    assert jira_calls == []
    db.session.expire_all()
    stored = PmSyncBinding.query.get(binding.id)
    assert (stored.status, stored.config["pause_reason"]) == ("paused", READ_ONLY)


@pytest.mark.parametrize("actor", sorted(WRITERS))
def test_editing_roles_bindings_still_sync(client, project, monkeypatch, actor):
    binding = _insert_binding(project, actor=actor, mode="push_only")
    pushes = []
    monkeypatch.setattr(
        "app.pm_sync.reconciliation.push_binding",
        lambda current, trigger="send", **_kw: pushes.append(current.id) or {"success": True, "errors": []},
    )

    response = _request(client, project, actor, "POST", f"/api/v1/pm-sync/bindings/{binding.id}/sync", {})

    assert response.status_code == 200
    assert pushes == [binding.id]
    db.session.expire_all()
    assert PmSyncBinding.query.get(binding.id).status == "active"


def test_departed_owner_keeps_its_own_reason(client, project, jira_calls):
    binding = _insert_binding(project, actor="editor", mode="push_only")
    OrganizationMember.query.filter_by(
        organization_id=project["org"].id, user_id=project["users"]["editor"].id,
    ).one().status = "removed"
    db.session.commit()

    response = _request(client, project, "editor", "POST", f"/api/v1/pm-sync/bindings/{binding.id}/sync", {})

    _assert_paused_answer(response, binding.id, "sync_owner_left_organization")
    db.session.expire_all()
    assert PmSyncBinding.query.get(binding.id).config["pause_reason"] == "sync_owner_left_organization"
    assert jira_calls == []


# --- Part 2: legacy inbound webhooks --------------------------------------

CONNECTORS = ["jira_sync", "smartsheet_sync"]
EXTERNAL = {"jira_sync": "JPT-1", "smartsheet_sync": "9001"}


@pytest.fixture
def secrets(app):
    app.config["JIRA_WEBHOOK_SECRET"] = SECRET
    app.config["SMARTSHEET_WEBHOOK_SECRET"] = SECRET
    yield
    app.config.pop("JIRA_WEBHOOK_SECRET", None)
    app.config.pop("SMARTSHEET_WEBHOOK_SECRET", None)


def _thread_for(project, actor):
    return THREAD_ID if actor == "other-org" else project["projects"][actor][0]


def _default_task(thread_id):
    return "task-1" if thread_id == THREAD_ID else "t1"


def _record_link(user, connector, thread_id, task_id=None, external=None, mode="two_way"):
    """What Jaspen's own legacy sync or import records for a member: the link,
    scoped to the organization the member is working in (P2e webhook tenant
    isolation: links without an owning organization are refused)."""
    from app.connector_store import link_organization_key

    task_id = task_id or _default_task(thread_id)
    links = {task_id: external or EXTERNAL[connector]}
    update_thread_sync_profile(user.id, thread_id, {
        "sync_mode": mode,
        "preferred_pm_tool": connector,
        "wbs_task_external_ids": links,
        "wbs_task_external_links_patch": {
            "organization_key": link_organization_key(user.active_organization_id),
            "links": links,
            "reconnect": True,
        },
    })
    if connector == "jira_sync":
        update_connector_settings(user.id, "jira_sync", {"jira_base_url": JIRA_SITE})


def _event(connector, user, thread_id, *, task_id=None, external=None, title=None,
           site=JIRA_SITE, include_task=True, include_thread=True):
    task_id = task_id or _default_task(thread_id)
    title = title or f"Renamed outside Jaspen {uuid.uuid4().hex[:6]}"
    external = external or EXTERNAL[connector]
    if connector == "jira_sync":
        labels = ["jaspen", f"jaspen_user_{user.id}"]
        if include_thread:
            labels.append(f"jaspen_thread_{thread_id}")
        if include_task:
            labels.append(f"jaspen_task_{task_id}")
        issue = {"key": external, "fields": {"summary": title, "labels": labels, "status": {"name": "In Progress"}}}
        if site:
            issue["self"] = f"{site}/rest/api/2/issue/10001"
        return "/api/v1/connectors/jira/webhook", {"issue": issue}, title
    metadata = {"user_id": user.id}
    if include_thread:
        metadata["thread_id"] = thread_id
    if include_task:
        metadata["task_id"] = task_id
    row = {"id": external, "jaspen_metadata": metadata,
           "cells": [{"columnName": "Task Name", "displayValue": title}]}
    return "/api/v1/connectors/smartsheet/webhook", {"row": row}, title


def _post(client, path, body):
    return client.post(path, json=body, headers={"X-Webhook-Secret": SECRET})


def _task(thread_id, task_id=None):
    task_id = task_id or _default_task(thread_id)
    db.session.expire_all()
    row = UserSession.query.filter_by(session_id=thread_id).one()
    return next(t for t in row.scenarios_json["project_wbs"]["tasks"] if t["id"] == task_id), row


@pytest.mark.parametrize("connector", CONNECTORS)
@pytest.mark.parametrize("actor", ACTORS)
def test_webhook_follows_the_named_members_current_role(client, project, secrets, connector, actor):
    user = project["users"][actor]
    thread_id = _thread_for(project, actor)
    _record_link(user, connector, thread_id)
    path, body, title = _event(connector, user, thread_id)
    before = _world(project, thread_id)

    response = _post(client, path, body)

    assert response.status_code == 200
    payload = response.get_json()
    if actor in WRITERS:
        assert payload["success"] is True and payload["thread_id"] == thread_id, payload
        task, row = _task(thread_id)
        assert task["title"] == title
        assert row.last_edited_by_user_id == user.id
        assert UserSession.query.filter_by(session_id=thread_id).count() == 1
        return
    expected = "not_authorized" if actor in {"viewer", "creator-now-viewer"} else "thread_not_found"
    assert payload == {"success": False, "ignored": True, "reason": expected}
    assert _world(project, thread_id) == before


@pytest.mark.parametrize("connector", CONNECTORS)
def test_editor_event_on_a_teammates_project_saves_the_canonical_row(client, project, secrets, connector):
    editor = project["users"]["editor"]
    _record_link(editor, connector, THREAD_ID)
    path, body, title = _event(connector, editor, THREAD_ID)

    response = _post(client, path, body)

    assert response.get_json()["success"] is True
    task, row = _task(THREAD_ID)
    assert task["title"] == title
    assert row.user_id == project["users"]["owner"].id
    assert UserSession.query.filter_by(session_id=THREAD_ID, user_id=editor.id).count() == 0


@pytest.mark.parametrize("connector", CONNECTORS)
def test_labels_alone_never_authorize_a_write(client, project, secrets, connector):
    """The owner recorded the link; an event naming the editor (who recorded
    nothing) is refused even though the editor may edit the project."""
    _record_link(project["users"]["owner"], connector, THREAD_ID)
    path, body, _title = _event(connector, project["users"]["editor"], THREAD_ID)
    before = _world(project, THREAD_ID)

    response = _post(client, path, body)

    assert response.get_json() == {"success": False, "ignored": True, "reason": "link_not_recorded"}
    assert _world(project, THREAD_ID) == before


@pytest.mark.parametrize("connector", CONNECTORS)
@pytest.mark.parametrize("case", ["no_link", "other_task_linked", "other_external_id"])
def test_event_without_a_matching_recorded_link_writes_nothing(client, project, secrets, connector, case):
    owner = project["users"]["owner"]
    if case == "no_link":
        update_thread_sync_profile(owner.id, THREAD_ID, {"sync_mode": "two_way"})
        update_connector_settings(owner.id, "jira_sync", {"jira_base_url": JIRA_SITE})
    elif case == "other_task_linked":
        _record_link(owner, connector, THREAD_ID, task_id="t-other")
    else:
        _record_link(owner, connector, THREAD_ID, external="JPT-99" if connector == "jira_sync" else "9999")
    path, body, _title = _event(connector, owner, THREAD_ID)
    before = _world(project, THREAD_ID)

    response = _post(client, path, body)

    assert response.get_json() == {"success": False, "ignored": True, "reason": "link_not_recorded"}
    assert _world(project, THREAD_ID) == before


@pytest.mark.parametrize("site", ["https://other-site.atlassian.net", None])
def test_jira_event_from_another_site_writes_nothing(client, project, secrets, site):
    owner = project["users"]["owner"]
    _record_link(owner, "jira_sync", THREAD_ID)
    path, body, _title = _event("jira_sync", owner, THREAD_ID, site=site)
    before = _world(project, THREAD_ID)

    response = _post(client, path, body)

    assert response.get_json() == {"success": False, "ignored": True, "reason": "link_not_recorded"}
    assert _world(project, THREAD_ID) == before


@pytest.mark.parametrize("connector", CONNECTORS)
def test_recorded_link_finds_the_task_without_a_task_label(client, project, secrets, connector):
    owner = project["users"]["owner"]
    _record_link(owner, connector, THREAD_ID)
    path, body, title = _event(connector, owner, THREAD_ID, include_task=False)

    response = _post(client, path, body)

    assert response.get_json()["success"] is True
    assert _task(THREAD_ID)[0]["title"] == title


@pytest.mark.parametrize("connector", CONNECTORS)
def test_event_without_a_project_reference_keeps_its_response_and_writes_nothing(client, project, secrets, connector):
    owner = project["users"]["owner"]
    _record_link(owner, connector, THREAD_ID)
    path, body, _title = _event(connector, owner, THREAD_ID, include_thread=False, include_task=False,
                                external="JPT-404" if connector == "jira_sync" else "404404")
    before = _world(project, THREAD_ID)

    response = _post(client, path, body)

    reason = "missing_thread_label" if connector == "jira_sync" else "missing_thread_reference"
    assert response.get_json() == {"success": False, "ignored": True, "reason": reason}
    assert _world(project, THREAD_ID) == before


@pytest.mark.parametrize("connector", CONNECTORS)
def test_push_only_profile_still_ignores_authorized_events(client, project, secrets, connector):
    owner = project["users"]["owner"]
    _record_link(owner, connector, THREAD_ID, mode="push")
    path, body, _title = _event(connector, owner, THREAD_ID)
    before = _project_state(THREAD_ID)

    response = _post(client, path, body)

    assert response.get_json()["reason"] == "thread_sync_is_push_only"
    assert _project_state(THREAD_ID) == before


@pytest.mark.parametrize("connector", CONNECTORS)
def test_report_mode_former_creator_event_is_pinned_and_audited(client, project, secrets, monkeypatch, connector):
    from app import org_access

    monkeypatch.setenv("ORG_ACCESS_ENFORCEMENT", "report")
    org_access.reset_dedup()
    former = project["users"]["former-member"]
    _record_link(former, connector, "t-former")
    path, body, title = _event(connector, former, "t-former")

    response = _post(client, path, body)

    # SEC-06: report mode still lets a former creator through. Pinned, not changed.
    assert response.get_json()["success"] is True
    assert _task("t-former")[0]["title"] == title
    assert OrgAccessShadowEvent.query.filter_by(user_id=former.id, mode="report", resource_id="t-former").count() >= 1


@pytest.mark.parametrize("connector", CONNECTORS)
def test_secret_checks_and_missing_member_are_unchanged(client, project, app, connector):
    env = "JIRA_WEBHOOK_SECRET" if connector == "jira_sync" else "SMARTSHEET_WEBHOOK_SECRET"
    path = "/api/v1/connectors/jira/webhook" if connector == "jira_sync" else "/api/v1/connectors/smartsheet/webhook"
    app.config[env] = ""
    assert client.post(path, json={}).status_code == 503
    app.config[env] = SECRET
    try:
        assert client.post(path, json={}, headers={"X-Webhook-Secret": "wrong"}).status_code == 401
        response = _post(client, path, {})
        assert response.status_code == 200
        assert response.get_json() == {"success": True, "ignored": True, "reason": "missing_user_label"}
    finally:
        app.config.pop(env, None)


def test_webhook_helpers_read_the_project_not_personal_rows():
    from app.jira_sync import apply_jira_webhook_to_wbs
    from app.smartsheet_sync import apply_smartsheet_webhook_to_wbs

    import ast
    import inspect
    import textwrap

    for helper in (apply_jira_webhook_to_wbs, apply_smartsheet_webhook_to_wbs):
        tree = ast.parse(textwrap.dedent(inspect.getsource(helper)))
        called = {
            node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
            for node in ast.walk(tree) if isinstance(node, ast.Call)
        }
        # Their thread id is a local (enforce_thread_id), so the H-2e-2a
        # parameter-based guard would pass vacuously; check the calls directly.
        assert "load_scenarios_data" not in called, helper.__name__
        assert "scenarios_for_thread" in called, helper.__name__


def test_webhook_routes_never_load_personal_scenarios():
    from app.routes import connectors

    assert _thread_scoped_load_scenario_calls(connectors) == []


# --- R1: a paused binding leaves "paused" only through the checked resume ---

BYPASS_STATUSES = ["active", "error", "partial", "links_missing", "reconnect_required", "disconnected"]


@pytest.fixture
def jira_network(monkeypatch):
    """Records real Jira HTTP requests, leaving the stored-connection check real."""
    calls = []

    def request(*args, **_kwargs):
        calls.append(args[1:3])
        raise AssertionError("Jira must not be contacted")

    monkeypatch.setattr("app.pm_sync.jira_adapter._jira_request", request)
    return calls


def _refused_everywhere(client, project, binding_id, reason):
    for method, path in (
        ("POST", f"/api/v1/pm-sync/bindings/{binding_id}/sync"),
        ("POST", f"/api/v1/pm-sync/bindings/{binding_id}/recreate-missing"),
        ("POST", f"/api/v1/connectors/threads/{THREAD_ID}/jira/sync"),
    ):
        _assert_paused_answer(_request(client, project, "editor", method, path, {}), binding_id, reason)


@pytest.mark.parametrize("target", BYPASS_STATUSES)
def test_patch_cannot_write_a_status_over_a_paused_binding(client, project, jira_network, target):
    """R1. The owner regained rights but has not resumed, and Jira is not
    connected, so even "active" (the resume path) is refused."""
    binding = _insert_binding(project, actor="editor", mode="push_only")
    _demote(project, "editor")
    _request(client, project, "editor", "POST", f"/api/v1/pm-sync/bindings/{binding.id}/sync", {})
    _demote(project, "editor", role="collaborator")

    response = _request(client, project, "editor", "PATCH", f"/api/v1/pm-sync/bindings/{binding.id}",
                        {"status": target, "mode": "two_way"})

    expected_reason = "credential_disconnected" if target == "active" else READ_ONLY
    _assert_paused_answer(response, binding.id, expected_reason)
    db.session.expire_all()
    stored = PmSyncBinding.query.get(binding.id)
    assert (stored.status, stored.config["pause_reason"], stored.mode) == ("paused", expected_reason, "push_only")
    _refused_everywhere(client, project, binding.id, expected_reason)
    assert jira_network == []


def test_patch_mode_and_policy_still_change_while_paused(client, project, jira_calls):
    binding = _insert_binding(project, actor="editor", mode="push_only")
    _demote(project, "editor")
    _request(client, project, "editor", "POST", f"/api/v1/pm-sync/bindings/{binding.id}/sync", {})
    _demote(project, "editor", role="collaborator")

    response = _request(client, project, "editor", "PATCH", f"/api/v1/pm-sync/bindings/{binding.id}",
                        {"mode": "two_way", "conflict_policy": "manual_review", "status": "paused"})

    assert response.status_code == 200
    db.session.expire_all()
    stored = PmSyncBinding.query.get(binding.id)
    assert (stored.status, stored.mode, stored.conflict_policy) == ("paused", "two_way", "manual_review")
    assert stored.config["pause_reason"] == READ_ONLY
    _refused_everywhere(client, project, binding.id, READ_ONLY)
    assert jira_calls == []


# --- R2: resume checks the owner's connection as it is now ----------------


def _disconnect_jira(user):
    """What the connector settings route does on disconnect."""
    from app.pm_sync.access import pause_personal_bindings

    _set_jira_connection(user, connected=False)
    pause_personal_bindings(user.id, "jira_sync", "credential_disconnected")
    db.session.commit()


def _reconnect_jira(user):
    """What /pm-sync/jira/connect does after a successful credential test."""
    from app.pm_sync.access import resume_personal_bindings

    _set_jira_connection(user, connected=True)
    resume_personal_bindings(user.id, "jira_sync")
    db.session.commit()


def _stored(binding_id):
    db.session.expire_all()
    row = PmSyncBinding.query.get(binding_id)
    return row.status, (row.config or {}).get("pause_reason")


def test_auditor_sequence_disconnect_then_role_loss_cannot_resume_without_reconnect(client, project):
    """R2, the re-verification's exact sequence: disconnect -> permission loss
    -> permission restored -> Resume. Must not activate without reconnecting."""
    editor = project["users"]["editor"]
    _set_jira_connection(editor)
    binding = _insert_binding(project, actor="editor", mode="push_only")
    sync = f"/api/v1/pm-sync/bindings/{binding.id}/sync"
    resume = f"/api/v1/pm-sync/bindings/{binding.id}/resume"

    _disconnect_jira(editor)
    assert _stored(binding.id) == ("paused", "credential_disconnected")
    _demote(project, "editor")
    _assert_paused_answer(_request(client, project, "editor", "POST", sync, {}), binding.id, READ_ONLY)
    assert _stored(binding.id) == ("paused", READ_ONLY)  # the stored reason no longer says "disconnected"
    _demote(project, "editor", role="collaborator")

    _assert_paused_answer(_request(client, project, "editor", "POST", resume, {}), binding.id, "credential_disconnected")
    assert _stored(binding.id) == ("paused", "credential_disconnected")
    _assert_paused_answer(
        _request(client, project, "editor", "PATCH", f"/api/v1/pm-sync/bindings/{binding.id}", {"status": "active"}),
        binding.id, "credential_disconnected",
    )
    _refused_everywhere(client, project, binding.id, "credential_disconnected")

    _reconnect_jira(editor)
    assert _stored(binding.id) == ("active", None)


def test_reconnect_does_not_bypass_a_remaining_role_restriction(client, project, monkeypatch):
    """R2, reverse order: permission loss -> disconnect -> reconnect while
    still read-only. Reconnecting restores the credential only."""
    editor = project["users"]["editor"]
    _set_jira_connection(editor)
    binding = _insert_binding(project, actor="editor", mode="push_only")
    _demote(project, "editor")
    _request(client, project, "editor", "POST", f"/api/v1/pm-sync/bindings/{binding.id}/sync", {})
    _disconnect_jira(editor)
    assert _stored(binding.id) == ("paused", "credential_disconnected")

    _reconnect_jira(editor)

    assert _stored(binding.id) == ("paused", READ_ONLY)
    _assert_paused_answer(
        _request(client, project, "editor", "PATCH", f"/api/v1/pm-sync/bindings/{binding.id}", {"status": "active"}),
        binding.id, READ_ONLY,
    )
    _refused_everywhere(client, project, binding.id, READ_ONLY)

    _demote(project, "editor", role="collaborator")
    resumed = _request(client, project, "editor", "POST", f"/api/v1/pm-sync/bindings/{binding.id}/resume", {})
    assert resumed.status_code == 200
    assert _stored(binding.id) == ("active", None)
    pushes = []
    monkeypatch.setattr(
        "app.pm_sync.reconciliation.push_binding",
        lambda current, trigger="send", **_kw: pushes.append(current.id) or {"success": True, "errors": []},
    )
    assert _request(client, project, "editor", "POST", f"/api/v1/pm-sync/bindings/{binding.id}/sync", {}).status_code == 200
    assert pushes == [binding.id]


def test_reconnect_still_resumes_a_plain_credential_pause(client, project):
    editor = project["users"]["editor"]
    _set_jira_connection(editor)
    binding = _insert_binding(project, actor="editor", mode="push_only")
    _disconnect_jira(editor)

    _reconnect_jira(editor)

    assert _stored(binding.id) == ("active", None)
