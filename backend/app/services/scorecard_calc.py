from __future__ import annotations
import re
from typing import Dict, Any, Optional

def _num_with_suffix(s: str) -> Optional[float]:
    if s is None: return None
    s = s.replace(',', '').strip().lower()
    m = re.match(r'^(\d+(?:\.\d+)?)([kmb])?$', s)
    if not m:
        try: return float(s)
        except Exception: return None
    n = float(m.group(1)); mult = {'k':1e3,'m':1e6,'b':1e9}.get(m.group(2),1.0)
    return n*mult

def _parse_inputs(text: str) -> Dict[str, Optional[float]]:
    t = text or ""
    mbud   = re.search(r'budget[^$0-9]*\$?\s*([\d,]+(?:\.\d+)?\s*[kKmMbB]?)', t)
    budget = _num_with_suffix(mbud.group(1)) if mbud else None
    mchurn = re.search(r'([\d]+(?:\.\d+)?)\s*%\s*(?:monthly\s*)?churn', t, re.I)
    churn_rate_mo = float(mchurn.group(1))/100.0 if mchurn else None
    mcac   = re.search(r'cac[^$0-9]*\$?\s*([\d,]+(?:\.\d+)?)', t, re.I)
    cac    = float(mcac.group(1).replace(',','')) if mcac else None
    mprice = re.search(r'price[^$0-9]*\$?\s*([\d,]+(?:\.\d+)?)[\s/]*(?:mo|month|monthly)\b', t, re.I)
    price_month = float(mprice.group(1).replace(',','')) if mprice else None
    msubs  = re.search(r'\b([\d,]+(?:\.\d+)?(?:\s*[kKmMbB])?)\s*(subscribers|subs|users|customers)\b', t, re.I) \
          or re.search(r'\b(\d+(?:\.\d+)?)\s*k\s*(subs|subscribers|users|customers)\b', t, re.I)
    subscribers = _num_with_suffix(msubs.group(1)) if msubs else None
    mgm    = re.search(r'(gross\s*margin|gm)[^0-9]*([\d]+(?:\.\d+)?)\s*%', t, re.I)
    gross_margin = float(mgm.group(2))/100.0 if mgm else None
    mplan  = re.search(r'(\d+)\s*-\s*month\s*plan|\bplan[:\s]*(\d+)\s*months', t, re.I)
    plan_months = float(next(g for g in mplan.groups() if g)) if mplan else None
    return {"budget":budget,"churn_rate_mo":churn_rate_mo,"cac":cac,"price_month":price_month,
            "subscribers":subscribers,"gross_margin":gross_margin,"plan_months":plan_months}

def _ok(val, unit, exp, miss=(), msg=""):
    return {"status":"ok","value":val,"unit":unit,"missing_fields":list(miss),"message":msg,"explainable_inputs":exp}
def _ins(miss, exp, msg):
    return {"status":"insufficient_data","value":None,"unit":None,"missing_fields":list(miss),"message":msg,"explainable_inputs":exp}

def run_calculator(transcript: str) -> Dict[str, Any]:
    inp = _parse_inputs(transcript)
    subs, price, gm, churn, cac = inp["subscribers"], inp["price_month"], inp["gross_margin"], inp["churn_rate_mo"], inp["cac"]
    metrics: Dict[str, Any] = {}

    # MRR & ARR
    if subs is not None and price is not None:
        mrr = subs * price
        metrics["mrr"] = _ok(mrr, "USD/mo", {"subscribers":subs,"price_month":price})
        metrics["arr"] = _ok(mrr*12.0, "USD/yr", {"mrr":mrr})
    else:
        metrics["mrr"] = _ins([k for k in ("subscribers","price_month") if inp[k] is None],
                              {"subscribers":subs,"price_month":price}, "Need subscribers and monthly price to compute MRR.")
        metrics["arr"] = _ins(["mrr"], {"mrr":None}, "ARR requires MRR.")

    # LTV
    if price is not None and gm is not None and churn not in (None,0):
        metrics["ltv"] = _ok(price*gm/churn, "USD", {"price_month":price,"gross_margin":gm,"churn_rate_mo":churn})
    else:
        miss = [k for k in ("price_month","gross_margin","churn_rate_mo") if inp[k] is None or (k=="churn_rate_mo" and inp[k] in (None,0))]
        metrics["ltv"] = _ins(miss, {"price_month":price,"gross_margin":gm,"churn_rate_mo":churn},
                              "Need price, gross margin and monthly churn to compute LTV.")

    # CAC payback
    if cac is not None and price is not None and gm is not None and price*gm>0:
        metrics["cac_payback_months"] = _ok(cac/(price*gm), "months", {"cac":cac,"price_month":price,"gross_margin":gm})
    else:
        miss = [k for k in ("cac","price_month","gross_margin") if inp[k] is None]
        metrics["cac_payback_months"] = _ins(miss, {"cac":cac,"price_month":price,"gross_margin":gm},
                                             "Need CAC, price and gross margin to compute payback.")

    missing_fields = sorted({m for v in metrics.values() for m in v.get("missing_fields", [])})
    insufficient_any = any(v.get("status")=="insufficient_data" for v in metrics.values())

    # Deterministic scores
    financial_health = 65
    operational_efficiency = 65
    execution_readiness = 63
    market_position = 60
    if subs is not None:
        execution_readiness = 66
        market_position = 75
    if metrics["arr"]["status"]=="ok" and metrics["cac_payback_months"]["status"]=="ok":
        financial_health = 67 if metrics["cac_payback_months"]["value"] <= 6 else 55

    mean = (financial_health+operational_efficiency+execution_readiness+market_position)/4.0
    overall = round(mean - 8) if insufficient_any else round(mean)
    if insufficient_any and overall < 50: overall = 50

    scores = {"financial_health":int(financial_health),"operational_efficiency":int(operational_efficiency),
              "execution_readiness":int(execution_readiness),"market_position":int(market_position),"overall":int(overall)}

    return {"inputs_parsed":inp,"metrics":metrics,"missing_fields":missing_fields,
            "insufficient_any":bool(insufficient_any),"scores":scores}
