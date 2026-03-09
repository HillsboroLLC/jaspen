import os

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.models import User
from app.billing_config import to_public_plan
from app.connector_registry import (
    get_connector_catalog,
    get_connector_definition,
    get_execution_connector_ids,
)
from app.connector_store import (
    CONFLICT_POLICIES,
    SYNC_MODES,
    get_all_connector_settings,
    get_connector_settings,
    get_thread_sync_profile,
    update_connector_settings,
    update_thread_sync_profile,
)
from app.jira_sync import apply_jira_webhook_to_wbs, sync_wbs_to_jira
from app.scenarios_store import load_scenarios_data, save_scenarios_data
from app.tool_registry import get_tool_entitlements


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
        "updated_at": settings.get("updated_at"),
    }
    if connector_id == "jira_sync":
        payload["jira"] = {
            "base_url": settings.get("jira_base_url") or "",
            "project_key": settings.get("jira_project_key") or settings.get("external_workspace") or "",
            "email": settings.get("jira_email") or "",
            "issue_type": settings.get("jira_issue_type") or "",
            "has_api_token": bool(settings.get("jira_api_token")),
            "field_mapping": settings.get("jira_field_mapping") if isinstance(settings.get("jira_field_mapping"), dict) else {},
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
        "external_workspace": str(payload.get("external_workspace") or current.get("external_workspace") or "").strip(),
    }
    if connector_id == "jira_sync":
        jira_mapping = payload.get("jira_field_mapping")
        updates.update({
            "jira_base_url": str(payload.get("jira_base_url") if "jira_base_url" in payload else persisted_settings.get("jira_base_url") or "").strip(),
            "jira_project_key": str(payload.get("jira_project_key") if "jira_project_key" in payload else persisted_settings.get("jira_project_key") or "").strip(),
            "jira_email": str(payload.get("jira_email") if "jira_email" in payload else persisted_settings.get("jira_email") or "").strip(),
            "jira_api_token": str(payload.get("jira_api_token") if "jira_api_token" in payload else persisted_settings.get("jira_api_token") or "").strip(),
            "jira_issue_type": str(payload.get("jira_issue_type") if "jira_issue_type" in payload else persisted_settings.get("jira_issue_type") or "").strip(),
            "jira_field_mapping": jira_mapping if isinstance(jira_mapping, dict) else (persisted_settings.get("jira_field_mapping") or {}),
        })
    saved = update_connector_settings(user.id, connector_id, updates)
    _, updated_views = _connector_views_for_user(user)
    updated_view = next((item for item in updated_views if item["id"] == connector_id), None)

    return jsonify({
        "success": True,
        "plan_key": plan_key,
        "connector": updated_view,
        "saved_settings": saved,
    }), 200


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

    scenarios = load_scenarios_data(user.id)
    thread = scenarios.get(thread_id)
    if not isinstance(thread, dict):
        return jsonify({"error": "Thread not found"}), 404
    project_wbs = thread.get("project_wbs")
    if not isinstance(project_wbs, dict):
        return jsonify({"error": "No WBS found for thread"}), 404

    profile = get_thread_sync_profile(user.id, thread_id)
    result = sync_wbs_to_jira(user.id, thread_id, project_wbs, thread_sync_profile=profile)
    next_wbs = result.get("project_wbs")
    if isinstance(next_wbs, dict):
        thread["project_wbs"] = next_wbs
        scenarios[thread_id] = thread
        save_scenarios_data(user.id, scenarios)

    return jsonify({
        "success": bool(result.get("success")),
        "thread_id": thread_id,
        "sync_result": result,
    }), 200


@connectors_bp.route("/jira/webhook", methods=["POST"])
def jira_webhook():
    configured_secret = (
        current_app.config.get("JIRA_WEBHOOK_SECRET")
        or os.getenv("JIRA_WEBHOOK_SECRET")
        or ""
    ).strip()
    provided_secret = (
        request.headers.get("X-Jaspen-Webhook-Secret")
        or request.args.get("secret")
        or ""
    ).strip()
    if configured_secret and provided_secret != configured_secret:
        return jsonify({"error": "Unauthorized webhook"}), 401

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
    return jsonify(result), 200
