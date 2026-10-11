import os
from urllib.parse import quote

from app.connector_store import get_connector_settings
from app.jira_sync import _jira_request, _jira_runtime_config, _normalize_jira_base_url


def runtime_config(user_id, project_key=None):
    config = _jira_runtime_config(user_id)
    if project_key:
        config["project_key"] = str(project_key).strip()
    return config


def assert_connected(user_id, project_key=None):
    settings = get_connector_settings(user_id, "jira_sync")
    if str(settings.get("connection_status") or "").lower() != "connected":
        raise ValueError("Jira is not connected for this account.")
    config = runtime_config(user_id, project_key)
    missing = [key for key in ("base_url", "email", "api_token") if not config.get(key)]
    if project_key is not None and not config.get("project_key"):
        missing.append("project_key")
    if missing:
        raise ValueError("Jira configuration is missing: " + ", ".join(missing))
    return config


def list_projects(user_id):
    config = assert_connected(user_id)
    data, _ = _jira_request(config, "GET", "/rest/api/3/project/search?maxResults=100", timeout=20)
    values = data.get("values") if isinstance(data, dict) else []
    return [
        {
            "id": str(item.get("id") or ""),
            "key": str(item.get("key") or ""),
            "name": str(item.get("name") or ""),
            "url": f"{config['base_url']}/browse/{item.get('key')}",
        }
        for item in (values or []) if item.get("key")
    ]


def request(config, method, path, payload=None, timeout=30):
    return _jira_request(config, method, path, payload=payload, timeout=timeout)


def adf_document(task, jaspen_url):
    description = str(task.get("description") or "").strip()
    rationale = str(task.get("rationale") or "").strip()
    lineage = task.get("lineage") if isinstance(task.get("lineage"), list) else []
    lines = []
    if description:
        lines.append(description)
    if rationale:
        lines.extend(["", "Why this task", rationale])
    if lineage:
        lines.extend(["", "Derived from"])
        for item in lineage:
            if isinstance(item, dict):
                label = item.get("label") or item.get("text") or item.get("source")
            else:
                label = item
            if str(label or "").strip():
                lines.append(f"• {str(label).strip()}")
    owner = str(task.get("owner") or "").strip()
    if owner:
        lines.extend(["", f"Suggested owner: {owner}"])
    lines.extend(["", f"Open in Jaspen: {jaspen_url}"])
    text = "\n".join(lines).strip() or "Synced from Jaspen."
    return {
        "type": "doc",
        "version": 1,
        "content": [{"type": "panel", "attrs": {"panelType": "info"}, "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "From Jaspen", "marks": [{"type": "strong"}]}]},
            *[
                {"type": "paragraph", "content": ([{"type": "text", "text": line}] if line else [])}
                for line in text.splitlines()
            ],
        ]}],
    }


def task_fields(task, binding, parent_key=None):
    config = binding.config or {}
    frontend = os.getenv("FRONTEND_BASE_URL", "https://jaspen.ai").rstrip("/")
    jaspen_url = f"{frontend}/new?sid={quote(binding.thread_id)}"
    fields = {
        "project": {"key": binding.external_container_id},
        "issuetype": {"name": str(config.get("task_issue_type") or "Task")},
        "summary": str(task.get("title") or "Untitled task")[:255],
        "description": adf_document(task, jaspen_url),
        "labels": ["jaspen", f"jaspen_plan_{binding.id.replace('-', '')[:12]}"],
    }
    if parent_key:
        fields["parent"] = {"key": parent_key}
    if task.get("due_date"):
        fields["duedate"] = str(task["due_date"])[:10]
    if task.get("priority"):
        priority_map = config.get("priority_map") if isinstance(config.get("priority_map"), dict) else {}
        name = priority_map.get(str(task["priority"]).lower()) or str(task["priority"]).title()
        fields["priority"] = {"name": name}
    start_field = str(config.get("start_date_field_id") or "").strip()
    if start_field and task.get("start_date"):
        fields[start_field] = str(task["start_date"])[:10]
    return fields


def phase_fields(phase_name, binding):
    return {
        "project": {"key": binding.external_container_id},
        "issuetype": {"name": "Epic"},
        "summary": str(phase_name)[:255],
        "labels": ["jaspen", f"jaspen_plan_{binding.id.replace('-', '')[:12]}"],
    }


def recover_issue(config, binding, entity_id):
    label = f"jaspen_plan_{binding.id.replace('-', '')[:12]}"
    safe_id = str(entity_id).replace('"', '\\"')
    jql = (
        f'project = "{binding.external_container_id}" AND labels = "{label}" '
        f'AND issue.property[jaspen].task_id = "{safe_id}"'
    )
    data, _ = request(config, "POST", "/rest/api/3/search/jql", {
        "jql": jql, "maxResults": 2, "fields": ["key", "updated"],
    })
    issues = data.get("issues") if isinstance(data, dict) else []
    return issues[0] if issues else None


def update_fields(fields):
    return {key: value for key, value in fields.items() if key not in {"project", "issuetype"}}


def set_identity(config, binding, issue_key, entity_type, jaspen_id):
    request(config, "PUT", f"/rest/api/3/issue/{quote(issue_key)}/properties/jaspen", {
        "binding_id": binding.id,
        "plan_key": binding.plan_key,
        "entity_type": entity_type,
        "task_id": jaspen_id,
    })
    frontend = os.getenv("FRONTEND_BASE_URL", "https://jaspen.ai").rstrip("/")
    global_id = quote(f"system=jaspen&binding={binding.id}&entity={entity_type}:{jaspen_id}", safe="")
    request(config, "PUT", f"/rest/api/3/issue/{quote(issue_key)}/remotelink?globalId={global_id}", {
        "globalId": f"system=jaspen&binding={binding.id}&entity={entity_type}:{jaspen_id}",
        "object": {"url": f"{frontend}/new?sid={quote(binding.thread_id)}", "title": "Open in Jaspen"}
    })


def sync_status(config, binding, issue_key, jaspen_status):
    """Move an issue using Jira workflow transitions, never by writing status."""
    status = str(jaspen_status or "todo").strip().lower()
    configured = (binding.config or {}).get("status_map")
    configured = configured if isinstance(configured, dict) else {}
    desired = str(configured.get(status) or "").strip().lower()
    category = {"todo": "new", "in_progress": "indeterminate", "blocked": "indeterminate", "done": "done"}.get(status, "new")
    data, _ = request(config, "GET", f"/rest/api/3/issue/{quote(issue_key)}/transitions?expand=transitions.fields")
    transitions = data.get("transitions") if isinstance(data, dict) else []
    selected = None
    if desired:
        selected = next((row for row in transitions or [] if str(row.get("id") or "").lower() == desired or str(row.get("name") or "").strip().lower() == desired), None)
    if selected is None and status == "blocked":
        selected = next((row for row in transitions or [] if str((row.get("to") or {}).get("name") or "").strip().lower() == "blocked"), None)
    if selected is None:
        selected = next((row for row in transitions or [] if str((((row.get("to") or {}).get("statusCategory") or {}).get("key")) or "").lower() == category), None)
    transition_id = str((selected or {}).get("id") or "").strip()
    if transition_id:
        request(config, "POST", f"/rest/api/3/issue/{quote(issue_key)}/transitions", {"transition": {"id": transition_id}})
    return bool(transition_id)
