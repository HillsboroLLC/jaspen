from __future__ import annotations
from typing import Dict, Any

class SimpleFinancialScorer:
    """
    Minimal, deterministic scorer that returns a readiness_percent (0..100).
    It blends a few common features; everything is optional and safely defaulted.
    """

    def __init__(self) -> None:
        pass

    @staticmethod
    def _num(v: Any, default: float = 0.0) -> float:
        try:
            n = float(v)
            if n != n:  # NaN
                return default
            return n
        except Exception:
            return default

    def score(self, fx: Dict[str, Any]) -> Dict[str, int]:
        # Pull features with safe defaults
        price_month        = self._num(fx.get("price_month"))
        subscribers        = self._num(fx.get("subscribers"))
        gross_margin       = self._num(fx.get("gross_margin"))          # expect 0..100
        budget             = self._num(fx.get("budget"))
        plan_months        = self._num(fx.get("plan_months"))
        revenue            = self._num(fx.get("revenue"))
        assets             = self._num(fx.get("assets"))
        liabilities        = self._num(fx.get("liabilities"))
        ebit               = self._num(fx.get("ebit"))
        cash_flow_oper     = self._num(fx.get("cash_flow_oper"))
        cac_payback_months = self._num(fx.get("cac_payback_months"))
        ltv                = self._num(fx.get("ltv"))
        has_mrr            = 1.0 if int(self._num(fx.get("has_mrr"))) == 1 else 0.0

        # Normalize/clip a few signals to 0..1
        def clip01(x: float) -> float:
            return max(0.0, min(1.0, x))

        # Very rough-and-ready normalizations
        n_margin   = clip01(gross_margin / 80.0)   # treat 80% as very strong
        n_subs     = clip01(subscribers / 10000.0) # cap “strong” at 10k subs
        n_price    = clip01(price_month / 200.0)   # cap “strong” at $200/mo
        n_budget   = clip01(budget / 1_000_000.0)  # cap at $1M
        n_plan     = clip01(plan_months / 18.0)    # 18 mo plan is good
        n_revenue  = clip01(revenue / 5_000_000.0) # cap at $5M
        n_assets   = clip01(max(0.0, assets) / max(1.0, abs(liabilities))) if liabilities != 0 else clip01(assets / 1_000_000.0)
        n_ebit     = clip01(max(0.0, ebit) / 1_000_000.0)        # cap at $1M
        n_cfo      = clip01(max(0.0, cash_flow_oper) / 1_000_000.0)

        # CAC payback: shorter is better
        n_cac_pb   = 1.0 - clip01(cac_payback_months / 18.0)     # <=18mo is okay-ish

        # LTV: larger is better; scale loosely
        n_ltv      = clip01(ltv / 5_000.0)                       # cap at $5k

        # A gentle weighted blend (sums to 1.0)
        score01 = (
            0.18 * n_margin +
            0.12 * n_subs +
            0.08 * n_price +
            0.10 * n_revenue +
            0.08 * n_assets +
            0.08 * n_ebit +
            0.06 * n_cfo +
            0.10 * n_cac_pb +
            0.10 * n_ltv +
            0.06 * n_plan +
            0.04 * n_budget +
            0.10 * has_mrr
        )

        # Guardrails: tiny bump if they have *some* revenue but low normalizations
        if revenue > 0 and score01 < 0.2:
            score01 = min(1.0, score01 + 0.05)

        return {"readiness_percent": int(round(score01 * 100))}
