# backend/app/intake_readiness.py
#
# The deterministic decision-readiness engine — extracted verbatim from
# app/routes/ai_agent.py so it can be imported by the unauthenticated public
# intake endpoint (app/routes/public_intake.py) WITHOUT importing the rest of
# that 14K-line, session/credit/tool-coupled module.
#
# This is a pure move, not a refactor: every name below is byte-identical to
# what lived in ai_agent.py. ai_agent.py now imports everything here back via
# named re-exports, so all of its existing internal call sites (the
# authenticated workspace's readiness computation, the agent's confidence
# framing, etc.) are completely unchanged. See ai_agent.py's imports for the
# re-export list.
#
# NOTE — these specs, keyword lists, and follow-up questions are used by BOTH
# the authenticated workspace and the unauthenticated public homepage (see
# app/routes/public_intake.py). There is exactly one readiness engine and one
# active spec for both surfaces — do not add a homepage-specific
# spec/keyword-set/question-set. Editing a question or keyword here changes
# what the public homepage asks, not just the authenticated sidebar.
#
# Do NOT add imports from app.routes.ai_agent (or anything that imports it)
# here — that would create a circular import, since ai_agent.py imports this
# module. This file must only depend on stdlib + nothing session/Flask-app
# specific beyond os.getenv for the spec-version env var.

import os
import re

# ---------------------------------------------------------------------------
# Strategy objective normalization (used by _compute_readiness and broadly
# elsewhere in ai_agent.py — moved here as the single source of truth so
# there's no circular dependency).
# ---------------------------------------------------------------------------

STRATEGY_OBJECTIVE_OPTIONS = ("balanced", "cost", "speed", "growth")
STRATEGY_OBJECTIVE_ALIASES = {
    "balanced": "balanced",
    "default": "balanced",
    "general": "balanced",
    "transform": "balanced",
    "transformation": "balanced",
    "modernization": "balanced",
    "cost": "cost",
    "cost optimization": "cost",
    "cost-optimization": "cost",
    "efficiency": "cost",
    "profitability": "cost",
    "margin": "cost",
    "margins": "cost",
    "savings": "cost",
    "saving": "cost",
    "roi": "cost",
    "optimize": "cost",
    "optimization": "cost",
    "speed": "speed",
    "speed to market": "speed",
    "speed-to-market": "speed",
    "timeline": "speed",
    "delivery": "speed",
    "accelerate": "speed",
    "acceleration": "speed",
    "fast track": "speed",
    "fast-track": "speed",
    "launch": "speed",
    "growth": "growth",
    "revenue": "growth",
    "expansion": "growth",
    "scale": "growth",
    "scaling": "growth",
    "retention": "growth",
    "churn": "growth",
    "acquisition": "growth",
    "market share": "growth",
    "market-share": "growth",
    "pipeline": "growth",
}


def normalize_strategy_objective(value, default="balanced"):
    text = str(value or "").strip().lower()
    if not text:
        return default
    if text in STRATEGY_OBJECTIVE_ALIASES:
        return STRATEGY_OBJECTIVE_ALIASES[text]
    compact = text.replace("_", " ").replace("-", " ")
    return STRATEGY_OBJECTIVE_ALIASES.get(compact, default)


# ---------------------------------------------------------------------------
# Message text extraction (used broadly in ai_agent.py beyond readiness —
# moved here as the single source of truth for the same circular-import
# reason as above).
# ---------------------------------------------------------------------------

def _attachment_reference_text(attachments):
    parts = []
    for attachment in attachments if isinstance(attachments, list) else []:
        if not isinstance(attachment, dict):
            continue
        name = str(attachment.get("name") or attachment.get("filename") or "").strip()
        media_type = str(attachment.get("type") or attachment.get("media_type") or "").strip()
        kind = str(attachment.get("kind") or "").strip().lower()
        label = kind or media_type or "file"
        if name:
            parts.append(f"{name} ({label})")
    if not parts:
        return ""
    return "Attached files: " + ", ".join(parts[:5])


def _message_text(msg):
    if not isinstance(msg, dict):
        return ""
    content = msg.get("content")
    attachments = msg.get("attachments") if isinstance(msg.get("attachments"), list) else []
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, dict):
        text = str(content.get("text") or content.get("message") or "").strip()
    else:
        text = str(msg.get("text") or msg.get("message") or "").strip()
    if not attachments:
        return text
    attachment_summary = _attachment_reference_text(attachments)
    if text and attachment_summary:
        return f"{text}\n\n{attachment_summary}"
    return text or attachment_summary


# ---------------------------------------------------------------------------
# Readiness specs, keywords, and follow-up questions.
# ---------------------------------------------------------------------------

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
    # required_keys: these categories MUST be complete for ready_to_analyze to trigger,
    # regardless of overall percent. Goal + measurable evidence are non-negotiable gates.
    "required_keys": ["goal_definition", "evidence_baseline"],
    # min_keywords: how many keyword matches a category needs before it counts as complete.
    # 1 is intentional — each keyword in the v2 lists is already specific enough that a
    # single match carries real signal (e.g. "domain expert", "constraint", "reduce").
    # min_word_context=4 in _category_is_addressed already filters one-word replies.
    "min_keywords": 1,
    # Which category key uses the numeric/financial/KPI quality-score path (see
    # _score_data_evidence) instead of plain keyword matching. Generalized so other
    # readiness profiles can name their own evidence category.
    "evidence_category_key": "evidence_baseline",
    "categories": [
        # Required gate: must have a specific outcome + measurable target.
        {"key": "goal_definition",    "label": "Goal Definition",               "weight": 0.20, "step": 1, "required": True},
        # Required gate: must have at least one number or financial/KPI metric.
        # evidence_baseline uses its own quality-score path inside _compute_readiness.
        {"key": "evidence_baseline",  "label": "Current Evidence (Financial/KPI)", "weight": 0.20, "step": 2, "required": True},
        # Core operational categories — each carries equal weight of the remaining 60%.
        {"key": "sme_drivers",        "label": "SME Drivers (Why)",             "weight": 0.15, "step": 3},
        {"key": "system_mapping",     "label": "System Mapping",                "weight": 0.15, "step": 4},
        {"key": "constraint_unlock",  "label": "Constraint + Unlock",           "weight": 0.15, "step": 5},
        {"key": "execution_sequence", "label": "Execution Sequencing",          "weight": 0.15, "step": 6},
        # Optional — valuable context but not a gate for readiness.
        {"key": "replication_plan",   "label": "Replication Plan",              "weight": 0.00, "step": 7},
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
        # Needs a specific target/metric + time horizon — not just "goal" appearing anywhere.
        "goal_definition": [
            "objective", "north star", "target date", "success metric", "desired outcome",
            "we want to", "we need to", "initiative", "improve", "increase", "decrease",
            "reduce", "grow", "achieve", "deadline", "goal", "target", "outcome",
            "profitability", "profitable", "by month", "within", "from", "cut",
            "lower", "boost", "hit", "reach", "save",
        ],
        # Needs a real number/metric with context — handled separately via evidence quality score,
        # but keywords here back up cases where quality scoring doesn't fire.
        "evidence_baseline": [
            "baseline", "kpi", "metric", "percent", "rate", "score", "churn",
            "revenue", "cost", "margin", "conversion", "retention", "throughput",
            "cycle time", "uptime", "defect", "volume", "budget",
        ],
        # Must reference a person/team with domain knowledge, strategic driver, or root cause.
        "sme_drivers": [
            "stakeholder", "subject matter expert", "sme", "domain expert",
            "root cause", "root-cause", "because", "driving factor", "contributing factor",
            "team lead", "ops team", "sales team", "finance team", "product team",
            "insight", "pattern", "expertise",
            # Strategic "why now" language users naturally use:
            "why now", "seed round", "funding", "investors", "board", "competitive",
            "undercutting", "losing", "pressure", "opportunity", "window",
            "customer demand", "market signal", "proof of concept", "pilot",
            "loi", "letter of intent", "convert", "close the deal",
            "cto", "ceo", "vp", "head of", "years experience", "years in",
        ],
        # Needs to describe a workflow, handoff, or technical integration.
        "system_mapping": [
            "workflow", "process", "handoff", "hand-off", "end-to-end", "step",
            "stage", "pipeline", "funnel", "touchpoint", "team owns", "responsible for",
            "dependencies", "upstream", "downstream", "sequence of",
            # Technical/integration language users naturally use:
            "integrate", "integration", "api", "connector", "data flow", "architecture",
            "stack", "backend", "database", "infrastructure", "ingest", "sync",
            "platform", "middleware", "endpoint", "connect", "feed",
        ],
        # Needs an identified blocker, risk, or unlock action.
        "constraint_unlock": [
            "constraint", "bottleneck", "blocker", "blocking", "critical path",
            "unlock", "gate", "dependency blocks", "waiting on", "holding back",
            "friction", "bandwidth", "capacity", "approval needed",
            # Risk and limitation language users naturally use:
            "risk", "challenge", "limitation", "legacy", "limited", "adapter",
            "workaround", "delay", "adds", "slower", "complex", "complexity",
            "difficult", "hard to", "technical debt", "migration",
        ],
        # Needs sequencing language or an owner/timeline.
        "execution_sequence": [
            "milestone", "timeline", "sequence", "phase", "sprint", "by q",
            "owner", "responsible", "parallel", "dependency", "first we", "then we",
            "next step", "week", "month",
        ],
        # Optional — scale/replication thinking.
        "replication_plan": [
            "replicate", "template", "playbook", "standardize", "rollout",
            "repeat", "scale", "expand to", "other teams", "other sites",
        ],
    },
}

# Per-category "weak" keywords for readiness-v2 — see _category_is_addressed's
# docstring for the mechanism. A keyword is weak if it's common enough in
# unrelated writing (generic problem/status language, everyday English) that
# seeing it once is not real evidence this category was actually addressed.
# Keywords NOT listed here for a category are treated as strong: specific
# enough multi-word phrases (e.g. "domain expert", "critical path", "we need
# to") that a single hit is trustworthy on its own. Only readiness-v2 has this
# refinement; v1's short, already-generic-by-design lists are untouched.
WEAK_KEYWORDS_BY_VERSION = {
    "readiness-v2": {
        "goal_definition": {
            "objective", "improve", "increase", "decrease", "reduce", "grow",
            "achieve", "deadline", "goal", "target", "outcome", "within",
            "from", "cut", "lower", "boost", "hit", "reach", "save",
        },
        "evidence_baseline": {
            "baseline", "metric", "percent", "rate", "score", "revenue",
            "cost", "margin", "conversion", "retention", "throughput",
            "uptime", "defect", "volume", "budget",
        },
        "sme_drivers": {
            "stakeholder", "because", "team lead", "ops team", "sales team",
            "finance team", "product team", "insight", "pattern", "expertise",
            "funding", "investors", "board", "competitive", "undercutting",
            "losing", "pressure", "opportunity", "window", "pilot", "convert",
            "cto", "ceo", "vp", "head of", "years experience", "years in",
        },
        "system_mapping": {
            "workflow", "process", "handoff", "step", "stage", "pipeline",
            "funnel", "touchpoint", "responsible for", "dependencies",
            "upstream", "downstream", "sequence of", "integrate",
            "integration", "api", "connector", "architecture", "stack",
            "backend", "database", "infrastructure", "ingest", "sync",
            "platform", "endpoint", "connect", "feed",
        },
        "constraint_unlock": {
            "constraint", "bottleneck", "blocker", "blocking", "unlock",
            "gate", "friction", "bandwidth", "capacity", "risk", "challenge",
            "limitation", "legacy", "limited", "adapter", "workaround",
            "delay", "adds", "slower", "complex", "complexity", "difficult",
            "hard to", "migration",
        },
        "execution_sequence": {
            "milestone", "timeline", "sequence", "phase", "sprint", "by q",
            "owner", "responsible", "parallel", "dependency", "next step",
            "week", "month",
        },
        # Optional, zero-weight category — not a gate, left permissive.
        "replication_plan": set(),
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
        "evidence_baseline": "Share current evidence: current vs target metrics, timeframe, and source (financial or KPI).",
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

OBJECTIVE_FOCUS_PROFILES = {
    "balanced": [
        {
            "id": "balanced_financial_impact",
            "label": "Financial impact and ROI path are explicit",
            "keywords": ["roi", "revenue", "margin", "cost", "savings", "budget", "financial"],
            "question": "What financial outcome matters most here, and how will you measure ROI or value creation?",
        },
        {
            "id": "balanced_execution_feasibility",
            "label": "Execution feasibility and ownership are grounded",
            "keywords": ["owner", "team", "resource", "capacity", "timeline", "feasible"],
            "question": "Who owns delivery, what capacity exists, and what makes this feasible now?",
        },
        {
            "id": "balanced_market_position",
            "label": "Customer or market impact is clear",
            "keywords": ["customer", "buyer", "market", "segment", "adoption", "competitive"],
            "question": "Which customer or market outcome improves if this succeeds?",
        },
        {
            "id": "balanced_operational_efficiency",
            "label": "Operational workflow changes are mapped",
            "keywords": ["workflow", "process", "handoff", "bottleneck", "system"],
            "question": "Which workflow or operating model changes are required to make this stick?",
        },
    ],
    "cost": [
        {
            "id": "cost_baseline",
            "label": "Current cost level and target savings are defined",
            "keywords": ["cost", "expense", "budget", "savings", "baseline", "target"],
            "question": "What are your current costs, and what savings target are you trying to achieve?",
        },
        {
            "id": "cost_efficiency_levers",
            "label": "Efficiency levers and waste sources are identified",
            "keywords": ["waste", "redundant", "efficiency", "utilization", "overlap", "duplicate"],
            "question": "Where is the waste or overlap today, and which levers will reduce it fastest?",
        },
        {
            "id": "cost_guardrails",
            "label": "ROI guardrails and risk limits are documented",
            "keywords": ["roi", "payback", "risk", "guardrail", "tradeoff", "threshold"],
            "question": "What ROI or payback threshold must this meet, and what risks cannot be introduced to get there?",
        },
    ],
    "speed": [
        {
            "id": "speed_critical_path",
            "label": "Critical path and launch sequence are explicit",
            "keywords": ["critical path", "sequence", "milestone", "deadline", "launch", "timeline"],
            "question": "What is the critical path to launch, and which milestones must happen in order?",
        },
        {
            "id": "speed_dependency_risk",
            "label": "Dependencies and blockers are called out early",
            "keywords": ["dependency", "blocker", "approval", "handoff", "risk", "constraint"],
            "question": "Which dependencies or approvals could slow this down, and how will you unblock them?",
        },
        {
            "id": "speed_capacity",
            "label": "Delivery capacity and staffing plan are realistic",
            "keywords": ["capacity", "staffing", "bandwidth", "resource", "owner", "team"],
            "question": "Do you have the staffing and decision bandwidth to move at the requested pace?",
        },
    ],
    "growth": [
        {
            "id": "growth_segment",
            "label": "Target segment and growth thesis are explicit",
            "keywords": ["segment", "customer", "growth", "revenue", "market", "expansion"],
            "question": "Which segment or revenue motion is this expected to grow first, and why that one?",
        },
        {
            "id": "growth_funnel",
            "label": "Acquisition or conversion funnel is defined",
            "keywords": ["acquisition", "conversion", "pipeline", "funnel", "lead", "activation"],
            "question": "What funnel stage do you expect to improve, and what is your current conversion rate?",
        },
        {
            "id": "growth_retention",
            "label": "Retention or expansion signals are identified",
            "keywords": ["retention", "adoption", "expansion", "upsell", "churn", "engagement"],
            "question": "Which retention, adoption, or expansion signal will prove this is driving durable growth?",
        },
    ],
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

MAX_USER_MESSAGE_LENGTH = 12_000


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

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


def _build_objective_focus_items(objective, user_text, user_turns):
    items = []
    for item in OBJECTIVE_FOCUS_PROFILES.get(objective, OBJECTIVE_FOCUS_PROFILES["balanced"]):
        hits = sum(1 for term in item.get("keywords", []) if term in user_text)
        if hits > 0:
            percent = min(100, 45 + hits * 18)
        else:
            percent = 0
        items.append({
            "id": item.get("id"),
            "key": item.get("id"),
            "label": item.get("label"),
            "type": "objective",
            "context_module": objective,
            "status": _status_from_percent(percent),
            "percent": int(percent),
            "confidence": round(max(0.2, min(0.99, percent / 100)), 2),
            "next_question": item.get("question"),
            "step": None,
        })
    return items


def _build_readiness_items(spec, version, categories, user_text, user_turns, objective="balanced"):
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

    items.extend(_build_objective_focus_items(objective, user_text, user_turns))

    # Context-specific items (adaptive by request type)
    for profile in _selected_context_profiles(user_text):
        for item in profile.get("items", []):
            hits = sum(1 for term in item.get("keywords", []) if term in user_text)
            if hits > 0:
                percent = min(100, 55 + hits * 20)
            else:
                percent = 0
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


def _category_is_addressed(key, chat_history, keyword_map, min_word_context=4, min_keyword_count=1, weak_keywords=None):
    """
    A category is addressed only if at least `min_keyword_count` distinct keywords
    from the category's list appear across all user messages, and each matching message
    has at least `min_word_context` surrounding words (prevents one-word replies from
    ticking off categories).

    Increasing min_keyword_count to 2+ prevents incidental single-word matches
    (e.g. "process", "why") from marking a category complete.

    weak_keywords (optional): a set of this category's own keywords that are common
    enough in unrelated writing (engineering status updates, generic problem-talk,
    etc.) that a single hit is not reliable evidence — e.g. "blocker", "risk",
    "delay". A category still completes instantly on any match that is NOT in this
    set (those keywords are specific enough to stand alone, e.g. "domain expert",
    "critical path"). If every match found is weak, at least 2 DISTINCT weak
    keywords are required, so one incidental generic word can no longer complete
    a category by itself. This guards against exactly the failure mode where an
    unrelated document (e.g. a software engineering status report containing the
    word "blocker") got marked as satisfying a business-decision category it was
    never actually about.
    """
    keywords = keyword_map.get(key, [])
    if not keywords:
        return False

    # Collect all user message text (lowercased, concatenated for multi-turn scanning)
    all_user_text = ""
    for msg in (chat_history or []):
        if not isinstance(msg, dict) or str(msg.get("role", "")).lower() != "user":
            continue
        content = str(_message_text(msg) or "").strip().lower()
        if len(content.split()) < max(1, int(min_word_context or 4)):
            continue
        all_user_text += " " + content

    matched = [
        str(kw).strip().lower() for kw in keywords
        if str(kw or "").strip().lower() and str(kw or "").strip().lower() in all_user_text
    ]
    if len(matched) < max(1, int(min_keyword_count or 1)):
        return False

    weak = weak_keywords or set()
    if any(kw not in weak for kw in matched):
        return True
    return len(set(matched)) >= 2


def _compute_readiness(chat_history, strategy_objective="balanced", spec=None):
    """Compute readiness against a readiness spec (profile).

    `spec` lets a caller pick a different profile (e.g. the pre-signup
    decision-intake profile) than whatever is globally active via
    READINESS_SPEC_VERSION. Omitting it preserves the exact existing behavior
    for every authenticated call site.
    """
    spec = spec or _active_readiness_spec()
    version = spec.get("version", "readiness-v1")
    keyword_map = READINESS_KEYWORDS_BY_VERSION.get(version, {})
    objective = normalize_strategy_objective(strategy_objective, default="balanced")
    # How many keyword matches are required before a category counts as complete.
    # Default 1 preserves v1 behavior; v2 spec raises this to 2 to prevent
    # single incidental words (e.g. "process", "why") from ticking off categories.
    spec_min_keywords = int(spec.get("min_keywords") or 1)
    # Which category (if any) uses the numeric/financial/KPI quality-score path
    # instead of plain keyword matching. Configurable per spec so profiles other
    # than readiness-v2 can name their own evidence category.
    evidence_category_key = spec.get("evidence_category_key")

    user_msgs = [
        _message_text(m)
        for m in (chat_history or [])
        if isinstance(m, dict) and str(m.get("role", "")).lower() == "user"
    ]
    user_text = " ".join(user_msgs).lower()
    user_turns = len([m for m in user_msgs if m])
    evidence = _score_data_evidence(user_text) if evidence_category_key else None

    categories = []
    completed_weight = 0.0
    for cat in spec["categories"]:
        key = cat["key"]
        weight = float(cat.get("weight", 0))

        if evidence_category_key and key == evidence_category_key and evidence:
            # Evidence is complete when the user has shared a measurable baseline
            # (number + metric type + some timeframe context).  quality_score >= 2
            # is intentionally lower than the old threshold of 3 because the v2
            # keyword list is now more specific — fewer false positives.
            completed = evidence["quality_score"] >= 2
            percent = min(100, evidence["quality_score"] * 25)
        else:
            weak_keywords = WEAK_KEYWORDS_BY_VERSION.get(version, {}).get(key)
            hits = _category_is_addressed(
                key, chat_history, keyword_map,
                min_keyword_count=spec_min_keywords, weak_keywords=weak_keywords,
            )
            completed = bool(hits)
            percent = 100 if hits else 0

        if completed:
            completed_weight += weight
        category_payload = {
            "key": key,
            "label": cat["label"],
            "weight": weight,
            "step": cat.get("step"),
            "percent": int(percent),
            "completed": completed,
            "required": bool(cat.get("required")),
        }
        if evidence_category_key and key == evidence_category_key and evidence:
            category_payload["evidence_checks"] = evidence
        categories.append(category_payload)

    overall = int(round(min(1.0, completed_weight) * 100))
    readiness_payload = {
        "overall": {
            "percent": overall,
            "source": "heuristic_intake_v2" if version == "readiness-v2" else "heuristic_intake",
            "heur_overall": overall,
        },
        "categories": categories,
        "version": version,
        "objective_profile": objective,
    }
    items, checklist_summary = _build_readiness_items(spec, version, categories, user_text, user_turns, objective=objective)
    readiness_payload["items"] = items
    readiness_payload["checklist_summary"] = checklist_summary
    readiness_payload["checklist_mode"] = "adaptive"
    if evidence:
        readiness_payload["evidence_quality"] = evidence
        readiness_payload["data_contract"] = EVIDENCE_DATA_CONTRACT
    return readiness_payload


def _readiness_completed_keys(readiness_payload):
    return {
        str(item.get("key") or "").strip()
        for item in (readiness_payload.get("categories") if isinstance(readiness_payload, dict) else [])
        if isinstance(item, dict) and bool(item.get("completed")) and str(item.get("key") or "").strip()
    }


def _is_ready_to_analyze(readiness):
    """
    True when:
      1. Overall percent >= the spec's ready_threshold_percent (default 85 —
         sufficient coverage across scored categories), AND
      2. Every category marked required=True in the spec is complete.

    This prevents ready_to_analyze from triggering when a user skips a
    foundational category (e.g. goal_definition or evidence_baseline) but
    happens to hit the threshold via other categories.

    Resolves the spec from the readiness payload's own `version` first, so this
    is correct for whichever profile actually produced the payload — not just
    whatever profile happens to be globally active right now.
    """
    if not isinstance(readiness, dict):
        return False
    overall = readiness.get("overall") if isinstance(readiness.get("overall"), dict) else {}
    pct = int(overall.get("percent") or readiness.get("percent") or 0)
    spec = READINESS_SPECS.get(readiness.get("version")) or _active_readiness_spec()
    threshold = int(spec.get("ready_threshold_percent") or 85)
    if pct < threshold:
        return False
    # Check that all required categories are complete.
    required_keys = set(spec.get("required_keys") or set())
    if not required_keys:
        return True
    categories = readiness.get("categories") if isinstance(readiness.get("categories"), list) else []
    completed_required = {
        str(c.get("key") or "").strip()
        for c in categories
        if isinstance(c, dict) and bool(c.get("completed")) and bool(c.get("required"))
    }
    return required_keys.issubset(completed_required)


def _clamp_readiness_with_delta(previous_snapshot, current_snapshot):
    """
    Allow readiness increases only when newly completed categories are present.
    """
    if not isinstance(current_snapshot, dict):
        return current_snapshot
    if not isinstance(previous_snapshot, dict):
        return current_snapshot

    prev_percent = int(((previous_snapshot.get("overall") or {}).get("percent")) or previous_snapshot.get("percent") or 0)
    curr_percent = int(((current_snapshot.get("overall") or {}).get("percent")) or current_snapshot.get("percent") or 0)
    if curr_percent < prev_percent:
        clamped = dict(current_snapshot)
        overall = dict(clamped.get("overall") or {})
        overall["percent"] = prev_percent
        overall["heur_overall"] = prev_percent
        clamped["overall"] = overall
        clamped["percent"] = prev_percent
        clamped["delta_clamped"] = True
        return clamped
    if curr_percent == prev_percent:
        return current_snapshot

    prev_completed = _readiness_completed_keys(previous_snapshot)
    curr_completed = _readiness_completed_keys(current_snapshot)
    newly_completed = curr_completed - prev_completed
    if newly_completed:
        return current_snapshot

    clamped = dict(current_snapshot)
    overall = dict(clamped.get("overall") or {})
    overall["percent"] = prev_percent
    overall["heur_overall"] = prev_percent
    clamped["overall"] = overall
    clamped["percent"] = prev_percent
    clamped["delta_clamped"] = True
    return clamped


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
