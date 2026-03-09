import json
import os
from copy import deepcopy
from datetime import datetime


CONNECTORS_DIR = "connectors_data"
SYNC_MODES = ("import", "push", "two_way")
CONFLICT_POLICIES = ("latest_wins", "prefer_external", "prefer_jaspen", "manual_review")


def _iso_now():
    return datetime.utcnow().isoformat()


def _ensure_connectors_dir():
    if not os.path.exists(CONNECTORS_DIR):
        os.makedirs(CONNECTORS_DIR)


def _connector_file(user_id):
    _ensure_connectors_dir()
    return os.path.join(CONNECTORS_DIR, f"user_{user_id}_connectors.json")


def _default_state():
    return {
        "connectors": {},
        "thread_sync": {},
    }


def _default_connector_settings(connector_id):
    return {
        "connector_id": connector_id,
        "connection_status": "disconnected",
        "sync_mode": "import",
        "conflict_policy": "prefer_external",
        "auto_sync": True,
        "external_workspace": "",
        "jira_base_url": "",
        "jira_project_key": "",
        "jira_email": "",
        "jira_api_token": "",
        "jira_issue_type": "",
        "jira_field_mapping": {},
        "last_sync_at": None,
        "updated_at": None,
    }


def _default_thread_sync_profile(thread_id):
    return {
        "thread_id": thread_id,
        "connector_ids": [],
        "sync_mode": "import",
        "conflict_policy": "prefer_external",
        "field_mapping": {
            "summary": "title",
            "status": "status",
            "owner": "owner",
            "due_date": "due_date",
        },
        "mirror_external_to_wbs": True,
        "mirror_wbs_to_external": False,
        "auto_reconcile": True,
        "updated_at": None,
    }


def load_connector_state(user_id):
    path = _connector_file(user_id)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    data.setdefault("connectors", {})
                    data.setdefault("thread_sync", {})
                    if not isinstance(data["connectors"], dict):
                        data["connectors"] = {}
                    if not isinstance(data["thread_sync"], dict):
                        data["thread_sync"] = {}
                    return data
        except Exception as e:
            print(f"[connectors] load error for {user_id}: {e}")
    return _default_state()


def save_connector_state(user_id, data):
    path = _connector_file(user_id)
    try:
        with open(path, "w") as f:
            json.dump(data or _default_state(), f, indent=2)
        return True
    except Exception as e:
        print(f"[connectors] save error for {user_id}: {e}")
        return False


def get_connector_settings(user_id, connector_id):
    state = load_connector_state(user_id)
    connectors = state.get("connectors") or {}
    key = str(connector_id or "").strip().lower()
    current = connectors.get(key)
    base = _default_connector_settings(key)
    if isinstance(current, dict):
        base.update(current)
    return base


def get_all_connector_settings(user_id):
    state = load_connector_state(user_id)
    raw = state.get("connectors") or {}
    result = {}
    for key, value in raw.items():
        connector_id = str(key or "").strip().lower()
        merged = _default_connector_settings(connector_id)
        if isinstance(value, dict):
            merged.update(value)
        result[connector_id] = merged
    return result


def update_connector_settings(user_id, connector_id, updates):
    state = load_connector_state(user_id)
    connectors = state.setdefault("connectors", {})
    key = str(connector_id or "").strip().lower()
    current = get_connector_settings(user_id, key)
    if isinstance(updates, dict):
        for field in (
            "connection_status",
            "sync_mode",
            "conflict_policy",
            "auto_sync",
            "external_workspace",
            "jira_base_url",
            "jira_project_key",
            "jira_email",
            "jira_api_token",
            "jira_issue_type",
            "jira_field_mapping",
            "last_sync_at",
        ):
            if field in updates:
                current[field] = updates.get(field)
    current["updated_at"] = _iso_now()
    connectors[key] = current
    save_connector_state(user_id, state)
    return current


def get_thread_sync_profile(user_id, thread_id):
    state = load_connector_state(user_id)
    thread_sync = state.get("thread_sync") or {}
    key = str(thread_id or "").strip()
    current = thread_sync.get(key)
    base = _default_thread_sync_profile(key)
    if isinstance(current, dict):
        base.update(current)
    return base


def update_thread_sync_profile(user_id, thread_id, updates):
    state = load_connector_state(user_id)
    thread_sync = state.setdefault("thread_sync", {})
    key = str(thread_id or "").strip()
    current = get_thread_sync_profile(user_id, key)
    if isinstance(updates, dict):
        for field in (
            "connector_ids",
            "sync_mode",
            "conflict_policy",
            "field_mapping",
            "mirror_external_to_wbs",
            "mirror_wbs_to_external",
            "auto_reconcile",
        ):
            if field in updates:
                current[field] = updates.get(field)
    current["thread_id"] = key
    current["updated_at"] = _iso_now()
    thread_sync[key] = current
    save_connector_state(user_id, state)
    return deepcopy(current)
