"""Read-only Jira portfolio evidence.

All arithmetic in this module is deterministic.  The returned snapshot contains
aggregates only; raw Jira issues are never passed to the language model.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from urllib.parse import quote

from app.connector_store import get_connector_settings, update_connector_settings
from app.jira_sync import _jira_request, _jira_runtime_config


RULES_VERSION = "jira-portfolio-health-v1"
CACHE_TTL_HOURS = 6
DEFAULT_WINDOW_DAYS = 90
DEFAULT_WORKLOAD_THRESHOLD = 8
MAX_ISSUES_PER_REFRESH = 1000
MAX_CHANGELOG_SAMPLES = 200

HEALTH_THRESHOLDS = {
    "at_risk_overdue_share": 0.20,
    "watch_overdue_share": 0.10,
    "at_risk_blocked_share": 0.10,
    "watch_blocked_share": 0.05,
}


def _utcnow():
    return datetime.now(timezone.utc)


def _iso(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def _dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _number(value):
    try:
        return float(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def _nearest_rank(values, percentile):
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    return ordered[max(0, math.ceil((percentile / 100.0) * len(ordered)) - 1)]


def _week_bucket(when, now):
    days = max(0, (now.date() - when.date()).days)
    return days // 7


def throughput_trend(resolved_dates, *, now=None):
    """Compare trailing four weeks with the preceding eight-week average.

    Up/down requires both a 10% relative change and 0.25 issue/week absolute
    change; otherwise the trend is flat.  This prevents tiny volumes from
    producing noisy status changes.
    """
    now = now or _utcnow()
    buckets = Counter(_week_bucket(value, now) for value in resolved_dates if value)
    recent = sum(buckets[i] for i in range(4)) / 4.0
    previous = sum(buckets[i] for i in range(4, 12)) / 8.0
    delta = recent - previous
    relative = delta / previous if previous else (1.0 if recent else 0.0)
    direction = "flat"
    if delta >= 0.25 and relative >= 0.10:
        direction = "up"
    elif delta <= -0.25 and relative <= -0.10:
        direction = "down"
    return {
        "trailing_4_weekly": round(recent, 2),
        "trailing_12_weekly": round(sum(buckets[i] for i in range(12)) / 12.0, 2),
        "comparison_prior_8_weekly": round(previous, 2),
        "trend": direction,
    }


def _cycle_days(issue):
    histories = ((issue.get("changelog") or {}).get("histories") or []) if isinstance(issue, dict) else []
    first_in_progress = None
    first_done = None
    for history in sorted(histories, key=lambda row: str(row.get("created") or "")):
        changed = _dt(history.get("created"))
        if not changed:
            continue
        for item in history.get("items") or []:
            if str(item.get("field") or "").lower() != "status":
                continue
            category = str(item.get("toString") or "").strip().lower()
            category_id = str(item.get("to") or "").strip()
            if first_in_progress is None and ("progress" in category or category_id == "4"):
                first_in_progress = changed
            if first_in_progress is not None and (category in {"done", "closed", "resolved"} or category_id == "3"):
                first_done = changed
                break
        if first_done:
            break
    if not first_in_progress or not first_done or first_done < first_in_progress:
        return None
    return (first_done - first_in_progress).total_seconds() / 86400.0


def _status_category(fields):
    category = ((fields.get("status") or {}).get("statusCategory") or {})
    key = str(category.get("key") or "").lower()
    if key in {"new", "undefined", "to-do", "todo"}:
        return "to_do"
    if key in {"indeterminate", "in-progress", "in_progress"}:
        return "in_progress"
    if key in {"done", "complete"}:
        return "done"
    return "to_do"


def _is_flagged(fields):
    for key, value in fields.items():
        if "flagged" not in str(key).lower() and "flagged" not in str((value or {}).get("name") if isinstance(value, dict) else "").lower():
            continue
        if value not in (None, "", [], False):
            return True
    return False


def _has_open_blocker(fields):
    for link in fields.get("issuelinks") or []:
        link_type = str((link.get("type") or {}).get("inward") or "").lower()
        blocker = link.get("inwardIssue")
        if "blocked by" not in link_type or not isinstance(blocker, dict):
            continue
        blocker_category = (((blocker.get("fields") or {}).get("status") or {}).get("statusCategory") or {}).get("key")
        if str(blocker_category or "").lower() != "done":
            return True
    return False


def _health(metrics):
    total = max(1, int(metrics.get("total") or 0))
    open_count = int(metrics.get("status_counts", {}).get("to_do", 0)) + int(metrics.get("status_counts", {}).get("in_progress", 0))
    overdue_share = int(metrics.get("overdue_count") or 0) / max(1, open_count)
    blocked_share = int(metrics.get("blocked_count") or 0) / total
    trend = str((metrics.get("throughput") or {}).get("trend") or "flat")
    overloaded = int(metrics.get("overloaded_assignee_count") or 0)
    if overdue_share > HEALTH_THRESHOLDS["at_risk_overdue_share"] or blocked_share > HEALTH_THRESHOLDS["at_risk_blocked_share"]:
        status = "at_risk"
    elif overdue_share > HEALTH_THRESHOLDS["watch_overdue_share"] or blocked_share > HEALTH_THRESHOLDS["watch_blocked_share"] or trend == "down" or overloaded:
        status = "watch"
    else:
        status = "healthy"
    return {"status": status, "overdue_share": round(overdue_share, 4), "blocked_share": round(blocked_share, 4)}


def compute_project_metrics(project, issues, *, story_points_field=None, flagged_field=None, sprint_field=None, now=None, window_days=DEFAULT_WINDOW_DAYS, workload_threshold=DEFAULT_WORKLOAD_THRESHOLD):
    now = now or _utcnow()
    status_counts = Counter()
    story_points = Counter()
    overdue = []
    resolved_dates = []
    cycle_values = []
    workload = Counter()
    blocked = []
    closed_sprints = {}

    for issue in issues:
        fields = issue.get("fields") or {}
        category = _status_category(fields)
        status_counts[category] += 1
        points = _number(fields.get(story_points_field)) if story_points_field else None
        if points is not None:
            story_points[category] += points
        due = _dt(fields.get("duedate"))
        if due and category != "done" and due.date() < now.date():
            overdue.append((issue.get("key"), due))
        resolved = _dt(fields.get("resolutiondate"))
        if resolved and (now - resolved).days <= max(90, window_days):
            resolved_dates.append(resolved)
        if len(cycle_values) < MAX_CHANGELOG_SAMPLES:
            cycle = _cycle_days(issue)
            if cycle is not None:
                cycle_values.append(cycle)
        if category == "in_progress":
            assignee = fields.get("assignee") or {}
            name = str(assignee.get("displayName") or assignee.get("accountId") or "Unassigned")
            workload[name] += 1
        explicitly_flagged = bool(flagged_field and fields.get(flagged_field) not in (None, "", [], False))
        if explicitly_flagged or _is_flagged(fields) or _has_open_blocker(fields):
            created = _dt(fields.get("created")) or now
            blocked.append((issue.get("key"), max(0, (now - created).days)))
        if sprint_field:
            for sprint in fields.get(sprint_field) or []:
                if not isinstance(sprint, dict) or str(sprint.get("state") or "").lower() != "closed":
                    continue
                sprint_id = str(sprint.get("id") or sprint.get("name") or "")
                entry = closed_sprints.setdefault(sprint_id, {
                    "id": sprint.get("id"), "name": sprint.get("name") or sprint_id,
                    "completed_at": sprint.get("completeDate") or sprint.get("endDate"),
                    "committed": 0, "completed": 0,
                })
                entry["committed"] += 1
                if category == "done":
                    entry["completed"] += 1

    total = sum(status_counts.values())
    done = status_counts["done"]
    point_total = sum(story_points.values())
    oldest = min(overdue, key=lambda row: row[1]) if overdue else None
    overloaded = [{"assignee": name, "in_progress": count} for name, count in sorted(workload.items()) if count > workload_threshold]
    result = {
        "project_key": project.get("key"),
        "project_name": project.get("name") or project.get("key"),
        "total": total,
        "status_counts": {key: int(status_counts[key]) for key in ("to_do", "in_progress", "done")},
        "completion_percent": round((done / total) * 100, 1) if total else None,
        "story_points": {
            "available": bool(story_points_field),
            "field_id": story_points_field,
            "total": round(point_total, 2) if story_points_field else None,
            "done": round(story_points["done"], 2) if story_points_field else None,
            "completion_percent": round((story_points["done"] / point_total) * 100, 1) if story_points_field and point_total else None,
        },
        "overdue_count": len(overdue),
        "oldest_overdue": {"issue_key": oldest[0], "due_date": oldest[1].date().isoformat()} if oldest else None,
        "throughput": throughput_trend(resolved_dates, now=now),
        "cycle_time": {
            "median_days": round(median(cycle_values), 2) if cycle_values else None,
            "p85_days": round(_nearest_rank(cycle_values, 85), 2) if cycle_values else None,
            "sample_size": len(cycle_values),
        },
        "blocked_count": len(blocked),
        "oldest_blocked_days": max((age for _, age in blocked), default=None),
        "workload": dict(sorted(workload.items())),
        "workload_threshold": workload_threshold,
        "overloaded_assignees": overloaded,
        "overloaded_assignee_count": len(overloaded),
        "sprint_health": {
            "available": bool(sprint_field and closed_sprints),
            "closed_sprints": sorted(closed_sprints.values(), key=lambda row: str(row.get("completed_at") or ""), reverse=True)[:3],
        },
    }
    result["health"] = _health(result)
    return result


def rollup_metrics(project_metrics):
    counts = Counter()
    total = overdue = blocked = 0
    overloaded_names = set()
    cycle_weighted = []
    throughput_4 = throughput_12 = 0.0
    for metrics in project_metrics:
        total += int(metrics.get("total") or 0)
        overdue += int(metrics.get("overdue_count") or 0)
        blocked += int(metrics.get("blocked_count") or 0)
        counts.update(metrics.get("status_counts") or {})
        overloaded_names.update(row.get("assignee") for row in metrics.get("overloaded_assignees") or [] if row.get("assignee"))
        cycle = metrics.get("cycle_time") or {}
        throughput = metrics.get("throughput") or {}
        throughput_4 += float(throughput.get("trailing_4_weekly") or 0)
        throughput_12 += float(throughput.get("trailing_12_weekly") or 0)
        if cycle.get("median_days") is not None:
            cycle_weighted.extend([float(cycle["median_days"])] * max(1, int(cycle.get("sample_size") or 1)))
    result = {
        "project_count": len(project_metrics),
        "at_risk_projects": sum(1 for row in project_metrics if (row.get("health") or {}).get("status") == "at_risk"),
        "total": total,
        "status_counts": {key: int(counts[key]) for key in ("to_do", "in_progress", "done")},
        "completion_percent": round((counts["done"] / total) * 100, 1) if total else None,
        "overdue_count": overdue,
        "blocked_count": blocked,
        "overloaded_assignee_count": len(overloaded_names),
        "cycle_time": {"median_days": round(median(cycle_weighted), 2) if cycle_weighted else None, "sample_size": len(cycle_weighted)},
        "throughput": {
            "trailing_4_weekly": round(throughput_4, 2),
            "trailing_12_weekly": round(throughput_12, 2),
            "trend": "down" if any((row.get("throughput") or {}).get("trend") == "down" for row in project_metrics) else ("up" if project_metrics and all((row.get("throughput") or {}).get("trend") == "up" for row in project_metrics) else "flat"),
        },
    }
    result["health"] = _health(result)
    return result


def canonical_evidence(snapshot):
    portfolio = snapshot.get("portfolio") or {}
    provenance = snapshot.get("provenance") or {}
    stale = bool(snapshot.get("stale"))
    values = {
        "jira_active_project_count": portfolio.get("project_count"),
        "jira_completion_percent": portfolio.get("completion_percent"),
        "jira_throughput_per_week": (portfolio.get("throughput") or {}).get("trailing_4_weekly"),
        "jira_overdue_share": (portfolio.get("health") or {}).get("overdue_share"),
        "jira_overdue_count": portfolio.get("overdue_count"),
        "jira_at_risk_project_count": portfolio.get("at_risk_projects"),
        "jira_blocked_count": portfolio.get("blocked_count"),
        "jira_overloaded_assignee_count": portfolio.get("overloaded_assignee_count"),
    }
    return [
        {
            "key": key,
            "fact_key": key,
            "value": value,
            "normalized_value": value,
            "source": "connector",
            "source_classification": "computed_connector_evidence",
            "evidence": f"Jira computed {key} = {value} as of {snapshot.get('fetched_at')}",
            "source_id": "jira_sync",
            "locator": f"{provenance.get('site', '')} | projects={','.join(provenance.get('projects') or [])} | window={provenance.get('window_days')}d",
            "provenance": provenance,
            "fetched_at": snapshot.get("fetched_at"),
            "stale": stale,
            "confidence": 0.55 if stale else 0.85,
        }
        for key, value in values.items() if value is not None
    ]


def _fresh(snapshot, *, now=None):
    now = now or _utcnow()
    fetched = _dt((snapshot or {}).get("fetched_at"))
    return bool(fetched and now - fetched <= timedelta(hours=CACHE_TTL_HOURS))


def _list_projects(config):
    projects, start = [], 0
    while True:
        data, _ = _jira_request(config, "GET", f"/rest/api/3/project/search?startAt={start}&maxResults=50&orderBy=name", timeout=30)
        rows = data.get("values") or []
        projects.extend(row for row in rows if not row.get("archived"))
        if data.get("isLast", start + len(rows) >= int(data.get("total") or 0)) or not rows:
            break
        start += len(rows)
    return projects


def _discover_fields(config):
    data, _ = _jira_request(config, "GET", "/rest/api/3/field", timeout=30)
    discovered = {"story_points": None, "flagged": None, "sprint": None}
    for field in data if isinstance(data, list) else []:
        custom = str((field.get("schema") or {}).get("custom") or "").lower()
        name = str(field.get("name") or "").lower()
        if not discovered["story_points"] and ("story-points" in custom or "story point" in name):
            discovered["story_points"] = field.get("id")
        if not discovered["flagged"] and ("flagged" in custom or name == "flagged"):
            discovered["flagged"] = field.get("id")
        if not discovered["sprint"] and ("gh-sprint" in custom or name == "sprint"):
            discovered["sprint"] = field.get("id")
    return discovered


def _search_project(config, project_key, fields, cap, window_days=DEFAULT_WINDOW_DAYS):
    rows, token = [], None
    while len(rows) < cap:
        payload = {
            "jql": f'project = "{project_key}" AND (resolution is EMPTY OR resolved >= -{int(window_days)}d) ORDER BY updated DESC',
            "maxResults": min(100, cap - len(rows)), "fields": fields, "expand": ["changelog"],
        }
        if token:
            payload["nextPageToken"] = token
        data, _ = _jira_request(config, "POST", "/rest/api/3/search/jql", payload=payload, timeout=45)
        batch = data.get("issues") or []
        rows.extend(batch)
        token = data.get("nextPageToken")
        if not token or not batch:
            break
    return rows


def refresh_portfolio(user_id, *, force=False, now=None):
    now = now or _utcnow()
    settings = get_connector_settings(user_id, "jira_sync")
    cached = settings.get("jira_portfolio_snapshot") if isinstance(settings.get("jira_portfolio_snapshot"), dict) else None
    if cached and not force and _fresh(cached, now=now):
        return cached
    config = _jira_runtime_config(user_id)
    missing = [key for key in ("base_url", "email", "api_token") if not config.get(key)]
    if missing:
        raise ValueError("Connect Jira with a site, email, and API token to load portfolio evidence.")
    try:
        projects = _list_projects(config)
        scope = str(settings.get("jira_data_project_scope") or "all")
        selected = {str(key) for key in settings.get("jira_data_selected_projects") or []}
        included = [row for row in projects if scope != "selected" or str(row.get("key")) in selected]
        window_days = max(14, min(365, int(settings.get("jira_data_window_days") or DEFAULT_WINDOW_DAYS)))
        threshold = max(1, min(100, int(settings.get("jira_data_workload_threshold") or DEFAULT_WORKLOAD_THRESHOLD)))
        discovered_fields = _discover_fields(config)
        story_field = discovered_fields.get("story_points")
        flagged_field = discovered_fields.get("flagged")
        sprint_field = discovered_fields.get("sprint")
        fields = ["summary", "status", "assignee", "duedate", "resolutiondate", "created", "issuelinks"]
        fields.extend(value for value in discovered_fields.values() if value)
        remaining = MAX_ISSUES_PER_REFRESH
        metrics, no_access = [], []
        for project in included:
            if remaining <= 0:
                break
            key = str(project.get("key") or "")
            try:
                issues = _search_project(config, key, fields, remaining, window_days=window_days)
            except Exception as exc:
                if "HTTP 401" in str(exc) or "HTTP 403" in str(exc):
                    no_access.append({"project_key": key, "project_name": project.get("name") or key, "status": "no_access"})
                    continue
                raise
            remaining -= len(issues)
            row = compute_project_metrics(project, issues, story_points_field=story_field, flagged_field=flagged_field, sprint_field=sprint_field, now=now, window_days=window_days, workload_threshold=threshold)
            row["jira_url"] = f"{config['base_url']}/issues/?jql={quote('project = ' + key)}"
            row["jira_links"] = {
                "all": row["jira_url"],
                "open": f"{config['base_url']}/issues/?jql={quote('project = ' + key + ' AND statusCategory != Done')}",
                "overdue": f"{config['base_url']}/issues/?jql={quote('project = ' + key + ' AND statusCategory != Done AND due < now()')}",
                "done": f"{config['base_url']}/issues/?jql={quote('project = ' + key + ' AND statusCategory = Done')}",
            }
            metrics.append(row)
        snapshot = {
            "rules_version": RULES_VERSION,
            "fetched_at": _iso(now),
            "stale": False,
            "refresh_failed": False,
            "projects": metrics,
            "no_access_projects": no_access,
            "portfolio": rollup_metrics(metrics),
            "provenance": {"source": "connector", "connector": "jira_sync", "site": config["base_url"], "projects": [row.get("project_key") for row in metrics], "window_days": window_days, "fetched_at": _iso(now)},
        }
        snapshot["evidence"] = canonical_evidence(snapshot)
        update_connector_settings(user_id, "jira_sync", {"jira_portfolio_snapshot": snapshot, "jira_data_last_refresh_failed": False})
        return snapshot
    except Exception:
        if cached:
            stale = dict(cached)
            stale["stale"] = True
            stale["refresh_failed"] = True
            stale["evidence"] = canonical_evidence(stale)
            update_connector_settings(user_id, "jira_sync", {"jira_portfolio_snapshot": stale, "jira_data_last_refresh_failed": True})
            return stale
        raise


def portfolio_context_text(snapshot):
    portfolio = snapshot.get("portfolio") or {}
    fetched_at = snapshot.get("fetched_at") or "unknown"
    stale = " STALE—refresh failed; lower confidence." if snapshot.get("stale") else ""
    return (
        f"Jira delivery capacity evidence as of {fetched_at}.{stale}\n"
        f"Projects: {portfolio.get('project_count', 0)}; at risk: {portfolio.get('at_risk_projects', 0)}; "
        f"complete: {portfolio.get('completion_percent')}%; overdue: {portfolio.get('overdue_count', 0)}; "
        f"blocked/flagged: {portfolio.get('blocked_count', 0)}; overloaded assignees: {portfolio.get('overloaded_assignee_count', 0)}; "
        f"throughput: {(portfolio.get('throughput') or {}).get('trailing_4_weekly', 0)} issues/week.\n"
        "These are deterministic computed connector facts. Cite them; do not recalculate or alter them."
    )


def list_accessible_projects(user_id):
    config = _jira_runtime_config(user_id)
    missing = [key for key in ("base_url", "email", "api_token") if not config.get(key)]
    if missing:
        raise ValueError("Connect Jira before choosing projects.")
    return [{"key": row.get("key"), "name": row.get("name"), "archived": bool(row.get("archived"))} for row in _list_projects(config)]
