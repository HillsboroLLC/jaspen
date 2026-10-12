import hashlib
import os
from datetime import date, datetime, timedelta
from urllib.parse import quote

from app.connector_store import get_connector_settings
from app.jira_sync import _jira_request, _jira_runtime_config, _normalize_jira_base_url
from app.pm_sync.provider import ProjectToolProvider


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


def test_connection(settings):
    """Validate transient credentials without persisting or logging a token."""
    config = {
        "base_url": _normalize_jira_base_url(settings.get("jira_base_url")),
        "email": str(settings.get("jira_email") or "").strip(),
        "api_token": str(settings.get("jira_api_token") or "").strip(),
    }
    if not all(config.values()):
        raise ValueError("Jira site URL, email, and API token are required.")
    data, _ = _jira_request(config, "GET", "/rest/api/3/myself", timeout=20)
    return {"ok": True, "account_id": str((data or {}).get("accountId") or ""), "base_url": config["base_url"]}


def discover_start_date_field(config):
    """Return Jira's real date-backed start field, never a name-only match."""
    data, _ = request(config, "GET", "/rest/api/3/field", timeout=20)
    fields = data if isinstance(data, list) else []
    system_matches = []
    custom_matches = []
    for field in fields:
        if not isinstance(field, dict):
            continue
        schema = field.get("schema") if isinstance(field.get("schema"), dict) else {}
        field_id = str(field.get("id") or "").strip()
        system = str(schema.get("system") or "").strip().lower().replace("_", "")
        schema_type = str(schema.get("type") or "").strip().lower()
        custom_type = str(schema.get("custom") or "").strip().lower()
        normalized_name = "".join(ch for ch in str(field.get("name") or "").lower() if ch.isalnum())
        if field_id and (system == "startdate" or field_id.lower() == "startdate") and schema_type == "date":
            system_matches.append(field_id)
        elif (
            field_id
            and normalized_name == "startdate"
            and schema_type == "date"
            and ("datepicker" in custom_type or "date" in custom_type)
        ):
            custom_matches.append(field_id)
    return (system_matches or custom_matches or [None])[0]


def effective_start_date(task):
    explicit = str((task or {}).get("start_date") or "").strip()[:10]
    if explicit:
        return explicit
    due = str((task or {}).get("due_date") or "").strip()[:10]
    duration = (task or {}).get("timeline_days")
    if duration is None:
        duration = (task or {}).get("estimated_days")
    try:
        duration = int(duration)
        due_date = date.fromisoformat(due)
    except (TypeError, ValueError):
        return None
    if duration < 1:
        return None
    return (due_date - timedelta(days=duration)).isoformat()


def create_project(user_id, payload):
    config = assert_connected(user_id)
    key = str(payload.get("key") or "").strip().upper()
    name = str(payload.get("name") or "").strip()
    if not key or not name:
        raise ValueError("Project key and name are required.")
    me, _ = request(config, "GET", "/rest/api/3/myself", timeout=20)
    account_id = str((me or {}).get("accountId") or "")
    if not account_id:
        raise ValueError("Jira did not return an account for the project lead.")
    body = {
        "key": key,
        "name": name,
        "projectTypeKey": str(payload.get("project_type") or "software"),
        "projectTemplateKey": str(payload.get("template") or "com.pyxis.greenhopper.jira:gh-scrum-template"),
        "leadAccountId": account_id,
    }
    data, _ = request(config, "POST", "/rest/api/3/project", body, timeout=30)
    return {"id": str((data or {}).get("id") or ""), "key": key, "name": name, "url": f"{config['base_url']}/browse/{key}"}


def request(config, method, path, payload=None, timeout=30):
    return _jira_request(config, method, path, payload=payload, timeout=timeout)


def plan_label(binding):
    return f"jaspen_plan_{binding.id.replace('-', '')[:12]}"


def entity_label(binding, entity_id):
    """Searchable, stable Jira identity; entity properties are not JQL indexed."""
    digest = hashlib.sha256(f"{binding.id}:{entity_id}".encode("utf-8")).hexdigest()[:24]
    return f"jaspen_e_{digest}"


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
        "labels": ["jaspen", plan_label(binding), entity_label(binding, task.get("id"))],
    }
    if not str(task.get("owner") or "").strip() and not str(task.get("owner_email") or "").strip():
        # Jira otherwise applies the project's default assignee. An explicit
        # null keeps an unowned Jaspen task unassigned when the site permits it.
        fields["assignee"] = None
    if parent_key:
        fields["parent"] = {"key": parent_key}
    if task.get("due_date"):
        fields["duedate"] = str(task["due_date"])[:10]
    if task.get("priority"):
        priority_map = config.get("priority_map") if isinstance(config.get("priority_map"), dict) else {}
        name = priority_map.get(str(task["priority"]).lower()) or str(task["priority"]).title()
        fields["priority"] = {"name": name}
    start_field = str(config.get("start_date_field_id") or "").strip()
    start_date = effective_start_date(task)
    if start_field and start_date:
        fields[start_field] = start_date
    return fields


def phase_fields(phase_name, binding, tasks=None, entity_id=None):
    fields = {
        "project": {"key": binding.external_container_id},
        "issuetype": {"name": "Epic"},
        "summary": str(phase_name)[:255],
        "labels": ["jaspen", plan_label(binding), entity_label(binding, entity_id or f"phase:{phase_name}")],
    }
    tasks = [task for task in (tasks or []) if isinstance(task, dict)]
    starts = [effective_start_date(task) for task in tasks]
    starts = [value for value in starts if value]
    dues = [str(task.get("due_date") or "").strip()[:10] for task in tasks]
    dues = [value for value in dues if value]
    start_field = str((binding.config or {}).get("start_date_field_id") or "").strip()
    if start_field and starts:
        fields[start_field] = min(starts)
    if dues:
        fields["duedate"] = max(dues)
    return fields


def recover_issue(config, binding, entity_id):
    label = plan_label(binding)
    identity_label = entity_label(binding, entity_id)
    jql = (
        f'project = "{binding.external_container_id}" AND labels = "{label}" '
        f'AND labels = "{identity_label}"'
    )
    data, _ = request(config, "POST", "/rest/api/3/search/jql", {
        "jql": jql, "maxResults": 2, "fields": ["key", "updated"],
    })
    issues = data.get("issues") if isinstance(data, dict) else []
    return issues[0] if issues else None


def update_fields(fields):
    return {key: value for key, value in fields.items() if key not in {"project", "issuetype"}}


def get_parent(config, issue_key):
    data, _ = request(
        config, "GET", f"/rest/api/3/issue/{quote(issue_key)}?fields=parent", timeout=20,
    )
    fields = data.get("fields") if isinstance(data, dict) and isinstance(data.get("fields"), dict) else {}
    parent = fields.get("parent") if isinstance(fields.get("parent"), dict) else {}
    return str(parent.get("key") or "").strip() or None


def set_parent(config, issue_key, parent_key):
    request(config, "PUT", f"/rest/api/3/issue/{quote(issue_key)}", {
        "fields": {"parent": {"key": str(parent_key)}},
    })


def set_identity(config, binding, issue_key, entity_type, jaspen_id):
    ensure_recovery_identity(config, binding, issue_key, jaspen_id)
    request(config, "PUT", f"/rest/api/3/issue/{quote(issue_key)}/properties/jaspen", {
        "binding_id": binding.id,
        "plan_key": binding.plan_key,
        "entity_type": entity_type,
        "task_id": jaspen_id,
    })
    frontend = os.getenv("FRONTEND_BASE_URL", "https://jaspen.ai").rstrip("/")
    global_id = f"system=jaspen&binding={binding.id}&entity={entity_type}:{jaspen_id}"
    request(config, "POST", f"/rest/api/3/issue/{quote(issue_key)}/remotelink", {
        "globalId": global_id,
        "object": {"url": f"{frontend}/new?sid={quote(binding.thread_id)}", "title": "Open in Jaspen"}
    })


def ensure_recovery_identity(config, binding, issue_key, jaspen_id):
    """Backfill the JQL-searchable identity label without replacing other labels."""
    request(config, "PUT", f"/rest/api/3/issue/{quote(issue_key)}", {
        "update": {"labels": [{"add": entity_label(binding, jaspen_id)}]},
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


def _adf_text(value):
    parts = []
    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "text" and node.get("text"):
                parts.append(str(node["text"]))
            for child in node.get("content") or []:
                walk(child)
            if node.get("type") in {"paragraph", "heading"}:
                parts.append("\n")
        elif isinstance(node, list):
            for child in node:
                walk(child)
    walk(value)
    text = "".join(parts).strip()
    if text.startswith("From Jaspen"):
        text = text[len("From Jaspen"):].lstrip()
    for marker in ("\nWhy this task\n", "\nDerived from\n", "\nSuggested owner:", "\nOpen in Jaspen:"):
        if marker in text:
            text = text.split(marker, 1)[0]
    return text.strip()


def _parse_iso(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return text


def _status_from_jira(status):
    category = str((((status or {}).get("statusCategory") or {}).get("key")) or "").lower()
    name = str((status or {}).get("name") or "").strip()
    if category == "done":
        return "done", None
    if category == "indeterminate":
        return ("blocked" if name.lower() == "blocked" else "in_progress"), None
    if category in {"new", "undefined"}:
        return "todo", None
    return None, name or "Unknown Jira status"


class JiraProvider(ProjectToolProvider):
    connector_id = "jira_sync"

    def assert_connected(self, user_id, container_id=None):
        return assert_connected(user_id, container_id)

    def list_containers(self, user_id):
        return list_projects(user_id)

    def create_container(self, user_id, payload):
        return create_project(user_id, payload)

    def recover_item(self, config, binding, entity_id):
        return recover_issue(config, binding, entity_id)

    def set_identity(self, config, binding, external_id, entity_type, jaspen_id):
        return set_identity(config, binding, external_id, entity_type, jaspen_id)

    def ensure_recovery_identity(self, config, binding, external_id, jaspen_id):
        return ensure_recovery_identity(config, binding, external_id, jaspen_id)

    def create_items(self, config, binding, items):
        payload = {"issueUpdates": [
            {"fields": phase_fields(row["title"], binding, entity_id=row.get("jaspen_id"))} if row.get("entity_type") == "phase"
            else {"fields": task_fields(row["task"], binding, row.get("parent_id"))}
            for row in items
        ]}
        data, _ = request(config, "POST", "/rest/api/3/issue/bulk", payload, timeout=45)
        return data or {}

    def update_item(self, config, binding, external_id, changes, task=None):
        task = dict(task or {})
        task.update(changes or {})
        fields = {}
        if "title" in changes:
            fields["summary"] = str(changes.get("title") or "Untitled task")[:255]
        if "description" in changes:
            fields["description"] = adf_document(task, f"{os.getenv('FRONTEND_BASE_URL', 'https://jaspen.ai').rstrip('/')}/new?sid={quote(binding.thread_id)}")
        if "due_date" in changes:
            fields["duedate"] = str(changes.get("due_date") or "")[:10] or None
        start_field = str((binding.config or {}).get("start_date_field_id") or "").strip()
        if "start_date" in changes and start_field:
            fields[start_field] = str(changes.get("start_date") or "")[:10] or None
        if "owner_email" in changes or "owner" in changes:
            user_map = binding.user_map if isinstance(binding.user_map, dict) else {}
            account_id = user_map.get(str(changes.get("owner_email") or task.get("owner_email") or "")) or user_map.get(str(changes.get("owner") or task.get("owner") or ""))
            if account_id:
                fields["assignee"] = {"accountId": account_id}
            elif not str(changes.get("owner") or "").strip() and not str(changes.get("owner_email") or "").strip():
                fields["assignee"] = None
        if fields:
            request(config, "PUT", f"/rest/api/3/issue/{quote(external_id)}", {"fields": fields})
        status_ok = True
        if "status" in changes:
            status_ok = sync_status(config, binding, external_id, changes.get("status"))
        return {"status_mapped": status_ok}

    def create_dependency(self, config, binding, prerequisite_id, dependent_id):
        data, _ = request(config, "POST", "/rest/api/3/issueLink", {
            "type": {"name": "Blocks"}, "inwardIssue": {"key": prerequisite_id}, "outwardIssue": {"key": dependent_id},
        })
        return str((data or {}).get("id") or f"{prerequisite_id}->{dependent_id}")

    def get_item(self, config, binding, external_id):
        start_field = str((binding.config or {}).get("start_date_field_id") or "").strip()
        fields = ["summary", "description", "assignee", "status", "parent", "duedate", "updated"]
        if start_field:
            fields.append(start_field)
        try:
            data, _ = request(config, "GET", f"/rest/api/3/issue/{quote(external_id)}?expand=changelog&fields={','.join(fields)}", timeout=30)
        except Exception as exc:
            response = getattr(exc, "response", None)
            if getattr(response, "status_code", None) == 404:
                return {"deleted": True, "values": {}, "changed_at": {}, "version": None}
            raise
        row = data if isinstance(data, dict) else {}
        remote = row.get("fields") if isinstance(row.get("fields"), dict) else {}
        status, status_error = _status_from_jira(remote.get("status"))
        assignee = remote.get("assignee") if isinstance(remote.get("assignee"), dict) else {}
        parent = remote.get("parent") if isinstance(remote.get("parent"), dict) else {}
        values = {
            "title": remote.get("summary") or "",
            "description": _adf_text(remote.get("description")),
            "owner": assignee.get("displayName") or "",
            "owner_email": assignee.get("emailAddress") or "",
            "status": status,
            "start_date": remote.get(start_field) if start_field else None,
            "due_date": remote.get("duedate"),
        }
        field_map = {"summary": "title", "description": "description", "assignee": "owner", "status": "status", "duedate": "due_date"}
        if start_field:
            field_map[start_field] = "start_date"
        changed_at = {}
        histories = ((row.get("changelog") or {}).get("histories") or []) if isinstance(row.get("changelog"), dict) else []
        for history in histories:
            created = _parse_iso(history.get("created"))
            for item in history.get("items") or []:
                key = field_map.get(str(item.get("fieldId") or "")) or field_map.get(str(item.get("field") or "").lower())
                if key and created and (not changed_at.get(key) or created > changed_at[key]):
                    changed_at[key] = created
                    if key == "owner":
                        changed_at["owner_email"] = created
        return {
            "deleted": False, "values": values, "changed_at": changed_at,
            "version": _parse_iso(remote.get("updated")), "status_error": status_error,
            "parent_id": str(parent.get("key") or "").strip() or None,
            "supported_fields": ["title", "description", "owner", "owner_email", "status", "due_date"] + (["start_date"] if start_field else []),
            "url": f"{config['base_url']}/browse/{external_id}",
        }
