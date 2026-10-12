from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app import db
from app.connector_store import encrypt_token, get_connector_settings, update_connector_settings
from app.models import User
from app.models_pm_sync import PmSyncBinding, PmSyncLink
from app.pm_sync.jira_adapter import create_project, list_projects, test_connection
from app.pm_sync.reconciliation import list_logs, reconcile_binding
from app.pm_sync.service import MODES, POLICIES, STATUSES, create_binding, get_plan, preview, push_binding

pm_sync_bp = Blueprint("pm_sync", __name__)


def _user():
    return User.query.get(get_jwt_identity())


def _owned(binding_id, user_id):
    return PmSyncBinding.query.filter_by(id=binding_id, user_id=user_id).first()


def _error(exc, status=400):
    return jsonify({"error": str(exc), "code": "PM_SYNC_ERROR"}), status


def _jira_auth_failure(value):
    text = str(value or "")
    return "HTTP 401" in text or "HTTP 403" in text


def _jira_connection(user_id):
    settings = get_connector_settings(user_id, "jira_sync")
    return {
        "base_url": str(settings.get("jira_base_url") or "").strip(),
        "email": str(settings.get("jira_email") or "").strip(),
        "has_api_token": bool(settings.get("jira_api_token")),
    }


def _reconnect_response(user, binding=None):
    if binding is not None:
        binding.status = "reconnect_required"
        db.session.commit()
    return jsonify({
        "error": "Your saved Jira connection no longer works. Enter a new API token to continue.",
        "code": "JIRA_RECONNECT_REQUIRED",
        "connection": _jira_connection(user.id),
        "binding": binding.to_dict() if binding is not None else None,
    }), 401


def _result_has_auth_failure(result):
    errors = result.get("errors") if isinstance(result, dict) and isinstance(result.get("errors"), list) else []
    return any(_jira_auth_failure(item.get("error") if isinstance(item, dict) else item) for item in errors)


@pm_sync_bp.route("/jira/projects", methods=["GET"])
@jwt_required()
def jira_projects():
    user = _user()
    if not user:
        return _error("User not found", 404)
    try:
        return jsonify({"projects": list_projects(user.id), "connection": _jira_connection(user.id)})
    except Exception as exc:
        if _jira_auth_failure(exc):
            return _reconnect_response(user)
        return jsonify({
            "error": "Jira projects could not be loaded. Check your Jira connection and try again.",
            "code": "JIRA_PROJECTS_UNAVAILABLE",
            "connection": _jira_connection(user.id),
        }), 502


@pm_sync_bp.route("/jira/test-connection", methods=["POST"])
@jwt_required()
def jira_test_connection():
    """Probe transient credentials. Nothing is persisted by this endpoint."""
    try:
        return jsonify(test_connection(request.get_json(silent=True) or {}))
    except Exception as exc:
        if _jira_auth_failure(exc):
            return jsonify({"error": "Jira rejected those credentials. Check the email and enter a new API token.", "code": "JIRA_AUTH_FAILED"}), 401
        return jsonify({"error": "Could not connect to Jira. Check the site URL, email, and API token.", "code": "JIRA_CONNECTION_FAILED"}), 400


@pm_sync_bp.route("/jira/connect", methods=["POST"])
@jwt_required()
def jira_connect():
    user = _user()
    if not user:
        return _error("User not found", 404)
    payload = request.get_json(silent=True) or {}
    try:
        probe = test_connection(payload)
        token = str(payload.get("jira_api_token") or "").strip()
        if token and not encrypt_token(token).startswith("enc::"):
            raise ValueError("Connector credential encryption is not configured. Set CONNECTOR_ENCRYPTION_KEY before saving Jira credentials.")
        saved = update_connector_settings(user.id, "jira_sync", {
            "jira_base_url": str(payload.get("jira_base_url") or "").strip(),
            "jira_email": str(payload.get("jira_email") or "").strip(),
            "jira_api_token": token,
            "connection_status": "connected", "lifecycle_status": "connected",
            "last_verified_at": __import__("datetime").datetime.utcnow().isoformat(),
        })
        return jsonify({
            "success": True, "base_url": probe["base_url"],
            "email": str(payload.get("jira_email") or "").strip(),
            "has_api_token": bool(saved.get("jira_api_token")),
        })
    except Exception as exc:
        if _jira_auth_failure(exc):
            return jsonify({"error": "Jira rejected those credentials. Nothing was saved. Enter a new API token.", "code": "JIRA_AUTH_FAILED"}), 401
        if "CONNECTOR_ENCRYPTION_KEY" in str(exc):
            return _error(exc)
        return jsonify({"error": "Could not connect to Jira. Nothing was saved. Check the site URL, email, and API token.", "code": "JIRA_CONNECTION_FAILED"}), 400


@pm_sync_bp.route("/jira/projects", methods=["POST"])
@jwt_required()
def jira_create_project():
    user = _user()
    if not user:
        return _error("User not found", 404)
    try:
        return jsonify({"project": create_project(user.id, request.get_json(silent=True) or {})}), 201
    except Exception as exc:
        if _jira_auth_failure(exc):
            return _reconnect_response(user)
        return _error(exc)


@pm_sync_bp.route("/preview", methods=["GET"])
@jwt_required()
def binding_preview():
    user = _user()
    if not user:
        return _error("User not found", 404)
    try:
        thread_id = str(request.args.get("thread_id") or "").strip()
        plan_key = str(request.args.get("plan_key") or "").strip()
        group = str(request.args.get("group_under_epics") or "true").lower() not in {"0", "false", "no"}
        plan, resolved = get_plan(user.id, thread_id, plan_key)
        return jsonify({"thread_id": thread_id, "plan_key": resolved, "preview": preview(plan, group)})
    except LookupError as exc:
        return _error(exc, 404)
    except Exception as exc:
        return _error(exc)


@pm_sync_bp.route("/bindings", methods=["POST"])
@jwt_required()
def create_and_send_binding():
    user = _user()
    if not user:
        return _error("User not found", 404)
    try:
        binding, plan = create_binding(user, request.get_json(silent=True) or {})
        result = push_binding(binding, plan, trigger="send")
        if _result_has_auth_failure(result):
            return _reconnect_response(user, binding)
        return jsonify({"binding": binding.to_dict(), "result": result}), 201 if result.get("success") else 207
    except LookupError as exc:
        return _error(exc, 404)
    except Exception as exc:
        db.session.rollback()
        return _error(exc)


@pm_sync_bp.route("/bindings", methods=["GET"])
@jwt_required()
def list_bindings():
    user = _user()
    if not user:
        return _error("User not found", 404)
    query = PmSyncBinding.query.filter_by(user_id=user.id)
    thread_id = str(request.args.get("thread_id") or "").strip()
    plan_key = str(request.args.get("plan_key") or "").strip()
    if thread_id:
        query = query.filter_by(thread_id=thread_id)
    if plan_key:
        query = query.filter_by(plan_key=plan_key)
    return jsonify({"bindings": [row.to_dict() for row in query.order_by(PmSyncBinding.created_at.desc()).all()]})


@pm_sync_bp.route("/bindings/<binding_id>", methods=["GET"])
@jwt_required()
def get_binding(binding_id):
    user = _user()
    binding = _owned(binding_id, user.id) if user else None
    if not binding:
        return _error("Binding not found", 404)
    links = PmSyncLink.query.filter_by(binding_id=binding.id).all()
    return jsonify({"binding": binding.to_dict(), "links": [link.to_dict() for link in links], "logs": list_logs(binding)})


@pm_sync_bp.route("/bindings/<binding_id>", methods=["PATCH"])
@jwt_required()
def update_binding(binding_id):
    user = _user()
    binding = _owned(binding_id, user.id) if user else None
    if not binding:
        return _error("Binding not found", 404)
    data = request.get_json(silent=True) or {}
    status = str(data.get("status") or "").strip().lower()
    policy = str(data.get("conflict_policy") or "").strip().lower()
    mode = str(data.get("mode") or "").strip().lower()
    if status:
        if status not in STATUSES:
            return _error("Invalid binding status")
        binding.status = status
    if policy:
        if policy not in POLICIES:
            return _error("Invalid conflict policy")
        binding.conflict_policy = policy
        binding.policy_set_by_user_id = user.id
        from datetime import datetime
        binding.policy_set_at = datetime.utcnow()
    if mode:
        if mode not in MODES:
            return _error("Invalid sync mode")
        binding.mode = mode
    if "field_policy_overrides" in data:
        if not isinstance(data["field_policy_overrides"], dict):
            return _error("field_policy_overrides must be an object")
        if any(value not in POLICIES for value in data["field_policy_overrides"].values()):
            return _error("Invalid field conflict policy")
        binding.field_policy_overrides = data["field_policy_overrides"]
    db.session.commit()
    return jsonify({"binding": binding.to_dict()})


@pm_sync_bp.route("/bindings/<binding_id>/sync", methods=["POST"])
@jwt_required()
def sync_binding(binding_id):
    user = _user()
    binding = _owned(binding_id, user.id) if user else None
    if not binding:
        return _error("Binding not found", 404)
    try:
        result = reconcile_binding(binding, trigger="sync_now")
        if _result_has_auth_failure(result):
            return _reconnect_response(user, binding)
        return jsonify({"binding": binding.to_dict(), "result": result, "logs": list_logs(binding)})
    except Exception as exc:
        db.session.rollback()
        if _jira_auth_failure(exc):
            return _reconnect_response(user, binding)
        return _error(exc, 502)
