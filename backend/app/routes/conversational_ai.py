from __future__ import annotations
from app.services.rate_limit import rate_limit
"""
Conversational AI Route for Sekki Market IQ — ENHANCED A+ VERSION
Features:
- Comprehensive macro/micro readiness tracking
- Cumulative text analysis (all messages)
- Smart keyword matching with word boundaries
- Graceful degradation
- Foundation for caching and analytics (Phase 2/3)
"""
import os, json, time, uuid, re
from pathlib import Path
from typing import Any, Dict, List, Optional
from flask import Blueprint, request, jsonify, current_app, make_response
from dotenv import load_dotenv
import anthropic
# =========================
# UI Intents (Interactive)
# =========================
import json
import re
from typing import Any, Dict, List, Optional, Tuple

_UI_INTENTS_RE = re.compile(
    r"<ui_intents>\s*(\[[\s\S]*?\]|\{[\s\S]*?\})\s*</ui_intents>",
    re.IGNORECASE
)

# Keep this aligned with frontend ChatActionTypes
ALLOWED_UI_INTENTS = {
    "SCORECARD_SELECT",
    "SCORECARD_UPDATE_FIELD",
    "SCENARIO_SET_INPUT",
    "SCENARIO_RUN",
    "SCENARIO_ADOPT",
    "PROJECT_BEGIN",
}

def _as_list(x: Any) -> List[Any]:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]

def extract_ui_intents(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Extracts strict JSON inside:
      <ui_intents> [...] </ui_intents>

    Returns: (clean_text, intents)
    """
    if not text:
        return "", []

    m = _UI_INTENTS_RE.search(text)
    if not m:
        return text, []

    raw_json = (m.group(1) or "").strip()
    clean_text = (text[:m.start()] + text[m.end():]).strip()

    try:
        parsed = json.loads(raw_json)
    except Exception:
        # If parsing fails, don't break replies; leave as-is
        return text, []

    items = parsed if isinstance(parsed, list) else _as_list(parsed)

    intents: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue

        intent_type = it.get("type") or it.get("intent") or it.get("action")
        payload = it.get("payload") or {}

        if not isinstance(intent_type, str):
            continue
        if intent_type not in ALLOWED_UI_INTENTS:
            continue

        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            payload = {"value": payload}

        intents.append({"type": intent_type, "payload": payload})

    return clean_text, intents

def interactive_system_suffix(ui_context: Optional[Dict[str, Any]] = None) -> str:
    ctx = ui_context or {}
    return (
        "If the user asks to change UI/state on the current screen, you MAY propose 'ui_intents'.\n"
        "If you propose intents, append them at the END of your reply in this exact machine-readable format:\n"
        "<ui_intents>\n"
        "[{\"type\":\"SCORECARD_UPDATE_FIELD\",\"payload\":{...}}]\n"
        "</ui_intents>\n"
        "Rules:\n"
        "- Inside <ui_intents> must be STRICT JSON only.\n"
        "- Only use allowed intent types.\n"
        "- If no UI change is needed, do NOT include <ui_intents>.\n"
        f"- UI context: {json.dumps(ctx, ensure_ascii=False)}\n"
    )

# --- Use the Market IQ system prompt centrally defined in market_iq.py ---
try:
    # reuse the exact same prompt the Market IQ routes use
    from .market_iq import CONVERSATION_SYSTEM_PROMPT as MARKET_IQ_SYSTEM_PROMPT
except Exception:
    MARKET_IQ_SYSTEM_PROMPT = None

def _load_prompt_fallback() -> str:
    """
    Fallback: if import fails, load from prompts file so we never hard-crash.
    """
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    prompt_path = os.path.join(base_dir, "prompts", "market_iq_system.txt")
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        # very small safe default (won't be used in normal flows)
        return "You are a senior market analyst. Have a natural conversation and end with one question."

# Single canonical variable used in this module:
SYSTEM_PROMPT = MARKET_IQ_SYSTEM_PROMPT or _load_prompt_fallback()

from app.utils.request_payload import extract_user_text
from app.services.scorecard_calc import run_calculator
from app.utils.financial_scoring import SimpleFinancialScorer
from app.financial_profiles import detect_profile, get_profile_slots

_SCORER: SimpleFinancialScorer | None = None
def _get_scorer() -> SimpleFinancialScorer:
    global _SCORER
    if _SCORER is None:
        _SCORER = SimpleFinancialScorer()
    return _SCORER

# === Enhanced Readiness Structure with Macro/Micro Elements ==================

# Define micro elements for each macro category with detailed keywords
MACRO_CATEGORIES = {
    "business_description": {
        "weight": 0.10,
        "micros": [
            "overview",
            "mission_vision",
            "product_service",
            "value_proposition",
            "unique_selling_points"
        ],
        "keywords": {
            "overview": ["business", "company", "we do", "we are", "organization", "startup", "venture"],
            "mission_vision": ["mission", "vision", "goal", "purpose", "why we exist", "our mission"],
            "product_service": ["product", "service", "offering", "solution", "what we sell", "provide"],
            "value_proposition": ["value", "benefit", "advantage", "why choose", "value prop"],
            "unique_selling_points": ["unique", "different", "competitive edge", "stand out", "differentiate"]
        }
    },
    "target_market": {
        "weight": 0.15,
        "micros": [
            "customer_segment",
            "demographics",
            "geographic_region",
            "industry_vertical",
            "market_size"
        ],
        "keywords": {
            "customer_segment": ["customer", "audience", "segment", "who buys", "target", "buyer persona"],
            "demographics": ["age", "gender", "income", "education", "demographics", "profile"],
            "geographic_region": ["region", "country", "city", "location", "geographic", "territory", "area"],
            "industry_vertical": ["industry", "sector", "vertical", "b2b", "b2c", "enterprise", "smb"],
            "market_size": ["market size", "tam", "sam", "som", "addressable market", "total market"]
        }
    },
    "revenue_model": {
        "weight": 0.15,
        "micros": [
            "pricing_strategy",
            "revenue_streams",
            "business_model",
            "unit_economics"
        ],
        "keywords": {
            "pricing_strategy": ["price", "pricing", "cost", "fee", "charge", "rate", "tier"],
            "revenue_streams": ["revenue", "income", "sales", "monetization", "earn", "generate"],
            "business_model": ["subscription", "one-time", "recurring", "saas", "licensing", "freemium", "model"],
            "unit_economics": ["arpu", "ltv", "cac", "unit economics", "customer value", "lifetime value"]
        }
    },
    "financial_metrics": {
        "weight": 0.25,
        "micros": [
            "revenue_figures",
            "profitability",
            "margins",
            "growth_rate",
            "burn_rate"
        ],
        "keywords": {
            "revenue_figures": ["revenue", "sales", "arr", "mrr", "income", "run rate", "annual revenue"],
            "profitability": ["profit", "ebitda", "net income", "bottom line", "profitable", "earnings"],
            "margins": ["margin", "gross margin", "contribution margin", "cm", "profit margin"],
            "growth_rate": ["growth", "yoy", "mom", "cagr", "growth rate", "growing"],
            "burn_rate": ["burn", "runway", "cash flow", "operating expenses", "burn rate"]
        }
    },
    "timeline": {
        "weight": 0.10,
        "micros": [
            "launch_date",
            "milestones",
            "phases",
            "duration"
        ],
        "keywords": {
            "launch_date": ["launch", "go live", "start date", "begin", "kickoff", "release"],
            "milestones": ["milestone", "checkpoint", "deliverable", "key date", "deadline"],
            "phases": ["phase", "stage", "step", "iteration", "sprint"],
            "duration": ["timeline", "duration", "months", "weeks", "quarters", "timeframe", "year"]
        }
    },
    "budget": {
        "weight": 0.20,
        "micros": [
            "total_budget",
            "allocation",
            "funding_source",
            "cost_structure"
        ],
        "keywords": {
            "total_budget": ["budget", "funding", "investment", "capital", "money", "dollars"],
            "allocation": ["allocate", "spend", "distribution", "breakdown", "split"],
            "funding_source": ["funded", "investor", "bootstrap", "loan", "grant", "raised"],
            "cost_structure": ["cost", "expense", "capex", "opex", "fixed cost", "variable cost"]
        }
    },
    "competition": {
        "weight": 0.02,
        "micros": [
            "competitors",
            "market_position",
            "differentiation"
        ],
        "keywords": {
            "competitors": ["competitor", "rival", "alternative", "competition", "competing"],
            "market_position": ["market share", "leader", "challenger", "position", "rank"],
            "differentiation": ["different", "unique", "better", "advantage", "versus", "compared to"]
        }
    },
    "team": {
        "weight": 0.03,
        "micros": [
            "leadership",
            "team_size",
            "key_roles",
            "expertise"
        ],
        "keywords": {
            "leadership": ["founder", "ceo", "cto", "leadership", "executive", "management"],
            "team_size": ["team", "employees", "headcount", "staff", "people", "members"],
            "key_roles": ["roles", "positions", "hiring", "talent", "recruit"],
            "expertise": ["experience", "expertise", "skills", "background", "qualified"]
        }
    }
}


def smart_keyword_match(keyword: str, text: str) -> bool:
    """
    Smart keyword matching with word boundaries to reduce false positives.
    Handles both single words and phrases.
    """
    # Escape special regex characters in keyword
    escaped = re.escape(keyword)
    # Use word boundaries for single words, phrase matching for multi-word
    if ' ' in keyword:
        # Multi-word phrase: match the whole phrase
        pattern = r'\b' + escaped + r'\b'
    else:
        # Single word: strict word boundary
        pattern = r'\b' + escaped + r'\b'
    
    return bool(re.search(pattern, text, re.IGNORECASE))


def get_cumulative_user_text(sess: dict) -> str:
    """
    Extract and combine all user messages from the session.
    This ensures we don't lose information from earlier messages.
    """
    messages = sess.get("messages", [])
    user_texts = [
        msg.get("content", "")
        for msg in messages
        if msg.get("role") == "user" and msg.get("content", "").strip()
    ]
    return " ".join(user_texts).lower()


def compute_readiness(sess: dict) -> dict:
    # --- patched compute_readiness ---
    try:
        cumulative_text = get_cumulative_user_text(sess)
        session_micros = sess.get("micro_elements", {})

        def has(pat: str) -> bool:
            try:
                return re.search(pat, cumulative_text, re.I) is not None
            except re.error:
                return False

        # Simple regex marks (examples)
        if has(r"\b(b2b|saas|product|service|solution)\b"):
            session_micros.setdefault("business_description", {}).setdefault("product_service", {"collected": True, "confidence": 1.0})
        if has(r"\bmid[-\s]?market\b") and has(r"\bretail(?:er|ers)?\b"):
            session_micros.setdefault("target_market", {}).setdefault("customer_segment", {"collected": True, "confidence": 1.0})
            session_micros.setdefault("target_market", {}).setdefault("industry_vertical", {"collected": True, "confidence": 1.0})
        if has(r"\bU\.?S\.?|United States|USA\b"):
            session_micros.setdefault("target_market", {}).setdefault("geographic_region", {"collected": True, "confidence": 1.0})
        if has(r"\bbudget\b.*\$?\s*\d[\d,\.]*\s*[kmb]?\b|\$250k\b"):
            session_micros.setdefault("budget", {}).setdefault("total_budget", {"collected": True, "confidence": 1.0})
        if has(r"\b(\d+)\s*-\s*month\b|\b(\d+)\s*months\b|\b12-month plan\b"):
            session_micros.setdefault("timeline", {}).setdefault("duration", {"collected": True, "confidence": 1.0})
        if has(r"\bgross margin\b|\bGM\b|\b\d{1,2}\s*%.*margin"):
            session_micros.setdefault("financial_metrics", {}).setdefault("margins", {"collected": True, "confidence": 1.0})

        # Calculator extraction (safe)
        try:
            calc = run_calculator(cumulative_text or "")
        except Exception:
            calc = {}
        parsed = (calc or {}).get("inputs_parsed", {}) or {}
        # Merge session-sourced parsed inputs (authoritative user labels)
        try:
            _sess_parsed = dict(sess.get("parsed_inputs") or {})
            if _sess_parsed:
                # session values override calculator if present
                for k, v in _sess_parsed.items():
                    if isinstance(v, (int, float)):
                        if k == "gross_margin":
                            # accept either 0..1 or 0..100; normalize to 0..100
                            try:
                                v = float(v)
                                if v <= 1.0:   # e.g., 0.68 -> 68.0
                                    v = v * 100.0
                                v = max(0.0, min(100.0, v))
                            except Exception:
                                pass
                        parsed[k] = v
        except Exception:
            pass

        # Apply active scenario overrides last (highest priority)
        try:
            _scn = sess.get("scenario_overrides") or {}
            if isinstance(_scn, dict) and _scn:
                for k, v in _scn.items():
                    if isinstance(v, (int, float)):
                        if k == "gross_margin":
                            # accept either 0..1 or 0..100; normalize to 0..100
                            try:
                                v = float(v)
                                if v <= 1.0:
                                    v = v * 100.0
                                v = max(0.0, min(100.0, v))
                            except Exception:
                                pass
                        parsed[k] = v
        except Exception:
            pass


                # --- Fallback signals if calculator missed obvious patterns (text heuristics) ---
        try:
            # e.g., "$49/user/month", "$49 per user per month", "49/mo"
            if not parsed.get("price_month"):
                if re.search(r'\$?\s*\d+(?:[.,]\d{2})?\s*(?:/|\bper\b)\s*(?:user|seat|acct)', cumulative_text, re.I) and \
                   re.search(r'\b(?:per\s*)?(?:month|mo|m)\b', cumulative_text, re.I):
                    parsed["price_month"] = 1  # sentinel to satisfy rule

            # e.g., "launch in 6 months", "in 6 mo", "6-month plan"
            if not parsed.get("plan_months"):
                if re.search(r'\b(?:in|within)?\s*\d{1,2}\s*(?:months?|mos?|mo)\b', cumulative_text, re.I) or \
                   re.search(r'\b\d{1,2}\s*-\s*month\b', cumulative_text, re.I) or \
                   re.search(r'\b\d{1,2}\s*(?:month)\s*(?:plan|timeline)\b', cumulative_text, re.I):
                    parsed["plan_months"] = 1  # sentinel to satisfy rule
                        # Try to capture a numeric per-user monthly price if sentinel/missing
            if not parsed.get("price_month") or parsed.get("price_month") == 1:
                m_price = re.search(
                    r'\$?\s*([0-9][\d,]*(?:\.[0-9]{1,2})?)\s*(?:/|\bper\b)\s*(?:user|seat|acct)\s*(?:/|\bper\b)?\s*(?:month|mo|m)\b',
                    cumulative_text,
                    re.I,
                )
                if m_price:
                    try:
                        parsed["price_month"] = float(m_price.group(1).replace(",", ""))
                    except Exception:
                        parsed["price_month"] = 1  # fallback sentinel

            # Capture subscribers/users count, e.g. "target 1,000 users", "1000 subscribers"
            if not parsed.get("subscribers"):
                m_users = re.search(
                    r'\b(?:target\s*)?([\d,\.]{1,9})\s*(?:users?|subs(?:cribers)?)\b',
                    cumulative_text,
                    re.I,
                )
                if m_users:
                    try:
                        parsed["subscribers"] = int(re.sub(r'[^\d]', '', m_users.group(1))) or 0
                    except Exception:
                        parsed["subscribers"] = 0

            # Derive monthly revenue if we have both price and subscribers
            if not parsed.get("revenue"):
                pm = parsed.get("price_month") or 0
                subs = parsed.get("subscribers") or 0
                if isinstance(pm, (int, float)) and pm > 0 and isinstance(subs, (int, float)) and subs > 0:
                    parsed["revenue"] = pm * subs  # monthly revenue proxy

        except Exception:
            # keep readiness robust even if regex fails
            pass

        metrics_ok = {k for k, v in ((calc or {}).get("metrics", {}) or {}).items() if (v or {}).get("status") == "ok"}

        # Initialize structures
        categories_detail = []
        collected_data = {}
        weighted_total = 0.0
        total_weight = sum(cat["weight"] for cat in MACRO_CATEGORIES.values())

        # ---- Macro-only scoring aligned to the calculator (no micro rows) ----

        # High-confidence text signals (no micro rows exposed)
        txt = cumulative_text
        has_company_identity   = bool(re.search(r"\b(company|business|startup|organization)\b", txt, re.I))
        has_product_service    = bool(re.search(r"\b(product|service|solution|platform|app)\b", txt, re.I))
        has_value_prop_phrase  = bool(re.search(r"\b(value|benefit|advantage|why (choose|us))\b", txt, re.I))
        has_budget_word        = bool(re.search(r"\b(budget|capex|opex|investment)\b", txt, re.I))
        has_money_amount       = bool(re.search(r"(?:\$|usd|\d+[,\.]?\d*\s*(k|m|b)\b)", txt, re.I))

        # For each macro, list the signals that must be satisfied.
        # A category only reaches 100% if ALL its intended basics are present.
        MACRO_RULES = {
            "business_description": [
                ("_any_text", True),  # user said anything at all

                # Count *what it is* OR *what problem/opportunity it addresses*.
                # This lets plain problem/opportunity statements score, even without nouns like "product".
                ("_txt_what", (lambda _v: has(
                    r"\b("
                    r"product|service|solution|platform|copilot|subscription|"
                    r"problem|opportunity|pain point|pain|challenge|bottleneck|"
                    r"margin leakage|stockout|overstock"
                    r")\b"
                ))),

                # Count *why it matters* (value/outcome words), not just labels.
                ("_txt_why", (lambda _v: has(
                    r"\b("
                    r"value|benefit|optimiz(?:e|ation)|automate|improv(?:e|ement)|"
                    r"reduce waste|increase margin|lift sales|lower costs|efficiency|accuracy|"
                    r"personalization|retention|advantage|competitive|differentiation|moat"
                    r")\b"
                ))),
            ],

            "target_market": [
                # geography + vertical/industry (already text-driven)
                ("_txt_geo",      (lambda _v: has(r"\b(us|u\.s\.|united states|usa|north america|texas|california)\b"))),
                ("_txt_vertical", (lambda _v: has(r"\b(retail|retailer|apparel|fashion|grocery|electronics)\b"))),
                # subscribers: accept calculator OR text like "Subscribers = 250" / "250 subscribers"
                ("subscribers",   lambda v: (isinstance(v, (int, float)) and v > 0)
                                              or has(r"\bsubscribers?\b\s*=\s*\d+")
                                              or has(r"\b\d+\s+subscribers?\b")),
                ("has_mrr_arr",   (lambda _v: has_mrr_arr)),
            ],

            "revenue_model": [
                # price: calculator OR text like "pricing $20/user", "per user per month", "recurring SaaS"
                ("price_month",   lambda v: (isinstance(v, (int, float)) and v > 0)
                                              or has(r"\b(price|pricing)\b")
                                              or has(r"\bper[-\s]?(user|seat|month)\b")
                                              or has(r"\b(recurring|saas)\b")),
                # revenue: calculator OR text like "MRR 5000", "ARR 60k", "$5,000 per month"
                ("revenue",       lambda v: (isinstance(v, (int, float)) and v > 0)
                                              or has(r"\b(mrr|arr|revenue)\b")
                                              or has(r"\$\s*\d[\d,\.]*\b")),
            ],

            "financial_metrics": [
                # gross margin: calculator OR text like "65% gross margin" / "GM 65%" / "60% margin"
                ("gross_margin",    lambda v: isinstance(v, (int, float))
                                               or has(r"\b(gross margin|gm|margin)\b")
                                               or has(r"\b\d{1,2}\s*%")),
                # profit/EBIT/EBITDA: accept common business terms
                ("ebit",            lambda v: isinstance(v, (int, float))
                                               or has(r"\b(ebit|ebitda|profit|net income)\b\s*[=:]?\s*\$?\d")
                                               or has(r"\$\d+[km]?\s*(profit|ebitda)")),
                # Cash flow or MRR/ARR: accept revenue metrics as proxy
                ("cash_flow_oper",  lambda v: isinstance(v, (int, float))
                                               or has(r"\b(operating cash flow|cash flow|cfo)\b\s*[=:]?\s*\$?\d")
                                               or has(r"\b(mrr|arr|monthly revenue|annual revenue)\b\s*[=:]?\s*\$?\d")
                                               or has(r"\$\d+[km]?\s*(mrr|arr|revenue|cash flow)")),
            ],

            "timeline": [
                ("plan_months",        lambda v: isinstance(v, (int, float)) and v > 0),
            ],
            "budget": [
                # require both a budget concept and a numeric amount
                ("budget_keyword",     lambda _: has_budget_word),
                ("budget_amount",      lambda _: (isinstance(parsed.get("budget"), (int, float)) and parsed.get("budget") > 0) or has_money_amount),
            ],
        }

        categories_detail = []
        collected_data = {}
        weighted_total = 0.0
        total_weight = sum(cat["weight"] for cat in MACRO_CATEGORIES.values())

        # convenience flags for rules
        _any_text   = bool((cumulative_text or "").strip())
        has_mrr_arr = (("mrr" in metrics_ok) or ("arr" in metrics_ok) or (isinstance(parsed.get("revenue"), (int, float)) and parsed.get("revenue", 0) > 0))

        for macro_key, macro_cfg in MACRO_CATEGORIES.items():
            weight = macro_cfg["weight"]
            rules  = MACRO_RULES.get(macro_key, [])

            # evaluate rules -> booleans
            items_bool = []
            for name, cond in rules:
                if name == "_any_text":
                    ok = _any_text
                elif name == "has_mrr_arr":
                    ok = has_mrr_arr
                else:
                    val = parsed.get(name)
                    ok  = (cond(val) if callable(cond) else bool(val))
                items_bool.append(bool(ok))

            # percent for this macro
            total_slots = max(1, len(items_bool))
            collected   = sum(1 for x in items_bool if x)
            category_fraction = collected / total_slots
            category_percent  = int(round(category_fraction * 100))

            weighted_total += category_fraction * weight

            # minimal detail (no micro rows; UI uses percent)
            categories_detail.append({
                "key": macro_key,
                "percent": category_percent,
                "weight": weight,
                "completed": category_percent >= 100,
                "collected": collected,
                "total": total_slots,
                "micros": [],  # intentionally empty
            })

            # frontend mini-bar uses this boolean list; safe to keep for now
            collected_data[macro_key] = {
                "percent": category_percent,
                "items": items_bool,
            }

        # Heuristic overall
        heur_overall = int(round((weighted_total / (total_weight or 1.0)) * 100))
        overall = heur_overall
        source = "heuristic"
        ml_info = None
                # Optional ML blend (disabled by default to avoid early bumps)
        use_ml = os.getenv("READINESS_USE_ML", "false").lower() in {"1", "true", "yes", "on"}
        if use_ml:
            try:
                scorer = _get_scorer()
                fx = {
                    "price_month":        parsed.get("price_month")        or 0,
                    "subscribers":        parsed.get("subscribers")        or 0,
                    "gross_margin":       parsed.get("gross_margin")       or 0,
                    "budget":             parsed.get("budget")             or 0,
                    "plan_months":        parsed.get("plan_months")        or 0,
                    "revenue":            parsed.get("revenue")            or 0,
                    "assets":             parsed.get("assets")             or 0,
                    "liabilities":        parsed.get("liabilities")        or 0,
                    "ebit":               parsed.get("ebit")               or 0,
                    "cash_flow_oper":     parsed.get("cash_flow_oper")     or 0,
                    "cac_payback_months": parsed.get("cac_payback_months") or 0,
                    "ltv":                parsed.get("ltv")                or 0,
                    "has_mrr": 1 if ("mrr" in metrics_ok or "arr" in metrics_ok) else 0,
                }
                ml = scorer.score(fx)
                ml_overall = int(
                    getattr(ml, "readiness_percent", None)
                    or (ml.get("readiness_percent") if isinstance(ml, dict) else 0)
                    or 0
                )
                if ml_overall:
                    overall = ml_overall
                    source = "ml"
                    ml_info = {"features": fx, "readiness_percent": ml_overall}
            except Exception:
                # keep heuristic if ML scorer fails
                pass

        result = {
            "percent": int(overall),
            "categories": categories_detail,
            "collected_data": collected_data,
            "source": source,
            "ml_info": ml_info,
            "heur_overall": int(heur_overall),
            "weighted_total": float(weighted_total),
            "total_weight": float(total_weight),
        }
        # expose the inputs in effect (after session + scenario overrides)
        result["effective_inputs"] = dict(parsed)
        result["parsed_inputs"] = dict(parsed)
        # scenario context (for UI state)
        try:
            result["active_scenario"] = sess.get("active_scenario")
            adopted = sess.get("adopted_scenarios") or {}
            result["has_adopted"] = bool(adopted)
            result["adopted_scenarios"] = adopted or None
            # convenience: active overrides object (no FE dictionary lookup needed)
            active = result.get("active_scenario")
            if active and isinstance(adopted, dict):
                result["active_overrides"] = adopted.get(active, {})

        except Exception:
            # keep readiness robust even if session fields are missing
            pass

        result["gate"] = _gate_from_categories(overall, categories_detail)


        # Persist a few handy fields to the session (optional but helpful)
        try:
            sess["collected_data"]   = collected_data
            sess["micro_elements"]   = session_micros
            sess["readiness"]        = int(result.get("percent", 0))
            sess["readiness_detail"] = result
        except Exception:
            pass
        # --- PROFILE SLOT GATE (step 2) ---
        try:
            # Use the same parsed dict assembled above (calc + session labels + scenario overrides)
            parsed_for_slots = dict(parsed)

            profile = detect_profile(cumulative_text, parsed_for_slots)
            missing_slots = _find_missing_slots_for_profile(parsed_for_slots, profile)

            obj = result  # readiness payload dict
            if isinstance(obj, dict):
                gate = dict(obj.get("gate") or {})
                gate["missing_slots"] = missing_slots
                if missing_slots:
                    gate["can_finish"] = False
                obj["gate"] = gate
        except Exception:
            pass


            # Keep gross_margin sane if present
            if "gross_margin" in effective_parsed:
                try:
                    gm = float(effective_parsed.get("gross_margin"))
                    effective_parsed["gross_margin"] = max(0.0, min(100.0, gm))
                except Exception:
                    pass

            profile = detect_profile(cumulative_text, effective_parsed)
            missing_slots = _find_missing_slots_for_profile(effective_parsed, profile)

            # Expose the effective inputs in the payload for debugging/clients
            try:
                result["parsed_inputs"] = dict(effective_parsed)
            except Exception:
                pass

            gate = dict(result.get("gate") or {})
            gate["missing_slots"] = missing_slots
            if missing_slots:
                gate["can_finish"] = False
            result["gate"] = gate
        except Exception:
            pass


        return result

    except Exception as e:
        current_app.logger.error(f"Readiness calculation error: {e}", exc_info=True)
        user_turns = len([m for m in sess.get("messages", []) if m.get("role") == "user"])
        fallback = min(100, user_turns * 10)
        return {
            "percent": fallback,
            "readiness_percent": fallback,
            "value": fallback,
            "status": "degraded",
            "error": str(e),
            "categories": [],
            "collected_data": sess.get("collected_data", {}),
        }
def _gate_from_categories(overall: int, categories_detail: list[dict]) -> dict:
    categories_dict = {row["key"]: int(row.get("percent", 0)) for row in (categories_detail or [])}

    # Configurable gate; enforce a hard minimum of 85%
    gate_percent = int(os.getenv("READINESS_GATE_PERCENT", "85"))
    required_csv = os.getenv(
        "REQUIRED_CATEGORIES",
        "business_description,target_market,revenue_model,financial_metrics,timeline,budget",
    )
    required = [s.strip() for s in required_csv.split(",") if s.strip()]
    min_required = {k: int(os.getenv(f"MIN_REQUIRED_{k}", "70")) for k in required}

    # A required category is unmet if it is below its per-category minimum
    unmet_required = [k for k in required if categories_dict.get(k, 0) < min_required.get(k, 70)]
    required_ok = (len(unmet_required) == 0)

    # Enforce floor of 85% regardless of env (use the higher of the two)
    GATE_MIN_PERCENT = 85
    threshold = max(gate_percent, GATE_MIN_PERCENT)

    can_finish = (int(overall) >= threshold) and required_ok

    return {
        "overall_percent": int(overall),
        "required_ok": required_ok,
        "can_finish": can_finish,
        "unmet_required": unmet_required,
    }

# --- Profile slot gate helpers (readiness step 2) ---
def _to_number(val):
    """Best-effort numeric coercion. Accepts '70%', '5,000', 5000, etc."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return None
    pct = s.endswith("%")
    s = s.replace(",", "").replace("$", "").replace("€", "").replace("£", "")
    try:
        num = float(s.rstrip("%"))
    except ValueError:
        return None
    return num if not pct else num  # keep 70 from "70%"

def _is_positive(n):
    return (n is not None) and (n > 0)

def _valid_gross_margin(n):
    # Accept 0–100 inclusive; typical sanity 0–100
    return n is not None and 0 <= n <= 100
def _slot_present_and_sane(slot: str, aliases: list, parsed: dict) -> bool:
    """
    Check if any alias for a slot exists in parsed with sane value.
    Accept both LabelCase (e.g., 'MRR', 'Gross_Margin') and snake_case (e.g., 'mrr', 'gross_margin').
    """
    def val_for(*keys):
        for k in keys:
            if k in parsed and parsed.get(k) not in (None, "", []):
                return parsed.get(k)
        return None

    # Map common snake_case equivalents for each alias
    snake_map = {
        "MRR": ["mrr", "monthly_revenue", "revenue_mrr"],
        "ARR": ["arr", "annual_revenue", "revenue_arr"],
        "Revenue": ["revenue", "revenue_monthly", "revenue_total"],
        "Gross_Margin": ["gross_margin", "gm"],
        "EBIT": ["ebit"],
        "Operating_Cash_Flow": ["operating_cash_flow", "ocf"],
        "Plan_Months": ["plan_months", "timeline_months"],
    }

    def any_alias_value(alias_list):
        # check LabelCase then known snake_case fallbacks
        for a in alias_list:
            v = val_for(a)
            if v is not None:
                return v
            for sk in snake_map.get(a, []):
                v2 = val_for(sk)
                if v2 is not None:
                    return v2
        return None

    if slot == "plan_window":
        v = any_alias_value(aliases)
        n = _to_number(v)
        return _is_positive(n)

    if slot == "revenue_run_rate":
        v = any_alias_value(aliases)  # MRR or ARR or Revenue
        n = _to_number(v)
        return _is_positive(n)

    if slot == "profitability":
        # Accept either Gross_Margin in [0..100] OR positive EBIT/OCF
        gm = any_alias_value(["Gross_Margin"])
        gm_n = _to_number(gm)
        if _valid_gross_margin(gm_n):
            return True
        ebit = any_alias_value(["EBIT"])
        ocf  = any_alias_value(["Operating_Cash_Flow"])
        return _is_positive(_to_number(ebit)) or _is_positive(_to_number(ocf))

    # Default conservative: any alias present (LabelCase or snake_case)
    v = any_alias_value(aliases)
    return v not in (None, "", [])

def _find_missing_slots_for_profile(parsed: dict, profile) -> list:
    """
    Returns list of {slot, options: [...]} where any-of aliases acceptable.
    """
    slots = get_profile_slots(profile)
    missing = []
    for slot, aliases in slots.items():
        if not _slot_present_and_sane(slot, aliases, parsed):
            missing.append({"slot": slot, "options": list(aliases)})
    return missing
def _format_profile_nudge(missing_slots: list) -> str | None:
    """Return one natural, persona-styled question for the first missing slot."""
    if not missing_slots:
        return None
    slot = (missing_slots[0] or {}).get("slot")
    if not slot:
        return None
    try:
        # Defer import to avoid circulars; phrase ask via Market IQ persona
        from flask import request
        from app.routes.market_iq import render_conversational_nudge

        # Light context from the current POST body (safe even without history)
        payload = request.get_json(silent=True) or {}
        last_user_msg = (payload.get("message") or "").strip() or None
        persona = f"{rendered_conversational_ai_prompt(slot, last_user_msg) or ''}".strip()
        # Build soft, human examples from provided options or slot defaults
        opts = (missing_slots[0] or {}).get("options") or []
        natural_map = {
            "MRR": "monthly revenue",
            "ARR": "annual revenue",
            "Revenue": "revenue",
            "Gross_Margin": "gross margin %",
            "EBIT": "profit (EBIT)",
            "Operating_Cash_Flow": "operating cash flow",
            "Plan_Months": "planning window (months)",
        }
        # Slot-level defaults when options are empty
        slot_examples = {
            "target_market": ["buyer role", "company size", "vertical", "geography"],
            "business_description": ["what the product does", "why customers choose it"],
            "revenue_model": ["pricing model", "tiers", "primary revenue streams"],
            "financial_metrics": ["monthly revenue", "annual revenue", "gross margin %", "profit (EBIT)"],
            "timeline": ["planning window (months)"],
            "budget": ["total budget"],
            "competition": ["top competitors", "key differentiators"],
            "team": ["key roles"],
            "revenue_run_rate": ["monthly revenue", "annual revenue"],
            "profitability": ["gross margin %", "profit (EBIT)", "operating cash flow"],
            "plan_window": ["planning window (months)"],
        }

        examples = [natural_map.get(o, o.replace("_", " ").lower()) for o in opts] or slot_examples.get(slot, [])
        examples = examples[:3]

        # Use persona only if it actually targets the slot/options; else prefer example-based ask
        def _mentions_any(text: str, words: list[str]) -> bool:
            t = (text or "").lower()
            return any(w and (w.lower() in t) for w in words)
        if persona:
            return persona  # accept persona phrasing even if keywords don't match

        # Natural, example-based ask
        if examples:
            if len(examples) == 1:
                return f"Could you share your {examples[0]}?"
            if len(examples) == 2:
                return f"Could you share your {examples[0]} or {examples[1]}?"
            joined = ", ".join(examples[:-1]) + f", or {examples[-1]}"
            return f"Could you share {joined}?"

        return f"Could you share a bit more about {str(slot).replace('_', ' ')}?"

        # Use persona only if it actually targets the slot/options; else prefer example-based ask
        def _mentions_any(text: str, words: list[str]) -> bool:
            t = (text or "").lower()
            return any(w and (w.lower() in t) for w in words)

        target_words = [slot.replace("_", " ")] + examples
        if persona and _mentions_any(persona, target_words):
            return persona

        # Natural, example-based ask
        if examples:
            if len(examples) == 1:
                return f"Could you share your {examples[0]}?"
            if len(examples) == 2:
                return f"Could you share your {examples[0]} or {examples[1]}?"
            joined = ", ".join(examples[:-1]) + f", or {examples[-1]}"
            return f"Could you share {joined}?"
        return f"Could you share a bit more about {str(slot).replace('_', ' ')}?"
    except Exception:
        # Generic, human fallback using soft examples from options (no tech labels)
        opts = (missing_slots[0] or {}).get("options") or []
        natural_map = {
            "MRR": "monthly revenue",
            "ARR": "annual revenue",
            "Revenue": "revenue",
            "Gross_Margin": "gross margin %",
            "EBIT": "profit (EBIT)",
            "Operating_Cash_Flow": "operating cash flow",
            "Plan_Months": "planning window (months)",
        }
        examples = [natural_map.get(o, o.replace("_", " ").lower()) for o in opts][:3]
        if examples:
            if len(examples) == 1:
                return f"Could you share your {examples[0]}?"
            if len(examples) == 2:
                return f"Could you share your {examples[0]} or {examples[1]}?"
            joined = ", ".join(examples[:-1]) + f", or {examples[-1]}"
            return f"Could you share {joined}?"
        return f"Could you share a bit more about {str(slot).replace('_', ' ')}?"

        return None


# Load .env early; systemd also injects env
load_dotenv(dotenv_path='/home/sekki/sekki-platform/backend/.env')

# Anthropic client / model from env (defaults to a stable "latest" alias)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL   = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
CLIENT: Optional[anthropic.Anthropic] = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

# File-backed sessions (shared by all Gunicorn workers)
SESS_DIR = Path(os.getenv("SESSION_DIR", "/home/sekki/sekki-platform/backend/runtime/sessions"))
SESS_DIR.mkdir(parents=True, exist_ok=True)

# History caps (avoid token bloat)
MAX_HISTORY_CHARS = int(os.getenv("MAX_HISTORY_CHARS", "20000"))
MAX_TOKENS        = int(os.getenv("ANTHROPIC_MAX_TOKENS", "1024"))
TEMPERATURE       = float(os.getenv("ANTHROPIC_TEMPERATURE", "0.2"))

SYSTEM_PROMPT = """You are Sekki's market analysis copilot. Be conversational and avoid repeating questions already answered in this session. Build on prior context to advance the analysis for sekki.io."""

conversational_ai_bp = Blueprint("conversational_ai", __name__)

from typing import Optional

def _get_or_create_session(sid: Optional[str]) -> dict:
    # prefer given sid; else try to derive from request; else new
    if not sid:
        try:
            sid = _sid_from_request()
        except Exception:
            sid = f"web_{os.urandom(6).hex()}"
    sess = _load_session(sid)
    sess["id"] = sess.get("id") or sid
    return sess


def _sid_from_request() -> str:
    # Prefer explicit header from the frontend, then cookie. Avoids api.<domain> vs www.<domain> cookie scope issues.
    sid = request.headers.get("X-Session-ID")
    if not sid:
        sid = request.cookies.get("sekki_sid")
    if not sid:
        sid = f"web_{os.urandom(6).hex()}"
    return sid

def _p(sid: str) -> Path:
    return SESS_DIR / f"{sid}.json"

def _load_session(sid: str) -> Dict[str, Any]:
    fp = _p(sid)
    if not fp.exists():
        return {"id": sid, "messages": [], "created_at": int(time.time())}
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except Exception as e:
        current_app.logger.error(f"session_load_error sid={sid}: {e}")
        return {"id": sid, "messages": [], "created_at": int(time.time())}

def _save_session(sess: Dict[str, Any]) -> None:
    sid = sess["id"]
    tmp = _p(f"{sid}.{int(time.time()*1000)}.tmp")
    dst = _p(sid)
    try:

        tmp.write_text(json.dumps(sess, ensure_ascii=False), encoding="utf-8")
        tmp.replace(dst)  # atomic
    except Exception as e:
        current_app.logger.error(f"session_save_error sid={sid}: {e}")
# --- Scenarios: adopt & activate (session-backed) -----------------------------
def _sess_scenarios(sess: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    """Return a copy of adopted scenarios (name -> overrides)."""
    try:
        sc = sess.get("adopted_scenarios") or {}
        return dict(sc) if isinstance(sc, dict) else {}
    except Exception:
        return {}

def _set_active_scenario(sess: Dict[str, Any], name: str) -> None:
    """Set the active scenario name and mirror its overrides into scenario_overrides."""
    if not isinstance(name, str) or not name.strip():
        return
    all_sc = _sess_scenarios(sess)
    ov = all_sc.get(name) or {}
    sess["active_scenario"] = name
    # Back-compat with compute_readiness(): it already applies sess["scenario_overrides"]
    sess["scenario_overrides"] = dict(ov)

def _clean_numeric_overrides(raw: Dict[str, Any]) -> Dict[str, float]:
    """Accept numbers or number-like strings (e.g., '250k', '$49', '65%')."""
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, float] = {}
    allowed = {
        "price_month", "plan_months", "budget", "gross_margin", "subscribers",
        "revenue", "mrr", "arr", "ebit", "operating_cash_flow",
    }
    for k, v in raw.items():
        if k not in allowed:
            continue
        if isinstance(v, (int, float)):
            out[k] = float(v)
            continue
        if isinstance(v, str):
            s = v.strip().replace(",", "").replace("$", "")
            mult = 1.0
            if s and s[-1].lower() in ("k", "m", "b"):
                suf = s[-1].lower()
                s = s[:-1]
                mult = 1e3 if suf == "k" else 1e6 if suf == "m" else 1e9
            s = s.rstrip("%")
            try:
                out[k] = float(s) * mult
            except Exception:
                pass
    # sanity for gross_margin % (keep 0..100)
    if "gross_margin" in out:
        out["gross_margin"] = max(0.0, min(100.0, float(out["gross_margin"])))
    return out

@conversational_ai_bp.route("/scenario/adopt", methods=["POST"])
def scenario_adopt() -> Any:
    """
    Adopt (or update) a named scenario and make it active.
    Body:
      {
        "name": "Promo39",             # optional; defaults to "Scenario_<epoch>"
        "overrides": { "price_month": 39, "plan_months": 6, ... }
      }
    Returns:
      { "ok": true,
        "active_scenario": "Promo39",
        "adopted_scenarios": { "Promo39": {...}, ... }
      }
    """
    try:
        sid = _sid_from_request()
        sess = _load_session(sid)
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or data.get("scenario") or f"Scenario_{int(time.time())}").strip()
        overrides_raw = data.get("overrides") or {}
        overrides = _clean_numeric_overrides(overrides_raw)

        # Store/update
        all_sc = _sess_scenarios(sess)
        all_sc[name] = overrides
        sess["adopted_scenarios"] = all_sc

        # Activate it and mirror into scenario_overrides
        _set_active_scenario(sess, name)

        _save_session(sess)
        try:
            current_app.logger.info("[scenario] %s -> %s %s", sid, name, overrides)
        except Exception:
            pass

        return jsonify({
            "ok": True,
            "active_scenario": name,
            "adopted_scenarios": sess.get("adopted_scenarios", {}),
        }), 200
    except Exception as e:
        current_app.logger.exception("scenario_adopt failed")
        return jsonify({"ok": False, "error": str(e)}), 500

def _trim_by_chars(history: List[Dict[str, str]], max_chars: int) -> List[Dict[str, str]]:
    total = 0
    out: List[Dict[str, str]] = []
    for m in reversed(history):
        c = m.get("content") or ""
        if total + len(c) > max_chars and out:
            break
        out.append(m)
        total += len(c)
    return list(reversed(out))


def _anthropic_reply(
    history: List[Dict[str, str]],
    ui_mode: str = "",
    ui_context: Optional[Dict[str, Any]] = None,
) -> tuple[str, List[Dict[str, Any]]]: 
    if not CLIENT:
        return "(server missing ANTHROPIC_API_KEY)", []
    # Trim what we SEND to Anthropic to keep costs predictable,
    # but keep full `history` for server-side reasoning (snap/collected).
    MAX_SEND_CHARS = int(os.getenv("ANTHROPIC_MAX_SEND_CHARS", "12000"))
    trimmed_history = _trim_by_chars(history, MAX_SEND_CHARS)

    msgs = [
        {"role": m.get("role"), "content": m.get("content", "")}
        for m in trimmed_history
        if m.get("role") in ("user", "assistant") and (m.get("content") or "").strip()
    ]

    try:
        current_app.logger.info(
            "[anthropic] send_chars=%d full_chars=%d msgs=%d model=%s",
            sum(len(m.get("content") or "") for m in msgs),
            sum(len(m.get("content") or "") for m in history),
            len(msgs),
            ANTHROPIC_MODEL,
        )
    except Exception:
        pass
    for _ in range(2):
        try:
            # --- Dynamic "nudge" to keep it conversational and avoid repeats ---
            dynamic_system = SYSTEM_PROMPT
            collected = {}
            # Load MarketIQ system prompt based on context
            try:
                from app.routes.market_iq import (
                    CONVERSATION_SYSTEM_PROMPT as MARKET_IQ_INTAKE,
                    SCORECARD_QA_SYSTEM_PROMPT as MARKET_IQ_SCORECARD_QA,
                    SCENARIOS_INTERNAL_SYSTEM_PROMPT as MARKET_IQ_SCENARIOS,
                    EXECUTION_INTERNAL_SYSTEM_PROMPT as MARKET_IQ_EXECUTION
                )
                
                # Detect which mode based on session status and conversation history
                session_status = sess.get("status", "in_progress")
                has_scorecard = sess.get("result") and isinstance(sess.get("result"), dict)
                
                # Check if user is asking about scenarios or execution
                recent_messages = history[-5:] if len(history) > 5 else history
                recent_text = " ".join([m.get("content", "") for m in recent_messages]).lower()

                if "scenario" in recent_text or "option" in recent_text or "alternative" in recent_text:
                    dynamic_system = MARKET_IQ_SCENARIOS
                elif "plan" in recent_text or "execution" in recent_text or "timeline" in recent_text:
                    dynamic_system = MARKET_IQ_EXECUTION
                elif session_status == "completed" or has_scorecard:
                    # User has a scorecard and is asking questions about it
                    dynamic_system = MARKET_IQ_SCORECARD_QA

                    # HARD GUARDRAIL: bind the assistant to the actual scorecard values.
                    # Do NOT allow it to invent or "remember" numbers from earlier.
                    try:
                        scorecard = sess.get("result") or {}
                        dynamic_system += (
                            "\n\nSOURCE OF TRUTH (scorecard):\n"
                            + json.dumps(scorecard, ensure_ascii=False)
                            + "\n\nRules:\n"
                            "- Use ONLY the numbers present in SOURCE OF TRUTH.\n"
                            "- If a number is not present, say you don’t have it.\n"
                            "- Do NOT guess, estimate, or reuse numbers from prior messages.\n"
                        )
                    except Exception:
                        pass

                # Check if user is asking about scenarios or execution
                recent_messages = history[-5:] if len(history) > 5 else history
                recent_text = " ".join([m.get("content", "") for m in recent_messages]).lower()
                
                if "scenario" in recent_text or "option" in recent_text or "alternative" in recent_text:
                    dynamic_system = MARKET_IQ_SCENARIOS
                elif "plan" in recent_text or "execution" in recent_text or "timeline" in recent_text:
                    dynamic_system = MARKET_IQ_EXECUTION
                elif session_status == "completed" or has_scorecard:
                    # User has a scorecard and is asking questions about it
                    dynamic_system = MARKET_IQ_SCORECARD_QA
                else:
                    # Default to intake mode
                    dynamic_system = MARKET_IQ_INTAKE
                    
            except Exception as e:
                # Fallback to default if imports fail
                dynamic_system = SYSTEM_PROMPT

            # Lazy import the collector (avoid circulars)
            try:
                from app.routes.market_iq import extract_collected_data as _extract_collected_data
            except Exception:
                _extract_collected_data = None

            # Build readiness snapshot (independent) + collected snapshot (optional)
            snap = {}
            try:
                snap = build_readiness_snapshot(history) or {}
            except Exception:
                snap = {}

            collected = {}
            if _extract_collected_data:
                try:
                    collected = _extract_collected_data(history) or {}
                except Exception:
                    collected = {}

            # compute focus keys from readiness snapshot (optional)
            missing = []
            try:
                gate = (snap.get("gate") or {})
                unmet = gate.get("unmet_required") or []
                if unmet:
                    missing = unmet[:2]
                else:
                    cats = (snap.get("categories") or [])
                    cats = sorted(cats, key=lambda c: c.get("percent", 0))
                    missing = [c.get("key") for c in cats[:2] if isinstance(c, dict)]
            except Exception:
                missing = []


            # Don't re-ask the project name if we already have it
            if collected.get("project_name_present"):
                dynamic_system += (
                    "\n\nNote: You already captured the project name; avoid asking for it again."
                )

            # Soft-prioritize the most valuable remaining gaps (no rigid script)
            _order = [
                "revenue_model",      # pricing / how money is made
                "market_size",        # TAM/SAM/SOM or simple sizing
                "cac_ltv",            # unit economics
                "value_prop",         # differentiators/value proposition
                "sales_channels",     # GTM channels
                "differentiators",    # competitive edge
                "team_roles",         # who executes
                "headcount",          # current/needed
                "timeline_window",    # delivery timeframe
                "budget_amount",      # budget clarity
                "discount_rate",      # for NPV guidance
                "industry_multiple",  # for valuation guidance
            ]
            _labels = {
                "revenue_model": "pricing & revenue model",
                "market_size": "market size/opportunity",
                "cac_ltv": "CAC/LTV (unit economics)",
                "value_prop": "value proposition",
                "sales_channels": "go-to-market channels",
                "differentiators": "competitive differentiators",
                "team_roles": "team roles/capabilities",
                "headcount": "headcount",
                "timeline_window": "timeline",
                "budget_amount": "budget",
                "discount_rate": "discount rate / hurdle rate",
                "industry_multiple": "industry EBITDA multiple",
            }
            missing = [k for k in _order if not collected.get(k)]
            if missing:
                focus = ", ".join(_labels.get(k, k) for k in missing[:2])
                dynamic_system += (
                    f"\n\nFocus next on: {focus}. "
                    "Ask one concise question that builds on what they already said, "
                    "and end with exactly ONE clear question."
                )

            # ---- Anthropic call with the dynamic system prompt ----

            # --- Interactive mode: allow model to emit structured UI intents ---
            if ui_mode == "interactive":
                try:
                    dynamic_system = (dynamic_system or "") + "\n\n" + interactive_system_suffix(ui_context or {})
                except Exception:
                    pass

            resp = CLIENT.messages.create(
                model=ANTHROPIC_MODEL,
                system=dynamic_system,          # <-- key change from SYSTEM_PROMPT
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                messages=msgs,
            )

            parts = []
            for blk in resp.content:
                if getattr(blk, "type", None) == "text":
                    parts.append(blk.text)
            text_out = ("".join(parts)).strip() or "(no content)"
            if ui_mode == "interactive":
                clean_text, intents = extract_ui_intents(text_out)
                return clean_text, intents
            return text_out, []
        except Exception as e:
            current_app.logger.warning(f"anthropic_call_failed: {e}")

    return "(anthropic error)", []

def _gap_aware_followup(snap: dict) -> str:
    """
    Return ONE targeted question.
    Rule: required-first via gate.unmet_required[0]; else lowest-percent category.
    """
    try:
        # 1) Required-first
        gate = snap.get("gate") or {}
        unmet = gate.get("unmet_required") or []
        prompts = {
            "business_description": "In 1–2 sentences, what problem/opportunity is this solving and what outcome do you want?",
            "target_market": "Who is the target customer and where? Include a count if relevant (e.g., Subscribers: 1000).",
            "revenue_model": "What is the pricing model? e.g., Price/Month: 49 and MRR: 5000.",
            "financial_metrics": "Please provide GM: <0–100%> and either EBIT: <amount> or Cash_Flow_Oper: <amount>.",
            "timeline": "What is the delivery timeline? e.g., Plan_Months: 6.",
            "budget": "What is the project budget? e.g., Budget: 250k.",
            # optional buckets
            "competition": "Who are the main competitors and how do you differ?",
            "team": "Who will execute this? Any key roles or experience?",
        }
        if unmet:
            k = unmet[0]
            return prompts.get(k, f"Tell me more about {k.replace('_',' ')}.")

        # 2) Otherwise, pick lowest-percent category
        cats = snap.get("categories") or []
        if not cats:
            return ""
        def _pct(c):
            try:
                return int(c.get("percent") or 0)
            except Exception:
                return 0
        worst = min(cats, key=_pct)
        k = (worst or {}).get("key", "")
        if not k:
            return ""
        return prompts.get(k, f"Tell me more about {k.replace('_',' ')}.")
    except Exception:
        return ""
# --- Readiness gate config (module-level constants; used by readiness endpoints) ---
def _next_best_gap(snap: dict) -> str:
    """
    Pick ONE targeted question to close the biggest gap.
    Prioritizes required categories first (those in gate.unmet_required),
    then any other incomplete category, both sorted by ascending percent.
    Returns "" if nothing useful is needed.
    """
    try:
        cats = snap.get("categories") or []
        gate = snap.get("gate") or {}
        required = set(gate.get("unmet_required") or [])
        prompts = {
            "business_description": "In 1–2 sentences, what problem/opportunity is this solving and what outcome do you want?",
            "target_market": "Who is the target customer and where? Include a count if relevant (e.g., Subscribers: 1000).",
            "revenue_model": "What is the pricing model? e.g., Price/Month: 49 and MRR: 5000.",
            "financial_metrics": "Please provide GM: <0–100%> and either EBIT: <amount> or Cash_Flow_Oper: <amount>.",
            "timeline": "What is the delivery timeline? e.g., Plan_Months: 6.",
            "budget": "What is the project budget? e.g., Budget: 250k.",
            "competition": "Who are the main competitors and how do you differ?",
            "team": "Who will execute this? Any key roles or experience?",
        }

        def _pct(c):
            try:
                return int(c.get("percent") or 0)
            except Exception:
                return 0
        # Tie-breaker priority (lower = earlier); allow override via env READINESS_PRIORITY
        import os
        default_order = ["budget", "timeline", "financial_metrics", "business_description",
                         "target_market", "revenue_model", "competition", "team"]
        env_order = os.getenv("READINESS_PRIORITY", "")
        order = [s.strip() for s in env_order.split(",") if s.strip()] or default_order
        priority = {k: i for i, k in enumerate(order)}

        def _rank(c):
            k = c.get("key")
            return (priority.get(k, 999), _pct(c))  # priority first, then percent

        # required-first, now with deterministic tie-breaks
        required_incomplete = sorted(
            [c for c in cats if (c.get("key") in required) and _pct(c) < 100],
            key=_rank,
        )
        other_incomplete = sorted(
            [c for c in cats if (c.get("key") not in required) and _pct(c) < 100],
            key=_rank,
        )

        pick = (required_incomplete or other_incomplete)
        if not pick:
            return ""

        key = (pick[0].get("key") or "").strip()

        # Try persona-driven, context-aware nudge first; fall back to static prompt
        nudge = _format_profile_nudge([{"slot": key, "options": []}])
        return (nudge or prompts.get(key, ""))
    except Exception:
        return ""

GATE_PERCENT = int(os.getenv("READINESS_GATE_PERCENT", "85"))

# Per-category minimums required to pass the gate.
# Only these categories must meet the listed minimums to enable "Finish & Analyze".
# Others may remain partial; we’ll keep them optional for the gate.
MIN_REQUIRED = {
    "business_description": 100,  # must clearly state what it is/does
    "target_market":        50,   # at least segment + geo
    "revenue_model":        100,  # clear pricing/revenue mechanics
    "financial_metrics":    33,   # at least one metric (e.g., MRR/ARR or margin)
    "budget":               100,  # budget keyword + numeric amount
    # "timeline":           100,  # <- uncomment if you decide timeline must be mandatory
    # competition/team remain optional for enabling the button
}

# --- Readiness snapshot (percent + categories) -------------------------------
def _all_required_met(snapshot: dict, min_required: dict) -> bool:
    """Return True if every required category meets its minimum percent."""
    cats = {c.get("key"): int(c.get("percent", 0) or 0) for c in (snapshot.get("categories") or [])}
    for key, minp in (min_required or {}).items():
        if cats.get(key, 0) < int(minp):
            return False
    return True
# --- Project plan generators --------------------------------------------------

def _make_plan_agile(duration_months: int = 6) -> dict:
    # 12 two-week sprints + kickoff, UAT, go-live
    tasks = [
        {"id": "A0", "name": "Project kickoff & scope confirmation", "type": "milestone", "duration_weeks": 1},
        {"id": "A1", "name": "Backlog setup & sizing",                "type": "activity",  "duration_weeks": 1},
    ]
    # 12 sprints
    for i in range(1, 13):
        tasks.append({"id": f"S{i}", "name": f"Sprint {i}", "type": "sprint", "duration_weeks": 2})
    tasks += [
        {"id": "A2", "name": "UAT & hardening", "type": "activity",  "duration_weeks": 1},
        {"id": "A3", "name": "Go-live & hypercare", "type": "milestone", "duration_weeks": 1},
    ]
    return {"style": "agile", "duration_months": duration_months, "tasks": tasks}


def _make_plan_waterfall(duration_months: int = 6) -> dict:
    # Classic phase gates; durations approximate a 6-mo window
    tasks = [
        {"id": "W0", "name": "Project kickoff",           "type": "milestone", "duration_weeks": 1},
        {"id": "W1", "name": "Discovery & requirements",  "type": "phase",     "duration_weeks": 3},
        {"id": "W2", "name": "Solution design",           "type": "phase",     "duration_weeks": 4},
        {"id": "W3", "name": "Build & integration",       "type": "phase",     "duration_weeks": 12},
        {"id": "W4", "name": "System & UAT testing",      "type": "phase",     "duration_weeks": 4},
        {"id": "W5", "name": "Deployment planning",       "type": "activity",  "duration_weeks": 1},
        {"id": "W6", "name": "Go-live",                   "type": "milestone", "duration_weeks": 1},
        {"id": "W7", "name": "Stabilization & handover",  "type": "phase",     "duration_weeks": 2},
    ]
    return {"style": "waterfall", "duration_months": duration_months, "tasks": tasks}


def _make_plan_hybrid(duration_months: int = 6) -> dict:
    # Hybrid: short discovery, then sprints, then formal UAT/go-live
    tasks = [
        {"id": "H0", "name": "Kickoff & scope",           "type": "milestone", "duration_weeks": 1},
        {"id": "H1", "name": "Discovery & solution shaping","type": "activity","duration_weeks": 3},
        {"id": "H2", "name": "Backlog & release planning","type": "activity",  "duration_weeks": 1},
    ]
    # 8 sprints (2 weeks each) ~ 16 weeks
    for i in range(1, 9):
        tasks.append({"id": f"HS{i}", "name": f"Sprint {i}", "type": "sprint", "duration_weeks": 2})
    tasks += [
        {"id": "H3", "name": "System/UAT",               "type": "phase",     "duration_weeks": 3},
        {"id": "H4", "name": "Go-live & hypercare",      "type": "milestone", "duration_weeks": 1},
    ]
    return {"style": "hybrid", "duration_months": duration_months, "tasks": tasks}


def next_readiness_gap(
    snapshot: dict,
    min_required: dict = None,
    gate_percent: int = None,
) -> dict:
    """
    Decide the single next gap to close, with a required-only bias first, then optional.
    Returns a dict describing the target category and the impact.

    Structure:
    {
      "key": "financial_metrics",
      "current_percent": 33,
      "target_percent": 50,          # the minimum needed if required, else toward 100
      "gap_type": "required_min" | "optional_to_100",
      "weighted_gain": 0.105,        # estimated boost to overall (0..1)
      "weight": 0.25,
      "reason": "Raising 'financial_metrics' from 33% to 50% satisfies required minimum."
    }

    If no meaningful gap remains (all required met and overall >= gate), returns {}.
    """
    if snapshot is None:
        return {}

    min_required = min_required if min_required is not None else (globals().get("MIN_REQUIRED") or {})
    gate_percent = int(gate_percent if gate_percent is not None else (globals().get("GATE_PERCENT") or 85))

    cats = snapshot.get("categories") or []
    overall = float(snapshot.get("percent", 0) or 0)

    # Build a weight lookup from the payload; fallback to MACRO_CATEGORIES if needed.
    weight_by_key = {}
    for c in cats:
        k = c.get("key")
        w = c.get("weight")
        if w is not None:
            weight_by_key[k] = float(w)
    if any(w is None for w in weight_by_key.values()) or len(weight_by_key) < len(cats):
        try:
            for k, cfg in (globals().get("MACRO_CATEGORIES") or {}).items():
                weight_by_key.setdefault(k, float(cfg.get("weight", 0.0)))
        except Exception:
            pass

    # Helper to read current percent safely
    def pct_of(key: str) -> int:
        for c in cats:
            if c.get("key") == key:
                return int(c.get("percent", 0) or 0)
        return 0

    # 1) If all required met AND overall >= gate, no gap to chase (button can show).
    if _all_required_met(snapshot, min_required) and overall >= gate_percent:
        return {}

    # 2) PRIORITY: Required categories that are below their minimum. Choose max weighted gain.
    best_req = None
    best_req_gain = -1.0
    for key, minp in (min_required or {}).items():
        cur = pct_of(key)
        if cur < int(minp):
            w = float(weight_by_key.get(key, 0.0))
            # Estimated overall lift if we take this category to its minimum
            gain = w * ((int(minp) - cur) / 100.0)
            if gain > best_req_gain:
                best_req_gain = gain
                best_req = {
                    "key": key,
                    "current_percent": cur,
                    "target_percent": int(minp),
                    "gap_type": "required_min",
                    "weighted_gain": round(gain, 6),
                    "weight": w,
                    "reason": f"Raising '{key}' from {cur}% to {int(minp)}% satisfies required minimum."
                }

    if best_req:
        return best_req

    # 3) OPTIONAL: If requireds are met (but overall < gate), push the single biggest weighted lift toward 100%.
    if _all_required_met(snapshot, min_required):
        best_opt = None
        best_opt_gain = -1.0
        for c in cats:
            key = c.get("key")
            cur = int(c.get("percent", 0) or 0)
            if cur >= 100:
                continue
            w = float(weight_by_key.get(key, 0.0))
            gain = w * ((100 - cur) / 100.0)
            if gain > best_opt_gain:
                best_opt_gain = gain
                best_opt = {
                    "key": key,
                    "current_percent": cur,
                    "target_percent": 100,
                    "gap_type": "optional_to_100",
                    "weighted_gain": round(gain, 6),
                    "weight": w,
                    "reason": f"Raising '{key}' from {cur}% toward 100% gives the largest weighted lift."
                }
        return best_opt or {}

    # 4) Fallback: If we get here, return the largest deficit among required anyway.
    best_any = None
    best_any_gain = -1.0
    for key, minp in (min_required or {}).items():
        cur = pct_of(key)
        if cur < int(minp):
            w = float(weight_by_key.get(key, 0.0))
            gain = w * ((int(minp) - cur) / 100.0)
            if gain > best_any_gain:
                best_any_gain = gain
                best_any = {
                    "key": key,
                    "current_percent": cur,
                    "target_percent": int(minp),
                    "gap_type": "required_min",
                    "weighted_gain": round(gain, 6),
                    "weight": w,
                    "reason": f"Raising '{key}' from {cur}% to {int(minp)}% satisfies required minimum."
                }
    return best_any or {}
@conversational_ai_bp.route("/scenario/list", methods=["GET"])
def scenario_list() -> Any:
    """
    Returns all adopted scenarios and which one is currently active.
    Shape:
    {
      "ok": true,
      "active_scenario": "Promo39" | null,
      "adopted": {
        "<name>": { ... numeric overrides ... }
      }
    }
    """
    try:
        sid = _sid_from_request()
        sess = _load_session(sid)

        active = sess.get("active_scenario")
        adopted = sess.get("adopted_scenarios") or {}

        return jsonify({
            "ok": True,
            "active_scenario": active,
            "adopted": adopted
        }), 200
    except Exception as e:
        current_app.logger.exception("scenario_list failed")
        return jsonify({"ok": False, "error": str(e)}), 500
@conversational_ai_bp.route("/scenario/state", methods=["GET"])
def scenario_state() -> Any:
    """
    Lightweight scenario state fetcher for the FE.
    Returns:
      - active_scenario (str|None)
      - adopted_scenarios (dict|None)
      - has_adopted (bool)
      - effective_inputs (dict)  # exactly what readiness uses
    Implementation calls compute_readiness(sess) to ensure consistency.
    """
    try:
        # Accept session id via header or querystring (same as /readiness)
        sid = request.headers.get("X-Session-ID") or request.args.get("sid")
        sess = _get_or_create_session(sid)

        # Reuse readiness logic to compute effective_inputs and scenario fields reliably
        snap = compute_readiness(sess) or {}

        return jsonify({
            "ok": True,
            "active_scenario":   snap.get("active_scenario"),
            "adopted_scenarios": snap.get("adopted_scenarios"),
            "has_adopted":       bool(snap.get("has_adopted")),
            "effective_inputs":  snap.get("effective_inputs") or {},
        }), 200
    except Exception as e:
        current_app.logger.exception("scenario_state failed")
        return jsonify({"ok": False, "error": str(e)}), 500
@conversational_ai_bp.route("/ideas/rank", methods=["POST"])
@rate_limit('chat', limit=20, window=60)
def ideas_rank() -> Any:
    """
    Batch-rank multiple ideas in one call (JSON only for step 1).
    Body:
      {
        "ideas": [
          {"title": "optional short name", "text": "the idea content..."},
          {"text": "another idea ..."}
        ],
        "top_n": 3
      }
    Returns readiness-based scores and a top-N recommendation.
    """
    try:
        data = request.get_json(silent=True) or {}
        ideas = data.get("ideas") or []
        top_n = int(data.get("top_n") or 3)
        if not isinstance(ideas, list) or not ideas:
            return jsonify({"ok": False, "error": "ideas (array) is required"}), 400

        results = []
        for idx, item in enumerate(ideas):
            if not isinstance(item, dict):
                continue
            title = (item.get("title") or f"Idea #{idx+1}").strip()
            text  = (item.get("text") or "").strip()

            if not text:
                results.append({
                    "index": idx,
                    "title": title,
                    "error": "empty text",
                    "score": 0,
                })
                continue

            # Build an isolated, throwaway session for this idea
            sid = f"batch_{uuid.uuid4().hex[:10]}"
            sess = {
                "id": sid,
                "messages": [{"role": "user", "content": text, "ts": int(time.time())}],
            }

            # Deterministic label parsing from the one-turn text
            try:
                parsed = _parse_slot_numbers(text) or {}
                if parsed:
                    sess["parsed_inputs"] = dict(parsed)
            except Exception:
                parsed = {}

            # Compute readiness using the same scoring pipeline as chat
            try:
                readiness = compute_readiness(sess) or {}
            except Exception as e:
                readiness = {"percent": 0, "error": str(e)}

            score = int(readiness.get("percent") or 0)

            # Keep the effective inputs visible for UI scorecards
            effective_inputs = dict(readiness.get("effective_inputs") or {})
            # Fallback: surface parsed if effective not present
            if not effective_inputs and parsed:
                effective_inputs = dict(parsed)

            results.append({
                "index": idx,
                "title": title,
                "score": score,
                "readiness": readiness,
                "effective_inputs": effective_inputs,
            })

        # Sort desc by score and clip top_n
        ranked = sorted(results, key=lambda r: int(r.get("score", 0)), reverse=True)
        top_n = max(1, min(top_n, len(ranked)))
        top = ranked[:top_n]

        # Human-friendly recommendation line
        rec_titles = ", ".join([t.get("title") for t in top])
        recommendation = f"I recommend: {rec_titles}" if rec_titles else "No valid ideas to recommend."

        body = {
            "ok": True,
            "count": len(results),
            "top_n": top_n,
            "ideas": ranked,          # full stack, sorted
            "top": top,               # top N with full detail
            "recommendation": recommendation,
        }
        return jsonify(body), 200

    except Exception as e:
        current_app.logger.exception("ideas_rank failed")
        return jsonify({"ok": False, "error": str(e)}), 500

@conversational_ai_bp.route('/readiness', methods=['GET'])
def get_readiness():
    from flask import request, jsonify, current_app
    try:
        # Accept session id via header or querystring
        sid = request.headers.get("X-Session-ID") or request.args.get("sid")

        # however you already do this elsewhere:
        sess = _get_or_create_session(sid)  # or your existing session getter

        # compute_readiness MUST return a plain dict (your ML-blended payload)
        payload = compute_readiness(sess)

        # optionally persist the last snapshot for convenience
        try:
            sess["readiness"] = payload.get("percent", 0)
            sess["readiness_detail"] = payload
        except Exception:
            pass
        return jsonify({"success": True, "readiness": payload, "gate": payload.get("gate", {})}), 200
    except Exception as e:
        current_app.logger.exception("readiness endpoint failed")
        return jsonify({
            "success": True,
            "readiness": payload,
            "gate": payload.get("gate", {}),
            "active_scenario": sess.get("active_scenario"),
            "adopted_scenarios": sess.get("adopted_scenarios", {}),
            "parsed_inputs": sess.get("parsed_inputs", {})
        }), 200
@conversational_ai_bp.route("/project/start", methods=["POST"])
def project_start() -> Any:
    """
    Creates a first-pass project plan from current session context.
    - Requires gate.can_finish == True (readiness sufficient)
    - Chooses simple style (agile vs waterfall) from text/profile
    - Builds a lightweight WBS sized by plan window (months)
    """
    try:
        sid = _sid_from_request()
        sess = _load_session(sid)

        # 1) Verify readiness gate
        snap = compute_readiness(sess) or {}
        gate = (snap.get("gate") or {})
        if not bool(gate.get("can_finish", False)):
            return jsonify({
                "ok": False,
                "error": "readiness gate not met",
                "gate": gate
            }), 400

        # 2) Build effective inputs (calculator -> session labels -> scenario overrides)
        try:
            cum_text = get_cumulative_user_text(sess) or ""
        except Exception:
            cum_text = ""

        try:
            calc = run_calculator(cum_text or "") or {}
        except Exception:
            calc = {}

        effective = dict((calc.get("inputs_parsed") or {}) if isinstance(calc, dict) else {})

        try:
            for k, v in (sess.get("parsed_inputs") or {}).items():
                if isinstance(v, (int, float)):
                    effective[k] = v
        except Exception:
            pass

        try:
            for k, v in (sess.get("scenario_overrides") or {}).items():
                if isinstance(v, (int, float)):
                    effective[k] = v
        except Exception:
            pass

        # normalize GM to 0..100 if present
        try:
            if "gross_margin" in effective and isinstance(effective["gross_margin"], (int, float)):
                gm = float(effective["gross_margin"])
                effective["gross_margin"] = max(0.0, min(100.0, gm))
        except Exception:
            pass
        # 3) Decide style + duration
        txt = (cum_text or "").lower()

        # duration: accept Plan_Months from effective; safe defaults
        try:
            duration_raw = float(effective.get("plan_months") or 6)
            duration_months = max(1, int(round(duration_raw)))
        except Exception:
            duration_months = 6

        # explicit style override if provided in parsed/scenario:
        # accept any of: project_style, style (case-insensitive) -> {"agile","waterfall","hybrid"}
        style_raw = None
        for k in ("project_style", "style"):
            v = effective.get(k)
            if isinstance(v, str) and v.strip():
                style_raw = v.strip().lower()
                break

        # text heuristics
        is_software    = bool(re.search(r"\b(software|app|platform|api|saas|copilot|ml|ai)\b", txt, re.I))
        mentions_agile = bool(re.search(r"\b(agile|sprints?|scrum|kanban)\b", txt, re.I))
        mentions_hyb   = bool(re.search(r"\b(hybrid|agile[- ]?waterfall|wagile)\b", txt, re.I))
        mentions_wf    = bool(re.search(r"\b(waterfall|phase[- ]based|stage[- ]gate)\b", txt, re.I))
        # choose style: explicit > heuristic
        if style_raw in {"agile", "waterfall", "hybrid"}:
            style = style_raw
        else:
            if mentions_hyb:
                style = "hybrid"
            elif is_software or mentions_agile:
                style = "agile"
            elif mentions_wf:
                style = "waterfall"
            else:
                # default: software-ish → agile, otherwise waterfall
                style = "agile" if is_software else "waterfall"

        # --- INSERT: style rationale (goes here) ---
        reasons = []
        if style_raw in {"agile", "waterfall", "hybrid"}:
            reasons.append(f"user override: {style_raw}")
        if is_software:
            reasons.append("software/AI keywords detected")
        if mentions_agile:
            reasons.append("user mentioned agile/sprints")
        if mentions_hyb:
            reasons.append("user mentioned hybrid/waterfall+agile")
        if mentions_wf:
            reasons.append("user mentioned waterfall")
        if not reasons:
            reasons.append("heuristic default")
        style_reason = ", ".join(reasons)
        # --- END INSERT ---
        # choose style: explicit > heuristic
        if style_raw in {"agile", "waterfall", "hybrid"}:
            style = style_raw
        else:
            if mentions_hyb:
                style = "hybrid"
            elif is_software or mentions_agile:
                style = "agile"
            elif mentions_wf:
                style = "waterfall"
            else:
                # default: software-ish → agile, otherwise waterfall
                style = "agile" if is_software else "waterfall"

        # --- build style rationale & source ---
        style_source = "heuristic"
        if style_raw in {"agile", "waterfall", "hybrid"}:
            style_source = "override"

        reasons = []
        if is_software:
            reasons.append("software/AI keywords detected")
        if mentions_agile:
            reasons.append("user mentioned agile/sprints")
        if mentions_wf:
            reasons.append("user mentioned waterfall")
        if mentions_hyb:
            reasons.append("user mentioned hybrid")
        if style_source == "override":
            reasons.append(f"user override: {style_raw}")

        if not reasons:
            reasons.append("heuristic default")
        style_reason = ", ".join(reasons)

        # 4) Generate a comprehensive WBS

        tasks = []
        weeks = max(1, duration_months * 4)

        # tiny helper to append tasks with consistent shape
        def _add(tid, name, ttype, duration_weeks=1, depends_on=None):
            task = {
                "id": tid,
                "name": name,
                "type": ttype,
                "duration_weeks": max(1, int(duration_weeks)),
            }
            if depends_on:
                task["depends_on"] = depends_on if isinstance(depends_on, list) else [depends_on]
            tasks.append(task)

        if style == "agile":
            # ---- Agile comprehensive plan ----
            # Assumptions: 2-week sprints; discovery, build, QA, demo, retro per sprint
            sprint_weeks = 2
            # reserve 2 weeks for init/charter/backlog & 1 week for UAT/launch
            reserve_weeks = 3
            agile_weeks = max(1, weeks - reserve_weeks)
            num_sprints = max(1, agile_weeks // sprint_weeks)

            # Pre-work & governance
            _add("A0.1", "Project charter & objectives", "activity", 1)
            _add("A0.2", "Stakeholder register & RACI", "activity", 1, depends_on="A0.1")
            _add("A0.3", "Kickoff meeting", "milestone", 1, depends_on=["A0.1", "A0.2"])
            _add("A0.4", "Backlog setup, sizing & prioritization", "activity", 1, depends_on="A0.3")
            _add("A0.5", "CI/CD pipeline baseline", "activity", 1, depends_on="A0.3")

            # Sprints
            for i in range(1, num_sprints + 1):
                sid = f"S{i}"
                # Each sprint’s internal flow
                _add(f"{sid}.1", f"Sprint {i} planning", "activity", 0.5, depends_on="A0.4" if i == 1 else f"S{i-1}.6")
                _add(f"{sid}.2", f"Sprint {i} discovery / grooming", "activity", 0.5, depends_on=f"{sid}.1")
                _add(f"{sid}.3", f"Sprint {i} build (dev)", "activity", 1,   depends_on=f"{sid}.2")
                _add(f"{sid}.4", f"Sprint {i} QA (unit + integration)", "activity", 0.5, depends_on=f"{sid}.3")
                _add(f"{sid}.5", f"Sprint {i} demo & stakeholder review", "milestone", 0.25, depends_on=f"{sid}.4")
                _add(f"{sid}.6", f"Sprint {i} retro & improvement actions", "activity", 0.25, depends_on=f"{sid}.5")

            # Hardening & launch
            _add("A1.1", "UAT planning & entry criteria", "activity", 0.5, depends_on=f"S{num_sprints}.6")
            _add("A1.2", "UAT execution & defect triage", "activity", 0.5, depends_on="A1.1")
            _add("A1.3", "Cutover plan & rollback", "activity", 0.25, depends_on="A1.2")
            _add("A1.4", "Training & enablement", "activity", 0.25, depends_on="A1.2")
            _add("A1.5", "Go-live", "milestone", 0.25, depends_on=["A1.3", "A1.4"])
            _add("A1.6", "Hypercare & stabilization", "activity", 0.75, depends_on="A1.5")
            _add("A1.7", "Project closeout & retrospective", "phase", 0.5, depends_on="A1.6")

        elif style == "hybrid":
            # ---- Hybrid comprehensive plan ----
            # 2/3 Agile sprints + 1/3 Waterfall closure phases
            sprint_weeks = 2
            # Reserve 3 weeks for governance (init, kickoff, backlog) and closure adjustments
            reserve_weeks = 3
            agile_weeks = max(1, int(round(weeks * (2.0 / 3.0))))
            agile_weeks = max(1, agile_weeks - reserve_weeks)
            num_sprints = max(1, agile_weeks // sprint_weeks)
            closure_weeks = max(1, weeks - (num_sprints * sprint_weeks) - reserve_weeks)

            # Initiation & planning (waterfall-ish)
            _add("H0.1", "Business case & charter", "activity", 1)
            _add("H0.2", "Stakeholders, RACI & comms plan", "activity", 1, depends_on="H0.1")
            _add("H0.3", "Solution outline & release plan", "activity", 1, depends_on=["H0.1", "H0.2"])
            _add("H0.4", "Kickoff", "milestone", 0.5, depends_on="H0.3")
            _add("H0.5", "Backlog setup & sizing", "activity", 0.5, depends_on="H0.4")

            # Agile sprints
            for i in range(1, num_sprints + 1):
                sid = f"HS{i}"
                _add(f"{sid}.1", f"Sprint {i} planning", "activity", 0.5, depends_on="H0.5" if i == 1 else f"HS{i-1}.6")
                _add(f"{sid}.2", f"Sprint {i} build", "activity", 1, depends_on=f"{sid}.1")
                _add(f"{sid}.3", f"Sprint {i} QA", "activity", 0.5, depends_on=f"{sid}.2")
                _add(f"{sid}.4", f"Sprint {i} demo", "milestone", 0.25, depends_on=f"{sid}.3")
                _add(f"{sid}.5", f"Sprint {i} retro", "activity", 0.25, depends_on=f"{sid}.4")
                _add(f"{sid}.6", f"Sprint {i} tech debt / stabilization", "activity", 0.5, depends_on=f"{sid}.5")

            # Waterfall-style closure
            phases = [
                ("System Integration & Perf test", 0.30),
                ("Pilot / Limited Launch",        0.35),
                ("Full Launch & Hypercare",       0.35),
            ]
            allocated = 0
            for idx, (name, pct) in enumerate(phases, start=1):
                dw = max(1, int(round(closure_weeks * pct)))
                allocated += dw
                _add(f"H1.{idx}", name, "phase", dw, depends_on=f"HS{num_sprints}.6")
            drift = allocated - closure_weeks
            if drift != 0:
                # adjust last phase for rounding drift
                tasks[-1]["duration_weeks"] = max(1, tasks[-1]["duration_weeks"] - drift)
            _add("H2.1", "Training & enablement", "activity", 1, depends_on=f"H1.{len(phases)}")
            _add("H2.2", "Operational handoff", "activity", 1, depends_on="H2.1")
            _add("H2.3", "Closeout & lessons learned", "phase", 1, depends_on="H2.2")

        else:
            # ---- Waterfall comprehensive plan ----
            # Allocate phases by proportion; each phase expands into detailed tasks
            phase_defs = [
                ("Initiation", 0.10, [
                    ("Business case & objectives", 0.4),
                    ("Stakeholder map & RACI",     0.3),
                    ("Charter & approval",         0.3),
                ]),
                ("Planning",   0.15, [
                    ("Requirements & scope baseline", 0.30),
                    ("WBS & schedule (critical path)",0.25),
                    ("Budget & resource plan",       0.20),
                    ("Risk register & mitigations",   0.15),
                    ("Comms plan & kickoff prep",     0.10),
                ]),
                ("Design",     0.20, [
                    ("Solution architecture",          0.30),
                    ("Data model & integrations",      0.25),
                    ("UX/UI flows & prototypes",       0.25),
                    ("Non-functional requirements",    0.20),
                ]),
                ("Build",      0.35, [
                    ("Backend services",               0.25),
                    ("Frontend / UI",                  0.20),
                    ("Data pipelines / ETL",           0.20),
                    ("Integrations (POS/ERP/etc.)",    0.20),
                    ("Env setup & CI/CD",              0.15),
                ]),
                ("Test",       0.15, [
                    ("Unit & integration testing",     0.30),
                    ("System / SIT",                   0.25),
                    ("Performance & security",         0.25),
                    ("UAT readiness & entry",          0.20),
                ]),
                ("Deploy",     0.05, [
                    ("Cutover & rollback plans",       0.45),
                    ("Training & enablement",          0.30),
                    ("Go-live & hypercare",            0.25),
                ]),
            ]

            # Expand phases & subtasks
            running_dep = None
            for pidx, (pname, ppct, subtasks) in enumerate(phase_defs, start=1):
                phase_weeks = max(1, int(round(weeks * ppct)))
                pid = f"W{pidx}"
                _add(pid, pname, "phase", phase_weeks, depends_on=running_dep)

                # subdivide phase into detailed activities (sum of proportions ≈ 1.0 of phase)
                alloc = 0
                for sidx, (sname, spct) in enumerate(subtasks, start=1):
                    sw = max(1, int(round(phase_weeks * spct)))
                    alloc += sw
                    sid = f"{pid}.{sidx}"
                    _add(sid, f"{pname}: {sname}", "activity", sw, depends_on=pid)

                # rounding drift adjustment on the last subtask
                drift = alloc - phase_weeks
                if drift != 0:
                    tasks[-1]["duration_weeks"] = max(1, tasks[-1]["duration_weeks"] - drift)

                running_dep = f"{pid}.{len(subtasks)}"  # next phase waits for last subtask

            # Closeout
            _add("W7", "Project closeout & lessons learned", "phase", 1, depends_on=running_dep)


        plan = {
            "style": style,
            "duration_months": duration_months,
            "tasks": tasks,
        }

        # 5) Persist plan to session so UI can fetch/display later
        try:
            sess["project_plan"] = plan
            _save_session(sess)
        except Exception:
            pass
        return jsonify({
            "ok": True,
            "plan": plan,
            "effective_inputs": effective,
            "gate": gate,
            # convenience preview fields
            "style": plan.get("style"),
            "style_source": style_source,
            "style_reason": style_reason,
            "duration_months": plan.get("duration_months"),
            "task_count": len(plan.get("tasks") or []),
        }), 200

    except Exception as e:
        current_app.logger.exception("project_start failed")
        return jsonify({"ok": False, "error": str(e)}), 500
@conversational_ai_bp.route("/project/plan", methods=["GET"])
def project_plan_get() -> Any:
    """
    Return the staged plan if present; otherwise fall back to the last committed project
    so the UI still has something to render after a cancel.
    """
    try:
        sid = _sid_from_request()
        sess = _load_session(sid)

        staged = sess.get("project_plan")
        committed = sess.get("project_current") or sess.get("project")

        if staged:
            return jsonify({"ok": True, "has_plan": True, "source": "staged", "plan": staged}), 200
        if committed:
            return jsonify({"ok": True, "has_plan": True, "source": "committed_fallback", "plan": committed}), 200

        return jsonify({"ok": True, "has_plan": False}), 200
    except Exception as e:
        current_app.logger.exception("project_plan_get failed")
        return jsonify({"ok": False, "error": str(e)}), 500
@conversational_ai_bp.route("/project/status", methods=["GET"])
def project_status() -> Any:
    """
    Read-only status for the current project/plan.
    Priorities:
      1) committed project (project_current / project)
      2) staged plan (project_plan)
    """
    try:
        sid = _sid_from_request()
        sess = _load_session(sid)

        committed = sess.get("project_current") or sess.get("project")
        staged    = sess.get("project_plan")

        if committed:
            tasks = committed.get("tasks") or []
            return jsonify({
                "ok": True,
                "has_project": True,
                "source": "committed",
                "project": {
                    "id": committed.get("id"),
                    "style": committed.get("style"),
                    "duration_months": committed.get("duration_months"),
                    "task_count": len(tasks),
                }
            }), 200

        if staged:
            tasks = staged.get("tasks") or []
            return jsonify({
                "ok": True,
                "has_project": False,
                "has_staged_plan": True,
                "source": "staged",
                "plan": {
                    "id": staged.get("id"),
                    "style": staged.get("style"),
                    "duration_months": staged.get("duration_months"),
                    "task_count": len(tasks),
                }
            }), 200

        # Nothing found
        return jsonify({
            "ok": True,
            "has_project": False,
            "has_staged_plan": False,
            "source": "none",
            "project": None,
            "plan": None
        }), 200
    except Exception as e:
        current_app.logger.exception("project_status failed")
        return jsonify({"ok": False, "error": str(e)}), 500

@conversational_ai_bp.route("/project/validate", methods=["POST"])
def project_validate() -> Any:
    """
    Commit the staged plan to a durable 'project_current' (and 'project' for legacy reads).
    Ensures tasks/style/duration are preserved so /project/plan fallback returns a full plan.
    """
    try:
        sid = _sid_from_request()
        sess = _load_session(sid)

        staged = sess.get("project_plan")
        if not staged:
            return jsonify({"ok": False, "error": "no staged plan to validate"}), 400

        # Make a deep-ish copy to avoid accidental mutation later
        committed = {
            "id": staged.get("id") or f"proj_{uuid.uuid4().hex[:10]}",
            "style": staged.get("style"),
            "duration_months": staged.get("duration_months"),
            "tasks": list(staged.get("tasks") or []),
        }

        # If style/duration missing, infer from readiness/session when possible
        if not committed.get("style"):
            # Default to agile if plan_months present; else fallback waterfall
            try:
                parsed = dict(sess.get("parsed_inputs") or {})
                committed["style"] = "agile" if parsed.get("plan_months") else "waterfall"
            except Exception:
                committed["style"] = "waterfall"
        if not committed.get("duration_months"):
            try:
                parsed = dict(sess.get("parsed_inputs") or {})
                pm = parsed.get("plan_months")
                committed["duration_months"] = int(pm) if isinstance(pm, (int, float)) and pm > 0 else None
            except Exception:
                committed["duration_months"] = None

        # Persist in session (new + legacy keys)
        sess["project_current"] = committed
        sess["project"] = committed  # legacy readers
        # Clear the staged plan after commit
        sess.pop("project_plan", None)

        _save_session(sess)
        return jsonify({
            "ok": True,
            "project": {
                "id": committed["id"],
                "style": committed["style"],
                "duration_months": committed["duration_months"],
                "task_count": len(committed["tasks"]),
            }
        }), 200
    except Exception as e:
        current_app.logger.exception("project_validate failed")
        return jsonify({"ok": False, "error": str(e)}), 500
@conversational_ai_bp.route("/project/current", methods=["GET"])
def project_current() -> Any:
    """
    Return the most recently validated/committed project (if any).
    Does not include a staged plan; use /project/plan for that.
    """
    try:
        sid = _sid_from_request()
        sess = _load_session(sid)

        proj = sess.get("project_committed")
        if proj:
            return jsonify({"ok": True, "project": proj, "has_project": True}), 200
        else:
            return jsonify({"ok": True, "project": None, "has_project": False}), 200

    except Exception as e:
        current_app.logger.exception("project_current failed")
        return jsonify({"ok": False, "error": str(e)}), 500
@conversational_ai_bp.route("/project/cancel", methods=["POST"])
def project_plan_cancel() -> Any:
    """
    Cancel the staged plan only. Do NOT remove the last committed project.
    """
    try:
        sid = _sid_from_request()
        sess = _load_session(sid)

        # Drop only the in-progress/staged plan
        if "project_plan" in sess:
            sess.pop("project_plan", None)

        _save_session(sess)
        return jsonify({"ok": True, "canceled": True}), 200
    except Exception as e:
        current_app.logger.exception("project_plan_cancel failed")
        return jsonify({"ok": False, "error": str(e)}), 500

@conversational_ai_bp.route("/health", methods=["GET"])
def health() -> Any:
    return jsonify({"ok": True, "model": ANTHROPIC_MODEL, "client": bool(CLIENT)}), 200
@conversational_ai_bp.route("/health/routes", methods=["GET"])
def health_routes() -> Any:
    """
    Lists registered routes in this blueprint and flags duplicates.
    Use in CI/CD to guard against accidental duplicate endpoints.
    """
    try:
        # Collect rules belonging to this blueprint only
        rules = []
        for rule in current_app.url_map.iter_rules():
            if rule.endpoint.startswith(f"{conversational_ai_bp.name}."):
                rules.append({
                    "rule": str(rule),
                    "methods": sorted(m for m in rule.methods if m not in {"HEAD", "OPTIONS"}),
                    "endpoint": rule.endpoint,
                })

        # Detect duplicates by path + sorted methods
        seen = {}
        duplicates = []
        for r in rules:
            key = (r["rule"], tuple(r["methods"]))
            if key in seen:
                duplicates.append({"a": seen[key], "b": r})
            else:
                seen[key] = r

        return jsonify({
            "ok": True,
            "blueprint": conversational_ai_bp.name,
            "count": len(rules),
            "duplicates": duplicates,
            "routes": rules,
        }), 200
    except Exception as e:
        current_app.logger.exception("health_routes failed")
        return jsonify({"ok": False, "error": str(e)}), 500

# --- explicit label parser: pulls numbers from one user turn ---
def _parse_slot_numbers(text: str) -> dict:
    """
    Tolerant one-turn parser. Accepts:
      - Labels with spaces/_/dashes, any case (e.g., "price month", "Gross-Margin")
      - Delimiters ":" or "="
      - Numbers with optional "$", commas, "%", and k/m/b suffix
    Canonical output keys (snake_case): price_month, plan_months, budget, gross_margin, mrr, arr,
    revenue, ebit, operating_cash_flow, subscribers.
    """
    out: dict[str, float] = {}
    if not isinstance(text, str) or not text:
        return out

    # Map many label variants → canonical snake_case
    CANON: dict[str, str] = {
        "price_month": "price_month",
        "price_per_month": "price_month",
        "price_monthly": "price_month",
        "plan_month": "plan_months",
        "plan_months": "plan_months",
        "mrr": "mrr",
        "arr": "arr",
        "revenue": "revenue",
        "ebit": "ebit",
        "operating_cash_flow": "operating_cash_flow",
        "cash_flow_oper": "operating_cash_flow",
        "gross_margin": "gross_margin",
        "gm": "gross_margin",
        "budget": "budget",
        "subscribers": "subscribers",
        "users": "subscribers",
        "seats": "subscribers",
    }

    # Label + delimiter + number (with $, %, k/m/b)
    pat = re.compile(
        r"""(?mi)^\s*
            (?P<label>[A-Za-z][A-Za-z _\-]*?)
            \s*[:=]\s*
            (?P<num>
                \$?\s*[0-9][0-9,\.]*\s*%?
                (?:\s*[kmbKMB])?
            )
            \s*$
        """,
        re.VERBOSE,
    )

    def _canon_label(label: str) -> Optional[str]:
        norm = re.sub(r"[\s\-]+", "_", label.strip().lower())
        return CANON.get(norm)

    def _to_float(token: str, is_percent: bool = False) -> Optional[float]:
        s = token.strip().replace(",", "").replace("$", "")
        mult = 1.0
        if s and s[-1].lower() in ("k", "m", "b"):
            suffix = s[-1].lower()
            s = s[:-1]
            mult = 1e3 if suffix == "k" else 1e6 if suffix == "m" else 1e9
        s = s.rstrip("%")
        try:
            val = float(s) * mult
            return val
        except ValueError:
            return None
    # debug: begin scan
    try:
        current_app.logger.info("[parse-slots][fn] scanning...")
    except Exception:
        pass

    for m in pat.finditer(text):
        key = _canon_label(m.group("label"))
        if not key:
            continue
        raw = m.group("num")
        is_pct = "%" in raw
        val = _to_float(raw, is_percent=is_pct)
        if val is None:
            continue
        if key == "gross_margin" and is_pct:
            out["gross_margin"] = val  # why: keep 0–100 scale if % provided
        else:
            out[key] = val
        try:
            current_app.logger.info("[parse-slots][fn] hit label=%s raw=%s val=%s", key, raw, val)
        except Exception:
            pass

    return out

    # Canonical alias map (normalize spaces/dashes/underscores + lowercase)
    ALIASES = {
        "price_month": "Price_Month",
        "price_per_month": "Price_Month",
        "plan_months": "Plan_Months",
        "plan_month": "Plan_Months",
        "mrr": "MRR",
        "arr": "ARR",
        "revenue": "Revenue",
        "ebit": "EBIT",
        "operating_cash_flow": "Operating_Cash_Flow",
        "gross_margin": "Gross_Margin",
        "gm": "Gross_Margin",
        "budget": "Budget",
        "subscribers": "Subscribers",
    }

    # Label: number (allow %, commas)
    pattern = r'(?mi)^\s*([A-Za-z][A-Za-z _\-]*)\s*:\s*([0-9][0-9,\.%]*)\s*$'
    for m in re.finditer(pattern, text):
        key_raw = m.group(1)
        val_raw = m.group(2)

        # normalize key to lookup form
        norm = re.sub(r'[\s\-]+', '_', key_raw.strip().lower())
        canon = ALIASES.get(norm)
        if not canon:
            continue

        ntxt = val_raw.replace(",", "")
        try:
            if canon == "Gross_Margin":
                # accept "70%" or "70"
                out["gross_margin"] = float(ntxt.rstrip("%"))
            elif canon == "Price_Month":
                out["price_month"] = float(ntxt)
            elif canon == "Plan_Months":
                out["plan_months"] = float(ntxt)
            elif canon == "Subscribers":
                out["subscribers"] = float(ntxt)
            elif canon in ("MRR", "ARR", "Revenue", "EBIT", "Operating_Cash_Flow", "Budget"):
                out[canon] = float(ntxt)
        except Exception:
            # ignore malformed numbers; continue scanning
            pass

    return out

def build_ui_actions(user_text: str) -> dict:
    """
    Lightweight UI-action parser.
    Returns a dict the frontend can interpret (Interactive-like “do this UI thing”).
    """
    if not isinstance(user_text, str):
        return {}

    t = user_text.strip().lower()

    # Example intent:
    # "update the table to say maybe and funding needed"
    # You can make this more robust later.
    if "update the table" in t and "maybe" in t and "funding needed" in t:
        return {
            "type": "SCORECARD_UPDATE_FIELD",
            "payload": {
                "section": "decision_framework",
                "rowLabel": "Overall Recommendation",
                "updates": {
                    "decision": "Maybe",
                    "notes": "Funding Needed",
                },
            },
        }

    return {}

@conversational_ai_bp.route("/chat", methods=["POST"])
@rate_limit('chat', limit=20, window=60)
def chat() -> Any:
    # --- robust request extraction (JSON, form, raw) ---
    try:
        raw_body = request.get_data(as_text=True)  # why: exact bytes from nginx/gunicorn
    except Exception:
        raw_body = ""
    # 0) Absolute fast-path: accept ?message=... or form message immediately
    user_text_raw = None
    try:
        _val_msg = request.values.get("message")  # covers args + form
        if isinstance(_val_msg, str) and _val_msg.strip():
            user_text_raw = _val_msg.strip()
            try:
                current_app.logger.info("[chat] values message<= %s", user_text_raw[:160])
            except Exception:
                pass
    except Exception:
        pass

    # 1) Try Flask JSON first (may be {} silently)
    data = request.get_json(silent=True) or {}
    # --- canonical session/thread id (single thread across all surfaces) ---
    import uuid

    sid = (
        request.headers.get("X-Session-ID")
        or data.get("session_id")
        or data.get("sid")
        or request.cookies.get("sekki_sid")
        or ""
    ).strip()

    if not sid:
        sid = f"web_{uuid.uuid4().hex[:12]}"

    thread_id = (data.get("thread_id") or sid).strip()

    # normalize into payload so downstream code uses one identity
    data["session_id"] = sid
    data["thread_id"] = thread_id
    # --- persist inbound user message so refresh can hydrate sidebar/history ---
    try:
        from app import db
        from app.models import MiqMessage

        if isinstance(user_text_raw, str) and user_text_raw.strip():
            db.session.add(MiqMessage(
                thread_id=thread_id,
                role="user",
                content={"text": user_text_raw.strip()},
                meta={
                    "sid": sid,
                    "surface": data.get("surface") or data.get("docType") or "market_iq",
                    "channel": data.get("channel") or "intake",
                },
            ))
            db.session.commit()
    except Exception as e:
        try:
            current_app.logger.exception("[chat] MiqMessage(user) persist failed")
            db.session.rollback()
        except Exception:
            pass

    # 2) If JSON looks empty but raw body exists, try manual json.loads
    if (not isinstance(data, dict) or not data) and isinstance(raw_body, str) and raw_body.strip():
        try:
            import json as _json
            data = _json.loads(raw_body)
        except Exception:
            pass  # keep data as-is
    # 2b) If still empty, extract "message" via regex from raw_body (handles odd proxies)
    if (not isinstance(data, dict) or not data) and isinstance(raw_body, str) and '"message"' in raw_body:
        try:
            import re, json as _json
            m = re.search(r'"message"\s*:\s*"(.*?)"', raw_body, re.S)
            if m:
                _raw = m.group(1)
                # unescape \n, \t, etc.
                _raw = bytes(_raw, "utf-8").decode("unicode_escape")
                user_text_raw = _raw.strip()
                try:
                    current_app.logger.info("[chat] regex message<= %s", user_text_raw[:160])
                except Exception:
                    pass
        except Exception:
            pass

    # 3) Hard fast-path: direct "message" from JSON or form
    if isinstance(data, dict):
        _msg = data.get("message")
        if isinstance(_msg, str) and _msg.strip():
            user_text_raw = _msg.strip()

    # Interactive parameters (used to enable intent output)
    ui_mode = (data.get("ui_mode") or "").strip().lower()
    ui_context = data.get("ui_context") if isinstance(data.get("ui_context"), dict) else {}
    if user_text_raw is None:
        try:
            _form_msg = request.form.get("message")
            if isinstance(_form_msg, str) and _form_msg.strip():
                user_text_raw = _form_msg.strip()
        except Exception:
            pass
    # 4) Fallback: use extractors if still empty (and log)
    if user_text_raw is None:
        try:
            current_app.logger.info(
                "[chat] payload keys=%s body_len=%s",
                (list(data.keys()) if isinstance(data, dict) else type(data).__name__),
                (len(raw_body) if isinstance(raw_body, str) else "n/a"),
            )
        except Exception:
            pass

        user_text_raw = extract_user_text(data)
        if (not isinstance(user_text_raw, str)) or (not user_text_raw.strip()) or (user_text_raw.strip() == "{}"):
            try:
                current_app.logger.info("[chat] extractor empty -> using local _extract_user_text")
            except Exception:
                pass
            user_text_raw = _extract_user_text(data)

        # Last-resort: accept plain-text body if not JSON
        if ((not isinstance(user_text_raw, str)) or (not user_text_raw.strip())) and isinstance(raw_body, str):
            if raw_body.strip() and not raw_body.strip().startswith("{"):
                user_text_raw = raw_body.strip()
    
    ui_actions = []

    ui_mode = ui_mode if isinstance(ui_mode, str) else ""
    ui_context = ui_context if isinstance(ui_context, dict) else {}

    # 6) Normalize and log preview
    if isinstance(user_text_raw, str):
        user_text_raw = user_text_raw.replace("\r\n", "\n").strip()

        ui_actions = build_ui_actions(user_text_raw)

        # Normalize to Interactive-style list of actions
        if isinstance(ui_actions, dict):
            ui_actions = [ui_actions] if ui_actions else []
        elif not isinstance(ui_actions, list):
            ui_actions = []

        # Keep only well-formed actions
        ui_actions = [
            a for a in ui_actions
            if isinstance(a, dict) and isinstance(a.get("type"), str) and a.get("type").strip()
        ]

        try:
            current_app.logger.info("[chat] raw<= %s", user_text_raw[:160])
        except Exception:
            pass

    if not user_text_raw:
        return jsonify({"error": "message is required"}), 400


    system_preamble = _ctx_preamble()
    user_text = user_text_raw
    if system_preamble and isinstance(user_text, str):
        user_text = "[CONTEXT]\n" + system_preamble + "\n\n" + user_text

    sid = _sid_from_request()
    sess = _load_session(sid)

    # Append user turn
    sess.setdefault("messages", []).append({"role": "user", "content": user_text, "ts": int(time.time())})
    # Parse explicit slot labels from this user turn and merge into session
    try:
        # debug: show exactly what we parse (first 500 chars)
        current_app.logger.info("[parse-slots] raw <= %s", (user_text_raw[:500] if isinstance(user_text_raw, str) else type(user_text_raw).__name__))
        slot_vals = _parse_slot_numbers(user_text_raw)
        current_app.logger.info("[parse-slots] out => %s", slot_vals)

        if slot_vals:
            sess.setdefault("parsed_inputs", {})
            sess["parsed_inputs"].update(slot_vals)
            current_app.logger.info("[parse-slots] merged => %s", sess.get("parsed_inputs"))
        else:
            current_app.logger.info("[parse-slots] no-matches")
    except Exception as exc:
        current_app.logger.exception("parse-slots failed: %r", exc)

    # Trim and get reply
    history = _trim_by_chars(sess["messages"], MAX_HISTORY_CHARS)
    reply, model_ui_intents = _anthropic_reply(history, ui_mode=ui_mode, ui_context=ui_context)
    # Merge model-emitted intents (interactive mode) with any rule-based actions
    try:
        if isinstance(model_ui_intents, list) and model_ui_intents:
            if not isinstance(ui_actions, list):
                ui_actions = []
            ui_actions = ui_actions + [a for a in model_ui_intents if isinstance(a, dict)]
    except Exception:
        pass
    # --- Normalize scenario actions (so frontend can execute them) ---
    fixed = []
    wants_run = False
    wants_adopt = False
    try:
        lt = user_text_raw.lower() if isinstance(user_text_raw, str) else ""
        wants_run = ("run scenario" in lt) or lt.strip().startswith("run ")
        wants_adopt = ("adopt scenario" in lt) or lt.strip().startswith("adopt ")
    except Exception:
        wants_run = False
        wants_adopt = False

    selected_scenario = None  # "A" / "B"

    for a in (ui_actions or []):
        if not isinstance(a, dict):
            continue

        t = (a.get("type") or "").strip()
        p = a.get("payload") or {}

        if not isinstance(p, dict):
            fixed.append(a)
            continue

        # 1) If payload explicitly targets a scenario lever, map to SCENARIO_SET_INPUT
        if p.get("scenario") and t == "SCORECARD_UPDATE_FIELD":
            selected_scenario = str(p.get("scenario")).strip() or selected_scenario
            a = {**a, "type": "SCENARIO_SET_INPUT"}
            fixed.append(a)
            continue

        # 2) If model used activeScenario field, treat it as selecting a scenario
        if t == "SCORECARD_UPDATE_FIELD" and p.get("field") == "activeScenario":
            selected_scenario = str(p.get("value")).strip() or selected_scenario
            fixed.append({"type": "SCENARIO_SELECT", "payload": {"scenario": selected_scenario}})
            continue

        fixed.append(a)

    # 3) If user asked to run/adopt, emit actions (and select scenario if we can infer it)
    if wants_run or wants_adopt:
        if not selected_scenario:
            txt = (user_text_raw or "").upper() if isinstance(user_text_raw, str) else ""
            if "SCENARIO A" in txt or txt.strip().endswith(" A"):
                selected_scenario = "A"
            elif "SCENARIO B" in txt or txt.strip().endswith(" B"):
                selected_scenario = "B"

        if selected_scenario:
            fixed.append({"type": "SCENARIO_SELECT", "payload": {"scenario": selected_scenario}})

        if wants_run:
            fixed.append({"type": "SCENARIO_RUN", "payload": {"scenario": selected_scenario}})
        if wants_adopt:
            fixed.append({"type": "SCENARIO_ADOPT", "payload": {"scenario": selected_scenario}})

    ui_actions = fixed

    prev = sess.get("readiness_detail") or {}

    # PHASE 1: Single, comprehensive readiness calculation
    readiness = compute_readiness(sess) or {}

    # Progress (compact)
    progress = None  # always defined
    try:
        prev_detail = prev if isinstance(prev, dict) else {}

        def _pct_map(rows):
            out = {}
            if isinstance(rows, list):
                for r in rows:
                    if isinstance(r, dict):
                        k = r.get("key")
                        if isinstance(k, str):
                            try:
                                out[k] = int(r.get("percent", 0))
                            except Exception:
                                out[k] = 0
            return out

        before_overall = int(
            prev_detail.get("percent")
            or prev_detail.get("readiness_percent")
            or 0
        )
        after_overall  = int(readiness.get("percent") or 0)

        before_map = _pct_map(prev_detail.get("categories"))
        after_map  = _pct_map(readiness.get("categories"))

        improved = []
        for k, newp in after_map.items():
            oldp = int(before_map.get(k, 0))
            if newp > oldp:
                improved.append({"key": k, "from": oldp, "to": newp, "delta": newp - oldp})

        gate = readiness.get("gate") or {}
        progress = {
            "overall_prev": before_overall,
            "overall_new":  after_overall,
            "overall_delta": after_overall - before_overall,
            "improved_categories": improved,
            "unmet_required": gate.get("unmet_required", []),
            "can_finish": bool(gate.get("can_finish", False)),
        }
    except Exception:
        current_app.logger.exception("progress block failed")
        progress = None

    # Single-nudge until gate.can_finish == True (required-first)
    try:
        gate = readiness.get("gate") or {}
        can_finish = bool(gate.get("can_finish", False))
    except Exception:
        can_finish = False
    # Let Claude respond naturally - no hardcoded question override
    # The AI will ask follow-up questions conversationally based on context

    # Note: Session is already updated inside compute_readiness()

    # Append assistant turn and persist
    sess["messages"].append({"role": "assistant", "content": reply, "ts": int(time.time())})
    _save_session(sess)
    # Echo parsed numeric inputs back to the client for validation
    # Merge calculator outputs with session-parsed labels (session wins)
    try:
        txt = get_cumulative_user_text(sess) or ""
    except Exception:
        txt = ""

    try:
        _calc0 = run_calculator(txt or "") or {}
        calc_parsed = (_calc0.get("inputs_parsed") or {}) if isinstance(_calc0, dict) else {}
    except Exception:
        calc_parsed = {}

    sess_parsed = {}
    try:
        sess_parsed = dict(sess.get("parsed_inputs") or {})
    except Exception:
        sess_parsed = {}

    # session overrides calculator
    parsed_inputs = dict(calc_parsed)
    try:
        parsed_inputs.update(sess_parsed)
    except Exception:
        pass

    # Validate presence of unit-tagged inputs (deterministic parsing)
    required_tags = {
        "Budget": ("budget:", "budget", "capex", "investment"),
        "Gross_Margin": ("gm:", "gross margin", "gross_margin", "gm"),
        "Plan_Months": ("plan_months:", "plan months", "plan_months", "months"),
    }

    def _has_any_label(labels: tuple[str, ...]) -> bool:
        low = txt.lower()
        return any(lbl.lower() in low for lbl in labels)

    missing_units = []
    # Budget: numeric and explicitly tagged
    if not (isinstance(parsed_inputs.get("budget"), (int, float)) and parsed_inputs.get("budget", 0) > 0 and _has_any_label(required_tags["Budget"])):
        missing_units.append("Budget (e.g., Budget: 250k)")
    # Gross Margin: 0–100% and explicitly tagged
    gm = parsed_inputs.get("gross_margin")
    if not (isinstance(gm, (int, float)) and 0 <= gm <= 100 and _has_any_label(required_tags["Gross_Margin"])):
        missing_units.append("Gross_Margin (e.g., GM: 65%)")
    # Plan Months: positive int/float and explicitly tagged
    pm = parsed_inputs.get("plan_months")
    if not (isinstance(pm, (int, float)) and pm > 0 and _has_any_label(required_tags["Plan_Months"])):
        missing_units.append("Plan_Months (e.g., Plan_Months: 6)")
    # Build response
    body = {
        "session_id": sid,
        "reply": reply,
        "ui_actions": ui_actions,
        "actions": ui_actions,
        "readiness": readiness,
        "readiness_percent": readiness.get("percent"),
        "gate": (readiness.get("gate") or {
            "overall_percent": int(readiness.get("percent") or 0),
            "required_ok": False,
            "can_finish": False,
            "unmet_required": [],
        }),
        "collected_data": sess.get("collected_data", {}),
        "parsed_inputs": parsed_inputs,
        "missing_units": missing_units,
        "progress": progress
    }

    # Gate-driven locks for the UI
    gate = (body.get("gate") or {})
    body["locks"] = {
        "allow_finish":   bool(gate.get("can_finish", False)),  # <— NEW: front-end can gate Finish & Analyze
        "allow_scenarios": bool(gate.get("can_finish", False)),
        "allow_adopt":     bool(gate.get("can_finish", False)),
        "allow_project":   bool(gate.get("can_finish", False)),
    }
    # Profile-aware nudge (step 3) — inject into body BEFORE making Response
    try:
        # Nudges disabled; keep names defined for backward-compat
        ask = ""
        body.pop("nudge_debug", None)
    except Exception:
        pass
    # Echo parsed numeric inputs back to the client for validation
    try:
        body["parsed_inputs"] = dict(sess.get("parsed_inputs") or {})
    except Exception:
        body["parsed_inputs"] = {}

    # Response (sets cookie if needed)
    resp = make_response(jsonify(body))
    # keep browser cookie aligned with the active SID every response
    resp.set_cookie(
        "sekki_sid",
        sid,
        max_age=30*24*3600,
        path="/",
        domain=".sekki.io",   # share across subdomains
        secure=True,
        samesite="None",
        httponly=False
    )

    return resp

# --- begin: safe user text extractor ---
def _extract_user_text(data):
    """Accepts multiple request shapes and returns a clean string."""
    if data is None:
        return ""
    if isinstance(data, str):
        return data.strip()
    if isinstance(data, dict):
        for key in ("message","user_message","prompt","text","content"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, dict):
                for k in ("text","content","message"):
                    v = val.get(k)
                    if isinstance(v, str) and v.strip():
                        return v.strip()
        msgs = data.get("messages") or data.get("history")
        if isinstance(msgs, list):
            for m in reversed(msgs):
                if isinstance(m, dict):
                    role = m.get("role")
                    content = m.get("content")
                    if role in ("user","human") and isinstance(content, str) and content.strip():
                        return content.strip()
                    if role in ("user","human") and isinstance(content, list):
                        for part in content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                t = part.get("text")
                                if isinstance(t, str) and t.strip():
                                    return t.strip()
        try:
            import json
            return json.dumps(data, ensure_ascii=False)[:1000].strip()
        except Exception:
            return ""
    return str(data).strip()
# --- end: safe user text extractor ---
@conversational_ai_bp.route("/scenarios/set", methods=["POST"])
def scenarios_set() -> Any:
    """
    Set/replace the active scenario overrides for this session.
    Body: { "name": "string", "overrides": { "price_month": 39, "plan_months": 6, ... } }
    Allowed keys: price_month, plan_months, budget, gross_margin, mrr, arr, revenue, ebit, operating_cash_flow, subscribers
    """
    try:
        data = request.get_json(silent=True) or {}
        name = data.get("name") or "scenario"
        overrides = data.get("overrides") or {}

        if not isinstance(overrides, dict):
            return jsonify({"ok": False, "error": "overrides must be an object"}), 400

        # Load/create session
        sid = _sid_from_request()
        sess = _load_session(sid)

        # Sanitize & clamp
        allowed = {
            "price_month", "plan_months", "budget", "gross_margin",
            "mrr", "arr", "revenue", "ebit", "operating_cash_flow", "subscribers"
        }
        cleaned: Dict[str, float] = {}
        for k, v in overrides.items():
            if k not in allowed:
                continue
            try:
                if isinstance(v, bool) or v is None:
                    continue
                num = float(v)
                if k == "gross_margin":
                    num = max(0.0, min(100.0, num))  # keep % sane
                cleaned[k] = num
            except Exception:
                continue

        sess["scenario_name"] = str(name)[:80]
        sess["scenario_overrides"] = cleaned
        _save_session(sess)

        current_app.logger.info(f"[scenario] {sid} -> {sess['scenario_name']} {cleaned}")
        # Echo the effective parsed map (baseline + overrides view)
        effective = dict(sess.get("parsed_inputs") or {})
        effective.update(cleaned)
        return jsonify({"ok": True, "session_id": sid, "scenario": sess["scenario_name"],
                        "overrides": cleaned, "effective_inputs": effective}), 200
    except Exception as e:
        current_app.logger.exception("scenarios_set failed")
        return jsonify({"ok": False, "error": str(e)}), 500


@conversational_ai_bp.route("/discuss/ping", methods=["GET"])
def discuss_ping():
    return jsonify({"ok": True}), 200


# === CORS helpers for /api/chat ===
_ALLOWED_ORIGINS = {"https://sekki.io", "https://www.sekki.io"}

def _allow_origin(origin: str|None) -> bool:
    return bool(origin) and origin in _ALLOWED_ORIGINS

@conversational_ai_bp.route('/chat', methods=['OPTIONS'])
def _chat_cors_options():
    origin = request.headers.get("Origin")
    resp = make_response("", 204)
    if _allow_origin(origin):
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With, X-Session-ID"
        resp.headers["Access-Control-Max-Age"] = "86400"
        resp.headers["Vary"] = "Origin"
    return resp

@conversational_ai_bp.after_request
def _chat_cors_after(resp):
    try:
        origin = request.headers.get("Origin")
        if _allow_origin(origin) and request.path.startswith("/api/chat"):
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            resp.headers["Vary"] = "Origin"
    except Exception:
        pass
    return resp


# === discuss context (Redis-backed) ===
from app.services.discuss_context import set_ctx as _set_ctx, get_ctx as _get_ctx, new_sid as _new_sid

def _sid_from_cookie():
    return request.cookies.get("sekki_sid")

def _ensure_sid_cookie(resp):
    sid = _sid_from_cookie() or _new_sid()
    resp.set_cookie("sekki_sid", sid, secure=True, httponly=False, samesite="None", path="/", max_age=60*60*24*30)
    return sid

@conversational_ai_bp.route("/discuss/start", methods=["POST"])
def discuss_start():
    try:
        from app.services.discuss_context import set_ctx, new_sid
    except Exception:
        return jsonify({"error": "context service unavailable"}), 500

    data = request.get_json(silent=True) or {}
    analysis = data.get("analysis") or {}
    aid = data.get("analysis_id") or analysis.get("id")
    if not aid and not analysis:
        return jsonify({"error": "analysis_id or analysis required"}), 400

    ctx = {
        "analysis_id": aid,
        "summary": analysis.get("summary") or data.get("summary"),
        "score": analysis.get("score") or data.get("score"),
        "meta": {
            "name": analysis.get("name") or data.get("name"),
            "ts": time.time(),
        },
        "raw": analysis if isinstance(analysis, dict) else None,
    }

    sid = (
        request.cookies.get("sekki_sid")
        or request.headers.get("X-Session-ID")
        or request.args.get("sid")
        or data.get("sid")
        or new_sid()
    )

    try:
        set_ctx(sid, ctx)
    except Exception:
        try:
            g = globals()
            store = g.setdefault("_CTX", {})
            store[sid] = (time.time() + 7200, ctx)
        except Exception:
            return jsonify({"error": "failed to store context"}), 500

    resp = make_response(jsonify({
        "ok": True,
        "session_id": sid,
        "context_keys": sorted(ctx.keys())
    }), 200)

    try:
        resp.set_cookie(
            "sekki_sid", sid,
            secure=True, samesite="None", path="/", httponly=False,
            domain="sekki.io",
            max_age=60*60*24*30
        )
    except Exception:
        pass
    return resp

@conversational_ai_bp.route("/discuss/context", methods=["GET"])
def discuss_context():
    sid = request.cookies.get("sekki_sid") or request.headers.get("X-Session-ID") or request.args.get("sid")
    if not sid:
        return jsonify({"error": "missing session id"}), 400

    ctx = None
    try:
        from app.services.discuss_context import get_ctx
        ctx = get_ctx(sid)
    except Exception:
        ctx = None

    if not ctx:
        g = globals()
        legacy = g.get("_CTX")
        try:
            rec = None
            if isinstance(legacy, dict) and sid in legacy:
                rec = legacy.get(sid)
            if isinstance(rec, tuple) and len(rec) == 2:
                ctx = rec[1]
            elif isinstance(rec, dict):
                ctx = rec
            if ctx:
                try:
                    from app.services.discuss_context import set_ctx as _promote
                    _promote(sid, ctx)
                except Exception:
                    pass
        except Exception:
            pass

    if not ctx:
        return jsonify({"ok": False, "session_id": sid, "context": None, "error": "not found"}), 404
    return jsonify({"ok": True, "session_id": sid, "context": ctx}), 200


@conversational_ai_bp.before_request
def _rl_guard_chat_only():
    try:
        if request.endpoint == "conversational_ai.chat" and request.method == "POST":
            from app.services.rate_limit import guard_or_429
            hit = guard_or_429("chat", limit=20, window=60)
            if hit is not None:
                return hit
    except Exception:
        return None

def _ctx_preamble():
    try:
        from app.services.context_store import get_context
        sid = request.cookies.get("sekki_sid") or request.headers.get("X-Session-ID") or ""
        ctx = get_context(sid) if sid else None
    except Exception:
        ctx = None
    if not isinstance(ctx, dict):
        return ""
    summ  = ctx.get("summary") or ""
    aid   = ctx.get("analysis_id") or ""
    name  = (ctx.get("meta") or {}).get("name") or ""
    score = ctx.get("score")
    parts = [
        "You are discussing a specific analysis with the user.",
        f"Analysis ID: {aid}" if aid else "",
        f"Name: {name}"       if name else "",
        f"Summary: {summ}"    if summ else "",
        f"Score: {score}"     if isinstance(score, (int, float)) else "",
        "Refer to these details when answering, and avoid repeating the same overview.",
    ]
    return " ".join(p for p in parts if p)


# --- Readiness Spec (versioned, read-only) -----------------------------------
@conversational_ai_bp.route('/readiness/spec', methods=['GET'])
def readiness_spec():
    """
    Publishes the current readiness scoring spec (categories, weights, thresholds).
    The categories/weights are pulled directly from MACRO_CATEGORIES to avoid drift.
    """
    try:
        version = os.getenv("READINESS_SPEC_VERSION", "readiness_v1.2.0")
        gate_percent = int(os.getenv("READINESS_GATE_PERCENT", "85"))
        required_csv = os.getenv("REQUIRED_CATEGORIES", "business_description,target_market,revenue_model,financial_metrics,timeline,budget")
        required_categories = [s.strip() for s in required_csv.split(",") if s.strip()]
        required_minimums = {k: int(os.getenv(f"MIN_REQUIRED_{k}", "70")) for k in required_categories}
        thresholds = {
            "finish_analyze": gate_percent,
            "almost_ready": gate_percent,
            "finish_analyze_threshold": gate_percent,  # legacy alias
            "almost_ready_threshold": gate_percent,    # legacy alias
        }

        # Optional label overrides (so UI gets human-readable names)
        label_overrides = {
            "business_description": "Business Description",
            "target_market":        "Target Market",
            "revenue_model":        "Revenue Model",
            "financial_metrics":    "Financial Metrics",
            "timeline":             "Timeline",
            "budget":               "Budget",
            "competition":          "Competition",
            "team":                 "Team & Resources",
        }
        def _labelize(key: str) -> str:
            return label_overrides.get(key) or key.replace("_", " ").title()

        # Build categories from the single source of truth used by compute_readiness
        cats = [
            {
                "key": key,
                "label": _labelize(key),
                "weight": float(cfg.get("weight", 0.0)),
            }
            for key, cfg in MACRO_CATEGORIES.items()
        ]

        model_info = {
            "scorer": "SimpleFinancialScorer",
            "source": "heuristic_or_blended",  # actual method is reported by /api/readiness
        }
        payload = {
            "version": version,
            "thresholds": thresholds,
            "gate_percent": gate_percent,
            "required_categories": required_categories,
            "required_minimums": required_minimums,
            "categories": cats,
            "model_info": model_info,
        }
        return jsonify(payload), 200
    except Exception as e:
        current_app.logger.exception("readiness_spec failed")
        return jsonify({"error": str(e)}), 500
@conversational_ai_bp.route('/score/spec', methods=['GET'])
def score_spec():
    """
    Immutable MarketIQ Core spec (weights + version).
    UI and services should treat this as the single source of truth.
    """
    try:
        version = os.getenv("MARKETIQ_SPEC_VERSION", "marketiq_core_v1.0.0")

        # Weights (sum to 100)
        weights = {
            "value": 40,        # ROI/payback/EBIT-Δ
            "confidence": 25,   # inputs/comparables/sensitivity present
            "feasibility": 20,  # team, timeline, complexity
            "strategic_fit": 15 # ICP/target clarity, differentiation, ICP size
        }

        # Normalization notes (UI can display; engine uses its own code path)
        notes = {
            "value": "Map payback months to 0–100 (0 if >24m, 100 if ≤6m, linear between). NPV optional; fallback to payback + EBIT-Δ.",
            "confidence": "Score from explicit flags (provided/not provided) only.",
            "feasibility": "Team roles present, timeline ≤12m favored, execution complexity via T-shirt sizing.",
            "strategic_fit": "Target clarity, differentiation stated, ICP size over threshold.",
            "rounding": "Nearest int, clamped 0–100, then weight-sum."
        }

        payload = {
            "version": version,
            "weights": weights,
            "normalization": notes,
        }
        return jsonify(payload), 200
    except Exception as e:
        current_app.logger.exception("score_spec failed")
        return jsonify({"error": str(e)}), 500
@conversational_ai_bp.route('/ideas/analyze', methods=['POST'])
def ideas_analyze():
    """
    Batch-ingest many ideas from a pasted document.
    Returns a ranked list: [{idea_id, title, readiness%, can_finish, top_gaps[]}].
    """
    try:
        data = request.get_json(silent=True) or {}
        text = data.get("text") or ""
        if not isinstance(text, str) or not text.strip():
            return jsonify({"ok": False, "error": "text is required"}), 400

        # 1) Segment into ideas: split by blank lines or numbered/bulleted blocks.
        raw_blocks = [b.strip() for b in re.split(r'(?:\n\s*\n)+', text) if b and b.strip()]
        if not raw_blocks:
            return jsonify({"ok": True, "ideas": []}), 200

        ideas = []
        for idx, block in enumerate(raw_blocks, start=1):
            # Title: first non-empty line, trimmed
            first_line = next((ln.strip() for ln in block.splitlines() if ln.strip()), "")[:120]
            title = first_line or f"Idea {idx}"

            # 2) Build a temporary session using your existing structures
            sid = f"batch_{uuid.uuid4().hex[:8]}_{idx}"
            sess = {"id": sid, "messages": [{"role": "user", "content": block, "ts": int(time.time())}]}

            # 3) Score with the same readiness engine
            snap = compute_readiness(sess) or {}
            gate = snap.get("gate") or {}
            ideas.append({
                "idea_id": sid,
                "title": title,
                "readiness_percent": int(snap.get("percent") or 0),
                "can_finish": bool(gate.get("can_finish", False)),
                "top_gaps": gate.get("unmet_required", []) or [],
                "categories": [
                    {"key": r.get("key"), "percent": int(r.get("percent", 0))}
                    for r in (snap.get("categories") or [])
                ],
            })

        # 4) Sort by readiness desc
        ideas.sort(key=lambda x: x["readiness_percent"], reverse=True)

        # 5) Return top 3 separately highlighted (client convenience)
        top3 = ideas[:3]
        return jsonify({"ok": True, "ideas": ideas, "top3": top3}), 200
    except Exception as e:
        current_app.logger.exception("ideas_analyze failed")
        return jsonify({"ok": False, "error": str(e)}), 500
@conversational_ai_bp.route('/files/analyze', methods=['POST'])
def files_analyze():
    """
    Accepts one uploaded file (Word/Excel/CSV/TXT). Extracts text and runs the same
    segmentation/scoring as /ideas/analyze. Returns ranked ideas with can_finish.
    """
    try:
        from flask import request, jsonify
        if 'file' not in request.files:
            return jsonify({"ok": False, "error": "file is required"}), 400

        f = request.files['file']
        filename = (f.filename or "").lower()

        # --- simple type routing (no heavy deps; fail safe) ---
        text = ""
        if filename.endswith(('.txt',)):
            text = f.read().decode('utf-8', errors='ignore')
        elif filename.endswith(('.csv',)):
            content = f.read().decode('utf-8', errors='ignore')
            # keep it simple: join lines as text
            text = content
        elif filename.endswith(('.docx',)):
            # best-effort extraction if python-docx is available
            try:
                from docx import Document  # type: ignore
                import io
                doc = Document(io.BytesIO(f.read()))
                text = "\n".join(p.text for p in doc.paragraphs if p.text)
            except Exception:
                return jsonify({"ok": False, "error": "DOCX support requires python-docx"}), 400
        elif filename.endswith(('.xlsx',)):
            try:
                import pandas as pd  # type: ignore
                import io
                buf = io.BytesIO(f.read())
                dfs = pd.read_excel(buf, sheet_name=None)
                # flatten all sheets to text (first 1000 rows to avoid bloat)
                parts = []
                for name, df in dfs.items():
                    head = df.astype(str).head(1000)
                    parts.append(f"[Sheet: {name}]\n" + head.to_csv(index=False))
                text = "\n\n".join(parts)
            except Exception:
                return jsonify({"ok": False, "error": "XLSX support requires pandas/openpyxl"}), 400
        else:
            return jsonify({"ok": False, "error": "Unsupported file type. Use TXT, CSV, DOCX, or XLSX."}), 400

        if not text.strip():
            return jsonify({"ok": True, "ideas": [], "top3": []}), 200

        # Reuse the same segmentation/scoring as /ideas/analyze
        raw_blocks = [b.strip() for b in re.split(r'(?:\n\s*\n)+', text) if b and b.strip()]
        ideas = []
        for idx, block in enumerate(raw_blocks, start=1):
            first_line = next((ln.strip() for ln in block.splitlines() if ln.strip()), "")[:120]
            title = first_line or f"Idea {idx}"
            sid = f"upload_{uuid.uuid4().hex[:8]}_{idx}"
            sess = {"id": sid, "messages": [{"role": "user", "content": block, "ts": int(time.time())}]}
            snap = compute_readiness(sess) or {}
            gate = snap.get("gate") or {}
            ideas.append({
                "idea_id": sid,
                "title": title,
                "readiness_percent": int(snap.get("percent") or 0),
                "can_finish": bool(gate.get("can_finish", False)),
                "top_gaps": gate.get("unmet_required", []) or [],
                "categories": [
                    {"key": r.get("key"), "percent": int(r.get("percent", 0))}
                    for r in (snap.get("categories") or [])
                ],
            })

        ideas.sort(key=lambda x: x["readiness_percent"], reverse=True)
        top3 = ideas[:3]
        return jsonify({"ok": True, "ideas": ideas, "top3": top3}), 200
    except Exception as e:
        current_app.logger.exception("files_analyze failed")
        return jsonify({"ok": False, "error": str(e)}), 500
@conversational_ai_bp.route('/score/compute', methods=['GET'])
def score_compute():
    """
    Deterministic MarketIQ Core score (v1).
    Uses env-weighted spec and parsed inputs (fallback: recompute from session text).
    """
    try:
        from flask import request, jsonify

        # Version + weights (align with /score/spec)
        version = os.getenv("MARKETIQ_SPEC_VERSION", "marketiq_core_v1.0.0")
        weights = {
            "value": 40,
            "confidence": 25,
            "feasibility": 20,
            "strategic_fit": 15,
        }

        # Acquire session and parsed inputs
        sid = request.headers.get("X-Session-ID") or request.args.get("sid")
        sess = _get_or_create_session(sid)

        try:
            cum_text = get_cumulative_user_text(sess)
            calc = run_calculator(cum_text or "") or {}
            parsed = (calc.get("inputs_parsed") or {}) if isinstance(calc, dict) else {}
        except Exception:
            parsed = {}

        # Extract needed fields (strict, deterministic)
        budget = parsed.get("budget") or 0
        gross_margin = parsed.get("gross_margin")  # expected 0-100
        revenue = parsed.get("revenue") or 0       # monthly revenue proxy
        plan_months = parsed.get("plan_months") or 0

        # Compute monthly gross-profit uplift if possible
        try:
            gm_frac = (gross_margin / 100.0) if isinstance(gross_margin, (int, float)) else None
        except Exception:
            gm_frac = None
        monthly_gp_uplift = (revenue * gm_frac) if (isinstance(revenue, (int, float)) and isinstance(gm_frac, float)) else None

        # Deterministic payback (months)
        if isinstance(budget, (int, float)) and budget > 0 and isinstance(monthly_gp_uplift, (int, float)) and monthly_gp_uplift > 0:
            payback_months = budget / monthly_gp_uplift
        else:
            payback_months = None

        # Map payback → 0–100 (0 if >24m, 100 if ≤6m, linear in between)
        def _payback_to_score(m: float | None) -> int:
            if not isinstance(m, (int, float)) or m <= 0:
                return 0
            if m <= 6:
                return 100
            if m >= 24:
                return 0
            # linear from 6→24: 100 at 6, 0 at 24
            return int(round((24 - m) * (100.0 / (24 - 6))))

        value_score = _payback_to_score(payback_months)

        # Confidence: explicit flags present (binary). Keep v1 simple & deterministic.
        confidence_flags = 0
        total_flags = 0
        for key in ("budget", "gross_margin", "plan_months", "revenue"):
            total_flags += 1
            if isinstance(parsed.get(key), (int, float)) and parsed.get(key) is not None:
                confidence_flags += 1
        confidence_score = int(round((confidence_flags / max(1, total_flags)) * 100))

        # Feasibility: timeline ≤ 12 months favored; else scaled down.
        if isinstance(plan_months, (int, float)) and plan_months > 0:
            feasibility_score = 100 if plan_months <= 12 else max(0, int(round(100 - (plan_months - 12) * 5)))
        else:
            feasibility_score = 0

        # Strategic fit: placeholder deterministic minimum (will evolve with tags)
        # If target market signals exist in cumulative text, give 60; else 30.
        txt = (cum_text or "").lower()
        has_target = any(s in txt for s in ("retail", "apparel", "grocery", "usa", "united states", "north america"))
        strategic_fit_score = 60 if has_target else 30

        # Weighted sum (0–100), nearest int
        weighted = (
            value_score       * (weights["value"] / 100.0) +
            confidence_score  * (weights["confidence"] / 100.0) +
            feasibility_score * (weights["feasibility"] / 100.0) +
            strategic_fit_score * (weights["strategic_fit"] / 100.0)
        )
        marketiq_score = int(round(min(100, max(0, weighted))))

        # Response
        return jsonify({
            "ok": True,
            "version": version,
            "weights": weights,
            "inputs": {
                "budget": budget,
                "gross_margin": gross_margin,
                "revenue_monthly": revenue,
                "plan_months": plan_months,
                "monthly_gross_profit_uplift": monthly_gp_uplift,
                "payback_months": payback_months,
            },
            "sub_scores": {
                "value": value_score,
                "confidence": confidence_score,
                "feasibility": feasibility_score,
                "strategic_fit": strategic_fit_score,
            },
            "score": marketiq_score
        }), 200
    except Exception as e:
        current_app.logger.exception("score_compute failed")
        return jsonify({"ok": False, "error": str(e)}), 500

# --- Readiness prompt hints (transparent examples for users/UX) --------------
@conversational_ai_bp.route('/readiness/prompts', methods=['GET'])
def readiness_prompts():
    """
    Returns example phrases the readiness engine recognizes for each macro category.
    Use this to drive frontend hint text / tooltips and to demonstrate objective criteria.
    """
    from flask import jsonify
    gate_percent = int(os.getenv("READINESS_GATE_PERCENT", "85"))

    payload = {
        "version": "readiness_v1.2.0",
        "finish_analyze_threshold": gate_percent,
        "almost_ready_threshold": gate_percent,
        "categories": [
            {
                "key": "business_description",
                "label": "Business Description",
                "examples": [
                    "We provide a subscription service for ...",
                    "Our product helps retailers ...",
                    "Our value proposition is ..."
                ]
            },
            {
                "key": "target_market",
                "label": "Target Market",
                "examples": [
                    "Mid-market US retailers",
                    "Targeting apparel and specialty stores in Texas",
                    "Primary region is the United States"
                ]
            },
            {
                "key": "revenue_model",
                "label": "Revenue Model",
                "examples": [
                    "$20 per user per month",
                    "Tiered pricing with annual discount",
                    "Recurring SaaS subscriptions"
                ]
            },
            {
                "key": "financial_metrics",
                "label": "Financial Metrics",
                "examples": [
                    "65% gross margin",
                    "ARR of $2.4M; MRR of $200k",
                    "CAC payback under 12 months"
                ]
            },
            {
                "key": "timeline",
                "label": "Timeline",
                "examples": [
                    "12-month plan",
                    "Launch in Q2",
                    "9 months to open 3 locations"
                ]
            },
            {
                "key": "budget",
                "label": "Budget",
                "examples": [
                    "Total budget is $250k",
                    "Marketing spend of $150k",
                    "Capex of $1.2M"
                ]
            },
            {
                "key": "competition",
                "label": "Competition",
                "examples": [
                    "Main competitors are ...",
                    "We differentiate from Trade Coffee by ...",
                    "We’re positioned as ..."
                ]
            },
            {
                "key": "team",
                "label": "Team & Resources",
                "examples": [
                    "Team of 10 with a dedicated sales lead",
                    "Hiring a PM and a data analyst",
                    "Experienced founders in retail tech"
                ]
            }
        ]
    }
    return jsonify(payload), 200

# --- Readiness trace (transparent calculation snapshot) ----------------------
@conversational_ai_bp.route('/readiness/trace', methods=['GET'])
def readiness_trace():
    """
    Returns a transparent snapshot of the current readiness calculation for a session.
    Useful for debugging and investor-facing transparency.
    """
    from flask import request, jsonify
    try:
        sid = request.headers.get("X-Session-ID") or request.args.get("sid")
        sess = _get_or_create_session(sid)
        # Fresh compute (authoritative for the caller)
        snapshot = compute_readiness(sess) or {}
        # Whatever is already persisted on the session (if any)
        last = sess.get("readiness_detail") or {}
        # Tailored trace details
        try:
            cum_text = get_cumulative_user_text(sess)
            _calc = run_calculator(cum_text or "") or {}
            parsed_inputs = (_calc.get("inputs_parsed") or {}) if isinstance(_calc, dict) else {}
        except Exception:
            parsed_inputs = {}

        gate = snapshot.get("gate") or {}
        cats = snapshot.get("categories") or []
        readiness_spec_ver = os.getenv("READINESS_SPEC_VERSION", "readiness_v1.2.0")
        marketiq_spec_ver  = os.getenv("MARKETIQ_SPEC_VERSION", "marketiq_core_v1.0.0")

        out = {
            "ok": True,
            "session_id": sess.get("id"),
            "messages_seen": len(sess.get("messages", [])),
            "versions": {
                "readiness_spec": readiness_spec_ver,
                "marketiq_spec": marketiq_spec_ver
            },
            "overall_percent": int(snapshot.get("percent") or 0),
            "source": snapshot.get("source") or "heuristic",
            "heur_overall": int(snapshot.get("heur_overall") or 0),
            "weighted_total": float(snapshot.get("weighted_total") or 0.0),
            "total_weight": float(snapshot.get("total_weight") or 0.0),
            "gate": gate,
            "categories": [
                {
                    "key": c.get("key"),
                    "percent": int(c.get("percent", 0)),
                    "weight": float(c.get("weight", 0.0))
                } for c in cats
            ],
            "parsed_inputs": parsed_inputs,
            "snapshot": snapshot,
            "last_saved": last
        }
        return jsonify(out), 200

    except Exception as e:
        current_app.logger.exception("readiness_trace failed")
        return jsonify({"ok": False, "error": str(e)}), 500
@conversational_ai_bp.route('/analysis/trace', methods=['GET'])
def analysis_trace():
    """Alias to readiness_trace for client convenience."""
    return readiness_trace()

# --- Readiness audit (minimal, investor-friendly) ----------------------------
@conversational_ai_bp.route('/readiness/audit/min', methods=['GET'])
def readiness_audit_min():
    """
    Minimal, stable audit payload:
      - overall percent + source (ml/heuristic)
      - heuristic fields (heur_overall, weighted_total, total_weight)
      - per-category percent + weight
    """
    from flask import request, jsonify
    try:
        sid = request.headers.get("X-Session-ID") or request.args.get("sid")
        sess = _get_or_create_session(sid)
        snap = compute_readiness(sess) or {}

        cats_in = snap.get("categories") or []
        cats_out = []
        for c in cats_in:
            try:
                cats_out.append({
                    "key": c.get("key"),
                    "percent": int(c.get("percent") or 0),
                    "weight": float(c.get("weight") or 0.0),
                    "completed": bool(c.get("completed") or False),
                })
            except Exception:
                # Be defensive—never crash the audit
                pass

        payload = {
            "ok": True,
            "session_id": sess.get("id"),
            "percent": int(snap.get("percent") or 0),
            "source": snap.get("source") or "heuristic",
            "heur_overall": int(snap.get("heur_overall") or 0),
            "weighted_total": float(snap.get("weighted_total") or 0.0),
            "total_weight": float(snap.get("total_weight") or 0.0),
            "categories": cats_out,
            "version": "readiness_v1.2.0",
        }
        return jsonify(payload), 200
    except Exception as e:
        current_app.logger.exception("readiness_audit failed")
        return jsonify({"ok": False, "error": str(e)}), 500

# --- Readiness reasons (what's missing + suggested prompts) -------------------
@conversational_ai_bp.route('/readiness/reasons', methods=['GET'])
def readiness_reasons():
    """
    Returns a minimal, investor-friendly gap report:
      - overall percent/source
      - per-category percent
      - for incomplete categories: 'missing' bullets + short 'suggested_prompts'
    This is derived without reintroducing micro-rows into the public API.
    """
    from flask import request, jsonify
    try:
        sid = request.headers.get("X-Session-ID") or request.args.get("sid")
        sess = _get_or_create_session(sid)

        # Fresh authoritative snapshot
        snap = compute_readiness(sess) or {}
        cats = snap.get("categories") or []

        # Pull cumulative text + parsed numbers to tailor hints a bit
        try:
            cum_text = get_cumulative_user_text(sess)
        except Exception:
            cum_text = ""
        try:
            calc = run_calculator(cum_text or "") or {}
            parsed = (calc.get("inputs_parsed") or {}) if isinstance(calc, dict) else {}
        except Exception:
            parsed = {}

        # Simple presence heuristics
        def has_any(*phrases) -> bool:
            txt = cum_text.lower()
            return any(p.lower() in txt for p in phrases if isinstance(p, str))

        # Generic, non-micro guidance per macro category
        HINTS = {
              "business_description": {
                  "missing": ["Problem/opportunity stated", "Value/outcome stated"],
                  "prompt": "Briefly state the problem/opportunity and desired business outcome."
              },
              "target_market": {
                  "missing": ["Target customer segment", "Geo or industry specified", "Subscribers/users count"],
                  "prompt": "Who is the target customer and where? Include subscribers/users if known (e.g., Subscribers: 1000)."
              },
              "revenue_model": {
                  "missing": ["Pricing model stated", "MRR/ARR or revenue proxy"],
                  "prompt": "What is the pricing model? Example: Price/Month: 49 and MRR: 5000."
              },
              "financial_metrics": {
                  "missing": ["Gross margin %", "EBIT or Operating cash flow"],
                  "prompt": "Provide Gross_Margin: 65% and any EBIT or Operating Cash Flow (e.g., EBIT: 200k)."
              },
              "timeline": {
                  "missing": ["Plan months / delivery horizon"],
                  "prompt": "What is the delivery timeline in months? Example: Plan_Months: 6."
              },
              "budget": {
                  "missing": ["Budget amount provided"],
                  "prompt": "What is the project budget? Example: Budget: 250k."
              },
        }

        gate = snap.get("gate") or {}
        unmet_required = set(gate.get("unmet_required") or [])
        overall_percent = int(snap.get("percent") or 0)
        source = snap.get("source") or "heuristic"
        # Build a minimal, investor-friendly gap list
        cats_out = []
        for row in cats:
            key = row.get("key")
            pct = int(row.get("percent", 0))
            hint = HINTS.get(key, {"missing": [], "prompt": ""})
            need = (pct < 100)

            entry = {
                "key": key,
                "percent": pct,
                "required": (key in unmet_required) or bool(key in (gate.get("required") or [])),
                "missing": hint.get("missing") if need else [],
                "suggested_prompts": ([hint.get("prompt")] if (need and hint.get("prompt")) else []),
            }
            cats_out.append(entry)

        # Early, explicit return with reasons
        return jsonify({
            "ok": True,
            "overall_percent": overall_percent,
            "source": source,
            "gate": gate,
            "categories": cats_out,
        }), 200

    except Exception as e:
        current_app.logger.exception("readiness_reasons failed")
        return jsonify({"ok": False, "error": str(e)}), 500

# --- Readiness audit (investor-friendly summary report) ----------------------
@conversational_ai_bp.route('/readiness/audit', methods=['GET'])
def readiness_audit_full():
    """
    Returns a compact, investor-friendly JSON report:
      - overall readiness percent + source
      - per-category percent/weight/completed
      - missing bullets + short prompts (like /readiness/reasons)
      - light metadata (messages seen, version)
    """
    from flask import request, jsonify
    try:
        sid = request.headers.get("X-Session-ID") or request.args.get("sid")
        sess = _get_or_create_session(sid)

        # Authoritative snapshot
        snap = compute_readiness(sess) or {}
        cats = snap.get("categories") or []

        # Cumulative text + parsed numbers for small tailoring
        try:
            cum_text = get_cumulative_user_text(sess)
        except Exception:
            cum_text = ""
        try:
            calc = run_calculator(cum_text or "") or {}
            parsed = (calc.get("inputs_parsed") or {}) if isinstance(calc, dict) else {}
        except Exception:
            parsed = {}

        def has_any(*phrases) -> bool:
            txt = cum_text.lower()
            return any(isinstance(p, str) and p.lower() in txt for p in phrases)

        HINTS = {
            "business_description": {
                "missing": [
                    "1–2 sentence description of the product",
                    "Clear value proposition (why customers choose it)"
                ],
                "prompts": [
                    "In one sentence, what does your product do?",
                    "Why do customers choose your product over alternatives?"
                ],
            },
            "target_market": {
                "missing": [
                    "Customer segment (role/company size) and vertical",
                    "Primary geography or region"
                ],
                "prompts": [
                    "Who is the ideal customer (role, company size, vertical)?",
                    "What geography are you focused on in the next 12 months?"
                ],
            },
            "revenue_model": {
                "missing": [
                    "Pricing structure (per user/location/tier)",
                    "Primary revenue streams"
                ],
                "prompts": [
                    "How is pricing structured (per user/location/tier)?",
                    "List your primary revenue streams."
                ],
            },
            "financial_metrics": {
                "missing": [
                    "ARR/MRR and gross margin",
                    "Monthly churn and CAC/payback"
                ],
                "prompts": [
                    "What are your current ARR/MRR and gross margin?",
                    "What’s your monthly churn and CAC/payback target?"
                ],
            },
            "timeline": {
                "missing": [
                    "Overall duration (months) and major milestones"
                ],
                "prompts": [
                    "What’s the overall timeline and top 3 milestones (dates/outcomes)?"
                ],
            },
            "budget": {
                "missing": [
                    "Total budget and high-level allocation"
                ],
                "prompts": [
                    "Confirm total budget and rough allocation by channel/area."
                ],
            },
            "competition": {
                "missing": [
                    "Top 2–3 competitors and key differentiators"
                ],
                "prompts": [
                    "Name your top competitors and how you differ."
                ],
            },
            "team": {
                "missing": [
                    "Key roles/owners for delivery"
                ],
                "prompts": [
                    "List the key roles/owners responsible for execution."
                ],
            },
        }

        # Tailor a little bit using parsed signals
        tailored = []
        for c in cats:
            key = c.get("key")
            pct = int(c.get("percent") or 0)
            item = {
                "key": key,
                "percent": pct,
                "weight": float(c.get("weight") or 0.0),
                "completed": bool(c.get("completed") or False),
            }
            hints = HINTS.get(key, {})
            missing = list(hints.get("missing", []))
            prompts = list(hints.get("prompts", []))

            if key == "budget":
                if (parsed.get("budget") or 0) > 0 or has_any("budget", "$"):
                    missing = [m for m in missing if "Total budget" not in m]

            if key == "financial_metrics":
                gm = parsed.get("gross_margin") or 0
                arr = parsed.get("revenue") or parsed.get("arr") or 0
                if gm or has_any("gross margin"):
                    missing = [m for m in missing if "gross margin" not in m.lower()]
                if arr or has_any("arr", "mrr", "revenue"):
                    # ensure we don't keep the ARR/MRR bullet redundantly
                    missing = [m for m in missing if "arr/mrr" not in m.lower()]

            if key == "timeline":
                months = parsed.get("plan_months") or 0
                if months or has_any("month", "months", "timeline", "12-month"):
                    # keep milestones wording only
                    missing = ["Major milestones (dates & outcomes)"]

            if pct >= 100:
                item["missing"] = []
                item["suggested_prompts"] = []
            else:
                item["missing"] = missing
                item["suggested_prompts"] = prompts

            tailored.append(item)

        report = {
            "ok": True,
            "version": "readiness_v1.2.0",
            "session_id": sess.get("id"),
            "messages_seen": len(sess.get("messages", [])),
            "overall": {
                "percent": int(snap.get("percent") or 0),
                "source": snap.get("source") or "heuristic",
                "heur_overall": int(snap.get("heur_overall") or 0),
            },
            "categories": tailored,
            "thresholds": {
                "finish_analyze": 60,
                "almost_ready": 90
            }
        }
        return jsonify(report), 200
    except Exception as e:
        current_app.logger.exception("readiness_audit failed")
        return jsonify({"ok": False, "error": str(e)}), 500
