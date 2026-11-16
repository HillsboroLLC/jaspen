"""P2e-4 N1: a Jira binding follows its own organization, not the owner's active one.

The defect: a binding owner demoted from editor to viewer in organization A
switched their active organization to B. The pause check resolved the project
through the owner's active organization, so it either found nothing (and a
missing project is not a pause reason) or found B's project under the same
thread id (where the owner may edit). Either way the sync was not paused; with
a same-id project in B it read B's plan, contacted Jira, and imported A's Jira
content into B.

The rule (same as ``decision_records.record_project_row``): a binding's
project is the row in ``binding.organization_id`` (or, for a personal binding,
its owner's rows with no organization). The pause check, the plan a sync
reads, and every plan write the sync makes use that row. The legacy alias only
uses a binding of the readable project's organization.

Each refusal asserts the structured pause, zero Jira calls, and that neither
organization's project changed.
"""

import copy
import json
import uuid

import pytest

from app import db
from app.models import OrganizationMember, UserSession
from app.models_pm_sync import PmSyncBinding, PmSyncLink
from app.routes.sessions import save_user_sessions
from app.scenarios_store import save_project_scenarios_data
from tests.journeys.test_conversation_turn_lifecycle import _headers, _mk_org, solo  # noqa: F401
from tests.journeys.test_p2b_workspace_project_access import team  # noqa: F401
from tests.journeys.test_p2c_distribution_project_access import dist  # noqa: F401
from tests.journeys.test_p2e_jira_owner_role_and_webhooks import _assert_paused_answer
from tests.journeys.test_p2e_jira_plan_access import (
    MARKER,
    PLAN_KEY,
    THREAD_ID,
    _PullProvider,
    _base_snapshot,
    _insert_binding,
    _set_project_plans,
)

READ_ONLY = "sync_owner_read_only"
ORG_B_MARKER = "ORGB-N1-PLAN"
SWITCHES = ["no-matching-project-in-b", "matching-project-in-b"]


# --- Fixtures -----------------------------------------------------------------

@pytest.fixture
def project(dist):
    _set_project_plans(dist["users"]["owner"], THREAD_ID)
    return dist


@pytest.fixture
def jira_calls(monkeypatch):
    """Every Jira contact a binding sync could make, recorded and refused."""
    calls = []

    def connected(user_id, project_key):
        calls.append(("assert_connected", str(user_id), project_key))
        raise AssertionError("Jira must not be contacted")

    def provider(connector_id):
        calls.append(("get_provider", connector_id))
        raise AssertionError("Jira must not be contacted")

    monkeypatch.setattr("app.pm_sync.service.jira_adapter.assert_connected", connected)
    monkeypatch.setattr("app.pm_sync.reconciliation.get_provider", provider)
    return calls


def _request(client, project, actor, method, path, body=None):
    return client.open(path, method=method, headers=_headers(project["app"], project["users"][actor]), json=body)


def _demote(project, actor, role="viewer"):
    membership = OrganizationMember.query.filter_by(
        organization_id=project["org"].id, user_id=project["users"][actor].id,
    ).one()
    membership.role = role
    db.session.commit()


def _org_b_plan():
    return {
        "scorecard_id": PLAN_KEY, "name": f"Org B plan {ORG_B_MARKER}", "phases": ["B"],
        "tasks": [{"id": "task-1", "title": f"B task {ORG_B_MARKER}", "status": "todo", "phase": "B"}],
    }


def _switch_to_b(project, actor, switch):
    """The actor creates organization B and makes it active. With
    ``matching-project-in-b`` they also own a ``t-shared`` project there,
    with its own plan under the same plan key."""
    user = project["users"][actor]
    org_b = _mk_org(user, f"OrgB{uuid.uuid4().hex[:6]}")
    if switch == "matching-project-in-b":
        assert save_user_sessions(user.id, {THREAD_ID: {
            "session_id": THREAD_ID, "user_id": user.id, "name": f"B project {ORG_B_MARKER}",
            "status": "in_progress", "organization_id": org_b.id, "visibility": "team",
            "chat_history": [],
        }})
        plan = _org_b_plan()

        def update(data):
            data["project_wbs"] = copy.deepcopy(plan)
            data["wbs_by_scorecard"] = {PLAN_KEY: copy.deepcopy(plan)}
            data["active_execution_scorecard_id"] = PLAN_KEY
            return data

        save_project_scenarios_data(user.id, THREAD_ID, updater=update)
    db.session.expire_all()
    assert str(project["users"][actor].active_organization_id) == str(org_b.id)
    return org_b


def _rows_by_org():
    """Every row stored under the thread id, keyed by organization."""
    db.session.expire_all()
    return {
        str(r.organization_id): (
            r.id, r.user_id, int(r.revision or 1), r.last_edited_by_user_id,
            json.dumps(r.payload, sort_keys=True, default=str),
            json.dumps(r.scenarios_json, sort_keys=True, default=str),
        )
        for r in UserSession.query.filter_by(session_id=THREAD_ID).order_by(UserSession.id).all()
    }


def _row_in(org_id):
    db.session.expire_all()
    return UserSession.query.filter_by(session_id=THREAD_ID, organization_id=str(org_id)).one()


def _link_tasks(binding, org_id):
    """Active Jira links for the binding's own project's tasks."""
    tasks = _row_in(org_id).scenarios_json["wbs_by_scorecard"][PLAN_KEY]["tasks"]
    for index, task in enumerate(tasks, 1):
        db.session.add(PmSyncLink(
            binding_id=binding.id, entity_type="task", jaspen_id=task["id"],
            external_id=f"JPT-{index}", base_snapshot=_base_snapshot(task), state="active",
        ))
    db.session.commit()
    return tasks


# --- The demoted owner who switches organizations -----------------------------

BINDING_OPS = {
    "sync_push_only": ("POST", "/api/v1/pm-sync/bindings/{id}/sync", None, "push_only"),
    "sync_two_way": ("POST", "/api/v1/pm-sync/bindings/{id}/sync", None, "two_way"),
    "recreate_missing": ("POST", "/api/v1/pm-sync/bindings/{id}/recreate-missing", None, "push_only"),
    "unlink": ("POST", "/api/v1/pm-sync/bindings/{id}/unlink", None, "push_only"),
    "resume_patch": ("PATCH", "/api/v1/pm-sync/bindings/{id}", {"status": "active"}, "push_only"),
    "resume_post": ("POST", "/api/v1/pm-sync/bindings/{id}/resume", None, "push_only"),
}


@pytest.mark.parametrize("switch", SWITCHES)
@pytest.mark.parametrize("op", sorted(BINDING_OPS))
def test_demoted_owner_switching_organizations_is_paused_before_jira(client, project, jira_calls, op, switch):
    method, path, body, mode = BINDING_OPS[op]
    binding = _insert_binding(project, actor="editor", mode=mode)
    _link_tasks(binding, project["org"].id)
    _demote(project, "editor")
    _switch_to_b(project, "editor", switch)
    before = _rows_by_org()

    response = _request(client, project, "editor", method, path.format(id=binding.id), body if body is not None else {})

    _assert_paused_answer(response, binding.id, READ_ONLY)
    assert ORG_B_MARKER.encode() not in response.data and MARKER.encode() not in response.data
    assert jira_calls == [], (op, switch, jira_calls)
    db.session.expire_all()
    stored = PmSyncBinding.query.get(binding.id)
    assert (stored.status, stored.config["pause_reason"]) == ("paused", READ_ONLY)
    assert str(stored.organization_id) == str(project["org"].id)
    assert _rows_by_org() == before, (op, switch, "a project changed")


@pytest.mark.parametrize("switch", SWITCHES)
def test_listing_marks_the_switched_demoted_owners_binding_paused(client, project, switch):
    binding = _insert_binding(project, actor="editor")
    _demote(project, "editor")
    _switch_to_b(project, "editor", switch)
    before = _rows_by_org()

    response = _request(client, project, "editor", "GET", f"/api/v1/pm-sync/bindings?thread_id={THREAD_ID}")

    assert response.status_code == 200
    listed = {row["id"]: row for row in response.get_json()["bindings"]}
    assert (listed[binding.id]["status"], listed[binding.id]["pause_reason"]) == ("paused", READ_ONLY)
    assert _rows_by_org() == before


@pytest.mark.parametrize("switch", SWITCHES)
@pytest.mark.parametrize("demoted", [True, False], ids=["demoted", "still-editor"])
def test_legacy_alias_never_uses_another_organizations_binding(client, project, jira_calls, switch, demoted):
    """Active in B, ``/threads/t-shared/jira/sync`` names B's project (or
    none). A's binding is not that project's, so it is never picked up: the
    alias answers that no destination is chosen, with zero Jira calls and
    neither project changed. A's binding is left exactly as it was."""
    binding = _insert_binding(project, actor="editor", mode="push_only")
    if demoted:
        _demote(project, "editor")
    _switch_to_b(project, "editor", switch)
    before = _rows_by_org()
    binding_before = PmSyncBinding.query.get(binding.id).to_dict()

    response = _request(client, project, "editor", "POST", f"/api/v1/connectors/threads/{THREAD_ID}/jira/sync", {})

    assert response.status_code == 409, response.get_data(as_text=True)[:300]
    assert response.get_json()["code"] == "PM_SYNC_BINDING_REQUIRED"
    assert jira_calls == []
    assert _rows_by_org() == before
    db.session.expire_all()
    assert PmSyncBinding.query.get(binding.id).to_dict() == binding_before


def test_legacy_alias_in_the_bindings_own_organization_still_pauses_a_demoted_owner(client, project, jira_calls):
    """The H-2e-2b behaviour is unchanged when the owner is active in A."""
    binding = _insert_binding(project, actor="editor", mode="push_only")
    _demote(project, "editor")
    before = _rows_by_org()

    response = _request(client, project, "editor", "POST", f"/api/v1/connectors/threads/{THREAD_ID}/jira/sync", {})

    _assert_paused_answer(response, binding.id, READ_ONLY)
    assert jira_calls == []
    assert _rows_by_org() == before


# --- Authorized syncs still work and stay in the binding's organization -------

def test_authorized_owner_switched_to_b_syncs_as_pulls_into_as_project_only(client, project, monkeypatch):
    """Still an editor in A, active in B where a same-id project exists: the
    two-way sync reads A's plan, pulls A's Jira change into A's row, and
    hands A's plan to the push. B's project is untouched."""
    binding = _insert_binding(project, actor="editor", mode="two_way")
    tasks = _link_tasks(binding, project["org"].id)
    org_b = _switch_to_b(project, "editor", "matching-project-in-b")
    b_before = _rows_by_org()[str(org_b.id)]

    calls, pushed = [], []
    provider = _PullProvider(tasks, calls)
    monkeypatch.setattr("app.pm_sync.reconciliation.get_provider", lambda _connector: provider)
    monkeypatch.setattr(
        "app.pm_sync.reconciliation.push_binding",
        lambda current, plan=None, trigger="send", **_kw: pushed.append(copy.deepcopy(plan))
        or {"success": True, "created": 0, "updated": 0, "failed": 0, "errors": []},
    )

    response = _request(client, project, "editor", "POST", f"/api/v1/pm-sync/bindings/{binding.id}/sync", {})

    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    assert any(call[0] == "provider.get_item" for call in calls)
    pulled = {call[1] for call in calls if call[0] == "provider.get_item"}
    assert pulled == {f"JPT-{index}" for index in range(1, len(tasks) + 1)}, "the sync pulled another plan's links"
    assert all(ORG_B_MARKER not in json.dumps(plan) for plan in pushed), "organization B's plan was pushed"
    a_row = _row_in(project["org"].id)
    assert a_row.scenarios_json["wbs_by_scorecard"][PLAN_KEY]["tasks"][0]["status"] == "done"
    assert a_row.last_edited_by_user_id == project["users"]["editor"].id
    assert _rows_by_org()[str(org_b.id)] == b_before, "organization B's project changed"
    db.session.expire_all()
    assert PmSyncBinding.query.get(binding.id).status == "active"


def test_authorized_owner_in_a_still_syncs(client, project, monkeypatch):
    binding = _insert_binding(project, actor="editor", mode="push_only")
    pushes = []
    monkeypatch.setattr(
        "app.pm_sync.reconciliation.push_binding",
        lambda current, trigger="send", **_kw: pushes.append(current.id) or {"success": True, "errors": []},
    )

    response = _request(client, project, "editor", "POST", f"/api/v1/pm-sync/bindings/{binding.id}/sync", {})

    assert response.status_code == 200
    assert pushes == [binding.id]


def test_legacy_alias_in_the_bindings_organization_still_sends(client, project, monkeypatch):
    binding = _insert_binding(project, actor="editor", mode="push_only")
    sent = []
    monkeypatch.setattr(
        "app.pm_sync.service.push_binding",
        lambda current, trigger="send", **_kw: sent.append((current.id, trigger)) or {"success": True},
    )

    response = _request(client, project, "editor", "POST", f"/api/v1/connectors/threads/{THREAD_ID}/jira/sync", {})

    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    assert sent == [(binding.id, "legacy_sync_alias")]


def test_binding_plan_and_commitments_follow_the_binding_organization(project):
    """Library level: active in B, the binding's plan is A's and a commitment
    write lands in A's row only."""
    from app.pm_sync.access import binding_project_row
    from app.pm_sync.service import _persist_task_commitments, get_plan

    binding = _insert_binding(project, actor="editor", mode="push_only")
    org_b = _switch_to_b(project, "editor", "matching-project-in-b")
    b_before = _rows_by_org()[str(org_b.id)]

    assert str(binding_project_row(binding).organization_id) == str(project["org"].id)
    plan, key = get_plan(binding.user_id, binding.thread_id, binding.plan_key, binding=binding)
    assert key == PLAN_KEY and MARKER in json.dumps(plan) and ORG_B_MARKER not in json.dumps(plan)

    plan["tasks"][0]["commitment"] = {"connector_id": "jira_sync", "external_ref": "JPT-1"}
    _persist_task_commitments(binding, plan)

    a_row = _row_in(project["org"].id)
    assert a_row.scenarios_json["wbs_by_scorecard"][PLAN_KEY]["tasks"][0]["commitment"] == {
        "connector_id": "jira_sync", "external_ref": "JPT-1",
    }
    assert _rows_by_org()[str(org_b.id)] == b_before


def test_binding_whose_project_is_gone_finds_no_plan_and_writes_nothing(project):
    """The binding's own project purged: no plan (so no Jira call follows),
    and a commitment write refuses rather than creating a row anywhere."""
    from app.pm_sync.service import _persist_task_commitments, get_plan

    binding = _insert_binding(project, actor="editor", mode="push_only")
    _switch_to_b(project, "editor", "matching-project-in-b")
    UserSession.query.filter_by(session_id=THREAD_ID, organization_id=str(project["org"].id)).delete()
    db.session.commit()
    before = _rows_by_org()

    with pytest.raises(LookupError):
        get_plan(binding.user_id, binding.thread_id, binding.plan_key, binding=binding)
    with pytest.raises(LookupError):
        _persist_task_commitments(binding, {"tasks": [{"id": "task-1", "commitment": {"external_ref": "JPT-1"}}]})
    assert _rows_by_org() == before


def test_personal_binding_resolves_only_its_owners_unbound_row(project):
    from app.pm_sync.access import binding_project_row

    binding = _insert_binding(project, actor="owner")
    binding.organization_id = None
    db.session.commit()
    assert binding_project_row(binding) is None, "a personal binding never resolves an organization row"
