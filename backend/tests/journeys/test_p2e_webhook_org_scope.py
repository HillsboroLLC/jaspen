"""P2e: legacy Jira and Smartsheet webhooks follow the link's owning organization.

The defect: the legacy webhooks authorized the named member in the member's
*active* organization and trusted a link from the member's per-user thread
sync profile, which is keyed by thread id only and recorded no organization.
A link recorded for organization A's project, with the member active in B
where a same-id project exists, could be authorized against, and applied to,
B's project.

Approved policy (Lydia):
1. Every recorded Jira/Smartsheet link carries a verified owning organization.
2. Authorization, project lookup and the webhook's read and write use that
   organization, never the member's active one.
3. Links without a verifiable organization fail closed (``link_not_scoped``).
4. The member reconnects them by running their own sync or import of the
   project, which records the project's organization.
5. Nothing infers or automatically assigns an organization to an existing
   unscoped link (an automatic post-turn sync does not reconnect).

Every refusal asserts that no project, profile, connector state or sync log
changed, and that no outbound HTTP call or background thread was started.
"""

import copy
import json
import uuid

import pytest

from app import db
from app.connector_store import (
    LINK_SCOPE_PERSONAL,
    _apply_scoped_link_patch,
    get_thread_sync_profile,
    link_organization_key,
    load_connector_state,
    update_connector_settings,
    update_thread_sync_profile,
)
from app.models import ConnectorSyncLog, OrganizationMember, UserSession
from app.routes.sessions import save_user_sessions
from app.scenarios_store import save_project_scenarios_data
from tests.journeys.test_conversation_turn_lifecycle import _mk_org, solo  # noqa: F401
from tests.journeys.test_p2b_workspace_project_access import team  # noqa: F401
from tests.journeys.test_p2c_distribution_project_access import dist  # noqa: F401
from tests.journeys.test_p2e_jira_owner_role_and_webhooks import (  # noqa: F401
    EXTERNAL,
    JIRA_SITE,
    _event,
    _post,
    secrets,
)
from tests.journeys.test_p2e_jira_plan_access import THREAD_ID, _set_project_plans

CONNECTORS = ["jira_sync", "smartsheet_sync"]
ORG_B_MARKER = "ORGB-WEBHOOK-PLAN"
TASK = "task-1"


# --- Fixtures -------------------------------------------------------------------

@pytest.fixture
def project(dist):
    _set_project_plans(dist["users"]["owner"], THREAD_ID)
    return dist


@pytest.fixture
def side_effects(monkeypatch):
    """Outbound HTTP and background threads, recorded and refused."""
    import threading

    import requests

    recorded = {"http": [], "threads": []}
    original_start = threading.Thread.start

    def _http(self, method, url, *args, **kwargs):
        recorded["http"].append((method, url))
        raise RuntimeError("no outbound call expected")

    def _start(self):
        target = getattr(self, "_target", None)
        if str(getattr(target, "__module__", "") or "").startswith("app."):
            recorded["threads"].append(getattr(target, "__qualname__", repr(target)))
            return None  # an application background job: recorded, never run
        return original_start(self)

    monkeypatch.setattr(requests.sessions.Session, "request", _http)
    monkeypatch.setattr(threading.Thread, "start", _start)
    return recorded


def _org_b(project, actor="editor", *, with_project=True):
    """``actor`` creates organization B and makes it active. With
    ``with_project`` they own a same-id ``t-shared`` there, whose plan has a
    ``task-1`` too."""
    user = project["users"][actor]
    org_b = _mk_org(user, f"OrgB{uuid.uuid4().hex[:6]}")
    if with_project:
        assert save_user_sessions(user.id, {THREAD_ID: {
            "session_id": THREAD_ID, "user_id": user.id, "name": f"B project {ORG_B_MARKER}",
            "status": "in_progress", "organization_id": org_b.id, "visibility": "team",
            "chat_history": [],
        }})
        plan = {"name": f"B plan {ORG_B_MARKER}", "phases": ["B"],
                "tasks": [{"id": TASK, "title": f"B task {ORG_B_MARKER}", "status": "todo", "phase": "B"}]}

        def update(data):
            data["project_wbs"] = copy.deepcopy(plan)
            return data

        save_project_scenarios_data(user.id, THREAD_ID, updater=update)
    db.session.expire_all()
    return org_b


def _switch(user, org):
    user.active_organization_id = org.id
    db.session.commit()
    db.session.expire_all()


def _demote(project, actor, role="viewer"):
    OrganizationMember.query.filter_by(
        organization_id=project["org"].id, user_id=project["users"][actor].id,
    ).one().role = role
    db.session.commit()


def _record_scoped(user, connector, org_id, *, external=None, task_id=TASK, mode="two_way"):
    """A link as Jaspen's own sync or import now records it."""
    links = {task_id: external or EXTERNAL[connector]}
    update_thread_sync_profile(user.id, THREAD_ID, {
        "sync_mode": mode, "preferred_pm_tool": connector,
        "wbs_task_external_ids": links,
        "wbs_task_external_links_patch": {
            "organization_key": link_organization_key(org_id), "links": links, "reconnect": True,
        },
    })
    if connector == "jira_sync":
        update_connector_settings(user.id, "jira_sync", {"jira_base_url": JIRA_SITE})


def _record_legacy(user, connector, *, external=None, task_id=TASK, mode="two_way"):
    """A link recorded before owning organizations were stored."""
    update_thread_sync_profile(user.id, THREAD_ID, {
        "sync_mode": mode, "preferred_pm_tool": connector,
        "wbs_task_external_ids": {task_id: external or EXTERNAL[connector]},
    })
    if connector == "jira_sync":
        update_connector_settings(user.id, "jira_sync", {"jira_base_url": JIRA_SITE})


def _rows_by_org():
    db.session.expire_all()
    return {
        str(r.organization_id): (
            r.id, r.user_id, int(r.revision or 1), r.last_edited_by_user_id,
            json.dumps(r.payload, sort_keys=True, default=str),
            json.dumps(r.scenarios_json, sort_keys=True, default=str),
        )
        for r in UserSession.query.filter_by(session_id=THREAD_ID).order_by(UserSession.id).all()
    }


def _world(project):
    """Every store an inbound event could write."""
    return {
        "projects": _rows_by_org(),
        "sessions": UserSession.query.count(),
        "connector_state": {
            name: json.dumps(load_connector_state(user.id), sort_keys=True, default=str)
            for name, user in project["users"].items()
        },
        "sync_logs": ConnectorSyncLog.query.count(),
    }


def _task_title(org_id):
    db.session.expire_all()
    row = UserSession.query.filter_by(session_id=THREAD_ID, organization_id=str(org_id)).one()
    task = next(t for t in row.scenarios_json["project_wbs"]["tasks"] if t["id"] == TASK)
    return task["title"], row


def _refused(response, reason):
    assert response.status_code == 200
    assert response.get_json() == {"success": False, "ignored": True, "reason": reason}


# --- A's link, member active in B ------------------------------------------------

@pytest.mark.parametrize("connector", CONNECTORS)
@pytest.mark.parametrize("b_project", [True, False], ids=["same-id-project-in-b", "no-project-in-b"])
def test_event_for_as_link_applies_to_as_project_while_active_in_b(
    client, project, secrets, side_effects, connector, b_project,
):
    """Still an editor in A, active in B: the event changes A's project only."""
    editor, org_a = project["users"]["editor"], project["org"]
    _record_scoped(editor, connector, org_a.id)
    org_b = _org_b(project, with_project=b_project)
    b_before = _rows_by_org().get(str(org_b.id))
    path, body, title = _event(connector, editor, THREAD_ID)

    response = _post(client, path, body)

    assert response.get_json()["success"] is True, response.get_json()
    a_title, a_row = _task_title(org_a.id)
    assert a_title == title
    assert a_row.last_edited_by_user_id == editor.id
    assert _rows_by_org().get(str(org_b.id)) == b_before, "organization B's project changed"
    assert side_effects == {"http": [], "threads": []}


@pytest.mark.parametrize("connector", CONNECTORS)
@pytest.mark.parametrize("b_project", [True, False], ids=["same-id-project-in-b", "no-project-in-b"])
def test_member_demoted_in_a_is_refused_even_while_active_in_b(
    client, project, secrets, side_effects, connector, b_project,
):
    """The role that counts is the one in the link's organization (A). Being
    able to edit B's same-id project does not authorize A's link."""
    editor, org_a = project["users"]["editor"], project["org"]
    _record_scoped(editor, connector, org_a.id)
    _demote(project, "editor")
    _org_b(project, with_project=b_project)
    path, body, _title = _event(connector, editor, THREAD_ID)
    before = _world(project)

    response = _post(client, path, body)

    _refused(response, "not_authorized")
    assert ORG_B_MARKER.encode() not in response.data
    assert _world(project) == before
    assert side_effects == {"http": [], "threads": []}


@pytest.mark.parametrize("connector", CONNECTORS)
def test_link_owned_by_b_applies_to_bs_project_while_active_in_a(client, project, secrets, side_effects, connector):
    """The reverse: a link recorded for B's project, with the member active
    in A (where a same-id project exists), changes B's project only."""
    editor, org_a = project["users"]["editor"], project["org"]
    org_b = _org_b(project)
    _record_scoped(editor, connector, org_b.id)
    _switch(editor, org_a)
    a_before = _rows_by_org()[str(org_a.id)]
    path, body, title = _event(connector, editor, THREAD_ID)

    response = _post(client, path, body)

    assert response.get_json()["success"] is True, response.get_json()
    assert _task_title(org_b.id)[0] == title
    assert _rows_by_org()[str(org_a.id)] == a_before, "organization A's project changed"


@pytest.mark.parametrize("connector", CONNECTORS)
def test_owning_organizations_project_gone_never_falls_back_to_another(client, project, secrets, side_effects, connector):
    """A's project is gone; the member owns a same-id project in B. The link
    is A's, so the event is refused and B is untouched (the active-org lookup
    would otherwise fall back to the member's B row)."""
    editor, org_a = project["users"]["editor"], project["org"]
    _record_scoped(editor, connector, org_a.id)
    _org_b(project)
    UserSession.query.filter_by(session_id=THREAD_ID, organization_id=str(org_a.id)).delete()
    db.session.commit()
    path, body, _title = _event(connector, editor, THREAD_ID)
    before = _world(project)

    response = _post(client, path, body)

    _refused(response, "thread_not_found")
    assert _world(project) == before
    assert side_effects == {"http": [], "threads": []}


@pytest.mark.parametrize("connector", CONNECTORS)
def test_former_member_of_the_owning_organization_is_refused(client, project, secrets, side_effects, connector, monkeypatch):
    monkeypatch.setenv("ORG_ACCESS_ENFORCEMENT", "enforce")
    editor, org_a = project["users"]["editor"], project["org"]
    _record_scoped(editor, connector, org_a.id)
    _org_b(project)
    OrganizationMember.query.filter_by(organization_id=org_a.id, user_id=editor.id).one().status = "removed"
    db.session.commit()
    path, body, _title = _event(connector, editor, THREAD_ID)
    before = _world(project)

    response = _post(client, path, body)

    _refused(response, "thread_not_found")
    assert _world(project) == before


@pytest.mark.parametrize("connector", CONNECTORS)
def test_same_external_id_scoped_to_two_organizations_is_ambiguous(client, project, secrets, side_effects, connector):
    editor, org_a = project["users"]["editor"], project["org"]
    org_b = _org_b(project)
    _record_scoped(editor, connector, org_a.id)
    _record_scoped(editor, connector, org_b.id)
    path, body, _title = _event(connector, editor, THREAD_ID)
    before = _world(project)

    response = _post(client, path, body)

    _refused(response, "link_ambiguous")
    assert _world(project) == before


# --- Legacy links fail closed, until the member reconnects -------------------------

@pytest.mark.parametrize("connector", CONNECTORS)
@pytest.mark.parametrize("switched", [False, True], ids=["active-in-a", "active-in-b"])
def test_legacy_unscoped_link_fails_closed(client, project, secrets, side_effects, connector, switched):
    """A link with no recorded organization is refused for everyone, even an
    editor of the project, and no organization is inferred."""
    editor = project["users"]["editor"]
    _record_legacy(editor, connector)
    if switched:
        _org_b(project)
    path, body, _title = _event(connector, editor, THREAD_ID)
    before = _world(project)

    response = _post(client, path, body)

    _refused(response, "link_not_scoped")
    assert _world(project) == before
    assert get_thread_sync_profile(editor.id, THREAD_ID)["wbs_task_external_links"] == {}
    assert side_effects == {"http": [], "threads": []}


@pytest.mark.parametrize("connector", CONNECTORS)
def test_member_reconnects_a_legacy_link_by_importing_the_project(client, project, secrets, monkeypatch, connector):
    """The member's own import of the project records the link under the
    project's organization; the next event is accepted and lands in A."""
    from app.routes import connectors as connector_routes
    from tests.journeys.test_conversation_turn_lifecycle import _headers

    editor, org_a = project["users"]["editor"], project["org"]
    _record_legacy(editor, connector)
    path, body, title = _event(connector, editor, THREAD_ID)
    _refused(_post(client, path, body), "link_not_scoped")

    update_connector_settings(editor.id, connector, {"lifecycle_status": "connected", "connection_status": "connected"})
    imported = {"success": True, "tasks": [], "external_id_map": {TASK: EXTERNAL[connector]}}
    name = "import_tasks_from_jira" if connector == "jira_sync" else "import_tasks_from_smartsheet"
    monkeypatch.setattr(connector_routes, name, lambda *_a, **_k: dict(imported))
    reconnect = client.post(f"/api/v1/connectors/threads/{THREAD_ID}/{connector}/import",
                            headers=_headers(project["app"], editor), json={})
    assert reconnect.status_code == 200, reconnect.get_data(as_text=True)[:300]
    scoped = get_thread_sync_profile(editor.id, THREAD_ID)["wbs_task_external_links"]
    assert scoped == {str(org_a.id): {TASK: EXTERNAL[connector]}}

    path, body, title = _event(connector, editor, THREAD_ID)
    response = _post(client, path, body)
    assert response.get_json()["success"] is True, response.get_json()
    assert _task_title(org_a.id)[0] == title


@pytest.mark.parametrize("connector", CONNECTORS)
def test_reconnect_from_b_records_bs_organization_not_as(client, project, secrets, monkeypatch, connector):
    """Importing while active in B reconnects the link for B's project. A's
    project never receives the events."""
    from app.routes import connectors as connector_routes
    from tests.journeys.test_conversation_turn_lifecycle import _headers

    editor, org_a = project["users"]["editor"], project["org"]
    _record_legacy(editor, connector)
    org_b = _org_b(project)
    update_connector_settings(editor.id, connector, {"lifecycle_status": "connected", "connection_status": "connected"})
    name = "import_tasks_from_jira" if connector == "jira_sync" else "import_tasks_from_smartsheet"
    monkeypatch.setattr(connector_routes, name, lambda *_a, **_k: {
        "success": True, "tasks": [], "external_id_map": {TASK: EXTERNAL[connector]},
    })
    assert client.post(f"/api/v1/connectors/threads/{THREAD_ID}/{connector}/import",
                       headers=_headers(project["app"], editor), json={}).status_code == 200
    assert get_thread_sync_profile(editor.id, THREAD_ID)["wbs_task_external_links"] == {
        str(org_b.id): {TASK: EXTERNAL[connector]},
    }
    a_before = _rows_by_org()[str(org_a.id)]
    path, body, title = _event(connector, editor, THREAD_ID)

    assert _post(client, path, body).get_json()["success"] is True
    assert _task_title(org_b.id)[0] == title
    assert _rows_by_org()[str(org_a.id)] == a_before


@pytest.mark.parametrize("connector", CONNECTORS)
def test_automatic_post_turn_sync_does_not_reconnect_a_legacy_link(client, project, secrets, monkeypatch, connector):
    """An automatic sync never gives an organization to a link that existed
    without one. A link it newly creates is recorded with the project's
    organization."""
    from app.routes import ai_agent

    editor, org_a = project["users"]["editor"], project["org"]
    _record_legacy(editor, connector)
    update_thread_sync_profile(editor.id, THREAD_ID, {"thread_sync_status": "synced", "auto_sync": True})
    update_connector_settings(editor.id, connector, {"lifecycle_status": "connected", "connection_status": "connected"})
    new_external = "JPT-2" if connector == "jira_sync" else "9002"
    ref_key = "jira_issue_key" if connector == "jira_sync" else "smartsheet_row_id"
    synced_wbs = {"tasks": [
        {"id": TASK, "external_refs": {ref_key: EXTERNAL[connector]}},
        {"id": "task-2", "external_refs": {ref_key: new_external}},
    ]}
    monkeypatch.setattr(ai_agent, "_dispatch_sync_for_preferred_pm_tool",
                        lambda *_a, **_k: ({"success": True, "project_wbs": synced_wbs}, connector))

    with project["app"].test_request_context():
        status = ai_agent._trigger_post_mutation_sync(editor.id, THREAD_ID, synced_wbs)
    assert status["status"] == "synced"

    scoped = get_thread_sync_profile(editor.id, THREAD_ID)["wbs_task_external_links"]
    assert scoped == {str(org_a.id): {"task-2": new_external}}, "the legacy link was reconnected automatically"
    path, body, _title = _event(connector, editor, THREAD_ID)
    _refused(_post(client, path, body), "link_not_scoped")


# --- Store rules -------------------------------------------------------------------

def test_scoped_link_patch_rules():
    prior_flat = {"legacy": "JPT-1"}
    scoped = _apply_scoped_link_patch({}, prior_flat, {
        "organization_key": "org-a", "links": {"legacy": "JPT-1", "new": "JPT-2"}, "reconnect": False,
    })
    assert scoped == {"org-a": {"new": "JPT-2"}}, "a legacy link was given an organization without reconnecting"

    scoped = _apply_scoped_link_patch(scoped, prior_flat, {
        "organization_key": "org-a", "links": {"legacy": "JPT-1"}, "reconnect": True,
    })
    assert scoped == {"org-a": {"new": "JPT-2", "legacy": "JPT-1"}}

    assert _apply_scoped_link_patch(scoped, prior_flat, {"organization_key": "", "links": {"x": "JPT-9"}}) == scoped
    assert _apply_scoped_link_patch(scoped, prior_flat, {
        "organization_key": "org-a", "links": {"new": "", "legacy": ""},
    }) == {}
    assert link_organization_key(None) == LINK_SCOPE_PERSONAL
    assert link_organization_key("org-a") == "org-a"
