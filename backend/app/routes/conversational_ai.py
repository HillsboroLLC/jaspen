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
from app.utils.request_payload import extract_user_text

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
    """
    Comprehensive weighted readiness calculation with macro/micro element tracking.
    
    PHASE 1 ENHANCEMENTS:
    - Cumulative text analysis (all user messages)
    - Smart keyword matching with word boundaries
    - Graceful error handling
    - Detailed micro element tracking
    
    PHASE 2/3 FOUNDATION:
    - Caching hooks ready
    - Analytics logging points marked
    - History tracking structure in place
    
    Returns:
    {
        "percent": 45,  # Overall weighted percentage (0-100)
        "categories": [  # Detailed per-category progress
            {
                "key": "business_description",
                "percent": 60,
                "weight": 0.10,
                "completed": false,
                "collected": 3,
                "total": 5,
                "micros": [
                    {"key": "overview", "collected": true, "confidence": 0.8},
                    {"key": "mission_vision", "collected": false, "confidence": 0.0},
                    ...
                ]
            },
            ...
        ],
        "collected_data": {  # Frontend-compatible format
            "business_description": {"percent": 60, "items": [true, true, false, ...]},
            ...
        }
    }
    """
    
    # PHASE 2 HOOK: Check cache (commented out for now, easy to enable later)
    # last_calc_msg_count = sess.get("_readiness_cache_msg_count", 0)
    # current_msg_count = len(sess.get("messages", []))
    # if current_msg_count == last_calc_msg_count and "_readiness_cache" in sess:
    #     return sess["_readiness_cache"]
    
    try:
        # PHASE 1: Cumulative text analysis (all user messages)
        cumulative_text = get_cumulative_user_text(sess)
        
        # Load existing session data
        session_micros = sess.get("micro_elements", {})
        
        # Initialize results
        categories_detail = []
        collected_data = {}
        weighted_total = 0.0
        total_weight = sum(cat["weight"] for cat in MACRO_CATEGORIES.values())
        
        # Process each macro category
        for macro_key, macro_config in MACRO_CATEGORIES.items():
            weight = macro_config["weight"]
            micros = macro_config["micros"]
            keywords = macro_config["keywords"]
            
            # Get or initialize micro tracking for this category
            if macro_key not in session_micros:
                session_micros[macro_key] = {
                    micro: {"collected": False, "confidence": 0.0} 
                    for micro in micros
                }
            
            category_micros = session_micros[macro_key]
            
            # Update micro elements based on cumulative text
            micros_detail = []
            collected_count = 0
            
            for micro_key in micros:
                micro_keywords = keywords.get(micro_key, [])
                
                # PHASE 1: Smart keyword matching with word boundaries
                matches = sum(1 for kw in micro_keywords if smart_keyword_match(kw, cumulative_text))
                
                # Update confidence based on keyword matches
                if matches > 0:
                    # Increase confidence (max 1.0)
                    current_confidence = category_micros[micro_key]["confidence"]
                    # Each match adds 0.25, capped at 1.0
                    new_confidence = min(1.0, current_confidence + (matches * 0.25))
                    category_micros[micro_key]["confidence"] = new_confidence
                    
                    # Mark as collected if confidence >= 0.5
                    if new_confidence >= 0.5:
                        category_micros[micro_key]["collected"] = True
                
                # Track collected status
                is_collected = category_micros[micro_key]["collected"]
                if is_collected:
                    collected_count += 1
                
                micros_detail.append({
                    "key": micro_key,
                    "collected": is_collected,
                    "confidence": round(category_micros[micro_key]["confidence"], 2)
                })
            
            # Calculate category percentage
            total_micros = len(micros)
            category_percent = int(round((collected_count / total_micros) * 100)) if total_micros > 0 else 0
            
            # Contribute to weighted total
            category_fraction = collected_count / total_micros if total_micros > 0 else 0
            weighted_total += (category_fraction * weight)
            
            # Build category detail
            categories_detail.append({
                "key": macro_key,
                "percent": category_percent,
                "weight": weight,
                "completed": category_percent >= 100,
                "collected": collected_count,
                "total": total_micros,
                "micros": micros_detail
            })
            
            # Build collected_data for frontend compatibility
            collected_data[macro_key] = {
                "percent": category_percent,
                "items": [m["collected"] for m in micros_detail]
            }
        
        # Calculate overall readiness percentage
        readiness_percent = int(round((weighted_total / total_weight) * 100)) if total_weight > 0 else 0
        
        # Save updated micro elements back to session
        import logging; logging.warning(f"DEBUG: session_micros keys: {list(session_micros.keys())}, first category sample: {list(session_micros.values())[0] if session_micros else None}")
        import logging; logging.warning(f"DEBUG: Saving {len(session_micros)} categories to session")
        sess["collected_data"] = collected_data
        sess["micro_elements"] = session_micros
        sess["readiness"] = readiness_percent
        sess["micro_elements"] = session_micros

        # PHASE 3 HOOK: Track readiness history (commented out for now)
        # sess.setdefault("readiness_history", []).append({
        #     "timestamp": int(time.time()),
        #     "percent": readiness_percent,
        #     "message_count": len(sess.get("messages", []))
        # })
        # sess["readiness_history"] = sess["readiness_history"][-20:]  # Keep last 20
        
        # Build comprehensive payload
        readiness_payload = {
            "percent": readiness_percent,
            "readiness_percent": readiness_percent,
            "value": readiness_percent,
            "categories": categories_detail,
            "collected_data": collected_data
        }
        
        # PHASE 2 HOOK: Cache the result (commented out for now)
        # sess["_readiness_cache"] = readiness_payload
        # sess["_readiness_cache_msg_count"] = len(sess.get("messages", []))
        
        # PHASE 3 HOOK: Analytics logging point
        # logger.info("readiness_calculated", extra={
        #     "session_id": sess.get("id"),
        #     "percent": readiness_percent,
        #     "categories_complete": sum(1 for c in categories_detail if c["completed"])
        # })
        
        return readiness_payload
        
    except Exception as e:
        # PHASE 1: Graceful degradation - never let readiness break the chat
        current_app.logger.error(f"Readiness calculation error: {e}", exc_info=True)
        
        # Fallback to simple turn-based estimate
        user_turn_count = len([m for m in sess.get("messages", []) if m.get("role") == "user"])
        fallback_percent = min(100, user_turn_count * 10)
        
        return {
            "percent": fallback_percent,
            "readiness_percent": fallback_percent,
            "value": fallback_percent,
            "status": "degraded",
            "error": str(e),
            "categories": [],
            "collected_data": sess.get("collected_data", {})
        }


# Load .env early; systemd also injects env
load_dotenv(dotenv_path='/home/sekki/sekki-platform/backend/.env')

# Anthropic client / model from env (defaults to a stable "latest" alias)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL   = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
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


def _anthropic_reply(history: List[Dict[str, str]]) -> str:
    if not CLIENT:
        return "(server missing ANTHROPIC_API_KEY)"
    msgs = [
        {"role": m.get("role"), "content": m.get("content", "")}
        for m in history
        if m.get("role") in ("user", "assistant") and (m.get("content") or "").strip()
    ]
    for _ in range(2):
        try:
            resp = CLIENT.messages.create(
                model=ANTHROPIC_MODEL,
                system=SYSTEM_PROMPT,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                messages=msgs,
            )
            parts = []
            for blk in resp.content:
                if getattr(blk, "type", None) == "text":
                    parts.append(blk.text)
            return ("".join(parts)).strip() or "(no content)"
        except Exception as e:
            current_app.logger.warning(f"anthropic_call_failed: {e}")
    return "(anthropic error)"


@conversational_ai_bp.route("/health", methods=["GET"])
def health() -> Any:
    return jsonify({"ok": True, "model": ANTHROPIC_MODEL, "client": bool(CLIENT)}), 200

@conversational_ai_bp.route("/chat", methods=["POST"])
@rate_limit('chat', limit=20, window=60)
def chat() -> Any:
    data = request.get_json(silent=True) or {}
    user_text = _extract_user_text(data)
    if not user_text:
        return jsonify({"error": "message is required"}), 400
    system_preamble = _ctx_preamble()
    if system_preamble and isinstance(user_text, str):
        user_text = "[CONTEXT]\n" + system_preamble + "\n\n" + user_text

    sid = _sid_from_request()
    sess = _load_session(sid)

    # Append user turn
    sess.setdefault("messages", []).append({"role": "user", "content": user_text, "ts": int(time.time())})

    # Trim and get reply
    history = _trim_by_chars(sess["messages"], MAX_HISTORY_CHARS)
    reply = _anthropic_reply(history)

    # PHASE 1: Single, comprehensive readiness calculation
    readiness = compute_readiness(sess)
    # Note: Session is already updated inside compute_readiness()

    # Append assistant turn and persist
    sess["messages"].append({"role": "assistant", "content": reply, "ts": int(time.time())})
    _save_session(sess)

    # Build response
    body = {
        "session_id": sid,
        "reply": reply,
        "readiness": readiness,
        "readiness_percent": readiness.get("percent"),
        "collected_data": sess.get("collected_data", {})
    }

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

