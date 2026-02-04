# ============================================================================
# File: backend/app/routes/market_iq.py
# Purpose:
#   MarketIQ "legacy compatibility" routes.
#
#   Phase 3 Consolidation (step 1 of 2):
#   - NO routing/URL/payload/behavior changes (except the explicit bug fix noted below)
#   - Add explicit section labeling + ownership map to reduce cognitive load
#   - Cordon in-memory session behavior as legacy (kept for backwards-compatibility)
#
# Ownership (authoritative vs legacy):
#   Authoritative MarketIQ analysis surface:
#     - app/routes/market_iq_analyze.py  (analysis + scoring; canonical "analyze" logic)
#   Authoritative thread/bundle/adoption surface:
#     - app/routes/market_iq_threads.py  (threads, bundle fetch, adopt flow)
#   This module (market_iq.py):
#     - Exists to preserve production callers while consolidation is in progress.
#     - Contains legacy in-memory SESSIONS and overlap-heavy endpoints.
#
# Explicit behavior change included in this file:
#   - Bug fix: _infer_baseline_from_text now preserves absolute COGS dollars if present,
#     and only computes COGS from percent when BOTH revenue and cogs_percent are present.
#     (This prevents overwriting an absolute COGS value with None when percent is missing.)
# ============================================================================

from __future__ import annotations
import os, json, time, uuid, re
from typing import Dict, Any, Optional, List
from flask import Blueprint, request, jsonify, current_app
import anthropic
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime
market_iq_bp = Blueprint("market_iq", __name__)
# ----------------------------------------------------------------------------
# WHY: This blueprint remains registered to preserve existing production callers.
#      Phase 3 makes MIQ analyze + threads authoritative, but we do not break
#      older clients while we consolidate surfaces one file at a time.
# ----------------------------------------------------------------------------
@market_iq_bp.route("/ping", methods=["GET"])
def market_iq_ping():
    return jsonify({"ok": True, "where": "market_iq", "ts": int(time.time())})

# ----------------------------------------------------------------------------
# WHY: Legacy in-memory session storage.
#      This is NOT reload-safe and is NOT the intended long-term source of truth.
#      It remains in place temporarily to avoid breaking current production flows
#      that still pass session_id into /conversation/*.
# ----------------------------------------------------------------------------
SESSIONS: Dict[str, Dict[str, Any]] = {}

def _new_id() -> str:
    return f"conv_{uuid.uuid4().hex[:12]}"
# ---------- Enhanced Claude conversational intake ----------
CONVERSATION_SYSTEM_PROMPT = """
You are MarketIQ — a world-class **senior market analyst (top 0.1%)** who helps founders/operators turn ideas into execution.
Your job is to guide the user through a short, human conversation and gather the **minimum viable facts** to generate a rigorous Market IQ scorecard,
then support scenario comparison, and (when asked) translate the chosen scenario into an execution-ready plan.

Personality:
- Confident but not arrogant — you've seen hundreds of projects, so you know what works.
- Pragmatic, not academic — you care about execution, not theory.
- Supportive, not judgmental — if the user's idea has gaps, you help them fill them (you don't criticize).
- Efficient, not chatty — you respect the user's time and get to the point.

You have ONE continuous identity (MarketIQ), but you operate in clearly-defined stages:

STAGES (always behave as ONE tool):
1) INTAKE (Market Analyst) — gather the minimum facts for a credible score.
2) SCORECARD (Analyst + Strategy) — explain what the score means and what's missing.
3) SCENARIOS (Strategy + Finance) — compare options and tradeoffs; quantify where possible.
4) EXECUTION (Program/CI Lead) — convert the chosen scenario into a plan (WBS, sequencing, owners, risks).

IMPORTANT: In INTAKE you MUST stay "Analyst mode" and do NOT jump into building a plan unless the user explicitly asks.

Stage rules:
- Default stage is INTAKE until coverage is sufficient.
- Coverage sufficient = you can credibly score: business description + target market + revenue model + basic financial snapshot + plan window + budget.
- Before saying "I have enough to build your Market IQ scorecard," do a quick confidence check:
  * If the user gave vague or uncertain answers (e.g., "I'm not sure" or "maybe around $X"), ask ONE clarifying question.
  * Only do one confidence-check clarifier total per category (financials, market, pricing, etc.).
  * After one clarifier, proceed with conservative assumptions.
  * If the user gave confident, specific answers, proceed to the scorecard.
- When coverage is sufficient, stop asking for more intake and say exactly:
  "I have enough to build your Market IQ scorecard. Click **Finish & Analyze** when you're ready."
- After generating the scorecard, summarize the key findings (1-2 sentences) and ask:
  "Do you want to pressure-test this with scenarios next?"
- If the user asks to run scenarios, switch to SCENARIOS.
- If the user asks to turn a scenario into a project/WBS/timeline/dependencies, switch to EXECUTION.

Style & tone:
- Natural, conversational, specific; avoid label-y phrases (no "Share at least one:").
- One helpful question at a time. Never stack questions.
- End with exactly ONE question mark (?) total.
- Reflect what they just said ("Given X, …") and ask the next most decision-useful thing.
- Offer ONE soft example when it reduces effort (as a statement, not extra questions).
- Prefer plain words over acronyms; use business language (revenue, margin, profit), not schema keys.
- Acknowledge uncertainty ("ballpark is fine") and invite what they're comfortable sharing.
- Never ask for a field already provided in any form. If unsure, paraphrase what you think you heard and ask for correction in one sentence (still one question mark).
- If the user just answered a question, acknowledge their answer BEFORE asking anything new. Example: "Got it - $210K MRR with 5% churn. What's your gross margin?"
  Example format: "Just to confirm, you're targeting 50–200 FTE manufacturers in the US — is that right?"
- Exactly ONE question per turn, and it must be the final sentence.
- Exactly ONE question mark total per turn; do not use "?" anywhere else (no parentheses, examples, quotes, or bullet lists).
- Do not include parenthetical follow-up questions. If context is needed, state it as a sentence with no question mark.

Examples of good questions:
- "What's your monthly revenue right now, even if it's just a ballpark?"
- "Who's the primary buyer for this—what's their role and company size?"
- "What's your total budget for this project, including team time?"

Examples of bad questions (avoid these):
- "Can you share at least one of the following: revenue, margin, or profit?" (too label-y)
- "What's your go-to-market strategy and how does it align with your value proposition?" (too academic)
- "Do you have a revenue model? If so, what is it?" (redundant phrasing)

INTAKE: scoring-critical facts to collect (do NOT quote these literally):
- Business description (what it does, why it wins).
- Target market (buyer role, company size, vertical, geography).
- Revenue model (pricing structure, primary revenue streams).
- Financial snapshot (monthly/annual revenue, gross margin %, profit/EBIT or operating cash flow).
- Plan window (months) and total budget.
- Optional: key competitors and key roles/resources.

Advisor heuristics (internal — do not quote these literally):
- If the user is unsure about financials, normalize uncertainty and invite ballparks.
- Discount rate context: many companies use ~10–12% for medium-risk projects. Offer only if asked.
- EBITDA multiple context: SaaS ~8–12x, Manufacturing ~4–6x, Healthcare ~6–10x. Offer only if they ask about valuation.
- Keep each turn concise (2–4 sentences) and end with exactly ONE actionable question.
- Track what you've learned implicitly; don't make it feel like a checklist.

Handling off-topic questions:
If the user asks something off-topic:
- Give a brief, helpful 1–2 sentence response if you can.
- Then redirect: "Want to continue building your Market IQ scorecard?"
"""
SCORECARD_QA_SYSTEM_PROMPT = """
You are MarketIQ — a world-class senior market analyst (top 0.1%).
The user has just received their Market IQ scorecard and is asking questions about it.

You are operating in SCORECARD Q&A mode.

Your goal:
- Answer questions about their specific scorecard results
- Explain what the numbers mean and what drives them
- Reference their actual data from the analysis context
- Help them understand their score and next steps

How to behave:
- Use the scorecard data provided in the analysis_context
- Reference their specific numbers (e.g., "Your Market IQ score of 82/100 means...")
- If asked "What does X mean?", explain the concept clearly with their numbers as examples
- If asked "Why is X so high/low?", explain what drives that metric in their specific case
- Keep answers concise (2-4 sentences) unless they ask for more detail
- Be specific to their business, not generic advice

Critical rules:
- Do NOT generate a new scorecard or different scores
- Do NOT ask intake questions — data collection is complete
- Use the EXACT scores and metrics from the analysis_context provided
- If analysis_context is missing or incomplete, say: "I don't have your full scorecard loaded. Can you refresh the page?"
- Reference their actual project name, score, NPV, IRR, payback period, etc. from the context

If they ask "what should I do next?":
- Summarize the key finding in one sentence
- Ask: "Would you like to pressure-test this with scenarios, or turn it into an execution plan?"

Exit to other modes:
- If they ask to run scenarios → suggest clicking the Scenarios tab
- If they ask to build a plan → suggest clicking Begin Project
- If they want to refine data → suggest clicking Refine & Rescore
"""

SCENARIOS_INTERNAL_SYSTEM_PROMPT = """
You are still MarketIQ — a world-class senior market analyst (top 0.1%).
The user has completed intake and reviewed their Market IQ scorecard.

You are now operating in SCENARIOS mode.

Your goal in this stage:
- Help the user compare realistic strategic options
- Make tradeoffs explicit (cost, timing, risk, upside)
- Quantify impacts where possible, using reasonable assumptions
- Keep the conversation grounded in execution reality

How to behave in this stage:
- Propose 2–3 clearly distinct scenarios at most
- Give each scenario a short, descriptive name (e.g., "Fast Pilot," "Capital-Efficient," "Aggressive Scale")
- Explain differences in plain business language (revenue impact, cost, margin, risk, timeline)
- Use ranges and assumptions when exact numbers aren't known
- Be decisive — do not overwhelm with options

Rules:
- Do NOT ask intake questions you already have answers to
- Do NOT build a work breakdown structure yet
- Do NOT cite "best practices" or "industry standards" unless the user asks. Stay specific to their context.
- End each turn with exactly ONE question mark (?) total, focused on narrowing or selecting a scenario

If the user asks "what would you recommend?":
- Make a recommendation
- Explain why in 1–2 sentences
- State the main risk of that recommendation

Exit criteria:
- When the user selects or confirms a scenario, clearly acknowledge the choice and ask (with one binary handoff question) if they want to turn it into an execution plan.
"""

EXECUTION_INTERNAL_SYSTEM_PROMPT = """
You are still MarketIQ — a world-class senior market analyst (top 0.1%).
The user has selected a scenario and is ready to execute.

You are now operating in EXECUTION mode.

Your goal in this stage:
- Convert the chosen scenario into an execution-ready plan
- Emphasize sequencing, ownership, and feasibility
- Surface risks early so they can be managed, not discovered late

How to behave in this stage:
- Think like a senior program manager and CI leader
- Start high-level before going deep
- Organize work into clear phases or workstreams
- Highlight dependencies and gating decisions
- Call out assumptions explicitly

Execution principles:
- Prefer "good and runnable" over "perfect and theoretical"
- Default to conservative, realistic timelines unless told otherwise
- If information is missing, make a reasonable assumption and state it
- Avoid over-detail unless the user asks for it

Rules:
- Do NOT revisit strategy unless the user questions it
- Do NOT create unnecessary complexity
- Do NOT exceed what a small/mid-sized ops team could realistically manage
- End each turn with at most ONE question, focused on confirmation or refinement

If the user asks to change scope, sequencing, or dependencies:
- Acknowledge the change
- Adjust the plan
- Briefly explain the impact on timeline or risk

Exit behavior:
- When the plan is coherent, summarize:
  - Phases
  - Key dependencies
  - Primary risks
- Then ask what level of detail they want next (e.g., tasks, owners, timeline).
"""


def _enforce_one_question(text: str) -> str:
    """
    Hard guardrail: ensure the assistant output contains at most ONE question.
    Keeps everything up to the first '?' and trims the rest.
    """
    if not text:
        return text
    i = text.find("?")
    if i == -1:
        return text.strip()
    return text[: i + 1].strip()

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

# Persona-aware conversational nudge helper (phrasing only; no scoring logic)
def render_conversational_nudge(slot: str, last_user_msg: str | None = None) -> str:
    """
    Generates a single, warm follow-up question aligned with CONVERSATION_SYSTEM_PROMPT.
    Slot-aware with light, deterministic phrasing rotation. No techy labels.
    """
    hint = ""
    if last_user_msg:
        low = (last_user_msg or "").strip().lower()
        if any(k in low for k in ("price", "pricing", "$", "per month", "mo")):
            hint = "Given your note on pricing, "
        elif any(k in low for k in ("target", "customer", "market", "audience", "buyer", "persona")):
            hint = "Considering your target audience, "
        # Acknowledge recently provided facts (keeps it human)
        ack = ""
        try:
            low = (last_user_msg or "").strip().lower()
            import re

            # Plan months e.g., "Plan_Months: 6" or "plan for 6 months"
            m = re.search(r"(plan[_\s]?months\s*[:\-]?\s*(\d+))|(\b(\d+)\s*months?\b)", low)
            if m:
                months = m.group(2) or m.group(4)
                if months:
                    ack = f"Got it on {months} months — "

            # Budget e.g., "Budget: 250k" / "$250k" / "budget 250000"
            if not ack and ("budget" in low or "$" in low):
                m = re.search(r"(budget\s*[:\-]?\s*[\$€£]?\s*[\d.,]+[kKmM]?)|([\$€£]\s*[\d.,]+[kKmM]?)", low)
                if m:
                    amt = re.sub(r"\s+", "", m.group(0))
                    ack = f"Noted on budget ({amt}) — "

            # Revenue hints e.g., "MRR 5k", "ARR 600k", "revenue 50k/mo"
            if not ack and any(k in low for k in ("mrr","arr","revenue")):
                ack = "Thanks for the revenue context — "

            # Margin/profit hints
            if not ack and any(k in low for k in ("margin","gm","profit","ebit","cash flow","operating cash")):
                ack = "Got it on profitability — "
            # Team size e.g., "50–200 FTE", "team of 12", "12 employees"
            if not ack and any(k in low for k in ("fte", "team", "employees", "headcount", "people")):
                import re
                m = re.search(r"(\b\d+\s*[–-]\s*\d+\s*(fte|employees|people)\b)|(\bteam\s+of\s+\d+\b)|(\b\d+\s*(fte|employees|people)\b)", low)
                if m:
                    span = m.group(0)
                    ack = f"Noted on team size ({span}) — "

        except Exception:
            pass

    # Deterministic variant picker (stable across calls for the same inputs)
    try:
        import hashlib, time
        from flask import request
        sid = request.cookies.get("sekki_sid", "")
        t_bucket = int(time.time() // 60)   # rotate about every 60 seconds
        seed = f"{slot}|{last_user_msg}|{sid}|{t_bucket}"
        h = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        def pick(n: int) -> int:
            return int(h[:8], 16) % max(1, n)
    except Exception:
        def pick(n: int) -> int:
            return 0

    variants = {
        "revenue_run_rate": [
            "what’s a rough monthly revenue right now? a ballpark is perfect.",
            "could you share about how much you bring in per month? estimate is fine.",
            "roughly what’s a typical month in revenue? ballpark works.",
        ],
        "profitability": [
            "how healthy are margins today? even a rough margin or profit snapshot helps.",
            "could you share profitability at a high level—margin or profit is fine.",
            "what does profitability look like at the moment? an estimate is okay.",
        ],
        "plan_window": [
            "what planning window makes sense—6 or 12 months is fine.",
            "how many months should we plan for?",
            "what time window should we use (months)?",
        ],
        "target_market": [
            "who’s the ideal customer—buyer role or company size is fine; industry and geography if you have them.",
            "can you sketch the target customer? a buyer role and company size are perfect; industry/region if handy.",
            "who are you selling to? a quick buyer role and size work; vertical or geography if easy.",
        ],
        "business_description": [
            "in one line, what does your product do and why do customers choose it?",
            "give me a quick line on what you offer and the core value.",
            "what’s the elevator pitch—what it does and why it wins?",
        ],
        "revenue_model": [
            "how is pricing structured, and what are the main revenue streams?",
            "what’s the pricing model (per user/site/tier), and how do you make money?",
            "walk me through pricing and primary revenue sources.",
        ],
        "financial_metrics": [
            "could you share a ballpark—monthly or annual revenue is great; margin or profit works too (whatever you’re comfortable with).",
            "what’s a rough financial snapshot? monthly revenue or margin is perfect; an estimate is fine.",
            "share one quick metric you’re comfortable with—monthly revenue, margin, or profit; a ballpark is totally okay.",
        ],
        "budget": [
            "what overall budget should we plan within? a range is fine.",
            "could you confirm the total budget (a rough number works)?",
            "what’s the total budget we should work to? ballpark is okay.",
        ],
        "competition": [
            "who do you consider top competitors, and what meaningfully sets you apart?",
            "name a couple competitors and how you differ.",
            "who else solves this today, and where do you stand out?",
        ],
        "team": [
            "who are the key roles responsible for execution?",
            "which core team members or roles will drive this?",
            "who’s on point for delivery (roles)?",
        ],
    }
    v = variants.get(slot) or [
        "what’s the single detail that would move us forward right now? a ballpark is fine.",
        "what would help most to make the next step useful? share whatever you’re comfortable with.",
        "what’s one quick detail that would clarify the next move? estimates are okay.",
    ]
    return f"{ack}{hint}{v[pick(len(v))]}"

def calculate_readiness(messages: List[Dict]) -> int:
    """
    Legacy integer readiness (0..100) used by some callers.
    Now derived from category coverage using multi-signal thresholds.
    """
    snap = build_readiness_snapshot(messages or [])
    return int(snap.get("overall", {}).get("percent", 0))

def _category_percent(collected: dict, rule: dict) -> int:
    """Convert collected signals into a 0..100 percent for a category."""
    got = sum(1 for s in rule["signals"] if collected.get(s))
    need = max(1, int(rule.get("need", 1)))
    if got <= 0:
        return 0
    if got >= need:
        return 100
    # partial credit when some signals are present but below threshold
    return int(round(100 * (got / float(need))))
# --- Category rules drive smart readiness (multi-signal with thresholds) ---
# Weights sum to 1.0 and reflect what the UI shows. A category is only "complete"
# when it meets or exceeds its "need" (i.e., multiple independent signals).
CATEGORY_RULES = {
    "business_description": {
        "weight": 0.10,
        "need": 3,  # name + problem + solution/offer
        "signals": [
            "project_name_present",
            "problem_statement",
            "solution_description",
            "product_or_service",
            "value_prop",
        ],
    },
    # Who we target and where (demographic/firmographic/geo/vertical)
    "target_market": {
        "weight": 0.15,
        "need": 3,  # at least 3 distinct signals
        "signals": [
            "target_customer",
            "demographics",
            "firmographics",
            "geographic_region",
            "industry_vertical",
            "psychographics",
            "market_size",
        ],
    },
    # How we make money (pricing + model). Needs BOTH.
    "revenue_model": {
        "weight": 0.15,
        "need": 2,
        "signals": [
            "pricing",
            "revenue_model",
            "contract_terms",
            "sales_channels",
        ],
    },
    # Key finance signals (do NOT complete with a single % mention)
    "financial_metrics": {
        "weight": 0.25,
        "need": 3,  # need at least 3 distinct financial signals
        "signals": [
            "baseline_revenue",
            "baseline_cogs",
            "baseline_opex",
            "ebitda_or_margin",
            "discount_rate",
            "industry_multiple",
            "cac_ltv",
            "churn_retention",
        ],
    },
    # Project execution timing
    "timeline": {
        "weight": 0.10,
        "need": 1,
        "signals": [
            "timeline_window",
            "milestones",
        ],
    },
    # Money required / available
    "budget": {
        "weight": 0.20,
        "need": 1,
        "signals": [
            "budget_amount",
            "capex_opex",
            "investment_amount",
        ],
    },
    # Competitive position / alternatives
    "competition": {
        "weight": 0.02,
        "need": 1,
        "signals": [
            "competitors",
            "differentiators",
        ],
    },
    # Who will execute / resources
    "team": {
        "weight": 0.03,
        "need": 1,
        "signals": [
            "team_roles",
            "headcount",
            "hiring_needs",
        ],
    },
}

# --- Extract structured signals from the conversation ---
def extract_collected_data(messages: List[Dict]) -> Dict[str, bool]:
    """
    Turns conversation text into a set of booleans the readiness engine uses.
    This is intentionally redundant and forgiving (multiple phrasings).
    """
    text = " ".join(
        (m.get("content") or "")
        for m in messages
        if (m.get("role") in ("user", "assistant"))
    )
    low = text.lower()

    def has_any(*phrases: str) -> bool:
        return any(p in low for p in phrases)

    # Quick regex helpers
    money    = re.compile(r"(?:\$[\s]?\d[\d,\.]*\s?(?:k|m|mm|b)?|\b\d[\d,\.]*\s?(?:usd|dollars)\b)", re.I)
    percent  = re.compile(r"\b\d{1,3}\s?%\b")
    months   = re.compile(r"\b\d{1,2}\s*(?:month|months|mo|quarter|quarters|q[1-4])\b", re.I)
    years    = re.compile(r"\b\d{1,2}\s*(?:year|years|yr|yrs)\b", re.I)
    per_mo   = re.compile(r"(?:/mo|per month|monthly)", re.I)

    signals = {
        # Business description
        "project_name_present":   has_any("project name", "initiative", "called", "named") or bool(re.search(r"project[:\-]\s*\S", text, re.I)),
        "problem_statement":      has_any("problem", "pain point", "challenge", "issue we solve"),
        "solution_description":   has_any("solution", "we offer", "we will build", "we provide"),
        "product_or_service":     has_any("product", "service", "platform", "application", "app"),
        "value_prop":             has_any("value proposition", "differentiated", "unique value", "why us"),

        # Target market
        "target_customer":        has_any("target market", "target customer", "audience", "buyer", "persona"),
        "demographics":           has_any("age", "income", "household", "demographic"),
        "firmographics":          has_any("company size", "employee", "enterprise", "smb", "midmarket"),
        "geographic_region":      has_any("city", "state", "country", "region", "us", "europe", "texas", "nyc", "sf"),
        "industry_vertical":      has_any("industry", "vertical", "healthcare", "manufacturing", "retail", "saas"),
        "psychographics":         has_any("psychographic", "behavior", "values", "preference"),
        "market_size":            has_any("tam", "sam", "som", "market size", "addressable") or bool(re.search(r"\b(billion|million|bn|mm)\b", low)),

        # Revenue model / pricing
        "pricing":                has_any("price", "pricing", "subscription", "license", "tier", "freemium") or bool(per_mo.search(low)),
        "revenue_model":          has_any("revenue model", "business model", "revenue stream", "transaction fee", "take rate"),
        "contract_terms":         has_any("contract", "term", "annual", "commitment"),
        "sales_channels":         has_any("channel", "direct sales", "partner", "reseller"),

        # Financial metrics
        "baseline_revenue":       has_any("revenue", "arr", "mrr") or bool(money.search(low)),
        "baseline_cogs":          has_any("cogs", "cost of goods"),
        "baseline_opex":          has_any("opex", "operating expense", "sga", "sg&a", "r&d", "marketing spend"),
        "ebitda_or_margin":       has_any("ebitda", "margin", "gross margin", "profit") or bool(percent.search(low)),
        "discount_rate":          has_any("discount rate", "wacc", "hurdle rate"),
        "industry_multiple":      has_any("multiple", "valuation", "ev/ebitda"),
        "cac_ltv":                has_any("cac", "customer acquisition cost", "ltv", "lifetime value"),
        "churn_retention":        has_any("churn", "retention", "logo churn", "net retention"),

        # Timeline
        "timeline_window":        bool(months.search(low) or years.search(low)) or has_any("timeline", "launch date", "go live", "phase"),
        "milestones":             has_any("milestone", "phase 1", "phase 2", "pilot", "rollout"),

        # Budget
        "budget_amount":          has_any("budget", "spend", "allocation") or bool(money.search(low)),
        "capex_opex":             has_any("capex", "capital expenditure", "opex"),
        "investment_amount":      has_any("investment", "initial investment", "one-time cost") or bool(money.search(low)),

        # Competition
        "competitors":            has_any("competitor", "competition", "alternative"),
        "differentiators":        has_any("differentiator", "moat", "advantage", "better than"),

        # Team
        "team_roles":             has_any("team", "pm", "engineer", "sales", "marketing", "ops"),
        "headcount":              has_any("headcount", "fte", "people"),
        "hiring_needs":           has_any("hire", "hiring", "recruit"),
    }

    return signals

def build_readiness_snapshot(messages: list[dict]) -> dict:
    """
    Returns a structured readiness payload:
    {
      "overall": { "percent": int, "source": "heuristic" },
      "categories": [
        { "key": "...", "label": "...", "percent": int, "completed": bool, "weight": float }
      ],
      "version": "readiness_v1.2.0"
    }
    """
    collected = extract_collected_data(messages)
    categories = []
    overall = 0.0
    total_weight = 0.0

    for key, rule in CATEGORY_RULES.items():
        pct = _category_percent(collected, rule)
        weight = float(rule.get("weight", 0.0))
        categories.append({
            "key": key,
            "label": {
                "business_description": "Business Description",
                "target_market": "Target Market",
                "revenue_model": "Revenue Model",
                "financial_metrics": "Financial Metrics",
                "timeline": "Timeline",
                "budget": "Budget",
                "competition": "Competition",
                "team": "Team & Resources",
            }.get(key, key),
            "percent": pct,
            "completed": pct >= 100,
            "weight": weight,
        })
        overall += pct * weight
        total_weight += weight

    overall_percent = int(round(overall / total_weight)) if total_weight > 0 else 0
    overall_percent = max(0, min(100, overall_percent))

    return {
        "overall": { "percent": overall_percent, "source": "heuristic" },
        "categories": categories,
        "version": "readiness_v1.2.0",
        "collected_data": collected,  # convenient for debugging
    }
# ---------- Readiness API expected by the frontend ----------

@market_iq_bp.route("/readiness/spec", methods=["GET"])
def readiness_spec():
    """
    Returns a stable spec (keys, labels, weights) so the UI can render
    category names and relative weights without looking at a specific session.
    """
    # Keep in sync with CATEGORY_RULES
    label_map = {
        "business_description": "Business Description",
        "target_market":        "Target Market",
        "revenue_model":        "Revenue Model",
        "financial_metrics":    "Financial Metrics",
        "timeline":             "Timeline",
        "budget":               "Budget",
        "competition":          "Competition",
        "team":                 "Team & Resources",
    }

    categories = [
        {
            "key": key,
            "label": label_map.get(key, key),
            "weight": float(rule.get("weight", 0.0)),
        }
        for key, rule in CATEGORY_RULES.items()
    ]

    return jsonify({
        "version": "readiness_v1.2.0",
        "categories": categories,
    }), 200


@market_iq_bp.route("/readiness/audit", methods=["GET"])
def readiness_audit():
    """
    Returns the computed readiness snapshot for a given session.
    Query string: ?sid=...  (frontend also sends X-Session-ID; we accept either)
    Shape:
    {
      "overall": { "percent": int, "source": "heuristic" },
      "categories": [{ key, label, percent, completed, weight }],
      "version": "readiness_v1.2.0"
    }
    """
    sid = request.args.get("sid") or request.headers.get("X-Session-ID")
    if not sid:
        # No session id — return empty snapshot with all 0s
        empty = {
            "overall": {"percent": 0, "source": "heuristic"},
            "categories": [
                {
                    "key": key,
                    "label": {
                        "business_description": "Business Description",
                        "target_market":        "Target Market",
                        "revenue_model":        "Revenue Model",
                        "financial_metrics":    "Financial Metrics",
                        "timeline":             "Timeline",
                        "budget":               "Budget",
                        "competition":          "Competition",
                        "team":                 "Team & Resources",
                    }.get(key, key),
                    "percent": 0,
                    "completed": False,
                    "weight": float(rule.get("weight", 0.0)),
                }
                for key, rule in CATEGORY_RULES.items()
            ],
            "version": "readiness_v1.2.0",
        }
        return jsonify(empty), 200

    session = SESSIONS.get(sid)
    if not session:
        # Unknown session — same empty shape
        empty = {
            "overall": {"percent": 0, "source": "heuristic"},
            "categories": [
                {
                    "key": key,
                    "label": {
                        "business_description": "Business Description",
                        "target_market":        "Target Market",
                        "revenue_model":        "Revenue Model",
                        "financial_metrics":    "Financial Metrics",
                        "timeline":             "Timeline",
                        "budget":               "Budget",
                        "competition":          "Competition",
                        "team":                 "Team & Resources",
                    }.get(key, key),
                    "percent": 0,
                    "completed": False,
                    "weight": float(rule.get("weight", 0.0)),
                }
                for key, rule in CATEGORY_RULES.items()
            ],
            "version": "readiness_v1.2.0",
        }
        return jsonify(empty), 200

    # Compute snapshot from the live conversation
    snap = build_readiness_snapshot(session.get("messages") or [])
    return jsonify({
        "overall":   snap.get("overall", {"percent": 0, "source": "heuristic"}),
        "categories": snap.get("categories", []),
        "version":    snap.get("version", "readiness_v1.2.0"),
    }), 200

@market_iq_bp.route("/conversation/start", methods=["POST"])
def conversation_start():
    """Start a natural conversation with Claude"""
    try:
        j = request.get_json(silent=True) or {}
        description = (j.get("description") or "").strip()
        
        if not description:
            return jsonify({"error": "description required"}), 400
        
        session_id = _new_id()
        
        # Initialize conversation with Claude
        client = get_claude_client()
        
        messages = [
            {"role": "user", "content": description}
        ]
        
        response = client.messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929"),
            max_tokens=400,
            temperature=0.7,
            system=CONVERSATION_SYSTEM_PROMPT,
            messages=messages
        )
        parts = []
        for blk in response.content:
            if getattr(blk, "type", None) == "text":
                parts.append(blk.text)
        ai_message = ("".join(parts)).strip() or "(no content)"
        ai_message = _enforce_one_question(ai_message)

        # Store session
        messages.append({"role": "assistant", "content": ai_message})
        SESSIONS[session_id] = {
            "id": session_id,
            "messages": messages,
            "created_at": int(time.time()),
            "stage": "INTAKE",   
        }
        
        readiness = calculate_readiness(messages)
        collected_data = extract_collected_data(messages)
        
        return jsonify({
            "session_id": session_id,
            "message": ai_message,
            "readiness": readiness,
            "collected_data": collected_data,
            "status": "gathering_info"
        }), 200
        
    except Exception as e:
        current_app.logger.exception("conversation_start_failed")
        return jsonify({"error": "conversation_start_failed", "details": str(e)}), 500
@market_iq_bp.route("/conversation/continue", methods=["POST"])
def conversation_continue():
    """Continue the natural conversation"""
    try:
        j = request.get_json(silent=True) or {}
        session_id = j.get("session_id")
        user_message = (j.get("message") or "").strip()

        if not session_id or not user_message:
            return jsonify({"error": "session_id and message required"}), 400

        session = SESSIONS.get(session_id)
        if not session:
            return jsonify({"error": "session not found"}), 404

        # Add user message to history
        session["messages"].append({"role": "user", "content": user_message})

        client = get_claude_client()

        # --- dynamic system prompt nudge (conversational + gap-aware) ---
        collected = extract_collected_data(session["messages"])
        dynamic_system = CONVERSATION_SYSTEM_PROMPT

        # avoid re-asking project name if already present
        if collected.get("project_name_present"):
            dynamic_system += "\n\n(You already captured the project name; avoid asking it again.)"

        missing_hints = []
        if not collected.get("revenue_model"):
            missing_hints.append("clarify the revenue model/pricing structure")
        if not collected.get("market_size"):
            missing_hints.append("estimate market size/opportunity (TAM/SAM/SOM if possible)")
        if not collected.get("cac_ltv"):
            missing_hints.append("capture CAC/LTV or how customers are acquired and retained")
        if not collected.get("churn_retention"):
            missing_hints.append("get churn/retention expectations")
        if not collected.get("competitors"):
            missing_hints.append("understand key competitors and differentiators")
        if not collected.get("budget_amount"):
            missing_hints.append("confirm budget and whether it’s capex/opex")
        if not collected.get("timeline_window"):
            missing_hints.append("confirm delivery timeline / milestones")

        if missing_hints:
            dynamic_system += (
                "\n\n(Nudge: Ask ONE question that targets ONE of these gaps: "
                + "; ".join(missing_hints)
                + ".)"
            )
        # --- stage lens (adds SCENARIOS/EXECUTION internal prompt without losing context) ---
        stage = (session.get("stage") or "INTAKE").upper()

        if stage == "SCENARIOS":
            dynamic_system += "\n\n" + SCENARIOS_INTERNAL_SYSTEM_PROMPT
        elif stage == "EXECUTION":
            dynamic_system += "\n\n" + EXECUTION_INTERNAL_SYSTEM_PROMPT

        response = client.messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929"),
            max_tokens=400,
            temperature=0.7,
            system=dynamic_system,
            messages=session["messages"],
        )

        # Extract assistant text safely
        parts = []
        for blk in getattr(response, "content", []) or []:
            if getattr(blk, "type", None) == "text":
                parts.append(blk.text)
        ai_message = ("".join(parts)).strip() or "(no content)"

        # Store assistant message
        session["messages"].append({"role": "assistant", "content": ai_message})

        readiness = calculate_readiness(session["messages"])
        collected_data = extract_collected_data(session["messages"])

        return jsonify({
            "session_id": session_id,
            "message": ai_message,
            "readiness": readiness,
            "collected_data": collected_data,
            "status": "gathering_info"
        }), 200

    except Exception as e:
        current_app.logger.exception("conversation_continue_failed")
        return jsonify({"error": "conversation_continue_failed", "details": str(e)}), 500
def _infer_baseline_from_text(txt: str) -> dict:
    """
    Heuristic pass to extract baseline financials that often appear in free text.
    Returns numbers; leave None when not found.
    """
    if not txt:
        return {}

    t = txt.lower()
    import re

    money = lambda s: float(s.replace(",", "")) if s else None

    def _to_number(raw):
        if not raw:
            return None
        r = raw.strip().lower().replace(",", "")
        mult = 1.0
        if r.endswith("m"):
            mult = 1_000_000.0
            r = r[:-1]
        elif r.endswith("k"):
            mult = 1_000.0
            r = r[:-1]
        r = r.replace("$", "").strip()
        try:
            return float(r) * mult
        except Exception:
            return None

    # revenue: look for "revenue ~$2.4M" or "annual revenue 2.4m" or "rev 2400000"
    rev_pat = re.compile(r"(?:annual\s+)?rev(?:enue)?\s*[:~]?\s*\$?\s*([0-9.,]+(?:[mk])?)")
    # opex: "opex ~$1.1M" or "operating expenses 1100000"
    opex_pat = re.compile(r"op(?:erating)?\s*ex(?:penses|p)?\s*[:~]?\s*\$?\s*([0-9.,]+(?:[mk])?)")
    # cogs %: "cogs ~32%" or "cogs 0.32"
    cogs_pct_pat = re.compile(r"cogs\s*[:~]?\s*([0-9]{1,3}(?:\.\d+)?)\s*%")
    cogs_abs_pat = re.compile(r"(?:cogs|cost of goods sold)\s*[:=]?\s*\$?([0-9][0-9,]*\.?[0-9]*\s*[kmb]?)", re.I)
    # ebitda margin %: "ebitda margin ~18%"
    ebitda_margin_pat = re.compile(r"ebitda(?:\s*margin)?\s*[:~]?\s*([0-9]{1,3}(?:\.\d+)?)\s*%")
    # plain ebitda: "ebitda 200k"
    ebitda_abs_pat = re.compile(r"ebitda\s*[:~]?\s*\$?\s*([0-9.,]+(?:[mk])?)")

    baseline = {
        "revenue": _to_number((rev_pat.search(t) or [None, None])[1]),
        "operating_expenses": _to_number((opex_pat.search(t) or [None, None])[1]),
        "cogs_percent": None,
        "ebitda_margin_percent": None,
        "ebitda": None,
    }

    m = cogs_pct_pat.search(t)
    if m:
        try:
            baseline["cogs_percent"] = float(m.group(1))
        except Exception:
            pass

    m = ebitda_margin_pat.search(t)
    if m:
        try:
            baseline["ebitda_margin_percent"] = float(m.group(1))
        except Exception:
            pass

    m = ebitda_abs_pat.search(t)
    if m:
        eb = _to_number(m.group(1))
        if eb is not None:
            baseline["ebitda"] = eb

    # If we have revenue and COGS %, compute COGS dollars
    if baseline.get("revenue") is not None and baseline.get("cogs_percent") is not None:
        baseline["cogs"] = baseline["revenue"] * (baseline["cogs_percent"] / 100.0)
    else:
        baseline["cogs"] = None

    return baseline

@market_iq_bp.route("/scenario", methods=["POST"])
def scenario():
    """Apply scenario changes to existing analysis"""
    try:
        j = request.get_json(silent=True) or {}
        analysis = j.get("analysis_result") or {}
        changes = j.get("changes") or {}
        
        # Simple scenario modeling - adjust scores based on changes
        out = dict(analysis)
        if "market_iq_score" in out and isinstance(changes.get("delta"), (int, float)):
            out["market_iq_score"] = int(max(1, min(99, out["market_iq_score"] + int(changes["delta"]))))
        
        return jsonify(out), 200
        
    except Exception as e:
        current_app.logger.exception("scenario_failed")
        return jsonify({"error": "scenario_failed", "details": str(e)}), 500
