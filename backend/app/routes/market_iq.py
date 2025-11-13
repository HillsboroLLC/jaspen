from __future__ import annotations
import os, json, time, uuid, re
from typing import Dict, Any, Optional, List
from flask import Blueprint, request, jsonify, current_app
import anthropic

market_iq_bp = Blueprint("market_iq", __name__, url_prefix="/api")

# ---------- In-memory session storage (replace with Redis/DB in production) ----------
SESSIONS: Dict[str, Dict[str, Any]] = {}

def _new_id() -> str:
    return f"conv_{uuid.uuid4().hex[:12]}"

# ---------- Enhanced Claude conversational intake ----------
CONVERSATION_SYSTEM_PROMPT = """You are a top 0.1% senior financial analyst and strategic advisor helping entrepreneurs and business leaders evaluate their projects through natural conversation.

Your goal: Extract comprehensive information to build a Market IQ scorecard with rigorous financial analysis covering:

**Strategic Context:**
- Project name (explicit, clear title)
- Primary goal & objectives
- Target customers/market
- Problem being solved & solution approach
- Competitive differentiators & value proposition
- Market size & opportunity

**Current Financial Baseline (Before State):**
- Current annual revenue
- Current COGS (Cost of Goods Sold)
- Current operating expenses (SG&A, R&D, marketing)
- Current EBITDA (or you'll calculate it)
- Number of sites/locations/units (if applicable)

**Investment Requirements:**
- Initial investment required
- Time period for benefits (typically 3-5 years)

**Expected Benefits (After State):**
- Expected revenue impact
- Expected COGS changes
- Expected operating expense changes
- Expected annual benefit or cash flow improvement
- Expected EBITDA improvement

**Financial Parameters:**
- Discount rate / WACC / hurdle rate (for NPV analysis)
- Industry EBITDA multiple (for valuation)

**Execution Context:**
- Budget & timeline
- Team capabilities
- Key performance indicators
- Risks & constraints
- Go-to-market channels

Guidelines:
- **ALWAYS start by asking for the project name explicitly**: "Let's start with the basics - what's the name of this project or initiative?"
- Have a NATURAL, flowing conversation - don't follow a rigid script
- Listen to what the user shares and ask relevant follow-up questions
- Pocket information as it comes up organically
- Never ask the same question twice
- If they mention something, acknowledge it and build on it
- Keep responses conversational and concise (2-4 sentences)
- Always end with ONE clear question that moves the conversation forward
- If the user is unsure about financial details, offer guidance:
  - Discount rate: "Most companies use 10-12% for medium-risk projects"
  - EBITDA multiple: "Typical ranges: SaaS 8-12x, Manufacturing 4-6x, Healthcare 6-10x"
- Track what you've learned internally, but don't make it feel like a checklist
- When you have gathered sufficient information (typically after 8-12 meaningful exchanges covering financial details), tell the user: "I have enough information to build your comprehensive Market IQ scorecard with financial analysis. Click 'Finish & Analyze' when you're ready to see the results."

Be warm, professional, and genuinely curious about their project. Remember: you're a trusted financial advisor, not a form-filler."""

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

def calculate_readiness(messages: List[Dict]) -> int:
    """Calculate how ready we are to generate a score based on conversation depth"""
    user_messages = [m for m in messages if m["role"] == "user"]
    num_exchanges = len(user_messages)
    
    # Enhanced heuristic: need more exchanges for comprehensive financial analysis
    if num_exchanges >= 12:
        return 95
    elif num_exchanges >= 10:
        return 90
    elif num_exchanges >= 8:
        return 80
    elif num_exchanges >= 6:
        return 65
    elif num_exchanges >= 4:
        return 45
    elif num_exchanges >= 2:
        return 25
    else:
        return 10

def extract_collected_data(messages: List[Dict]) -> Dict[str, Any]:
    """Extract what information has been collected from the conversation"""
    collected = {}
    conversation_text = " ".join([m.get("content", "") for m in messages if m.get("role") == "user"])
    
    # Enhanced keyword detection for financial data
    keywords = {
        "project_name": ["project", "initiative", "called", "name"],
        "business_description": ["business", "company", "product", "service", "solution"],
        "target_market": ["market", "customer", "audience", "segment", "demographic"],
        "revenue": ["revenue", "sales", "income", "$", "million", "thousand"],
        "costs": ["cost", "cogs", "expense", "opex", "spending"],
        "investment": ["investment", "capital", "funding", "budget", "spend"],
        "benefits": ["benefit", "savings", "improvement", "increase", "growth"],
        "timeline": ["month", "year", "quarter", "timeline", "period"],
        "discount_rate": ["discount", "wacc", "hurdle", "rate", "percent"],
        "ebitda": ["ebitda", "margin", "profit", "earnings"],
        "competition": ["competitor", "competition", "alternative", "versus"],
        "team": ["team", "founder", "employee", "hire", "staff", "resource"]
    }
    
    for key, terms in keywords.items():
        if any(term in conversation_text.lower() for term in terms):
            collected[key] = True
    
    return collected

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
        
        ai_message = (response.content[0].text or "").strip()
        
        # Store session
        messages.append({"role": "assistant", "content": ai_message})
        SESSIONS[session_id] = {
            "id": session_id,
            "messages": messages,
            "created_at": int(time.time()),
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
        
        # Get Claude's response with full conversation context
        client = get_claude_client()
        
        response = client.messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929"),
            max_tokens=400,
            temperature=0.7,
            system=CONVERSATION_SYSTEM_PROMPT,
            messages=session["messages"]
        )
        
        ai_message = (response.content[0].text or "").strip()
        
        # Add AI response to history
        session["messages"].append({"role": "assistant", "content": ai_message})
        
        readiness = calculate_readiness(session["messages"])
        collected_data = extract_collected_data(session["messages"])
        
        return jsonify({
            "message": ai_message,
            "readiness": readiness,
            "collected_data": collected_data,
            "status": "gathering_info" if readiness < 85 else "ready_to_analyze"
        }), 200
        
    except Exception as e:
        current_app.logger.exception("conversation_continue_failed")
        return jsonify({"error": "conversation_continue_failed", "details": str(e)}), 500

@market_iq_bp.route("/analyze", methods=["POST"])
def analyze():
    """Generate Market IQ score from conversation with comprehensive financial analysis"""
    try:
        j = request.get_json(silent=True) or {}
        session_id = j.get("session_id")
        transcript = j.get("transcript", "")
        
        session = SESSIONS.get(session_id) if session_id else None
        
        current_app.logger.info("analyze.inputs sid=%s has_session=%s transcript_len=%s", 
                                session_id, bool(session), len(transcript or ""))

        # Extract information from conversation
        conversation_text = ""
        if session:
            conversation_text = "\n".join([
                f"{m['role'].upper()}: {m['content']}" 
                for m in session["messages"]
            ])
        elif transcript:
            conversation_text = transcript
        else:
            return jsonify({"error": "No conversation data provided"}), 400
        
        # Use Claude to analyze and score with comprehensive financial calculations
        client = get_claude_client()
        
        analysis_prompt = f"""Based on this conversation about a business project, generate a comprehensive Market IQ scorecard with rigorous financial analysis.

Conversation:
{conversation_text}

Provide a JSON response with the following structure. Return ONLY raw JSON (no markdown/backticks).

{{
  "project_name": "Clear, descriptive project title (NOT 'Unknown' or 'Business Project')",
  "market_iq_score": <integer 1-99, calculated from weighted components>,
  "score_category": "Excellent|Good|Fair|At Risk",
  "summary": "2-3 sentence executive summary",
  
  "component_scores": {{
    "financial_health": <integer 0-100, based on NPV, IRR, margins>,
    "operational_efficiency": <integer 0-100, based on EBITDA margin, payback>,
    "market_position": <integer 0-100, based on competitive strength>,
    "execution_readiness": <integer 0-100, based on team, resources>
  }},
  
  "before_after_financials": {{
    "before": {{
      "revenue": <number>,
      "cogs": <number>,
      "operating_expenses": <number>,
      "ebitda": <number>,
      "ebitda_margin_percent": <number>
    }},
    "after": {{
      "revenue": <number>,
      "cogs": <number>,
      "operating_expenses": <number>,
      "ebitda": <number>,
      "ebitda_margin_percent": <number>
    }}
  }},
  
  "investment_analysis": {{
    "initial_investment": <number>,
    "annual_benefit": <number>,
    "duration_years": <integer>,
    "total_benefit": <number>,
    "roi_percent": <number>,
    "payback_period": <number in years>
  }},
  
  "npv_irr_analysis": {{
    "initial_investment": <number>,
    "discount_rate": <decimal, e.g., 0.10>,
    "cash_flows": [<array of annual cash flows>],
    "npv": <number>,
    "irr": <decimal, e.g., 0.25>,
    "sensitivity": {{
      "npv_at_6": <number>,
      "npv_at_8": <number>,
      "npv_at_10": <number>,
      "npv_at_12": <number>
    }}
  }},
  
  "valuation": {{
    "ebitda": <number>,
    "multiple": <number>,
    "enterprise_value": <number>
  }},
  
  "decision_framework": {{
    "strategic_alignment": <boolean>,
    "npv_positive": <boolean>,
    "irr_above_hurdle": <boolean>,
    "acceptable_payback": <boolean>,
    "robust_sensitivity": <boolean>,
    "overall_recommendation": "Strong Investment|Moderate|High Risk|Do Not Proceed"
  }},
  
  "financial_impact": {{
    "ebitda_at_risk": <number>,
    "roi_opportunity": <number>,
    "projected_ebitda": <number>
  }},
  
  "key_insights": [<array of 3-5 specific, actionable insights>],
  "recommendations": [<array of 3-5 prioritized recommendations>],
  "risks": [<array of 3-5 key risks>]
}}

CALCULATION GUIDELINES:

1. **ROI & Payback:**
   - Total Benefit = Annual Benefit × Duration
   - ROI % = ((Total Benefit - Investment) / Investment) × 100
   - Payback Period = Investment / Annual Benefit

2. **NPV:**
   - NPV = Σ(CF_t / (1 + r)^t) - Initial Investment
   - Calculate for each year's cash flow

3. **IRR:**
   - Find the rate where NPV = 0
   - Use iterative calculation

4. **Sensitivity Analysis:**
   - Calculate NPV at 6%, 8%, 10%, 12% discount rates

5. **Valuation:**
   - Enterprise Value = EBITDA (After) × Industry Multiple

6. **Decision Framework:**
   - Strategic Alignment: Does it support strategy?
   - NPV Positive: Is NPV > 0?
   - IRR Above Hurdle: Is IRR > Discount Rate?
   - Acceptable Payback: Is Payback ≤ 4 years?
   - Robust Sensitivity: Is NPV positive in ≥3 scenarios?
   - Overall: All 5 pass = "Strong Investment", 4 = "Moderate", 3 = "High Risk", ≤2 = "Do Not Proceed"

7. **Component Scoring:**
   - Financial Health (30%): NPV > $1M → 80-100, NPV > 0 → 60-79, NPV marginally positive → 40-59, NPV negative → 0-39
   - Operational Efficiency (20%): EBITDA margin > 25% → 80-100, 15-25% → 60-79, 10-15% → 40-59, < 10% → 0-39
   - Market Position (30%): Strong competitive position → 80-100, Moderate → 60-79, Weak → 40-59
   - Execution Readiness (20%): Proven team, clear plan → 80-100, Capable team → 60-79, Uncertain → 40-59

8. **Overall Score:**
   - Weighted average: (Financial Health × 0.30) + (Operational Efficiency × 0.20) + (Market Position × 0.30) + (Execution Readiness × 0.20)

Be realistic and analytical. Base all scores and calculations on what was actually discussed. If data is missing, make conservative assumptions and note them in key_insights."""

        response = client.messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929"),
            max_tokens=3000,
            temperature=0.3,
            messages=[{"role": "user", "content": analysis_prompt}]
        )
        
        analysis_text = response.content[0].text
        
        # Extract JSON from response
        json_match = re.search(r'\{.*\}', analysis_text, re.DOTALL)
        if json_match:
            analysis_result = json.loads(json_match.group())
        else:
            # If JSON parsing fails, return error - NO HARDCODED FALLBACK
            current_app.logger.error("Failed to parse JSON from Claude response")
            return jsonify({"error": "Failed to generate analysis", "details": "Invalid response format"}), 500
        
        # Normalize project_name - NEVER allow generic names
        _name = analysis_result.get("project_name")
        bad_names = {"", "unknown", "business project", "project", "analysis", "none", "null", "market iq project"}
        if not _name or str(_name).strip().lower() in bad_names:
            # Try to extract from first user message
            _name = None
            try:
                if session and session.get("messages"):
                    for _m in session["messages"]:
                        if _m.get("role") == "user" and _m.get("content"):
                            _name = _m["content"].split("\n",1)[0].strip()[:60]
                            break
            except Exception:
                pass
            if not _name:
                _t = (transcript or "").strip()
                if _t:
                    _name = _t.split("\n",1)[0].strip()[:60]
            analysis_result["project_name"] = _name or "Strategic Initiative"
        
        # Ensure aliases for compatibility
        analysis_result["title"] = analysis_result.get("project_name")
        analysis_result["name"]  = analysis_result.get("project_name")
        
        # Ensure score_category
        try:
            s = int(float(analysis_result.get("market_iq_score", 0)))
        except Exception:
            s = 0
        if not analysis_result.get("score_category"):
            analysis_result["score_category"] = (
                "Excellent" if s >= 80 else 
                "Good" if s >= 60 else 
                "Fair" if s >= 40 else 
                "At Risk"
            )
        
        current_app.logger.info("analysis_result.project_name=%s, market_iq_score=%s", 
                                analysis_result.get("project_name"), 
                                analysis_result.get("market_iq_score"))
        
        return jsonify({"analysis_result": analysis_result}), 200
        
    except Exception as e:
        current_app.logger.exception("analyze_failed")
        return jsonify({"error": "analyze_failed", "details": str(e)}), 500

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
