import copy
import os
from datetime import datetime

from app.connectors.workfront import workfront_push_wbs
from app.connector_runtime import request_json_with_backoff
from app.connector_store import get_connector_settings, get_thread_sync_profile
from app.scenarios_store import load_scenarios_data, save_scenarios_data


WBS_TO_WORKFRONT_FIELD_MAPPING = {
    "title": "name",
    "due_date": "plannedCompletionDate",
    "owner": "assignedToID",
    "status": "status",
}

WORKFRONT_TO_WBS_FIELD_MAPPING = {
    "name": "title",
    "plannedCompletionDate": "due_date",
    "assignedToName": "owner",
    "status": "status",
}

WORKFRONT_TO_JASPEN_STATUS = {
    "new": "todo",
    "in progress": "in_progress",
    "working": "in_progress",
    "on hold": "blocked",
    "blocked": "blocked",
    "complete": "done",
    "completed": "done",
}



def _iso_now():
    return datetime.utcnow().isoformat()



def _text(value):
    return str(value or "").strip()



def _task_list(project_wbs):
    tasks = project_wbs.get("tasks") if isinstance(project_wbs, dict) else []
    return tasks if isinstance(tasks, list) else []



def _mapping_dict(value):
    return value if isinstance(value, dict) else {}



def _normalize_status(value):
    key = _text(value).lower()
    if not key:
        return "todo"
    return WORKFRONT_TO_JASPEN_STATUS.get(key) or (
        "done" if "complete" in key else "in_progress"
    )



def _workfront_runtime_config(user_id):
    settings = get_connector_settings(user_id, "workfront_sync")
    return {
        "base_url": _text(settings.get("workfront_base_url") or os.getenv("WORKFRONT_BASE_URL")).rstrip("/"),
        "project_id": _text(
            settings.get("workfront_project_id")
            or settings.get("external_workspace")
            or os.getenv("WORKFRONT_PROJECT_ID")
        ),
        "api_token": _text(settings.get("workfront_api_token") or os.getenv("WORKFRONT_API_TOKEN")),
        "field_mapping": _mapping_dict(settings.get("workfront_field_mapping")),
    }



def _workfront_ready(config):
    return bool(config.get("base_url") and config.get("project_id") and config.get("api_token"))



def _workfront_headers(config):
    token = config.get("api_token")
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "X-API-Key": token,
    }



def _workfront_request(config, method, path, payload=None, timeout=20):
    url = f"{config['base_url']}{path}"
    result = request_json_with_backoff(
        method,
        url,
        json_payload=payload,
        headers=_workfront_headers(config),
        timeout=timeout,
    )
    return result["data"], result



def _resolve_wbs_to_workfront_mapping(settings):
    mapping = dict(WBS_TO_WORKFRONT_FIELD_MAPPING)
    configured = _mapping_dict(settings)
    for wbs_field in ("title", "due_date", "owner", "status"):
        value = _text(configured.get(wbs_field))
        if value:
            mapping[wbs_field] = value
    return mapping



def _resolve_workfront_to_wbs_mapping(profile):
    mapping = dict(WORKFRONT_TO_WBS_FIELD_MAPPING)
    configured = _mapping_dict(profile.get("field_mapping"))
    for external_field, wbs_field in configured.items():
        ext = _text(external_field)
        wbs = _text(wbs_field)
        if ext and wbs:
            mapping[ext] = wbs
    return mapping



def _extract_record_id(data):
    if not isinstance(data, dict):
        return ""
    for key in ("id", "ID", "taskID", "objID"):
        value = _text(data.get(key))
        if value:
            return value
    payload = data.get("data")
    if isinstance(payload, dict):
        for key in ("id", "ID", "taskID", "objID"):
            value = _text(payload.get(key))
            if value:
                return value
    payload = data.get("data")
    if isinstance(payload, list) and payload:
        first = payload[0] if isinstance(payload[0], dict) else {}
        for key in ("id", "ID", "taskID", "objID"):
            value = _text(first.get(key))
            if value:
                return value
    return ""



def _task_to_workfront_fields(user_id, thread_id, task, mapping, project_id):
    task_id = _text(task.get("id")) or "task"
    title = _text(task.get("title")) or "Untitled task"
    owner = _text(task.get("owner"))
    due_date = _text(task.get("due_date")) or None
    status = _text(task.get("status")) or "todo"

    title_field = _text(mapping.get("title") or "name")
    due_field = _text(mapping.get("due_date") or "plannedCompletionDate")
    owner_field = _text(mapping.get("owner") or "assignedToID")
    status_field = _text(mapping.get("status") or "status")

    payload = {
        "projectID": project_id,
        "description": f"Synced from Jaspen task {task_id} (thread {thread_id}).",
        "jaspenMetadata": {
            "jaspen_user_id": str(user_id),
            "jaspen_thread_id": str(thread_id),
            "jaspen_task_id": task_id,
        },
        "tags": [
            f"jaspen_user_{user_id}",
            f"jaspen_thread_{thread_id}",
            f"jaspen_task_{task_id}",
        ],
    }

    if title_field:
        payload[title_field] = title
    if due_date and due_field:
        payload[due_field] = due_date
    if owner and owner_field:
        payload[owner_field] = owner
    if status and status_field:
        payload[status_field] = status
    return payload



def sync_wbs_to_workfront(user_id, thread_id, project_wbs, thread_sync_profile=None):
    profile = thread_sync_profile or get_thread_sync_profile(user_id, thread_id)
    mode = _text(profile.get("sync_mode") or "import").lower()
    connector_ids = profile.get("connector_ids") if isinstance(profile.get("connector_ids"), list) else []
    connector_ids = [str(item).strip().lower() for item in connector_ids if str(item).strip()]

    settings = get_connector_settings(user_id, "workfront_sync")

    if _text(settings.get("connection_status")).lower() != "connected":
        return {"success": False, "skipped": True, "reason": "workfront_not_connected", "project_wbs": project_wbs}
    if connector_ids and "workfront_sync" not in connector_ids:
        return {"success": False, "skipped": True, "reason": "workfront_not_selected_for_thread", "project_wbs": project_wbs}
    if mode not in ("push", "two_way"):
        return {"success": False, "skipped": True, "reason": "sync_mode_is_not_push", "project_wbs": project_wbs}

    config = _workfront_runtime_config(user_id)
    if not _workfront_ready(config):
        return {"success": False, "skipped": True, "reason": "workfront_config_missing", "project_wbs": project_wbs}
    connector_config = {
        "base_url": config.get("base_url"),
        "api_key": config.get("api_token"),
        "project_id": config.get("project_id"),
        "field_mapping": settings.get("workfront_field_mapping") if isinstance(settings.get("workfront_field_mapping"), dict) else {},
        "last_sync_at": settings.get("last_sync_at"),
    }
    return workfront_push_wbs(thread_id, project_wbs, connector_config)



def _label_lookup(labels, prefix):
    for label in labels or []:
        value = _text(label)
        if value.startswith(prefix):
            return value[len(prefix):]
    return ""



def apply_workfront_webhook_to_wbs(user_id, payload, enforce_thread_id=None, enforce_task_id=None):
    payload = payload if isinstance(payload, dict) else {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload

    labels = data.get("tags") if isinstance(data.get("tags"), list) else []
    metadata = data.get("jaspenMetadata") if isinstance(data.get("jaspenMetadata"), dict) else {}

    thread_id = _text(enforce_thread_id or metadata.get("jaspen_thread_id") or _label_lookup(labels, "jaspen_thread_"))
    task_id = _text(enforce_task_id or metadata.get("jaspen_task_id") or _label_lookup(labels, "jaspen_task_"))
    external_id = _text(data.get("id") or data.get("ID") or data.get("objID"))

    if not thread_id:
        return {"success": False, "ignored": True, "reason": "missing_thread_reference"}

    profile = get_thread_sync_profile(user_id, thread_id)
    mode = _text(profile.get("sync_mode") or "import").lower()
    if mode not in ("import", "two_way"):
        return {"success": False, "ignored": True, "reason": "thread_sync_is_push_only"}

    mapping = _resolve_workfront_to_wbs_mapping(profile)
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
        target = next((item for item in tasks if _text(item.get("id")) == task_id), None)
    if target is None and external_id:
        for item in tasks:
            refs = item.get("external_refs") if isinstance(item.get("external_refs"), dict) else {}
            if _text(refs.get("workfront_task_id")) == external_id:
                target = item
                break

    if target is None:
        return {"success": False, "ignored": True, "reason": "task_not_found"}

    title_key = _text(next((k for k, v in mapping.items() if v == "title"), "name"))
    due_key = _text(next((k for k, v in mapping.items() if v == "due_date"), "plannedCompletionDate"))
    owner_key = _text(next((k for k, v in mapping.items() if v == "owner"), "assignedToName"))
    status_key = _text(next((k for k, v in mapping.items() if v == "status"), "status"))

    if _text(data.get(title_key)):
        target["title"] = _text(data.get(title_key))
    if _text(data.get(due_key)):
        target["due_date"] = _text(data.get(due_key))
    if _text(data.get(owner_key)):
        target["owner"] = _text(data.get(owner_key))
    if _text(data.get(status_key)):
        target["status"] = _normalize_status(data.get(status_key))

    refs = target.get("external_refs") if isinstance(target.get("external_refs"), dict) else {}
    if external_id:
        refs["workfront_task_id"] = external_id
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
        "workfront_task_id": external_id,
    }


def import_tasks_from_workfront(user_id, thread_id):
    profile = get_thread_sync_profile(user_id, thread_id)
    config = _workfront_runtime_config(user_id)
    if not _workfront_ready(config):
        return {"success": False, "reason": "workfront_config_missing", "tasks": [], "external_id_map": {}}

    mapping = _resolve_workfront_to_wbs_mapping(profile)
    fields = "ID,name,status,plannedCompletionDate,assignedToName"
    path = f"/attask/api/v15.0/task/search?projectID={config['project_id']}&fields={fields}"
    try:
        data, meta = _workfront_request(config, "GET", path)
    except Exception as exc:
        return {"success": False, "reason": str(exc), "tasks": [], "external_id_map": {}}

    rows = data.get("data") if isinstance(data.get("data"), list) else []
    tasks = []
    external_id_map = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        external_id = _text(row.get("ID") or row.get("id"))
        if not external_id:
            continue
        title = _text(row.get(next((k for k, v in mapping.items() if v == "title"), "name"))) or f"Workfront Task {external_id}"
        due = _text(row.get(next((k for k, v in mapping.items() if v == "due_date"), "plannedCompletionDate")))
        owner = _text(row.get(next((k for k, v in mapping.items() if v == "owner"), "assignedToName")))
        status = _normalize_status(row.get(next((k for k, v in mapping.items() if v == "status"), "status")))
        task_id = f"workfront_{external_id}"
        tasks.append({
            "id": task_id,
            "title": title,
            "status": status,
            "owner": owner,
            "due_date": due or None,
            "source": "workfront_import",
            "external_refs": {"workfront_task_id": external_id},
        })
        external_id_map[task_id] = external_id

    return {
        "success": True,
        "thread_id": thread_id,
        "connector_id": "workfront_sync",
        "attempt_count": meta.get("attempt_count"),
        "duration_ms": meta.get("duration_ms"),
        "tasks": tasks,
        "external_id_map": external_id_map,
    }
