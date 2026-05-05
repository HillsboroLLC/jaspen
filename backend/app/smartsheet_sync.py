import copy
import os
from datetime import datetime

from app.connectors.smartsheet import smartsheet_push_wbs
from app.connector_runtime import request_json_with_backoff
from app.connector_store import get_connector_settings, get_thread_sync_profile
from app.scenarios_store import load_scenarios_data, save_scenarios_data


WBS_TO_SMARTSHEET_FIELD_MAPPING = {
    "title": "Task Name",
    "due_date": "Due Date",
    "owner": "Assigned To",
    "status": "Status",
}

SMARTSHEET_TO_WBS_FIELD_MAPPING = {
    "Task Name": "title",
    "Due Date": "due_date",
    "Assigned To": "owner",
    "Status": "status",
}

SMARTSHEET_STATUS_MAP = {
    "not started": "todo",
    "in progress": "in_progress",
    "at risk": "blocked",
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
    return SMARTSHEET_STATUS_MAP.get(key) or ("done" if "complete" in key else "in_progress")



def _runtime_config(user_id):
    settings = get_connector_settings(user_id, "smartsheet_sync")
    return {
        "base_url": _text(settings.get("smartsheet_base_url") or os.getenv("SMARTSHEET_BASE_URL") or "https://api.smartsheet.com").rstrip("/"),
        "sheet_id": _text(
            settings.get("smartsheet_sheet_id")
            or settings.get("external_workspace")
            or os.getenv("SMARTSHEET_SHEET_ID")
        ),
        "api_token": _text(settings.get("smartsheet_api_token") or os.getenv("SMARTSHEET_API_TOKEN")),
        "field_mapping": _mapping_dict(settings.get("smartsheet_field_mapping")),
    }



def _ready(config):
    return bool(config.get("base_url") and config.get("sheet_id") and config.get("api_token"))



def _headers(config):
    token = config.get("api_token")
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }



def _smartsheet_request(config, method, path, payload=None, timeout=20):
    url = f"{config['base_url']}{path}"
    result = request_json_with_backoff(
        method,
        url,
        json_payload=payload,
        headers=_headers(config),
        timeout=timeout,
    )
    return result["data"], result



def _resolve_wbs_to_smartsheet_mapping(settings):
    mapping = dict(WBS_TO_SMARTSHEET_FIELD_MAPPING)
    configured = _mapping_dict(settings)
    for wbs_field in ("title", "due_date", "owner", "status"):
        value = _text(configured.get(wbs_field))
        if value:
            mapping[wbs_field] = value
    return mapping



def _resolve_smartsheet_to_wbs_mapping(profile):
    mapping = dict(SMARTSHEET_TO_WBS_FIELD_MAPPING)
    configured = _mapping_dict(profile.get("field_mapping"))
    for external_field, wbs_field in configured.items():
        ext = _text(external_field)
        wbs = _text(wbs_field)
        if ext and wbs:
            mapping[ext] = wbs
    return mapping



def _build_cell(column_key, value):
    reference = _text(column_key)
    if not reference:
        return None
    payload = {"value": value}
    if reference.isdigit():
        payload["columnId"] = int(reference)
    else:
        payload["columnName"] = reference
    return payload



def _task_to_row(user_id, thread_id, task, mapping, include_id=None):
    title = _text(task.get("title")) or "Untitled task"
    owner = _text(task.get("owner"))
    due_date = _text(task.get("due_date")) or None
    status = _text(task.get("status")) or "todo"
    task_id = _text(task.get("id")) or "task"

    cells = []
    for field, value in (
        (mapping.get("title") or "Task Name", title),
        (mapping.get("owner") or "Assigned To", owner),
        (mapping.get("due_date") or "Due Date", due_date),
        (mapping.get("status") or "Status", status),
    ):
        if value in (None, ""):
            continue
        cell = _build_cell(field, value)
        if cell:
            cells.append(cell)

    metadata_cell = _build_cell(
        "Jaspen Metadata",
        f"jaspen_user={user_id};thread={thread_id};task={task_id}",
    )
    if metadata_cell:
        cells.append(metadata_cell)

    row = {
        "toBottom": True,
        "cells": cells,
    }
    if include_id:
        row["id"] = include_id
    return row



def _extract_row_id(data):
    if not isinstance(data, dict):
        return ""
    for key in ("id", "rowId"):
        value = _text(data.get(key))
        if value:
            return value

    result = data.get("result")
    if isinstance(result, list) and result:
        first = result[0] if isinstance(result[0], dict) else {}
        for key in ("id", "rowId"):
            value = _text(first.get(key))
            if value:
                return value

    data_rows = data.get("data")
    if isinstance(data_rows, list) and data_rows:
        first = data_rows[0] if isinstance(data_rows[0], dict) else {}
        for key in ("id", "rowId"):
            value = _text(first.get(key))
            if value:
                return value
    return ""



def sync_wbs_to_smartsheet(user_id, thread_id, project_wbs, thread_sync_profile=None):
    profile = thread_sync_profile or get_thread_sync_profile(user_id, thread_id)
    mode = _text(profile.get("sync_mode") or "import").lower()
    connector_ids = profile.get("connector_ids") if isinstance(profile.get("connector_ids"), list) else []
    connector_ids = [str(item).strip().lower() for item in connector_ids if str(item).strip()]

    settings = get_connector_settings(user_id, "smartsheet_sync")

    if _text(settings.get("connection_status")).lower() != "connected":
        return {"success": False, "skipped": True, "reason": "smartsheet_not_connected", "project_wbs": project_wbs}
    if connector_ids and "smartsheet_sync" not in connector_ids:
        return {"success": False, "skipped": True, "reason": "smartsheet_not_selected_for_thread", "project_wbs": project_wbs}
    if mode not in ("push", "two_way"):
        return {"success": False, "skipped": True, "reason": "sync_mode_is_not_push", "project_wbs": project_wbs}

    config = _runtime_config(user_id)
    if not _ready(config):
        return {"success": False, "skipped": True, "reason": "smartsheet_config_missing", "project_wbs": project_wbs}
    connector_config = {
        "base_url": config.get("base_url"),
        "access_token": config.get("api_token"),
        "sheet_id": config.get("sheet_id"),
        "field_mapping": settings.get("smartsheet_field_mapping") if isinstance(settings.get("smartsheet_field_mapping"), dict) else {},
        "last_sync_at": settings.get("last_sync_at"),
    }
    return smartsheet_push_wbs(thread_id, project_wbs, connector_config)



def _labels_lookup(labels, prefix):
    for label in labels or []:
        token = _text(label)
        if token.startswith(prefix):
            return token[len(prefix):]
    return ""



def _extract_cell_map(row):
    cells = row.get("cells") if isinstance(row.get("cells"), list) else []
    mapping = {}
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        key = _text(cell.get("columnName") or cell.get("title") or cell.get("columnId"))
        if not key:
            continue
        value = cell.get("displayValue")
        if value is None:
            value = cell.get("value")
        mapping[key] = value
    return mapping



def apply_smartsheet_webhook_to_wbs(user_id, payload, enforce_thread_id=None, enforce_task_id=None):
    payload = payload if isinstance(payload, dict) else {}

    row = payload.get("row") if isinstance(payload.get("row"), dict) else {}
    if not row:
        events = payload.get("events") if isinstance(payload.get("events"), list) else []
        first = events[0] if events and isinstance(events[0], dict) else {}
        row = first.get("row") if isinstance(first.get("row"), dict) else first

    labels = row.get("labels") if isinstance(row.get("labels"), list) else []
    metadata = row.get("jaspen_metadata") if isinstance(row.get("jaspen_metadata"), dict) else {}
    thread_id = _text(enforce_thread_id or metadata.get("thread_id") or _labels_lookup(labels, "jaspen_thread_"))
    task_id = _text(enforce_task_id or metadata.get("task_id") or _labels_lookup(labels, "jaspen_task_"))
    row_id = _text(row.get("id") or row.get("rowId"))

    if not thread_id:
        return {"success": False, "ignored": True, "reason": "missing_thread_reference"}

    profile = get_thread_sync_profile(user_id, thread_id)
    mode = _text(profile.get("sync_mode") or "import").lower()
    if mode not in ("import", "two_way"):
        return {"success": False, "ignored": True, "reason": "thread_sync_is_push_only"}

    mapping = _resolve_smartsheet_to_wbs_mapping(profile)
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
    if target is None and row_id:
        for item in tasks:
            refs = item.get("external_refs") if isinstance(item.get("external_refs"), dict) else {}
            if _text(refs.get("smartsheet_row_id")) == row_id:
                target = item
                break

    if target is None:
        return {"success": False, "ignored": True, "reason": "task_not_found"}

    cell_values = _extract_cell_map(row)

    def _external_value_for(wbs_field, fallback_key):
        for external_key, mapped in mapping.items():
            if _text(mapped) == wbs_field and external_key in cell_values:
                return cell_values.get(external_key)
        return cell_values.get(fallback_key)

    title = _external_value_for("title", "Task Name")
    due_date = _external_value_for("due_date", "Due Date")
    owner = _external_value_for("owner", "Assigned To")
    status = _external_value_for("status", "Status")

    if _text(title):
        target["title"] = _text(title)
    if _text(due_date):
        target["due_date"] = _text(due_date)
    if _text(owner):
        target["owner"] = _text(owner)
    if _text(status):
        target["status"] = _normalize_status(status)

    refs = target.get("external_refs") if isinstance(target.get("external_refs"), dict) else {}
    if row_id:
        refs["smartsheet_row_id"] = row_id
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
        "smartsheet_row_id": row_id,
    }


def import_tasks_from_smartsheet(user_id, thread_id):
    profile = get_thread_sync_profile(user_id, thread_id)
    config = _runtime_config(user_id)
    if not _ready(config):
        return {"success": False, "reason": "smartsheet_config_missing", "tasks": [], "external_id_map": {}}

    mapping = _resolve_smartsheet_to_wbs_mapping(profile)
    try:
        sheet_data, meta = _smartsheet_request(config, "GET", f"/2.0/sheets/{config['sheet_id']}")
    except Exception as exc:
        return {"success": False, "reason": str(exc), "tasks": [], "external_id_map": {}}

    columns = sheet_data.get("columns") if isinstance(sheet_data.get("columns"), list) else []
    col_name_by_id = {}
    for col in columns:
        if not isinstance(col, dict):
            continue
        col_id = _text(col.get("id"))
        col_name = _text(col.get("title"))
        if col_id and col_name:
            col_name_by_id[col_id] = col_name

    rows = sheet_data.get("rows") if isinstance(sheet_data.get("rows"), list) else []
    tasks = []
    external_id_map = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_id = _text(row.get("id") or row.get("rowId"))
        if not row_id:
            continue
        cells = row.get("cells") if isinstance(row.get("cells"), list) else []
        values = {}
        for cell in cells:
            if not isinstance(cell, dict):
                continue
            key = _text(cell.get("columnName") or cell.get("title"))
            if not key:
                col_id = _text(cell.get("columnId"))
                key = col_name_by_id.get(col_id) or col_id
            if not key:
                continue
            value = cell.get("displayValue")
            if value is None:
                value = cell.get("value")
            values[key] = value

        def _value_for(wbs_field, fallback):
            for external_key, mapped in mapping.items():
                if _text(mapped) == wbs_field and external_key in values:
                    return values.get(external_key)
            return values.get(fallback)

        title = _text(_value_for("title", "Task Name")) or f"Smartsheet Row {row_id}"
        due_date = _text(_value_for("due_date", "Due Date"))
        owner = _text(_value_for("owner", "Assigned To"))
        status = _normalize_status(_value_for("status", "Status"))
        task_id = f"smartsheet_{row_id}"
        tasks.append({
            "id": task_id,
            "title": title,
            "status": status,
            "owner": owner,
            "due_date": due_date or None,
            "source": "smartsheet_import",
            "external_refs": {"smartsheet_row_id": row_id},
        })
        external_id_map[task_id] = row_id

    return {
        "success": True,
        "thread_id": thread_id,
        "connector_id": "smartsheet_sync",
        "attempt_count": meta.get("attempt_count"),
        "duration_ms": meta.get("duration_ms"),
        "tasks": tasks,
        "external_id_map": external_id_map,
    }
