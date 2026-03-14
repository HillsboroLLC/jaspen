from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime
import io
import json
import math
import os
import re
import uuid

from app import db, limiter
from app.models import User
from app.billing_config import (
    bootstrap_legacy_credits,
    consume_credits,
    get_allowed_model_types,
    get_default_model_type,
    get_monthly_credit_limit,
    get_model_catalog,
    normalize_model_type,
    to_public_plan,
)
from app.connector_monitor import check_connector_health
from app.tool_registry import (
    get_context_budget,
    get_tool_catalog,
    get_tool_entitlements,
    is_tool_allowed,
)
from app.orgs import resolve_active_org_for_user

from .sessions import load_user_sessions, save_user_sessions

ai_agent_bp = Blueprint('ai_agent', __name__)

STRATEGY_OBJECTIVE_OPTIONS = ("balanced", "cost", "speed", "growth")
STRATEGY_OBJECTIVE_ALIASES = {
    "balanced": "balanced",
    "default": "balanced",
    "general": "balanced",
    "cost": "cost",
    "cost optimization": "cost",
    "cost-optimization": "cost",
    "efficiency": "cost",
    "profitability": "cost",
    "speed": "speed",
    "speed to market": "speed",
    "speed-to-market": "speed",
    "timeline": "speed",
    "delivery": "speed",
    "growth": "growth",
    "revenue": "growth",
    "expansion": "growth",
}

INTAKE_COMPANY_SIZE_ALIASES = {
    "startup": "startup",
    "start-up": "startup",
    "small business": "smb",
    "small-business": "smb",
    "smb": "smb",
    "mid market": "mid-market",
    "mid-market": "mid-market",
    "enterprise": "enterprise",
}

INTAKE_OBJECTIVE_GUIDANCE = {
    "balanced": (
        "Balance decisions across financial impact, execution feasibility, market position, and "
        "operational efficiency. Ask tradeoff questions when one area improves at the expense of another."
    ),
    "cost": (
        "Prioritize discovery on cost structure, budget constraints, waste reduction opportunities, "
        "efficiency gaps, and ROI targets."
    ),
    "speed": (
        "Prioritize discovery on timeline compression, critical-path blockers, dependency sequencing, "
        "resource bottlenecks, and fast delivery milestones."
    ),
    "growth": (
        "Prioritize discovery on market opportunity size, customer acquisition, competitive positioning, "
        "revenue expansion paths, and scaling constraints."
    ),
}


def normalize_strategy_objective(value, default="balanced"):
    text = str(value or "").strip().lower()
    if not text:
        return default
    if text in STRATEGY_OBJECTIVE_ALIASES:
        return STRATEGY_OBJECTIVE_ALIASES[text]
    compact = text.replace("_", " ").replace("-", " ")
    return STRATEGY_OBJECTIVE_ALIASES.get(compact, default)


def _normalize_company_size(value):
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in INTAKE_COMPANY_SIZE_ALIASES:
        return INTAKE_COMPANY_SIZE_ALIASES[text]
    compact = text.replace("_", " ").replace("-", " ")
    return INTAKE_COMPANY_SIZE_ALIASES.get(compact)


def _sanitize_intake_context(raw_context, fallback_objective="balanced"):
    base_objective = normalize_strategy_objective(fallback_objective)
    context = raw_context if isinstance(raw_context, dict) else {}

    objective = normalize_strategy_objective(context.get("objective"), default=base_objective)
    industry = str(context.get("industry") or "").strip()
    company_size = _normalize_company_size(context.get("company_size"))

    cleaned = {"objective": objective}
    if industry:
        cleaned["industry"] = industry[:120]
    if company_size:
        cleaned["company_size"] = company_size
    return cleaned


def _intake_context_prompt_suffix(intake_context):
    if not isinstance(intake_context, dict):
        return ""

    objective = normalize_strategy_objective(intake_context.get("objective"), default="balanced")
    guidance = INTAKE_OBJECTIVE_GUIDANCE.get(objective, INTAKE_OBJECTIVE_GUIDANCE["balanced"])

    context_lines = [
        "Intake context:",
        f"- Objective: {objective}",
        f"- Focus guidance: {guidance}",
    ]

    industry = str(intake_context.get("industry") or "").strip()
    if industry:
        context_lines.append(f"- Industry: {industry}")

    company_size = _normalize_company_size(intake_context.get("company_size"))
    if company_size:
        context_lines.append(f"- Company size: {company_size}")

    return "\n" + "\n".join(context_lines)


def _format_component_label(key):
    token = str(key or "").replace("_", " ").strip()
    return token.title() if token else "Component"


def _thread_session_record(sessions, thread_id):
    if not isinstance(sessions, dict):
        return None
    if thread_id in sessions and isinstance(sessions.get(thread_id), dict):
        return sessions.get(thread_id)
    for candidate in sessions.values():
        if str((candidate or {}).get("session_id") or "") == str(thread_id):
            return candidate if isinstance(candidate, dict) else None
    return None


def _thread_scorecard_summary(user_id, thread_id):
    if not user_id or not thread_id:
        return {"has_scorecard": False, "scenario_count": 0, "low_components": []}

    session = _thread_session_record(load_user_sessions(user_id), thread_id)
    if not isinstance(session, dict):
        return {"has_scorecard": False, "scenario_count": 0, "low_components": []}

    result = session.get("result") if isinstance(session.get("result"), dict) else {}
    if not result:
        history = session.get("analysis_history")
        if isinstance(history, list):
            for item in reversed(history):
                if isinstance(item, dict) and isinstance(item.get("result"), dict):
                    result = item.get("result")
                    break

    component_scores = {}
    if isinstance(result, dict):
        raw_components = result.get("component_scores") if isinstance(result.get("component_scores"), dict) else {}
        if not raw_components and isinstance(result.get("scores"), dict):
            raw_components = result.get("scores")
        component_scores = raw_components if isinstance(raw_components, dict) else {}

    has_scorecard = bool(component_scores) or result.get("jaspen_score") is not None

    low_components = []
    for key, value in (component_scores or {}).items():
        try:
            score_value = float(value)
        except Exception:
            continue
        if score_value < 50:
            low_components.append({"key": str(key), "label": _format_component_label(key), "score": round(score_value, 2)})
    low_components.sort(key=lambda item: item.get("score", 100))

    scenario_count = 0
    try:
        from .strategy import _load_scenarios
        all_data = _load_scenarios(user_id) if user_id else {}
        thread_entry = all_data.get(thread_id) if isinstance(all_data, dict) else {}
        scenarios = thread_entry.get("scenarios") if isinstance(thread_entry, dict) else []
        if isinstance(scenarios, list):
            scenario_count = len(scenarios)
    except Exception:
        scenario_count = 0

    return {
        "has_scorecard": has_scorecard,
        "scenario_count": scenario_count,
        "low_components": low_components[:3],
    }


def _scenario_modeling_prompt_suffix(user_id, thread_id):
    summary = _thread_scorecard_summary(user_id, thread_id)
    if not summary.get("has_scorecard"):
        return ""

    lines = [
        "Scenario coaching guidance:",
        "- A scorecard exists for this thread.",
        "- After a scorecard is generated, proactively suggest scenario modeling.",
        "- If the user agrees, use the create_scenario tool and explain rationale for each lever adjustment.",
        "- If the user asks how to improve score/performance, suggest and offer to run a scenario before giving generic advice.",
    ]
    if int(summary.get("scenario_count") or 0) == 0:
        lines.append("- No scenarios exist yet; propose a first what-if scenario instead of waiting.")
    low_components = summary.get("low_components") or []
    if low_components:
        hints = ", ".join(f"{item['label']} ({item['score']})" for item in low_components)
        lines.append(
            f"- Weak components detected below 50: {hints}. "
            "Reference these directly when suggesting improvements."
        )
    return "\n" + "\n".join(lines)


def _monitoring_prompt_suffix(user_id):
    if not user_id:
        return ""
    try:
        health_report = check_connector_health(user_id)
    except Exception:
        current_app.logger.exception("Failed to load connector health report for ai-agent prompt")
        return ""

    alerts = health_report.get("alerts") if isinstance(health_report, dict) else []
    if not isinstance(alerts, list) or not alerts:
        return ""

    alert_summary = "\n".join(
        f"- [{str(item.get('severity') or 'info').upper()}] {item.get('connector_id')}: {item.get('message')}"
        for item in alerts
        if isinstance(item, dict)
    )
    if not alert_summary:
        return ""

    return (
        "\n\n## Connected Data Source Alerts\n"
        "The following issues were detected with the user's connected data sources:\n"
        f"{alert_summary}\n"
        "Proactively inform the user of these issues and suggest corrective actions."
    )


def _mutation_result_summary(tool_name, result_payload):
    if not isinstance(result_payload, dict):
        return {}

    summary = {"confirmation": str(result_payload.get("confirmation") or "").strip()}
    if tool_name == "create_scenario":
        scenario = result_payload.get("scenario") if isinstance(result_payload.get("scenario"), dict) else {}
        scenario_result = scenario.get("result") if isinstance(scenario.get("result"), dict) else {}
        summary.update({
            "scenario_id": scenario.get("scenario_id") or scenario.get("id"),
            "label": scenario.get("label"),
            "jaspen_score": scenario_result.get("jaspen_score"),
        })
    elif tool_name in {"update_wbs_task", "add_wbs_task", "remove_wbs_task"}:
        project_wbs = result_payload.get("project_wbs") if isinstance(result_payload.get("project_wbs"), dict) else {}
        tasks = project_wbs.get("tasks") if isinstance(project_wbs.get("tasks"), list) else []
        summary.update({
            "task_count": len(tasks),
            "wbs_name": project_wbs.get("name") or "Execution WBS",
        })
    return summary


def _sanitize_lever_defaults(raw_defaults):
    if not isinstance(raw_defaults, dict):
        return {}
    cleaned = {}
    for key, value in raw_defaults.items():
        lever_id = str(key or "").strip()
        if not lever_id:
            continue
        if isinstance(value, (int, float, bool, str)) or value is None:
            cleaned[lever_id] = value
    return cleaned


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

ADAPTIVE_CONTEXT_PROFILES = [
    {
        "key": "marketing_campaign",
        "triggers": ["campaign", "ad", "marketing", "impression", "promotion", "offer"],
        "items": [
            {
                "id": "campaign_audience",
                "label": "Target audience and segment are defined",
                "keywords": ["segment", "audience", "customer", "buyer", "persona"],
                "question": "Who is the target audience segment for this initiative?",
            },
            {
                "id": "campaign_channel",
                "label": "Channel, reach, and conversion assumptions are explicit",
                "keywords": ["channel", "reach", "conversion", "ctr", "impression", "funnel"],
                "question": "Which channels will you use and what conversion assumptions are you using?",
            },
        ],
    },
    {
        "key": "operations_execution",
        "triggers": ["operation", "process", "workflow", "handoff", "capacity", "throughput"],
        "items": [
            {
                "id": "process_owner",
                "label": "Owners are assigned for the critical workflow",
                "keywords": ["owner", "responsible", "team", "lead", "accountable"],
                "question": "Who owns each critical workflow step and decision?",
            },
            {
                "id": "process_constraint",
                "label": "Operational bottleneck and release plan are defined",
                "keywords": ["bottleneck", "constraint", "queue", "capacity", "blocker", "unlock"],
                "question": "What is the main operational bottleneck and how will you remove it?",
            },
        ],
    },
    {
        "key": "product_growth",
        "triggers": ["product", "feature", "launch", "adoption", "retention", "churn"],
        "items": [
            {
                "id": "value_hypothesis",
                "label": "Customer value hypothesis is testable",
                "keywords": ["value proposition", "hypothesis", "customer need", "pain point", "benefit"],
                "question": "What customer value hypothesis are you testing first?",
            },
            {
                "id": "success_signal",
                "label": "Leading success signals are defined",
                "keywords": ["activation", "retention", "adoption", "engagement", "signal", "north star"],
                "question": "Which leading signals will show this is working before final outcomes?",
            },
        ],
    },
]

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
    "jaspen_score", "score_category", "component_scores", "financial_impact",
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


def _status_from_percent(percent):
    pct = int(max(0, min(100, percent)))
    if pct >= 85:
        return "complete"
    if pct >= 45:
        return "in_progress"
    return "missing"


def _selected_context_profiles(user_text):
    ranked = []
    for profile in ADAPTIVE_CONTEXT_PROFILES:
        score = sum(1 for term in profile.get("triggers", []) if term in user_text)
        if score > 0:
            ranked.append((score, profile))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return [profile for _, profile in ranked[:2]]


def _build_readiness_items(spec, version, categories, user_text, user_turns):
    followups = FOLLOW_UP_QUESTIONS_BY_VERSION.get(version, {})
    items = []

    # Core framework items (always present)
    for category in categories:
        key = category.get("key")
        percent = int(category.get("percent", 0))
        items.append({
            "id": f"core_{key}",
            "key": key,
            "label": category.get("label") or key,
            "type": "core",
            "status": _status_from_percent(percent),
            "percent": percent,
            "confidence": round(max(0.2, min(0.99, percent / 100)), 2),
            "next_question": followups.get(key),
            "step": category.get("step"),
        })

    # Context-specific items (adaptive by request type)
    for profile in _selected_context_profiles(user_text):
        for item in profile.get("items", []):
            hits = sum(1 for term in item.get("keywords", []) if term in user_text)
            if hits > 0:
                percent = min(100, 55 + hits * 20 + min(user_turns * 4, 20))
            else:
                percent = min(45, user_turns * 10)
            items.append({
                "id": item.get("id"),
                "key": item.get("id"),
                "label": item.get("label"),
                "type": "context",
                "context_module": profile.get("key"),
                "status": _status_from_percent(percent),
                "percent": int(percent),
                "confidence": round(max(0.2, min(0.99, percent / 100)), 2),
                "next_question": item.get("question"),
                "step": None,
            })

    summary = {"complete": 0, "in_progress": 0, "missing": 0, "total": len(items)}
    for item in items:
        state = item.get("status")
        if state in summary:
            summary[state] += 1

    return items, summary


def _new_session(
    user_id,
    thread_id,
    name,
    model_type=None,
    strategy_objective=None,
    objective_explicit=False,
    organization_id=None,
    visibility="private",
    intake_context=None,
    starter_lever_defaults=None,
):
    now = _iso_now()
    normalized_objective = normalize_strategy_objective(strategy_objective)
    return {
        "session_id": thread_id,
        "name": name or "Jaspen Intake",
        "document_type": "strategy",
        "model_type": normalize_model_type(model_type) or None,
        "current_phase": 1,
        "chat_history": [],
        "notes": {},
        "created": now,
        "timestamp": now,
        "status": "in_progress",
        "user_id": user_id,
        "created_by_user_id": user_id,
        "organization_id": organization_id,
        "visibility": str(visibility or "private").strip().lower() or "private",
        "shared_with_user_ids": [],
        "strategy_objective": normalized_objective,
        "objective_explicitly_set": bool(objective_explicit),
        "intake_context": _sanitize_intake_context(intake_context, fallback_objective=normalized_objective),
        "starter_lever_defaults": _sanitize_lever_defaults(starter_lever_defaults),
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
    items, checklist_summary = _build_readiness_items(spec, version, categories, user_text, user_turns)
    readiness_payload["items"] = items
    readiness_payload["checklist_summary"] = checklist_summary
    readiness_payload["checklist_mode"] = "adaptive"
    if evidence:
        readiness_payload["evidence_quality"] = evidence
        readiness_payload["data_contract"] = EVIDENCE_DATA_CONTRACT
    return readiness_payload


def _next_question(readiness):
    for item in readiness.get("items", []):
        if item.get("status") != "complete":
            prompt = item.get("next_question")
            if prompt:
                return prompt

    version = readiness.get("version", "readiness-v1")
    followups = FOLLOW_UP_QUESTIONS_BY_VERSION.get(version, FOLLOW_UP_QUESTIONS_BY_VERSION["readiness-v1"])
    for category in readiness.get("categories", []):
        if not category.get("completed"):
            return followups.get(category["key"])
    return "Great, I have enough context. You can click Finish & Analyze when ready."


def _anthropic_api_key():
    return (
        current_app.config.get("ANTHROPIC_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or current_app.config.get("CLAUDE_API_KEY")
        or os.getenv("CLAUDE_API_KEY")
    )


def _anthropic_model_for_selection(model_selection):
    selected = str((model_selection or {}).get("llm_model") or "").strip()
    if selected.lower().startswith("claude"):
        return selected
    return str(
        current_app.config.get("AI_AGENT_ANTHROPIC_MODEL")
        or os.getenv("AI_AGENT_ANTHROPIC_MODEL")
        or "claude-3-7-sonnet-latest"
    ).strip()


def _model_credit_multiplier(model_type):
    model_type = normalize_model_type(model_type)
    defaults = {"pluto": 1.0, "orbit": 1.5, "titan": 2.25}
    raw = (
        current_app.config.get("AI_AGENT_CREDIT_MULTIPLIERS")
        or os.getenv("AI_AGENT_CREDIT_MULTIPLIERS_JSON")
        or {}
    )
    multipliers = defaults.copy()
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                for k, v in parsed.items():
                    try:
                        multipliers[str(k).strip().lower()] = max(0.1, float(v))
                    except Exception:
                        continue
        except Exception:
            pass
    elif isinstance(raw, dict):
        for k, v in raw.items():
            try:
                multipliers[str(k).strip().lower()] = max(0.1, float(v))
            except Exception:
                continue
    return float(multipliers.get(model_type, multipliers["pluto"]))


def _estimate_usage_credit_charge(total_tokens, model_type):
    total_tokens = int(total_tokens or 0)
    if total_tokens <= 0:
        return 0

    per_1k = float(
        current_app.config.get("AI_AGENT_CREDITS_PER_1K_TOKENS")
        or os.getenv("AI_AGENT_CREDITS_PER_1K_TOKENS")
        or 1.0
    )
    min_charge = int(
        current_app.config.get("AI_AGENT_MIN_CREDIT_CHARGE")
        or os.getenv("AI_AGENT_MIN_CREDIT_CHARGE")
        or 1
    )
    raw_credits = (total_tokens / 1000.0) * max(0.01, per_1k) * _model_credit_multiplier(model_type)
    return max(min_charge, int(math.ceil(raw_credits)))


def _anthropic_messages_from_history(chat_history, max_turns=14):
    normalized = []
    for msg in (chat_history or []):
        text = _message_text(msg)
        if not text:
            continue
        role = str((msg or {}).get("role") or "").lower()
        normalized.append({
            "role": "assistant" if role in ("assistant", "ai", "bot") else "user",
            "content": text,
        })

    if max_turns and len(normalized) > max_turns:
        normalized = normalized[-max_turns:]
    return normalized


def _anthropic_history_summary(chat_history, keep_last_turns=16):
    normalized = _anthropic_messages_from_history(chat_history, max_turns=0)
    if not normalized:
        return ""

    keep = max(1, int(keep_last_turns or 0))
    if len(normalized) <= keep:
        return ""

    older = normalized[:-keep]
    user_points = []
    assistant_points = []
    for msg in older:
        content = str(msg.get("content") or "").strip()
        if not content:
            continue
        compact = re.sub(r"\s+", " ", content)
        compact = compact[:200]
        if msg.get("role") == "user":
            user_points.append(compact)
        else:
            assistant_points.append(compact)

    if not user_points and not assistant_points:
        return ""

    parts = []
    if user_points:
        parts.append("Earlier user context: " + " | ".join(user_points[-4:]))
    if assistant_points:
        parts.append("Earlier assistant guidance: " + " | ".join(assistant_points[-2:]))
    summary = "Thread summary for continuity. " + " ".join(parts)
    return summary[:1200]


def _anthropic_tool_definitions(enable_mutation_tools=False):
    tools = [
        {
            "name": "get_readiness_snapshot",
            "description": "Return the latest readiness percent, missing checklist items, and top follow-up question.",
            "input_schema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "name": "get_data_contract",
            "description": "Return required fields for baseline evidence collection when readiness v2 is active.",
            "input_schema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    ]
    if enable_mutation_tools:
        tools.extend([
            {
                "name": "create_scenario",
                "description": "Create a scenario from lever deltas for the active thread.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "deltas": {
                            "type": "object",
                            "description": "Map of lever_id to new value",
                            "additionalProperties": {"type": "number"},
                        },
                    },
                    "required": ["label", "deltas"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "update_wbs_task",
                "description": "Update one editable field on a WBS task for the active thread.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "field": {"type": "string", "enum": ["title", "description", "priority", "estimated_days", "suggested_role"]},
                        "new_value": {},
                    },
                    "required": ["task_id", "field", "new_value"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "add_wbs_task",
                "description": "Add a new WBS task in a phase for the active thread.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "phase_name": {"type": "string"},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "priority": {"type": "string"},
                        "estimated_days": {"type": "number"},
                    },
                    "required": ["phase_name", "title", "description", "priority", "estimated_days"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "remove_wbs_task",
                "description": "Remove a WBS task by id for the active thread.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                    },
                    "required": ["task_id"],
                    "additionalProperties": False,
                },
            },
        ])
    return tools


def _anthropic_tool_output(tool_name, readiness):
    if tool_name == "get_data_contract":
        if readiness.get("version") == "readiness-v2":
            return {
                "available": True,
                "version": "readiness-v2",
                "data_contract": EVIDENCE_DATA_CONTRACT,
            }
        return {
            "available": False,
            "reason": "Data contract is only used for readiness-v2.",
        }

    missing_items = [
        {
            "id": item.get("id"),
            "label": item.get("label"),
            "next_question": item.get("next_question"),
            "status": item.get("status"),
        }
        for item in readiness.get("items", [])
        if item.get("status") != "complete"
    ]

    return {
        "percent": int((readiness.get("overall") or {}).get("percent") or 0),
        "version": readiness.get("version"),
        "missing_items": missing_items[:5],
        "top_followup": _next_question(readiness),
        "checklist_summary": readiness.get("checklist_summary") or {},
    }


def _tool_error(message, code="tool_error"):
    return {"ok": False, "code": code, "error": str(message)}


def _tool_success(payload):
    out = {"ok": True}
    if isinstance(payload, dict):
        out.update(payload)
    return out


def _execute_mutation_tool(tool_name, tool_input, *, user, user_id, thread_id):
    if not user:
        return _tool_error("User context missing.")
    if not thread_id:
        return _tool_error("thread_id is required for mutation tools.", code="missing_thread")

    plan_key = to_public_plan(user.subscription_plan)
    tool_input = tool_input if isinstance(tool_input, dict) else {}

    from .strategy import (
        _compute_scenario_scorecard,
        _create_scenario_record,
        _normalize_project_wbs,
        _resolve_thread_baseline,
        _sanitize_deltas,
        _save_scenarios,
    )

    if tool_name == "create_scenario":
        if not is_tool_allowed(plan_key, "scenario_create", "write"):
            return _tool_error("Scenario creation is not allowed on your current plan.", code="tool_not_allowed")

        label = str(tool_input.get("label") or "AI Scenario").strip() or "AI Scenario"
        raw_deltas = tool_input.get("deltas") if isinstance(tool_input.get("deltas"), dict) else {}
        _, _, baseline, baseline_inputs, _session, objective = _resolve_thread_baseline(user_id, thread_id)
        if not isinstance(baseline, dict):
            return _tool_error("No baseline scorecard is available yet for this thread.", code="missing_baseline")

        deltas = _sanitize_deltas(baseline_inputs or {}, raw_deltas)
        if not deltas:
            return _tool_error("No valid lever deltas were provided.", code="invalid_deltas")

        scenario_id = str(uuid.uuid4())
        result = _compute_scenario_scorecard(baseline, deltas, baseline_inputs or {})
        result.update({
            "analysis_id": scenario_id,
            "scenario_id": scenario_id,
            "thread_id": thread_id,
            "label": label,
        })
        try:
            scenario = _create_scenario_record(
                user_id,
                thread_id,
                deltas=deltas,
                label=label,
                baseline=baseline,
                scenario_id=scenario_id,
                plan_key=plan_key,
                result=result,
                metadata={
                    "ai_rationale": "Created from conversational tool request.",
                    "strategy_objective": objective,
                },
            )
        except PermissionError as limit_error:
            return _tool_error(str(limit_error), code="scenario_limit_reached")

        return _tool_success({
            "tool": tool_name,
            "confirmation": (
                f"I've created a new scenario called '{label}' with {len(deltas)} lever adjustments "
                f"and a projected score of {result.get('jaspen_score')}."
            ),
            "scenario": scenario,
        })

    if tool_name in {"update_wbs_task", "add_wbs_task", "remove_wbs_task"}:
        if not is_tool_allowed(plan_key, "wbs_write", "write"):
            return _tool_error("WBS write actions are not allowed on your current plan.", code="tool_not_allowed")

        from .strategy import _load_scenarios, _thread_entry

        all_data = _load_scenarios(user_id)
        if thread_id not in all_data or not isinstance(all_data.get(thread_id), dict):
            all_data[thread_id] = _thread_entry()
        td = all_data[thread_id]
        current_wbs = td.get("project_wbs") if isinstance(td.get("project_wbs"), dict) else {"name": "Execution WBS", "tasks": []}
        tasks = list(current_wbs.get("tasks") if isinstance(current_wbs.get("tasks"), list) else [])

        if tool_name == "update_wbs_task":
            task_id = str(tool_input.get("task_id") or "").strip()
            field = str(tool_input.get("field") or "").strip()
            new_value = tool_input.get("new_value")
            idx = next((i for i, task in enumerate(tasks) if str((task or {}).get("id") or "") == task_id), -1)
            if idx < 0:
                return _tool_error("Task not found.", code="task_not_found")

            task = dict(tasks[idx] or {})
            if field == "title":
                task["title"] = str(new_value or "").strip()
            elif field == "description":
                task["description"] = str(new_value or "").strip()
            elif field == "priority":
                priority = str(new_value or "").strip().lower()
                if priority not in {"high", "medium", "low"}:
                    return _tool_error("Priority must be high, medium, or low.", code="invalid_priority")
                task["priority"] = priority
            elif field == "estimated_days":
                try:
                    days = max(1, int(new_value))
                except Exception:
                    return _tool_error("estimated_days must be a positive integer.", code="invalid_estimated_days")
                task["estimated_days"] = days
                task["timeline_days"] = days
            elif field == "suggested_role":
                role = str(new_value or "").strip()
                task["suggested_role"] = role
                task["owner"] = role
            else:
                return _tool_error("Unsupported WBS update field.", code="invalid_field")
            tasks[idx] = task
            confirmation = f"Updated task '{task.get('title') or task_id}' ({field})."

        elif tool_name == "add_wbs_task":
            title = str(tool_input.get("title") or "").strip()
            if not title:
                return _tool_error("title is required.", code="invalid_title")
            priority = str(tool_input.get("priority") or "").strip().lower()
            if priority not in {"high", "medium", "low"}:
                return _tool_error("Priority must be high, medium, or low.", code="invalid_priority")
            try:
                estimated_days = max(1, int(tool_input.get("estimated_days")))
            except Exception:
                return _tool_error("estimated_days must be a positive integer.", code="invalid_estimated_days")

            new_task = {
                "id": f"task_{uuid.uuid4().hex[:10]}",
                "title": title,
                "description": str(tool_input.get("description") or "").strip(),
                "priority": priority,
                "estimated_days": estimated_days,
                "timeline_days": estimated_days,
                "suggested_role": str(tool_input.get("suggested_role") or "Project Manager").strip(),
                "owner": str(tool_input.get("suggested_role") or "Project Manager").strip(),
                "phase": str(tool_input.get("phase_name") or "Execution").strip() or "Execution",
                "status": "todo",
                "depends_on": [],
            }
            tasks.append(new_task)
            confirmation = f"Added task '{title}' to phase '{new_task.get('phase')}'."

        else:  # remove_wbs_task
            task_id = str(tool_input.get("task_id") or "").strip()
            before_count = len(tasks)
            tasks = [task for task in tasks if str((task or {}).get("id") or "") != task_id]
            if len(tasks) == before_count:
                return _tool_error("Task not found.", code="task_not_found")
            for task in tasks:
                deps = task.get("depends_on")
                if isinstance(deps, list):
                    task["depends_on"] = [dep for dep in deps if str(dep) != task_id]
            confirmation = f"Removed task '{task_id}' from the WBS."

        normalized = _normalize_project_wbs({"project_wbs": {**current_wbs, "tasks": tasks}}, existing=current_wbs)
        td["project_wbs"] = normalized
        all_data[thread_id] = td
        if not _save_scenarios(user_id, all_data):
            return _tool_error("Failed to persist WBS changes.", code="persist_failed")

        return _tool_success({
            "tool": tool_name,
            "confirmation": confirmation,
            "project_wbs": normalized,
        })

    return _tool_error(f"Unsupported tool '{tool_name}'.", code="unknown_tool")


def _anthropic_content_to_dicts(content_blocks):
    normalized = []
    for block in (content_blocks or []):
        if isinstance(block, dict):
            normalized.append(block)
            continue
        if hasattr(block, "model_dump"):
            try:
                normalized.append(block.model_dump())
                continue
            except Exception:
                pass
        payload = {"type": getattr(block, "type", "text")}
        for field in ("id", "name", "input", "text"):
            value = getattr(block, field, None)
            if value is not None:
                payload[field] = value
        normalized.append(payload)
    return normalized


def _anthropic_text(content_blocks):
    out = []
    for block in (content_blocks or []):
        if isinstance(block, dict):
            if block.get("type") == "text" and block.get("text"):
                out.append(str(block.get("text")))
            continue
        if getattr(block, "type", None) == "text":
            text = getattr(block, "text", "")
            if text:
                out.append(str(text))
    return "\n".join(out).strip()


def _generate_assistant_reply(
    user_message,
    chat_history,
    readiness,
    model_selection,
    context_budget=None,
    user=None,
    user_id=None,
    thread_id=None,
    intake_context=None,
):
    fallback_reply = _next_question(readiness)
    api_key = _anthropic_api_key()
    if not api_key:
        return fallback_reply, {"provider": "heuristic", "model": None, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}, [], []

    try:
        import anthropic
    except Exception:
        return fallback_reply, {"provider": "heuristic", "model": None, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}, [], []

    model_name = _anthropic_model_for_selection(model_selection)
    max_tokens = int(
        current_app.config.get("AI_AGENT_MAX_OUTPUT_TOKENS")
        or os.getenv("AI_AGENT_MAX_OUTPUT_TOKENS")
        or 260
    )
    temperature = float(
        current_app.config.get("AI_AGENT_TEMPERATURE")
        or os.getenv("AI_AGENT_TEMPERATURE")
        or 0.2
    )

    system_prompt = (
        "You are Jaspen's intake agent. Ask one concise next question that advances readiness when intake is incomplete. "
        "When the user asks to modify scenarios or WBS tasks, call the relevant tools instead of only describing steps. "
        "After a tool succeeds, summarize exactly what was changed. "
        "After a scorecard is generated, proactively suggest scenario modeling when it can improve outcomes. "
        "For example: 'Your Resource Allocation score is 42 — would you like me to create a scenario "
        "exploring what happens if you increase budget by 15%?' "
        "Use the create_scenario tool when the user agrees and always explain the rationale for lever adjustments."
    )
    system_prompt = (
        f"{system_prompt}"
        f"{_intake_context_prompt_suffix(intake_context)}"
        f"{_scenario_modeling_prompt_suffix(user_id, thread_id)}"
        f"{_monitoring_prompt_suffix(user_id)}"
    )
    max_turns = int((context_budget or {}).get("recent_turns") or 16)
    max_turns = max(8, min(80, max_turns))
    messages = _anthropic_messages_from_history(chat_history, max_turns=max_turns)
    summary = _anthropic_history_summary(chat_history, keep_last_turns=max_turns)
    if summary:
        messages = [{"role": "user", "content": summary}, *messages]
    if not messages:
        messages = [{"role": "user", "content": user_message}]

    client = anthropic.Anthropic(api_key=api_key)
    plan_key = to_public_plan(user.subscription_plan) if user else "free"
    can_mutate = bool(thread_id) and (
        is_tool_allowed(plan_key, "scenario_create", "write")
        or is_tool_allowed(plan_key, "wbs_write", "write")
    )
    tools = _anthropic_tool_definitions(enable_mutation_tools=can_mutate)
    total_input_tokens = 0
    total_output_tokens = 0
    executed_actions = []
    executed_mutations = []
    tool_confirmations = []

    try:
        response = client.messages.create(
            model=model_name,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            tools=tools,
            messages=messages,
        )
        total_input_tokens += int(getattr(getattr(response, "usage", None), "input_tokens", 0) or 0)
        total_output_tokens += int(getattr(getattr(response, "usage", None), "output_tokens", 0) or 0)

        # Tool loop: allow Claude to call local readiness/data-contract tools.
        for _ in range(3):
            tool_blocks = [b for b in (response.content or []) if getattr(b, "type", None) == "tool_use" or (isinstance(b, dict) and b.get("type") == "tool_use")]
            if not tool_blocks:
                break

            tool_results = []
            for block in tool_blocks:
                if isinstance(block, dict):
                    tool_name = str(block.get("name") or "").strip()
                    tool_use_id = block.get("id")
                    tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
                else:
                    tool_name = str(getattr(block, "name", "") or "").strip()
                    tool_use_id = getattr(block, "id", None)
                    raw_input = getattr(block, "input", None)
                    tool_input = raw_input if isinstance(raw_input, dict) else {}

                if tool_name in {"get_readiness_snapshot", "get_data_contract"}:
                    result_payload = _anthropic_tool_output(tool_name, readiness)
                else:
                    result_payload = _execute_mutation_tool(
                        tool_name,
                        tool_input,
                        user=user,
                        user_id=user_id,
                        thread_id=thread_id,
                    )
                    if isinstance(result_payload, dict) and result_payload.get("ok"):
                        confirmation = str(result_payload.get("confirmation") or "").strip()
                        if confirmation:
                            tool_confirmations.append(confirmation)
                    if isinstance(result_payload, dict):
                        executed_actions.append({
                            "tool": tool_name,
                            "input": tool_input,
                            "result": result_payload,
                        })
                        executed_mutations.append({
                            "tool": tool_name,
                            "success": bool(result_payload.get("ok")),
                            "result_summary": _mutation_result_summary(tool_name, result_payload),
                            "error": result_payload.get("error"),
                            "code": result_payload.get("code"),
                        })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": json.dumps(result_payload),
                })

            messages.append({"role": "assistant", "content": _anthropic_content_to_dicts(response.content)})
            messages.append({"role": "user", "content": tool_results})
            response = client.messages.create(
                model=model_name,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                tools=tools,
                messages=messages,
            )
            total_input_tokens += int(getattr(getattr(response, "usage", None), "input_tokens", 0) or 0)
            total_output_tokens += int(getattr(getattr(response, "usage", None), "output_tokens", 0) or 0)

        reply = _anthropic_text(response.content) or fallback_reply
        if tool_confirmations:
            confirmations_text = "\n".join(f"- {item}" for item in tool_confirmations)
            if confirmations_text and confirmations_text not in reply:
                reply = f"{reply}\n\nApplied changes:\n{confirmations_text}".strip()
        usage = {
            "provider": "anthropic",
            "model": model_name,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "total_tokens": total_input_tokens + total_output_tokens,
        }
        return reply, usage, executed_actions, executed_mutations
    except Exception:
        current_app.logger.exception("ai_agent anthropic generation failed")
        return fallback_reply, {"provider": "heuristic", "model": model_name, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}, [], []


def _record_usage(session, usage, credits_charged):
    if not isinstance(session, dict):
        return
    usage = usage if isinstance(usage, dict) else {}

    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or (input_tokens + output_tokens))
    provider = usage.get("provider") or "unknown"
    model = usage.get("model")

    summary = session.get("usage_summary")
    if not isinstance(summary, dict):
        summary = {
            "provider": provider,
            "model": model,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "credits_charged": 0,
            "events": 0,
        }
    summary["provider"] = provider
    summary["model"] = model
    summary["input_tokens"] = int(summary.get("input_tokens") or 0) + input_tokens
    summary["output_tokens"] = int(summary.get("output_tokens") or 0) + output_tokens
    summary["total_tokens"] = int(summary.get("total_tokens") or 0) + total_tokens
    summary["credits_charged"] = int(summary.get("credits_charged") or 0) + int(credits_charged or 0)
    summary["events"] = int(summary.get("events") or 0) + 1
    session["usage_summary"] = summary

    events = session.get("usage_events")
    if not isinstance(events, list):
        events = []
    events.append({
        "timestamp": _iso_now(),
        "provider": provider,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "credits_charged": int(credits_charged or 0),
    })
    session["usage_events"] = events[-150:]


def _resolve_model_selection(user, requested_model_type=None, fallback_model_type=None):
    plan_key = to_public_plan(user.subscription_plan)
    allowed_model_types = get_allowed_model_types(plan_key, current_app.config)
    default_model_type = get_default_model_type(plan_key, current_app.config)
    normalized = normalize_model_type(requested_model_type or fallback_model_type or default_model_type)

    if normalized not in allowed_model_types:
        return None, {
            "error": f"Model '{requested_model_type}' is not available on your {plan_key} plan.",
            "code": "model_type_not_allowed",
            "plan_key": plan_key,
            "allowed_model_types": allowed_model_types,
            "default_model_type": default_model_type,
        }

    model_catalog = get_model_catalog(current_app.config)
    model_meta = model_catalog.get(normalized, {})
    return {
        "model_type": normalized,
        "llm_model": model_meta.get("llm_model"),
        "allowed_model_types": allowed_model_types,
        "default_model_type": default_model_type,
    }, None


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


def _data_insights_model():
    return (
        current_app.config.get("AI_DATA_INSIGHTS_MODEL")
        or os.getenv("AI_DATA_INSIGHTS_MODEL")
        or current_app.config.get("AI_AGENT_ANTHROPIC_MODEL")
        or os.getenv("AI_AGENT_ANTHROPIC_MODEL")
        or "claude-3-7-sonnet-latest"
    )


def _dataset_from_upload(uploaded_file):
    try:
        import pandas as pd
    except Exception as e:
        raise RuntimeError(f"pandas is required for data analysis: {e}")

    uploaded_file.seek(0, 2)
    file_size = uploaded_file.tell()
    uploaded_file.seek(0)
    if file_size > 10 * 1024 * 1024:
        raise ValueError("File size exceeds 10 MB limit.")

    raw_name = str(getattr(uploaded_file, "filename", "") or "upload").strip() or "upload"
    filename = re.sub(r"[^a-zA-Z0-9._-]", "_", raw_name)[:255] or "upload"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    content = uploaded_file.read()
    if not content:
        raise ValueError("Uploaded file is empty.")

    bio = io.BytesIO(content)
    if ext in ("csv", "txt"):
        df = pd.read_csv(bio)
    elif ext in ("xlsx", "xls"):
        try:
            df = pd.read_excel(bio)
        except Exception as exc:
            raise ValueError(f"Could not parse Excel file ({filename}): {exc}")
    else:
        raise ValueError("Unsupported file type. Upload CSV or Excel (.csv/.xlsx/.xls).")

    if df is None or df.empty:
        raise ValueError("Dataset has no rows.")
    return df, filename


def _linear_slope(values):
    n = len(values)
    if n < 2:
        return 0.0
    sum_x = (n - 1) * n / 2.0
    sum_x2 = (n - 1) * n * (2 * n - 1) / 6.0
    sum_y = float(sum(values))
    sum_xy = sum(i * float(v) for i, v in enumerate(values))
    denom = (n * sum_x2) - (sum_x ** 2)
    if abs(denom) < 1e-12:
        return 0.0
    return ((n * sum_xy) - (sum_x * sum_y)) / denom


def _summarize_dataset(df):
    try:
        import pandas as pd
    except Exception as e:
        raise RuntimeError(f"pandas is required for data analysis: {e}")

    row_count = int(df.shape[0])
    column_count = int(df.shape[1])
    columns = [str(c) for c in list(df.columns)]
    numeric_cols = [str(c) for c in list(df.select_dtypes(include=["number"]).columns)]
    categorical_cols = [c for c in columns if c not in numeric_cols]

    trends = []
    anomalies = []
    risk_indicators = []
    opportunities = []

    for col in numeric_cols:
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        if series.empty:
            continue

        values = [float(v) for v in series.tolist()]
        mean_val = float(sum(values) / len(values))
        variance = float(sum((v - mean_val) ** 2 for v in values) / max(1, len(values)))
        std_val = math.sqrt(variance)
        slope = _linear_slope(values)
        rel_slope = (slope / max(abs(mean_val), 1.0))

        direction = "stable"
        if rel_slope > 0.01:
            direction = "increasing"
        elif rel_slope < -0.01:
            direction = "decreasing"

        anomaly_count = 0
        if std_val > 1e-9:
            anomaly_count = sum(1 for v in values if abs((v - mean_val) / std_val) >= 3.0)

        trends.append({
            "metric": col,
            "direction": direction,
            "slope": round(float(slope), 6),
            "mean": round(mean_val, 4),
            "latest": round(values[-1], 4),
        })
        anomalies.append({
            "metric": col,
            "count": int(anomaly_count),
            "pct_rows": round((anomaly_count / max(1, len(values))) * 100.0, 2),
        })

        if direction == "decreasing":
            risk_indicators.append(f"{col} is trending downward and may impact delivery performance.")
        elif direction == "increasing":
            opportunities.append(f"{col} shows positive momentum and may support higher-confidence targets.")
        if anomaly_count > max(2, int(len(values) * 0.05)):
            risk_indicators.append(f"{col} has elevated outlier frequency; validate data quality or process variance.")

    trends_sorted = sorted(
        trends,
        key=lambda x: abs(float(x.get("slope") or 0.0)),
        reverse=True,
    )
    anomalies_sorted = sorted(anomalies, key=lambda x: x.get("count", 0), reverse=True)

    return {
        "row_count": row_count,
        "column_count": column_count,
        "columns": columns,
        "numeric_columns": numeric_cols,
        "categorical_columns": categorical_cols,
        "trends": trends_sorted[:8],
        "anomalies": anomalies_sorted[:8],
        "risk_indicators": risk_indicators[:8],
        "opportunities": opportunities[:8],
    }


def _heuristic_insight_text(summary):
    trend_bits = []
    for item in (summary.get("trends") or [])[:3]:
        trend_bits.append(f"{item.get('metric')}: {item.get('direction')}")
    anomaly_bits = []
    for item in (summary.get("anomalies") or [])[:3]:
        if int(item.get("count") or 0) > 0:
            anomaly_bits.append(f"{item.get('metric')} ({item.get('count')} outliers)")

    lead = f"Analyzed {summary.get('row_count')} rows across {summary.get('column_count')} columns."
    trend_sentence = f"Top trends: {', '.join(trend_bits)}." if trend_bits else "No strong numeric trends were detected."
    anomaly_sentence = (
        f"Anomaly watch: {', '.join(anomaly_bits)}."
        if anomaly_bits else
        "No major anomaly clusters were detected."
    )
    risks = summary.get("risk_indicators") or []
    opps = summary.get("opportunities") or []
    risk_sentence = f"Risks: {risks[0]}" if risks else "Risks: None flagged from basic statistical checks."
    opp_sentence = f"Opportunity: {opps[0]}" if opps else "Opportunity: Establish a baseline dashboard and monitor trend inflections weekly."
    return " ".join([lead, trend_sentence, anomaly_sentence, risk_sentence, opp_sentence]).strip()


def _llm_data_insight_text(summary, user_prompt):
    api_key = _anthropic_api_key()
    if not api_key:
        return _heuristic_insight_text(summary), "heuristic"

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        prompt = f"""
You are a strategy data analyst. Summarize dataset trends, risk indicators, and opportunity recommendations.

User focus:
{user_prompt or "General strategy and execution insights"}

Structured summary:
{json.dumps(summary, indent=2)}

Return concise plain text with:
1) Trend summary
2) Top risks
3) Top opportunities
4) Recommended next actions (3 bullets inline)
""".strip()
        response = client.messages.create(
            model=_data_insights_model(),
            max_tokens=600,
            temperature=0.2,
            system="You are a concise strategy analytics assistant.",
            messages=[{"role": "user", "content": prompt}],
        )
        text_parts = []
        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", None) == "text":
                txt = str(getattr(block, "text", "") or "").strip()
                if txt:
                    text_parts.append(txt)
        text = "\n".join(text_parts).strip()
        if not text:
            raise ValueError("empty_llm_response")
        return text, "anthropic"
    except Exception:
        return _heuristic_insight_text(summary), "heuristic"


def _persist_thread_insight(user_id, thread_id, filename, insight_payload, summary_text):
    sessions = load_user_sessions(user_id) or {}
    session_key, session = _resolve_user_session(sessions, thread_id)
    if not isinstance(session, dict):
        session = _new_session(user_id, thread_id, f"Data Upload: {filename}")
        session_key = thread_id

    insights = session.get("ai_insights")
    if not isinstance(insights, list):
        insights = []

    event = {
        "id": f"ins_{uuid.uuid4().hex[:10]}",
        "timestamp": _iso_now(),
        "file_name": filename,
        "summary": summary_text,
        "insight": insight_payload,
    }
    insights = [event, *[item for item in insights if isinstance(item, dict)]][:20]
    session["ai_insights"] = insights

    chat_history = _session_chat_history(session)
    chat_history.append({
        "role": "assistant",
        "content": f"[AI Data Insights] {summary_text}",
        "timestamp": _iso_now(),
    })
    session["chat_history"] = chat_history
    session["timestamp"] = _iso_now()
    sessions[session_key or thread_id] = session
    save_user_sessions(user_id, sessions)
    return event


@ai_agent_bp.route("/conversation/start", methods=["POST"])
@jwt_required()
@limiter.limit("20 per minute")
def conversation_start():
    data = request.get_json() or {}
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    if bootstrap_legacy_credits(user, current_app.config):
        db.session.commit()
    active_org, _ = resolve_active_org_for_user(user)
    active_org_id = active_org.id if active_org else user.active_organization_id

    user_message = str(data.get("message") or data.get("description") or "").strip()
    if not user_message:
        return jsonify({"error": "message is required"}), 400

    thread_id = str(data.get("thread_id") or request.headers.get("X-Session-ID") or f"thread_{uuid.uuid4().hex[:12]}")
    name = str(data.get("name") or user_message[:60] or "Jaspen Intake").strip()
    model_selection, model_error = _resolve_model_selection(user, requested_model_type=data.get("model_type"))
    if model_error:
        return jsonify(model_error), 403

    objective_supplied = any(key in data for key in ("strategy_objective", "objective"))
    requested_objective = normalize_strategy_objective(data.get("strategy_objective") or data.get("objective"))
    intake_context_supplied = isinstance(data.get("intake_context"), dict)
    intake_context_raw = data.get("intake_context") if intake_context_supplied else None
    intake_objective_raw = (intake_context_raw or {}).get("objective") if isinstance(intake_context_raw, dict) else None
    if intake_objective_raw:
        intake_objective = normalize_strategy_objective(intake_objective_raw, default=requested_objective)
        if not objective_supplied:
            requested_objective = intake_objective
            objective_supplied = True
    starter_lever_defaults = _sanitize_lever_defaults(data.get("lever_defaults"))

    sessions = load_user_sessions(user_id)
    session = sessions.get(thread_id) or _new_session(
        user_id,
        thread_id,
        name,
        model_selection["model_type"],
        strategy_objective=requested_objective,
        objective_explicit=objective_supplied,
        organization_id=active_org_id,
        intake_context=intake_context_raw,
        starter_lever_defaults=starter_lever_defaults,
    )
    session["organization_id"] = session.get("organization_id") or active_org_id
    session["created_by_user_id"] = session.get("created_by_user_id") or user_id
    session["visibility"] = str(session.get("visibility") or "private").strip().lower() or "private"
    if not isinstance(session.get("shared_with_user_ids"), list):
        session["shared_with_user_ids"] = []
    existing_objective = normalize_strategy_objective(session.get("strategy_objective"))
    session["strategy_objective"] = requested_objective if objective_supplied else existing_objective
    if objective_supplied:
        session["objective_explicitly_set"] = True
    elif "objective_explicitly_set" not in session:
        session["objective_explicitly_set"] = False
    if intake_context_supplied:
        session["intake_context"] = _sanitize_intake_context(
            intake_context_raw,
            fallback_objective=session.get("strategy_objective"),
        )
    else:
        session["intake_context"] = _sanitize_intake_context(
            session.get("intake_context"),
            fallback_objective=session.get("strategy_objective"),
        )
    session["intake_context"]["objective"] = normalize_strategy_objective(
        session.get("strategy_objective"),
        default=session["intake_context"].get("objective") or "balanced",
    )
    if starter_lever_defaults:
        session["starter_lever_defaults"] = starter_lever_defaults
    elif not isinstance(session.get("starter_lever_defaults"), dict):
        session["starter_lever_defaults"] = {}

    chat_history = session.get("chat_history")
    if not isinstance(chat_history, list):
        chat_history = []

    chat_history.append({"role": "user", "content": user_message, "timestamp": _iso_now()})
    readiness = _compute_readiness(chat_history)
    context_budget = get_context_budget(to_public_plan(user.subscription_plan))
    assistant_reply, usage, actions, mutations = _generate_assistant_reply(
        user_message,
        chat_history,
        readiness,
        model_selection,
        context_budget=context_budget,
        user=user,
        user_id=user_id,
        thread_id=thread_id,
        intake_context=session.get("intake_context"),
    )

    credits_charged = _estimate_usage_credit_charge(usage.get("total_tokens"), model_selection["model_type"])
    charged, remaining = consume_credits(user, credits_charged)
    if not charged:
        return jsonify({
            "error": "Insufficient credits",
            "required_credits": credits_charged,
            "credits_remaining": user.credits_remaining,
            "plan_key": to_public_plan(user.subscription_plan),
            "monthly_credit_limit": get_monthly_credit_limit(user.subscription_plan, current_app.config),
            "suggestion": "Purchase an overage pack or upgrade your plan.",
        }), 402

    chat_history.append({"role": "assistant", "content": assistant_reply, "timestamp": _iso_now()})

    session["chat_history"] = chat_history
    session["name"] = name
    session["model_type"] = model_selection["model_type"]
    session["timestamp"] = _iso_now()
    session["status"] = "in_progress"
    _record_usage(session, usage, credits_charged)
    sessions[thread_id] = session
    if not save_user_sessions(user_id, sessions):
        return jsonify({"error": "Failed to persist conversation state"}), 500

    return jsonify({
        "thread_id": thread_id,
        "session_id": thread_id,
        "reply": assistant_reply,
        "message": assistant_reply,
        "model_type": model_selection["model_type"],
        "allowed_model_types": model_selection["allowed_model_types"],
        "actions": actions if isinstance(actions, list) else [],
        "mutations": mutations if isinstance(mutations, list) else [],
        "tool_results": mutations if isinstance(mutations, list) else [],
        "usage": usage,
        "context_budget": context_budget,
        "credits": {
            "charged": credits_charged,
            "remaining": remaining,
        },
        "readiness": {
            "percent": readiness["overall"]["percent"],
            "categories": readiness["categories"],
            "items": readiness.get("items", []),
            "checklist_summary": readiness.get("checklist_summary", {}),
            "version": readiness.get("version"),
            "updated_at": _iso_now(),
        },
        "status": "gathering_info",
        "strategy_objective": session.get("strategy_objective") or "balanced",
        "objective_explicitly_set": bool(session.get("objective_explicitly_set")),
        "intake_context": session.get("intake_context") if isinstance(session.get("intake_context"), dict) else {},
        "organization_id": session.get("organization_id"),
        "visibility": session.get("visibility") or "private",
        "objective_options": list(STRATEGY_OBJECTIVE_OPTIONS),
    }), 200


@ai_agent_bp.route("/conversation/continue", methods=["POST"])
@jwt_required()
@limiter.limit("30 per minute")
def conversation_continue():
    data = request.get_json() or {}
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    if bootstrap_legacy_credits(user, current_app.config):
        db.session.commit()
    active_org, _ = resolve_active_org_for_user(user)
    active_org_id = active_org.id if active_org else user.active_organization_id

    thread_id = str(data.get("thread_id") or data.get("session_id") or request.headers.get("X-Session-ID") or "").strip()
    user_message = str(data.get("message") or data.get("user_message") or "").strip()

    if not thread_id:
        return jsonify({"error": "thread_id or session_id is required"}), 400
    if not user_message:
        return jsonify({"error": "message is required"}), 400

    sessions = load_user_sessions(user_id)
    session = sessions.get(thread_id)
    fallback_model_type = (session or {}).get("model_type")
    model_selection, model_error = _resolve_model_selection(
        user,
        requested_model_type=data.get("model_type"),
        fallback_model_type=fallback_model_type,
    )
    if model_error:
        return jsonify(model_error), 403

    objective_supplied = any(key in data for key in ("strategy_objective", "objective"))
    requested_objective = normalize_strategy_objective(data.get("strategy_objective") or data.get("objective"))
    intake_context_supplied = isinstance(data.get("intake_context"), dict)
    intake_context_raw = data.get("intake_context") if intake_context_supplied else None
    intake_objective_raw = (intake_context_raw or {}).get("objective") if isinstance(intake_context_raw, dict) else None
    if intake_objective_raw:
        intake_objective = normalize_strategy_objective(intake_objective_raw, default=requested_objective)
        if not objective_supplied:
            requested_objective = intake_objective
            objective_supplied = True
    starter_lever_defaults = _sanitize_lever_defaults(data.get("lever_defaults"))

    session = session or _new_session(
        user_id,
        thread_id,
        "Jaspen Intake",
        model_selection["model_type"],
        strategy_objective=requested_objective,
        objective_explicit=objective_supplied,
        organization_id=active_org_id,
        intake_context=intake_context_raw,
        starter_lever_defaults=starter_lever_defaults,
    )
    session["organization_id"] = session.get("organization_id") or active_org_id
    session["created_by_user_id"] = session.get("created_by_user_id") or user_id
    session["visibility"] = str(session.get("visibility") or "private").strip().lower() or "private"
    if not isinstance(session.get("shared_with_user_ids"), list):
        session["shared_with_user_ids"] = []
    existing_objective = normalize_strategy_objective(session.get("strategy_objective"))
    session["strategy_objective"] = requested_objective if objective_supplied else existing_objective
    if objective_supplied:
        session["objective_explicitly_set"] = True
    elif "objective_explicitly_set" not in session:
        session["objective_explicitly_set"] = False
    if intake_context_supplied:
        session["intake_context"] = _sanitize_intake_context(
            intake_context_raw,
            fallback_objective=session.get("strategy_objective"),
        )
    else:
        session["intake_context"] = _sanitize_intake_context(
            session.get("intake_context"),
            fallback_objective=session.get("strategy_objective"),
        )
    session["intake_context"]["objective"] = normalize_strategy_objective(
        session.get("strategy_objective"),
        default=session["intake_context"].get("objective") or "balanced",
    )
    if starter_lever_defaults:
        session["starter_lever_defaults"] = starter_lever_defaults
    elif not isinstance(session.get("starter_lever_defaults"), dict):
        session["starter_lever_defaults"] = {}
    chat_history = session.get("chat_history")
    if not isinstance(chat_history, list):
        chat_history = []

    chat_history.append({"role": "user", "content": user_message, "timestamp": _iso_now()})
    readiness = _compute_readiness(chat_history)
    context_budget = get_context_budget(to_public_plan(user.subscription_plan))
    assistant_reply, usage, actions, mutations = _generate_assistant_reply(
        user_message,
        chat_history,
        readiness,
        model_selection,
        context_budget=context_budget,
        user=user,
        user_id=user_id,
        thread_id=thread_id,
        intake_context=session.get("intake_context"),
    )

    credits_charged = _estimate_usage_credit_charge(usage.get("total_tokens"), model_selection["model_type"])
    charged, remaining = consume_credits(user, credits_charged)
    if not charged:
        return jsonify({
            "error": "Insufficient credits",
            "required_credits": credits_charged,
            "credits_remaining": user.credits_remaining,
            "plan_key": to_public_plan(user.subscription_plan),
            "monthly_credit_limit": get_monthly_credit_limit(user.subscription_plan, current_app.config),
            "suggestion": "Purchase an overage pack or upgrade your plan.",
        }), 402

    chat_history.append({"role": "assistant", "content": assistant_reply, "timestamp": _iso_now()})

    session["chat_history"] = chat_history
    session["model_type"] = model_selection["model_type"]
    session["timestamp"] = _iso_now()
    session["status"] = "ready_to_analyze" if readiness["overall"]["percent"] >= 85 else "in_progress"
    _record_usage(session, usage, credits_charged)
    sessions[thread_id] = session
    if not save_user_sessions(user_id, sessions):
        return jsonify({"error": "Failed to persist conversation state"}), 500

    return jsonify({
        "thread_id": thread_id,
        "session_id": thread_id,
        "reply": assistant_reply,
        "message": assistant_reply,
        "model_type": model_selection["model_type"],
        "allowed_model_types": model_selection["allowed_model_types"],
        "actions": actions if isinstance(actions, list) else [],
        "mutations": mutations if isinstance(mutations, list) else [],
        "tool_results": mutations if isinstance(mutations, list) else [],
        "usage": usage,
        "context_budget": context_budget,
        "credits": {
            "charged": credits_charged,
            "remaining": remaining,
        },
        "readiness": {
            "percent": readiness["overall"]["percent"],
            "categories": readiness["categories"],
            "items": readiness.get("items", []),
            "checklist_summary": readiness.get("checklist_summary", {}),
            "version": readiness.get("version"),
            "updated_at": _iso_now(),
        },
        "status": "ready_to_analyze" if readiness["overall"]["percent"] >= 85 else "gathering_info",
        "strategy_objective": session.get("strategy_objective") or "balanced",
        "objective_explicitly_set": bool(session.get("objective_explicitly_set")),
        "intake_context": session.get("intake_context") if isinstance(session.get("intake_context"), dict) else {},
        "organization_id": session.get("organization_id"),
        "visibility": session.get("visibility") or "private",
        "objective_options": list(STRATEGY_OBJECTIVE_OPTIONS),
    }), 200


@ai_agent_bp.route("/readiness/spec", methods=["GET"])
def readiness_spec():
    spec = dict(_active_readiness_spec())
    spec["active_version"] = _active_readiness_version()
    spec["available_versions"] = list(READINESS_SPECS.keys())
    spec["checklist_mode"] = "adaptive"
    spec["context_profiles"] = [profile.get("key") for profile in ADAPTIVE_CONTEXT_PROFILES]
    if spec.get("version") == "readiness-v2":
        spec["data_contract"] = EVIDENCE_DATA_CONTRACT
    return jsonify(spec), 200


@ai_agent_bp.route("/tools/catalog", methods=["GET"])
def tools_catalog():
    return jsonify({
        "version": "1.0",
        "tools": get_tool_catalog(),
        "context_budget_defaults": get_context_budget("free"),
    }), 200


@ai_agent_bp.route("/tools/entitlements", methods=["GET"])
@jwt_required()
def tools_entitlements():
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({"error": "User not found"}), 404

    plan_key = to_public_plan(user.subscription_plan)
    return jsonify({
        "plan_key": plan_key,
        "context_budget": get_context_budget(plan_key),
        "tools": get_tool_entitlements(plan_key),
    }), 200


@ai_agent_bp.route("/provider/status", methods=["GET"])
@jwt_required()
def provider_status():
    api_key = _anthropic_api_key()
    return jsonify({
        "anthropic_configured": bool(api_key),
        "anthropic_model": str(
            current_app.config.get("AI_AGENT_ANTHROPIC_MODEL")
            or os.getenv("AI_AGENT_ANTHROPIC_MODEL")
            or "claude-3-7-sonnet-latest"
        ),
    }), 200


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
            "name": candidate.get("name") or "Jaspen Intake",
            "model_type": normalize_model_type(candidate.get("model_type")) or None,
            "strategy_objective": normalize_strategy_objective(candidate.get("strategy_objective")),
            "objective_explicitly_set": bool(candidate.get("objective_explicitly_set")),
            "intake_context": _sanitize_intake_context(
                candidate.get("intake_context"),
                fallback_objective=candidate.get("strategy_objective"),
            ),
            "starter_lever_defaults": _sanitize_lever_defaults(candidate.get("starter_lever_defaults")),
            "organization_id": candidate.get("organization_id"),
            "created_by_user_id": candidate.get("created_by_user_id"),
            "visibility": candidate.get("visibility") or "private",
            "shared_with_user_ids": candidate.get("shared_with_user_ids") if isinstance(candidate.get("shared_with_user_ids"), list) else [],
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
        "name": session.get("name") or "Jaspen Intake",
        "model_type": normalize_model_type(session.get("model_type")) or None,
        "strategy_objective": normalize_strategy_objective(session.get("strategy_objective")),
        "objective_explicitly_set": bool(session.get("objective_explicitly_set")),
        "intake_context": _sanitize_intake_context(
            session.get("intake_context"),
            fallback_objective=session.get("strategy_objective"),
        ),
        "starter_lever_defaults": _sanitize_lever_defaults(session.get("starter_lever_defaults")),
        "organization_id": session.get("organization_id"),
        "created_by_user_id": session.get("created_by_user_id"),
        "visibility": session.get("visibility") or "private",
        "shared_with_user_ids": session.get("shared_with_user_ids") if isinstance(session.get("shared_with_user_ids"), list) else [],
        "status": session.get("status") or ("completed" if analyses else "in_progress"),
        "created_at": session.get("created"),
        "updated_at": session.get("timestamp"),
        "conversation_history": chat_history,
        "readiness_snapshot": readiness,
    }

    session_payload = {
        **session,
        "session_id": resolved_thread_id,
        "model_type": normalize_model_type(session.get("model_type")) or None,
        "strategy_objective": normalize_strategy_objective(session.get("strategy_objective")),
        "objective_explicitly_set": bool(session.get("objective_explicitly_set")),
        "intake_context": _sanitize_intake_context(
            session.get("intake_context"),
            fallback_objective=session.get("strategy_objective"),
        ),
        "starter_lever_defaults": _sanitize_lever_defaults(session.get("starter_lever_defaults")),
        "organization_id": session.get("organization_id"),
        "created_by_user_id": session.get("created_by_user_id"),
        "visibility": session.get("visibility") or "private",
        "shared_with_user_ids": session.get("shared_with_user_ids") if isinstance(session.get("shared_with_user_ids"), list) else [],
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
    status_supplied = "status" in data
    objective_supplied = any(key in data for key in ("strategy_objective", "objective"))
    visibility_supplied = "visibility" in data
    shared_users_supplied = "shared_with_user_ids" in data
    objective_explicit_supplied = "objective_explicitly_set" in data
    intake_context_supplied = "intake_context" in data
    starter_lever_defaults_supplied = "starter_lever_defaults" in data or "lever_defaults" in data
    if (
        not name
        and not objective_supplied
        and not objective_explicit_supplied
        and not visibility_supplied
        and not shared_users_supplied
        and not status_supplied
        and not intake_context_supplied
        and not starter_lever_defaults_supplied
    ):
        return jsonify(
            {"error": "name, status, strategy_objective, intake_context, visibility, or shared_with_user_ids is required"}
        ), 400

    user_id = get_jwt_identity()
    sessions = load_user_sessions(user_id) or {}
    session_key, session = _resolve_user_session(sessions, thread_id)
    if not isinstance(session, dict):
        return jsonify({"error": "Thread not found"}), 404

    resolved_thread_id = str(session.get("session_id") or session_key or thread_id)
    if name:
        session["name"] = name
    if objective_supplied:
        session["strategy_objective"] = normalize_strategy_objective(
            data.get("strategy_objective") or data.get("objective")
        )
    if objective_explicit_supplied:
        session["objective_explicitly_set"] = bool(data.get("objective_explicitly_set"))
    elif objective_supplied:
        session["objective_explicitly_set"] = True
    elif "objective_explicitly_set" not in session:
        session["objective_explicitly_set"] = False
    if intake_context_supplied:
        session["intake_context"] = _sanitize_intake_context(
            data.get("intake_context"),
            fallback_objective=session.get("strategy_objective"),
        )
    else:
        session["intake_context"] = _sanitize_intake_context(
            session.get("intake_context"),
            fallback_objective=session.get("strategy_objective"),
        )
    session["intake_context"]["objective"] = normalize_strategy_objective(
        session.get("strategy_objective"),
        default=session["intake_context"].get("objective") or "balanced",
    )
    if starter_lever_defaults_supplied:
        incoming_defaults = data.get("starter_lever_defaults")
        if incoming_defaults is None and "lever_defaults" in data:
            incoming_defaults = data.get("lever_defaults")
        session["starter_lever_defaults"] = _sanitize_lever_defaults(incoming_defaults)
    elif not isinstance(session.get("starter_lever_defaults"), dict):
        session["starter_lever_defaults"] = {}
    if visibility_supplied:
        raw_visibility = str(data.get("visibility") or "").strip().lower()
        if raw_visibility in {"private", "team", "specific"}:
            session["visibility"] = raw_visibility
    if shared_users_supplied:
        raw_ids = data.get("shared_with_user_ids")
        if isinstance(raw_ids, list):
            cleaned = []
            seen = set()
            for item in raw_ids:
                candidate = str(item or "").strip()
                if not candidate or candidate in seen:
                    continue
                cleaned.append(candidate)
                seen.add(candidate)
            session["shared_with_user_ids"] = cleaned
    if status_supplied:
        raw_status = str(data.get("status") or "").strip().lower()
        if raw_status not in {"in_progress", "ready_to_analyze", "completed", "archived"}:
            return jsonify({"error": "status must be one of in_progress, ready_to_analyze, completed, archived"}), 400
        session["status"] = raw_status
    if not session.get("created_by_user_id"):
        session["created_by_user_id"] = str(user_id)
    session["timestamp"] = _iso_now()
    sessions[session_key or resolved_thread_id] = session
    save_user_sessions(user_id, sessions)

    chat_history = _session_chat_history(session)
    readiness = session.get("readiness") if isinstance(session.get("readiness"), dict) else _compute_readiness(chat_history)
    session_payload = {
        **session,
        "session_id": resolved_thread_id,
        "strategy_objective": normalize_strategy_objective(session.get("strategy_objective")),
        "objective_explicitly_set": bool(session.get("objective_explicitly_set")),
        "intake_context": _sanitize_intake_context(
            session.get("intake_context"),
            fallback_objective=session.get("strategy_objective"),
        ),
        "starter_lever_defaults": _sanitize_lever_defaults(session.get("starter_lever_defaults")),
        "visibility": session.get("visibility") or "private",
        "shared_with_user_ids": session.get("shared_with_user_ids") if isinstance(session.get("shared_with_user_ids"), list) else [],
        "chat_history": chat_history,
        "readiness": readiness,
    }

    return jsonify({
        "success": True,
        "thread": {
            "id": resolved_thread_id,
            "name": session.get("name") or "Jaspen Intake",
            "strategy_objective": normalize_strategy_objective(session.get("strategy_objective")),
            "objective_explicitly_set": bool(session.get("objective_explicitly_set")),
            "intake_context": _sanitize_intake_context(
                session.get("intake_context"),
                fallback_objective=session.get("strategy_objective"),
            ),
            "starter_lever_defaults": _sanitize_lever_defaults(session.get("starter_lever_defaults")),
            "visibility": session.get("visibility") or "private",
            "shared_with_user_ids": session.get("shared_with_user_ids") if isinstance(session.get("shared_with_user_ids"), list) else [],
            "status": session.get("status") or "in_progress",
            "updated_at": session.get("timestamp"),
        },
        "session": session_payload,
    }), 200


@ai_agent_bp.route("/threads/<thread_id>/usage", methods=["GET"])
@jwt_required()
def get_thread_usage(thread_id):
    user_id = get_jwt_identity()
    sessions = load_user_sessions(user_id) or {}
    session_key, session = _resolve_user_session(sessions, thread_id)
    if not isinstance(session, dict):
        return jsonify({"error": "Thread not found"}), 404

    resolved_thread_id = str(session.get("session_id") or session_key or thread_id)
    usage_summary = session.get("usage_summary") if isinstance(session.get("usage_summary"), dict) else {}
    usage_events = session.get("usage_events") if isinstance(session.get("usage_events"), list) else []
    return jsonify({
        "thread_id": resolved_thread_id,
        "usage_summary": usage_summary,
        "usage_events": usage_events,
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


@ai_agent_bp.route("/analyze-data", methods=["POST"])
@jwt_required()
def analyze_data():
    """
    Upload CSV/Excel data and return AI-driven trend/risk/opportunity insights.
    Persists insights onto the thread (when thread_id provided) for richer scoring context.
    """
    try:
        user_id = get_jwt_identity()
        thread_id = str(
            request.form.get("thread_id")
            or request.args.get("thread_id")
            or request.headers.get("X-Session-ID")
            or ""
        ).strip() or None
        user_prompt = str(request.form.get("prompt") or request.form.get("instruction") or "").strip()

        uploaded = request.files.get("file")
        if uploaded is None:
            return jsonify({"error": "file is required (multipart/form-data)"}), 400
        if not str(getattr(uploaded, "filename", "") or "").strip():
            return jsonify({"error": "Uploaded file must have a name."}), 400

        df, filename = _dataset_from_upload(uploaded)
        summary = _summarize_dataset(df)
        insight_text, provider = _llm_data_insight_text(summary, user_prompt)

        try:
            preview_df = df.head(5).copy()
            preview_json = preview_df.where(preview_df.notna(), None).to_json(orient="records", date_format="iso")
            preview_rows = json.loads(preview_json)
        except Exception:
            preview_rows = []

        insight_payload = {
            "file_name": filename,
            "dataset_summary": summary,
            "insight_text": insight_text,
            "provider": provider,
            "timestamp": _iso_now(),
        }

        persisted_event = None
        if thread_id:
            persisted_event = _persist_thread_insight(
                user_id=user_id,
                thread_id=thread_id,
                filename=filename,
                insight_payload=insight_payload,
                summary_text=insight_text,
            )

        return jsonify({
            "success": True,
            "thread_id": thread_id,
            "insight": insight_payload,
            "preview_rows": preview_rows,
            "persisted": bool(persisted_event),
            "persisted_event": persisted_event,
        }), 200
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except RuntimeError as re_err:
        return jsonify({"error": str(re_err)}), 500
    except Exception as e:
        current_app.logger.error("[analyze_data] %s", e)
        return jsonify({"error": "Failed to analyze uploaded data."}), 500
