import copy
from datetime import datetime

from app.connector_store import connector_api_call


DEFAULT_BASE_URL = "https://api.smartsheet.com"
DEFAULT_MAPPING = {
    "title": "Task Name",
    "due_date": "Due Date",
    "owner": "Assigned To",
    "status": "Status",
}


def _text(value):
    return str(value or "").strip()


def _iso_now():
    return datetime.utcnow().isoformat()


def _task_list(project_wbs):
    tasks = project_wbs.get("tasks") if isinstance(project_wbs, dict) else []
    return tasks if isinstance(tasks, list) else []


def _base_url(config):
    return _text(
        config.get("base_url")
        or config.get("smartsheet_base_url")
        or DEFAULT_BASE_URL
    ).rstrip("/")


def _access_token(config):
    return _text(
        config.get("access_token")
        or config.get("api_token")
        or config.get("smartsheet_api_token")
    )


def _headers(config):
    token = _access_token(config)
    if not token:
        raise RuntimeError("Missing Smartsheet access token.")
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }


def _request(config, method, path, body=None, params=None):
    url = f"{_base_url(config)}/{str(path or '').lstrip('/')}"
    return connector_api_call(
        method=method,
        url=url,
        headers=_headers(config),
        body=body,
        params=params,
        max_retries=3,
        timeout=20,
    )


def _sheet_id(config):
    return _text(config.get("sheet_id") or config.get("smartsheet_sheet_id"))


def _column_index(sheet):
    columns = sheet.get("columns") if isinstance(sheet.get("columns"), list) else []
    index = {}
    for column in columns:
        row = column if isinstance(column, dict) else {}
        col_id = row.get("id")
        title = _text(row.get("title"))
        if col_id is not None and title:
            index[title] = col_id
    return index


def _find_row_id(payload):
    data = payload.get("data")
    if isinstance(data, dict) and _text(data.get("id")):
        return _text(data.get("id"))
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return _text(data[0].get("id"))

    result = payload.get("result")
    if isinstance(result, list) and result and isinstance(result[0], dict):
        return _text(result[0].get("id"))
    if isinstance(result, dict):
        return _text(result.get("id"))
    return ""


def _cells_for_task(task, column_map, mapping, thread_id):
    task_id = _text(task.get("id")) or "task"
    fields = {
        "title": _text(task.get("title")) or "Untitled task",
        "due_date": _text(task.get("due_date")) or "",
        "owner": _text(task.get("owner")) or "",
        "status": _text(task.get("status")) or "todo",
    }
    cells = []
    for source_field, column_name in mapping.items():
        column_id = column_map.get(column_name)
        value = fields.get(source_field)
        if column_id is None or value in (None, ""):
            continue
        cells.append({"columnId": column_id, "value": value})

    metadata_col = column_map.get("Jaspen Metadata")
    if metadata_col is not None:
        cells.append(
            {
                "columnId": metadata_col,
                "value": f"thread={thread_id};task={task_id}",
            }
        )
    return cells


def smartsheet_connect(access_token):
    config = {"access_token": access_token, "base_url": DEFAULT_BASE_URL}
    try:
        _request(config, "GET", "2.0/users/me")
        return True
    except Exception:
        return False


def smartsheet_list_sheets(config):
    settings = config if isinstance(config, dict) else {}
    response = _request(settings, "GET", "2.0/sheets", params={"includeAll": "true", "pageSize": 100})
    payload = response.get("data")
    rows = payload.get("data") if isinstance(payload, dict) else None
    sheets = rows if isinstance(rows, list) else []
    normalized = []
    for sheet in sheets:
        item = sheet if isinstance(sheet, dict) else {}
        normalized.append(
            {
                "id": _text(item.get("id")),
                "name": _text(item.get("name")),
                "access_level": _text(item.get("accessLevel")),
                "permalink": _text(item.get("permalink")),
            }
        )
    return normalized


def smartsheet_get_sheet(config, sheet_id):
    """Read one configured sheet without changing it."""
    target = _text(sheet_id)
    if not target:
        raise RuntimeError("Smartsheet sheet ID is not configured.")
    response = _request(config, "GET", f"2.0/sheets/{target}")
    payload = response.get("data")
    if not isinstance(payload, dict):
        raise RuntimeError("Smartsheet returned an unexpected sheet response.")
    return payload


def smartsheet_push_wbs(thread_id, wbs_data, config):
    settings = config if isinstance(config, dict) else {}
    sheet_id = _sheet_id(settings)
    if not sheet_id or not _access_token(settings):
        return {
            "success": False,
            "skipped": True,
            "reason": "smartsheet_config_missing",
            "project_wbs": wbs_data,
        }

    mapping = dict(DEFAULT_MAPPING)
    configured_map = settings.get("field_mapping") if isinstance(settings.get("field_mapping"), dict) else {}
    for source_field, column_name in configured_map.items():
        source = _text(source_field)
        target = _text(column_name)
        if source in mapping and target:
            mapping[source] = target

    sheet_response = _request(settings, "GET", f"2.0/sheets/{sheet_id}")
    sheet_payload = sheet_response.get("data") if isinstance(sheet_response.get("data"), dict) else {}
    column_map = _column_index(sheet_payload)

    updated_wbs = copy.deepcopy(wbs_data) if isinstance(wbs_data, dict) else {"name": "Execution WBS", "tasks": []}
    tasks = _task_list(updated_wbs)
    created = 0
    updated = 0
    errors = []
    max_attempt_count = int(sheet_response.get("attempt_count") or 1)

    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_id = _text(task.get("id"))
        if not task_id:
            continue

        refs = task.get("external_refs") if isinstance(task.get("external_refs"), dict) else {}
        row_id = _text(refs.get("smartsheet_row_id") or task.get("smartsheet_row_id"))
        row_payload = {
            "toBottom": True,
            "cells": _cells_for_task(task, column_map, mapping, thread_id),
        }

        try:
            if row_id:
                row_payload["id"] = int(row_id) if row_id.isdigit() else row_id
                result = _request(settings, "PUT", f"2.0/sheets/{sheet_id}/rows", body=[row_payload])
                updated += 1
            else:
                result = _request(settings, "POST", f"2.0/sheets/{sheet_id}/rows", body=[row_payload])
                new_row_id = _find_row_id(result)
                if new_row_id:
                    refs["smartsheet_row_id"] = new_row_id
                    task["external_refs"] = refs
                    created += 1
                    updated += 1
            max_attempt_count = max(max_attempt_count, int(result.get("attempt_count") or 1))
        except Exception as exc:
            errors.append({"task_id": task_id, "error": str(exc)[:800]})

    updated_wbs["updated_at"] = _iso_now()
    return {
        "success": len(errors) == 0,
        "skipped": False,
        "created_rows": created,
        "updated_tasks": updated,
        "errors": errors,
        "attempt_count": max_attempt_count,
        "duration_ms": 0,
        "project_wbs": updated_wbs,
    }


def _row_cells_by_name(row, columns):
    by_id = {}
    for column in columns:
        record = column if isinstance(column, dict) else {}
        col_id = record.get("id")
        if col_id is not None:
            by_id[str(col_id)] = _text(record.get("title"))

    values = {}
    cells = row.get("cells") if isinstance(row.get("cells"), list) else []
    for cell in cells:
        item = cell if isinstance(cell, dict) else {}
        column_id = _text(item.get("columnId"))
        title = by_id.get(column_id) or _text(item.get("columnName"))
        if not title:
            continue
        cell_value = item.get("displayValue")
        if cell_value is None:
            cell_value = item.get("value")
        values[title] = cell_value
    return values


def _parse_jaspen_metadata(value):
    text = _text(value)
    parts = [chunk for chunk in text.split(";") if chunk]
    metadata = {}
    for chunk in parts:
        if "=" not in chunk:
            continue
        key, raw_value = chunk.split("=", 1)
        metadata[_text(key)] = _text(raw_value)
    return metadata


def smartsheet_import_tasks(config):
    settings = config if isinstance(config, dict) else {}
    sheet_id = _sheet_id(settings)
    if not sheet_id or not _access_token(settings):
        raise RuntimeError("Smartsheet import requires sheet_id and access token.")

    response = _request(settings, "GET", f"2.0/sheets/{sheet_id}", params={"pageSize": 500})
    sheet = response.get("data") if isinstance(response.get("data"), dict) else {}
    columns = sheet.get("columns") if isinstance(sheet.get("columns"), list) else []
    rows = sheet.get("rows") if isinstance(sheet.get("rows"), list) else []

    tasks = []
    for row in rows:
        item = row if isinstance(row, dict) else {}
        cell_map = _row_cells_by_name(item, columns)
        metadata = _parse_jaspen_metadata(cell_map.get("Jaspen Metadata"))
        tasks.append(
            {
                "external_id": _text(item.get("id")),
                "title": _text(cell_map.get("Task Name")),
                "status": _text(cell_map.get("Status")),
                "owner": _text(cell_map.get("Assigned To")),
                "due_date": _text(cell_map.get("Due Date")) or None,
                "thread_id": _text(metadata.get("thread")),
                "task_id": _text(metadata.get("task")),
                "raw": item,
            }
        )
    return {
        "success": True,
        "tasks": tasks,
        "count": len(tasks),
        "attempt_count": int(response.get("attempt_count") or 1),
    }
