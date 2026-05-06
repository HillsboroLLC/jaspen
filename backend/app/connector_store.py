import base64
import hashlib
import json
import os
import secrets
import time
from copy import deepcopy
from datetime import datetime, timedelta

import requests

try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception:  # pragma: no cover - optional import guard for constrained envs
    Fernet = None
    InvalidToken = Exception


_CONNECTORS_DIR_ENV = str(os.getenv("CONNECTORS_DATA_DIR") or "").strip()
_DEFAULT_CONNECTORS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "connectors_data"))
_LEGACY_CONNECTORS_DIR = os.path.abspath("connectors_data")
if _CONNECTORS_DIR_ENV:
    CONNECTORS_DIR = os.path.abspath(os.path.expanduser(_CONNECTORS_DIR_ENV))
elif os.path.isdir(_DEFAULT_CONNECTORS_DIR) or not os.path.isdir(_LEGACY_CONNECTORS_DIR):
    CONNECTORS_DIR = _DEFAULT_CONNECTORS_DIR
else:
    # Preserve existing deployments that wrote connector files relative to cwd.
    CONNECTORS_DIR = _LEGACY_CONNECTORS_DIR
SYNC_MODES = ("import", "push", "two_way")
CONFLICT_POLICIES = ("latest_wins", "prefer_external", "prefer_jaspen", "manual_review")
AUDIT_LOG_LIMIT = 500
DEFAULT_AUDIT_LIMIT = 100
MAX_AUDIT_LIMIT = 500
_SECRET_PREFIX = "enc::"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# Per-connector credential fields that must never be stored in plain text.
SENSITIVE_CONNECTOR_FIELDS = {
    "jira_sync": ("jira_api_token",),
    "smartsheet_sync": ("smartsheet_api_token",),
    "salesforce_insights": ("salesforce_client_secret", "salesforce_refresh_token", "salesforce_access_token"),
    "snowflake_insights": ("snowflake_password", "snowflake_private_key"),
    "oracle_fusion_insights": ("oracle_fusion_password",),
    "servicenow_insights": ("servicenow_password",),
    "netsuite_insights": ("netsuite_consumer_secret", "netsuite_token_secret"),
}
EXECUTION_PM_CONNECTOR_IDS = {"jira_sync", "smartsheet_sync"}
THREAD_SYNC_STATUS_VALUES = {
    "not_started",
    "tool_selected",
    "wbs_pending",
    "ready",
    "syncing",
    "synced",
    "error",
    "paused",
    "degraded",
}
CONNECTOR_REQUIRED_FIELDS = {
    "jira_sync": ("jira_base_url", "jira_project_key", "jira_email", "jira_api_token"),
    "smartsheet_sync": ("smartsheet_base_url", "smartsheet_sheet_id", "smartsheet_api_token"),
    "salesforce_insights": ("salesforce_auth_base_url", "salesforce_client_id", "salesforce_client_secret"),
    "snowflake_insights": ("snowflake_account", "snowflake_warehouse", "snowflake_database", "snowflake_schema", "snowflake_role", "snowflake_user"),
    "oracle_fusion_insights": ("oracle_fusion_base_url", "oracle_fusion_username", "oracle_fusion_password"),
    "servicenow_insights": ("servicenow_instance_url", "servicenow_username", "servicenow_password"),
    "netsuite_insights": ("netsuite_account_id", "netsuite_consumer_key", "netsuite_consumer_secret", "netsuite_token_id", "netsuite_token_secret"),
}


def _iso_now():
    return datetime.utcnow().isoformat()


def _parse_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def _ensure_connectors_dir():
    if not os.path.exists(CONNECTORS_DIR):
        os.makedirs(CONNECTORS_DIR, exist_ok=True)


def _connector_file(user_id):
    _ensure_connectors_dir()
    return os.path.join(CONNECTORS_DIR, f"user_{user_id}_connectors.json")


def _default_state():
    return {
        "connectors": {},
        "thread_sync": {},
        "audit_log": [],
    }


def _default_connector_settings(connector_id):
    return {
        "connector_id": connector_id,
        "connection_status": "disconnected",
        "lifecycle_status": "disconnected",
        "sync_mode": "import",
        "conflict_policy": "prefer_external",
        "auto_sync": True,
        "external_workspace": "",
        "last_verified_at": None,
        "verified_instance_url": "",

        # Common runtime and reliability metadata
        "last_sync_at": None,
        "last_sync_result": "never",
        "health_status": "unknown",
        "consecutive_failures": 0,
        "next_retry_at": None,
        "last_success_at": None,
        "last_error_at": None,
        "last_error_message": "",
        "updated_at": None,

        # Jira
        "jira_base_url": "",
        "jira_project_key": "",
        "jira_email": "",
        "jira_api_token": "",
        "jira_issue_type": "",
        "jira_field_mapping": {},

        # Smartsheet
        "smartsheet_base_url": "",
        "smartsheet_sheet_id": "",
        "smartsheet_api_token": "",
        "smartsheet_field_mapping": {},

        # Salesforce (enterprise data)
        "salesforce_auth_base_url": "",
        "salesforce_instance_url": "",
        "salesforce_client_id": "",
        "salesforce_client_secret": "",
        "salesforce_refresh_token": "",
        "salesforce_access_token": "",
        "salesforce_token_type": "",
        "salesforce_token_expires_at": None,

        # Snowflake (enterprise data)
        "snowflake_account": "",
        "snowflake_warehouse": "",
        "snowflake_database": "",
        "snowflake_schema": "",
        "snowflake_role": "",
        "snowflake_user": "",
        "snowflake_password": "",
        "snowflake_private_key": "",
        "snowflake_table_allowlist": [],

        # Oracle Fusion (enterprise data)
        "oracle_fusion_base_url": "",
        "oracle_fusion_username": "",
        "oracle_fusion_password": "",
        "oracle_fusion_business_unit": "",

        # ServiceNow (enterprise data)
        "servicenow_instance_url": "",
        "servicenow_username": "",
        "servicenow_password": "",
        "servicenow_table_allowlist": [],

        # NetSuite (enterprise data)
        "netsuite_account_id": "",
        "netsuite_consumer_key": "",
        "netsuite_consumer_secret": "",
        "netsuite_token_id": "",
        "netsuite_token_secret": "",
        "netsuite_rest_base_url": "",
    }


def _default_thread_sync_profile(thread_id):
    return {
        "thread_id": thread_id,
        "connector_ids": [],
        "preferred_pm_tool": None,
        "pm_tool_bound_at": None,
        "thread_sync_status": "not_started",
        "wbs_task_external_ids": {},
        "last_full_sync_at": None,
        "last_webhook_received_at": None,
        "sync_lock_acquired_at": None,
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
        "auto_sync": True,
        "updated_at": None,
    }


def _connector_has_complete_credentials(connector_id, settings):
    key = str(connector_id or "").strip().lower()
    settings = settings if isinstance(settings, dict) else {}
    required = CONNECTOR_REQUIRED_FIELDS.get(key, ())
    for field in required:
        if not str(settings.get(field) or "").strip():
            return False
    if key == "snowflake_insights":
        has_password = bool(str(settings.get("snowflake_password") or "").strip())
        has_private_key = bool(str(settings.get("snowflake_private_key") or "").strip())
        if not has_password and not has_private_key:
            return False
    if key == "salesforce_insights":
        has_secret = bool(str(settings.get("salesforce_client_secret") or "").strip())
        has_refresh = bool(str(settings.get("salesforce_refresh_token") or "").strip())
        has_access = bool(str(settings.get("salesforce_access_token") or "").strip())
        if not has_secret and not has_refresh and not has_access:
            return False
    return True


def _derive_connector_ids_from_preferred_tool(preferred_pm_tool):
    preferred = str(preferred_pm_tool or "").strip().lower()
    if preferred and preferred != "jaspen":
        return [preferred]
    return []


def _normalize_thread_sync_status(value, default="not_started"):
    status = str(value or "").strip().lower()
    if status in THREAD_SYNC_STATUS_VALUES:
        return status
    return default


def _wbs_exists(project_wbs):
    if not isinstance(project_wbs, dict):
        return False
    tasks = project_wbs.get("tasks")
    if isinstance(tasks, list) and tasks:
        return True
    name = str(project_wbs.get("name") or "").strip()
    return bool(name and name.lower() != "execution wbs")


def _compute_connector_lifecycle_status(connector_id, settings):
    settings = settings if isinstance(settings, dict) else {}
    connection_status = str(settings.get("connection_status") or "").strip().lower()
    lifecycle_status = str(settings.get("lifecycle_status") or "").strip().lower()
    failure_count = _parse_int(settings.get("consecutive_failures"), default=0)

    if lifecycle_status in {"disconnected", "configured", "verifying", "connected", "degraded"}:
        if lifecycle_status == "connected" and failure_count >= 3:
            return "degraded"
        if lifecycle_status == "disconnected" and connection_status == "connected":
            return "connected"
        return lifecycle_status

    has_credentials = _connector_has_complete_credentials(connector_id, settings)
    if failure_count >= 3:
        return "degraded"
    if connection_status == "connected":
        return "connected"
    if has_credentials:
        return "configured"
    return "disconnected"


def _compute_thread_sync_status(profile, connector_settings=None, project_wbs=None):
    profile = profile if isinstance(profile, dict) else {}
    connector_settings = connector_settings if isinstance(connector_settings, dict) else {}
    preferred = str(profile.get("preferred_pm_tool") or "").strip().lower()
    stored = _normalize_thread_sync_status(profile.get("thread_sync_status"), default="not_started")

    if not preferred or preferred == "jaspen":
        return "not_started"
    if preferred not in EXECUTION_PM_CONNECTOR_IDS:
        return "not_started"
    if not _wbs_exists(project_wbs):
        return "wbs_pending"

    lifecycle = _compute_connector_lifecycle_status(preferred, connector_settings)
    if lifecycle != "connected":
        return "degraded"

    if stored in {"syncing", "synced", "error", "paused"}:
        return stored
    if stored == "tool_selected":
        return "ready"
    return "ready"


def get_thread_sync_status(profile, connector_settings=None, project_wbs=None):
    return _compute_thread_sync_status(profile, connector_settings=connector_settings, project_wbs=project_wbs)


def _sensitive_fields_for(connector_id):
    key = str(connector_id or "").strip().lower()
    sensitive_fields = set(SENSITIVE_CONNECTOR_FIELDS.get(key, ()))
    defaults = _default_connector_settings(key)
    for field_name in defaults.keys():
        if str(field_name).strip().endswith("_api_token"):
            sensitive_fields.add(field_name)
    return sensitive_fields


def _derive_fernet_key(secret_material):
    text = str(secret_material or "").strip()
    if not text:
        return None
    try:
        raw = text.encode("utf-8")
        if len(raw) == 44:
            Fernet(raw)
            return raw
    except Exception:
        pass
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _build_cipher_candidates():
    if Fernet is None:
        return []

    legacy_secrets = []
    legacy_raw = os.getenv("CONNECTOR_ENCRYPTION_OLD_KEYS")
    if legacy_raw:
        try:
            parsed = json.loads(legacy_raw)
            if isinstance(parsed, list):
                legacy_secrets.extend([str(item or "").strip() for item in parsed if str(item or "").strip()])
        except Exception:
            legacy_secrets.extend([part.strip() for part in legacy_raw.split(",") if part.strip()])

    candidate_secrets = [
        os.getenv("CONNECTOR_ENCRYPTION_KEY"),
        os.getenv("CONNECTOR_CREDENTIALS_SECRET"),
        os.getenv("JWT_SECRET_KEY"),
        os.getenv("SECRET_KEY"),
        *legacy_secrets,
    ]
    seen_keys = set()
    ciphers = []
    for secret_material in candidate_secrets:
        key = _derive_fernet_key(secret_material)
        if not key:
            continue
        key_text = key.decode("utf-8")
        if key_text in seen_keys:
            continue
        seen_keys.add(key_text)
        try:
            ciphers.append(Fernet(key))
        except Exception:
            continue
    return ciphers


def _current_key_version():
    return str(os.getenv("CONNECTOR_ENCRYPTION_KEY_VERSION") or "v1").strip() or "v1"


def _split_encrypted_payload(value):
    text = str(value or "")
    if not text.startswith(_SECRET_PREFIX):
        return None, None
    body = text[len(_SECRET_PREFIX):]
    if "::" in body:
        version, token = body.split("::", 1)
        return (str(version or "").strip() or None), token
    return None, body


def _build_cipher():
    ciphers = _build_cipher_candidates()
    return ciphers[0] if ciphers else None


def encrypt_token(value):
    text = str(value or "")
    if not text:
        return ""
    if text.startswith(_SECRET_PREFIX):
        return text
    cipher = _build_cipher()
    if not cipher:
        # Fallback is plain text if no secret key is configured. This avoids breaking
        # runtime behavior while still allowing secure-at-rest in configured envs.
        return text
    token = cipher.encrypt(text.encode("utf-8")).decode("utf-8")
    return f"{_SECRET_PREFIX}{_current_key_version()}::{token}"


def decrypt_token(value):
    text = str(value or "")
    if not text:
        return ""
    if not text.startswith(_SECRET_PREFIX):
        return text
    ciphers = _build_cipher_candidates()
    if not ciphers:
        return ""
    _version, token = _split_encrypted_payload(text)
    for cipher in ciphers:
        try:
            return cipher.decrypt(token.encode("utf-8")).decode("utf-8")
        except (InvalidToken, ValueError):
            continue
    return ""


def _encrypt_secret(value):
    return encrypt_token(value)


def _decrypt_secret(value):
    return decrypt_token(value)


def _hydrate_connector_settings(connector_id, current):
    base = _default_connector_settings(connector_id)
    if isinstance(current, dict):
        base.update(current)
    base["lifecycle_status"] = _compute_connector_lifecycle_status(connector_id, base)
    for secret_field in _sensitive_fields_for(connector_id):
        if secret_field in base:
            base[secret_field] = decrypt_token(base.get(secret_field))
    return base


def _persist_connector_settings(connector_id, current):
    prepared = dict(current or {})
    for secret_field in _sensitive_fields_for(connector_id):
        if secret_field in prepared:
            prepared[secret_field] = encrypt_token(prepared.get(secret_field))
    return prepared


def connector_api_call(method, url, headers=None, body=None, max_retries=3, timeout=20, params=None, auth=None):
    last_error = None
    retry_count = max(0, _parse_int(max_retries, default=3))

    for attempt in range(0, retry_count + 1):
        try:
            response = requests.request(
                method=str(method or "GET").upper(),
                url=url,
                headers=headers,
                json=body,
                params=params,
                auth=auth,
                timeout=timeout,
            )
            status_code = int(response.status_code or 0)
            should_retry = status_code in RETRYABLE_STATUS_CODES and attempt < retry_count
            if should_retry:
                time.sleep(2 ** attempt)
                continue

            payload = {}
            if response.text:
                try:
                    payload = response.json()
                except Exception:
                    payload = {"raw": response.text}

            if status_code >= 400:
                raise RuntimeError(f"HTTP {status_code}: {payload or response.text}")

            return {
                "status_code": status_code,
                "data": payload if isinstance(payload, dict) else {"items": payload},
                "attempt_count": attempt + 1,
            }
        except requests.RequestException as exc:
            last_error = exc
            if attempt < retry_count:
                time.sleep(2 ** attempt)
                continue
            break
        except Exception as exc:
            last_error = exc
            if attempt < retry_count:
                time.sleep(2 ** attempt)
                continue
            break

    raise RuntimeError(f"Connector API call failed for {url}: {last_error}")


def load_connector_state(user_id):
    path = _connector_file(user_id)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    data.setdefault("connectors", {})
                    data.setdefault("thread_sync", {})
                    data.setdefault("audit_log", [])
                    if not isinstance(data["connectors"], dict):
                        data["connectors"] = {}
                    if not isinstance(data["thread_sync"], dict):
                        data["thread_sync"] = {}
                    if not isinstance(data["audit_log"], list):
                        data["audit_log"] = []
                    return data
        except Exception as e:
            print(f"[connectors] load error for {user_id}: {e}")
    return _default_state()


def save_connector_state(user_id, data):
    path = _connector_file(user_id)
    payload = data if isinstance(data, dict) else _default_state()
    try:
        with open(path, "w") as f:
            json.dump(payload, f, indent=2)
        return True
    except Exception as e:
        print(f"[connectors] save error for {user_id}: {e}")
        return False


def _upgrade_connector_secret_storage(state, connector_id):
    connectors = state.get("connectors") if isinstance(state.get("connectors"), dict) else {}
    key = str(connector_id or "").strip().lower()
    current = connectors.get(key)
    if not isinstance(current, dict):
        return False
    if not _build_cipher():
        return False
    prepared = _persist_connector_settings(key, current)
    if prepared == current:
        return False
    connectors[key] = prepared
    state["connectors"] = connectors
    return True


def get_connector_settings(user_id, connector_id):
    state = load_connector_state(user_id)
    connectors = state.get("connectors") or {}
    key = str(connector_id or "").strip().lower()
    if _upgrade_connector_secret_storage(state, key):
        save_connector_state(user_id, state)
        connectors = state.get("connectors") or {}
    current = connectors.get(key)
    return _hydrate_connector_settings(key, current)


def get_all_connector_settings(user_id):
    state = load_connector_state(user_id)
    raw = state.get("connectors") or {}
    changed = False
    result = {}
    for key in list(raw.keys()):
        connector_id = str(key or "").strip().lower()
        changed = _upgrade_connector_secret_storage(state, connector_id) or changed
    if changed:
        save_connector_state(user_id, state)
        raw = state.get("connectors") or {}

    for key, value in raw.items():
        connector_id = str(key or "").strip().lower()
        result[connector_id] = _hydrate_connector_settings(connector_id, value)
    return result


def load_user_connectors(user_id):
    state = load_connector_state(user_id)
    return {
        "connectors": get_all_connector_settings(user_id),
        "thread_sync": state.get("thread_sync") if isinstance(state.get("thread_sync"), dict) else {},
        "audit_log": state.get("audit_log") if isinstance(state.get("audit_log"), list) else [],
    }


def redact_connector_settings(settings, connector_id=None):
    connector_id = str(connector_id or settings.get("connector_id") or "").strip().lower()
    secret_fields = _sensitive_fields_for(connector_id)
    redacted = deepcopy(settings if isinstance(settings, dict) else {})
    for field in secret_fields:
        has_key = bool(str(redacted.get(field) or "").strip())
        redacted[field] = ""
        redacted[f"has_{field}"] = has_key
    return redacted


def update_connector_settings(user_id, connector_id, updates):
    state = load_connector_state(user_id)
    connectors = state.setdefault("connectors", {})
    key = str(connector_id or "").strip().lower()
    current_raw = connectors.get(key)
    current = _hydrate_connector_settings(key, current_raw)

    if isinstance(updates, dict):
        for field, value in updates.items():
            current[field] = value
    previous_lifecycle = _compute_connector_lifecycle_status(key, current)

    current["connector_id"] = key
    connection_status = str(current.get("connection_status") or "").strip().lower()
    if connection_status == "connected":
        current["last_verified_at"] = _iso_now()
    if connection_status == "disconnected":
        current["last_verified_at"] = current.get("last_verified_at")

    current["lifecycle_status"] = _compute_connector_lifecycle_status(key, current)
    if previous_lifecycle == "connected" and connection_status == "disconnected":
        current["lifecycle_status"] = "disconnected"
    current["updated_at"] = _iso_now()
    connectors[key] = _persist_connector_settings(key, current)
    save_connector_state(user_id, state)
    return get_connector_settings(user_id, key)


def _next_retry_at(failure_count):
    retries = max(1, _parse_int(failure_count, default=1))
    delay_seconds = min(900, 15 * (2 ** min(retries - 1, 5)))
    return (datetime.utcnow() + timedelta(seconds=delay_seconds)).isoformat()


def mark_connector_sync_result(user_id, connector_id, status, error_message=""):
    now_iso = _iso_now()
    status_key = str(status or "").strip().lower()
    settings = get_connector_settings(user_id, connector_id)
    failure_count = _parse_int(settings.get("consecutive_failures"), default=0)

    if status_key == "success":
        updates = {
            "last_sync_at": now_iso,
            "last_sync_result": "success",
            "health_status": "healthy",
            "connection_status": "connected",
            "consecutive_failures": 0,
            "next_retry_at": None,
            "last_success_at": now_iso,
            "last_error_message": "",
            "last_verified_at": now_iso,
            "lifecycle_status": "connected",
        }
    elif status_key == "skipped":
        updates = {
            "last_sync_at": now_iso,
            "last_sync_result": "skipped",
            "health_status": settings.get("health_status") or "unknown",
            "next_retry_at": settings.get("next_retry_at"),
        }
    else:
        next_failures = failure_count + 1
        updates = {
            "last_sync_at": now_iso,
            "last_sync_result": "failed",
            "health_status": "degraded",
            "consecutive_failures": next_failures,
            "next_retry_at": _next_retry_at(next_failures),
            "last_error_at": now_iso,
            "last_error_message": str(error_message or "")[:1000],
            "lifecycle_status": "degraded" if next_failures >= 3 else settings.get("lifecycle_status") or "configured",
        }

    if status_key != "failed":
        updates.setdefault("last_error_at", settings.get("last_error_at"))

    return update_connector_settings(user_id, connector_id, updates)


def _sanitize_limit(limit):
    value = _parse_int(limit, default=DEFAULT_AUDIT_LIMIT)
    if value < 1:
        return DEFAULT_AUDIT_LIMIT
    return min(value, MAX_AUDIT_LIMIT)


def append_sync_audit_event(
    user_id,
    connector_id,
    action,
    status,
    thread_id=None,
    attempt_count=None,
    duration_ms=None,
    message="",
    metadata=None,
):
    state = load_connector_state(user_id)
    log = state.setdefault("audit_log", [])
    if not isinstance(log, list):
        log = []

    entry = {
        "id": f"audit_{secrets.token_hex(6)}",
        "timestamp": _iso_now(),
        "connector_id": str(connector_id or "").strip().lower(),
        "thread_id": str(thread_id or "").strip() or None,
        "action": str(action or "sync").strip().lower() or "sync",
        "status": str(status or "unknown").strip().lower() or "unknown",
        "attempt_count": _parse_int(attempt_count, default=0) if attempt_count is not None else None,
        "duration_ms": _parse_int(duration_ms, default=0) if duration_ms is not None else None,
        "message": str(message or "")[:1000],
        "metadata": metadata if isinstance(metadata, dict) else {},
    }
    log.insert(0, entry)
    state["audit_log"] = log[:AUDIT_LOG_LIMIT]
    save_connector_state(user_id, state)
    _persist_connector_sync_log(
        user_id=user_id,
        connector_id=entry.get("connector_id"),
        thread_id=entry.get("thread_id"),
        action=entry.get("action"),
        status=_normalize_sync_log_status(entry.get("status")),
        items_synced=_extract_items_synced(entry.get("metadata")),
        error_message=(entry.get("message") or "") if str(entry.get("status") or "").lower() in {"failed", "partial", "skipped"} else "",
    )
    return entry


def get_sync_audit_events(user_id, connector_id=None, thread_id=None, limit=DEFAULT_AUDIT_LIMIT):
    state = load_connector_state(user_id)
    log = state.get("audit_log") if isinstance(state.get("audit_log"), list) else []
    target_connector = str(connector_id or "").strip().lower()
    target_thread = str(thread_id or "").strip()
    rows = []

    for item in log:
        if not isinstance(item, dict):
            continue
        if target_connector and str(item.get("connector_id") or "").strip().lower() != target_connector:
            continue
        if target_thread and str(item.get("thread_id") or "").strip() != target_thread:
            continue
        rows.append(deepcopy(item))

    return rows[:_sanitize_limit(limit)]


def _normalize_sync_log_status(status):
    value = str(status or "").strip().lower()
    if value == "success":
        return "success"
    if value in {"failed", "error"}:
        return "failed"
    return "partial"


def _extract_items_synced(metadata):
    if not isinstance(metadata, dict):
        return 0
    if "items_synced" in metadata:
        return max(0, _parse_int(metadata.get("items_synced"), default=0))
    total = 0
    for key in ("created", "updated", "imported", "synced"):
        total += max(0, _parse_int(metadata.get(key), default=0))
    return total


def _persist_connector_sync_log(
    *,
    user_id,
    connector_id,
    thread_id,
    action,
    status,
    items_synced=0,
    error_message="",
):
    try:
        from app import db
        from app.models import ConnectorSyncLog

        record = ConnectorSyncLog(
            user_id=str(user_id),
            connector_id=str(connector_id or "").strip().lower(),
            thread_id=str(thread_id or "").strip() or None,
            action=str(action or "sync").strip().lower()[:100],
            status=str(status or "partial").strip().lower()[:50],
            items_synced=max(0, _parse_int(items_synced, default=0)),
            error_message=str(error_message or "")[:2000] or None,
        )
        db.session.add(record)
        db.session.commit()
    except Exception as exc:
        try:
            from app import db

            db.session.rollback()
        except Exception:
            pass
        print(f"[connectors] sync log write skipped: {exc}")


def get_thread_sync_profile(user_id, thread_id):
    state = load_connector_state(user_id)
    thread_sync = state.get("thread_sync") or {}
    key = str(thread_id or "").strip()
    current = thread_sync.get(key)
    base = _default_thread_sync_profile(key)
    if isinstance(current, dict):
        base.update(current)
    preferred = str(base.get("preferred_pm_tool") or "").strip().lower() or None
    if preferred == "jaspen":
        base["connector_ids"] = []
    elif preferred and preferred in EXECUTION_PM_CONNECTOR_IDS:
        base["connector_ids"] = [preferred]
    elif not isinstance(base.get("connector_ids"), list):
        base["connector_ids"] = []
    else:
        cleaned = []
        for connector_id in base.get("connector_ids") or []:
            token = str(connector_id or "").strip().lower()
            if token and token not in cleaned:
                cleaned.append(token)
        base["connector_ids"] = cleaned
    if not isinstance(base.get("wbs_task_external_ids"), dict):
        base["wbs_task_external_ids"] = {}
    base["thread_sync_status"] = _normalize_thread_sync_status(base.get("thread_sync_status"), default="not_started")
    return base


def get_all_thread_sync_profiles(user_id):
    state = load_connector_state(user_id)
    raw = state.get("thread_sync") if isinstance(state.get("thread_sync"), dict) else {}
    profiles = {}
    for key, value in raw.items():
        thread_id = str(key or "").strip()
        if not thread_id:
            continue
        base = _default_thread_sync_profile(thread_id)
        if isinstance(value, dict):
            base.update(value)
        preferred = str(base.get("preferred_pm_tool") or "").strip().lower()
        if preferred in EXECUTION_PM_CONNECTOR_IDS:
            base["connector_ids"] = [preferred]
        elif preferred == "jaspen" or not preferred:
            base["connector_ids"] = []
        if not isinstance(base.get("wbs_task_external_ids"), dict):
            base["wbs_task_external_ids"] = {}
        base["thread_sync_status"] = _normalize_thread_sync_status(base.get("thread_sync_status"), default="not_started")
        profiles[thread_id] = base
    return profiles


def update_thread_sync_profile(user_id, thread_id, updates):
    state = load_connector_state(user_id)
    thread_sync = state.setdefault("thread_sync", {})
    key = str(thread_id or "").strip()
    current = get_thread_sync_profile(user_id, key)
    if isinstance(updates, dict):
        for field in (
            "connector_ids",
            "preferred_pm_tool",
            "pm_tool_bound_at",
            "thread_sync_status",
            "last_full_sync_at",
            "last_webhook_received_at",
            "sync_lock_acquired_at",
            "sync_mode",
            "conflict_policy",
            "field_mapping",
            "mirror_external_to_wbs",
            "mirror_wbs_to_external",
            "auto_reconcile",
            "auto_sync",
        ):
            if field in updates:
                current[field] = updates.get(field)
        if "wbs_task_external_ids" in updates and isinstance(updates.get("wbs_task_external_ids"), dict):
            current["wbs_task_external_ids"] = updates.get("wbs_task_external_ids")
        if "wbs_task_external_ids_patch" in updates and isinstance(updates.get("wbs_task_external_ids_patch"), dict):
            merged = dict(current.get("wbs_task_external_ids") if isinstance(current.get("wbs_task_external_ids"), dict) else {})
            for task_id, external_id in updates.get("wbs_task_external_ids_patch", {}).items():
                task_key = str(task_id or "").strip()
                if not task_key:
                    continue
                ext_value = str(external_id or "").strip()
                if ext_value:
                    merged[task_key] = ext_value
                elif task_key in merged:
                    merged.pop(task_key, None)
            current["wbs_task_external_ids"] = merged
    preferred = str(current.get("preferred_pm_tool") or "").strip().lower()
    if preferred in EXECUTION_PM_CONNECTOR_IDS:
        current["connector_ids"] = [preferred]
    elif preferred == "jaspen" or not preferred:
        current["connector_ids"] = []
    else:
        current["preferred_pm_tool"] = None
        current["connector_ids"] = []
    current["thread_sync_status"] = _normalize_thread_sync_status(current.get("thread_sync_status"), default="not_started")
    current["thread_id"] = key
    current["updated_at"] = _iso_now()
    thread_sync[key] = current
    save_connector_state(user_id, state)
    return deepcopy(current)
