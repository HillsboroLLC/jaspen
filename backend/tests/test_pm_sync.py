from datetime import datetime
from unittest.mock import call, patch

import pytest

from app import db as app_db
from app.models_pm_sync import PmSyncBinding, PmSyncLink
from app.pm_sync.service import _sync_phases, create_binding, preview, push_binding
from app.pm_sync.reconciliation import reconcile_binding, resolve_conflict


PLAN = {
    "scorecard_id": "score-1",
    "name": "Launch plan",
    "tasks": [
        {
            "id": "task-a", "title": "Validate requirements", "phase": "Prepare",
            "description": "Confirm the scope.", "rationale": "Reduces delivery risk.",
            "lineage": [{"label": "Condition: legal review"}], "priority": "high",
            "status": "todo", "due_date": "2026-11-01", "owner": "Alex",
            "depends_on": [], "updated_at": "2026-10-11T10:00:00",
        },
        {
            "id": "task-b", "title": "Ship pilot", "phase": "Deliver",
            "status": "todo", "depends_on": ["task-a"], "updated_at": "2026-10-11T11:00:00",
        },
    ],
}


def _binding(user):
    row = PmSyncBinding(
        user_id=user.id, thread_id="thread-1", plan_key="score-1", connector_id="jira_sync",
        external_container_id="JST", external_container_url="https://example.atlassian.net/browse/JST",
        mode="push_only", conflict_policy="manual_review", policy_set_by_user_id=user.id,
        field_policy_overrides={}, config={"task_issue_type": "Task", "group_under_epics": False,
                                           "start_date_field_id": "customfield_10015"}, user_map={},
    )
    app_db.session.add(row); app_db.session.commit()
    return row


def test_preview_is_deterministic_and_counts_dependencies():
    assert preview(PLAN, group_under_epics=True) == {
        "epics": 2, "issues": 2, "dependencies": 1, "unmapped_owners": 1,
        "tasks_without_start_date": 2,
        "structure": "Creates epic 'Prepare' with 1 task Creates epic 'Deliver' with 1 task, 1 'Blocks' link.",
    }


def test_single_generic_phase_uses_plan_title_and_reports_missing_start_dates():
    plan = {
        "name": "Denver Water Pump Station — RFP Pursuit and Submission WBS",
        "tasks": [
            {"id": "a", "title": "A", "phase": "Generated Plan", "due_date": "2026-11-10", "timeline_days": 2},
            {"id": "b", "title": "B", "phase": "Generated Plan", "due_date": "2026-11-12"},
        ],
    }
    result = preview(plan, group_under_epics=True)
    assert result["epics"] == 1
    assert result["structure"] == "Creates epic 'Denver Water Pump Station — RFP Pursuit and Submission WBS' with 2 tasks, 0 'Blocks' links."
    assert result["tasks_without_start_date"] == 1


def test_binding_requires_explicit_mode_and_conflict_policy(test_user):
    with patch("app.pm_sync.service.get_plan", return_value=(PLAN, "score-1")), patch(
        "app.pm_sync.service.jira_adapter.assert_connected", return_value={"base_url": "https://example.atlassian.net"}
    ), patch("app.pm_sync.service.jira_adapter.discover_start_date_field", return_value=None):
        with pytest.raises(ValueError, match="sync mode"):
            create_binding(test_user, {"thread_id": "thread-1", "plan_key": "score-1", "project_key": "JST", "conflict_policy": "manual_review"})
        with pytest.raises(ValueError, match="conflict policy"):
            create_binding(test_user, {"thread_id": "thread-1", "plan_key": "score-1", "project_key": "JST", "mode": "push_only"})


def test_push_is_plan_scoped_idempotent_and_preserves_lineage(test_user):
    binding = _binding(test_user)
    calls = []
    next_keys = iter(["JST-1", "JST-2"])

    def request(_config, method, path, payload=None, timeout=30):
        calls.append((method, path, payload))
        if path == "/rest/api/3/issue/bulk":
            return {"issues": [{"key": next(next_keys)}, {"key": next(next_keys)}], "errors": []}, {}
        if path == "/rest/api/3/issueLink":
            return {"id": "link-1"}, {}
        return {}, {}

    with patch("app.pm_sync.service.jira_adapter.assert_connected", return_value={"base_url": "https://example.atlassian.net"}), patch(
        "app.pm_sync.service.jira_adapter.request", side_effect=request
    ), patch("app.pm_sync.service.jira_adapter.set_identity") as identity, patch(
        "app.pm_sync.service.jira_adapter.recover_issue", return_value=None
    ):
        first = push_binding(binding, PLAN, trigger="send")
        second = push_binding(binding, PLAN, trigger="sync_now")

    assert first["created"] == 2
    assert first["dependencies"] == 1
    assert second["created"] == 0
    assert second["updated"] == 2
    assert sum(1 for method, path, _ in calls if path == "/rest/api/3/issue/bulk") == 1
    assert PmSyncLink.query.filter_by(binding_id=binding.id, entity_type="task").count() == 2
    assert PmSyncLink.query.filter_by(binding_id=binding.id, entity_type="dependency").count() == 1
    assert identity.call_count == 4  # create identity + refresh identity on idempotent updates
    create_payload = next(payload for method, path, payload in calls if path == "/rest/api/3/issue/bulk")
    adf = create_payload["issueUpdates"][0]["fields"]["description"]
    assert "Derived from" in str(adf)
    assert "Condition: legal review" in str(adf)


def test_partial_failure_keeps_successful_task_link_for_retry(test_user):
    binding = _binding(test_user)

    def request(_config, _method, path, payload=None, timeout=30):
        if path == "/rest/api/3/issue/bulk":
            return {"issues": [{"key": "JST-1"}], "errors": [{"failedElementNumber": 1, "elementErrors": {"errors": {"components": "Required Component"}}}]}, {}
        return {}, {}

    with patch("app.pm_sync.service.jira_adapter.assert_connected", return_value={"base_url": "https://example.atlassian.net"}), patch(
        "app.pm_sync.service.jira_adapter.request", side_effect=request
    ), patch("app.pm_sync.service.jira_adapter.set_identity"), patch(
        "app.pm_sync.service.jira_adapter.recover_issue", return_value=None
    ):
        result = push_binding(binding, PLAN, trigger="send")

    assert result["success"] is False
    assert result["created"] == 1
    assert result["failed"] >= 1
    assert PmSyncLink.query.filter_by(binding_id=binding.id, jaspen_id="task-a", state="active").one().external_id == "JST-1"
    assert PmSyncLink.query.filter_by(binding_id=binding.id, jaspen_id="task-b", state="failed_create").one().external_id is None


def test_missing_task_link_recovers_by_identity_without_creating_duplicate(test_user):
    binding = _binding(test_user)
    plan = {"name": "Plan", "tasks": [{
        "id": "task-a", "title": "Existing Jira task", "status": "todo", "depends_on": [],
    }]}
    calls = []

    def request(_config, method, path, payload=None, timeout=30):
        calls.append((method, path, payload))
        return {}, {}

    with patch("app.pm_sync.service.jira_adapter.assert_connected", return_value={"base_url": "https://example.atlassian.net"}), patch(
        "app.pm_sync.service.jira_adapter.request", side_effect=request
    ), patch("app.pm_sync.service.jira_adapter.recover_issue", return_value={"key": "JST-1"}), patch(
        "app.pm_sync.service.jira_adapter.set_identity"
    ):
        result = push_binding(binding, plan, trigger="sync_now")

    assert result["created"] == 0
    assert result["updated"] == 1
    assert not any(path == "/rest/api/3/issue/bulk" for _method, path, _payload in calls)
    saved = PmSyncLink.query.filter_by(binding_id=binding.id, entity_type="task", jaspen_id="task-a").one()
    assert saved.external_id == "JST-1"


def test_legacy_jira_sync_requires_exact_plan_binding(client, auth_headers):
    response = client.post("/api/v1/connectors/threads/thread-1/jira/sync", json={}, headers=auth_headers)
    assert response.status_code == 409
    assert response.get_json()["code"] == "PM_SYNC_BINDING_REQUIRED"

def test_wbs_normalization_keeps_stable_id_lineage_owner_and_versions_changes():
    from app.routes.strategy import _normalize_project_wbs

    original = {
        "name": "Plan",
        "tasks": [{
            "id": "stable-1", "title": "Do the work", "status": "todo",
            "owner": "Alex", "owner_email": "alex@example.com", "owner_user_id": "user-alex",
            "lineage": [{"type": "condition", "ref": "cond-1", "label": "Confirm demand"}],
            "updated_at": "2026-10-10T10:00:00",
        }],
    }
    unchanged = _normalize_project_wbs({"project_wbs": original}, existing=original)
    assert unchanged["tasks"][0]["id"] == "stable-1"
    assert unchanged["tasks"][0]["lineage"][0]["ref"] == "cond-1"
    assert unchanged["tasks"][0]["owner_email"] == "alex@example.com"
    assert unchanged["tasks"][0]["updated_at"] == "2026-10-10T10:00:00"

    changed_payload = {"project_wbs": {**original, "tasks": [{**original["tasks"][0], "status": "done"}]}}
    changed = _normalize_project_wbs(changed_payload, existing=original)
    assert changed["tasks"][0]["id"] == "stable-1"
    assert changed["tasks"][0]["updated_at"] != "2026-10-10T10:00:00"


def test_wbs_normalization_does_not_stamp_equivalent_empty_owner_fields():
    from app.routes.strategy import _normalize_project_wbs

    original = {"name": "Plan", "tasks": [{
        "id": "stable-1", "title": "Do the work", "status": "todo",
        "owner": "", "owner_email": None, "updated_at": "2026-10-10T10:00:00",
        "field_updated_at": {"title": "2026-10-10T10:00:00"},
    }]}
    incoming = {"project_wbs": {"name": "Plan", "tasks": [{
        "id": "stable-1", "title": "Do the work", "status": "todo",
        "owner": "   ", "owner_email": "",
    }]}}
    normalized = _normalize_project_wbs(incoming, existing=original)
    task = normalized["tasks"][0]
    assert task["updated_at"] == "2026-10-10T10:00:00"
    assert "owner" not in task["field_updated_at"]
    assert "owner_email" not in task["field_updated_at"]

def test_jira_status_uses_workflow_transition_category(test_user):
    from app.pm_sync.jira_adapter import sync_status

    binding = _binding(test_user)
    calls = []
    def request(_config, method, path, payload=None, timeout=30):
        calls.append((method, path, payload))
        if method == "GET":
            return {"transitions": [
                {"id": "11", "name": "Start", "to": {"statusCategory": {"key": "indeterminate"}}},
                {"id": "21", "name": "Finish", "to": {"statusCategory": {"key": "done"}}},
            ]}, {}
        return {}, {}

    with patch("app.pm_sync.jira_adapter.request", side_effect=request):
        assert sync_status({}, binding, "JST-1", "done") is True
    assert ("POST", "/rest/api/3/issue/JST-1/transitions", {"transition": {"id": "21"}}) in calls


def test_jira_identity_uses_remote_link_post_with_global_id_in_body(test_user):
    from app.pm_sync.jira_adapter import set_identity

    binding = _binding(test_user)
    with patch("app.pm_sync.jira_adapter.request") as request:
        set_identity({}, binding, "JST-7", "task", "task-a")
    # Searchable recovery label, entity property, then remote link.
    label_call = request.call_args_list[0]
    assert label_call.args[1:3] == ("PUT", "/rest/api/3/issue/JST-7")
    assert label_call.args[3]["update"]["labels"][0]["add"].startswith("jaspen_e_")
    remote = request.call_args_list[2]
    assert remote.args[1] == "POST"
    assert remote.args[2] == "/rest/api/3/issue/JST-7/remotelink"
    assert remote.args[3]["globalId"] == f"system=jaspen&binding={binding.id}&entity=task:task-a"
    assert "globalId=" not in remote.args[2]


def test_jira_recovery_uses_searchable_entity_label_not_unindexed_property(test_user):
    from app.pm_sync.jira_adapter import entity_label, plan_label, recover_issue

    binding = _binding(test_user)
    with patch("app.pm_sync.jira_adapter.request", return_value=({"issues": [{"key": "JST-7"}]}, {})) as request:
        result = recover_issue({}, binding, "task-a")
    assert result["key"] == "JST-7"
    payload = request.call_args.args[3]
    assert f'labels = "{plan_label(binding)}"' in payload["jql"]
    assert f'labels = "{entity_label(binding, "task-a")}"' in payload["jql"]
    assert "issue.property" not in payload["jql"]


def test_jira_parent_read_and_repair_use_issue_fields(test_user):
    from app.pm_sync.jira_adapter import get_parent, set_parent

    with patch("app.pm_sync.jira_adapter.request", return_value=({
        "fields": {"parent": {"key": "JST-9"}},
    }, {})) as request:
        assert get_parent({}, "JST-2") == "JST-9"
    request.assert_called_once_with({}, "GET", "/rest/api/3/issue/JST-2?fields=parent", timeout=20)

    with patch("app.pm_sync.jira_adapter.request") as request:
        set_parent({}, "JST-2", "JST-10")
    request.assert_called_once_with({}, "PUT", "/rest/api/3/issue/JST-2", {
        "fields": {"parent": {"key": "JST-10"}},
    })


def test_start_date_field_discovery_requires_date_schema_not_name_alone():
    from app.pm_sync.jira_adapter import discover_start_date_field

    fields = [
        {"id": "customfield_wrong", "name": "Start date", "schema": {"type": "string"}},
        {"id": "customfield_10015", "name": "Start date", "schema": {
            "type": "date", "custom": "com.atlassian.jira.plugin.system.customfieldtypes:datepicker",
        }},
    ]
    with patch("app.pm_sync.jira_adapter.request", return_value=(fields, {})) as request:
        assert discover_start_date_field({}) == "customfield_10015"
    request.assert_called_once_with({}, "GET", "/rest/api/3/field", timeout=20)


def test_task_and_epic_dates_use_discovered_start_field(test_user):
    from app.pm_sync.jira_adapter import phase_fields, task_fields

    binding = _binding(test_user)
    task = {"title": "Prepare bid", "due_date": "2026-11-20", "timeline_days": 5}
    assert task_fields(task, binding)["customfield_10015"] == "2026-11-15"
    fields = phase_fields("Bid submission", binding, [
        task,
        {"title": "Submit", "start_date": "2026-11-18", "due_date": "2026-11-25"},
    ])
    assert fields["customfield_10015"] == "2026-11-15"
    assert fields["duedate"] == "2026-11-25"


class _Provider:
    def __init__(self, remote):
        self.remote = remote
        self.updates = []
        self.recovery_identities = []
        self.get_calls = []

    def assert_connected(self, _user_id, _container_id):
        return {"base_url": "https://example.atlassian.net"}

    def get_item(self, _config, _binding, _external_id):
        self.get_calls.append(_external_id)
        return self.remote

    def update_item(self, _config, _binding, external_id, changes, _task=None):
        self.updates.append((external_id, changes))
        return {"status_mapped": True}

    def set_identity(self, _config, _binding, external_id, entity_type, jaspen_id):
        self.identity = (external_id, entity_type, jaspen_id)

    def ensure_recovery_identity(self, _config, _binding, external_id, jaspen_id):
        self.recovery_identities.append((external_id, jaspen_id))


def _linked_binding(test_user, base, mode="two_way", policy="latest_wins"):
    binding = _binding(test_user)
    binding.mode = mode
    binding.conflict_policy = policy
    link = PmSyncLink(binding_id=binding.id, entity_type="task", jaspen_id="task-a",
                      external_id="JST-1", base_snapshot=base, state="active")
    app_db.session.add(link); app_db.session.commit()
    return binding, link


def test_three_way_pull_and_push_are_field_scoped(test_user):
    base = {"title": "Old", "description": "Base", "owner": "Alex", "owner_email": None,
            "status": "todo", "start_date": None, "due_date": "2026-11-01"}
    binding, link = _linked_binding(test_user, base)
    plan = {"tasks": [{**base, "id": "task-a", "title": "Local title",
        "field_updated_at": {"title": "2026-10-11T12:00:00"}, "updated_at": "2026-10-11T12:00:00"}]}
    provider = _Provider({"deleted": False, "values": {**base, "status": "done"},
        "changed_at": {"status": "2026-10-11T13:00:00"}, "version": "2026-10-11T13:00:00"})
    with patch("app.pm_sync.reconciliation.get_plan", return_value=(plan, "score-1")), patch(
        "app.pm_sync.reconciliation.get_provider", return_value=provider), patch(
        "app.pm_sync.reconciliation._save_plan") as save:
        result = reconcile_binding(binding)
    assert result["pulled"] == 1
    assert result["pushed"] == 1
    assert plan["tasks"][0]["status"] == "done"
    assert provider.updates == [("JST-1", {"title": "Local title"})]
    assert save.called
    assert link.base_snapshot["title"] == "Local title"
    assert link.base_snapshot["status"] == "done"


def test_empty_values_do_not_create_false_changes_and_one_edit_pushes_one_task(test_user):
    base = {"title": "Task", "description": None, "owner": None, "owner_email": "",
            "status": "todo", "start_date": None, "due_date": None}
    binding, _ = _linked_binding(test_user, base)
    plan = {"tasks": [{"id": "task-a", "title": "Task", "description": " ", "owner": "",
                       "owner_email": None, "status": "todo", "start_date": "", "due_date": None}]}
    provider = _Provider({"deleted": False, "values": {**base, "owner": " ", "owner_email": None},
                          "changed_at": {}, "version": "2026-10-12T10:00:00"})
    with patch("app.pm_sync.reconciliation.get_plan", return_value=(plan, "score-1")), patch(
        "app.pm_sync.reconciliation.get_provider", return_value=provider):
        first = reconcile_binding(binding)
        assert first["pulled"] == 0
        assert first["pushed"] == 0
        plan["tasks"][0]["status"] = "done"
        plan["tasks"][0]["field_updated_at"] = {"status": "2026-10-12T11:00:00"}
        second = reconcile_binding(binding)
    assert second["pulled"] == 0
    assert second["pushed"] == 1
    assert provider.updates == [("JST-1", {"status": "done"})]


def test_newly_supported_start_date_pushes_without_erasing_jaspen(test_user):
    base = {"title": "Task", "description": None, "owner": None, "owner_email": None,
            "status": "todo", "start_date": "2026-10-10", "due_date": "2026-10-20"}
    binding, link = _linked_binding(test_user, base)
    link.last_synced_at = datetime(2026, 10, 12, 10, 0, 0)
    app_db.session.commit()
    plan = {"tasks": [{**base, "id": "task-a"}]}
    provider = _Provider({
        "deleted": False,
        "values": {**base, "start_date": None},
        "changed_at": {},
        "version": "2026-10-12T11:00:00",
        "supported_fields": ["title", "description", "owner", "owner_email", "status", "start_date", "due_date"],
    })
    with patch("app.pm_sync.reconciliation.get_plan", return_value=(plan, "score-1")), patch(
        "app.pm_sync.reconciliation.get_provider", return_value=provider):
        result = reconcile_binding(binding)
    assert result["pulled"] == 0
    assert result["pushed"] == 1
    assert plan["tasks"][0]["start_date"] == "2026-10-10"
    assert provider.updates == [("JST-1", {"start_date": "2026-10-10"})]
    assert "start_date" in link.base_snapshot["_synced_fields"]


def test_unverified_remote_empty_cannot_erase_nonempty_jaspen_value(test_user):
    base = {"title": "Task", "description": None, "owner": None, "owner_email": None,
            "status": "todo", "start_date": "2026-10-10", "due_date": None,
            "_synced_fields": ["title", "description", "owner", "owner_email", "status", "start_date", "due_date"]}
    binding, _ = _linked_binding(test_user, base)
    plan = {"tasks": [{**base, "id": "task-a"}]}
    provider = _Provider({"deleted": False, "values": {**base, "start_date": None},
                          "changed_at": {}, "version": "2026-10-12T11:00:00"})
    with patch("app.pm_sync.reconciliation.get_plan", return_value=(plan, "score-1")), patch(
        "app.pm_sync.reconciliation.get_provider", return_value=provider):
        result = reconcile_binding(binding)
    assert result["pulled"] == 0
    assert plan["tasks"][0]["start_date"] == "2026-10-10"
    assert result["conflicts"][0]["field"] == "start_date"
    assert "verified post-sync clear" in result["conflicts"][0]["reason"]


def test_jira_create_keeps_unowned_task_unassigned_and_absorbs_remote_default(test_user):
    binding = _binding(test_user)
    binding.mode = "two_way"
    app_db.session.commit()
    plan = {"name": "Plan", "tasks": [{
        "id": "task-a", "title": "Unowned task", "status": "todo",
        "owner": None, "owner_email": "", "depends_on": [],
    }]}
    calls = []

    def request(_config, method, path, payload=None, timeout=30):
        calls.append((method, path, payload))
        if path == "/rest/api/3/search/jql":
            return {"issues": []}, {}
        if path == "/rest/api/3/issue/bulk":
            return {"issues": [{"key": "JST-1"}], "errors": []}, {}
        if path.startswith("/rest/api/3/issue/JST-1?"):
            return {
                "fields": {
                    "summary": "Unowned task", "description": None,
                    "assignee": {"displayName": "Project Lead", "emailAddress": "lead@example.com"},
                    "status": {"name": "To Do", "statusCategory": {"key": "new"}},
                    "duedate": None, "updated": "2026-10-12T12:00:00Z",
                    "customfield_10015": None,
                },
                "changelog": {"histories": []},
            }, {}
        if "/transitions" in path and method == "GET":
            return {"transitions": []}, {}
        return {}, {}

    with patch("app.pm_sync.jira_adapter.assert_connected", return_value={"base_url": "https://example.atlassian.net"}), patch(
        "app.pm_sync.jira_adapter.request", side_effect=request
    ), patch("app.pm_sync.service.jira_adapter.recover_issue", return_value=None):
        pushed = push_binding(binding, plan, trigger="send")
        with patch("app.pm_sync.reconciliation.get_plan", return_value=(plan, "score-1")):
            synced = reconcile_binding(binding)

    create_payload = next(payload for method, path, payload in calls if path == "/rest/api/3/issue/bulk")
    assert create_payload["issueUpdates"][0]["fields"]["assignee"] is None
    link = PmSyncLink.query.filter_by(binding_id=binding.id, entity_type="task", jaspen_id="task-a").one()
    assert link.base_snapshot["owner"] == "Project Lead"
    assert set(link.base_snapshot["_preserve_local_empty_fields"]) == {"owner", "owner_email"}
    assert pushed["created"] == 1
    assert synced["pulled"] == 0
    assert synced["pushed"] == 0
    assert plan["tasks"][0]["owner"] is None
    assert plan["tasks"][0]["owner_email"] == ""


def test_sync_retries_identity_for_existing_link_with_prior_remote_link_failure(test_user):
    base = {"title": "Task", "description": None, "owner": None, "owner_email": None,
            "status": "todo", "start_date": None, "due_date": None}
    binding, link = _linked_binding(test_user, base)
    link.last_error = "405 Method Not Allowed"; app_db.session.commit()
    plan = {"tasks": [{**base, "id": "task-a"}]}
    provider = _Provider({"deleted": False, "values": base, "changed_at": {}, "version": None})
    with patch("app.pm_sync.reconciliation.get_plan", return_value=(plan, "score-1")), patch(
        "app.pm_sync.reconciliation.get_provider", return_value=provider):
        result = reconcile_binding(binding)
    assert result["success"] is True
    assert provider.identity == ("JST-1", "task", "task-a")
    assert provider.recovery_identities == [("JST-1", "task-a")]
    assert link.last_error is None


def test_existing_epic_is_updated_in_place_with_plan_title_and_dates(test_user):
    binding = _binding(test_user)
    binding.config = {**binding.config, "group_under_epics": True}
    link = PmSyncLink(binding_id=binding.id, entity_type="phase", jaspen_id="Generated Plan",
                      external_id="JST-9", base_snapshot={"title": "Generated Plan"}, state="active")
    app_db.session.add(link); app_db.session.commit()
    plan = {"name": "Denver Water Pump Station — RFP Pursuit and Submission WBS", "tasks": [
        {"id": "a", "title": "A", "phase": "Generated Plan", "start_date": "2026-11-10", "due_date": "2026-11-20"},
        {"id": "b", "title": "B", "phase": "Generated Plan", "start_date": "2026-11-12", "due_date": "2026-11-25"},
    ]}
    result = {"created": 0, "updated": 0, "failed": 0, "errors": []}
    with patch("app.pm_sync.service.jira_adapter.request", return_value=({}, {})) as request, patch(
        "app.pm_sync.service.jira_adapter.set_identity") as identity, patch(
        "app.pm_sync.service.jira_adapter.ensure_recovery_identity"):
        parents = _sync_phases(binding, plan, {}, {("phase", "Generated Plan"): link}, result)
    assert result == {"created": 0, "updated": 1, "failed": 0, "errors": []}
    assert parents == {"a": "JST-9", "b": "JST-9"}
    identity.assert_not_called()
    update = request.call_args.args
    assert update[1:3] == ("PUT", "/rest/api/3/issue/JST-9")
    assert update[3]["fields"]["summary"] == plan["name"]
    assert update[3]["fields"]["customfield_10015"] == "2026-11-10"
    assert update[3]["fields"]["duedate"] == "2026-11-25"
    assert PmSyncLink.query.filter_by(binding_id=binding.id, entity_type="phase").count() == 1


def test_failed_epic_identity_is_saved_and_retried_without_duplicate(test_user):
    binding = _binding(test_user)
    binding.config = {**binding.config, "group_under_epics": True}
    app_db.session.commit()
    plan = {"name": "Launch plan", "tasks": [
        {"id": "a", "title": "A", "phase": "Generated Plan", "due_date": "2026-11-20"},
    ]}
    first_result = {"created": 0, "updated": 0, "failed": 0, "errors": []}
    with patch("app.pm_sync.service.jira_adapter.request", return_value=({"key": "JST-9"}, {})) as request, patch(
        "app.pm_sync.service.jira_adapter.set_identity", side_effect=ValueError("405 Method Not Allowed")
    ):
        parents = _sync_phases(binding, plan, {}, {}, first_result)

    assert parents == {"a": "JST-9"}
    assert first_result["created"] == 1
    assert first_result["failed"] == 1
    assert sum(1 for call in request.call_args_list if call.args[1:3] == ("POST", "/rest/api/3/issue")) == 1
    saved = PmSyncLink.query.filter_by(binding_id=binding.id, entity_type="phase", jaspen_id="Generated Plan").one()
    assert saved.external_id == "JST-9"
    assert saved.last_error == "405 Method Not Allowed"

    retry_result = {"created": 0, "updated": 0, "failed": 0, "errors": []}
    with patch("app.pm_sync.service.jira_adapter.request") as request, patch(
        "app.pm_sync.service.jira_adapter.set_identity"
    ) as identity, patch("app.pm_sync.service.jira_adapter.ensure_recovery_identity"):
        parents = _sync_phases(binding, plan, {}, {("phase", "Generated Plan"): saved}, retry_result)

    assert parents == {"a": "JST-9"}
    assert retry_result == {"created": 0, "updated": 0, "failed": 0, "errors": []}
    request.assert_not_called()
    identity.assert_called_once_with({}, binding, "JST-9", "phase", "phase:Generated Plan")
    assert saved.last_error is None
    assert PmSyncLink.query.filter_by(binding_id=binding.id, entity_type="phase").count() == 1


def test_created_task_link_survives_identity_failure_and_retry_does_not_duplicate(test_user):
    binding = _binding(test_user)
    plan = {"name": "Plan", "tasks": [{
        "id": "task-a", "title": "Task", "status": "todo", "depends_on": [],
    }]}

    def first_request(_config, _method, path, payload=None, timeout=30):
        if path == "/rest/api/3/issue/bulk":
            return {"issues": [{"key": "JST-1"}], "errors": []}, {}
        return {}, {}

    with patch("app.pm_sync.service.jira_adapter.assert_connected", return_value={"base_url": "https://example.atlassian.net"}), patch(
        "app.pm_sync.service.jira_adapter.request", side_effect=first_request
    ), patch("app.pm_sync.service.jira_adapter.recover_issue", return_value=None), patch(
        "app.pm_sync.service.jira_adapter.set_identity", side_effect=ValueError("remote link failed")
    ):
        first = push_binding(binding, plan)

    saved = PmSyncLink.query.filter_by(binding_id=binding.id, entity_type="task", jaspen_id="task-a").one()
    assert saved.external_id == "JST-1"
    assert saved.last_error == "remote link failed"
    assert first["failed"] == 1

    with patch("app.pm_sync.service.jira_adapter.assert_connected", return_value={"base_url": "https://example.atlassian.net"}), patch(
        "app.pm_sync.service.jira_adapter.request", return_value=({}, {})
    ) as request, patch("app.pm_sync.service.jira_adapter.set_identity"):
        second = push_binding(binding, plan, trigger="sync_now")
    assert second["created"] == 0
    assert not any(call.args[2] == "/rest/api/3/issue/bulk" for call in request.call_args_list)
    assert PmSyncLink.query.filter_by(binding_id=binding.id, entity_type="task").count() == 1


def test_push_repairs_missing_parent_from_existing_phase_link(test_user):
    binding = _binding(test_user)
    binding.config = {**binding.config, "group_under_epics": True}
    phase = PmSyncLink(binding_id=binding.id, entity_type="phase", jaspen_id="Prepare",
                       external_id="JST-9", base_snapshot={"title": "Prepare"}, state="active")
    task_link = PmSyncLink(binding_id=binding.id, entity_type="task", jaspen_id="task-a",
                           external_id="JST-2", base_snapshot={}, state="active")
    task_link_b = PmSyncLink(binding_id=binding.id, entity_type="task", jaspen_id="task-b",
                             external_id="JST-3", base_snapshot={}, state="active")
    app_db.session.add_all([phase, task_link, task_link_b]); app_db.session.commit()
    plan = {"name": "Plan", "tasks": [{
        "id": "task-a", "title": "Task", "phase": "Prepare", "status": "todo", "depends_on": [],
    }, {
        "id": "task-b", "title": "Second task", "phase": "Prepare", "status": "todo", "depends_on": [],
    }]}
    result = {"created": 0, "updated": 0, "failed": 0, "errors": []}
    with patch("app.pm_sync.service.jira_adapter.assert_connected", return_value={"base_url": "https://example.atlassian.net"}), patch(
        "app.pm_sync.service._sync_phases", return_value={"task-a": "JST-9", "task-b": "JST-9"}
    ), patch("app.pm_sync.service.jira_adapter.get_parent", return_value=None), patch(
        "app.pm_sync.service.jira_adapter.set_parent"
    ) as set_parent, patch("app.pm_sync.service.jira_adapter.request", return_value=({}, {})), patch(
        "app.pm_sync.service.jira_adapter.set_identity"
    ), patch("app.pm_sync.service.jira_adapter.sync_status"):
        result = push_binding(binding, plan, trigger="sync_now")
    assert set_parent.call_args_list == [
        call({"base_url": "https://example.atlassian.net"}, "JST-2", "JST-9"),
        call({"base_url": "https://example.atlassian.net"}, "JST-3", "JST-9"),
    ]
    assert result["updated"] == 4  # two task updates plus two structural repairs
    assert task_link.external_parent_id == "JST-9"
    assert task_link_b.external_parent_id == "JST-9"


def test_reconcile_restores_removed_parent_and_does_not_touch_unlinked_issue(test_user):
    base = {"title": "Task", "description": None, "owner": None, "owner_email": None,
            "status": "todo", "start_date": None, "due_date": None,
            "_synced_fields": ["title", "description", "owner", "owner_email", "status", "due_date"]}
    binding, link = _linked_binding(test_user, base)
    binding.config = {**binding.config, "group_under_epics": True}
    phase = PmSyncLink(binding_id=binding.id, entity_type="phase", jaspen_id="Prepare",
                       external_id="JST-9", base_snapshot={"title": "Prepare"}, state="active")
    app_db.session.add(phase); app_db.session.commit()
    plan = {"tasks": [{**base, "id": "task-a", "phase": "Prepare"}]}
    provider = _Provider({"deleted": False, "values": base, "changed_at": {}, "version": None,
                          "parent_id": None})
    with patch("app.pm_sync.reconciliation.get_plan", return_value=(plan, "score-1")), patch(
        "app.pm_sync.reconciliation.get_provider", return_value=provider), patch(
        "app.pm_sync.reconciliation._sync_phases", return_value={"task-a": "JST-9"}
    ), patch("app.pm_sync.service.jira_adapter.set_parent") as set_parent:
        result = reconcile_binding(binding)
    set_parent.assert_called_once_with({"base_url": "https://example.atlassian.net"}, "JST-1", "JST-9")
    assert result["pushed"] == 1
    assert link.external_parent_id == "JST-9"
    assert provider.recovery_identities == [("JST-1", "task-a")]
    assert provider.get_calls == ["JST-1"]


def test_reconcile_respects_parent_moved_to_another_linked_epic(test_user):
    base = {"title": "Task", "description": None, "owner": None, "owner_email": None,
            "status": "todo", "start_date": None, "due_date": None,
            "_synced_fields": ["title", "description", "owner", "owner_email", "status", "due_date"]}
    binding, link = _linked_binding(test_user, base)
    binding.config = {**binding.config, "group_under_epics": True}
    app_db.session.add_all([
        PmSyncLink(binding_id=binding.id, entity_type="phase", jaspen_id="Prepare",
                   external_id="JST-10", base_snapshot={}, state="active"),
        PmSyncLink(binding_id=binding.id, entity_type="phase", jaspen_id="Deliver",
                   external_id="JST-11", base_snapshot={}, state="active"),
    ])
    app_db.session.commit()
    plan = {"tasks": [{**base, "id": "task-a", "phase": "Prepare"}]}
    provider = _Provider({"deleted": False, "values": base, "changed_at": {}, "version": None,
                          "parent_id": "JST-11"})
    with patch("app.pm_sync.reconciliation.get_plan", return_value=(plan, "score-1")), patch(
        "app.pm_sync.reconciliation.get_provider", return_value=provider), patch(
        "app.pm_sync.reconciliation._sync_phases", return_value={"task-a": "JST-10"}
    ), patch("app.pm_sync.service.jira_adapter.set_parent") as set_parent:
        result = reconcile_binding(binding)
    set_parent.assert_not_called()
    assert result["pushed"] == 0
    assert link.external_parent_id == "JST-11"


def test_both_changed_uses_changelog_time_and_missing_time_requires_review(test_user):
    assert resolve_conflict("latest_wins", "2026-10-11T14:00:00", "2026-10-11T13:00:00") == "local"
    assert resolve_conflict("latest_wins", "2026-10-11T12:00:00", "2026-10-11T13:00:00") == "remote"
    assert resolve_conflict("latest_wins", None, "2026-10-11T13:00:00") == "manual"
    base = {"title": "Old", "description": None, "owner": "", "owner_email": None,
            "status": "todo", "start_date": None, "due_date": None}
    binding, _ = _linked_binding(test_user, base)
    plan = {"tasks": [{**base, "id": "task-a", "title": "Local", "updated_at": None}]}
    provider = _Provider({"deleted": False, "values": {**base, "title": "Jira"}, "changed_at": {}, "version": None})
    with patch("app.pm_sync.reconciliation.get_plan", return_value=(plan, "score-1")), patch(
        "app.pm_sync.reconciliation.get_provider", return_value=provider):
        result = reconcile_binding(binding)
    assert len(result["conflicts"]) == 1
    assert result["conflicts"][0]["field"] == "title"
    assert not provider.updates


def test_push_only_never_pulls_and_deleted_remote_flags_instead_of_deleting(test_user):
    binding = _binding(test_user)
    binding.mode = "push_only"; app_db.session.commit()
    with patch("app.pm_sync.reconciliation.push_binding", return_value={"success": True}) as push:
        assert reconcile_binding(binding)["success"] is True
        push.assert_called_once()

    binding.mode = "two_way"; app_db.session.commit()
    base = {"title": "Task", "description": None, "owner": "", "owner_email": None,
            "status": "todo", "start_date": None, "due_date": None}
    link = PmSyncLink(binding_id=binding.id, entity_type="task", jaspen_id="task-a",
                      external_id="JST-1", base_snapshot=base, state="active")
    app_db.session.add(link); app_db.session.commit()
    plan = {"tasks": [{**base, "id": "task-a"}]}
    provider = _Provider({"deleted": True, "values": {}, "changed_at": {}, "version": None})
    with patch("app.pm_sync.reconciliation.get_plan", return_value=(plan, "score-1")), patch(
        "app.pm_sync.reconciliation.get_provider", return_value=provider), patch(
        "app.pm_sync.reconciliation._save_plan"):
        result = reconcile_binding(binding)
    assert result["deleted"] == 1
    assert len(plan["tasks"]) == 1
    assert plan["tasks"][0]["pm_sync_state"]["state"] == "removed_in_jira"


def test_connection_is_validated_before_save_and_secret_is_not_returned(client, auth_headers):
    payload = {"jira_base_url": "https://example.atlassian.net", "jira_email": "user@example.com", "jira_api_token": "top-secret"}
    with patch("app.routes.pm_sync.test_connection", return_value={"ok": True, "base_url": payload["jira_base_url"]}), patch(
        "app.routes.pm_sync.encrypt_token", return_value="enc::v1::ciphertext"), patch(
        "app.routes.pm_sync.update_connector_settings", return_value={"jira_api_token": "top-secret"}) as save:
        probe = client.post("/api/v1/pm-sync/jira/test-connection", json=payload, headers=auth_headers)
        assert probe.status_code == 200
        save.assert_not_called()
        connected = client.post("/api/v1/pm-sync/jira/connect", json=payload, headers=auth_headers)
        assert connected.status_code == 200
        save.assert_called_once()
        saved_user_id, connector_id, saved_fields = save.call_args.args
        assert saved_user_id
        assert connector_id == "jira_sync"
        assert saved_fields["jira_base_url"] == payload["jira_base_url"]
        assert saved_fields["jira_email"] == payload["jira_email"]
        assert saved_fields["jira_api_token"] == payload["jira_api_token"]
        assert "top-secret" not in connected.get_data(as_text=True)


def test_replaced_pm_sync_credentials_are_the_shared_jira_data_source_credentials(test_user):
    from app.jira_sync import _jira_runtime_config

    replacement = {
        "jira_base_url": "https://replacement.atlassian.net",
        "jira_email": "new@example.com",
        "jira_api_token": "new-token",
    }
    with patch("app.jira_sync.get_connector_settings", return_value=replacement) as load:
        config = _jira_runtime_config(test_user.id)

    load.assert_called_once_with(test_user.id, "jira_sync")
    assert config["base_url"] == replacement["jira_base_url"]
    assert config["email"] == replacement["jira_email"]
    assert config["api_token"] == replacement["jira_api_token"]


def test_saved_but_revoked_jira_connection_returns_reconnect_state(client, auth_headers):
    connection = {"base_url": "https://example.atlassian.net", "email": "user@example.com", "has_api_token": True}
    with patch("app.routes.pm_sync.list_projects", side_effect=RuntimeError("HTTP 401: unauthorized")), patch(
        "app.routes.pm_sync._jira_connection", return_value=connection
    ):
        response = client.get("/api/v1/pm-sync/jira/projects", headers=auth_headers)
    assert response.status_code == 401
    payload = response.get_json()
    assert payload["code"] == "JIRA_RECONNECT_REQUIRED"
    assert payload["error"] == "Your saved Jira connection no longer works. Enter a new API token to continue."
    assert payload["connection"] == connection
    assert "HTTP 401" not in response.get_data(as_text=True)


def test_valid_jira_connection_returns_projects_and_safe_account_identity(client, auth_headers):
    connection = {"base_url": "https://example.atlassian.net", "email": "user@example.com", "has_api_token": True}
    with patch("app.routes.pm_sync.list_projects", return_value=[{"key": "JST", "name": "Jaspen Test"}]), patch(
        "app.routes.pm_sync._jira_connection", return_value=connection
    ):
        response = client.get("/api/v1/pm-sync/jira/projects", headers=auth_headers)
    assert response.status_code == 200
    assert response.get_json() == {"projects": [{"key": "JST", "name": "Jaspen Test"}], "connection": connection}
    assert "api_token" not in response.get_data(as_text=True).replace("has_api_token", "")


def test_project_key_rejects_token_before_any_jira_request(test_user):
    from app.pm_sync.jira_adapter import create_project

    with patch("app.pm_sync.jira_adapter.assert_connected") as connected, patch(
        "app.pm_sync.jira_adapter.request"
    ) as request:
        with pytest.raises(ValueError, match="looks like an API token"):
            create_project(test_user.id, {"key": "ATATT-long-secret-token", "name": "Wrong field"})
    connected.assert_not_called()
    request.assert_not_called()


def test_project_key_requires_jira_key_format(test_user):
    from app.pm_sync.jira_adapter import create_project

    with pytest.raises(ValueError, match="2–10 uppercase"):
        create_project(test_user.id, {"key": "1A", "name": "Invalid"})


def test_linked_binding_auth_failure_requires_reconnect(client, auth_headers, test_user):
    binding = _binding(test_user)
    binding.mode = "two_way"
    app_db.session.commit()
    result = {"errors": [{"entity_type": "task", "jaspen_id": "task-a", "error": "HTTP 403: forbidden"}]}
    with patch("app.routes.pm_sync.reconcile_binding", return_value=result), patch(
        "app.routes.pm_sync._jira_connection", return_value={
            "base_url": "https://example.atlassian.net", "email": "user@example.com", "has_api_token": True,
        }
    ):
        response = client.post(f"/api/v1/pm-sync/bindings/{binding.id}/sync", json={}, headers=auth_headers)
    assert response.status_code == 401
    assert response.get_json()["code"] == "JIRA_RECONNECT_REQUIRED"
    app_db.session.refresh(binding)
    assert binding.status == "reconnect_required"


def test_failed_connection_never_persists_credentials(client, auth_headers):
    with patch("app.routes.pm_sync.test_connection", side_effect=ValueError("Unauthorized")), patch(
        "app.routes.pm_sync.update_connector_settings") as save:
        response = client.post("/api/v1/pm-sync/jira/connect", json={"jira_api_token": "secret"}, headers=auth_headers)
    assert response.status_code == 400
    save.assert_not_called()
    assert "secret" not in response.get_data(as_text=True)


def test_connected_jira_is_not_saved_without_credential_encryption(client, auth_headers):
    payload = {"jira_base_url": "https://example.atlassian.net", "jira_email": "user@example.com", "jira_api_token": "secret"}
    with patch("app.routes.pm_sync.test_connection", return_value={"ok": True, "base_url": payload["jira_base_url"]}), patch(
        "app.routes.pm_sync.encrypt_token", return_value="secret"), patch(
        "app.routes.pm_sync.update_connector_settings") as save:
        response = client.post("/api/v1/pm-sync/jira/connect", json=payload, headers=auth_headers)
    assert response.status_code == 400
    assert "CONNECTOR_ENCRYPTION_KEY" in response.get_data(as_text=True)
    assert "secret" not in response.get_data(as_text=True)
    save.assert_not_called()
