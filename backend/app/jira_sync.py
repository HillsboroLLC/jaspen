import copy
import os
from datetime import datetime

import requests

from app.connector_store import get_connector_settings, get_thread_sync_profile
from app.scenarios_store import load_scenarios_data, save_scenarios_data


JAS_TO_JIRA_STATUS = {
    "todo": "To Do",
    "in_progress": "In Progress",
    "blocked": "Blocked",
    "done": "Done",
}

JIRA_TO_JAS_STATUS = {
    "to do": "todo",
    "selected for development": "todo",
    "open": "todo",
    "in progress": "in_progress",
    "blocked": "blocked",
    "done": "done",
    "closed": "done",
    "resolved": "done",
}


DEFAULT_WBS_TO_JIRA_FIELD_MAPPING = {
    "title": "summary",
    "due_date": "duedate",
}

DEFAULT_JIRA_TO_WBS_FIELD_MAPPING = {
    "summary": "title",
    "status.name": "status",
    "assignee.displayName": "owner",
    "duedate": "due_date",
}


def _iso_now():
    return datetime.utcnow().isoformat()


def _task_list(project_wbs):
    tasks = project_wbs.get("tasks") if isinstance(project_wbs, dict) else []
    return tasks if isinstance(tasks, list) else []


def _text(value):
    return str(value or "").strip()


def _mapping_dict(value):
    return value if isinstance(value, dict) else {}


def _path_get(payload, path):
    if not isinstance(payload, dict):
        return None
    key = _text(path)
    if not key:
        return None
    parts = [part for part in key.split(".") if part]
    current = payload
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _pick_external_key_for_wbs(jira_to_wbs_map, wbs_field, fallback):
    for external_key, mapped_wbs_field in jira_to_wbs_map.items():
        if _text(mapped_wbs_field) == wbs_field:
            return _text(external_key)
    return fallback


def _resolve_wbs_to_jira_mapping(settings):
    mapping = dict(DEFAULT_WBS_TO_JIRA_FIELD_MAPPING)
    configured = _mapping_dict(settings.get("jira_field_mapping"))
    for wbs_field in ("title", "due_date", "owner", "status"):
        value = configured.get(wbs_field)
        if value is not None:
            mapping[wbs_field] = _text(value)
    return mapping


def _resolve_jira_to_wbs_mapping(profile):
    mapping = dict(DEFAULT_JIRA_TO_WBS_FIELD_MAPPING)
    configured = _mapping_dict(profile.get("field_mapping"))
    for external_key, wbs_field in configured.items():
        ext = _text(external_key)
        mapped = _text(wbs_field)
        if ext and mapped:
            mapping[ext] = mapped
    return mapping


def _jira_runtime_config(user_id):
    settings = get_connector_settings(user_id, "jira_sync")
    return {
        "base_url": _text(settings.get("jira_base_url") or os.getenv("JIRA_BASE_URL")).rstrip("/"),
        "project_key": _text(
            settings.get("jira_project_key")
            or settings.get("external_workspace")
            or os.getenv("JIRA_DEFAULT_PROJECT_KEY")
        ),
        "email": _text(settings.get("jira_email") or os.getenv("JIRA_EMAIL")),
        "api_token": _text(settings.get("jira_api_token") or os.getenv("JIRA_API_TOKEN")),
        "issue_type": _text(settings.get("jira_issue_type") or os.getenv("JIRA_DEFAULT_ISSUE_TYPE") or "Task"),
    }


def _jira_ready(config):
    return bool(config.get("base_url") and config.get("project_key") and config.get("email") and config.get("api_token"))


def _jira_headers():
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _adf_doc(text):
    payload = _text(text)[:6000] or "Synced from Jaspen."
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": payload},
                ],
            }
        ],
    }


def _task_to_jira_fields(user_id, thread_id, task, wbs_to_jira_map):
    task_id = _text(task.get("id")) or "task"
    title = _text(task.get("title")) or "Untitled task"
    owner = _text(task.get("owner"))
    due_date = _text(task.get("due_date")) or None
    status = _text(task.get("status")).lower() or "todo"
    labels = [
        "jaspen",
        f"jaspen_user_{user_id}",
        f"jaspen_thread_{thread_id}",
        f"jaspen_task_{task_id}",
        f"jaspen_status_{status}",
    ]
    description_lines = [
        f"Jaspen task id: {task_id}",
        f"Thread: {thread_id}",
        f"Status: {status}",
    ]
    if owner:
        description_lines.append(f"Owner: {owner}")
    if due_date:
        description_lines.append(f"Due date: {due_date}")

    title_key = _text(wbs_to_jira_map.get("title") or "summary")
    due_date_key = _text(wbs_to_jira_map.get("due_date") or "duedate")
    owner_key = _text(wbs_to_jira_map.get("owner"))
    status_key = _text(wbs_to_jira_map.get("status"))

    fields = {
        "description": _adf_doc("\n".join(description_lines)),
        "labels": labels,
    }
    if title_key:
        fields[title_key] = title
    if due_date and due_date_key:
        fields[due_date_key] = due_date
    if owner and owner_key and owner_key.startswith("customfield_"):
        fields[owner_key] = owner
    if status and status_key and status_key.startswith("customfield_"):
        fields[status_key] = status
    return fields


def _jira_request(config, method, path, payload=None, timeout=20):
    url = f"{config['base_url']}{path}"
    response = requests.request(
        method=method,
        url=url,
        json=payload,
        headers=_jira_headers(),
        auth=(config["email"], config["api_token"]),
        timeout=timeout,
    )
    data = {}
    try:
        data = response.json() if response.text else {}
    except Exception:
        data = {"raw": response.text}
    if response.status_code >= 400:
        raise RuntimeError(f"Jira API {method} {path} failed ({response.status_code}): {data}")
    return data


def sync_wbs_to_jira(user_id, thread_id, project_wbs, thread_sync_profile=None):
    profile = thread_sync_profile or get_thread_sync_profile(user_id, thread_id)
    mode = _text(profile.get("sync_mode") or "import").lower()
    connector_ids = profile.get("connector_ids") if isinstance(profile.get("connector_ids"), list) else []
    connector_ids = [str(item).strip().lower() for item in connector_ids if str(item).strip()]
    settings = get_connector_settings(user_id, "jira_sync")
    wbs_to_jira_map = _resolve_wbs_to_jira_mapping(settings)

    if str(settings.get("connection_status") or "").lower() != "connected":
        return {"success": False, "skipped": True, "reason": "jira_not_connected", "project_wbs": project_wbs}
    if connector_ids and "jira_sync" not in connector_ids:
        return {"success": False, "skipped": True, "reason": "jira_not_selected_for_thread", "project_wbs": project_wbs}
    if mode not in ("push", "two_way"):
        return {"success": False, "skipped": True, "reason": "sync_mode_is_not_push", "project_wbs": project_wbs}

    config = _jira_runtime_config(user_id)
    if not _jira_ready(config):
        return {"success": False, "skipped": True, "reason": "jira_config_missing", "project_wbs": project_wbs}

    updated_wbs = copy.deepcopy(project_wbs) if isinstance(project_wbs, dict) else {"name": "Execution WBS", "tasks": []}
    tasks = _task_list(updated_wbs)
    created = 0
    updated = 0
    errors = []

    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_id = _text(task.get("id"))
        if not task_id:
            continue
        refs = task.get("external_refs") if isinstance(task.get("external_refs"), dict) else {}
        issue_key = _text(refs.get("jira_issue_key") or task.get("jira_issue_key"))

        fields = _task_to_jira_fields(user_id, thread_id, task, wbs_to_jira_map)
        try:
            if issue_key:
                _jira_request(
                    config,
                    "PUT",
                    f"/rest/api/3/issue/{issue_key}",
                    payload={"fields": fields},
                )
                updated += 1
            else:
                create_payload = {
                    "fields": {
                        "project": {"key": config["project_key"]},
                        "issuetype": {"name": config["issue_type"]},
                        **fields,
                    }
                }
                created_issue = _jira_request(config, "POST", "/rest/api/3/issue", payload=create_payload)
                new_key = _text(created_issue.get("key"))
                if new_key:
                    refs["jira_issue_key"] = new_key
                    task["external_refs"] = refs
                    updated += 1
                    created += 1
        except Exception as e:
            errors.append({"task_id": task_id, "error": str(e)})

    updated_wbs["updated_at"] = _iso_now()
    return {
        "success": len(errors) == 0,
        "skipped": False,
        "created_issues": created,
        "updated_tasks": updated,
        "errors": errors,
        "project_wbs": updated_wbs,
    }


def _label_value(labels, prefix):
    for label in labels or []:
        text = _text(label)
        if text.startswith(prefix):
            return text[len(prefix):]
    return ""


def _jira_status_to_jaspen(status_name):
    value = _text(status_name).lower()
    return JIRA_TO_JAS_STATUS.get(value) or "in_progress"


def apply_jira_webhook_to_wbs(user_id, issue, enforce_thread_id=None, enforce_task_id=None):
    issue = issue if isinstance(issue, dict) else {}
    issue_key = _text(issue.get("key"))
    fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
    labels = fields.get("labels") if isinstance(fields.get("labels"), list) else []
    summary = _text(fields.get("summary"))
    due_date = _text(fields.get("duedate")) or None
    assignee = fields.get("assignee") if isinstance(fields.get("assignee"), dict) else {}
    owner = _text(assignee.get("displayName"))
    status_obj = fields.get("status") if isinstance(fields.get("status"), dict) else {}
    status_name = _text(status_obj.get("name"))
    next_status = _jira_status_to_jaspen(status_name)

    thread_id = _text(enforce_thread_id or _label_value(labels, "jaspen_thread_"))
    task_id = _text(enforce_task_id or _label_value(labels, "jaspen_task_"))
    if not thread_id:
        return {"success": False, "ignored": True, "reason": "missing_thread_label"}

    profile = get_thread_sync_profile(user_id, thread_id)
    jira_to_wbs_map = _resolve_jira_to_wbs_mapping(profile)
    mode = _text(profile.get("sync_mode") or "import").lower()
    if mode not in ("import", "two_way"):
        return {"success": False, "ignored": True, "reason": "thread_sync_is_push_only"}

    scenarios = load_scenarios_data(user_id)
    thread_data = scenarios.get(thread_id)
    if not isinstance(thread_data, dict):
        return {"success": False, "ignored": True, "reason": "thread_not_found"}
    project_wbs = thread_data.get("project_wbs")
    if not isinstance(project_wbs, dict):
        return {"success": False, "ignored": True, "reason": "wbs_not_found"}

    tasks = _task_list(project_wbs)
    target = None
    if task_id:
        for task in tasks:
            if _text(task.get("id")) == task_id:
                target = task
                break
    if target is None and issue_key:
        for task in tasks:
            refs = task.get("external_refs") if isinstance(task.get("external_refs"), dict) else {}
            if _text(refs.get("jira_issue_key")) == issue_key:
                target = task
                break
    if target is None:
        return {"success": False, "ignored": True, "reason": "task_not_found"}

    title_external_key = _pick_external_key_for_wbs(jira_to_wbs_map, "title", "summary")
    owner_external_key = _pick_external_key_for_wbs(jira_to_wbs_map, "owner", "assignee.displayName")
    due_external_key = _pick_external_key_for_wbs(jira_to_wbs_map, "due_date", "duedate")
    status_external_key = _pick_external_key_for_wbs(jira_to_wbs_map, "status", "status.name")

    incoming_title = _path_get(fields, title_external_key)
    incoming_owner = _path_get(fields, owner_external_key)
    incoming_due = _path_get(fields, due_external_key)
    incoming_status = _path_get(fields, status_external_key)
    if isinstance(incoming_owner, dict):
        incoming_owner = incoming_owner.get("displayName") or incoming_owner.get("accountId")
    if isinstance(incoming_status, dict):
        incoming_status = incoming_status.get("name")

    if _text(incoming_title):
        target["title"] = _text(incoming_title)
    elif summary:
        target["title"] = summary
    if _text(incoming_owner):
        target["owner"] = _text(incoming_owner)
    elif owner:
        target["owner"] = owner
    if _text(incoming_due):
        target["due_date"] = _text(incoming_due)
    elif due_date:
        target["due_date"] = due_date
    target["status"] = _jira_status_to_jaspen(_text(incoming_status) or status_name or next_status)
    refs = target.get("external_refs") if isinstance(target.get("external_refs"), dict) else {}
    if issue_key:
        refs["jira_issue_key"] = issue_key
    target["external_refs"] = refs
    project_wbs["updated_at"] = _iso_now()
    thread_data["project_wbs"] = project_wbs
    scenarios[thread_id] = thread_data
    save_scenarios_data(user_id, scenarios)

    return {
        "success": True,
        "ignored": False,
        "thread_id": thread_id,
        "task_id": _text(target.get("id")),
        "jira_issue_key": issue_key,
        "status": next_status,
    }
