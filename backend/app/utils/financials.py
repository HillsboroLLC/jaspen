import re

_num = r"-?\d+(?:\.\d+)?"
_ks  = r"(?:k|K|,000)"
def _to_float(tok):
    if tok is None: return None
    s = str(tok).strip().replace(",", "")
    try: return float(s)
    except: return None

def _find(pattern, text, flags=re.I):
    m = re.search(pattern, text, flags)
    return m.group(1) if m else None

def _money(v):
    try:
        n = float(v)
        if abs(n) >= 1e9: return f"${n/1e9:.1f}B"
        if abs(n) >= 1e6: return f"${n/1e6:.1f}M"
        if abs(n) >= 1e3: return f"${n/1e3:.1f}K"
        return f"${n:,.0f}"
    except:
        return "N/A"

def enrich_financials(text: str) -> dict:
    if not isinstance(text, str):
        text = str(text or "")

    # ---- extract inputs ----
    price  = _find(rf"(?:price|pricing)\s*[:=]?\s*\$?\s*({_num})\s*/?\s*(?:mo|month)?", text)
    price  = _to_float(price)

    subs   = _find(rf"(?:subs(?:cribers?)?|customers?)\s*[:=]?\s*({_num})(?:\s*{_ks})?", text)
    if subs:
        if re.search(_ks+"$", subs): subs = subs[:-1]+"000"
    subs   = _to_float(subs)

    margin = _find(rf"(?:margin|gross\s*margin)\s*[:=]?\s*({_num})\s*%", text)
    margin = _to_float(margin)
    if margin is not None and margin > 1.0: margin /= 100.0

    churn  = _find(rf"(?:churn|churn\s*rate|monthly\s*churn)\s*[:=]?\s*({_num})\s*%", text)
    churn  = _to_float(churn)
    if churn is not None and churn > 1.0: churn /= 100.0

    cac    = _find(r"(?:cac|acq(?:uisition)?\s*cost)\s*[:=]?\s*\$?\s*("+_num+")", text)
    cac    = _to_float(cac)

    budget = _find(rf"(?:budget|capex|investment)\s*[:=]?\s*\$?\s*({_num})(?:\s*{_ks})?", text)
    if budget and re.search(_ks+"$", budget): budget = budget[:-1]+"000"
    budget = _to_float(budget)

    # ---- compute annualized figures (simple model) ----
    # annual revenue = price * subs * 12
    # gross profit   = revenue * margin
    # churn backfill = subs * churn per month -> 12 months * CAC cost
    # projected EBITDA = gross profit - churn_acq_cost
    # ROI opportunity  = projected EBITDA / budget (if budget)
    annual_revenue   = None
    gross_profit     = None
    churn_acq_cost   = None
    projected_ebitda = None
    roi              = None

    if all(x is not None for x in (price, subs)):
        annual_revenue = price * subs * 12.0
    if annual_revenue is not None and margin is not None:
        gross_profit = annual_revenue * margin
    if subs is not None and churn is not None and cac is not None:
        churn_acq_cost = subs * churn * 12.0 * cac
    if gross_profit is not None and churn_acq_cost is not None:
        projected_ebitda = gross_profit - churn_acq_cost
    if projected_ebitda is not None and budget not in (None, 0):
        roi = projected_ebitda / budget

    # qualitative risk
    risk = "TBD"
    if projected_ebitda is not None and budget is not None:
        ratio = projected_ebitda / max(1.0, budget)
        if ratio >= 0.6:   risk = "Low"
        elif ratio >= 0.3: risk = "Medium"
        else:              risk = "High"

    out = {
        "financial_impact": {
            "projected_ebitda": _money(projected_ebitda) if projected_ebitda is not None else "TBD",
            "roi_opportunity": f"{roi*100:.0f}%" if roi is not None else "TBD",
            "potential_loss": _money(max(0.0, (budget or 0.0) - (projected_ebitda or 0.0))) if budget is not None and projected_ebitda is not None else "TBD",
            "ebitda_at_risk": risk,
            "annual_revenue": _money(annual_revenue) if annual_revenue is not None else "TBD",
            "gross_profit": _money(gross_profit) if gross_profit is not None else "TBD",
        },
        "_calc_inputs": {
            "price_per_month": price,
            "subscribers": subs,
            "gross_margin": margin,
            "monthly_churn": churn,
            "cac": cac,
            "budget": budget,
        }
    }
    return out
