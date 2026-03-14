from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import or_

from app import db, limiter
from app.admin_audit import append_admin_audit_event, list_admin_audit_events
from app.admin_policy import is_global_admin_email
from app.billing_config import (
    apply_plan_to_user,
    get_allowed_model_types,
    get_default_model_type,
    get_monthly_credit_limit,
    get_plan_catalog,
    normalize_plan_key,
    to_public_plan,
)
from app.connector_registry import get_connector_catalog, get_connector_definition
from app.connector_store import (
    CONFLICT_POLICIES,
    SYNC_MODES,
    get_all_connector_settings,
    get_connector_settings,
    save_connector_state,
    update_connector_settings,
)
from app.models import User, UserSession
from app.tool_registry import get_context_budget, get_tool_entitlements


admin_bp = Blueprint("admin", __name__)


def _to_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _to_int(value, default=None):
    try:
        return int(value)
    except Exception:
        return default


def _request_meta():
    return {
        "remote_addr": request.headers.get("X-Forwarded-For", request.remote_addr),
        "user_agent": request.headers.get("User-Agent"),
    }


def _serialize_user(user):
    if not user:
        return None
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "subscription_plan": to_public_plan(user.subscription_plan),
        "credits_remaining": user.credits_remaining,
        "seat_limit": user.seat_limit,
        "max_seats": user.max_seats,
        "unlimited_analysis": bool(user.unlimited_analysis),
        "max_concurrent_sessions": user.max_concurrent_sessions,
        "stripe_customer_id": user.stripe_customer_id,
        "stripe_subscription_id": user.stripe_subscription_id,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
    }


def _serialize_session(row):
    payload = row.payload if isinstance(row.payload, dict) else {}
    chat_history = payload.get("chat_history") if isinstance(payload.get("chat_history"), list) else []
    return {
        "id": row.id,
        "user_id": row.user_id,
        "session_id": row.session_id,
        "name": row.name,
        "document_type": row.document_type,
        "status": row.status,
        "chat_messages": len(chat_history),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _current_user():
    user = User.query.get(get_jwt_identity())
    if not user:
        return None, (jsonify({"error": "User not found"}), 404)
    return user, None


def _require_admin():
    user, err = _current_user()
    if err:
        return None, err
    if not is_global_admin_email(user.email, current_app.config):
        return None, (jsonify({"error": "Admin access required"}), 403)
    return user, None


def _audit(admin_user, action, target_user=None, details=None):
    meta = _request_meta()
    append_admin_audit_event(
        actor_user_id=admin_user.id,
        actor_email=admin_user.email,
        action=action,
        target_user_id=target_user.id if target_user else None,
        target_email=target_user.email if target_user else None,
        details=details if isinstance(details, dict) else {},
        remote_addr=meta.get("remote_addr"),
        user_agent=meta.get("user_agent"),
    )


def _connector_entitlements(plan_key):
    entitlements = get_tool_entitlements(plan_key)
    return {
        item.get("id"): item
        for item in entitlements
        if str(item.get("type") or "").lower() == "connector"
    }


def _connector_views_for_user(user):
    plan_key = to_public_plan(user.subscription_plan)
    entitlements = _connector_entitlements(plan_key)
    connector_settings = get_all_connector_settings(user.id)
    items = []

    for connector in get_connector_catalog():
        connector_id = connector.get("id")
        entitlement = entitlements.get(connector_id) or {}
        settings = connector_settings.get(connector_id) or get_connector_settings(user.id, connector_id)

        enabled = bool(entitlement.get("enabled"))
        allowed_read = bool(entitlement.get("allowed_read"))
        allowed_write = bool(entitlement.get("allowed_write"))
        available_sync_modes = ["import", "push", "two_way"] if allowed_write else (["import"] if allowed_read else [])

        raw_connection_status = str(settings.get("connection_status") or "disconnected").strip().lower()
        if raw_connection_status not in ("connected", "disconnected"):
            raw_connection_status = "disconnected"
        connected = enabled and raw_connection_status == "connected"
        sync_mode = str(settings.get("sync_mode") or "import").strip().lower()
        if sync_mode not in SYNC_MODES:
            sync_mode = "import"

        item = {
            "id": connector_id,
            "label": connector.get("label") or connector_id,
            "group": connector.get("group") or "data",
            "description": connector.get("description") or "",
            "supports_pm_sync": bool(connector.get("supports_pm_sync")),
            "required_min_tier": entitlement.get("required_min_tier"),
            "enabled": enabled,
            "allowed_read": allowed_read,
            "allowed_write": allowed_write,
            "available_sync_modes": list(SYNC_MODES) if allowed_write else available_sync_modes,
            "connection_status": "connected" if connected else "disconnected",
            "raw_connection_status": raw_connection_status,
            "sync_mode": sync_mode,
            "conflict_policy": settings.get("conflict_policy") or "prefer_external",
            "available_conflict_policies": list(CONFLICT_POLICIES),
            "auto_sync": _to_bool(settings.get("auto_sync"), default=True),
            "external_workspace": settings.get("external_workspace") or "",
            "updated_at": settings.get("updated_at"),
            "last_sync_at": settings.get("last_sync_at"),
        }
        if connector_id == "jira_sync":
            item["jira"] = {
                "base_url": settings.get("jira_base_url") or "",
                "project_key": settings.get("jira_project_key") or "",
                "email": settings.get("jira_email") or "",
                "issue_type": settings.get("jira_issue_type") or "",
                "has_api_token": bool(settings.get("jira_api_token")),
                "field_mapping": settings.get("jira_field_mapping") if isinstance(settings.get("jira_field_mapping"), dict) else {},
            }
        items.append(item)
    return plan_key, items


@admin_bp.route("/capabilities", methods=["GET"])
@jwt_required()
def capabilities():
    user, err = _current_user()
    if err:
        return err
    return jsonify({
        "is_admin": is_global_admin_email(user.email, current_app.config),
        "email": user.email,
        "admin_scope": "global",
        "org_admin_enabled": False,
    }), 200


@admin_bp.route("/preview/workspace", methods=["GET"])
@jwt_required()
def workspace_preview():
    _, err = _require_admin()
    if err:
        return err

    plan_key = normalize_plan_key(request.args.get("plan_key") or "free")
    plan_catalog = get_plan_catalog(current_app.config)
    if plan_key not in plan_catalog:
        return jsonify({"error": f"Unknown plan '{plan_key}'"}), 400

    monthly_limit = get_monthly_credit_limit(plan_key, current_app.config)
    return jsonify({
        "preview": True,
        "preview_type": "workspace",
        "preview_plan_key": plan_key,
        "plan_key": plan_key,
        "plan": plan_catalog.get(plan_key) or {},
        # Hide admin affordances while previewing the customer-facing surface.
        "is_admin": False,
        "credits_remaining": monthly_limit,
        "monthly_credit_limit": monthly_limit,
        "credits_used": 0 if monthly_limit is not None else None,
        "allowed_model_types": get_allowed_model_types(plan_key, current_app.config),
        "default_model_type": get_default_model_type(plan_key, current_app.config),
        "context_budget": get_context_budget(plan_key),
        "tool_entitlements": get_tool_entitlements(plan_key),
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
    }), 200


@admin_bp.route("/users", methods=["GET"])
@jwt_required()
def list_users():
    _, err = _require_admin()
    if err:
        return err

    query = str(request.args.get("q") or "").strip()
    limit = _to_int(request.args.get("limit"), default=50)
    limit = max(1, min(200, limit or 50))

    q = User.query
    if query:
        like = f"%{query}%"
        q = q.filter(or_(User.email.ilike(like), User.name.ilike(like)))

    users = q.order_by(User.updated_at.desc()).limit(limit).all()
    return jsonify({
        "users": [_serialize_user(user) for user in users],
        "count": len(users),
    }), 200


@admin_bp.route("/users/<user_id>", methods=["GET"])
@jwt_required()
def get_user(user_id):
    _, err = _require_admin()
    if err:
        return err

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    return jsonify({"user": _serialize_user(user)}), 200


@admin_bp.route("/users/<user_id>", methods=["PATCH"])
@jwt_required()
@limiter.limit("30 per minute")
def patch_user(user_id):
    admin_user, err = _require_admin()
    if err:
        return err

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    before = _serialize_user(user)
    data = request.get_json(silent=True) or {}
    plan_catalog = get_plan_catalog(current_app.config)
    allowed_plans = set(plan_catalog.keys())

    if "name" in data:
        name = str(data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name cannot be empty"}), 400
        if len(name) > 255:
            return jsonify({"error": "name is too long"}), 400
        user.name = name

    if "subscription_plan" in data:
        desired_plan = normalize_plan_key(data.get("subscription_plan"))
        if desired_plan not in allowed_plans:
            return jsonify({"error": f"subscription_plan must be one of {sorted(allowed_plans)}"}), 400
        user.subscription_plan = desired_plan

    if "credits_remaining" in data:
        value = data.get("credits_remaining")
        if value in (None, "", "null"):
            user.credits_remaining = None
        else:
            credits = _to_int(value)
            if credits is None:
                return jsonify({"error": "credits_remaining must be an integer or null"}), 400
            if credits < 0:
                return jsonify({"error": "credits_remaining cannot be negative"}), 400
            user.credits_remaining = credits

    if "seat_limit" in data:
        seat_limit = _to_int(data.get("seat_limit"))
        if seat_limit is None:
            return jsonify({"error": "seat_limit must be an integer"}), 400
        if seat_limit < 0:
            return jsonify({"error": "seat_limit cannot be negative"}), 400
        user.seat_limit = seat_limit

    if "max_seats" in data:
        max_seats = _to_int(data.get("max_seats"))
        if max_seats is None:
            return jsonify({"error": "max_seats must be an integer"}), 400
        if max_seats < 0:
            return jsonify({"error": "max_seats cannot be negative"}), 400
        user.max_seats = max_seats

    if "unlimited_analysis" in data:
        user.unlimited_analysis = _to_bool(data.get("unlimited_analysis"), default=False)

    if "max_concurrent_sessions" in data:
        value = data.get("max_concurrent_sessions")
        if value in (None, "", "null"):
            user.max_concurrent_sessions = None
        else:
            sessions = _to_int(value)
            if sessions is None:
                return jsonify({"error": "max_concurrent_sessions must be an integer or null"}), 400
            if sessions < 1:
                return jsonify({"error": "max_concurrent_sessions must be at least 1 when set"}), 400
            user.max_concurrent_sessions = sessions

    if "stripe_customer_id" in data:
        user.stripe_customer_id = str(data.get("stripe_customer_id") or "").strip() or None
    if "stripe_subscription_id" in data:
        user.stripe_subscription_id = str(data.get("stripe_subscription_id") or "").strip() or None

    db.session.commit()
    after = _serialize_user(user)
    changed_fields = {}
    for key, value in after.items():
        if before.get(key) != value:
            changed_fields[key] = {"before": before.get(key), "after": value}

    _audit(admin_user, "user.patch", target_user=user, details={"changed_fields": changed_fields})
    return jsonify({"success": True, "user": after}), 200


@admin_bp.route("/users/<user_id>/force-plan", methods=["POST"])
@jwt_required()
@limiter.limit("20 per minute")
def force_plan(user_id):
    admin_user, err = _require_admin()
    if err:
        return err

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json(silent=True) or {}
    desired_plan = normalize_plan_key(data.get("plan_key") or "essential")
    plan_catalog = get_plan_catalog(current_app.config)
    if desired_plan not in plan_catalog:
        return jsonify({"error": f"plan_key must be one of {sorted(plan_catalog.keys())}"}), 400

    reset_credits = _to_bool(data.get("reset_credits"), default=True)
    before_plan = to_public_plan(user.subscription_plan)
    before_credits = user.credits_remaining
    apply_plan_to_user(user, desired_plan, current_app.config, reset_credits=reset_credits)
    db.session.commit()

    _audit(
        admin_user,
        "user.force_plan",
        target_user=user,
        details={
            "before_plan": before_plan,
            "after_plan": to_public_plan(user.subscription_plan),
            "before_credits": before_credits,
            "after_credits": user.credits_remaining,
            "reset_credits": reset_credits,
        },
    )
    return jsonify({"success": True, "user": _serialize_user(user)}), 200


@admin_bp.route("/users/<user_id>/credits", methods=["POST"])
@jwt_required()
@limiter.limit("20 per minute")
def adjust_user_credits(user_id):
    admin_user, err = _require_admin()
    if err:
        return err

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json(silent=True) or {}
    mode = str(data.get("mode") or "adjust").strip().lower()
    reason = str(data.get("reason") or "").strip()
    if not reason:
        return jsonify({"error": "reason is required"}), 400
    if len(reason) > 500:
        return jsonify({"error": "reason is too long"}), 400

    before = user.credits_remaining
    if mode == "adjust":
        delta = _to_int(data.get("delta"))
        if delta is None or delta == 0:
            return jsonify({"error": "delta must be a non-zero integer"}), 400
        if user.credits_remaining is None:
            return jsonify({"error": "Cannot adjust unlimited credits. Use mode=set with a numeric value first."}), 400
        next_value = int(user.credits_remaining) + int(delta)
        if next_value < 0:
            return jsonify({"error": "Adjustment would make credits negative"}), 400
        user.credits_remaining = next_value
    elif mode == "set":
        value = data.get("value")
        if value in (None, "", "null"):
            user.credits_remaining = None
        else:
            next_value = _to_int(value)
            if next_value is None:
                return jsonify({"error": "value must be an integer or null"}), 400
            if next_value < 0:
                return jsonify({"error": "value cannot be negative"}), 400
            user.credits_remaining = next_value
    elif mode == "reset_plan":
        current_plan = to_public_plan(user.subscription_plan)
        user.credits_remaining = get_monthly_credit_limit(current_plan, current_app.config)
    else:
        return jsonify({"error": "mode must be one of adjust, set, reset_plan"}), 400

    db.session.commit()
    after = user.credits_remaining
    _audit(
        admin_user,
        "user.credits",
        target_user=user,
        details={
            "mode": mode,
            "reason": reason,
            "before_credits": before,
            "after_credits": after,
            "delta": _to_int(data.get("delta")),
            "value": data.get("value"),
        },
    )
    return jsonify({"success": True, "user": _serialize_user(user), "credits_before": before, "credits_after": after}), 200


@admin_bp.route("/users/<user_id>/connectors", methods=["GET"])
@jwt_required()
def get_user_connectors(user_id):
    _, err = _require_admin()
    if err:
        return err

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    plan_key, connectors = _connector_views_for_user(user)
    return jsonify({
        "user_id": user.id,
        "plan_key": plan_key,
        "connectors": connectors,
        "sync_modes": list(SYNC_MODES),
        "conflict_policies": list(CONFLICT_POLICIES),
    }), 200


@admin_bp.route("/users/<user_id>/connectors/<connector_id>", methods=["PATCH"])
@jwt_required()
@limiter.limit("30 per minute")
def patch_user_connector(user_id, connector_id):
    admin_user, err = _require_admin()
    if err:
        return err

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    connector_id = str(connector_id or "").strip().lower()
    if not get_connector_definition(connector_id):
        return jsonify({"error": f"Unknown connector '{connector_id}'"}), 404

    payload = request.get_json(silent=True) or {}
    before = get_connector_settings(user.id, connector_id)
    updates = {}

    if "connection_status" in payload:
        status = str(payload.get("connection_status") or "").strip().lower()
        if status not in ("connected", "disconnected"):
            return jsonify({"error": "connection_status must be connected or disconnected"}), 400
        updates["connection_status"] = status

    if "sync_mode" in payload:
        mode = str(payload.get("sync_mode") or "").strip().lower()
        if mode not in SYNC_MODES:
            return jsonify({"error": f"sync_mode must be one of {', '.join(SYNC_MODES)}"}), 400
        updates["sync_mode"] = mode

    if "conflict_policy" in payload:
        policy = str(payload.get("conflict_policy") or "").strip().lower()
        if policy not in CONFLICT_POLICIES:
            return jsonify({"error": f"conflict_policy must be one of {', '.join(CONFLICT_POLICIES)}"}), 400
        updates["conflict_policy"] = policy

    if "auto_sync" in payload:
        updates["auto_sync"] = _to_bool(payload.get("auto_sync"), default=True)

    if "external_workspace" in payload:
        updates["external_workspace"] = str(payload.get("external_workspace") or "").strip()

    if connector_id == "jira_sync":
        if "jira_base_url" in payload:
            updates["jira_base_url"] = str(payload.get("jira_base_url") or "").strip()
        if "jira_project_key" in payload:
            updates["jira_project_key"] = str(payload.get("jira_project_key") or "").strip()
        if "jira_email" in payload:
            updates["jira_email"] = str(payload.get("jira_email") or "").strip()
        if "jira_api_token" in payload:
            updates["jira_api_token"] = str(payload.get("jira_api_token") or "").strip()
        if "jira_issue_type" in payload:
            updates["jira_issue_type"] = str(payload.get("jira_issue_type") or "").strip()
        if "jira_field_mapping" in payload:
            mapping = payload.get("jira_field_mapping")
            if mapping is not None and not isinstance(mapping, dict):
                return jsonify({"error": "jira_field_mapping must be an object"}), 400
            updates["jira_field_mapping"] = mapping or {}

    saved = update_connector_settings(user.id, connector_id, updates)
    _, connectors = _connector_views_for_user(user)
    connector_view = next((item for item in connectors if item.get("id") == connector_id), None)

    _audit(
        admin_user,
        "user.connector.patch",
        target_user=user,
        details={
            "connector_id": connector_id,
            "updates": updates,
            "before": before,
            "after": saved,
        },
    )

    return jsonify({
        "success": True,
        "connector": connector_view,
        "saved_settings": saved,
    }), 200


@admin_bp.route("/users/<user_id>/sessions", methods=["GET"])
@jwt_required()
def list_user_sessions(user_id):
    _, err = _require_admin()
    if err:
        return err

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    limit = _to_int(request.args.get("limit"), default=25)
    limit = max(1, min(100, limit or 25))
    rows = (
        UserSession.query
        .filter_by(user_id=user.id)
        .order_by(UserSession.updated_at.desc(), UserSession.id.desc())
        .limit(limit)
        .all()
    )
    return jsonify({
        "user_id": user.id,
        "count": len(rows),
        "sessions": [_serialize_session(row) for row in rows],
    }), 200


@admin_bp.route("/users/<user_id>/recovery", methods=["POST"])
@jwt_required()
@limiter.limit("5 per minute")
def run_user_recovery(user_id):
    admin_user, err = _require_admin()
    if err:
        return err

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    payload = request.get_json(silent=True) or {}
    action = str(payload.get("action") or "").strip().lower()
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        return jsonify({"error": "reason is required"}), 400

    result = {"action": action}
    if action == "clear_sessions":
        deleted = UserSession.query.filter_by(user_id=user.id).delete(synchronize_session=False)
        result["deleted_sessions"] = int(deleted or 0)
    elif action == "clear_connectors":
        save_connector_state(user.id, {"connectors": {}, "thread_sync": {}})
        result["cleared_connectors"] = True
    elif action == "reset_plan_defaults":
        before = user.credits_remaining
        current_plan = to_public_plan(user.subscription_plan)
        apply_plan_to_user(user, current_plan, current_app.config, reset_credits=True)
        result["before_credits"] = before
        result["after_credits"] = user.credits_remaining
        result["plan"] = current_plan
    elif action == "clear_billing_links":
        user.stripe_customer_id = None
        user.stripe_subscription_id = None
        result["cleared_billing_links"] = True
    else:
        return jsonify({"error": "action must be one of clear_sessions, clear_connectors, reset_plan_defaults, clear_billing_links"}), 400

    db.session.commit()
    _audit(admin_user, "user.recovery", target_user=user, details={"reason": reason, **result})
    return jsonify({"success": True, "result": result, "user": _serialize_user(user)}), 200


@admin_bp.route("/audit", methods=["GET"])
@jwt_required()
def get_audit_events():
    _, err = _require_admin()
    if err:
        return err

    target_user_id = str(request.args.get("user_id") or "").strip() or None
    limit = _to_int(request.args.get("limit"), default=50)
    events = list_admin_audit_events(user_id=target_user_id, limit=limit or 50)
    return jsonify({"events": events, "count": len(events)}), 200
