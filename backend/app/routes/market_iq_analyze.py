from __future__ import annotations
import os, json, uuid, re
from copy import deepcopy
from pathlib import Path
from typing import Dict, Any
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required
from app.decorators.subscription import subscription_required
import anthropic

# Import enhanced finance calculator
try:
    from app.services.finance_calc import run_comprehensive_analysis, calculate_dynamic_scores
except Exception:
    run_comprehensive_analysis = None
    calculate_dynamic_scores = None

# Import legacy calculator for backward compatibility
try:
    from app.services.scorecard_calc import run_calculator
except Exception:
    try:
        from ..services.scorecard_calc import run_calculator
    except Exception:
        run_calculator = None

market_iq_analyze_bp = Blueprint("market_iq_analyze", __name__)

ROOT = Path(__file__).resolve().parents[2]
SESS_DIR = Path(os.getenv("SESSION_DIR", ROOT / "runtime" / "sessions"))

def _load_transcript(session_id: str) -> str:
    p = SESS_DIR / f"{session_id}.json"
    if p.exists():
        try:
            j = json.loads(p.read_text()); hist = j.get("history", [])
            lines=[]
            for m in hist:
                role = "User" if m.get("role")=="user" else "AI"
                c = (m.get("content") or "").strip()
                if c: lines.append(f"{role}: {c}")
            return "\n".join(lines)
        except Exception:
            return ""
    return ""

def _get_claude_client():
    """
    Use CLAUDE_API_KEY (preferred) or ANTHROPIC_API_KEY from env or Flask config.
    Raise if missing. No fallback.
    """
    key = (
        os.environ.get("CLAUDE_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or current_app.config.get("CLAUDE_API_KEY")
        or current_app.config.get("ANTHROPIC_API_KEY")
    )
    if not key:
        raise ValueError("CLAUDE_API_KEY/ANTHROPIC_API_KEY not configured")
    return anthropic.Anthropic(api_key=key)

def _build_compat(result: Dict[str, Any]) -> Dict[str, Any]:
    comps = result.get("component_scores") or {}
    fins  = result.get("financial_impact") or {}
    return {
        "title": result.get("project_name") or "Market IQ Project",
        "score": result.get("market_iq_score"),
        "components": {
            "financialHealth":       int(comps.get("financial_health") or 0),
            "operationalEfficiency": int(comps.get("operational_efficiency") or 0),
            "marketPosition":        int(comps.get("market_position") or 0),
            "executionReadiness":    int(comps.get("execution_readiness") or 0),
        },
        "financials": {
            "ebitdaAtRisk":    fins.get("ebitda_at_risk"),
            "roiOpportunity":  fins.get("roi_opportunity"),
            "projectedEbitda": fins.get("projected_ebitda"),
            "potentialLoss":   fins.get("potential_loss"),
        },
    }

def _normalize_for_calc(text: str) -> str:
    """Make common phrases calculator-friendly (very conservative)."""
    if not text:
        return text
    import re
    # "20k subs" → "20000 subscribers", also handles users/customers
    def repl_k(m):
        n = float(m.group(1))
        return f"{int(n * 1000)} subscribers"
    text = re.sub(r'\b(\d+(?:\.\d+)?)\s*k\s*(subs|subscribers|users|customers)\b',
                  repl_k, text, flags=re.IGNORECASE)
    # Normalize synonyms to "subscribers"
    text = re.sub(r'\bsubs\b', 'subscribers', text, flags=re.IGNORECASE)
    text = re.sub(r'\busers\b', 'subscribers', text, flags=re.IGNORECASE)
    text = re.sub(r'\bcustomers\b', 'subscribers', text, flags=re.IGNORECASE)
    # Friendly alias for margin
    text = re.sub(r'\bgm\b', 'gross margin', text, flags=re.IGNORECASE)
    return text

@market_iq_analyze_bp.route("/analyze", methods=["POST"])
@jwt_required(optional=True)
@subscription_required
def analyze_from_conversation():
    """
    Enhanced Claude analysis with comprehensive financial calculations.
    Request:  {session_id?, transcript?}
    Response: {analysis_result, analysis_id}
    """
    pld = request.get_json(silent=True) or {}
    sid = (pld.get("session_id") or "").strip()
    transcript = (pld.get("transcript") or "").strip() or (_load_transcript(sid) if sid else "")
    current_app.logger.info("analyze[enhanced]: sid=%s chars=%d", sid or "-", len(transcript))

    if not transcript:
        return jsonify({"error":"No transcript"}), 400

    # Enhanced prompt for comprehensive financial analysis
    prompt = f"""You are a top 0.1% senior financial analyst and strategic advisor. Analyze the conversation below and return a comprehensive Market IQ scorecard with rigorous financial analysis as STRICT JSON (no prose, no markdown).

Conversation Transcript:
{transcript}

Return a SINGLE JSON object with the following structure:

{{
  "project_name": "Clear, descriptive project title (NOT 'Unknown' or 'Business Project')",
  "market_iq_score": <integer 1-99>,
  "score_category": "Excellent|Good|Fair|At Risk",
  "summary": "2-3 sentence executive summary",
  
  "component_scores": {{
    "financial_health": <integer 0-100>,
    "operational_efficiency": <integer 0-100>,
    "market_position": <integer 0-100>,
    "execution_readiness": <integer 0-100>
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
    "projected_ebitda": <number>,
    "potential_loss": <number>
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

7. **Component Scoring (Base on actual metrics):**
   - Financial Health: NPV > $1M → 80-100, NPV > 0 → 60-79, NPV marginally positive → 40-59, NPV negative → 0-39
   - Operational Efficiency: EBITDA margin > 25% → 80-100, 15-25% → 60-79, 10-15% → 40-59, < 10% → 0-39
   - Market Position: Strong competitive position → 80-100, Moderate → 60-79, Weak → 40-59
   - Execution Readiness: Proven team, clear plan → 80-100, Capable team → 60-79, Uncertain → 40-59

8. **Overall Score:**
   - Weighted average: (Financial Health × 0.30) + (Operational Efficiency × 0.20) + (Market Position × 0.30) + (Execution Readiness × 0.20)

Rules:
- Output MUST be pure JSON (no backticks, no markdown).
- All financial values must be numbers (not strings with $ or commas).
- If data is missing, make conservative assumptions and note them in key_insights.
- Base all calculations on what was actually discussed in the conversation.
"""

    # LLM client
    try:
        client = _get_claude_client()
    except Exception as e:
        current_app.logger.exception("Claude key/config missing")
        return jsonify({"error":"llm_unconfigured","details":str(e)}), 500

    # Call Claude
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=3000,
            temperature=0.3,
            messages=[{"role":"user","content":prompt}],
        )
        raw = (resp.content[0].text or "").strip()
    except Exception as e:
        current_app.logger.exception("Claude call failed")
        return jsonify({"error":"llm_unavailable","details":str(e)[:300]}), 502

    # Parse strict JSON
    m = re.search(r"\{[\s\S]*\}\s*\Z", raw) or re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return jsonify({"error":"invalid_llm_response","details":"No JSON object detected"}), 502

    try:
        result = json.loads(m.group(0))
    except Exception as e:
        return jsonify({"error":"invalid_llm_json","details":str(e)[:300]}), 502

    if not isinstance(result, dict):
        return jsonify({"error":"invalid_llm_payload","details":"Top-level must be object"}), 502

    comps = result.get("component_scores") or {}
    required_comp_keys = {"market_position","execution_readiness","financial_health","operational_efficiency"}
    if "market_iq_score" not in result or not required_comp_keys.issubset(comps.keys()):
        return jsonify({"error":"invalid_llm_payload","details":"Missing required scores"}), 502

    # Normalize optional fields
    result.setdefault("financial_impact", {})
    result.setdefault("key_insights", [])
    result.setdefault("recommendations", [])
    if "top_risks" not in result:
        result["top_risks"] = result.get("risks", [])

    # Ensure project name is never generic
    _name = result.get("project_name")
    bad_names = {"", "unknown", "business project", "project", "analysis", "none", "null", "market iq project"}
    if not _name or str(_name).strip().lower() in bad_names:
        # Try to extract from transcript
        _name = None
        try:
            lines = transcript.split("\n")
            for line in lines:
                if line.strip() and not line.startswith("AI:"):
                    _name = line.replace("User:", "").strip()[:60]
                    break
        except Exception:
            pass
        result["project_name"] = _name or "Strategic Initiative"

    # Meta + id
    result.setdefault("_meta", {})["source"] = "claude_enhanced"
    result["_meta"]["llm_used"] = True
    result["analysis_id"] = sid or f"analysis_{uuid.uuid4().hex[:8]}"

    # Build compat mirror
    try:
        result["compat"] = _build_compat(result)
    except Exception:
        pass

    # === Enhanced financial calculations (if available) ===
    if run_comprehensive_analysis and calculate_dynamic_scores:
        try:
            # Extract data for comprehensive analysis
            inv_analysis = result.get("investment_analysis", {})
            npv_analysis = result.get("npv_irr_analysis", {})
            before_after = result.get("before_after_financials", {})
            
            if inv_analysis and npv_analysis:
                # Run comprehensive analysis to validate/enhance Claude's calculations
                data = {
                    'initial_investment': inv_analysis.get('initial_investment'),
                    'annual_benefit': inv_analysis.get('annual_benefit'),
                    'duration_years': inv_analysis.get('duration_years', 5),
                    'discount_rate': npv_analysis.get('discount_rate', 0.10),
                    'ebitda_after': before_after.get('after', {}).get('ebitda'),
                    'ebitda_multiple': result.get('valuation', {}).get('multiple', 8.0),
                    'strategic_alignment': result.get('decision_framework', {}).get('strategic_alignment', True)
                }
                
                # Only run if we have minimum required data
                if data['initial_investment'] and data['annual_benefit']:
                    comprehensive = run_comprehensive_analysis(data)
                    
                    # Merge comprehensive calculations with Claude's results
                    if comprehensive:
                        result.update(comprehensive)
                        
                        # Calculate dynamic scores based on actual financial metrics
                        npv = comprehensive.get('npv_irr_analysis', {}).get('npv')
                        irr = comprehensive.get('npv_irr_analysis', {}).get('irr')
                        payback = comprehensive.get('investment_analysis', {}).get('payback_period')
                        roi_pct = comprehensive.get('investment_analysis', {}).get('roi_percent')
                        
                        ebitda_after = before_after.get('after', {}).get('ebitda', 0)
                        revenue_after = before_after.get('after', {}).get('revenue', 1)
                        ebitda_margin = ebitda_after / revenue_after if revenue_after > 0 else 0
                        
                        dynamic_scores = calculate_dynamic_scores(
                            npv=npv,
                            irr=irr,
                            discount_rate=data['discount_rate'],
                            payback_period=payback,
                            ebitda_margin=ebitda_margin,
                            roi_percent=roi_pct,
                            market_position_qualitative=comps.get('market_position', 70),
                            execution_readiness_qualitative=comps.get('execution_readiness', 65)
                        )
                        
                        # Update scores with dynamically calculated values
                        result['component_scores'].update(dynamic_scores)
                        result['market_iq_score'] = dynamic_scores['overall']
                        
                        # Update score category
                        s = dynamic_scores['overall']
                        result['score_category'] = (
                            "Excellent" if s >= 80 else 
                            "Good" if s >= 60 else 
                            "Fair" if s >= 40 else 
                            "At Risk"
                        )
                        
                        result["_meta"]["enhanced_calculations"] = True
                        current_app.logger.info("Enhanced calculations applied: NPV=%s, IRR=%s, Score=%s", 
                                                npv, irr, dynamic_scores['overall'])
        except Exception as e:
            current_app.logger.exception("Enhanced calculations failed, using Claude's values")
            result["_meta"]["enhanced_calc_error"] = str(e)[:200]

    # === Legacy calculator attachment (for backward compatibility) ===
    if run_calculator:
        try:
            norm_text = _normalize_for_calc(transcript)
            calc_out = run_calculator(norm_text)
            if isinstance(calc_out, dict):
                result.setdefault("_meta", {})["calc_attached"] = True
                result["_calc"] = {
                    "inputs_parsed":    calc_out.get("inputs_parsed"),
                    "metrics":          calc_out.get("metrics"),
                    "scores":           calc_out.get("scores"),
                    "insufficient_any": calc_out.get("insufficient_any"),
                    "missing_fields":   calc_out.get("missing_fields"),
                }
        except Exception as e:
            result["_calc_error"] = str(e)[:200]

    return jsonify({"analysis_result": result, "analysis_id": result["analysis_id"]})

@market_iq_analyze_bp.route("/scenario", methods=["POST"])
@jwt_required(optional=True)
@subscription_required
def scenario_apply():
    """
    Accepts {analysis_id, analysis_result, changes}
    Supports:
      - market_iq_score: +/− int
      - component_scores: {key: +/−int}
      - financial_impact: {key: any}
      - budget: { deltaPercent: number }
    """
    p = request.get_json(silent=True) or {}
    analysis = deepcopy(p.get("analysis_result") or {})
    if not analysis:
        return jsonify({"error":"analysis_result_required"}), 400
    changes = p.get("changes") or {}

    def clamp(v, lo, hi):
        try: return int(max(lo, min(hi, int(v))))
        except Exception: return v

    if isinstance(changes.get("market_iq_score"), (int, float)):
        analysis["market_iq_score"] = clamp(
            analysis.get("market_iq_score", 60) + int(changes["market_iq_score"]), 1, 99
        )

    comps = analysis.setdefault("component_scores", {})
    for k, v in (changes.get("component_scores") or {}).items():
        try: comps[k] = clamp(int(comps.get(k, 60)) + int(v), 0, 100)
        except Exception: pass

    fin = analysis.setdefault("financial_impact", {})
    for k, v in (changes.get("financial_impact") or {}).items(): fin[k] = v

    b = (changes.get("budget") or {})
    try: dp = float(b.get("deltaPercent", None))
    except Exception: dp = None
    if dp is not None:
        delta_score = clamp(round(dp/20.0), -5, 5)
        delta_exec  = clamp(round(dp/10.0), -6, 6)
        delta_fin   = clamp(round(dp/15.0), -6, 6)
        analysis["market_iq_score"] = clamp(analysis.get("market_iq_score", 60) + delta_score, 1, 99)
        comps["execution_readiness"] = clamp(int(comps.get("execution_readiness", 60)) + delta_exec, 0, 100)
        comps["financial_health"]    = clamp(int(comps.get("financial_health", 60)) + delta_fin, 0, 100)
        roi = fin.get("roi_opportunity", "Moderate")
        if dp >= 20: roi = "Higher"
        elif dp <= -20: roi = "Lower"
        fin["roi_opportunity"] = roi
        analysis.setdefault("scenario_changes_applied", {})["budget"] = {"deltaPercent": dp}

    return jsonify(analysis)
