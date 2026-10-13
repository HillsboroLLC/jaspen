from datetime import datetime, timedelta, timezone

from app import jira_portfolio as portfolio
from app import connector_runtime
from app.decision_facts import normalize_fact_entry


NOW = datetime(2026, 10, 12, 16, 0, tzinfo=timezone.utc)


def _history(days_ago_start, days_ago_done):
    return {"histories": [
        {"created": (NOW - timedelta(days=days_ago_start)).isoformat(), "items": [{"field": "status", "toString": "In Progress", "to": "4"}]},
        {"created": (NOW - timedelta(days=days_ago_done)).isoformat(), "items": [{"field": "status", "toString": "Custom Completed", "to": "3"}]},
    ]}


def _issue(key, category, *, due=None, resolved=None, points=None, assignee=None, changelog=None, flagged=False, start=None, links=None, hierarchy_level=0):
    fields = {
        "status": {"name": f"Custom {category}", "statusCategory": {"key": category}},
        "duedate": due,
        "resolutiondate": resolved,
        "created": (NOW - timedelta(days=30)).isoformat(),
        "assignee": {"displayName": assignee} if assignee else None,
        "issuelinks": links or [],
        "issuetype": {"name": "Epic" if hierarchy_level >= 1 else "Task", "hierarchyLevel": hierarchy_level},
        "customfield_start": start,
        "customfield_flagged": ["Impediment"] if flagged else [],
        "customfield_10016": points,
    }
    return {"key": key, "fields": fields, "changelog": changelog or {"histories": []}}


def test_metric_math_uses_status_category_and_deterministic_rules():
    issues = [
        _issue("ABC-1", "new", due="2026-10-01", points=3),
        _issue("ABC-2", "indeterminate", points=5, assignee="Avery", flagged=True),
        _issue("ABC-3", "done", resolved=(NOW - timedelta(days=2)).isoformat(), points=8, changelog=_history(10, 2)),
        _issue("ABC-4", "done", resolved=(NOW - timedelta(days=9)).isoformat(), points=5, changelog=_history(20, 9)),
    ]
    result = portfolio.compute_project_metrics(
        {"key": "ABC", "name": "Alpha"}, issues,
        story_points_field="customfield_10016", flagged_field="customfield_flagged", now=NOW, workload_threshold=0,
    )

    assert result["status_counts"] == {"to_do": 1, "in_progress": 1, "done": 2}
    assert result["completion_percent"] == 50.0
    assert result["story_points"] == {
        "available": True, "field_id": "customfield_10016", "total": 21.0,
        "done": 13.0, "completion_percent": 61.9,
    }
    assert result["overdue_count"] == 1
    assert result["oldest_overdue"] == {"issue_key": "ABC-1", "due_date": "2026-10-01"}
    assert result["cycle_time"] == {"median_days": 9.5, "p85_days": 11.0, "sample_size": 2}
    assert result["blocked_count"] == 1
    assert result["overloaded_assignees"] == [{"assignee": "Avery", "in_progress": 1}]
    assert result["health"]["status"] == "at_risk"
    assert result["throughput"]["trailing_4_weekly"] == 0.5


def test_story_points_remain_unavailable_when_field_not_detected():
    result = portfolio.compute_project_metrics(
        {"key": "ABC"}, [_issue("ABC-1", "done", points=99)], now=NOW,
    )
    assert result["story_points"]["available"] is False
    assert result["story_points"]["total"] is None


def test_ai_prompt_payload_is_aggregate_only_and_respects_session_override(app, monkeypatch):
    from app.routes import ai_agent
    snapshot = {
        "fetched_at": "2026-10-12T16:00:00Z",
        "stale": False,
        "provenance": {"window_days": 90, "site": "https://secret.atlassian.net"},
        "portfolio": {
            "project_count": 1, "at_risk_projects": 1, "total": 4,
            "status_counts": {"to_do": 1, "in_progress": 1, "done": 2},
            "completion_percent": 50.0, "overdue_count": 1, "blocked_count": 1,
            "overloaded_assignee_count": 1,
            "throughput": {"trailing_4_weekly": 0.5, "trailing_12_weekly": 0.25, "trend": "up"},
            "cycle_time": {"median_days": 9.5, "sample_size": 2},
            "health": {"status": "at_risk", "overdue_share": 0.25, "blocked_share": 0.25},
        },
        "projects": [{
            "project_key": "ABC", "project_name": "Alpha", "total": 4,
            "status_counts": {"to_do": 1, "in_progress": 1, "done": 2},
            "completion_percent": 50.0, "overdue_count": 1, "blocked_count": 1,
            "overloaded_assignee_count": 1,
            "throughput": {"trailing_4_weekly": 0.5, "trailing_12_weekly": 0.25, "trend": "up"},
            "cycle_time": {"median_days": 9.5, "p85_days": 11.0, "sample_size": 2},
            "health": {"status": "at_risk", "overdue_share": 0.25, "blocked_share": 0.25},
            "oldest_overdue": {"issue_key": "SECRET-99", "due_date": "2026-10-01"},
            "overloaded_assignees": [{"assignee": "Private Person", "in_progress": 9}],
            "jira_links": {"all": "https://secret.atlassian.net/issues/SECRET-99"},
            "issue_title": "Confidential acquisition",
            "comment": "Never send this",
        }],
    }
    payload = portfolio.ai_prompt_payload(snapshot)
    serialized = portfolio.ai_prompt_text(snapshot)

    assert payload["projects"][0]["project_key"] == "ABC"
    assert payload["projects"][0]["project_name"] == "Alpha"
    assert payload["portfolio"]["overloaded_assignee_count"] == 1
    for forbidden in ("SECRET-99", "Private Person", "Confidential acquisition", "Never send this", "secret.atlassian.net"):
        assert forbidden not in serialized

    monkeypatch.setattr(ai_agent, "get_connector_settings", lambda *_: {"jira_data_enabled": True})
    monkeypatch.setattr(portfolio, "refresh_portfolio", lambda *_: snapshot)
    assert ai_agent._jira_portfolio_prompt_suffix("user-1", []) == ""
    included = ai_agent._jira_portfolio_prompt_suffix("user-1", ["jira_sync"])
    assert "Jira computed portfolio metrics" in included
    assert "SECRET-99" not in included
    with app.test_request_context():
        provider_prompt = ai_agent._build_agent_system_prompt(
            context_summary_text=None,
            intake_context=None,
            view_context=None,
            connector_context_snapshot=None,
            user_id="user-1",
            thread_id="thread-1",
            chat_history=[],
            readiness=None,
            data_context_connector_ids=["jira_sync"],
        )
    assert "Jira computed portfolio metrics" in provider_prompt
    for forbidden in ("SECRET-99", "Private Person", "Confidential acquisition", "Never send this", "secret.atlassian.net"):
        assert forbidden not in provider_prompt

    monkeypatch.setattr(ai_agent, "get_connector_settings", lambda *_: {"jira_data_enabled": False})
    assert ai_agent._jira_portfolio_prompt_suffix("user-1", ["jira_sync"]) == ""


def test_refresh_scopes_projects_paginates_caches_and_emits_provenance(monkeypatch):
    settings = {
        "jira_data_project_scope": "selected",
        "jira_data_selected_projects": ["A"],
        "jira_data_window_days": 90,
        "jira_data_workload_threshold": 8,
    }
    saved = []
    calls = []

    monkeypatch.setattr(portfolio, "get_connector_settings", lambda *_: settings)
    monkeypatch.setattr(portfolio, "update_connector_settings", lambda *args: saved.append(args[-1]))
    monkeypatch.setattr(portfolio, "_jira_runtime_config", lambda *_: {"base_url": "https://acme.atlassian.net", "email": "a@b.com", "api_token": "x"})

    def request(_config, method, path, payload=None, timeout=20):
        calls.append((method, path, payload))
        if path.startswith("/rest/api/3/project/search"):
            return ({"values": [{"key": "A", "name": "Alpha"}, {"key": "B", "name": "Beta"}, {"key": "OLD", "name": "Old", "archived": True}], "isLast": True}, {})
        if path == "/rest/api/3/field":
            return ([{"id": "customfield_10016", "name": "Points", "schema": {"custom": "com.pyxis.greenhopper.jira:jsw-story-points"}}], {})
        assert path == "/rest/api/3/search/jql"
        return ({"issues": [_issue("A-1", "done", points=3)], "nextPageToken": None}, {})

    monkeypatch.setattr(portfolio, "_jira_request", request)
    snapshot = portfolio.refresh_portfolio("user-1", force=True, now=NOW)

    assert [row["project_key"] for row in snapshot["projects"]] == ["A"]
    assert snapshot["provenance"] == {
        "source": "connector", "connector": "jira_sync", "site": "https://acme.atlassian.net",
        "projects": ["A"], "window_days": 90, "fetched_at": "2026-10-12T16:00:00Z",
    }
    assert snapshot["evidence"][0]["source"] == "connector"
    assert all(row["confidence"] == 0.85 for row in snapshot["evidence"])
    assert {row["fact_key"] for row in snapshot["evidence"]} >= {"jira_throughput_per_week", "jira_overdue_share"}
    assert len([row for row in calls if row[1] == "/rest/api/3/search/jql"]) == 1
    search_payload = next(row[2] for row in calls if row[1] == "/rest/api/3/search/jql")
    assert search_payload["expand"] == "changelog"
    assert saved[-1]["jira_portfolio_snapshot"]["portfolio"]["project_count"] == 1

    settings["jira_portfolio_snapshot"] = snapshot
    calls.clear()
    assert portfolio.refresh_portfolio("user-1", now=NOW + timedelta(hours=1)) == snapshot
    assert calls == []

    key, normalized = normalize_fact_entry(snapshot["evidence"][0]["key"], snapshot["evidence"][0])
    assert key == snapshot["evidence"][0]["fact_key"]
    assert normalized["value"] == snapshot["evidence"][0]["normalized_value"]
    assert normalized["source"] == "connector"
    assert normalized["source_id"] == "jira_sync"


def test_failed_refresh_uses_stale_cache_with_lower_confidence(monkeypatch):
    cached = {"fetched_at": "2026-10-11T00:00:00Z", "portfolio": {"project_count": 1}, "projects": [{"project_key": "ABC"}], "provenance": {"source": "connector"}}
    monkeypatch.setattr(portfolio, "get_connector_settings", lambda *_: {"jira_portfolio_snapshot": cached})
    monkeypatch.setattr(portfolio, "update_connector_settings", lambda *_: None)
    monkeypatch.setattr(portfolio, "_jira_runtime_config", lambda *_: {"base_url": "https://x", "email": "e", "api_token": "t"})
    monkeypatch.setattr(portfolio, "_list_projects", lambda *_: (_ for _ in ()).throw(RuntimeError("HTTP 429")))
    result = portfolio.refresh_portfolio("user", force=True, now=NOW)
    assert result["stale"] is True
    assert result["refresh_failed"] is True
    assert result["projects"] == [{"project_key": "ABC"}]
    assert result["refresh_error"] == {
        "category": "provider",
        "message": "Jaspen couldn't read Jira data — we've logged the details.",
        "reconnect_required": False,
    }
    assert all(row["confidence"] == 0.55 for row in result["evidence"])


def test_no_default_project_is_required(monkeypatch):
    monkeypatch.setattr(portfolio, "get_connector_settings", lambda *_: {})
    monkeypatch.setattr(portfolio, "_jira_runtime_config", lambda *_: {"base_url": "https://x", "email": "e", "api_token": "t", "project_key": ""})
    monkeypatch.setattr(portfolio, "_list_projects", lambda *_: [])
    monkeypatch.setattr(portfolio, "_discover_fields", lambda *_: {"story_points": None, "flagged": None, "sprint": None})
    monkeypatch.setattr(portfolio, "update_connector_settings", lambda *_: None)
    result = portfolio.refresh_portfolio("user", force=True, now=NOW)
    assert result["portfolio"]["project_count"] == 0


def test_last_three_closed_sprints_are_computed_from_detected_sprint_field():
    issues = []
    for index in range(4):
        issue = _issue(f"ABC-{index}", "done" if index != 1 else "indeterminate")
        issue["fields"]["customfield_10020"] = [{
            "id": index + 1, "name": f"Sprint {index + 1}", "state": "closed",
            "completeDate": (NOW - timedelta(days=index * 14)).isoformat(),
        }]
        issues.append(issue)
    result = portfolio.compute_project_metrics(
        {"key": "ABC"}, issues, sprint_field="customfield_10020", now=NOW,
    )
    assert result["sprint_health"]["available"] is True
    assert len(result["sprint_health"]["closed_sprints"]) == 3
    assert result["sprint_health"]["closed_sprints"][0]["name"] == "Sprint 1"


def test_one_no_access_project_does_not_fail_portfolio(monkeypatch):
    monkeypatch.setattr(portfolio, "get_connector_settings", lambda *_: {})
    monkeypatch.setattr(portfolio, "update_connector_settings", lambda *_: None)
    monkeypatch.setattr(portfolio, "_jira_runtime_config", lambda *_: {"base_url": "https://x", "email": "e", "api_token": "t"})
    monkeypatch.setattr(portfolio, "_list_projects", lambda *_: [{"key": "YES"}, {"key": "NO"}])
    monkeypatch.setattr(portfolio, "_discover_fields", lambda *_: {"story_points": None, "flagged": None, "sprint": None})
    def search(_config, key, _fields, _cap, window_days=90):
        if key == "NO":
            raise RuntimeError("HTTP 403")
        return [_issue("YES-1", "new")]
    monkeypatch.setattr(portfolio, "_search_project", search)
    result = portfolio.refresh_portfolio("user", force=True, now=NOW)
    assert result["portfolio"]["project_count"] == 1
    assert result["no_access_projects"] == [{"project_key": "NO", "project_name": "NO", "status": "no_access"}]


def test_all_projects_forbidden_preserves_cached_snapshot_and_names_projects(monkeypatch):
    cached = {
        "fetched_at": "2026-10-11T00:00:00Z", "projects": [{"project_key": "ABC"}],
        "portfolio": {"project_count": 1}, "provenance": {"source": "connector"},
    }
    monkeypatch.setattr(portfolio, "get_connector_settings", lambda *_: {"jira_portfolio_snapshot": cached})
    monkeypatch.setattr(portfolio, "update_connector_settings", lambda *_: None)
    monkeypatch.setattr(portfolio, "_jira_runtime_config", lambda *_: {"base_url": "https://x", "email": "e", "api_token": "t"})
    monkeypatch.setattr(portfolio, "_list_projects", lambda *_: [{"key": "SCRUM"}, {"key": "JST"}])
    monkeypatch.setattr(portfolio, "_discover_fields", lambda *_: {"story_points": None, "flagged": None, "sprint": None, "start_date": None})
    monkeypatch.setattr(portfolio, "_search_project", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("HTTP 403")))
    result = portfolio.refresh_portfolio("user", force=True, now=NOW)
    assert result["projects"] == [{"project_key": "ABC"}]
    assert result["stale"] is True
    assert result["refresh_error"]["category"] == "permission"
    assert result["refresh_error"]["projects"] == ["SCRUM", "JST"]


def _open_blocker_link(key="ABC-99"):
    return {
        "type": {"inward": "is blocked by", "outward": "blocks"},
        "inwardIssue": {"key": key, "fields": {"status": {"statusCategory": {"key": "new"}}}},
    }


def test_normal_sequencing_is_not_blocked_until_work_has_started():
    future_todo = _issue("ABC-1", "new", start="2026-10-20", links=[_open_blocker_link()])
    result = portfolio.compute_project_metrics(
        {"key": "ABC"}, [future_todo], start_date_field="customfield_start", now=NOW,
    )
    assert result["blocked_count"] == 0
    assert result["health"]["status"] == "healthy"


def test_flagged_or_active_work_with_open_blocker_is_blocked():
    issues = [
        _issue("ABC-1", "new", flagged=True),
        _issue("ABC-2", "indeterminate", links=[_open_blocker_link()]),
        _issue("ABC-3", "new", start="2026-10-01", links=[_open_blocker_link()]),
    ]
    result = portfolio.compute_project_metrics(
        {"key": "ABC"}, issues, flagged_field="customfield_flagged", start_date_field="customfield_start", now=NOW,
    )
    assert result["blocked_count"] == 3


def test_no_completed_work_has_no_cycle_time_sample():
    issue = _issue("ABC-1", "indeterminate", changelog={"histories": [
        {"created": (NOW - timedelta(days=5)).isoformat(), "items": [{"field": "status", "toString": "In Progress"}]},
    ]})
    result = portfolio.compute_project_metrics({"key": "ABC"}, [issue], now=NOW)
    assert result["cycle_time"] == {"median_days": None, "p85_days": None, "sample_size": 0}
    assert result["throughput"]["trailing_4_weekly"] == 0.0


def test_container_issue_types_are_reported_but_excluded_from_work_metrics():
    epic = _issue(
        "ABC-EPIC", "done", due="2026-10-01", resolved=(NOW - timedelta(days=1)).isoformat(),
        changelog=_history(10, 1), hierarchy_level=1,
    )
    task = _issue("ABC-1", "new")
    result = portfolio.compute_project_metrics({"key": "ABC"}, [epic, task], now=NOW)
    assert result["epic_count"] == 1
    assert result["total"] == 1
    assert result["status_counts"] == {"to_do": 1, "in_progress": 0, "done": 0}
    assert result["cycle_time"]["sample_size"] == 0
    assert result["throughput"]["trailing_4_weekly"] == 0.0


def test_http_429_honors_retry_and_recovers(monkeypatch):
    class Response:
        def __init__(self, status, body, headers=None):
            self.status_code = status
            self._body = body
            self.text = "body"
            self.headers = headers or {}
        def json(self):
            return self._body
    responses = iter([Response(429, {"error": "rate limited"}, {"Retry-After": "0"}), Response(200, {"issues": []})])
    monkeypatch.setattr(connector_runtime.requests, "request", lambda **_kwargs: next(responses))
    monkeypatch.setattr(connector_runtime.time, "sleep", lambda *_: None)
    result = connector_runtime.request_json_with_backoff("GET", "https://jira.test/search", max_attempts=2)
    assert result["attempt_count"] == 2
    assert result["data"] == {"issues": []}
