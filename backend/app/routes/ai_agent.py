"""
app.routes.ai_agent_consolidated

Purpose: Unified AI Agent system combining conversation, scoring, and analysis management.

This consolidates the best parts of MarketIQ into the new AI Agent architecture:
- Conversation handling (chat with Claude for idea intake)
- Scoring/analysis generation (deterministic scoring with ScoringFramework)
- Thread & Analysis CRUD
- Scenario modeling (what-if adjustments)
- Framework management

Endpoints:
  # Frameworks
  GET    /api/ai-agent/frameworks              - List available scoring frameworks
  GET    /api/ai-agent/frameworks/<id>         - Get framework details
  
  # Conversation (idea intake)
  POST   /api/ai-agent/conversation/start      - Start conversation for new idea
  POST   /api/ai-agent/conversation/continue   - Continue conversation
  GET    /api/ai-agent/readiness/spec          - Get readiness categories spec
  GET    /api/ai-agent/readiness/audit         - Get conversation readiness %
  
  # Analysis generation
  POST   /api/ai-agent/analyze                 - Generate analysis from conversation
  
  # Threads
  POST   /api/ai-agent/projects/<id>/threads   - Create thread in project
  GET    /api/ai-agent/projects/<id>/threads   - List threads in project
  GET    /api/ai-agent/threads/<id>            - Get thread details
  PUT    /api/ai-agent/threads/<id>            - Update thread
  DELETE /api/ai-agent/threads/<id>            - Delete thread (soft)
  
  # Analyses
  POST   /api/ai-agent/threads/<id>/analyses   - Create analysis for thread
  GET    /api/ai-agent/threads/<id>/analyses   - List analyses for thread
  GET    /api/ai-agent/analyses/<id>           - Get analysis details
  PUT    /api/ai-agent/analyses/<id>           - Update analysis
  DELETE /api/ai-agent/analyses/<id>           - Delete analysis (soft)
  
  # Scenarios
  POST   /api/ai-agent/threads/<id>/scenarios  - Create scenario (what-if)
  GET    /api/ai-agent/threads/<id>/scenarios  - List scenarios for thread
  PUT    /api/ai-agent/scenarios/<id>          - Update scenario
  POST   /api/ai-agent/scenarios/<id>/apply    - Apply scenario → new analysis
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
from datetime import datetime
import uuid

import anthropic
from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import desc
from sqlalchemy.orm.attributes import flag_modified

from app import db
from app.models import Analysis, AgentThread, Project, ScoringFramework
from app.services.scenario_calculator import ScenarioCalculator

ai_agent_bp = Blueprint("ai_agent", __name__)


# ============================================================================
# CLAUDE CLIENT
# ============================================================================

def get_claude_client():
    api_key = (
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("CLAUDE_API_KEY")
        or current_app.config.get("ANTHROPIC_API_KEY")
        or current_app.config.get("CLAUDE_API_KEY")
    )
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY/CLAUDE_API_KEY not configured")
    return anthropic.Anthropic(api_key=api_key)


# ============================================================================
# CONVERSATION SYSTEM PROMPTS
# ============================================================================

CONVERSATION_SYSTEM_PROMPT = """
You are an AI Agent — a world-class senior market analyst who helps founders turn ideas into execution.

Your job: guide users through a natural conversation, gather minimum viable facts, then generate a rigorous scorecard.

Personality:
- Confident but supportive
- Pragmatic, not academic
- Efficient, not chatty
- One question at a time, natural tone

Stages:
1) INTAKE - gather facts for credible scoring
2) SCORECARD - explain score and gaps
3) SCENARIOS - compare strategic options
4) EXECUTION - convert to action plan

Scoring-critical facts to collect:
- Business description (what it does, why it wins)
- Target market (buyer role, company size, vertical, geography)
- Revenue model (pricing, revenue streams)
- Financial snapshot (revenue, margin, profit)
- Plan window (months) and budget
- Optional: competitors, team

Style rules:
- One question per turn (exactly ONE ? total)
- Acknowledge what user just said before asking next question
- Use plain business language, not jargon
- Offer soft examples to reduce effort
- Never ask for data already provided

When coverage is sufficient, say exactly:
"I have enough to build your scorecard. Click **Finish & Analyze** when you're ready."
"""


# ============================================================================
# READINESS TRACKING (Multi-signal heuristic)
# ============================================================================

CATEGORY_RULES = {
    "business_description": {
        "weight": 0.10,
        "need": 3,
        "signals": ["project_name_present", "problem_statement", "solution_description", "product_or_service", "value_prop"],
    },
    "target_market": {
        "weight": 0.15,
        "need": 3,
        "signals": ["target_customer", "demographics", "firmographics", "geographic_region", "industry_vertical", "market_size"],
    },
    "revenue_model": {
        "weight": 0.15,
        "need": 2,
        "signals": ["pricing", "revenue_model", "contract_terms", "sales_channels"],
    },
    "financial_metrics": {
        "weight": 0.25,
        "need": 3,
        "signals": ["baseline_revenue", "baseline_cogs", "baseline_opex", "ebitda_or_margin", "cac_ltv", "churn_retention"],
    },
    "timeline": {
        "weight": 0.10,
        "need": 1,
        "signals": ["timeline_window", "milestones"],
    },
    "budget": {
        "weight": 0.20,
        "need": 1,
        "signals": ["budget_amount", "capex_opex", "investment_amount"],
    },
    "competition": {
        "weight": 0.02,
        "need": 1,
        "signals": ["competitors", "differentiators"],
    },
    "team": {
        "weight": 0.03,
        "need": 1,
        "signals": ["team_roles", "headcount", "hiring_needs"],
    },
}


def extract_collected_data(messages: list[dict]) -> dict[str, bool]:
    """Extract boolean signals from conversation text."""
    text = " ".join((m.get("content") or "") for m in messages if m.get("role") in ("user", "assistant"))
    low = text.lower()

    def has_any(*phrases: str) -> bool:
        return any(p in low for p in phrases)

    money = re.compile(r"(?:\$[\s]?\d[\d,\.]*\s?(?:k|m|mm|b)?|\b\d[\d,\.]*\s?(?:usd|dollars)\b)", re.I)
    percent = re.compile(r"\b\d{1,3}\s?%\b")
    months = re.compile(r"\b\d{1,2}\s*(?:month|months|mo|quarter|quarters)\b", re.I)

    return {
        # Business
        "project_name_present": has_any("project name", "initiative", "called", "named"),
        "problem_statement": has_any("problem", "pain point", "challenge"),
        "solution_description": has_any("solution", "we offer", "we provide"),
        "product_or_service": has_any("product", "service", "platform"),
        "value_prop": has_any("value proposition", "differentiated", "unique value"),
        
        # Market
        "target_customer": has_any("target market", "target customer", "buyer", "persona"),
        "demographics": has_any("age", "income", "demographic"),
        "firmographics": has_any("company size", "employee", "enterprise", "smb"),
        "geographic_region": has_any("city", "state", "country", "region", "us", "europe"),
        "industry_vertical": has_any("industry", "vertical", "healthcare", "manufacturing", "saas"),
        "market_size": has_any("tam", "sam", "som", "market size") or bool(re.search(r"\b(billion|million)\b", low)),
        
        # Revenue
        "pricing": has_any("price", "pricing", "subscription", "license", "tier"),
        "revenue_model": has_any("revenue model", "business model", "revenue stream"),
        "contract_terms": has_any("contract", "term", "annual"),
        "sales_channels": has_any("channel", "direct sales", "partner"),
        
        # Financials
        "baseline_revenue": has_any("revenue", "arr", "mrr") or bool(money.search(low)),
        "baseline_cogs": has_any("cogs", "cost of goods"),
        "baseline_opex": has_any("opex", "operating expense", "sga"),
        "ebitda_or_margin": has_any("ebitda", "margin", "gross margin", "profit") or bool(percent.search(low)),
        "cac_ltv": has_any("cac", "customer acquisition cost", "ltv", "lifetime value"),
        "churn_retention": has_any("churn", "retention"),
        
        # Timeline & Budget
        "timeline_window": bool(months.search(low)) or has_any("timeline", "launch date"),
        "milestones": has_any("milestone", "phase"),
        "budget_amount": has_any("budget", "spend") or bool(money.search(low)),
        "capex_opex": has_any("capex", "capital expenditure"),
        "investment_amount": has_any("investment", "initial investment"),
        
        # Competition & Team
        "competitors": has_any("competitor", "competition", "alternative"),
        "differentiators": has_any("differentiator", "moat", "advantage"),
        "team_roles": has_any("team", "pm", "engineer", "sales"),
        "headcount": has_any("headcount", "fte", "people"),
        "hiring_needs": has_any("hire", "hiring", "recruit"),
    }


def build_readiness_snapshot(messages: list[dict]) -> dict:
    """Calculate readiness % from conversation."""
    print(f"[DEBUG build_readiness_snapshot] len(messages)={len(messages)}")

    collected = extract_collected_data(messages)

    # Log which signals were detected
    detected_signals = [k for k, v in collected.items() if v]
    print(f"[DEBUG build_readiness_snapshot] detected_signals ({len(detected_signals)}): {detected_signals}")

    categories = []
    overall = 0.0
    total_weight = 0.0

    for key, rule in CATEGORY_RULES.items():
        got = sum(1 for s in rule["signals"] if collected.get(s))
        need = max(1, int(rule.get("need", 1)))
        pct = min(100, int(100 * (got / need))) if got > 0 else 0
        weight = float(rule.get("weight", 0.0))

        categories.append({
            "key": key,
            "label": key.replace("_", " ").title(),
            "percent": pct,
            "completed": pct >= 100,
            "weight": weight,
        })
        overall += pct * weight
        total_weight += weight

        if got > 0:
            matched_signals = [s for s in rule["signals"] if collected.get(s)]
            print(f"[DEBUG build_readiness_snapshot] {key}: got={got}/{need} pct={pct}% signals={matched_signals}")

    overall_percent = int(round(overall / total_weight)) if total_weight > 0 else 0
    print(f"[DEBUG build_readiness_snapshot] overall_percent={overall_percent}%")

    return {
        "overall": {"percent": max(0, min(100, overall_percent)), "source": "heuristic"},
        "categories": categories,
        "version": "readiness_v1.0",
    }


# ============================================================================
# METRICS EXTRACTION (from conversation)
# ============================================================================

def _parse_numeric_value(val_str: str) -> float:
    """Parse numeric values with units (k, M, %, months)."""
    if not val_str:
        return 0.0
    val_str = str(val_str).strip()
    multiplier = 1.0

    # Percent
    if "%" in val_str:
        val_str = val_str.replace("%", "")
        multiplier = 0.01
    # Millions
    elif val_str.lower().endswith("m"):
        multiplier = 1_000_000
        val_str = val_str[:-1]
    # Thousands
    elif val_str.lower().endswith("k"):
        multiplier = 1_000
        val_str = val_str[:-1]

    # Strip non-numeric except decimal
    val_str = re.sub(r"[^\d.]", "", val_str)
    try:
        return float(val_str) * multiplier
    except Exception:
        return 0.0


def _extract_levers(transcript: str) -> dict:
    """
    Extract financial inputs from conversation transcript using Claude.
    Returns structured dict with normalized numeric values.
    """
    extraction_prompt = """
Extract financial and business information from the conversation. Be precise with numbers.

CRITICAL EXTRACTION RULES:
1. Budget = Total capital investment amount (e.g., "$2.1M capex" → 2100000, not 18)
2. Timeline = Duration in months (e.g., "over 18 months" → 18)
3. Industry Vertical = Full industry name (e.g., "Manufacturing", "SaaS", "B2B Services", not abbreviations)

Extract these fields:
- budget: Numeric total investment/budget amount in dollars (look for words like "capex", "investment", "budget", "$X million")
- plan_months: Duration in months (look for "X months", "timeline", "over X months")
- industry_vertical: Full industry name (Manufacturing, SaaS, Healthcare, etc.)
- revenue: Annual or target revenue
- gross_margin: Gross margin as decimal (e.g., 45% → 0.45)
- ebitda_margin: EBITDA margin as decimal (e.g., 12% → 0.12)
- cac: Customer acquisition cost per customer
- ltv: Lifetime value per customer
- churn_rate_mo: Monthly churn rate as decimal (e.g., 5% → 0.05)
- subscribers: Number of customers/subscribers
- price_month: Monthly price per customer

EXAMPLES:
Input: "We need $2.1M capex over 18 months to expand manufacturing"
Output: {"budget": 2100000, "plan_months": 18}

Input: "Our industry is B2B SaaS"
Output: {"industry_vertical": "B2B SaaS"}

Input: "45% gross margin, 12% EBITDA margin"
Output: {"gross_margin": 0.45, "ebitda_margin": 0.12}

Return ONLY valid JSON with extracted numeric values. Use null for missing fields.

CONVERSATION:
{transcript}

EXTRACTED DATA (JSON only):
"""

    try:
        import anthropic

        client = anthropic.Anthropic(
            api_key=current_app.config.get("ANTHROPIC_API_KEY")
        )

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[
                {
                    "role": "user",
                    "content": extraction_prompt.format(transcript=transcript),
                }
            ],
        )

        import json
        response_text = message.content[0].text.strip()

        if response_text.startswith("```json"):
            response_text = response_text.replace("```json", "").replace("```", "").strip()
        elif response_text.startswith("```"):
            response_text = response_text.replace("```", "").strip()

        extracted = json.loads(response_text)

        # Normalize derived fields used elsewhere in the pipeline.
        if extracted.get("plan_months") and not extracted.get("timeline_months"):
            extracted["timeline_months"] = extracted["plan_months"]
        if extracted.get("churn_rate_mo") and not extracted.get("churn_rate"):
            extracted["churn_rate"] = extracted["churn_rate_mo"]
        if extracted.get("gross_margin"):
            extracted["margin_percent"] = extracted["gross_margin"]
        elif extracted.get("ebitda_margin"):
            extracted["margin_percent"] = extracted["ebitda_margin"]

        current_app.logger.info(f"[_extract_levers] Extracted: {extracted}")

        return extracted

    except Exception as e:
        current_app.logger.exception(
            f"[_extract_levers] LLM extraction failed, falling back to empty dict: {e}"
        )
        return {}


def _stable_fingerprint(payload_like_dict: dict) -> str:
    """SHA-256 fingerprint of canonicalized inputs."""
    canonical = json.dumps(payload_like_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _extract_detailed_metrics(conversation_history: list[dict], levers: dict) -> dict:
    """Extract detailed metrics organized by category for dynamic scorecard."""
    text = " ".join((m.get("content") or "") for m in conversation_history)
    
    metrics = {
        "financial_health": [],
        "market_position": [],
        "operational_efficiency": [],
        "execution_readiness": [],
    }
    
    # Financial Health metrics
    if levers.get("revenue"):
        metrics["financial_health"].append({
            "label": "ARR" if "arr" in text.lower() else "Revenue",
            "value": f"${levers['revenue']:,.0f}",
            "format": "currency"
        })
    
    if levers.get("margin_percent"):
        metrics["financial_health"].append({
            "label": "Gross Margin",
            "value": f"{levers['margin_percent']*100:.0f}%",
            "format": "percentage"
        })
    
    if levers.get("cac"):
        metrics["financial_health"].append({
            "label": "CAC",
            "value": f"${levers['cac']:,.0f}",
            "format": "currency"
        })
    
    if levers.get("ltv"):
        metrics["financial_health"].append({
            "label": "LTV",
            "value": f"${levers['ltv']:,.0f}",
            "format": "currency"
        })
    
    # Market Position metrics
    target_match = re.search(r"target(?:ing)?\s+([^.!?]+?)(?:companies|businesses|customers)", text, re.IGNORECASE)
    if target_match:
        metrics["market_position"].append({
            "label": "Target Market",
            "value": target_match.group(1).strip(),
            "format": "text"
        })
    
    # Industry vertical: scan for known verticals rather than relying on a
    # fragile regex that truncates at abbreviation-periods (e.g. "St." → "St").
    _KNOWN_VERTICALS = [
        ("b2b saas", "B2B SaaS"), ("enterprise saas", "Enterprise SaaS"),
        ("b2c saas", "B2C SaaS"), ("saas", "SaaS"),
        ("healthtech", "HealthTech"), ("healthcare", "Healthcare"), ("biotech", "BioTech"),
        ("fintech", "FinTech"), ("financial services", "Financial Services"),
        ("insurtech", "InsurTech"), ("insurance", "Insurance"),
        ("e-commerce", "E-Commerce"), ("ecommerce", "E-Commerce"),
        ("manufacturing", "Manufacturing"), ("industrial", "Industrial"),
        ("cybersecurity", "Cybersecurity"), ("adtech", "AdTech"),
        ("edtech", "EdTech"), ("education", "Education"),
        ("proptech", "PropTech"), ("real estate", "Real Estate"),
        ("cleantech", "CleanTech"), ("energy", "Energy"),
        ("logistics", "Logistics"), ("supply chain", "Supply Chain"),
        ("telecom", "Telecom"), ("legal tech", "Legal Tech"),
        ("hr tech", "HR Tech"), ("staffing", "Staffing"),
        ("retail", "Retail"), ("media", "Media"),
    ]
    low = text.lower()
    for _needle, _label in _KNOWN_VERTICALS:
        if _needle in low:
            metrics["market_position"].append({
                "label": "Industry Vertical",
                "value": _label,
                "format": "text"
            })
            break
    
    # Operational Efficiency metrics
    if levers.get("growth_rate"):
        metrics["operational_efficiency"].append({
            "label": "Monthly Growth",
            "value": f"{levers['growth_rate']*100:.0f}%",
            "format": "percentage"
        })
    
    if levers.get("ltv") and levers.get("cac"):
        ratio = levers["ltv"] / levers["cac"]
        metrics["operational_efficiency"].append({
            "label": "LTV:CAC Ratio",
            "value": f"{ratio:.1f}",
            "format": "number"
        })
    
    if levers.get("churn_rate"):
        metrics["operational_efficiency"].append({
            "label": "Churn Rate",
            "value": f"{levers['churn_rate']*100:.0f}%",
            "format": "percentage"
        })
    
    # Execution Readiness metrics
    if levers.get("timeline_months"):
        metrics["execution_readiness"].append({
            "label": "Timeline",
            "value": f"{levers['timeline_months']} months",
            "format": "text"
        })
    
    if levers.get("budget"):
        metrics["execution_readiness"].append({
            "label": "Budget",
            "value": f"${levers['budget']:,.0f}",
            "format": "currency"
        })
    
    return metrics


def generate_score_from_conversation(conversation_history: list[dict], framework: ScoringFramework) -> dict:
    """Generate real scores from conversation using ScenarioCalculator."""
    
    # Extract levers from conversation
    transcript = " ".join((m.get("content") or "") for m in conversation_history)
    levers = _extract_levers(transcript)
    
    # Use ScenarioCalculator for real calculations
    calculator = ScenarioCalculator()
    result = calculator.calculate_baseline(levers)
    
    # Extract detailed metrics for display
    detailed_metrics = _extract_detailed_metrics(conversation_history, levers)
    
    return {
        "overall_score": result["overall_score"],
        "scores": result["scores"],
        "score_category": (
            "Excellent" if result["overall_score"] >= 85 
            else "Good" if result["overall_score"] >= 70 
            else "Fair" if result["overall_score"] >= 55 
            else "Poor"
        ),
        "financial_impact": {
            "projected_ebitda": result["financial_analysis"].get("projected_ebitda", 0),
            "ebitda_at_risk": int(result["financial_analysis"].get("projected_ebitda", 0) * 0.8),
            "potential_loss": int(result["financial_analysis"].get("projected_ebitda", 0) * 0.6),
            "roi_opportunity": int(result["financial_analysis"].get("total_benefit", 0)),
            "npv": result["financial_analysis"].get("npv", 0),
            "irr": result["financial_analysis"].get("irr", 0),
            "payback_period": result["financial_analysis"].get("payback_period", 0),
        },
        "metrics": detailed_metrics,
        "inputs_fingerprint": _stable_fingerprint(levers),
        "extracted_levers": levers,
    }


# ============================================================================
# SCORING FRAMEWORKS
# ============================================================================

@ai_agent_bp.route("/frameworks", methods=["GET"])
@jwt_required()
def list_frameworks():
    """List all available scoring frameworks."""
    try:
        frameworks = ScoringFramework.query.filter_by(deleted_at=None).order_by(ScoringFramework.name).all()
        return jsonify({
            "frameworks": [
                {
                    **f.to_dict(),
                    "criteria_count": len(f.criteria or []),
                }
                for f in frameworks
            ]
        }), 200
    except Exception as e:
        return jsonify({"error": "server_error", "detail": str(e)}), 500


@ai_agent_bp.route("/frameworks/<framework_id>", methods=["GET"])
@jwt_required()
def get_framework(framework_id):
    """Get framework details."""
    try:
        framework = ScoringFramework.query.filter_by(id=framework_id, deleted_at=None).first()
        if not framework:
            return jsonify({"error": "not_found"}), 404

        return jsonify({
            "framework": {
                **framework.to_dict(),
                "description": framework.description,
                "criteria": framework.criteria,
                "meta": framework.meta,
            }
        }), 200
    except Exception as e:
        return jsonify({"error": "server_error", "detail": str(e)}), 500


# ============================================================================
# CONVERSATION
# ============================================================================

@ai_agent_bp.route("/conversation/start", methods=["POST"])
@jwt_required()
def conversation_start():
    """Start a new conversation thread."""
    try:
        user_id = get_jwt_identity()
        data = request.get_json() or {}

        project_id = data.get("project_id")
        current_app.logger.info(f"[conversation_start] START project_id={project_id}")

        if not project_id:
            return jsonify({"error": "project_id required"}), 400

        project = Project.query.filter_by(id=project_id, deleted_at=None).first()

        # Auto-create project if it doesn't exist
        if not project:
            current_app.logger.info(f"[conversation_start] Auto-creating project id={project_id}")
            project = Project(
                id=project_id,
                sid=data.get("name", "Market IQ Project")[:128],
                status="PENDING",
                created_at=datetime.utcnow()
            )
            db.session.add(project)
            db.session.flush()

        user_message = (data.get("message") or "").strip()
        if not user_message:
            return jsonify({"error": "message required"}), 400

        # Create thread with explicit UUID id
        thread_id = uuid.uuid4().hex
        current_app.logger.info(f"[conversation_start] Creating thread id={thread_id}")

        thread = AgentThread(
            id=thread_id,
            project_id=project_id,
            user_id=user_id,
            name=user_message[:60],  # Use first part of message as name
            status="active",
            conversation_history=[],
            last_activity_at=datetime.utcnow(),
        )
        db.session.add(thread)
        db.session.flush()

        # Add user message
        messages = [{"role": "user", "content": user_message}]

        # Get Claude response
        client = get_claude_client()
        response = client.messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
            max_tokens=400,
            temperature=0.7,
            system=CONVERSATION_SYSTEM_PROMPT,
            messages=messages,
        )

        ai_message = "".join(blk.text for blk in response.content if getattr(blk, "type", None) == "text").strip()
        messages.append({"role": "assistant", "content": ai_message})

        # Update thread
        thread.conversation_history = messages
        flag_modified(thread, "conversation_history")
        db.session.commit()

        current_app.logger.info(f"[conversation_start] thread.id={thread_id} committed with len(messages)={len(messages)}")

        readiness = build_readiness_snapshot(messages)
        current_app.logger.info(f"[conversation_start] thread.id={thread_id} readiness.overall={readiness['overall']['percent']}%")

        return jsonify({
            "thread_id": thread_id,
            "message": ai_message,
            "readiness": readiness,
            "status": "gathering_info",
        }), 201

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("conversation_start failed")
        return jsonify({"error": "server_error", "detail": str(e)}), 500


@ai_agent_bp.route("/conversation/continue", methods=["POST"])
@jwt_required()
def conversation_continue():
    """Continue existing conversation."""
    try:
        data = request.get_json() or {}
        thread_id = data.get("thread_id")
        user_message = (data.get("message") or "").strip()

        current_app.logger.info(f"[conversation_continue] START thread_id={thread_id}")

        if not thread_id or not user_message:
            return jsonify({"error": "thread_id and message required"}), 400

        thread = AgentThread.query.filter_by(id=thread_id, deleted_at=None).first()
        if not thread:
            current_app.logger.warning(f"[conversation_continue] thread_not_found for id={thread_id}")
            return jsonify({"error": "thread_not_found"}), 404

        # CRITICAL: Create a NEW list to avoid SQLAlchemy mutation detection issues
        # If we mutate the existing list in-place, SQLAlchemy won't detect the change
        old_messages = thread.conversation_history or []
        current_app.logger.info(f"[conversation_continue] thread.id={thread.id} BEFORE: len(conversation_history)={len(old_messages)}")

        # Create new list with old messages + new user message
        messages = list(old_messages)  # Copy to new list
        messages.append({"role": "user", "content": user_message})

        # Get Claude response
        client = get_claude_client()
        response = client.messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
            max_tokens=400,
            temperature=0.7,
            system=CONVERSATION_SYSTEM_PROMPT,
            messages=messages,
        )

        ai_message = "".join(blk.text for blk in response.content if getattr(blk, "type", None) == "text").strip()
        messages.append({"role": "assistant", "content": ai_message})

        current_app.logger.info(f"[conversation_continue] thread.id={thread.id} AFTER: len(messages)={len(messages)}")

        # Update thread - assign the NEW list
        thread.conversation_history = messages
        thread.last_activity_at = datetime.utcnow()

        # CRITICAL: Explicitly mark the JSON column as modified
        # This ensures SQLAlchemy knows to persist the change
        flag_modified(thread, "conversation_history")

        db.session.commit()

        # Verify the commit worked by re-reading
        db.session.refresh(thread)
        current_app.logger.info(f"[conversation_continue] thread.id={thread.id} POST-COMMIT: len(conversation_history)={len(thread.conversation_history or [])}")

        readiness = build_readiness_snapshot(messages)
        current_app.logger.info(f"[conversation_continue] thread.id={thread.id} readiness.overall={readiness['overall']['percent']}%")

        return jsonify({
            "thread_id": thread.id,
            "message": ai_message,
            "readiness": readiness,
            "status": "gathering_info",
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("conversation_continue failed")
        return jsonify({"error": "server_error", "detail": str(e)}), 500


# ============================================================================
# READINESS API
# ============================================================================

@ai_agent_bp.route("/readiness/spec", methods=["GET"])
def readiness_spec():
    """Get readiness category specification."""
    categories = [
        {
            "key": key,
            "label": key.replace("_", " ").title(),
            "weight": float(rule.get("weight", 0.0)),
        }
        for key, rule in CATEGORY_RULES.items()
    ]
    return jsonify({"version": "readiness_v1.0", "categories": categories}), 200


@ai_agent_bp.route("/readiness/audit", methods=["GET"])
def readiness_audit():
    """Get readiness for a specific thread."""
    thread_id = request.args.get("thread_id")
    current_app.logger.info(f"[readiness_audit] START thread_id={thread_id}")

    if not thread_id:
        return jsonify({"error": "thread_id required"}), 400

    thread = AgentThread.query.filter_by(id=thread_id, deleted_at=None).first()
    if not thread:
        current_app.logger.warning(f"[readiness_audit] thread_not_found for id={thread_id}")
        return jsonify({"error": "thread_not_found"}), 404

    messages = thread.conversation_history or []
    current_app.logger.info(f"[readiness_audit] thread.id={thread.id} len(conversation_history)={len(messages)}")

    # Log message roles for debugging
    roles = [m.get("role", "unknown") for m in messages]
    current_app.logger.info(f"[readiness_audit] thread.id={thread.id} message_roles={roles}")

    readiness = build_readiness_snapshot(messages)
    current_app.logger.info(f"[readiness_audit] thread.id={thread.id} readiness.overall={readiness['overall']['percent']}%")

    return jsonify(readiness), 200


# ============================================================================
# ANALYSIS GENERATION
# ============================================================================

@ai_agent_bp.route("/analyze", methods=["POST"])
@jwt_required()
def analyze():
    """Generate analysis from conversation thread."""
    try:
        user_id = get_jwt_identity()
        data = request.get_json() or {}

        thread_id = data.get("thread_id")
        framework_id = data.get("framework_id")

        current_app.logger.info(f"[analyze] START thread_id={thread_id}")

        if not thread_id:
            return jsonify({"error": "thread_id required"}), 400

        thread = AgentThread.query.filter_by(id=thread_id, deleted_at=None).first()
        if not thread:
            current_app.logger.warning(f"[analyze] thread_not_found for id={thread_id}")
            return jsonify({"error": "thread_not_found"}), 404

        messages = thread.conversation_history or []
        current_app.logger.info(f"[analyze] thread.id={thread.id} len(conversation_history)={len(messages)}")

        # Get framework (default to Market IQ Assessment if not specified)
        if not framework_id:
            framework = ScoringFramework.query.filter_by(
                name="Market IQ Assessment",
                is_system=True,
                deleted_at=None
            ).first()
        else:
            framework = ScoringFramework.query.filter_by(id=framework_id, deleted_at=None).first()

        if not framework:
            return jsonify({"error": "framework_not_found"}), 404

        # Generate scores
        score_data = generate_score_from_conversation(thread.conversation_history or [], framework)

        # Create Analysis
        _meta = {
            "fingerprint": score_data["inputs_fingerprint"],
            "financial_impact": score_data["financial_impact"],
            "metrics": score_data["metrics"],
            "extracted_levers": score_data["extracted_levers"],
        }
        print(f"[DEBUG analyze] meta being saved: extracted_levers={_meta['extracted_levers']}")

        analysis = Analysis(
            thread_id=thread_id,
            scoring_framework_id=framework.id,
            user_id=user_id,
            name=data.get("name", "Baseline Analysis"),
            description=f"Analysis using {framework.name}",
            scores=score_data["scores"],
            overall_score=score_data["overall_score"],
            status="completed",
            input_context={"conversation_length": len(thread.conversation_history or [])},
            meta=_meta,
            analyzed_at=datetime.utcnow(),
        )

        db.session.add(analysis)
        thread.last_activity_at = datetime.utcnow()
        db.session.commit()
        print(f"[DEBUG analyze] committed analysis.id={analysis.id}, meta.extracted_levers={analysis.meta.get('extracted_levers') if analysis.meta else 'META IS NONE'}")

        # Log scores for debugging
        print(f"[DEBUG analyze] score_data['scores']={score_data['scores']}")
        print(f"[DEBUG analyze] analysis.scores={analysis.scores}")

        return jsonify({
            "analysis": {
                **analysis.to_dict(),
                "framework_name": framework.name,
                "score_category": score_data["score_category"],
                "scores": score_data["scores"],  # Component scores (financial_health, etc.)
                "financial_impact": score_data["financial_impact"],
                "metrics": score_data["metrics"],
                "inputs": {**(score_data.get("extracted_levers") or {})},
                "compat": {**(score_data.get("extracted_levers") or {})},
            }
        }), 201

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("analyze failed")
        return jsonify({"error": "server_error", "detail": str(e)}), 500


# ============================================================================
# THREADS
# ============================================================================

@ai_agent_bp.route("/projects/<project_id>/threads", methods=["POST"])
@jwt_required()
def create_thread(project_id):
    """Create a thread manually (without conversation)."""
    try:
        user_id = get_jwt_identity()
        data = request.get_json() or {}

        project = Project.query.filter_by(id=project_id, deleted_at=None).first()
        if not project:
            return jsonify({"error": "project_not_found"}), 404

        thread = AgentThread(
            project_id=project_id,
            user_id=user_id,
            name=data.get("name", "New Thread"),
            description=data.get("description"),
            status="active",
            context=data.get("context"),
            conversation_history=data.get("conversation_history"),
            last_activity_at=datetime.utcnow(),
        )

        db.session.add(thread)
        db.session.commit()

        return jsonify({"thread": thread.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "server_error", "detail": str(e)}), 500


@ai_agent_bp.route("/projects/<project_id>/threads", methods=["GET"])
@jwt_required()
def list_threads(project_id):
    """List all threads in a project."""
    try:
        project = Project.query.filter_by(id=project_id, deleted_at=None).first()
        if not project:
            return jsonify({"error": "project_not_found"}), 404

        threads = AgentThread.query.filter_by(
            project_id=project_id, deleted_at=None
        ).order_by(AgentThread.last_activity_at.desc()).all()

        return jsonify({"project_id": project_id, "threads": [t.to_dict() for t in threads]}), 200
    except Exception as e:
        return jsonify({"error": "server_error", "detail": str(e)}), 500


@ai_agent_bp.route("/threads/<thread_id>", methods=["GET"])
@jwt_required()
def get_thread(thread_id):
    """Get thread with all analyses."""
    try:
        thread = AgentThread.query.filter_by(id=thread_id, deleted_at=None).first()
        if not thread:
            return jsonify({"error": "not_found"}), 404

        analyses = Analysis.query.filter_by(
            thread_id=thread_id, deleted_at=None
        ).order_by(Analysis.analyzed_at.desc()).all()

        _ctx = thread.context or {}
        return jsonify({
            "thread": {
                **thread.to_dict(),
                "description": thread.description,
                "context": thread.context,
                "conversation_history": thread.conversation_history,
                "adopted_analysis_id": _ctx.get("adopted_analysis_id"),
                "scorecard_snapshots": _ctx.get("scorecard_snapshots", []),
            },
            "analyses": [{
                **a.to_dict(),
                "scores": a.scores,
                "financial_impact": (a.meta or {}).get("financial_impact"),
                "metrics": (a.meta or {}).get("metrics"),
            } for a in analyses],
        }), 200
    except Exception as e:
        return jsonify({"error": "server_error", "detail": str(e)}), 500

@ai_agent_bp.route("/threads", methods=["GET"])
@jwt_required()
def list_all_user_threads():
    """List all threads for the current user across all projects."""
    try:
        user_id = get_jwt_identity()
        
        # Get status filter (optional)
        status_filter = request.args.get('status', '').strip().lower()
        if status_filter in ('active', 'open', 'inprogress'):
            status_filter = 'in_progress'
        
        # Query all threads for user's projects
        threads_query = AgentThread.query.filter_by(deleted_at=None)
        
        # Join with Project to filter by user (if Project has user_id field)
        # For now, we'll get all threads and sort by activity
        threads = threads_query.order_by(AgentThread.last_activity_at.desc()).all()
        
        # Build response with readiness
        items = []
        for thread in threads:
            # Calculate readiness from conversation history
            messages = thread.conversation_history or []
            readiness = build_readiness_snapshot(messages)
            
            # Get latest analysis if exists
            latest_analysis = Analysis.query.filter_by(
                thread_id=thread.id, deleted_at=None
            ).order_by(Analysis.analyzed_at.desc()).first()
            
            items.append({
                'session_id': thread.id,
                'name': thread.name or 'Untitled',
                'status': 'completed' if latest_analysis else 'in_progress',
                'score': latest_analysis.overall_score if latest_analysis else None,
                'created': thread.created_at.isoformat() if thread.created_at else None,
                'timestamp': thread.last_activity_at.isoformat() if thread.last_activity_at else None,
                'chat_history': messages,
                'readiness': readiness,
                'collected_data': {},  # TODO: extract from conversation if needed
            })
        
        # Apply status filter if provided
        if status_filter:
            items = [item for item in items if item['status'] == status_filter]
        
        return jsonify({'success': True, 'sessions': items}), 200
        
    except Exception as e:
        return jsonify({"error": "server_error", "detail": str(e)}), 500

@ai_agent_bp.route("/threads/<thread_id>", methods=["PUT"])
@jwt_required()
def update_thread(thread_id):
    """Update thread metadata."""
    try:
        data = request.get_json() or {}
        thread = AgentThread.query.filter_by(id=thread_id, deleted_at=None).first()
        if not thread:
            return jsonify({"error": "not_found"}), 404

        if "name" in data:
            thread.name = data["name"]
        if "description" in data:
            thread.description = data["description"]
        if "status" in data:
            thread.status = data["status"]
        if "context" in data:
            thread.context = data["context"]
        if "conversation_history" in data:
            thread.conversation_history = data["conversation_history"]

        thread.last_activity_at = datetime.utcnow()
        thread.updated_at = datetime.utcnow()
        db.session.commit()

        return jsonify({"thread": thread.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "server_error", "detail": str(e)}), 500


@ai_agent_bp.route("/threads/<thread_id>", methods=["DELETE"])
@jwt_required()
def delete_thread(thread_id):
    """Soft delete thread."""
    try:
        thread = AgentThread.query.filter_by(id=thread_id, deleted_at=None).first()
        if not thread:
            return jsonify({"error": "not_found"}), 404

        thread.deleted_at = datetime.utcnow()
        db.session.commit()

        return jsonify({"success": True}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "server_error", "detail": str(e)}), 500


# ============================================================================
# ANALYSES
# ============================================================================

@ai_agent_bp.route("/threads/<thread_id>/analyses", methods=["POST"])
@jwt_required()
def create_analysis(thread_id):
    """Create analysis manually (usually done via /analyze endpoint)."""
    try:
        user_id = get_jwt_identity()
        data = request.get_json() or {}

        thread = AgentThread.query.filter_by(id=thread_id, deleted_at=None).first()
        if not thread:
            return jsonify({"error": "thread_not_found"}), 404

        framework_id = data.get("scoring_framework_id")
        if not framework_id:
            return jsonify({"error": "scoring_framework_id required"}), 400

        framework = ScoringFramework.query.filter_by(id=framework_id, deleted_at=None).first()
        if not framework:
            return jsonify({"error": "framework_not_found"}), 404

        analysis = Analysis(
            thread_id=thread_id,
            scoring_framework_id=framework_id,
            user_id=user_id,
            name=data.get("name", "Analysis"),
            description=data.get("description"),
            scores=data.get("scores", {}),
            overall_score=data.get("overall_score", 0.0),
            status=data.get("status", "draft"),
            rank=data.get("rank"),
            strengths=data.get("strengths"),
            weaknesses=data.get("weaknesses"),
            opportunities=data.get("opportunities"),
            threats=data.get("threats"),
            recommendations=data.get("recommendations"),
            input_context=data.get("input_context"),
            meta=data.get("meta"),
            analyzed_at=datetime.utcnow(),
        )

        db.session.add(analysis)
        thread.last_activity_at = datetime.utcnow()
        db.session.commit()

        return jsonify({"analysis": analysis.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "server_error", "detail": str(e)}), 500


@ai_agent_bp.route("/threads/<thread_id>/analyses", methods=["GET"])
@jwt_required()
def list_analyses(thread_id):
    """List all analyses for a thread."""
    try:
        thread = AgentThread.query.filter_by(id=thread_id, deleted_at=None).first()
        if not thread:
            return jsonify({"error": "thread_not_found"}), 404

        analyses = Analysis.query.filter_by(
            thread_id=thread_id, deleted_at=None
        ).order_by(Analysis.analyzed_at.desc()).all()

        return jsonify({
            "thread_id": thread_id,
            "analyses": [
                {
                    **a.to_dict(),
                    "framework_name": a.scoring_framework.name if a.scoring_framework else None,
                }
                for a in analyses
            ],
        }), 200
    except Exception as e:
        return jsonify({"error": "server_error", "detail": str(e)}), 500


@ai_agent_bp.route("/analyses/<analysis_id>", methods=["GET"])
@jwt_required()
def get_analysis(analysis_id):
    """Get full analysis details."""
    try:
        analysis = Analysis.query.filter_by(id=analysis_id, deleted_at=None).first()
        if not analysis:
            return jsonify({"error": "not_found"}), 404

        return jsonify({
            "analysis": {
                **analysis.to_dict(),
                "description": analysis.description,
                "scores": analysis.scores,
                "strengths": analysis.strengths,
                "weaknesses": analysis.weaknesses,
                "opportunities": analysis.opportunities,
                "threats": analysis.threats,
                "recommendations": analysis.recommendations,
                "input_context": analysis.input_context,
                "meta": analysis.meta,
                "framework": analysis.scoring_framework.to_dict() if analysis.scoring_framework else None,
            }
        }), 200
    except Exception as e:
        return jsonify({"error": "server_error", "detail": str(e)}), 500


@ai_agent_bp.route("/analyses/<analysis_id>", methods=["PUT"])
@jwt_required()
def update_analysis(analysis_id):
    """Update analysis."""
    try:
        data = request.get_json() or {}
        analysis = Analysis.query.filter_by(id=analysis_id, deleted_at=None).first()
        if not analysis:
            return jsonify({"error": "not_found"}), 404

        if "name" in data:
            analysis.name = data["name"]
        if "description" in data:
            analysis.description = data["description"]
        if "scores" in data:
            analysis.scores = data["scores"]
        if "overall_score" in data:
            analysis.overall_score = data["overall_score"]
        if "status" in data:
            analysis.status = data["status"]
        if "rank" in data:
            analysis.rank = data["rank"]
        if "strengths" in data:
            analysis.strengths = data["strengths"]
        if "weaknesses" in data:
            analysis.weaknesses = data["weaknesses"]
        if "opportunities" in data:
            analysis.opportunities = data["opportunities"]
        if "threats" in data:
            analysis.threats = data["threats"]
        if "recommendations" in data:
            analysis.recommendations = data["recommendations"]
        if "meta" in data:
            analysis.meta = data["meta"]

        analysis.updated_at = datetime.utcnow()
        db.session.commit()

        return jsonify({"analysis": analysis.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "server_error", "detail": str(e)}), 500


@ai_agent_bp.route("/analyses/<analysis_id>", methods=["DELETE"])
@jwt_required()
def delete_analysis(analysis_id):
    """Soft delete analysis."""
    try:
        analysis = Analysis.query.filter_by(id=analysis_id, deleted_at=None).first()
        if not analysis:
            return jsonify({"error": "not_found"}), 404

        analysis.deleted_at = datetime.utcnow()
        db.session.commit()

        return jsonify({"success": True}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "server_error", "detail": str(e)}), 500
