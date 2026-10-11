from unittest.mock import patch

import pytest

from app import db as app_db
from app.models_pm_sync import PmSyncBinding, PmSyncLink
from app.pm_sync.service import create_binding, preview, push_binding


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
        field_policy_overrides={}, config={"task_issue_type": "Task", "group_under_epics": False}, user_map={},
    )
    app_db.session.add(row); app_db.session.commit()
    return row


def test_preview_is_deterministic_and_counts_dependencies():
    assert preview(PLAN, group_under_epics=True) == {
        "epics": 2, "issues": 2, "dependencies": 1, "unmapped_owners": 1,
    }


def test_binding_requires_explicit_mode_and_conflict_policy(test_user):
    with patch("app.pm_sync.service.get_plan", return_value=(PLAN, "score-1")), patch(
        "app.pm_sync.service.jira_adapter.assert_connected", return_value={"base_url": "https://example.atlassian.net"}
    ):
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
