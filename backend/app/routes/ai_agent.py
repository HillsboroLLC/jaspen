from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime
import os
import uuid

from .sessions import load_user_sessions, save_user_sessions

ai_agent_bp = Blueprint('ai_agent', __name__)


READINESS_SPEC = {
    "version": "readiness-v1",
    "categories": [
        {"key": "problem_clarity", "label": "Problem Clarity", "weight": 0.25},
        {"key": "market_context", "label": "Market Context", "weight": 0.25},
        {"key": "business_model", "label": "Business Model", "weight": 0.25},
        {"key": "execution_plan", "label": "Execution Plan", "weight": 0.25},
    ],
}

READINESS_KEYWORDS = {
    "problem_clarity": ["problem", "pain", "challenge", "issue", "goal"],
    "market_context": ["customer", "buyer", "market", "segment", "demand", "competition"],
    "business_model": ["revenue", "pricing", "price", "cost", "margin", "budget", "roi"],
    "execution_plan": ["timeline", "team", "resource", "milestone", "launch", "plan"],
}

FOLLOW_UP_QUESTIONS = {
    "problem_clarity": "What is the core problem you are solving, and who feels it most?",
    "market_context": "Who is your primary customer segment, and what alternatives do they use today?",
    "business_model": "How will this generate value financially (pricing, cost, ROI, or margin impact)?",
    "execution_plan": "What is your implementation timeline and which resources or team roles are required?",
}

SCENARIO_OUTPUT_FIELDS = {
    "market_iq_score", "score_category", "component_scores", "financial_impact",
    "analysis_id", "user_id", "timestamp", "project_description",
    "key_insights", "top_risks", "recommendations", "project_name",
    "risks", "compat", "inputs", "id", "label", "thread_id", "scenario_id",
    "overall_score", "scores", "name", "status", "framework_id",
}


def _iso_now():
    return datetime.utcnow().isoformat()


def _new_session(user_id, thread_id, name):
    now = _iso_now()
    return {
        "session_id": thread_id,
        "name": name or "Market IQ Intake",
        "document_type": "market_iq",
        "current_phase": 1,
        "chat_history": [],
        "notes": {},
        "created": now,
        "timestamp": now,
        "status": "in_progress",
        "user_id": user_id,
    }


def _message_text(msg):
    if not isinstance(msg, dict):
        return ""
    content = msg.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        return str(content.get("text") or content.get("message") or "").strip()
    return str(msg.get("text") or msg.get("message") or "").strip()


def _compute_readiness(chat_history):
    user_msgs = [
        _message_text(m)
        for m in (chat_history or [])
        if isinstance(m, dict) and str(m.get("role", "")).lower() == "user"
    ]
    user_text = " ".join(user_msgs).lower()
    user_turns = len([m for m in user_msgs if m])

    categories = []
    completed_weight = 0.0
    for cat in READINESS_SPEC["categories"]:
        key = cat["key"]
        weight = float(cat.get("weight", 0))
        hits = any(k in user_text for k in READINESS_KEYWORDS.get(key, []))
        percent = 100 if hits else min(70, user_turns * 15)
        completed = bool(hits)
        if completed:
            completed_weight += weight
        categories.append({
            "key": key,
            "label": cat["label"],
            "weight": weight,
            "percent": int(percent),
            "completed": completed,
        })

    # Small progress bonus for conversational depth.
    progress_bonus = min(0.15, user_turns * 0.025)
    overall = int(round(min(1.0, completed_weight + progress_bonus) * 100))
    return {
        "overall": {
            "percent": overall,
            "source": "heuristic_intake",
            "heur_overall": overall,
        },
        "categories": categories,
        "version": READINESS_SPEC["version"],
    }


def _next_question(readiness):
    for category in readiness.get("categories", []):
        if not category.get("completed"):
            return FOLLOW_UP_QUESTIONS.get(category["key"])
    return "Great, I have enough context. You can click Finish & Analyze when ready."


def _resolve_user_session(sessions, thread_id):
    thread_id = str(thread_id)
    if not isinstance(sessions, dict):
        return None, None
    if thread_id in sessions:
        return thread_id, sessions.get(thread_id)
    for key, candidate in sessions.items():
        if str((candidate or {}).get("session_id", "")) == thread_id:
            return key, candidate
    return None, None


def _session_chat_history(session):
    if not isinstance(session, dict):
        return []
    chat_history = session.get("chat_history")
    if isinstance(chat_history, list):
        return chat_history
    result_blob = session.get("result")
    if isinstance(result_blob, dict) and isinstance(result_blob.get("chat_history"), list):
        return result_blob.get("chat_history")
    return []


def _extract_baseline_inputs(baseline):
    if not isinstance(baseline, dict):
        return {}
    inputs = {}
    for source in (baseline.get("inputs") or {}, baseline.get("compat") or {}, baseline):
        if not isinstance(source, dict):
            continue
        for key, val in source.items():
            if key in inputs or key in SCENARIO_OUTPUT_FIELDS or str(key).startswith("_"):
                continue
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                inputs[key] = val
    return inputs


def _infer_lever_type(key):
    k = str(key).lower()
    if any(p in k for p in ("budget", "invest", "cost", "price", "revenue", "value")):
        return "currency"
    if any(p in k for p in ("month", "timeline", "period", "duration")):
        return "months"
    if any(p in k for p in ("percent", "rate", "margin", "growth", "penetrat")):
        return "percentage"
    return "number"


def _build_thread_levers(session):
    if not isinstance(session, dict):
        return []

    baseline_inputs = session.get("baseline_inputs")
    if not isinstance(baseline_inputs, dict) or not baseline_inputs:
        result_blob = session.get("result")
        baseline_inputs = _extract_baseline_inputs(result_blob if isinstance(result_blob, dict) else {})

    levers = []
    for key, val in (baseline_inputs or {}).items():
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            continue
        levers.append({
            "key": key,
            "label": str(key).replace("_", " ").title(),
            "current": val,
            "value": val,
            "type": _infer_lever_type(key),
            "display_multiplier": 1,
        })
    return levers


def _normalize_analysis_history(session, thread_id):
    if not isinstance(session, dict):
        return []

    history = session.get("analysis_history")
    if not isinstance(history, list):
        history = session.get("analyses")
    if not isinstance(history, list):
        history = []

    normalized = []
    for item in history:
        if not isinstance(item, dict):
            continue
        aid = item.get("analysis_id") or item.get("id")
        if not aid:
            continue
        normalized.append({
            **item,
            "analysis_id": str(aid),
            "created_at": item.get("created_at") or item.get("timestamp") or session.get("timestamp") or session.get("created"),
        })

    if normalized:
        normalized.sort(key=lambda a: a.get("created_at") or "", reverse=True)
        return normalized

    result_blob = session.get("result")
    if isinstance(result_blob, dict) and result_blob:
        analysis_id = str(
            result_blob.get("analysis_id")
            or result_blob.get("id")
            or session.get("session_id")
            or thread_id
        )
        return [{
            "analysis_id": analysis_id,
            "created_at": result_blob.get("timestamp") or session.get("timestamp") or session.get("created"),
            "result": result_blob,
        }]

    return []


def _find_session_by_thread(thread_id, user_id=None):
    thread_id = str(thread_id)

    if not user_id:
        return None

    sessions = load_user_sessions(user_id)
    if thread_id in sessions:
        return sessions[thread_id]
    for candidate in sessions.values():
        if str((candidate or {}).get("session_id", "")) == thread_id:
            return candidate

    return None


@ai_agent_bp.route("/conversation/start", methods=["POST"])
@jwt_required()
def conversation_start():
    data = request.get_json() or {}
    user_id = get_jwt_identity()

    user_message = str(data.get("message") or data.get("description") or "").strip()
    if not user_message:
        return jsonify({"error": "message is required"}), 400

    thread_id = str(data.get("thread_id") or request.headers.get("X-Session-ID") or f"thread_{uuid.uuid4().hex[:12]}")
    name = str(data.get("name") or user_message[:60] or "Market IQ Intake").strip()

    sessions = load_user_sessions(user_id)
    session = sessions.get(thread_id) or _new_session(user_id, thread_id, name)

    chat_history = session.get("chat_history")
    if not isinstance(chat_history, list):
        chat_history = []

    chat_history.append({"role": "user", "content": user_message, "timestamp": _iso_now()})
    readiness = _compute_readiness(chat_history)
    assistant_reply = _next_question(readiness)
    chat_history.append({"role": "assistant", "content": assistant_reply, "timestamp": _iso_now()})

    session["chat_history"] = chat_history
    session["name"] = name
    session["timestamp"] = _iso_now()
    session["status"] = "in_progress"
    sessions[thread_id] = session
    save_user_sessions(user_id, sessions)

    return jsonify({
        "thread_id": thread_id,
        "session_id": thread_id,
        "reply": assistant_reply,
        "message": assistant_reply,
        "readiness": {
            "percent": readiness["overall"]["percent"],
            "categories": readiness["categories"],
            "updated_at": _iso_now(),
        },
        "status": "gathering_info",
    }), 200


@ai_agent_bp.route("/conversation/continue", methods=["POST"])
@jwt_required()
def conversation_continue():
    data = request.get_json() or {}
    user_id = get_jwt_identity()

    thread_id = str(data.get("thread_id") or data.get("session_id") or request.headers.get("X-Session-ID") or "").strip()
    user_message = str(data.get("message") or data.get("user_message") or "").strip()

    if not thread_id:
        return jsonify({"error": "thread_id or session_id is required"}), 400
    if not user_message:
        return jsonify({"error": "message is required"}), 400

    sessions = load_user_sessions(user_id)
    session = sessions.get(thread_id) or _new_session(user_id, thread_id, "Market IQ Intake")
    chat_history = session.get("chat_history")
    if not isinstance(chat_history, list):
        chat_history = []

    chat_history.append({"role": "user", "content": user_message, "timestamp": _iso_now()})
    readiness = _compute_readiness(chat_history)
    assistant_reply = _next_question(readiness)
    chat_history.append({"role": "assistant", "content": assistant_reply, "timestamp": _iso_now()})

    session["chat_history"] = chat_history
    session["timestamp"] = _iso_now()
    session["status"] = "ready_to_analyze" if readiness["overall"]["percent"] >= 85 else "in_progress"
    sessions[thread_id] = session
    save_user_sessions(user_id, sessions)

    return jsonify({
        "thread_id": thread_id,
        "session_id": thread_id,
        "reply": assistant_reply,
        "message": assistant_reply,
        "actions": [],
        "readiness": {
            "percent": readiness["overall"]["percent"],
            "categories": readiness["categories"],
            "updated_at": _iso_now(),
        },
        "status": "ready_to_analyze" if readiness["overall"]["percent"] >= 85 else "gathering_info",
    }), 200


@ai_agent_bp.route("/readiness/spec", methods=["GET"])
def readiness_spec():
    return jsonify(READINESS_SPEC), 200


@ai_agent_bp.route("/readiness/audit", methods=["GET"])
@jwt_required()
def readiness_audit():
    thread_id = request.args.get("thread_id") or request.headers.get("X-Session-ID")
    if not thread_id:
        return jsonify({"error": "thread_id query param required"}), 400

    user_id = get_jwt_identity()
    session = _find_session_by_thread(thread_id, user_id=user_id)
    chat_history = session.get("chat_history", []) if isinstance(session, dict) else []
    readiness = _compute_readiness(chat_history)
    return jsonify(readiness), 200


@ai_agent_bp.route("/threads", methods=["GET"])
@jwt_required()
def list_threads():
    user_id = get_jwt_identity()
    sessions = load_user_sessions(user_id) or {}

    sessions_list = []
    for key, candidate in (sessions.items() if isinstance(sessions, dict) else []):
        if not isinstance(candidate, dict):
            continue
        thread_id = str(candidate.get("session_id") or key)
        chat_history = _session_chat_history(candidate)
        readiness = candidate.get("readiness") if isinstance(candidate.get("readiness"), dict) else _compute_readiness(chat_history)

        sessions_list.append({
            **candidate,
            "session_id": thread_id,
            "name": candidate.get("name") or "Market IQ Intake",
            "chat_history": chat_history,
            "readiness": readiness,
        })

    sessions_list.sort(
        key=lambda s: s.get("timestamp") or s.get("created") or "",
        reverse=True,
    )
    return jsonify({"success": True, "sessions": sessions_list}), 200


@ai_agent_bp.route("/threads", methods=["DELETE"])
@jwt_required()
def reset_threads():
    user_id = str(get_jwt_identity())
    sessions = load_user_sessions(user_id) or {}
    cleared_threads = len(sessions) if isinstance(sessions, dict) else 0

    # Reset per-user AI Agent sessions.
    save_user_sessions(user_id, {})

    # Reset per-user scenario storage used by ScenarioModeler.
    scenarios_path = os.path.join("scenarios_data", f"user_{user_id}_scenarios.json")
    scenarios_cleared = False
    try:
        if os.path.exists(scenarios_path):
            os.remove(scenarios_path)
            scenarios_cleared = True
    except Exception:
        scenarios_cleared = False

    return jsonify({
        "success": True,
        "cleared_threads": cleared_threads,
        "cleared_scenarios": scenarios_cleared,
    }), 200


@ai_agent_bp.route("/threads/reset", methods=["POST"])
@jwt_required()
def reset_threads_post():
    return reset_threads()


@ai_agent_bp.route("/threads/<thread_id>", methods=["GET"])
@jwt_required()
def get_thread(thread_id):
    user_id = get_jwt_identity()
    sessions = load_user_sessions(user_id) or {}
    session_key, session = _resolve_user_session(sessions, thread_id)
    if not isinstance(session, dict):
        return jsonify({"error": "Thread not found"}), 404

    resolved_thread_id = str(session.get("session_id") or session_key or thread_id)
    chat_history = _session_chat_history(session)
    readiness = session.get("readiness") if isinstance(session.get("readiness"), dict) else _compute_readiness(chat_history)
    analyses = _normalize_analysis_history(session, resolved_thread_id)

    thread_payload = {
        "id": resolved_thread_id,
        "session_id": resolved_thread_id,
        "name": session.get("name") or "Market IQ Intake",
        "status": session.get("status") or ("completed" if analyses else "in_progress"),
        "created_at": session.get("created"),
        "updated_at": session.get("timestamp"),
        "conversation_history": chat_history,
        "readiness_snapshot": readiness,
    }

    session_payload = {
        **session,
        "session_id": resolved_thread_id,
        "chat_history": chat_history,
        "readiness": readiness,
    }

    return jsonify({
        "success": True,
        "thread": thread_payload,
        "session": session_payload,
        "messages": chat_history,
        "analysis_history": analyses,
        "analyses": analyses,
        "adopted_analysis_id": session.get("adopted_analysis_id"),
    }), 200


@ai_agent_bp.route("/threads/<thread_id>", methods=["PATCH"])
@jwt_required()
def update_thread(thread_id):
    data = request.get_json() or {}
    name = str(data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    user_id = get_jwt_identity()
    sessions = load_user_sessions(user_id) or {}
    session_key, session = _resolve_user_session(sessions, thread_id)
    if not isinstance(session, dict):
        return jsonify({"error": "Thread not found"}), 404

    resolved_thread_id = str(session.get("session_id") or session_key or thread_id)
    session["name"] = name
    session["timestamp"] = _iso_now()
    sessions[session_key or resolved_thread_id] = session
    save_user_sessions(user_id, sessions)

    chat_history = _session_chat_history(session)
    readiness = session.get("readiness") if isinstance(session.get("readiness"), dict) else _compute_readiness(chat_history)
    session_payload = {
        **session,
        "session_id": resolved_thread_id,
        "chat_history": chat_history,
        "readiness": readiness,
    }

    return jsonify({
        "success": True,
        "thread": {
            "id": resolved_thread_id,
            "name": name,
            "status": session.get("status") or "in_progress",
            "updated_at": session.get("timestamp"),
        },
        "session": session_payload,
    }), 200


@ai_agent_bp.route("/threads/<thread_id>/levers", methods=["GET"])
@jwt_required()
def get_thread_levers(thread_id):
    user_id = get_jwt_identity()
    sessions = load_user_sessions(user_id) or {}
    session_key, session = _resolve_user_session(sessions, thread_id)
    if not isinstance(session, dict):
        return jsonify({"error": "Thread not found"}), 404

    resolved_thread_id = str(session.get("session_id") or session_key or thread_id)
    levers = _build_thread_levers(session)
    return jsonify({
        "thread_id": resolved_thread_id,
        "levers": levers,
    }), 200
