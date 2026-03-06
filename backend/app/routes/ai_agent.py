from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request
from datetime import datetime
import glob
import json
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


def _find_session_by_thread(thread_id, user_id=None):
    thread_id = str(thread_id)

    if user_id:
        sessions = load_user_sessions(user_id)
        if thread_id in sessions:
            return sessions[thread_id]
        for candidate in sessions.values():
            if str((candidate or {}).get("session_id", "")) == thread_id:
                return candidate

    for path in glob.glob(os.path.join("sessions_data", "user_*_sessions.json")):
        try:
            with open(path, "r") as f:
                sessions = json.load(f) or {}
            if thread_id in sessions:
                return sessions[thread_id]
            for candidate in sessions.values():
                if str((candidate or {}).get("session_id", "")) == thread_id:
                    return candidate
        except Exception:
            continue
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
def readiness_audit():
    thread_id = request.args.get("thread_id") or request.headers.get("X-Session-ID")
    if not thread_id:
        return jsonify({"error": "thread_id query param required"}), 400

    user_id = None
    try:
        verify_jwt_in_request(optional=True)
        user_id = get_jwt_identity()
    except Exception:
        user_id = None

    session = _find_session_by_thread(thread_id, user_id=user_id)
    chat_history = session.get("chat_history", []) if isinstance(session, dict) else []
    readiness = _compute_readiness(chat_history)
    return jsonify(readiness), 200
