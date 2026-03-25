from datetime import datetime, timedelta

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import or_

from app.access_controls import (
    APPROVAL_APPROVED,
    APPROVAL_PENDING,
    APPROVAL_REJECTED,
    APPROVAL_STATUSES,
    access_review_summary,
    get_access_controls,
    normalize_access_controls,
    save_access_controls,
)
from app import db, limiter
from app.admin_audit import append_admin_audit_event, list_admin_audit_events
from app.admin_policy import is_global_admin
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
    get_all_connector_settings,
    get_connector_settings,
    save_connector_state,
    update_connector_settings,
)
from app.models import User, UserSession
from app.tool_registry import get_context_budget, get_tool_entitlements


admin_bp = Blueprint("admin", __name__)
ADMIN_ALLOWED_CONNECTOR_FIELDS = {"connection_status", "auto_sync"}


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


def _serialize_user_for_admin(user):
    if not user:
        return None
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "email_verified": bool(user.email_verified),
        "email_verified_at": user.email_verified_at.isoformat() if user.email_verified_at else None,
        "email_verification_sent_at": user.email_verification_sent_at.isoformat() if user.email_verification_sent_at else None,
        "subscription_plan": to_public_plan(user.subscription_plan),
        "credits_remaining": user.credits_remaining,
        "seat_limit": user.seat_limit,
        "max_seats": user.max_seats,
        "unlimited_analysis": bool(user.unlimited_analysis),
        "max_concurrent_sessions": user.max_concurrent_sessions,
        "referral_code": user.referral_code,
        "referrals_earned": user.referrals_earned,
        "referred_by_user_id": user.referred_by_user_id,
        "signup_referral_code_used": user.signup_referral_code_used,
        "access_approval_status": str(user.access_approval_status or APPROVAL_APPROVED),
        "access_approved_at": user.access_approved_at.isoformat() if user.access_approved_at else None,
        "access_reviewed_by_user_id": user.access_reviewed_by_user_id,
        "deactivated_at": user.deactivated_at.isoformat() if user.deactivated_at else None,
        "deactivated_by_user_id": user.deactivated_by_user_id,
        "deactivation_reason": user.deactivation_reason,
        "recovery_expires_at": user.recovery_expires_at.isoformat() if user.recovery_expires_at else None,
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


def _session_chat_history(payload):
    if not isinstance(payload, dict):
        return []
    chat_history = payload.get("chat_history")
    if isinstance(chat_history, list):
        return chat_history
    result_blob = payload.get("result")
    if isinstance(result_blob, dict) and isinstance(result_blob.get("chat_history"), list):
        return result_blob.get("chat_history")
    return []


def _normalize_feedback_payload(value):
    if not isinstance(value, dict):
        return None
    feedback_value = str(value.get("value") or "").strip().lower()
    if feedback_value not in {"up", "down"}:
        return None
    updated_at = str(value.get("updated_at") or "").strip() or None
    return {
        "value": feedback_value,
        "updated_at": updated_at,
    }


def _message_excerpt(content, max_len=220):
    text = " ".join(str(content or "").split())
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 1].rstrip()}…"


def _collect_message_feedback(user_id=None, value=None, query=None, limit=100):
    rows = UserSession.query
    if user_id:
        rows = rows.filter(UserSession.user_id == user_id)
    scan_limit = max(limit * 12, 250)
    scan_limit = min(scan_limit, 1500)
    rows = (
        rows
        .order_by(UserSession.updated_at.desc(), UserSession.id.desc())
        .limit(scan_limit)
        .all()
    )

    user_ids = sorted({row.user_id for row in rows if row.user_id})
    users = {
        user.id: user
        for user in User.query.filter(User.id.in_(user_ids)).all()
    } if user_ids else {}

    lowered_query = str(query or "").strip().lower()
    items = []
    for row in rows:
        payload = row.payload if isinstance(row.payload, dict) else {}
        user = users.get(row.user_id)
        for idx, message in enumerate(_session_chat_history(payload)):
            if not isinstance(message, dict):
                continue
            if str(message.get("role") or "").strip().lower() != "assistant":
                continue
            feedback = _normalize_feedback_payload(message.get("feedback"))
            if not feedback:
                continue
            if value and feedback["value"] != value:
                continue
            excerpt = _message_excerpt(message.get("content"))
            searchable = " ".join(filter(None, [
                getattr(user, "email", "") or "",
                getattr(user, "name", "") or "",
                str(row.name or ""),
                str(row.session_id or ""),
                excerpt,
            ])).lower()
            if lowered_query and lowered_query not in searchable:
                continue
            items.append({
                "session_row_id": row.id,
                "thread_id": row.session_id,
                "session_name": row.name,
                "user_id": row.user_id,
                "user_email": getattr(user, "email", None),
                "user_name": getattr(user, "name", None),
                "feedback_value": feedback["value"],
                "feedback_updated_at": feedback.get("updated_at"),
                "message_index": idx,
                "message_excerpt": excerpt,
                "document_type": row.document_type,
                "status": row.status,
                "strategy_objective": payload.get("strategy_objective") if isinstance(payload.get("strategy_objective"), str) else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            })

    items.sort(key=lambda item: (item.get("feedback_updated_at") or "", item.get("updated_at") or ""), reverse=True)
    items = items[:limit]
    up_count = sum(1 for item in items if item.get("feedback_value") == "up")
    down_count = sum(1 for item in items if item.get("feedback_value") == "down")
    total = len(items)
    return {
        "items": items,
        "summary": {
            "total_feedback": total,
            "up_count": up_count,
            "down_count": down_count,
            "positive_rate": round((up_count / total) * 100, 1) if total else 0.0,
            "unique_users": len({item.get("user_id") for item in items if item.get("user_id")}),
        },
    }


def _collect_provider_health(user_id=None, provider=None, limit=50):
    rows = UserSession.query
    if user_id:
        rows = rows.filter(UserSession.user_id == user_id)
    scan_limit = max(limit * 12, 250)
    scan_limit = min(scan_limit, 2000)
    rows = (
        rows
        .order_by(UserSession.updated_at.desc(), UserSession.id.desc())
        .limit(scan_limit)
        .all()
    )

    user_ids = sorted({row.user_id for row in rows if row.user_id})
    users = {
        user.id: user
        for user in User.query.filter(User.id.in_(user_ids)).all()
    } if user_ids else {}

    provider_filter = str(provider or "").strip().lower() or None
    recent_failovers = []
    provider_summary = {}
    total_events = 0
    failover_events = 0

    for row in rows:
        payload = row.payload if isinstance(row.payload, dict) else {}
        usage_events = payload.get("usage_events") if isinstance(payload.get("usage_events"), list) else []
        if not usage_events:
            continue
        user = users.get(row.user_id)
        for event in usage_events:
            if not isinstance(event, dict):
                continue
            final_provider = str(event.get("provider") or "unknown").strip().lower() or "unknown"
            if provider_filter and final_provider != provider_filter:
                continue

            total_events += 1
            failover = event.get("failover") if isinstance(event.get("failover"), dict) else {}
            attempted = failover.get("attempted_providers") if isinstance(failover.get("attempted_providers"), list) else []
            failover_count = _to_int(failover.get("failover_count"), default=0) or 0
            if attempted or failover_count > 0:
                failover_events += 1

            summary = provider_summary.setdefault(final_provider, {
                "provider": final_provider,
                "events": 0,
                "failover_events": 0,
                "avg_failover_count": 0.0,
                "models": {},
            })
            summary["events"] += 1
            if attempted or failover_count > 0:
                summary["failover_events"] += 1
                summary["avg_failover_count"] += failover_count

            final_model = str(event.get("model") or failover.get("final_model") or "unknown").strip() or "unknown"
            model_summary = summary["models"].setdefault(final_model, {
                "model": final_model,
                "events": 0,
                "failover_events": 0,
            })
            model_summary["events"] += 1
            if attempted or failover_count > 0:
                model_summary["failover_events"] += 1

            if attempted or failover_count > 0:
                recent_failovers.append({
                    "timestamp": event.get("timestamp"),
                    "thread_id": row.session_id,
                    "session_name": row.name,
                    "user_id": row.user_id,
                    "user_email": getattr(user, "email", None),
                    "user_name": getattr(user, "name", None),
                    "final_provider": final_provider,
                    "final_model": final_model,
                    "failover_count": failover_count,
                    "attempted_providers": attempted,
                })

    provider_items = []
    for item in provider_summary.values():
        failover_count_total = item["avg_failover_count"]
        failover_event_count = item["failover_events"]
        item["avg_failover_count"] = round(
            (failover_count_total / failover_event_count),
            2,
        ) if failover_event_count else 0.0
        item["failover_rate"] = round((failover_event_count / item["events"]) * 100, 1) if item["events"] else 0.0
        item["models"] = sorted(
            item["models"].values(),
            key=lambda model_item: (model_item.get("failover_events") or 0, model_item.get("events") or 0),
            reverse=True,
        )
        provider_items.append(item)

    provider_items.sort(key=lambda item: (item.get("failover_events") or 0, item.get("events") or 0), reverse=True)
    recent_failovers.sort(key=lambda item: item.get("timestamp") or "", reverse=True)

    return {
        "summary": {
            "total_events": total_events,
            "failover_events": failover_events,
            "failover_rate": round((failover_events / total_events) * 100, 1) if total_events else 0.0,
            "unique_users": len({item.get("user_id") for item in recent_failovers if item.get("user_id")}),
        },
        "providers": provider_items,
        "recent_failovers": recent_failovers[:limit],
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
    if not is_global_admin(user, app_config=current_app.config):
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


def _connector_views_for_user(user):
    connector_settings = get_all_connector_settings(user.id)
    items = []

    for connector in get_connector_catalog():
        connector_id = connector.get("id")
        settings = connector_settings.get(connector_id) or get_connector_settings(user.id, connector_id)

        raw_connection_status = str(settings.get("connection_status") or "disconnected").strip().lower()
        if raw_connection_status not in ("connected", "disconnected"):
            raw_connection_status = "disconnected"
        health_status = str(settings.get("health_status") or "unknown").strip().lower() or "unknown"
        consecutive_failures = _to_int(settings.get("consecutive_failures"), default=0)

        item = {
            "id": connector_id,
            "label": connector.get("label") or connector_id,
            "group": connector.get("group") or "data",
            "connection_status": raw_connection_status,
            "health_status": health_status,
            "consecutive_failures": max(0, consecutive_failures or 0),
            "auto_sync": _to_bool(settings.get("auto_sync"), default=True),
            "last_sync_at": settings.get("last_sync_at"),
            "sync_mode": str(settings.get("sync_mode") or "").strip().lower() or None,
        }
        items.append(item)
    return items


@admin_bp.route("/capabilities", methods=["GET"])
@jwt_required()
def capabilities():
    user, err = _current_user()
    if err:
        return err
    return jsonify({
        "is_admin": is_global_admin(user, app_config=current_app.config),
        "email": user.email,
        "admin_scope": "global",
        "org_admin_enabled": False,
    }), 200


@admin_bp.route("/access-controls", methods=["GET"])
@jwt_required()
def get_access_controls_view():
    _, err = _require_admin()
    if err:
        return err

    return jsonify({
        "controls": get_access_controls(current_app.config),
        "review": access_review_summary(limit=_to_int(request.args.get("limit"), default=25)),
    }), 200


@admin_bp.route("/access-controls", methods=["PATCH"])
@jwt_required()
@limiter.limit("20 per minute")
def patch_access_controls():
    admin_user, err = _require_admin()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    before = get_access_controls(current_app.config)
    normalized = normalize_access_controls(data, app_config=current_app.config)
    save_access_controls(normalized, app_config=current_app.config)
    db.session.commit()

    _audit(
        admin_user,
        "access_controls.patch",
        details={
            "before": before,
            "after": normalized,
        },
    )
    return jsonify({
        "success": True,
        "controls": normalized,
        "review": access_review_summary(limit=25),
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
    }), 200


@admin_bp.route("/users", methods=["GET"])
@jwt_required()
def list_users():
    _, err = _require_admin()
    if err:
        return err

    query = str(request.args.get("q") or "").strip()
    status = str(request.args.get("status") or "").strip().lower()
    limit = _to_int(request.args.get("limit"), default=50)
    limit = max(1, min(200, limit or 50))

    q = User.query
    if query:
        like = f"%{query}%"
        q = q.filter(or_(User.email.ilike(like), User.name.ilike(like)))
    if status:
        if status == "active":
            q = q.filter(User.deactivated_at.is_(None), User.access_approval_status == APPROVAL_APPROVED)
        elif status == "pending":
            q = q.filter(User.deactivated_at.is_(None), User.access_approval_status == APPROVAL_PENDING)
        elif status == "rejected":
            q = q.filter(User.deactivated_at.is_(None), User.access_approval_status == APPROVAL_REJECTED)
        elif status == "deactivated":
            q = q.filter(User.deactivated_at.is_not(None))
        else:
            return jsonify({"error": "status must be one of active, pending, rejected, deactivated"}), 400

    users = q.order_by(User.updated_at.desc()).limit(limit).all()
    return jsonify({
        "users": [_serialize_user_for_admin(user) for user in users],
        "count": len(users),
        "status": status or "",
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
    return jsonify({"user": _serialize_user_for_admin(user)}), 200


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

    before = _serialize_user_for_admin(user)
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

    if "access_approval_status" in data:
        access_status = str(data.get("access_approval_status") or "").strip().lower()
        if access_status not in APPROVAL_STATUSES:
            return jsonify({"error": f"access_approval_status must be one of {sorted(APPROVAL_STATUSES)}"}), 400
        user.access_approval_status = access_status
        user.access_reviewed_by_user_id = admin_user.id
        if access_status == APPROVAL_APPROVED:
            user.access_approved_at = datetime.utcnow()
        else:
            user.access_approved_at = None

    db.session.commit()
    after = _serialize_user_for_admin(user)
    changed_fields = {}
    for key, value in after.items():
        if before.get(key) != value:
            changed_fields[key] = {"before": before.get(key), "after": value}

    _audit(admin_user, "user.patch", target_user=user, details={"changed_fields": changed_fields})
    return jsonify({"success": True, "user": after}), 200


@admin_bp.route("/users/<user_id>/deactivate", methods=["POST"])
@jwt_required()
@limiter.limit("10 per minute")
def deactivate_user(user_id):
    admin_user, err = _require_admin()
    if err:
        return err

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    if user.id == admin_user.id:
        return jsonify({"error": "You cannot deactivate your own admin account."}), 400
    if is_global_admin(user, app_config=current_app.config):
        return jsonify({"error": "Global admin accounts cannot be deactivated here."}), 400

    payload = request.get_json(silent=True) or {}
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        return jsonify({"error": "reason is required"}), 400
    recovery_days = _to_int(payload.get("recovery_days"), default=30)
    recovery_days = max(1, min(90, recovery_days or 30))

    now = datetime.utcnow()
    user.deactivated_at = now
    user.deactivated_by_user_id = admin_user.id
    user.deactivation_reason = reason
    user.recovery_expires_at = now + timedelta(days=recovery_days)
    user.auth_token_version = int(user.auth_token_version or 0) + 1
    db.session.commit()

    _audit(
        admin_user,
        "user.deactivated",
        target_user=user,
        details={
            "reason": reason,
            "recovery_days": recovery_days,
            "recovery_expires_at": user.recovery_expires_at.isoformat() if user.recovery_expires_at else None,
        },
    )
    return jsonify({"success": True, "user": _serialize_user_for_admin(user)}), 200


@admin_bp.route("/users/<user_id>/restore", methods=["POST"])
@jwt_required()
@limiter.limit("10 per minute")
def restore_user(user_id):
    admin_user, err = _require_admin()
    if err:
        return err

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    if user.deactivated_at is None:
        return jsonify({"error": "User is not deactivated."}), 400
    if user.recovery_expires_at and user.recovery_expires_at < datetime.utcnow():
        return jsonify({"error": "Recovery window has expired for this user."}), 400

    payload = request.get_json(silent=True) or {}
    reason = str(payload.get("reason") or "").strip() or None

    user.deactivated_at = None
    user.deactivated_by_user_id = None
    user.deactivation_reason = None
    user.recovery_expires_at = None
    user.auth_token_version = int(user.auth_token_version or 0) + 1
    db.session.commit()

    _audit(
        admin_user,
        "user.restored",
        target_user=user,
        details={"reason": reason},
    )
    return jsonify({"success": True, "user": _serialize_user_for_admin(user)}), 200


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
    return jsonify({"success": True, "user": _serialize_user_for_admin(user)}), 200


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
    return jsonify({"success": True, "user": _serialize_user_for_admin(user), "credits_before": before, "credits_after": after}), 200


@admin_bp.route("/users/<user_id>/connectors", methods=["GET"])
@jwt_required()
def get_user_connectors(user_id):
    _, err = _require_admin()
    if err:
        return err

    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    connectors = _connector_views_for_user(user)
    return jsonify({
        "user_id": user.id,
        "connectors": connectors,
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
    unsupported_fields = sorted(set(payload.keys()) - ADMIN_ALLOWED_CONNECTOR_FIELDS)
    if unsupported_fields:
        return jsonify({"error": f"Unsupported connector fields: {', '.join(unsupported_fields)}"}), 400

    before = next(
        (item for item in _connector_views_for_user(user) if item.get("id") == connector_id),
        None,
    )
    updates = {}

    if "connection_status" in payload:
        status = str(payload.get("connection_status") or "").strip().lower()
        if status not in ("connected", "disconnected"):
            return jsonify({"error": "connection_status must be connected or disconnected"}), 400
        updates["connection_status"] = status

    if "auto_sync" in payload:
        updates["auto_sync"] = _to_bool(payload.get("auto_sync"), default=True)

    update_connector_settings(user.id, connector_id, updates)
    connectors = _connector_views_for_user(user)
    connector_view = next((item for item in connectors if item.get("id") == connector_id), None)

    _audit(
        admin_user,
        "user.connector.patch",
        target_user=user,
        details={
            "connector_id": connector_id,
            "updates": updates,
            "before": before,
            "after": connector_view,
        },
    )

    return jsonify({
        "success": True,
        "connector": connector_view,
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
    return jsonify({"success": True, "result": result, "user": _serialize_user_for_admin(user)}), 200


@admin_bp.route("/audit", methods=["GET"])
@admin_bp.route("/audit-log", methods=["GET"])
@jwt_required()
def get_audit_events():
    _, err = _require_admin()
    if err:
        return err

    target_user_id = str(request.args.get("user_id") or "").strip() or None
    action = str(request.args.get("action") or "").strip().lower() or None
    date_from = str(request.args.get("date_from") or "").strip() or None
    date_to = str(request.args.get("date_to") or "").strip() or None
    limit = _to_int(request.args.get("limit"), default=50)
    events = list_admin_audit_events(
        user_id=target_user_id,
        action=action,
        date_from=date_from,
        date_to=date_to,
        limit=limit or 50,
    )
    return jsonify({"events": events, "count": len(events)}), 200


@admin_bp.route("/message-feedback", methods=["GET"])
@jwt_required()
def get_message_feedback():
    _, err = _require_admin()
    if err:
        return err

    user_id = str(request.args.get("user_id") or "").strip() or None
    value = str(request.args.get("value") or "").strip().lower() or None
    if value and value not in {"up", "down"}:
        return jsonify({"error": "value must be one of up or down"}), 400
    query = str(request.args.get("q") or "").strip() or None
    limit = _to_int(request.args.get("limit"), default=100)
    limit = max(1, min(250, limit or 100))

    result = _collect_message_feedback(user_id=user_id, value=value, query=query, limit=limit)
    return jsonify({
        "items": result["items"],
        "summary": result["summary"],
        "count": len(result["items"]),
        "filters": {
            "user_id": user_id,
            "value": value,
            "q": query,
            "limit": limit,
        },
    }), 200


@admin_bp.route("/provider-health", methods=["GET"])
@jwt_required()
def get_provider_health():
    _, err = _require_admin()
    if err:
        return err

    user_id = str(request.args.get("user_id") or "").strip() or None
    provider = str(request.args.get("provider") or "").strip().lower() or None
    if provider and provider not in {"anthropic", "gemini", "heuristic", "unknown"}:
        return jsonify({"error": "provider must be one of anthropic, gemini, heuristic, unknown"}), 400
    limit = _to_int(request.args.get("limit"), default=50)
    limit = max(1, min(250, limit or 50))

    result = _collect_provider_health(user_id=user_id, provider=provider, limit=limit)
    return jsonify({
        "summary": result["summary"],
        "providers": result["providers"],
        "recent_failovers": result["recent_failovers"],
        "count": len(result["recent_failovers"]),
        "filters": {
            "user_id": user_id,
            "provider": provider,
            "limit": limit,
        },
    }), 200
