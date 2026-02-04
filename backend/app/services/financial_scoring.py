"""
Validated financial scoring module for Market IQ readiness.

- Deterministic baseline: Altman Z-Score + Piotroski F-Score -> 0..100 readiness.
- Optional ML overlay: plug a trained Skorecard/scorecardpy model for PD; map to readiness.
- Clean seam: pass in calculator-parsed features; get back readiness + details + contributions.

Usage in compute_readiness():
    from app.services.financial_scoring import ReadinessScorer
    scorer = ReadinessScorer(model=None)
    score_res = scorer.score(features_dict)
    overall_pct = score_res.readiness_percent
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, Optional


@dataclass
class ScoreResult:
    readiness_percent: int
    details: Dict[str, Any]
    contributions: Dict[str, float]


# ---------------------------
# Classic, validated formulas
# ---------------------------

def altman_z_score(
    working_capital: float,
    retained_earnings: float,
    ebit: float,
    market_value_equity: float,
    total_liabilities: float,
    sales: float,
    total_assets: float,
) -> float:
    """
    Altman Z (public manufacturing version):
      Z = 1.2*X1 + 1.4*X2 + 3.3*X3 + 0.6*X4 + 1.0*X5
      X1=WC/TA, X2=RE/TA, X3=EBIT/TA, X4=MVE/TL, X5=Sales/TA
    """
    # why: guard against division by zero / missing data
    if total_assets <= 0 or total_liabilities <= 0:
        return 0.0
    x1 = working_capital / total_assets
    x2 = retained_earnings / total_assets
    x3 = ebit / total_assets
    x4 = market_value_equity / total_liabilities
    x5 = sales / total_assets
    return 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5


def piotroski_f_score(
    roa_pos: bool,
    cfo_pos: bool,
    delta_roa_pos: bool,
    accruals_pos: bool,
    leverage_down: bool,
    liquidity_up: bool,
    shares_not_issued: bool,
    gross_margin_up: bool,
    asset_turnover_up: bool,
) -> int:
    """
    Piotroski F-Score in [0,9]. Each boolean adds 1.
    Derive these booleans from your calculator metrics/deltas.
    """
    flags = [
        roa_pos,
        cfo_pos,
        delta_roa_pos,
        accruals_pos,
        leverage_down,
        liquidity_up,
        shares_not_issued,
        gross_margin_up,
        asset_turnover_up,
    ]
    return sum(1 for f in flags if bool(f))


# ------------------------------------------------------
# Readiness aggregator with seam for a trained scorecard
# ------------------------------------------------------

class ReadinessScorer:
    """
    scorer = ReadinessScorer(model=None)        # classic-only
    res = scorer.score(features_from_calculator)

    Later:
      from joblib import load
      model = load("app/models/readiness.pkl")  # Skorecard/scorecardpy logistic
      scorer = ReadinessScorer(model=model)
    """
    def __init__(self, model: Optional[object] = None):
        self.model = model  # plug-in ML model (must expose predict_proba)

    def score(self, fx: Dict[str, Any]) -> ScoreResult:
        # ----- 1) Classic baseline -----
        z = altman_z_score(
            working_capital=fx.get("working_capital", 0.0) or 0.0,
            retained_earnings=fx.get("retained_earnings", 0.0) or 0.0,
            ebit=fx.get("ebit", 0.0) or 0.0,
            market_value_equity=fx.get("market_value_equity", fx.get("equity_mv", 0.0) or 0.0),
            total_liabilities=fx.get("total_liabilities", fx.get("liabilities", 0.0) or 0.0),
            sales=fx.get("sales", fx.get("revenue", 0.0) or 0.0),
            total_assets=fx.get("total_assets", 0.0) or 0.0,
        )

        f = piotroski_f_score(
            roa_pos=(fx.get("roa") or 0.0) > 0,
            cfo_pos=(fx.get("cfo") or 0.0) > 0,
            delta_roa_pos=(fx.get("roa_delta") or 0.0) > 0,
            accruals_pos=((fx.get("cfo") or 0.0) - (fx.get("net_income") or 0.0)) > 0,
            leverage_down=(fx.get("leverage_delta") or 0.0) < 0,
            liquidity_up=(fx.get("current_ratio_delta") or 0.0) > 0,
            shares_not_issued=(fx.get("shares_out_delta") or 0.0) <= 0,
            gross_margin_up=(fx.get("gross_margin_delta") or 0.0) > 0,
            asset_turnover_up=(fx.get("asset_turnover_delta") or 0.0) > 0,
        )

        z_norm = _scale_altman_z_to_pct(z)
        f_norm = int(round((f / 9.0) * 100))
        classic_pct = int(round(0.6 * z_norm + 0.4 * f_norm))  # weight Z higher

        details = {
            "altman_z": z,
            "altman_z_pct": z_norm,
            "piotroski_f": f,
            "piotroski_f_pct": f_norm,
        }
        contributions = {
            "altman_z": 0.6 * z_norm,
            "piotroski_f": 0.4 * f_norm,
        }

        # ----- 2) Optional ML overlay (Skorecard/scorecardpy logistic) -----
        if self.model is not None:
            try:
                X = self._vectorize(fx)
                proba = float(self.model.predict_proba(X)[:, 1][0])  # PD
                ml_pct = int(round((1.0 - proba) * 100))  # lower PD => higher readiness
                details["model_prob_default"] = proba
                details["model_readiness_pct"] = ml_pct
                final_pct = int(round(0.5 * classic_pct + 0.5 * ml_pct))
                contributions["ml_overlay"] = 0.5 * ml_pct
                return ScoreResult(final_pct, details, contributions)
            except Exception:
                # why: if model input/schema mismatches, fall back gracefully
                pass

        return ScoreResult(classic_pct, details, contributions)

    def _vectorize(self, fx: Dict[str, Any]):
        """
        Minimal vectorizer: ensure the same order used during training.
        Replace with your pipeline's transformer (e.g., ColumnTransformer).
        """
        import numpy as np
        feature_order = [
            # commercial signals
            "price_month", "subscribers", "gross_margin",
            "cac", "ltv", "cac_payback_months",
            "budget", "plan_months",
            # unit economics / runway
            "burn_rate", "runway_months",
            # financial statements
            "revenue", "sales", "ebit", "cfo",
            "total_assets", "total_liabilities",
            "current_ratio", "asset_turnover",
        ]
        vals = [float((fx.get(k) or 0.0)) for k in feature_order]
        return np.array([vals])


def _scale_altman_z_to_pct(z: float) -> int:
    """
    Map Altman Z to 0..100 with conventional zones; smooth & bounded.
    """
    if z is None:
        return 0
    try:
        z = float(z)
    except (TypeError, ValueError):
        return 0
    if z <= 1.0:
        return 5
    if z <= 1.81:
        return int(5 + (z - 1.0) / 0.81 * 15)      # 5..20
    if z <= 2.99:
        return int(20 + (z - 1.81) / 1.18 * 50)    # 20..70
    if z <= 4.0:
        return int(70 + (z - 2.99) / 1.01 * 20)    # 70..90
    return 95
