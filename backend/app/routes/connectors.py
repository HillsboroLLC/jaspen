import hmac
import json
import os
import threading
from datetime import datetime
from urllib.parse import urlencode

from flask import Blueprint, current_app, jsonify, redirect, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app import limiter
from app.admin_audit import append_user_audit_event
from app.billing_config import to_public_plan
from app.connectors.smartsheet import smartsheet_connect, smartsheet_list_sheets
from app.connector_registry import (
    get_connector_catalog,
    get_connector_definition,
    get_execution_connector_ids,
)
from app.connector_store import (
    CONFLICT_POLICIES,
    EXECUTION_PM_CONNECTOR_IDS,
    SYNC_MODES,
    append_sync_audit_event,
    get_all_thread_sync_profiles,
    get_thread_sync_status,
    get_all_connector_settings,
    get_connector_settings,
    get_sync_audit_events,
    get_thread_sync_profile,
    mark_connector_sync_result,
    redact_connector_settings,
    update_connector_settings,
    update_thread_sync_profile,
)
from app.jira_sync import (
    apply_jira_webhook_to_wbs,
    fetch_jira_context_summary,
    import_tasks_from_jira,
    jira_check_connection,
    sync_wbs_to_jira,
)
from app.models import User
from app.scenarios_store import load_scenarios_data, save_scenarios_data
from app.salesforce_sync import (
    BadSignature as SalesforceBadSignature,
    SignatureExpired as SalesforceStateExpired,
    decode_salesforce_oauth_state,
    encode_salesforce_oauth_state,
    exchange_salesforce_code,
    fetch_pipeline_summary,
    generate_pkce_pair,
    probe_salesforce_connection,
    salesforce_authorize_url,
    salesforce_missing_oauth_config,
    salesforce_runtime_config,
)
from app.routes.strategy import get_llm_client
from app.smartsheet_sync import apply_smartsheet_webhook_to_wbs, import_tasks_from_smartsheet, sync_wbs_to_smartsheet
from app.snowflake_insights import extract_kpi_metrics, run_allowlisted_query, test_snowflake_connection
from app.tool_registry import get_tool_entitlements


connectors_bp = Blueprint("connectors", __name__)


def _audit_connector_event(action, *, user=None, user_id=None, details=None):
    append_user_audit_event(
        actor_user=user,
        actor_user_id=getattr(user, "id", None) if user is not None else user_id,
        actor_email=getattr(user, "email", None) if user is not None else None,
        action=action,
        target_user_id=getattr(user, "id", None) if user is not None else user_id,
        target_email=getattr(user, "email", None) if user is not None else None,
        details=details if isinstance(details, dict) else {},
    )


def _normalize_sync_mode(value):
    normalized = str(value or "").strip().lower()
    return normalized if normalized in SYNC_MODES else None



def _normalize_conflict_policy(value):
    normalized = str(value or "").strip().lower()
    return normalized if normalized in CONFLICT_POLICIES else None



def _to_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")



def _available_sync_modes(entitlement):
    if not entitlement or not entitlement.get("allowed_read"):
        return []
    if entitlement.get("allowed_write"):
        return ["import", "push", "two_way"]
    return ["import"]



def _text(value):
    return str(value or "").strip()


def _iso_now():
    return datetime.utcnow().isoformat()



def _frontend_base_url():
    return (current_app.config.get("FRONTEND_BASE_URL") or "http://localhost:3000").rstrip("/")


def _safe_next_path(candidate):
    path = str(candidate or "").strip()
    if not path or not path.startswith("/") or path.startswith("//"):
        return "/connectors-manage"
    return path


def _frontend_redirect(next_path, params=None):
    query = urlencode({k: v for k, v in (params or {}).items() if v is not None})
    safe_path = _safe_next_path(next_path)
    if query:
        separator = "&" if "?" in safe_path else "?"
        safe_path = f"{safe_path}{separator}{query}"
    return redirect(f"{_frontend_base_url()}{safe_path}", code=302)


def _salesforce_state_secret():
    return current_app.config.get("SECRET_KEY") or current_app.config.get("JWT_SECRET_KEY") or ""


def _salesforce_callback_url():
    explicit = _text(current_app.config.get("SALESFORCE_REDIRECT_URI") or os.getenv("SALESFORCE_REDIRECT_URI"))
    if explicit:
        return explicit

    # The OAuth callback MUST resolve to this backend (where the Flask route
    # lives), NOT the frontend host. Derive the base from the actual request
    # host so /oauth/start and /oauth/callback always agree and hit a real
    # route. (FRONTEND_BASE_URL points at the Vercel frontend, which has no
    # Flask route for the callback — using it silently breaks the flow.)
    try:
        host_base = _text(request.host_url).rstrip("/")
    except Exception:
        host_base = ""
    if host_base:
        host_base = host_base.replace("http://", "https://", 1) if host_base.startswith("http://") and "localhost" not in host_base and "127.0.0.1" not in host_base else host_base
        return f"{host_base}/api/v1/connectors/salesforce/oauth/callback"

    frontend_base = _frontend_base_url().replace("://www.", "://", 1)
    return f"{frontend_base.rstrip('/')}/api/v1/connectors/salesforce/oauth/callback"


def _salesforce_token_expires_at_iso(token_payload):
    if not isinstance(token_payload, dict):
        return None
    try:
        expires_in = int(token_payload.get("expires_in") or 0)
    except Exception:
        expires_in = 0
    if expires_in <= 0:
        return None
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) + timedelta(seconds=max(0, expires_in - 60))).isoformat()


def _safe_salesforce_oauth_error_reason(exc):
    message = str(exc or "").strip().lower()
    if "invalid_grant" in message or "expired authorization code" in message:
        return "authorization_code_invalid_or_expired"
    if "invalid_client" in message:
        return "client_configuration_invalid"
    if "access denied" in message:
        return "access_denied"
    if "timeout" in message:
        return "provider_timeout"
    return "oauth_exchange_failed"


def _safe_salesforce_oauth_error_code(raw_error):
    code = _text(raw_error).lower()
    allowed = {
        "access_denied": "oauth_access_denied",
        "invalid_scope": "oauth_invalid_scope",
        "invalid_request": "oauth_invalid_request",
        "server_error": "oauth_server_error",
        "temporarily_unavailable": "oauth_temporarily_unavailable",
    }
    return allowed.get(code, "oauth_failed")


def _runtime_fields(connector_id, settings):
    settings = settings if isinstance(settings, dict) else {}

    if connector_id == "jira_sync":
        return {
            "jira_base_url": _text(settings.get("jira_base_url") or os.getenv("JIRA_BASE_URL")),
            "jira_project_key": _text(
                settings.get("jira_project_key")
                or settings.get("external_workspace")
                or os.getenv("JIRA_DEFAULT_PROJECT_KEY")
            ),
            "jira_email": _text(settings.get("jira_email") or os.getenv("JIRA_EMAIL")),
            "jira_api_token": _text(settings.get("jira_api_token") or os.getenv("JIRA_API_TOKEN")),
        }

    if connector_id == "smartsheet_sync":
        return {
            "smartsheet_base_url": _text(
                settings.get("smartsheet_base_url")
                or os.getenv("SMARTSHEET_BASE_URL")
                or "https://api.smartsheet.com"
            ),
            "smartsheet_sheet_id": _text(
                settings.get("smartsheet_sheet_id")
                or settings.get("external_workspace")
                or os.getenv("SMARTSHEET_SHEET_ID")
            ),
            "smartsheet_api_token": _text(settings.get("smartsheet_api_token") or os.getenv("SMARTSHEET_API_TOKEN")),
        }

    if connector_id == "salesforce_insights":
        # Only client_id and client_secret are manually required for setup.
        # instance_url and refresh_token are populated automatically during OAuth
        # and must NOT be treated as missing/required before OAuth is completed.
        return {
            "salesforce_auth_base_url": _text(
                settings.get("salesforce_auth_base_url")
                or os.getenv("SALESFORCE_AUTH_BASE_URL")
                or "https://login.salesforce.com"
            ),
            "salesforce_client_id": _text(settings.get("salesforce_client_id") or os.getenv("SALESFORCE_CLIENT_ID")),
            "salesforce_client_secret": _text(settings.get("salesforce_client_secret") or os.getenv("SALESFORCE_CLIENT_SECRET")),
        }

    if connector_id == "snowflake_insights":
        return {
            "snowflake_account": _text(settings.get("snowflake_account") or os.getenv("SNOWFLAKE_ACCOUNT")),
            "snowflake_warehouse": _text(settings.get("snowflake_warehouse") or os.getenv("SNOWFLAKE_WAREHOUSE")),
            "snowflake_database": _text(settings.get("snowflake_database") or os.getenv("SNOWFLAKE_DATABASE")),
            "snowflake_schema": _text(settings.get("snowflake_schema") or os.getenv("SNOWFLAKE_SCHEMA")),
            "snowflake_role": _text(settings.get("snowflake_role") or os.getenv("SNOWFLAKE_ROLE")),
            "snowflake_user": _text(settings.get("snowflake_user") or os.getenv("SNOWFLAKE_USER")),
            "snowflake_password": _text(settings.get("snowflake_password") or os.getenv("SNOWFLAKE_PASSWORD")),
            "snowflake_private_key": _text(settings.get("snowflake_private_key") or os.getenv("SNOWFLAKE_PRIVATE_KEY")),
        }

    if connector_id == "oracle_fusion_insights":
        return {
            "oracle_fusion_base_url": _text(
                settings.get("oracle_fusion_base_url")
                or os.getenv("ORACLE_FUSION_BASE_URL")
            ),
            "oracle_fusion_username": _text(
                settings.get("oracle_fusion_username")
                or os.getenv("ORACLE_FUSION_USERNAME")
            ),
            "oracle_fusion_password": _text(
                settings.get("oracle_fusion_password")
                or os.getenv("ORACLE_FUSION_PASSWORD")
            ),
        }

    if connector_id == "servicenow_insights":
        return {
            "servicenow_instance_url": _text(
                settings.get("servicenow_instance_url")
                or os.getenv("SERVICENOW_INSTANCE_URL")
            ),
            "servicenow_username": _text(
                settings.get("servicenow_username")
                or os.getenv("SERVICENOW_USERNAME")
            ),
            "servicenow_password": _text(
                settings.get("servicenow_password")
                or os.getenv("SERVICENOW_PASSWORD")
            ),
        }

    if connector_id == "netsuite_insights":
        return {
            "netsuite_account_id": _text(
                settings.get("netsuite_account_id")
                or os.getenv("NETSUITE_ACCOUNT_ID")
            ),
            "netsuite_consumer_key": _text(
                settings.get("netsuite_consumer_key")
                or os.getenv("NETSUITE_CONSUMER_KEY")
            ),
            "netsuite_consumer_secret": _text(
                settings.get("netsuite_consumer_secret")
                or os.getenv("NETSUITE_CONSUMER_SECRET")
            ),
            "netsuite_token_id": _text(
                settings.get("netsuite_token_id")
                or os.getenv("NETSUITE_TOKEN_ID")
            ),
            "netsuite_token_secret": _text(
                settings.get("netsuite_token_secret")
                or os.getenv("NETSUITE_TOKEN_SECRET")
            ),
        }

    return {}



def _missing_required_fields(connector_id, settings):
    runtime = _runtime_fields(connector_id, settings)
    missing = [key for key, value in runtime.items() if not value]
    if connector_id == "snowflake_insights":
        # Snowflake auth supports password OR private key; either one satisfies setup.
        has_password = bool(_text(runtime.get("snowflake_password")))
        has_private_key = bool(_text(runtime.get("snowflake_private_key")))
        missing = [field for field in missing if field not in {"snowflake_password", "snowflake_private_key"}]
        if not has_password and not has_private_key:
            missing.append("snowflake_password_or_private_key")
    return missing



def _merge_connector_view(connector_id, entitlement, settings):
    meta = get_connector_definition(connector_id) or {"id": connector_id}
    required_min_tier = entitlement.get("required_min_tier")
    enabled = bool(entitlement.get("enabled"))
    modes = _available_sync_modes(entitlement)
    supports_push = "push" in modes
    supports_two_way = "two_way" in modes

    connection_status = str(settings.get("connection_status") or "disconnected").lower()
    if connection_status not in ("connected", "disconnected"):
        connection_status = "disconnected"

    connected = connection_status == "connected"
    # Salesforce OAuth may successfully return tokens before the explicit
    # connection_status flag is observed by a subsequent UI refresh. Treat a
    # valid token-bearing config as connected to avoid a false "disconnected"
    # badge after OAuth success.
    if not connected and connector_id == "salesforce_insights":
        has_oauth_token = bool(
            _text(settings.get("salesforce_refresh_token"))
            or _text(settings.get("salesforce_access_token"))
        )
        has_identity = bool(
            _text(settings.get("salesforce_client_id"))
            and _text(settings.get("salesforce_instance_url"))
        )
        if has_oauth_token and has_identity:
            connected = True
            connection_status = "connected"
    status = "locked" if not enabled else "connected" if connected else "available"
    sync_mode = str(settings.get("sync_mode") or "import").lower()
    if sync_mode not in modes:
        sync_mode = "import" if "import" in modes else None

    payload = {
        "id": connector_id,
        "label": meta.get("label") or connector_id,
        "group": meta.get("group") or "data",
        "description": meta.get("description") or entitlement.get("purpose") or "",
        "implementation_status": meta.get("implementation_status") or "implemented",
        "supports_pm_sync": bool(meta.get("supports_pm_sync")),
        "status": status,
        "enabled": enabled,
        "connected": connected,
        "connection_status": "connected" if connected else "disconnected",
        "lifecycle_status": settings.get("lifecycle_status") or ("connected" if connected else "disconnected"),
        "required_min_tier": required_min_tier,
        "access": entitlement.get("access"),
        "allowed_read": bool(entitlement.get("allowed_read")),
        "allowed_write": bool(entitlement.get("allowed_write")),
        "supports_push": supports_push,
        "supports_two_way": supports_two_way,
        "available_sync_modes": modes,
        "sync_mode": sync_mode,
        "conflict_policy": settings.get("conflict_policy") or "prefer_external",
        "available_conflict_policies": list(CONFLICT_POLICIES),
        "auto_sync": _to_bool(settings.get("auto_sync"), default=True),
        "external_workspace": settings.get("external_workspace") or "",
        "last_sync_at": settings.get("last_sync_at"),
        "last_sync_result": settings.get("last_sync_result") or "never",
        "updated_at": settings.get("updated_at"),
        "health": {
            "status": settings.get("health_status") or "unknown",
            "consecutive_failures": int(settings.get("consecutive_failures") or 0),
            "next_retry_at": settings.get("next_retry_at"),
            "last_success_at": settings.get("last_success_at"),
            "last_error_at": settings.get("last_error_at"),
            "last_error_message": settings.get("last_error_message") or "",
        },
    }

    if connector_id == "jira_sync":
        missing_fields = _missing_required_fields(connector_id, settings)
        payload["jira"] = {
            "base_url": settings.get("jira_base_url") or "",
            "project_key": settings.get("jira_project_key") or settings.get("external_workspace") or "",
            "email": settings.get("jira_email") or "",
            "issue_type": settings.get("jira_issue_type") or "",
            "has_api_token": bool(settings.get("jira_api_token")),
            "configuration_complete": len(missing_fields) == 0,
            "missing_required_fields": missing_fields,
            "field_mapping": settings.get("jira_field_mapping") if isinstance(settings.get("jira_field_mapping"), dict) else {},
        }
    elif connector_id == "smartsheet_sync":
        missing_fields = _missing_required_fields(connector_id, settings)
        payload["smartsheet"] = {
            "base_url": settings.get("smartsheet_base_url") or "",
            "sheet_id": settings.get("smartsheet_sheet_id") or settings.get("external_workspace") or "",
            "has_api_token": bool(settings.get("smartsheet_api_token")),
            "configuration_complete": len(missing_fields) == 0,
            "missing_required_fields": missing_fields,
            "field_mapping": settings.get("smartsheet_field_mapping") if isinstance(settings.get("smartsheet_field_mapping"), dict) else {},
        }
    elif connector_id == "salesforce_insights":
        missing_fields = _missing_required_fields(connector_id, settings)
        payload["salesforce"] = {
            "auth_base_url": settings.get("salesforce_auth_base_url") or "",
            "instance_url": settings.get("salesforce_instance_url") or "",
            "client_id": settings.get("salesforce_client_id") or "",
            "has_client_secret": bool(settings.get("salesforce_client_secret")),
            "has_refresh_token": bool(settings.get("salesforce_refresh_token")),
            "has_access_token": bool(settings.get("salesforce_access_token")),
            "configuration_complete": len(missing_fields) == 0,
            "missing_required_fields": missing_fields,
        }
    elif connector_id == "snowflake_insights":
        missing_fields = _missing_required_fields(connector_id, settings)
        payload["snowflake"] = {
            "account": settings.get("snowflake_account") or "",
            "warehouse": settings.get("snowflake_warehouse") or "",
            "database": settings.get("snowflake_database") or "",
            "schema": settings.get("snowflake_schema") or "",
            "role": settings.get("snowflake_role") or "",
            "user": settings.get("snowflake_user") or "",
            "has_password": bool(settings.get("snowflake_password")),
            "has_private_key": bool(settings.get("snowflake_private_key")),
            "table_allowlist": settings.get("snowflake_table_allowlist") if isinstance(settings.get("snowflake_table_allowlist"), list) else [],
            "configuration_complete": len(missing_fields) == 0,
            "missing_required_fields": missing_fields,
        }
    elif connector_id == "oracle_fusion_insights":
        missing_fields = _missing_required_fields(connector_id, settings)
        payload["oracle_fusion"] = {
            "base_url": settings.get("oracle_fusion_base_url") or "",
            "username": settings.get("oracle_fusion_username") or "",
            "has_password": bool(settings.get("oracle_fusion_password")),
            "business_unit": settings.get("oracle_fusion_business_unit") or "",
            "configuration_complete": len(missing_fields) == 0,
            "missing_required_fields": missing_fields,
        }
    elif connector_id == "servicenow_insights":
        missing_fields = _missing_required_fields(connector_id, settings)
        payload["servicenow"] = {
            "instance_url": settings.get("servicenow_instance_url") or "",
            "username": settings.get("servicenow_username") or "",
            "has_password": bool(settings.get("servicenow_password")),
            "table_allowlist": settings.get("servicenow_table_allowlist") if isinstance(settings.get("servicenow_table_allowlist"), list) else [],
            "configuration_complete": len(missing_fields) == 0,
            "missing_required_fields": missing_fields,
        }
    elif connector_id == "netsuite_insights":
        missing_fields = _missing_required_fields(connector_id, settings)
        payload["netsuite"] = {
            "account_id": settings.get("netsuite_account_id") or "",
            "consumer_key": settings.get("netsuite_consumer_key") or "",
            "has_consumer_secret": bool(settings.get("netsuite_consumer_secret")),
            "token_id": settings.get("netsuite_token_id") or "",
            "has_token_secret": bool(settings.get("netsuite_token_secret")),
            "rest_base_url": settings.get("netsuite_rest_base_url") or "",
            "configuration_complete": len(missing_fields) == 0,
            "missing_required_fields": missing_fields,
        }

    return payload



def _connector_views_for_user(user):
    plan_key = to_public_plan(user.subscription_plan)
    entitlements = get_tool_entitlements(plan_key)
    connector_entitlements = {
        item.get("id"): item
        for item in entitlements
        if str(item.get("type") or "").lower() == "connector"
    }
    connector_settings = get_all_connector_settings(user.id)

    views = []
    for connector in get_connector_catalog():
        connector_id = connector["id"]
        entitlement = connector_entitlements.get(connector_id) or {
            "id": connector_id,
            "type": "connector",
            "enabled": False,
            "allowed_read": False,
            "allowed_write": False,
            "required_min_tier": None,
            "access": "read",
            "purpose": connector.get("description"),
        }
        settings = connector_settings.get(connector_id) or get_connector_settings(user.id, connector_id)
        views.append(_merge_connector_view(connector_id, entitlement, settings))
    return plan_key, views



def _execution_connector_views(views):
    execution_ids = set(get_execution_connector_ids())
    return [view for view in views if view.get("id") in execution_ids]



def _coerce_allowlist(value):
    if isinstance(value, list):
        raw = value
    else:
        raw = str(value or "").split(",")
    cleaned = []
    for item in raw:
        token = _text(item)
        if token and token not in cleaned:
            cleaned.append(token)
    return cleaned



def _apply_field_update(updates, payload, persisted, field):
    if field in payload:
        updates[field] = _text(payload.get(field))
    elif field in persisted:
        updates[field] = _text(persisted.get(field))



def _load_thread_wbs(user_id, thread_id):
    scenarios = load_scenarios_data(user_id)
    thread = scenarios.get(thread_id)
    if not isinstance(thread, dict):
        return None, None, None
    project_wbs = thread.get("project_wbs")
    if not isinstance(project_wbs, dict):
        return scenarios, thread, None
    return scenarios, thread, project_wbs


def _error_payload(message, code, **extra):
    payload = {"error": str(message or "").strip() or "Request failed", "code": str(code or "UNKNOWN_ERROR")}
    if isinstance(extra, dict):
        payload.update({k: v for k, v in extra.items() if v is not None})
    return payload


def _thread_sync_readiness_payload(user, thread_id):
    _, views = _connector_views_for_user(user)
    execution_views = _execution_connector_views(views)
    execution_by_id = {str(item.get("id") or "").strip().lower(): item for item in execution_views}
    connected_execution = [item for item in execution_views if item.get("connected")]

    profile = get_thread_sync_profile(user.id, thread_id)
    preferred_tool = str(profile.get("preferred_pm_tool") or "").strip().lower() or None
    if not preferred_tool:
        connector_ids = profile.get("connector_ids") if isinstance(profile.get("connector_ids"), list) else []
        connector_ids = [str(item or "").strip().lower() for item in connector_ids if str(item or "").strip()]
        for candidate in connector_ids:
            if candidate in EXECUTION_PM_CONNECTOR_IDS:
                preferred_tool = candidate
                break

    settings_by_connector = get_all_connector_settings(user.id)
    preferred_settings = settings_by_connector.get(preferred_tool) if preferred_tool else {}
    _scenarios, _thread, project_wbs = _load_thread_wbs(user.id, thread_id)
    resolved_status = get_thread_sync_status(profile, connector_settings=preferred_settings, project_wbs=project_wbs)
    profile["thread_sync_status"] = resolved_status

    wbs_exists = bool(isinstance(project_wbs, dict) and project_wbs)
    if preferred_tool in EXECUTION_PM_CONNECTOR_IDS:
        connected_tool = execution_by_id.get(preferred_tool)
        sync_enabled = bool(connected_tool and connected_tool.get("connected"))
    elif preferred_tool == "jaspen":
        sync_enabled = True
    else:
        sync_enabled = False

    if resolved_status == "not_started":
        message = "No PM tool selected. Choose one when you begin the project."
    elif resolved_status == "wbs_pending":
        message = "PM tool selected. Generate an execution plan to start syncing."
    elif resolved_status == "ready":
        message = "Thread is ready to sync."
    elif resolved_status == "degraded":
        message = "PM connector needs re-verification before sync can continue."
    elif resolved_status == "syncing":
        message = "Sync in progress."
    elif resolved_status == "synced":
        message = "Thread sync is up to date."
    elif resolved_status == "error":
        message = "Last sync failed. Retry to continue."
    elif resolved_status == "paused":
        message = "Sync is paused."
    else:
        message = "Thread sync status unavailable."

    available_pm_tools = [
        {
            "id": "jaspen",
            "label": "Jaspen only",
            "connected": True,
            "lifecycle_status": "connected",
        }
    ]
    for item in execution_views:
        available_pm_tools.append(
            {
                "id": item.get("id"),
                "label": item.get("label") or item.get("id"),
                "connected": bool(item.get("connected")),
                "lifecycle_status": item.get("lifecycle_status") or ("connected" if item.get("connected") else "disconnected"),
            }
        )

    payload = {
        "thread_id": str(thread_id or "").strip(),
        "preferred_pm_tool": preferred_tool,
        "thread_sync_status": resolved_status,
        "wbs_exists": wbs_exists,
        "sync_enabled": sync_enabled,
        "connected_pm_tools": [str(item.get("id") or "").strip() for item in connected_execution],
        "available_pm_tools": available_pm_tools,
        "message": message,
    }
    return payload, profile, execution_views, connected_execution


def _find_thread_task_by_external_id(user_id, connector_id, external_id):
    connector_key = str(connector_id or "").strip().lower()
    target_external_id = _text(external_id)
    if not connector_key or not target_external_id:
        return None, None
    profiles = get_all_thread_sync_profiles(user_id)
    for thread_id, profile in profiles.items():
        ext_map = profile.get("wbs_task_external_ids") if isinstance(profile.get("wbs_task_external_ids"), dict) else {}
        for task_id, mapped_external_id in ext_map.items():
            if _text(mapped_external_id) == target_external_id:
                return _text(thread_id), _text(task_id)
    return None, None


def _sync_thread_with_connector(user, thread_id, connector_id, sync_callable):
    connector_id = str(connector_id or "").strip().lower()
    if connector_id not in EXECUTION_PM_CONNECTOR_IDS:
        return jsonify(_error_payload(
            f"Connector '{connector_id}' is not supported for execution sync",
            "CONNECTOR_NOT_FOUND",
            connector_id=connector_id,
        )), 404

    settings = get_connector_settings(user.id, connector_id)
    lifecycle_status = str(settings.get("lifecycle_status") or "").strip().lower() or "disconnected"
    if lifecycle_status != "connected":
        return jsonify(_error_payload(
            f"Connector '{connector_id}' is not connected",
            "CONNECTOR_NOT_CONNECTED",
            connector_id=connector_id,
            lifecycle_status=lifecycle_status,
        )), 400

    profile = get_thread_sync_profile(user.id, thread_id)
    preferred_tool = str(profile.get("preferred_pm_tool") or "").strip().lower() or None
    if not preferred_tool:
        connector_ids = profile.get("connector_ids") if isinstance(profile.get("connector_ids"), list) else []
        for candidate in connector_ids:
            token = str(candidate or "").strip().lower()
            if token in EXECUTION_PM_CONNECTOR_IDS:
                preferred_tool = token
                break
    if not preferred_tool:
        return jsonify(_error_payload(
            "No PM tool selected for this thread",
            "NO_PM_TOOL_SELECTED",
            thread_id=thread_id,
        )), 400
    if preferred_tool == "jaspen":
        return jsonify(_error_payload(
            "Preferred PM tool is Jaspen only. External sync is not enabled.",
            "NO_PM_TOOL_SELECTED",
            thread_id=thread_id,
            preferred_pm_tool="jaspen",
        )), 400
    if preferred_tool != connector_id:
        return jsonify(_error_payload(
            f"Preferred PM tool for this thread is '{preferred_tool}'",
            "PM_TOOL_NOT_CONNECTED",
            thread_id=thread_id,
            preferred_pm_tool=preferred_tool,
        )), 400

    lock_ts = str(profile.get("sync_lock_acquired_at") or "").strip()
    if lock_ts:
        try:
            lock_age = (datetime.utcnow() - datetime.fromisoformat(lock_ts.replace("Z", "+00:00")).replace(tzinfo=None)).total_seconds()
            if 0 <= lock_age < 30:
                return jsonify(_error_payload(
                    "Sync is already in progress",
                    "SYNC_IN_PROGRESS",
                    thread_id=thread_id,
                    connector_id=connector_id,
                )), 409
        except Exception:
            pass

    update_thread_sync_profile(user.id, thread_id, {"sync_lock_acquired_at": _iso_now(), "thread_sync_status": "syncing"})
    scenarios, thread, project_wbs = _load_thread_wbs(user.id, thread_id)
    if thread is None:
        update_thread_sync_profile(user.id, thread_id, {"sync_lock_acquired_at": None, "thread_sync_status": "error"})
        return jsonify(_error_payload("Thread not found", "THREAD_NOT_FOUND", thread_id=thread_id)), 404
    if project_wbs is None:
        update_thread_sync_profile(user.id, thread_id, {"sync_lock_acquired_at": None, "thread_sync_status": "wbs_pending"})
        return jsonify(_error_payload("No WBS found for thread", "WBS_NOT_FOUND", thread_id=thread_id)), 404

    profile = get_thread_sync_profile(user.id, thread_id)
    app = current_app._get_current_object()
    user_id_str = str(user.id)
    thread_id_str = str(thread_id)

    def _run_sync():
        with app.app_context():
            try:
                _result = sync_callable(user_id_str, thread_id_str, project_wbs, thread_sync_profile=profile)
            except Exception as _exc:
                update_thread_sync_profile(user_id_str, thread_id_str, {"sync_lock_acquired_at": None, "thread_sync_status": "error"})
                app.logger.error("[sync] %s failed for thread %s: %s", connector_id, thread_id_str, _exc)
                return

            _next_wbs = _result.get("project_wbs")
            if isinstance(_next_wbs, dict):
                thread["project_wbs"] = _next_wbs
                scenarios[thread_id_str] = thread
                save_scenarios_data(user_id_str, scenarios)

            _status = "success" if _result.get("success") else "skipped" if _result.get("skipped") else "failed"
            _errors = _result.get("errors") if isinstance(_result.get("errors"), list) else []
            _error_msg = ""
            if _errors:
                _error_msg = _text(_errors[0].get("error")) if isinstance(_errors[0], dict) else _text(_errors[0])
            elif _result.get("reason"):
                _error_msg = _text(_result.get("reason"))

            _ext_patch = {}
            if isinstance(_next_wbs, dict):
                for _task in (_next_wbs.get("tasks") if isinstance(_next_wbs.get("tasks"), list) else []):
                    if not isinstance(_task, dict):
                        continue
                    _tid = _text(_task.get("id"))
                    _refs = _task.get("external_refs") if isinstance(_task.get("external_refs"), dict) else {}
                    _ext_id = ""
                    if connector_id == "jira_sync":
                        _ext_id = _text(_refs.get("jira_issue_key") or _task.get("jira_issue_key"))
                    elif connector_id == "smartsheet_sync":
                        _ext_id = _text(_refs.get("smartsheet_row_id"))
                    if _tid and _ext_id:
                        _ext_patch[_tid] = _ext_id

            mark_connector_sync_result(user_id_str, connector_id, _status, error_message=_error_msg)
            _prof_updates = {
                "sync_lock_acquired_at": None,
                "last_full_sync_at": _iso_now(),
                "thread_sync_status": "synced" if _status == "success" else "error" if _status == "failed" else profile.get("thread_sync_status") or "ready",
            }
            if _ext_patch:
                _prof_updates["wbs_task_external_ids_patch"] = _ext_patch
            update_thread_sync_profile(user_id_str, thread_id_str, _prof_updates)

    bg = threading.Thread(target=_run_sync, daemon=True)
    bg.start()

    return jsonify({
        "success": True,
        "status": "syncing",
        "message": "Sync started. Poll /sync for status.",
        "thread_id": thread_id_str,
        "connector_id": connector_id,
    }), 202

def _normalize_imported_task(task, index=0):
    task = task if isinstance(task, dict) else {}
    task_id = _text(task.get("id")) or f"imported_{index + 1}"
    title = _text(task.get("title")) or f"Imported task {index + 1}"
    status = _text(task.get("status")).lower() or "todo"
    if status not in {"todo", "in_progress", "blocked", "done"}:
        status = "todo"
    owner = _text(task.get("owner"))
    due_date = _text(task.get("due_date")) or None
    refs = task.get("external_refs") if isinstance(task.get("external_refs"), dict) else {}
    return {
        "id": task_id,
        "title": title,
        "status": status,
        "owner": owner,
        "due_date": due_date,
        "external_refs": refs,
    }


def _merge_imported_tasks(existing_tasks, imported_tasks, *, conflict_policy="prefer_external"):
    existing_tasks = existing_tasks if isinstance(existing_tasks, list) else []
    imported_tasks = imported_tasks if isinstance(imported_tasks, list) else []
    policy = _text(conflict_policy).lower() or "prefer_external"

    by_id = {}
    for idx, item in enumerate(existing_tasks):
        normalized = _normalize_imported_task(item, idx)
        by_id[_text(normalized.get("id"))] = normalized

    for idx, imported in enumerate(imported_tasks):
        normalized = _normalize_imported_task(imported, idx)
        task_id = _text(normalized.get("id"))
        if task_id not in by_id:
            by_id[task_id] = normalized
            continue
        if policy == "prefer_external":
            merged = dict(by_id[task_id])
            merged.update({k: v for k, v in normalized.items() if v not in ("", None)})
            by_id[task_id] = merged
        else:
            # prefer_jaspen and all fallback policies preserve local values on collision.
            merged = dict(normalized)
            merged.update({k: v for k, v in by_id[task_id].items() if v not in ("", None)})
            by_id[task_id] = merged

    return list(by_id.values())
def _require_webhook_secret(connector_id):
    """Validate webhook secret. Returns error response or None if valid."""
    env_key = f"{connector_id.upper().replace('-', '_')}_WEBHOOK_SECRET"
    configured_secret = current_app.config.get(env_key) or os.getenv(env_key)

    if not configured_secret:
        current_app.logger.error("Webhook secret not configured for %s", connector_id)
        return jsonify({"error": "Webhook not configured"}), 503

    provided_secret = request.headers.get("X-Webhook-Secret", "")

    if not hmac.compare_digest(provided_secret, configured_secret):
        current_app.logger.warning("Invalid webhook secret for %s from %s", connector_id, request.remote_addr)
        return jsonify({"error": "Unauthorized"}), 401

    return None


@connectors_bp.route("/status", methods=["GET"])
@jwt_required()
def get_connector_status():
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({"error": "User not found"}), 404

    plan_key, views = _connector_views_for_user(user)
    execution_views = _execution_connector_views(views)
    connected_execution = [view for view in execution_views if view.get("connected")]

    return jsonify({
        "plan_key": plan_key,
        "connectors": views,
        "sync_modes": list(SYNC_MODES),
        "conflict_policies": list(CONFLICT_POLICIES),
        "execution_connectors": execution_views,
        "connected_execution_connectors": connected_execution,
    }), 200


@connectors_bp.route("/<connector_id>", methods=["PATCH"])
@jwt_required()
def update_connector(connector_id):
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({"error": "User not found"}), 404

    connector_id = str(connector_id or "").strip().lower()
    if not get_connector_definition(connector_id):
        return jsonify({"error": f"Unknown connector '{connector_id}'"}), 404

    payload = request.get_json(silent=True) or {}
    plan_key, views = _connector_views_for_user(user)
    view_map = {item["id"]: item for item in views}
    current = view_map.get(connector_id)
    if not current:
        return jsonify({"error": f"Unknown connector '{connector_id}'"}), 404

    desired_status = payload.get("connection_status")
    if desired_status is not None:
        desired_status = str(desired_status).strip().lower()
        if desired_status not in ("connected", "disconnected"):
            return jsonify({"error": "connection_status must be connected or disconnected"}), 400
    else:
        desired_status = current.get("connection_status")

    desired_mode = payload.get("sync_mode")
    if desired_mode is not None:
        desired_mode = _normalize_sync_mode(desired_mode)
        if not desired_mode:
            return jsonify({"error": f"sync_mode must be one of {', '.join(SYNC_MODES)}"}), 400
    else:
        desired_mode = current.get("sync_mode")

    desired_conflict_policy = payload.get("conflict_policy")
    if desired_conflict_policy is not None:
        desired_conflict_policy = _normalize_conflict_policy(desired_conflict_policy)
        if not desired_conflict_policy:
            return jsonify({"error": f"conflict_policy must be one of {', '.join(CONFLICT_POLICIES)}"}), 400
    else:
        desired_conflict_policy = current.get("conflict_policy")

    available_modes = current.get("available_sync_modes") or []
    if desired_mode and desired_mode not in available_modes:
        return jsonify({
            "error": f"sync_mode '{desired_mode}' is not allowed for your current plan or connector access.",
            "connector_id": connector_id,
            "plan_key": plan_key,
            "available_sync_modes": available_modes,
        }), 403

    if desired_status == "connected" and not current.get("enabled"):
        return jsonify({
            "error": f"Connector '{connector_id}' requires plan upgrade.",
            "connector_id": connector_id,
            "required_min_tier": current.get("required_min_tier"),
            "plan_key": plan_key,
        }), 403

    persisted_settings = get_connector_settings(user.id, connector_id)
    updates = {
        "connection_status": desired_status,
        "sync_mode": desired_mode,
        "conflict_policy": desired_conflict_policy,
        "auto_sync": _to_bool(payload.get("auto_sync"), default=current.get("auto_sync")),
        "external_workspace": _text(payload.get("external_workspace") if "external_workspace" in payload else current.get("external_workspace") or ""),
    }

    if connector_id == "jira_sync":
        jira_mapping = payload.get("jira_field_mapping")
        for field in ("jira_base_url", "jira_project_key", "jira_email", "jira_issue_type"):
            _apply_field_update(updates, payload, persisted_settings, field)
        if "jira_api_token" in payload:
            updates["jira_api_token"] = _text(payload.get("jira_api_token"))
        updates["jira_field_mapping"] = jira_mapping if isinstance(jira_mapping, dict) else (persisted_settings.get("jira_field_mapping") or {})

    elif connector_id == "smartsheet_sync":
        mapping = payload.get("smartsheet_field_mapping")
        for field in ("smartsheet_base_url", "smartsheet_sheet_id"):
            _apply_field_update(updates, payload, persisted_settings, field)
        if "smartsheet_api_token" in payload:
            updates["smartsheet_api_token"] = _text(payload.get("smartsheet_api_token"))
        updates["smartsheet_field_mapping"] = mapping if isinstance(mapping, dict) else (persisted_settings.get("smartsheet_field_mapping") or {})

    elif connector_id == "salesforce_insights":
        for field in ("salesforce_auth_base_url", "salesforce_instance_url", "salesforce_client_id"):
            _apply_field_update(updates, payload, persisted_settings, field)
        for secret_field in ("salesforce_client_secret", "salesforce_refresh_token"):
            if secret_field in payload:
                updates[secret_field] = _text(payload.get(secret_field))

    elif connector_id == "snowflake_insights":
        for field in (
            "snowflake_account",
            "snowflake_warehouse",
            "snowflake_database",
            "snowflake_schema",
            "snowflake_role",
            "snowflake_user",
        ):
            _apply_field_update(updates, payload, persisted_settings, field)
        for secret_field in ("snowflake_password", "snowflake_private_key"):
            if secret_field in payload:
                updates[secret_field] = _text(payload.get(secret_field))
        if "snowflake_table_allowlist" in payload:
            updates["snowflake_table_allowlist"] = _coerce_allowlist(payload.get("snowflake_table_allowlist"))
    elif connector_id == "oracle_fusion_insights":
        for field in (
            "oracle_fusion_base_url",
            "oracle_fusion_username",
            "oracle_fusion_business_unit",
        ):
            _apply_field_update(updates, payload, persisted_settings, field)
        if "oracle_fusion_password" in payload:
            updates["oracle_fusion_password"] = _text(payload.get("oracle_fusion_password"))
    elif connector_id == "servicenow_insights":
        for field in (
            "servicenow_instance_url",
            "servicenow_username",
        ):
            _apply_field_update(updates, payload, persisted_settings, field)
        if "servicenow_password" in payload:
            updates["servicenow_password"] = _text(payload.get("servicenow_password"))
        if "servicenow_table_allowlist" in payload:
            updates["servicenow_table_allowlist"] = _coerce_allowlist(payload.get("servicenow_table_allowlist"))
    elif connector_id == "netsuite_insights":
        for field in (
            "netsuite_account_id",
            "netsuite_consumer_key",
            "netsuite_token_id",
            "netsuite_rest_base_url",
        ):
            _apply_field_update(updates, payload, persisted_settings, field)
        if "netsuite_consumer_secret" in payload:
            updates["netsuite_consumer_secret"] = _text(payload.get("netsuite_consumer_secret"))
        if "netsuite_token_secret" in payload:
            updates["netsuite_token_secret"] = _text(payload.get("netsuite_token_secret"))

    candidate_settings = dict(persisted_settings)
    candidate_settings.update(updates)
    if desired_status == "connected":
        missing_required_fields = _missing_required_fields(connector_id, candidate_settings)
        if missing_required_fields:
            return jsonify({
                "error": f"{(current.get('label') or connector_id)} configuration is incomplete.",
                "connector_id": connector_id,
                "missing_required_fields": missing_required_fields,
            }), 400
        if connector_id == "smartsheet_sync":
            valid = smartsheet_connect(candidate_settings.get("smartsheet_api_token"))
            if not valid:
                return jsonify({
                    "error": "Unable to validate Smartsheet token.",
                    "connector_id": connector_id,
                }), 400
        if connector_id == "snowflake_insights":
            # Temporarily write candidate settings so test_snowflake_connection can read them
            update_connector_settings(user.id, connector_id, updates)
            ok, err_msg = test_snowflake_connection(user.id)
            if not ok:
                # Revert connection_status so we don't leave a false "connected" record
                update_connector_settings(user.id, connector_id, {"connection_status": "disconnected"})
                return jsonify({
                    "error": f"Could not connect to Snowflake: {err_msg}",
                    "connector_id": connector_id,
                }), 400

    saved = update_connector_settings(user.id, connector_id, updates)
    _, updated_views = _connector_views_for_user(user)
    updated_view = next((item for item in updated_views if item["id"] == connector_id), None)

    append_sync_audit_event(
        user.id,
        connector_id,
        action="config_update",
        status="success",
        message="Connector settings updated",
        metadata={"connected": desired_status == "connected"},
    )

    return jsonify({
        "success": True,
        "plan_key": plan_key,
        "connector": updated_view,
        "saved_settings": redact_connector_settings(saved, connector_id=connector_id),
    }), 200


@connectors_bp.route("/<connector_id>/health", methods=["GET"])
@jwt_required()
def get_connector_health(connector_id):
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({"error": "User not found"}), 404

    connector_id = str(connector_id or "").strip().lower()
    if not get_connector_definition(connector_id):
        return jsonify({"error": f"Unknown connector '{connector_id}'"}), 404

    settings = get_connector_settings(user.id, connector_id)
    recent_events = get_sync_audit_events(user.id, connector_id=connector_id, limit=10)
    live_status = None
    if connector_id == "jira_sync":
        probe = jira_check_connection(user.id)
        ok = bool(probe.get("ok"))
        err_msg = _text(probe.get("error")) if not ok else ""
        live_status = {
            "status": "healthy" if ok else "error",
            "message": "Connection successful" if ok else (err_msg or "Connection failed"),
        }
        if ok:
            mark_connector_sync_result(user.id, connector_id, "success")
            append_sync_audit_event(
                user.id,
                connector_id,
                action="health_check",
                status="success",
                message="Live connection test passed",
            )
        else:
            mark_connector_sync_result(user.id, connector_id, "failed", error_message=err_msg)
            append_sync_audit_event(
                user.id,
                connector_id,
                action="health_check",
                status="failed",
                message=err_msg or "Connection failed",
            )
    elif connector_id == "snowflake_insights":
        ok, err_msg = test_snowflake_connection(user.id)
        live_status = {
            "status": "healthy" if ok else "error",
            "message": "Connection successful" if ok else (err_msg or "Connection failed"),
        }
        if ok:
            mark_connector_sync_result(user.id, connector_id, "success")
            append_sync_audit_event(
                user.id,
                connector_id,
                action="health_check",
                status="success",
                message="Live connection test passed",
            )
        else:
            mark_connector_sync_result(user.id, connector_id, "failed", error_message=err_msg)
            append_sync_audit_event(
                user.id,
                connector_id,
                action="health_check",
                status="failed",
                message=err_msg or "Connection failed",
            )
    return jsonify({
        "success": True,
        "connector_id": connector_id,
        "health": {
            "status": settings.get("health_status") or "unknown",
            "last_sync_at": settings.get("last_sync_at"),
            "last_sync_result": settings.get("last_sync_result") or "never",
            "consecutive_failures": int(settings.get("consecutive_failures") or 0),
            "next_retry_at": settings.get("next_retry_at"),
            "last_success_at": settings.get("last_success_at"),
            "last_error_at": settings.get("last_error_at"),
            "last_error_message": settings.get("last_error_message") or "",
        },
        "live_status": live_status,
        "recent_events": recent_events,
    }), 200


@connectors_bp.route("/<connector_id>/check", methods=["GET"])
@jwt_required()
def check_connector_setup(connector_id):
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({"error": "User not found"}), 404

    connector_id = str(connector_id or "").strip().lower()
    if not get_connector_definition(connector_id):
        return jsonify(_error_payload(f"Unknown connector '{connector_id}'", "CONNECTOR_NOT_FOUND", connector_id=connector_id)), 404

    settings = get_connector_settings(user.id, connector_id)
    missing_required_fields = _missing_required_fields(connector_id, settings)
    lifecycle_status = str(settings.get("lifecycle_status") or "").strip().lower() or "disconnected"

    if missing_required_fields:
        if lifecycle_status == "connected":
            lifecycle_status = "configured"
            update_connector_settings(user.id, connector_id, {"lifecycle_status": "configured"})
        return jsonify({
            "connector_id": connector_id,
            "lifecycle_status": lifecycle_status,
            "missing_fields": missing_required_fields,
        }), 400

    try:
        if connector_id == "jira_sync":
            probe = jira_check_connection(user.id)
            if not probe.get("ok"):
                reason = _text(probe.get("error")) or "Unable to validate Jira credentials"
                update_connector_settings(user.id, connector_id, {
                    "lifecycle_status": "degraded",
                    "connection_status": "disconnected",
                })
                mark_connector_sync_result(user.id, connector_id, "failed", error_message=reason)
                return jsonify({
                    "connector_id": connector_id,
                    "lifecycle_status": "degraded",
                    "error": reason,
                    "next_retry_at": get_connector_settings(user.id, connector_id).get("next_retry_at"),
                }), 503
            update_connector_settings(
                user.id,
                connector_id,
                {
                    "connection_status": "connected",
                    "lifecycle_status": "connected",
                    "last_verified_at": _iso_now(),
                    "verified_instance_url": _text(settings.get("jira_base_url")),
                },
            )
            mark_connector_sync_result(user.id, connector_id, "success")
        elif connector_id == "snowflake_insights":
            ok, err_msg = test_snowflake_connection(user.id)
            if not ok:
                update_connector_settings(user.id, connector_id, {
                    "lifecycle_status": "degraded",
                    "connection_status": "disconnected",
                })
                mark_connector_sync_result(user.id, connector_id, "failed", error_message=err_msg or "Connection failed")
                return jsonify({
                    "connector_id": connector_id,
                    "lifecycle_status": "degraded",
                    "error": err_msg or "Connection failed",
                    "next_retry_at": get_connector_settings(user.id, connector_id).get("next_retry_at"),
                }), 503
            update_connector_settings(
                user.id,
                connector_id,
                {
                    "connection_status": "connected",
                    "lifecycle_status": "connected",
                    "last_verified_at": _iso_now(),
                    "verified_instance_url": _text(settings.get("snowflake_account")),
                },
            )
            mark_connector_sync_result(user.id, connector_id, "success")
        elif connector_id == "smartsheet_sync":
            valid = smartsheet_connect(settings.get("smartsheet_api_token"))
            if not valid:
                update_connector_settings(user.id, connector_id, {
                    "lifecycle_status": "degraded",
                    "connection_status": "disconnected",
                })
                mark_connector_sync_result(user.id, connector_id, "failed", error_message="Unable to validate Smartsheet token")
                return jsonify({
                    "connector_id": connector_id,
                    "lifecycle_status": "degraded",
                    "error": "Unable to validate Smartsheet token",
                    "next_retry_at": get_connector_settings(user.id, connector_id).get("next_retry_at"),
                }), 503
            update_connector_settings(
                user.id,
                connector_id,
                {
                    "connection_status": "connected",
                    "lifecycle_status": "connected",
                    "last_verified_at": _iso_now(),
                    "verified_instance_url": _text(settings.get("smartsheet_base_url")),
                },
            )
            mark_connector_sync_result(user.id, connector_id, "success")
        else:
            generic_instance_url = ""
            if connector_id == "salesforce_insights":
                generic_instance_url = _text(settings.get("salesforce_instance_url") or settings.get("salesforce_auth_base_url"))
            elif connector_id == "snowflake_insights":
                generic_instance_url = _text(settings.get("snowflake_account"))
            update_connector_settings(
                user.id,
                connector_id,
                {
                    "lifecycle_status": "connected",
                    "connection_status": "connected",
                    "last_verified_at": _iso_now(),
                    "verified_instance_url": generic_instance_url,
                },
            )
            mark_connector_sync_result(user.id, connector_id, "success")
    except Exception as exc:
        update_connector_settings(user.id, connector_id, {
            "lifecycle_status": "degraded",
            "connection_status": "disconnected",
        })
        mark_connector_sync_result(user.id, connector_id, "failed", error_message=str(exc))
        return jsonify({
            "connector_id": connector_id,
            "lifecycle_status": "degraded",
            "error": str(exc),
            "next_retry_at": get_connector_settings(user.id, connector_id).get("next_retry_at"),
        }), 503

    refreshed = get_connector_settings(user.id, connector_id)
    return jsonify({
        "connector_id": connector_id,
        "lifecycle_status": refreshed.get("lifecycle_status") or "connected",
        "last_verified_at": refreshed.get("last_verified_at"),
        "verified_instance_url": refreshed.get("verified_instance_url") or "",
    }), 200


@connectors_bp.route("/smartsheet/sheets", methods=["GET"])
@jwt_required()
def get_smartsheet_sheets():
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({"error": "User not found"}), 404

    settings = get_connector_settings(user.id, "smartsheet_sync")
    try:
        sheets = smartsheet_list_sheets(
            {
                "base_url": settings.get("smartsheet_base_url"),
                "access_token": settings.get("smartsheet_api_token"),
            }
        )
        return jsonify({"success": True, "sheets": sheets, "count": len(sheets)}), 200
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@connectors_bp.route("/<connector_id>/audit", methods=["GET"])
@jwt_required()
def get_connector_audit(connector_id):
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({"error": "User not found"}), 404

    connector_id = str(connector_id or "").strip().lower()
    if not get_connector_definition(connector_id):
        return jsonify({"error": f"Unknown connector '{connector_id}'"}), 404

    thread_id = _text(request.args.get("thread_id"))
    limit = request.args.get("limit")
    rows = get_sync_audit_events(user.id, connector_id=connector_id, thread_id=thread_id or None, limit=limit)

    return jsonify({
        "success": True,
        "connector_id": connector_id,
        "thread_id": thread_id or None,
        "events": rows,
        "count": len(rows),
    }), 200


@connectors_bp.route("/salesforce/oauth/start", methods=["GET"])
@jwt_required()
def salesforce_oauth_start():
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({"error": "User not found"}), 404

    _, views = _connector_views_for_user(user)
    salesforce_view = next((item for item in views if item.get("id") == "salesforce_insights"), None)
    if not salesforce_view:
        return jsonify({"error": "Salesforce connector is not available"}), 404
    if not salesforce_view.get("enabled"):
        return jsonify({
            "error": "Salesforce connector requires plan upgrade.",
            "required_min_tier": salesforce_view.get("required_min_tier"),
        }), 403

    next_path = _safe_next_path(request.args.get("next") or "/connectors-manage")
    config = salesforce_runtime_config(user.id)
    missing = salesforce_missing_oauth_config(config)
    if missing:
        return jsonify({
            "error": "Salesforce OAuth configuration is incomplete.",
            "missing_required_fields": missing,
        }), 400

    secret = _salesforce_state_secret()
    if not secret:
        return jsonify({"error": "Missing SECRET_KEY/JWT_SECRET_KEY for Salesforce OAuth state signing"}), 500

    code_verifier, code_challenge = generate_pkce_pair()
    state = encode_salesforce_oauth_state(secret, {
        "user_id": str(user.id),
        "next": next_path,
        "code_verifier": code_verifier,
    })
    auth_url = salesforce_authorize_url(
        config=config,
        state_token=state,
        redirect_uri=_salesforce_callback_url(),
        scope=request.args.get("scope"),
        code_challenge=code_challenge,
    )
    return jsonify({"success": True, "auth_url": auth_url, "next": next_path}), 200


@connectors_bp.route("/salesforce/oauth/callback", methods=["GET"])
def salesforce_oauth_callback():
    state_token = _text(request.args.get("state"))
    code = _text(request.args.get("code"))
    oauth_error = _text(request.args.get("error"))

    if oauth_error:
        safe_reason = _safe_salesforce_oauth_error_code(oauth_error)
        # Best effort parse state for redirect target.
        try:
            state_data = decode_salesforce_oauth_state(
                _salesforce_state_secret(),
                state_token,
                max_age_seconds=int(os.getenv("SALESFORCE_OAUTH_STATE_TTL_SECONDS", "900")),
            )
            return _frontend_redirect(
                (state_data or {}).get("next") or "/connectors-manage",
                {"sf_oauth": "error", "reason": safe_reason},
            )
        except Exception:
            return _frontend_redirect("/connectors-manage", {"sf_oauth": "error", "reason": safe_reason})

    if not code or not state_token:
        return _frontend_redirect("/connectors-manage", {"sf_oauth": "error", "reason": "missing_code_or_state"})

    try:
        state_data = decode_salesforce_oauth_state(
            _salesforce_state_secret(),
            state_token,
            max_age_seconds=int(os.getenv("SALESFORCE_OAUTH_STATE_TTL_SECONDS", "900")),
        )
    except SalesforceStateExpired:
        return _frontend_redirect("/connectors-manage", {"sf_oauth": "error", "reason": "state_expired"})
    except SalesforceBadSignature:
        return _frontend_redirect("/connectors-manage", {"sf_oauth": "error", "reason": "invalid_state"})
    except Exception:
        return _frontend_redirect("/connectors-manage", {"sf_oauth": "error", "reason": "invalid_state"})

    user_id = _text((state_data or {}).get("user_id"))
    next_path = _safe_next_path((state_data or {}).get("next") or "/connectors-manage")
    if not user_id:
        return _frontend_redirect(next_path, {"sf_oauth": "error", "reason": "missing_user_context"})

    user = User.query.get(user_id)
    if not user:
        return _frontend_redirect(next_path, {"sf_oauth": "error", "reason": "user_not_found"})

    try:
        config = salesforce_runtime_config(user.id)
        code_verifier = _text((state_data or {}).get("code_verifier"))
        token_payload, token_meta = exchange_salesforce_code(
            config=config,
            code=code,
            redirect_uri=_salesforce_callback_url(),
            code_verifier=code_verifier or None,
        )
        # Only update token fields when Salesforce actually returned non-empty values.
        # An empty access_token in updates would overwrite a previously-valid token
        # (the probe uses the old token as fallback, so it succeeds even when the new
        # token is empty — silently nuking the working credentials).
        new_access_token = _text(token_payload.get("access_token"))
        new_instance_url = _text(token_payload.get("instance_url") or config.get("instance_url"))
        updates = {"connection_status": "connected"}
        if new_instance_url:
            updates["salesforce_instance_url"] = new_instance_url
        if new_access_token:
            updates["salesforce_access_token"] = new_access_token
            updates["salesforce_token_type"] = _text(token_payload.get("token_type") or "Bearer") or "Bearer"
            updates["salesforce_token_expires_at"] = _salesforce_token_expires_at_iso(token_payload)
        refresh_token = _text(token_payload.get("refresh_token"))
        if refresh_token:
            updates["salesforce_refresh_token"] = refresh_token

        # Probe Salesforce before persisting "connected" so UI state matches reality.
        probe_config = dict(config or {})
        probe_config["instance_url"] = updates.get("salesforce_instance_url") or probe_config.get("instance_url")
        probe_config["access_token"] = updates.get("salesforce_access_token") or probe_config.get("access_token")
        probe_config["token_type"] = updates.get("salesforce_token_type") or probe_config.get("token_type") or "Bearer"
        probe_meta = probe_salesforce_connection(probe_config)

        update_connector_settings(user.id, "salesforce_insights", updates)
        mark_connector_sync_result(user.id, "salesforce_insights", "success")
        append_sync_audit_event(
            user.id,
            "salesforce_insights",
            action="oauth_callback",
            status="success",
            attempt_count=probe_meta.get("attempt_count") or token_meta.get("attempt_count"),
            duration_ms=probe_meta.get("duration_ms") or token_meta.get("duration_ms"),
            message="Salesforce OAuth connected",
            metadata={
                "token_refreshed": bool(refresh_token),
                "probe_ok": True,
                "probe_keys": probe_meta.get("keys") or [],
            },
        )
        return _frontend_redirect(next_path, {"sf_oauth": "success"})
    except Exception as exc:
        reason = _safe_salesforce_oauth_error_reason(exc)
        mark_connector_sync_result(user.id, "salesforce_insights", "failed", error_message=reason)
        append_sync_audit_event(
            user.id,
            "salesforce_insights",
            action="oauth_callback",
            status="failed",
            message=reason,
        )
        current_app.logger.exception("Salesforce OAuth callback failed")
        return _frontend_redirect(next_path, {"sf_oauth": "error", "reason": reason})


@connectors_bp.route("/salesforce/pipeline/summary", methods=["GET"])
@jwt_required()
def salesforce_pipeline_snapshot():
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({"error": "User not found"}), 404

    lookback_days = request.args.get("days", 90)
    max_records = request.args.get("limit", 200)
    try:
        result = fetch_pipeline_summary(user.id, lookback_days=lookback_days, max_records=max_records)
        update_connector_settings(user.id, "salesforce_insights", {"connection_status": "connected"})
        mark_connector_sync_result(user.id, "salesforce_insights", "success")
        append_sync_audit_event(
            user.id,
            "salesforce_insights",
            action="pipeline_summary",
            status="success",
            attempt_count=result.get("attempt_count"),
            duration_ms=result.get("duration_ms"),
            metadata={
                "opportunity_count": (result.get("summary") or {}).get("opportunity_count", 0),
                "lookback_days": (result.get("summary") or {}).get("lookback_days", 90),
            },
        )
        return jsonify({"success": True, **result}), 200
    except Exception as exc:
        mark_connector_sync_result(user.id, "salesforce_insights", "failed", error_message=str(exc))
        append_sync_audit_event(
            user.id,
            "salesforce_insights",
            action="pipeline_summary",
            status="failed",
            message=str(exc),
        )
        return jsonify({"error": str(exc)}), 400


@connectors_bp.route("/jira/context/summary", methods=["GET"])
@jwt_required()
def jira_context_summary():
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({"error": "User not found"}), 404

    max_issues = request.args.get("limit", 60)
    try:
        result = fetch_jira_context_summary(user.id, max_issues=int(max_issues))
        mark_connector_sync_result(user.id, "jira_sync", "success")
        append_sync_audit_event(
            user.id,
            "jira_sync",
            action="context_summary",
            status="success",
            metadata={
                "sprint_issue_count": (result.get("summary") or {}).get("sprint_issue_count", 0),
                "blocked_count": (result.get("summary") or {}).get("blocked_count", 0),
            },
        )
        return jsonify({"success": True, **result}), 200
    except Exception as exc:
        mark_connector_sync_result(user.id, "jira_sync", "failed", error_message=str(exc))
        append_sync_audit_event(
            user.id, "jira_sync", action="context_summary", status="failed", message=str(exc)
        )
        return jsonify({"error": str(exc)}), 400


@connectors_bp.route("/snowflake/query", methods=["POST"])
@jwt_required()
def snowflake_query():
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({"error": "User not found"}), 404

    payload = request.get_json(silent=True) or {}
    table = _text(payload.get("table"))
    if not table:
        return jsonify({"error": "table is required"}), 400

    try:
        result = run_allowlisted_query(
            user.id,
            table=table,
            columns=payload.get("columns"),
            date_column=payload.get("date_column"),
            date_from=payload.get("date_from"),
            date_to=payload.get("date_to"),
            filters=payload.get("filters"),
            order_by=payload.get("order_by"),
            limit=payload.get("limit", 200),
        )
        update_connector_settings(user.id, "snowflake_insights", {"connection_status": "connected"})
        mark_connector_sync_result(user.id, "snowflake_insights", "success")
        append_sync_audit_event(
            user.id,
            "snowflake_insights",
            action="query",
            status="success",
            message=f"Queried {table}",
            metadata={
                "table": table,
                "row_count": len(result.get("rows") or []),
                "limit": (result.get("summary") or {}).get("limit"),
            },
        )
        return jsonify({"success": True, **result}), 200
    except PermissionError as exc:
        mark_connector_sync_result(user.id, "snowflake_insights", "failed", error_message=str(exc))
        append_sync_audit_event(
            user.id,
            "snowflake_insights",
            action="query",
            status="failed",
            message=str(exc),
            metadata={"table": table},
        )
        return jsonify({"error": str(exc)}), 403
    except Exception as exc:
        mark_connector_sync_result(user.id, "snowflake_insights", "failed", error_message=str(exc))
        append_sync_audit_event(
            user.id,
            "snowflake_insights",
            action="query",
            status="failed",
            message=str(exc),
            metadata={"table": table},
        )
        return jsonify({"error": str(exc)}), 400


@connectors_bp.route("/snowflake/kpis", methods=["POST"])
@jwt_required()
def snowflake_kpis():
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({"error": "User not found"}), 404

    payload = request.get_json(silent=True) or {}
    table = _text(payload.get("table"))
    metric_columns = payload.get("metric_columns")
    if not table:
        return jsonify({"error": "table is required"}), 400
    if not isinstance(metric_columns, list) or not metric_columns:
        return jsonify({"error": "metric_columns must be a non-empty array"}), 400

    try:
        result = extract_kpi_metrics(
            user.id,
            table=table,
            metric_columns=metric_columns,
            date_column=payload.get("date_column"),
            date_from=payload.get("date_from"),
            date_to=payload.get("date_to"),
        )
        mark_connector_sync_result(user.id, "snowflake_insights", "success")
        append_sync_audit_event(
            user.id,
            "snowflake_insights",
            action="kpi_extract",
            status="success",
            message=f"KPI extract for {table}",
            metadata={"table": table, "metric_count": result.get("metric_count", 0)},
        )
        return jsonify({"success": True, **result}), 200
    except PermissionError as exc:
        mark_connector_sync_result(user.id, "snowflake_insights", "failed", error_message=str(exc))
        append_sync_audit_event(
            user.id,
            "snowflake_insights",
            action="kpi_extract",
            status="failed",
            message=str(exc),
            metadata={"table": table},
        )
        return jsonify({"error": str(exc)}), 403
    except Exception as exc:
        mark_connector_sync_result(user.id, "snowflake_insights", "failed", error_message=str(exc))
        append_sync_audit_event(
            user.id,
            "snowflake_insights",
            action="kpi_extract",
            status="failed",
            message=str(exc),
            metadata={"table": table},
        )
        return jsonify({"error": str(exc)}), 400


@connectors_bp.route("/generate-ideas", methods=["POST"])
@jwt_required()
def generate_ideas_from_connector():
    """
    Pull live data from a connected source and use Claude to extract
    3-5 strategic initiative ideas the user should consider executing.
    """
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({"error": "User not found"}), 404

    plan_key = to_public_plan(user.subscription_plan)

    payload = request.get_json(silent=True) or {}
    connector_id = _text(payload.get("connector_id"))
    focus = _text(payload.get("focus") or "")
    objective = _text(payload.get("objective") or "balanced")

    if not connector_id:
        return jsonify({"error": "connector_id is required"}), 400

    connector_data = {}
    data_description = ""

    try:
        if connector_id == "salesforce_insights":
            result = fetch_pipeline_summary(user.id, lookback_days=90, max_records=100)
            connector_data = result.get("summary") if isinstance(result, dict) else result
            connector_data = connector_data or result
            data_description = "Salesforce CRM pipeline data (opportunities, revenue, stage distribution, close rates)"
        elif connector_id == "snowflake_insights":
            result = extract_kpi_metrics(
                user.id,
                table=_text(payload.get("table") or "kpi_metrics"),
                metric_columns=payload.get("metric_columns") or ["revenue", "cost", "efficiency", "growth"],
                date_column=payload.get("date_column"),
                date_from=payload.get("date_from"),
                date_to=payload.get("date_to"),
            )
            connector_data = result.get("metrics") if isinstance(result, dict) else result
            connector_data = connector_data or result
            data_description = "Snowflake data warehouse KPI metrics (financial performance, operational efficiency)"
        elif connector_id == "servicenow_insights":
            from app.servicenow_sync import fetch_servicenow_summary
            result = fetch_servicenow_summary(user.id)
            connector_data = result
            data_description = "ServiceNow IT service management data (incidents, requests, SLA performance, categories)"
        elif connector_id == "netsuite_insights":
            from app.netsuite_sync import fetch_netsuite_summary
            result = fetch_netsuite_summary(user.id)
            connector_data = result
            data_description = "NetSuite ERP data (financial performance, AP/AR, inventory, operational costs)"
        elif connector_id == "oracle_fusion_insights":
            from app.oracle_fusion_sync import fetch_oracle_summary
            result = fetch_oracle_summary(user.id)
            connector_data = result
            data_description = "Oracle Fusion ERP data (financials, supply chain, workforce metrics)"
        else:
            return jsonify({"error": f"Connector '{connector_id}' does not support idea generation yet."}), 400
    except Exception as exc:
        return jsonify({"error": f"Could not fetch data from {connector_id}: {str(exc)}"}), 400

    objective_guidance = {
        "cost": "Focus on cost reduction, process efficiency, and margin improvement opportunities.",
        "speed": "Focus on time-to-market acceleration, bottleneck removal, and velocity improvements.",
        "growth": "Focus on revenue expansion, market penetration, and new opportunity capture.",
        "balanced": "Consider a balanced mix of cost, growth, efficiency, and risk reduction.",
    }.get(objective, "Consider a balanced mix of cost, growth, efficiency, and risk reduction.")
    focus_clause = f" The user's specific focus area is: {focus}." if focus else ""

    system_prompt = (
        "You are a senior strategy analyst specializing in identifying executable business initiatives from operational data. "
        "You extract specific, actionable opportunities from raw data and frame them as business cases a leadership team can evaluate and score."
    )
    user_prompt = f"""
Analyze the following {data_description} and identify the top 3-5 strategic initiatives this organization should consider executing.

DATA:
{str(connector_data)[:4000]}

OBJECTIVE: {objective_guidance}{focus_clause}

Return ONLY a JSON array with this exact structure (no other text):
[
  {{
    "id": "idea_1",
    "title": "Short initiative title (under 10 words)",
    "description": "One paragraph describing the initiative, what it addresses, and why now is the right time based on the data.",
    "data_signal": "The specific data point or trend that identified this opportunity (quote actual numbers where possible).",
    "estimated_roi_band": "e.g. 15-25% cost reduction or $2-4M revenue uplift",
    "effort_level": "Low | Medium | High",
    "time_to_impact": "e.g. 3-6 months",
    "category": "cost_reduction | revenue_growth | operational_efficiency | risk_mitigation | market_expansion"
  }}
]

Be specific to the actual data. Do not generate generic ideas. Every idea must be directly traceable to a signal in the data provided.
"""

    try:
        client = get_llm_client()
        response = client.messages.create(
            model=current_app.config.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"),
            max_tokens=2000,
            temperature=0.3,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw_text = str(response.content[0].text or "").strip()
        if raw_text.startswith("```"):
            parts = raw_text.split("```")
            if len(parts) > 1:
                raw_text = parts[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
        ideas = json.loads(raw_text.strip())
        if not isinstance(ideas, list):
            ideas = []
    except Exception as exc:
        return jsonify({"error": f"AI analysis failed: {str(exc)}"}), 500

    for idea in ideas:
        if not isinstance(idea, dict):
            continue
        parts = [
            "I want to evaluate the following initiative for scoring:",
            f"\n\n**{idea.get('title', 'Strategic Initiative')}**",
            f"\n\n{idea.get('description', '')}",
        ]
        if idea.get("data_signal"):
            parts.append(f"\n\nKey data signal: {idea['data_signal']}")
        if idea.get("estimated_roi_band"):
            parts.append(f"\nEstimated ROI: {idea['estimated_roi_band']}")
        if idea.get("time_to_impact"):
            parts.append(f"\nExpected time to impact: {idea['time_to_impact']}")
        idea["prefill_statement"] = "".join(parts)

    return jsonify({
        "success": True,
        "connector_id": connector_id,
        "idea_count": len(ideas),
        "ideas": ideas,
    }), 200


@connectors_bp.route("/threads/<thread_id>/sync", methods=["GET"])
@jwt_required()
def get_thread_sync(thread_id):
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({"error": "User not found"}), 404

    readiness, profile, execution_views, connected_execution = _thread_sync_readiness_payload(user, thread_id)
    return jsonify({
        "thread_id": readiness.get("thread_id"),
        "preferred_pm_tool": readiness.get("preferred_pm_tool"),
        "thread_sync_status": readiness.get("thread_sync_status"),
        "wbs_exists": readiness.get("wbs_exists"),
        "sync_enabled": readiness.get("sync_enabled"),
        "connected_pm_tools": readiness.get("connected_pm_tools"),
        "available_pm_tools": readiness.get("available_pm_tools"),
        "message": readiness.get("message"),
        "thread_sync": profile,
        "execution_connectors": execution_views,
        "connected_execution_connectors": connected_execution,
    }), 200


@connectors_bp.route("/threads/<thread_id>/sync", methods=["PUT", "PATCH"])
@jwt_required()
def upsert_thread_sync(thread_id):
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({"error": "User not found"}), 404

    payload = request.get_json(silent=True) or {}
    _, views = _connector_views_for_user(user)
    execution_map = {
        item["id"]: item
        for item in _execution_connector_views(views)
    }
    connected_execution_ids = {
        item["id"]
        for item in execution_map.values()
        if item.get("connected")
    }

    preferred_pm_tool = payload.get("preferred_pm_tool")
    if preferred_pm_tool is None and "connector_ids" in payload:
        requested_connector_ids = payload.get("connector_ids")
        if not isinstance(requested_connector_ids, list):
            return jsonify({"error": "connector_ids must be an array of connector ids"}), 400
        connector_ids = []
        for value in requested_connector_ids:
            key = str(value or "").strip().lower()
            if key and key not in connector_ids:
                connector_ids.append(key)
        preferred_pm_tool = connector_ids[0] if connector_ids else None
    elif preferred_pm_tool is None:
        preferred_pm_tool = get_thread_sync_profile(user.id, thread_id).get("preferred_pm_tool")
    preferred_pm_tool = str(preferred_pm_tool or "").strip().lower() or None

    if preferred_pm_tool and preferred_pm_tool != "jaspen" and preferred_pm_tool not in execution_map:
        return jsonify(_error_payload(
            f"Connector '{preferred_pm_tool}' is not a PM execution connector",
            "CONNECTOR_NOT_FOUND",
            connector_id=preferred_pm_tool,
        )), 400

    connector_ids = [preferred_pm_tool] if preferred_pm_tool in execution_map else []

    for connector_id in connector_ids:
        if connector_id not in execution_map:
            return jsonify({"error": f"Connector '{connector_id}' is not a PM execution connector"}), 400
        if connector_id not in connected_execution_ids:
            return jsonify(_error_payload(
                f"Connector '{connector_id}' must be connected before it can be used for PM sync.",
                "CONNECTOR_NOT_CONNECTED",
                connector_id=connector_id,
            )), 400

    sync_mode = payload.get("sync_mode")
    if sync_mode is None:
        sync_mode = get_thread_sync_profile(user.id, thread_id).get("sync_mode") or "import"
    sync_mode = _normalize_sync_mode(sync_mode)
    if not sync_mode:
        return jsonify({"error": f"sync_mode must be one of {', '.join(SYNC_MODES)}"}), 400

    conflict_policy = payload.get("conflict_policy")
    if conflict_policy is None:
        conflict_policy = get_thread_sync_profile(user.id, thread_id).get("conflict_policy") or "prefer_external"
    conflict_policy = _normalize_conflict_policy(conflict_policy)
    if not conflict_policy:
        return jsonify({"error": f"conflict_policy must be one of {', '.join(CONFLICT_POLICIES)}"}), 400

    field_mapping = payload.get("field_mapping")
    if field_mapping is None:
        field_mapping = get_thread_sync_profile(user.id, thread_id).get("field_mapping") or {}
    if not isinstance(field_mapping, dict):
        return jsonify({"error": "field_mapping must be an object"}), 400

    if sync_mode in ("push", "two_way"):
        if preferred_pm_tool == "jaspen":
            return jsonify(_error_payload(
                "Jaspen-only tool selection does not support external push or two-way sync.",
                "NO_PM_TOOL_SELECTED",
                sync_mode=sync_mode,
            )), 400
        if not connector_ids:
            return jsonify({
                "error": "connector_ids must include at least one connected execution connector for push/two_way sync.",
                "sync_mode": sync_mode,
            }), 400
        for connector_id in connector_ids:
            if not execution_map[connector_id].get("allowed_write"):
                return jsonify({
                    "error": f"Connector '{connector_id}' does not support write sync on your current plan.",
                    "connector_id": connector_id,
                    "sync_mode": sync_mode,
                }), 403

    mirror_external_to_wbs = _to_bool(payload.get("mirror_external_to_wbs"), default=True)
    mirror_wbs_to_external = _to_bool(payload.get("mirror_wbs_to_external"), default=False)
    if sync_mode == "import":
        mirror_wbs_to_external = False
    elif sync_mode == "push":
        mirror_external_to_wbs = False
        mirror_wbs_to_external = True
    elif sync_mode == "two_way":
        mirror_external_to_wbs = True
        mirror_wbs_to_external = True

    saved = update_thread_sync_profile(
        user.id,
        thread_id,
        {
            "connector_ids": connector_ids,
            "preferred_pm_tool": preferred_pm_tool,
            "pm_tool_bound_at": _iso_now() if "preferred_pm_tool" in payload or "connector_ids" in payload else get_thread_sync_profile(user.id, thread_id).get("pm_tool_bound_at"),
            "sync_mode": sync_mode,
            "conflict_policy": conflict_policy,
            "field_mapping": field_mapping,
            "mirror_external_to_wbs": mirror_external_to_wbs,
            "mirror_wbs_to_external": mirror_wbs_to_external,
            "auto_reconcile": _to_bool(payload.get("auto_reconcile"), default=True),
            "auto_sync": _to_bool(payload.get("auto_sync"), default=get_thread_sync_profile(user.id, thread_id).get("auto_sync", True)),
            "thread_sync_status": "not_started" if preferred_pm_tool in (None, "jaspen") else "tool_selected",
        },
    )
    readiness, _, _, _ = _thread_sync_readiness_payload(user, thread_id)
    if readiness.get("thread_sync_status"):
        saved = update_thread_sync_profile(user.id, thread_id, {"thread_sync_status": readiness.get("thread_sync_status")})
    _audit_connector_event(
        "connector.sync_profile_updated",
        user=user,
        details={
            "thread_id": thread_id,
            "connector_ids": connector_ids,
            "preferred_pm_tool": preferred_pm_tool,
            "sync_mode": sync_mode,
            "conflict_policy": conflict_policy,
        },
    )

    return jsonify({
        "success": True,
        "thread_sync": saved,
        "thread_sync_status": saved.get("thread_sync_status"),
        "preferred_pm_tool": saved.get("preferred_pm_tool"),
        "execution_connectors": list(execution_map.values()),
    }), 200


@connectors_bp.route("/threads/<thread_id>/preferred-pm-tool", methods=["POST"])
@jwt_required()
def set_preferred_pm_tool(thread_id):
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({"error": "User not found"}), 404

    payload = request.get_json(silent=True) or {}
    preferred = str(payload.get("preferred_pm_tool") or "").strip().lower() or None
    if preferred == "null":
        preferred = None
    if preferred and preferred != "jaspen" and preferred not in EXECUTION_PM_CONNECTOR_IDS:
        return jsonify(_error_payload(
            f"Unsupported PM tool '{preferred}'",
            "CONNECTOR_NOT_FOUND",
            preferred_pm_tool=preferred,
        )), 400

    _, views = _connector_views_for_user(user)
    execution_views = {str(item.get("id") or "").strip().lower(): item for item in _execution_connector_views(views)}
    if preferred and preferred != "jaspen":
        view = execution_views.get(preferred)
        if not view:
            return jsonify(_error_payload(
                f"Connector '{preferred}' is not available on your plan",
                "CONNECTOR_NOT_FOUND",
                preferred_pm_tool=preferred,
            )), 400
        if not view.get("connected"):
            return jsonify(_error_payload(
                f"Connector '{preferred}' is not connected",
                "CONNECTOR_NOT_CONNECTED",
                preferred_pm_tool=preferred,
                lifecycle_status=view.get("lifecycle_status"),
            )), 400

    sync_mode = _normalize_sync_mode(payload.get("sync_mode") or get_thread_sync_profile(user.id, thread_id).get("sync_mode") or "import")
    if not sync_mode:
        return jsonify({"error": f"sync_mode must be one of {', '.join(SYNC_MODES)}"}), 400
    conflict_policy = _normalize_conflict_policy(payload.get("conflict_policy") or get_thread_sync_profile(user.id, thread_id).get("conflict_policy") or "prefer_external")
    if not conflict_policy:
        return jsonify({"error": f"conflict_policy must be one of {', '.join(CONFLICT_POLICIES)}"}), 400

    profile_updates = {
        "preferred_pm_tool": preferred,
        "pm_tool_bound_at": _iso_now(),
        "connector_ids": [preferred] if preferred and preferred != "jaspen" else [],
        "sync_mode": sync_mode,
        "conflict_policy": conflict_policy,
        "thread_sync_status": "not_started" if preferred in (None, "jaspen") else "tool_selected",
    }
    saved = update_thread_sync_profile(user.id, thread_id, profile_updates)
    readiness, _, _, _ = _thread_sync_readiness_payload(user, thread_id)
    saved = update_thread_sync_profile(user.id, thread_id, {"thread_sync_status": readiness.get("thread_sync_status")})

    return jsonify({
        "thread_id": str(thread_id),
        "preferred_pm_tool": saved.get("preferred_pm_tool"),
        "thread_sync_status": saved.get("thread_sync_status"),
        "pm_tool_bound_at": saved.get("pm_tool_bound_at"),
        "sync_mode": saved.get("sync_mode"),
        "conflict_policy": saved.get("conflict_policy"),
    }), 200


@connectors_bp.route("/threads/<thread_id>/jira/sync", methods=["POST"])
@jwt_required()
def sync_thread_to_jira(thread_id):
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({"error": "User not found"}), 404
    return _sync_thread_with_connector(user, thread_id, "jira_sync", sync_wbs_to_jira)


@connectors_bp.route("/threads/<thread_id>/smartsheet/sync", methods=["POST"])
@jwt_required()
def sync_thread_to_smartsheet(thread_id):
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({"error": "User not found"}), 404
    return _sync_thread_with_connector(user, thread_id, "smartsheet_sync", sync_wbs_to_smartsheet)


@connectors_bp.route("/threads/<thread_id>/<connector_id>/import", methods=["POST"])
@jwt_required()
def import_thread_from_pm_tool(thread_id, connector_id):
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({"error": "User not found"}), 404

    connector_id = str(connector_id or "").strip().lower()
    if connector_id not in EXECUTION_PM_CONNECTOR_IDS:
        return jsonify(_error_payload(
            f"Connector '{connector_id}' is not supported for import",
            "CONNECTOR_NOT_FOUND",
            connector_id=connector_id,
        )), 404

    settings = get_connector_settings(user.id, connector_id)
    lifecycle_status = _text(settings.get("lifecycle_status")).lower() or "disconnected"
    if lifecycle_status != "connected":
        return jsonify(_error_payload(
            f"Connector '{connector_id}' is not connected",
            "CONNECTOR_NOT_CONNECTED",
            connector_id=connector_id,
            lifecycle_status=lifecycle_status,
        )), 400

    scenarios, thread, project_wbs = _load_thread_wbs(user.id, thread_id)
    if thread is None:
        return jsonify(_error_payload("Thread not found", "THREAD_NOT_FOUND", thread_id=thread_id)), 404
    if not isinstance(project_wbs, dict):
        return jsonify(_error_payload("No WBS found for thread", "WBS_NOT_FOUND", thread_id=thread_id)), 404

    profile = get_thread_sync_profile(user.id, thread_id)
    preferred_tool = _text(profile.get("preferred_pm_tool")).lower() or None
    if preferred_tool and preferred_tool not in {"jaspen", connector_id}:
        return jsonify(_error_payload(
            f"Preferred PM tool is '{preferred_tool}', not '{connector_id}'",
            "PM_TOOL_NOT_CONNECTED",
            preferred_pm_tool=preferred_tool,
            connector_id=connector_id,
        )), 400

    if connector_id == "jira_sync":
        imported = import_tasks_from_jira(user.id, thread_id)
    else:
        imported = import_tasks_from_smartsheet(user.id, thread_id)

    if not imported.get("success"):
        reason = _text(imported.get("reason")) or "Import failed"
        mark_connector_sync_result(user.id, connector_id, "failed", error_message=reason)
        return jsonify(_error_payload(reason, "IMPORT_FAILED", connector_id=connector_id, thread_id=thread_id)), 400

    conflict_policy = _text(profile.get("conflict_policy") or "prefer_external").lower()
    merged_tasks = _merge_imported_tasks(
        project_wbs.get("tasks") if isinstance(project_wbs.get("tasks"), list) else [],
        imported.get("tasks") if isinstance(imported.get("tasks"), list) else [],
        conflict_policy=conflict_policy,
    )
    project_wbs["tasks"] = merged_tasks
    project_wbs["updated_at"] = _iso_now()
    thread["project_wbs"] = project_wbs
    scenarios[thread_id] = thread
    save_scenarios_data(user.id, scenarios)

    external_id_map = imported.get("external_id_map") if isinstance(imported.get("external_id_map"), dict) else {}
    update_thread_sync_profile(
        user.id,
        thread_id,
        {
            "thread_sync_status": "synced",
            "last_full_sync_at": _iso_now(),
            "last_webhook_received_at": _iso_now(),
            "wbs_task_external_ids_patch": external_id_map,
        },
    )
    mark_connector_sync_result(user.id, connector_id, "success")
    append_sync_audit_event(
        user.id,
        connector_id,
        action="import",
        status="success",
        thread_id=thread_id,
        attempt_count=imported.get("attempt_count"),
        duration_ms=imported.get("duration_ms"),
        message=f"Imported {len(imported.get('tasks') or [])} task(s)",
        metadata={"imported": len(imported.get("tasks") or [])},
    )

    return jsonify({
        "success": True,
        "thread_id": thread_id,
        "connector_id": connector_id,
        "thread_sync_status": "synced",
        "imported_task_count": len(imported.get("tasks") or []),
        "project_wbs": project_wbs,
    }), 200


@connectors_bp.route("/jira/webhook", methods=["POST"])
@limiter.limit("60 per minute")
def jira_webhook():
    unauthorized = _require_webhook_secret("jira")
    if unauthorized:
        return unauthorized

    payload = request.get_json(silent=True) or {}
    issue = payload.get("issue") if isinstance(payload.get("issue"), dict) else {}
    fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
    labels = fields.get("labels") if isinstance(fields.get("labels"), list) else []

    user_id = ""
    thread_id = ""
    task_id = ""
    for label in labels:
        text = str(label or "").strip()
        if text.startswith("jaspen_user_"):
            user_id = text[len("jaspen_user_"):]
        elif text.startswith("jaspen_thread_"):
            thread_id = text[len("jaspen_thread_"):]
        elif text.startswith("jaspen_task_"):
            task_id = text[len("jaspen_task_"):]

    if not user_id:
        return jsonify({"success": True, "ignored": True, "reason": "missing_user_label"}), 200

    issue_key = _text(issue.get("key"))
    if (not thread_id or not task_id) and issue_key:
        resolved_thread_id, resolved_task_id = _find_thread_task_by_external_id(user_id, "jira_sync", issue_key)
        if not thread_id and resolved_thread_id:
            thread_id = resolved_thread_id
        if not task_id and resolved_task_id:
            task_id = resolved_task_id

    result = apply_jira_webhook_to_wbs(
        user_id=user_id,
        issue=issue,
        enforce_thread_id=thread_id or None,
        enforce_task_id=task_id or None,
    )
    status = "success" if result.get("success") else "skipped" if result.get("ignored") else "failed"
    mark_connector_sync_result(user_id, "jira_sync", status, error_message=result.get("reason") or "")
    resolved_thread_id = _text(result.get("thread_id") or thread_id)
    if resolved_thread_id:
        profile_updates = {"last_webhook_received_at": _iso_now()}
        if status == "success":
            profile_updates["thread_sync_status"] = "synced"
        elif status == "failed":
            profile_updates["thread_sync_status"] = "error"
        update_thread_sync_profile(
            user_id,
            resolved_thread_id,
            profile_updates,
        )
    append_sync_audit_event(
        user_id,
        "jira_sync",
        action="webhook",
        status=status,
        thread_id=resolved_thread_id or None,
        message=_text(result.get("reason")),
        metadata={"source": "jira"},
    )
    return jsonify(result), 200


@connectors_bp.route("/smartsheet/webhook", methods=["POST"])
@limiter.limit("60 per minute")
def smartsheet_webhook():
    unauthorized = _require_webhook_secret("smartsheet")
    if unauthorized:
        return unauthorized

    payload = request.get_json(silent=True) or {}
    row = payload.get("row") if isinstance(payload.get("row"), dict) else {}
    metadata = row.get("jaspen_metadata") if isinstance(row.get("jaspen_metadata"), dict) else {}
    labels = row.get("labels") if isinstance(row.get("labels"), list) else []

    user_id = _text(metadata.get("user_id"))
    thread_id = _text(metadata.get("thread_id"))
    task_id = _text(metadata.get("task_id"))

    for label in labels:
        token = _text(label)
        if not user_id and token.startswith("jaspen_user_"):
            user_id = token[len("jaspen_user_"):]
        elif not thread_id and token.startswith("jaspen_thread_"):
            thread_id = token[len("jaspen_thread_"):]
        elif not task_id and token.startswith("jaspen_task_"):
            task_id = token[len("jaspen_task_"):]

    if not user_id:
        return jsonify({"success": True, "ignored": True, "reason": "missing_user_label"}), 200

    row_id = _text(row.get("id") or row.get("rowId"))
    if (not thread_id or not task_id) and row_id:
        resolved_thread_id, resolved_task_id = _find_thread_task_by_external_id(user_id, "smartsheet_sync", row_id)
        if not thread_id and resolved_thread_id:
            thread_id = resolved_thread_id
        if not task_id and resolved_task_id:
            task_id = resolved_task_id

    result = apply_smartsheet_webhook_to_wbs(
        user_id=user_id,
        payload=payload,
        enforce_thread_id=thread_id or None,
        enforce_task_id=task_id or None,
    )
    status = "success" if result.get("success") else "skipped" if result.get("ignored") else "failed"
    mark_connector_sync_result(user_id, "smartsheet_sync", status, error_message=result.get("reason") or "")
    resolved_thread_id = _text(result.get("thread_id") or thread_id)
    if resolved_thread_id:
        profile_updates = {"last_webhook_received_at": _iso_now()}
        if status == "success":
            profile_updates["thread_sync_status"] = "synced"
        elif status == "failed":
            profile_updates["thread_sync_status"] = "error"
        update_thread_sync_profile(
            user_id,
            resolved_thread_id,
            profile_updates,
        )
    append_sync_audit_event(
        user_id,
        "smartsheet_sync",
        action="webhook",
        status=status,
        thread_id=resolved_thread_id or None,
        message=_text(result.get("reason")),
        metadata={"source": "smartsheet"},
    )
    return jsonify(result), 200
