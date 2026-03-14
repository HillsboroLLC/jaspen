import os
from urllib.parse import urlencode

from flask import Blueprint, current_app, jsonify, redirect, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app import limiter
from app.billing_config import to_public_plan
from app.connectors.smartsheet import smartsheet_connect, smartsheet_list_sheets
from app.connectors.workfront import workfront_connect, workfront_sync_status
from app.connector_registry import (
    get_connector_catalog,
    get_connector_definition,
    get_execution_connector_ids,
)
from app.connector_store import (
    CONFLICT_POLICIES,
    SYNC_MODES,
    append_sync_audit_event,
    get_all_connector_settings,
    get_connector_settings,
    get_sync_audit_events,
    get_thread_sync_profile,
    mark_connector_sync_result,
    redact_connector_settings,
    update_connector_settings,
    update_thread_sync_profile,
)
from app.jira_sync import apply_jira_webhook_to_wbs, sync_wbs_to_jira
from app.models import User
from app.scenarios_store import load_scenarios_data, save_scenarios_data
from app.salesforce_sync import (
    BadSignature as SalesforceBadSignature,
    SignatureExpired as SalesforceStateExpired,
    decode_salesforce_oauth_state,
    encode_salesforce_oauth_state,
    exchange_salesforce_code,
    fetch_pipeline_summary,
    salesforce_authorize_url,
    salesforce_missing_oauth_config,
    salesforce_runtime_config,
)
from app.smartsheet_sync import apply_smartsheet_webhook_to_wbs, sync_wbs_to_smartsheet
from app.snowflake_insights import extract_kpi_metrics, run_allowlisted_query
from app.tool_registry import get_tool_entitlements
from app.workfront_sync import apply_workfront_webhook_to_wbs, sync_wbs_to_workfront


connectors_bp = Blueprint("connectors", __name__)


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



def _frontend_base_url():
    return (current_app.config.get("FRONTEND_BASE_URL") or "http://localhost:3000").rstrip("/")


def _safe_next_path(candidate):
    path = str(candidate or "").strip()
    if not path or not path.startswith("/") or path.startswith("//"):
        return "/account?tab=connectors"
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
    configured = _text(
        current_app.config.get("SALESFORCE_REDIRECT_URI")
        or os.getenv("SALESFORCE_REDIRECT_URI")
    )
    if configured:
        return configured
    return f"{request.url_root.rstrip('/')}/api/connectors/salesforce/oauth/callback"


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

    if connector_id == "workfront_sync":
        return {
            "workfront_base_url": _text(settings.get("workfront_base_url") or os.getenv("WORKFRONT_BASE_URL")),
            "workfront_project_id": _text(
                settings.get("workfront_project_id")
                or settings.get("external_workspace")
                or os.getenv("WORKFRONT_PROJECT_ID")
            ),
            "workfront_api_token": _text(settings.get("workfront_api_token") or os.getenv("WORKFRONT_API_TOKEN")),
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
        return {
            "salesforce_auth_base_url": _text(
                settings.get("salesforce_auth_base_url")
                or os.getenv("SALESFORCE_AUTH_BASE_URL")
                or "https://login.salesforce.com"
            ),
            "salesforce_instance_url": _text(settings.get("salesforce_instance_url") or os.getenv("SALESFORCE_INSTANCE_URL")),
            "salesforce_client_id": _text(settings.get("salesforce_client_id") or os.getenv("SALESFORCE_CLIENT_ID")),
            "salesforce_client_secret": _text(settings.get("salesforce_client_secret") or os.getenv("SALESFORCE_CLIENT_SECRET")),
            "salesforce_refresh_token": _text(settings.get("salesforce_refresh_token") or os.getenv("SALESFORCE_REFRESH_TOKEN")),
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
        if "snowflake_password" in missing and "snowflake_private_key" in missing:
            missing = [field for field in missing if field not in {"snowflake_password", "snowflake_private_key"}]
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

    connected = enabled and connection_status == "connected"
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
    elif connector_id == "workfront_sync":
        missing_fields = _missing_required_fields(connector_id, settings)
        payload["workfront"] = {
            "base_url": settings.get("workfront_base_url") or "",
            "project_id": settings.get("workfront_project_id") or settings.get("external_workspace") or "",
            "has_api_token": bool(settings.get("workfront_api_token")),
            "configuration_complete": len(missing_fields) == 0,
            "missing_required_fields": missing_fields,
            "field_mapping": settings.get("workfront_field_mapping") if isinstance(settings.get("workfront_field_mapping"), dict) else {},
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



def _sync_thread_with_connector(user, thread_id, connector_id, sync_callable):
    scenarios, thread, project_wbs = _load_thread_wbs(user.id, thread_id)
    if thread is None:
        return jsonify({"error": "Thread not found"}), 404
    if project_wbs is None:
        return jsonify({"error": "No WBS found for thread"}), 404

    profile = get_thread_sync_profile(user.id, thread_id)
    result = sync_callable(user.id, thread_id, project_wbs, thread_sync_profile=profile)
    next_wbs = result.get("project_wbs")
    if isinstance(next_wbs, dict):
        thread["project_wbs"] = next_wbs
        scenarios[thread_id] = thread
        save_scenarios_data(user.id, scenarios)

    status = "success" if result.get("success") else "skipped" if result.get("skipped") else "failed"
    error_message = ""
    errors = result.get("errors") if isinstance(result.get("errors"), list) else []
    if errors:
        error_message = _text(errors[0].get("error")) if isinstance(errors[0], dict) else _text(errors[0])
    elif result.get("reason"):
        error_message = _text(result.get("reason"))

    mark_connector_sync_result(user.id, connector_id, status, error_message=error_message)
    append_sync_audit_event(
        user.id,
        connector_id,
        action="thread_sync",
        status=status,
        thread_id=thread_id,
        attempt_count=result.get("attempt_count"),
        duration_ms=result.get("duration_ms"),
        message=error_message,
        metadata={
            "created": result.get("created_issues") or result.get("created_tasks") or result.get("created_rows") or 0,
            "updated": result.get("updated_tasks") or 0,
        },
    )

    return jsonify({
        "success": bool(result.get("success")),
        "status": status,
        "thread_id": thread_id,
        "connector_id": connector_id,
        "sync_result": result,
    }), 200



def _read_webhook_secret(config_key, env_key):
    return (
        current_app.config.get(config_key)
        or os.getenv(env_key)
        or ""
    ).strip()



def _provided_webhook_secret():
    return (
        request.headers.get("X-Jaspen-Webhook-Secret")
        or request.args.get("secret")
        or ""
    ).strip()



def _require_webhook_secret(config_key, env_key):
    configured_secret = _read_webhook_secret(config_key, env_key)
    provided_secret = _provided_webhook_secret()
    if configured_secret and provided_secret != configured_secret:
        return jsonify({"error": "Unauthorized webhook"}), 401
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

    elif connector_id == "workfront_sync":
        mapping = payload.get("workfront_field_mapping")
        for field in ("workfront_base_url", "workfront_project_id"):
            _apply_field_update(updates, payload, persisted_settings, field)
        if "workfront_api_token" in payload:
            updates["workfront_api_token"] = _text(payload.get("workfront_api_token"))
        updates["workfront_field_mapping"] = mapping if isinstance(mapping, dict) else (persisted_settings.get("workfront_field_mapping") or {})

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
        if connector_id == "workfront_sync":
            valid = workfront_connect(
                candidate_settings.get("workfront_base_url"),
                candidate_settings.get("workfront_api_token"),
            )
            if not valid:
                return jsonify({
                    "error": "Unable to validate Workfront credentials. Check URL and API token.",
                    "connector_id": connector_id,
                }), 400
        if connector_id == "smartsheet_sync":
            valid = smartsheet_connect(candidate_settings.get("smartsheet_api_token"))
            if not valid:
                return jsonify({
                    "error": "Unable to validate Smartsheet token.",
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
    if connector_id == "workfront_sync":
        live_status = workfront_sync_status(
            {
                "base_url": settings.get("workfront_base_url"),
                "api_key": settings.get("workfront_api_token"),
                "project_id": settings.get("workfront_project_id"),
                "last_sync_at": settings.get("last_sync_at"),
            }
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

    next_path = _safe_next_path(request.args.get("next") or "/account?tab=connectors")
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

    state = encode_salesforce_oauth_state(secret, {"user_id": str(user.id), "next": next_path})
    auth_url = salesforce_authorize_url(
        config=config,
        state_token=state,
        redirect_uri=_salesforce_callback_url(),
        scope=request.args.get("scope"),
    )
    return jsonify({"success": True, "auth_url": auth_url, "next": next_path}), 200


@connectors_bp.route("/salesforce/oauth/callback", methods=["GET"])
def salesforce_oauth_callback():
    state_token = _text(request.args.get("state"))
    code = _text(request.args.get("code"))
    oauth_error = _text(request.args.get("error"))

    if oauth_error:
        # Best effort parse state for redirect target.
        try:
            state_data = decode_salesforce_oauth_state(
                _salesforce_state_secret(),
                state_token,
                max_age_seconds=int(os.getenv("SALESFORCE_OAUTH_STATE_TTL_SECONDS", "900")),
            )
            return _frontend_redirect(
                (state_data or {}).get("next") or "/account?tab=connectors",
                {"sf_oauth": "error", "reason": oauth_error},
            )
        except Exception:
            return _frontend_redirect("/account?tab=connectors", {"sf_oauth": "error", "reason": oauth_error})

    if not code or not state_token:
        return _frontend_redirect("/account?tab=connectors", {"sf_oauth": "error", "reason": "missing_code_or_state"})

    try:
        state_data = decode_salesforce_oauth_state(
            _salesforce_state_secret(),
            state_token,
            max_age_seconds=int(os.getenv("SALESFORCE_OAUTH_STATE_TTL_SECONDS", "900")),
        )
    except SalesforceStateExpired:
        return _frontend_redirect("/account?tab=connectors", {"sf_oauth": "error", "reason": "state_expired"})
    except SalesforceBadSignature:
        return _frontend_redirect("/account?tab=connectors", {"sf_oauth": "error", "reason": "invalid_state"})
    except Exception:
        return _frontend_redirect("/account?tab=connectors", {"sf_oauth": "error", "reason": "invalid_state"})

    user_id = _text((state_data or {}).get("user_id"))
    next_path = _safe_next_path((state_data or {}).get("next") or "/account?tab=connectors")
    if not user_id:
        return _frontend_redirect(next_path, {"sf_oauth": "error", "reason": "missing_user_context"})

    user = User.query.get(user_id)
    if not user:
        return _frontend_redirect(next_path, {"sf_oauth": "error", "reason": "user_not_found"})

    try:
        config = salesforce_runtime_config(user.id)
        token_payload, token_meta = exchange_salesforce_code(
            config=config,
            code=code,
            redirect_uri=_salesforce_callback_url(),
        )
        updates = {
            "connection_status": "connected",
            "salesforce_instance_url": _text(token_payload.get("instance_url") or config.get("instance_url")),
            "salesforce_access_token": _text(token_payload.get("access_token")),
            "salesforce_token_type": _text(token_payload.get("token_type") or "Bearer") or "Bearer",
        }
        refresh_token = _text(token_payload.get("refresh_token"))
        if refresh_token:
            updates["salesforce_refresh_token"] = refresh_token

        update_connector_settings(user.id, "salesforce_insights", updates)
        mark_connector_sync_result(user.id, "salesforce_insights", "success")
        append_sync_audit_event(
            user.id,
            "salesforce_insights",
            action="oauth_callback",
            status="success",
            attempt_count=token_meta.get("attempt_count"),
            duration_ms=token_meta.get("duration_ms"),
            message="Salesforce OAuth connected",
            metadata={"token_refreshed": bool(refresh_token)},
        )
        return _frontend_redirect(next_path, {"sf_oauth": "success"})
    except Exception as exc:
        mark_connector_sync_result(user.id, "salesforce_insights", "failed", error_message=str(exc))
        append_sync_audit_event(
            user.id,
            "salesforce_insights",
            action="oauth_callback",
            status="failed",
            message=str(exc),
        )
        return _frontend_redirect(next_path, {"sf_oauth": "error", "reason": "token_exchange_failed"})


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


@connectors_bp.route("/threads/<thread_id>/sync", methods=["GET"])
@jwt_required()
def get_thread_sync(thread_id):
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({"error": "User not found"}), 404

    _, views = _connector_views_for_user(user)
    execution_views = _execution_connector_views(views)
    connected_execution = [item for item in execution_views if item.get("connected")]
    profile = get_thread_sync_profile(user.id, thread_id)

    if not profile.get("connector_ids") and connected_execution:
        profile["connector_ids"] = [connected_execution[0]["id"]]

    return jsonify({
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

    requested_connector_ids = payload.get("connector_ids")
    if requested_connector_ids is None:
        requested_connector_ids = get_thread_sync_profile(user.id, thread_id).get("connector_ids") or []
    if not isinstance(requested_connector_ids, list):
        return jsonify({"error": "connector_ids must be an array of connector ids"}), 400
    connector_ids = []
    for value in requested_connector_ids:
        key = str(value or "").strip().lower()
        if key and key not in connector_ids:
            connector_ids.append(key)

    for connector_id in connector_ids:
        if connector_id not in execution_map:
            return jsonify({"error": f"Connector '{connector_id}' is not a PM execution connector"}), 400
        if connector_id not in connected_execution_ids:
            return jsonify({
                "error": f"Connector '{connector_id}' must be connected before it can be used for PM sync.",
                "connector_id": connector_id,
            }), 400

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
            "sync_mode": sync_mode,
            "conflict_policy": conflict_policy,
            "field_mapping": field_mapping,
            "mirror_external_to_wbs": mirror_external_to_wbs,
            "mirror_wbs_to_external": mirror_wbs_to_external,
            "auto_reconcile": _to_bool(payload.get("auto_reconcile"), default=True),
        },
    )

    return jsonify({
        "success": True,
        "thread_sync": saved,
        "execution_connectors": list(execution_map.values()),
    }), 200


@connectors_bp.route("/threads/<thread_id>/jira/sync", methods=["POST"])
@jwt_required()
def sync_thread_to_jira(thread_id):
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({"error": "User not found"}), 404
    return _sync_thread_with_connector(user, thread_id, "jira_sync", sync_wbs_to_jira)


@connectors_bp.route("/threads/<thread_id>/workfront/sync", methods=["POST"])
@jwt_required()
def sync_thread_to_workfront(thread_id):
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({"error": "User not found"}), 404
    return _sync_thread_with_connector(user, thread_id, "workfront_sync", sync_wbs_to_workfront)


@connectors_bp.route("/threads/<thread_id>/smartsheet/sync", methods=["POST"])
@jwt_required()
def sync_thread_to_smartsheet(thread_id):
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({"error": "User not found"}), 404
    return _sync_thread_with_connector(user, thread_id, "smartsheet_sync", sync_wbs_to_smartsheet)


@connectors_bp.route("/jira/webhook", methods=["POST"])
@limiter.limit("60 per minute")
def jira_webhook():
    unauthorized = _require_webhook_secret("JIRA_WEBHOOK_SECRET", "JIRA_WEBHOOK_SECRET")
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

    result = apply_jira_webhook_to_wbs(
        user_id=user_id,
        issue=issue,
        enforce_thread_id=thread_id or None,
        enforce_task_id=task_id or None,
    )
    status = "success" if result.get("success") else "skipped" if result.get("ignored") else "failed"
    mark_connector_sync_result(user_id, "jira_sync", status, error_message=result.get("reason") or "")
    append_sync_audit_event(
        user_id,
        "jira_sync",
        action="webhook",
        status=status,
        thread_id=thread_id or None,
        message=_text(result.get("reason")),
        metadata={"source": "jira"},
    )
    return jsonify(result), 200


@connectors_bp.route("/workfront/webhook", methods=["POST"])
@limiter.limit("60 per minute")
def workfront_webhook():
    unauthorized = _require_webhook_secret("WORKFRONT_WEBHOOK_SECRET", "WORKFRONT_WEBHOOK_SECRET")
    if unauthorized:
        return unauthorized

    payload = request.get_json(silent=True) or {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    metadata = data.get("jaspenMetadata") if isinstance(data.get("jaspenMetadata"), dict) else {}
    labels = data.get("tags") if isinstance(data.get("tags"), list) else []

    user_id = _text(metadata.get("jaspen_user_id"))
    thread_id = _text(metadata.get("jaspen_thread_id"))
    task_id = _text(metadata.get("jaspen_task_id"))

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

    result = apply_workfront_webhook_to_wbs(
        user_id=user_id,
        payload=payload,
        enforce_thread_id=thread_id or None,
        enforce_task_id=task_id or None,
    )
    status = "success" if result.get("success") else "skipped" if result.get("ignored") else "failed"
    mark_connector_sync_result(user_id, "workfront_sync", status, error_message=result.get("reason") or "")
    append_sync_audit_event(
        user_id,
        "workfront_sync",
        action="webhook",
        status=status,
        thread_id=thread_id or None,
        message=_text(result.get("reason")),
        metadata={"source": "workfront"},
    )
    return jsonify(result), 200


@connectors_bp.route("/smartsheet/webhook", methods=["POST"])
@limiter.limit("60 per minute")
def smartsheet_webhook():
    unauthorized = _require_webhook_secret("SMARTSHEET_WEBHOOK_SECRET", "SMARTSHEET_WEBHOOK_SECRET")
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

    result = apply_smartsheet_webhook_to_wbs(
        user_id=user_id,
        payload=payload,
        enforce_thread_id=thread_id or None,
        enforce_task_id=task_id or None,
    )
    status = "success" if result.get("success") else "skipped" if result.get("ignored") else "failed"
    mark_connector_sync_result(user_id, "smartsheet_sync", status, error_message=result.get("reason") or "")
    append_sync_audit_event(
        user_id,
        "smartsheet_sync",
        action="webhook",
        status=status,
        thread_id=thread_id or None,
        message=_text(result.get("reason")),
        metadata={"source": "smartsheet"},
    )
    return jsonify(result), 200
