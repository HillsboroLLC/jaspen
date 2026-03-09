from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime
import os
import re
import uuid

from .sessions import load_user_sessions, save_user_sessions

ai_agent_bp = Blueprint('ai_agent', __name__)


READINESS_SPEC_V1 = {
    "version": "readiness-v1",
    "categories": [
        {"key": "problem_clarity", "label": "Problem Clarity", "weight": 0.25},
        {"key": "market_context", "label": "Market Context", "weight": 0.25},
        {"key": "business_model", "label": "Business Model", "weight": 0.25},
        {"key": "execution_plan", "label": "Execution Plan", "weight": 0.25},
    ],
}

READINESS_SPEC_V2 = {
    "version": "readiness-v2",
    "categories": [
        {"key": "goal_definition", "label": "Goal Definition", "weight": 1 / 7, "step": 1},
        {"key": "evidence_baseline", "label": "Data Baseline (Financial or KPI)", "weight": 1 / 7, "step": 2},
        {"key": "sme_drivers", "label": "SME Drivers (Why)", "weight": 1 / 7, "step": 3},
        {"key": "system_mapping", "label": "System Mapping", "weight": 1 / 7, "step": 4},
        {"key": "constraint_unlock", "label": "Constraint + Unlock", "weight": 1 / 7, "step": 5},
        {"key": "execution_sequence", "label": "Execution Sequencing", "weight": 1 / 7, "step": 6},
        {"key": "replication_plan", "label": "Replication Plan", "weight": 1 / 7, "step": 7},
    ],
}

READINESS_SPECS = {
    "readiness-v1": READINESS_SPEC_V1,
    "readiness-v2": READINESS_SPEC_V2,
}

READINESS_VERSION_ALIASES = {
    "v1": "readiness-v1",
    "v2": "readiness-v2",
    "readiness-v1": "readiness-v1",
    "readiness-v2": "readiness-v2",
}

READINESS_KEYWORDS_BY_VERSION = {
    "readiness-v1": {
        "problem_clarity": ["problem", "pain", "challenge", "issue", "goal"],
        "market_context": ["customer", "buyer", "market", "segment", "demand", "competition"],
        "business_model": ["revenue", "pricing", "price", "cost", "margin", "budget", "roi"],
        "execution_plan": ["timeline", "team", "resource", "milestone", "launch", "plan"],
    },
    "readiness-v2": {
        "goal_definition": ["goal", "objective", "north star", "outcome", "deadline", "target date"],
        "evidence_baseline": ["metric", "kpi", "baseline", "current", "target", "trend", "data"],
        "sme_drivers": ["sme", "stakeholder", "expert", "root cause", "why", "insight"],
        "system_mapping": ["process", "workflow", "system", "handoff", "dependency map", "bottleneck"],
        "constraint_unlock": ["constraint", "bottleneck", "unlock", "gate", "blocker", "critical path"],
        "execution_sequence": ["sequence", "parallel", "milestone", "dependency", "owner", "timeline"],
        "replication_plan": ["replicate", "template", "playbook", "standardize", "rollout", "repeat"],
    },
}

FOLLOW_UP_QUESTIONS_BY_VERSION = {
    "readiness-v1": {
        "problem_clarity": "What is the core problem you are solving, and who feels it most?",
        "market_context": "Who is your primary customer segment, and what alternatives do they use today?",
        "business_model": "How will this generate value financially (pricing, cost, ROI, or margin impact)?",
        "execution_plan": "What is your implementation timeline and which resources or team roles are required?",
    },
    "readiness-v2": {
        "goal_definition": "What is the specific initiative goal, target outcome, and time horizon?",
        "evidence_baseline": "Share baseline data: current vs target metrics, timeframe, and source (financial or KPI).",
        "sme_drivers": "Which SMEs can explain why this is happening, and what patterns are they seeing?",
        "system_mapping": "Map the system: what teams, steps, and handoffs shape this initiative end-to-end?",
        "constraint_unlock": "What is the primary constraint today, and what unlock would remove it?",
        "execution_sequence": "What work must happen in sequence vs in parallel, and what are the key dependencies?",
        "replication_plan": "How will this be repeatable across teams, sites, or future initiatives?",
    },
}

EVIDENCE_DATA_CONTRACT = {
    "required_fields": [
        "metric_name",
        "metric_type",
        "unit",
        "direction",
        "current",
        "target",
        "period_start",
        "period_end",
        "source_type",
    ],
    "allowed_metric_types": ["financial", "kpi", "operational", "risk"],
    "allowed_source_types": ["system", "manual", "sme", "external_report"],
}

FINANCIAL_TERMS = [
    "revenue", "ebitda", "margin", "cost", "expense", "profit", "cash flow",
    "burn", "runway", "budget", "roi", "npv", "irr",
]
KPI_TERMS = [
    "conversion", "retention", "churn", "throughput", "cycle time", "on-time",
    "sla", "quality", "defect", "uptime", "adoption", "velocity",
]
TIMEFRAME_TERMS = [
    "week", "month", "quarter", "year", "q1", "q2", "q3", "q4", "by", "within",
]
BASELINE_TERMS = ["baseline", "current", "target", "goal", "today", "starting point"]
DATA_SOURCE_TERMS = ["dashboard", "crm", "erp", "finance", "system", "report", "spreadsheet"]

SCENARIO_OUTPUT_FIELDS = {
    "market_iq_score", "score_category", "component_scores", "financial_impact",
    "analysis_id", "user_id", "timestamp", "project_description",
    "key_insights", "top_risks", "recommendations", "project_name",
    "risks", "compat", "inputs", "id", "label", "thread_id", "scenario_id",
    "overall_score", "scores", "name", "status", "framework_id",
}


def _iso_now():
    return datetime.utcnow().isoformat()


def _active_readiness_version():
    requested = str(os.getenv("READINESS_SPEC_VERSION", "readiness-v2")).strip().lower()
    normalized = READINESS_VERSION_ALIASES.get(requested)
    return normalized if normalized in READINESS_SPECS else "readiness-v1"


def _active_readiness_spec():
    return READINESS_SPECS[_active_readiness_version()]


def _score_data_evidence(user_text):
    has_number = bool(re.search(r"\b\d+(\.\d+)?%?\b", user_text))
    has_financial = any(term in user_text for term in FINANCIAL_TERMS)
    has_kpi = any(term in user_text for term in KPI_TERMS)
    has_timeframe = any(term in user_text for term in TIMEFRAME_TERMS)
    has_baseline_target = any(term in user_text for term in BASELINE_TERMS)
    has_source = any(term in user_text for term in DATA_SOURCE_TERMS)

    quality_score = sum([
        int(has_number),
        int(has_financial or has_kpi),
        int(has_timeframe),
        int(has_baseline_target),
        int(has_source),
    ])

    if has_financial and has_kpi:
        metric_type = "mixed"
    elif has_financial:
        metric_type = "financial"
    elif has_kpi:
        metric_type = "kpi"
    else:
        metric_type = "unknown"

    return {
        "quality_score": quality_score,
        "has_number": has_number,
        "has_metric_type": bool(has_financial or has_kpi),
        "has_timeframe": has_timeframe,
        "has_baseline_target": has_baseline_target,
        "has_source": has_source,
        "metric_type_detected": metric_type,
    }


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
    spec = _active_readiness_spec()
    version = spec.get("version", "readiness-v1")
    keyword_map = READINESS_KEYWORDS_BY_VERSION.get(version, {})

    user_msgs = [
        _message_text(m)
        for m in (chat_history or [])
        if isinstance(m, dict) and str(m.get("role", "")).lower() == "user"
    ]
    user_text = " ".join(user_msgs).lower()
    user_turns = len([m for m in user_msgs if m])
    evidence = _score_data_evidence(user_text) if version == "readiness-v2" else None

    categories = []
    completed_weight = 0.0
    for cat in spec["categories"]:
        key = cat["key"]
        weight = float(cat.get("weight", 0))

        if version == "readiness-v2" and key == "evidence_baseline" and evidence:
            # Evidence is complete when we have a measurable baseline format that
            # works for both financial and non-financial KPI metrics.
            completed = evidence["quality_score"] >= 3
            percent = min(100, evidence["quality_score"] * 20 + min(user_turns * 4, 20))
        else:
            hits = any(k in user_text for k in keyword_map.get(key, []))
            completed = bool(hits)
            percent = 100 if hits else min(70, user_turns * 15)

        if completed:
            completed_weight += weight
        category_payload = {
            "key": key,
            "label": cat["label"],
            "weight": weight,
            "step": cat.get("step"),
            "percent": int(percent),
            "completed": completed,
        }
        if version == "readiness-v2" and key == "evidence_baseline" and evidence:
            category_payload["evidence_checks"] = evidence
        categories.append(category_payload)

    # Small progress bonus for conversational depth.
    progress_bonus = min(0.15, user_turns * 0.025)
    overall = int(round(min(1.0, completed_weight + progress_bonus) * 100))
    readiness_payload = {
        "overall": {
            "percent": overall,
            "source": "heuristic_intake_v2" if version == "readiness-v2" else "heuristic_intake",
            "heur_overall": overall,
        },
        "categories": categories,
        "version": version,
    }
    if evidence:
        readiness_payload["evidence_quality"] = evidence
        readiness_payload["data_contract"] = EVIDENCE_DATA_CONTRACT
    return readiness_payload


def _next_question(readiness):
    version = readiness.get("version", "readiness-v1")
    followups = FOLLOW_UP_QUESTIONS_BY_VERSION.get(version, FOLLOW_UP_QUESTIONS_BY_VERSION["readiness-v1"])
    for category in readiness.get("categories", []):
        if not category.get("completed"):
            return followups.get(category["key"])
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
            "version": readiness.get("version"),
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
            "version": readiness.get("version"),
            "updated_at": _iso_now(),
        },
        "status": "ready_to_analyze" if readiness["overall"]["percent"] >= 85 else "gathering_info",
    }), 200


@ai_agent_bp.route("/readiness/spec", methods=["GET"])
def readiness_spec():
    spec = dict(_active_readiness_spec())
    spec["active_version"] = _active_readiness_version()
    spec["available_versions"] = list(READINESS_SPECS.keys())
    if spec.get("version") == "readiness-v2":
        spec["data_contract"] = EVIDENCE_DATA_CONTRACT
    return jsonify(spec), 200


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
