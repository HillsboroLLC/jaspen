"""
Purpose: Unified scenario calculation engine that combines all existing calculation logic.

This service integrates:
- finance_calculator.py: Real NPV, IRR, Payback calculations
- financial_scoring.py: Altman Z-Score + Piotroski F-Score
- scorecard_calc.py: SaaS metrics (MRR, ARR, LTV, CAC Payback)

Used by:
- ai_agent.py: Generate baseline analysis from conversation
- market_iq_analyze.py: Calculate scenario results with real formulas
- ai_agent_scenarios.py: Provide lever schema for scenario modeling
"""

from typing import Dict, Any, List, Optional
import sys
import os

# Import existing calculation modules
from app.services.finance_calc import (
    calculate_npv,
    calculate_irr,
    calculate_roi,
    calculate_sensitivity_analysis,
    _safe_float,
    _safe_percent
)

from app.services.financial_scoring import ReadinessScorer


class ScenarioCalculator:
    """
    Unified calculator that uses all existing calculation engines.
    Provides consistent calculation logic for baseline and scenario analysis.
    """
    
    def __init__(self):
        self.scorer = ReadinessScorer()
        self.default_discount_rate = 0.10  # 10% default discount rate
    
    def calculate_baseline(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate baseline analysis from parsed inputs.
        
        Args:
            inputs: Dictionary of parsed inputs from conversation or form
                   Expected keys: budget, plan_months, subscribers, price_month,
                   gross_margin, churn_rate_mo, cac, revenue, etc.
        
        Returns:
            Complete analysis with scores, metrics, and financial calculations
        """
        # 1. Calculate SaaS metrics
        metrics = self._calculate_saas_metrics(inputs)
        
        # 2. Calculate financial metrics (NPV/IRR/Payback)
        financial_analysis = self._calculate_financials(inputs)
        
        # 3. Calculate component scores
        scores = self._calculate_scores(inputs, metrics)
        
        # 4. Calculate readiness score
        readiness = self.scorer.score(inputs)
        
        return {
            "inputs": inputs,
            "metrics": metrics,
            "scores": scores,
            "overall_score": scores.get("overall", 0),
            "financial_analysis": financial_analysis,
            "readiness_percent": getattr(readiness, "readiness_percent", 0),
            "calculation_method": "comprehensive"
        }
    
    def calculate_scenario(
        self,
        baseline_inputs: Dict[str, Any],
        deltas: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Calculate scenario by applying deltas to baseline.
        Recalculates everything using real formulas.
        
        Args:
            baseline_inputs: Original baseline inputs
            deltas: Changes to apply (e.g., {"budget": 600000, "plan_months": 10})
        
        Returns:
            Complete scenario analysis with updated scores and metrics
        """
        # 1. Merge baseline + deltas
        scenario_inputs = {**baseline_inputs}
        scenario_inputs.update(deltas)
        
        # 2. Recalculate everything
        return self.calculate_baseline(scenario_inputs)
    
    def _calculate_saas_metrics(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate SaaS-specific metrics: MRR, ARR, LTV, CAC Payback.
        Based on logic from scorecard_calc.py but enhanced.
        """
        subs = _safe_float(inputs.get("subscribers", 0))
        price = _safe_float(inputs.get("price_month", 0))
        gm = _safe_percent(inputs.get("gross_margin", 0))
        churn = _safe_percent(inputs.get("churn_rate_mo", 0))
        cac = _safe_float(inputs.get("cac", 0))
        
        metrics = {}
        
        # MRR & ARR
        if subs > 0 and price > 0:
            mrr = subs * price
            metrics["mrr"] = {
                "value": mrr,
                "unit": "USD/mo",
                "status": "ok",
                "explainable_inputs": {"subscribers": subs, "price_month": price}
            }
            metrics["arr"] = {
                "value": mrr * 12,
                "unit": "USD/yr",
                "status": "ok",
                "explainable_inputs": {"mrr": mrr}
            }
        else:
            missing = []
            if not subs: missing.append("subscribers")
            if not price: missing.append("price_month")
            metrics["mrr"] = {
                "status": "insufficient_data",
                "missing_fields": missing,
                "message": "Need subscribers and monthly price to compute MRR"
            }
            metrics["arr"] = {
                "status": "insufficient_data",
                "missing_fields": ["mrr"],
                "message": "ARR requires MRR"
            }
        
        # LTV
        if price > 0 and gm > 0 and churn > 0:
            ltv = (price * gm) / churn
            metrics["ltv"] = {
                "value": ltv,
                "unit": "USD",
                "status": "ok",
                "explainable_inputs": {
                    "price_month": price,
                    "gross_margin": gm,
                    "churn_rate_mo": churn
                }
            }
        else:
            missing = []
            if not price: missing.append("price_month")
            if not gm: missing.append("gross_margin")
            if not churn: missing.append("churn_rate_mo")
            metrics["ltv"] = {
                "status": "insufficient_data",
                "missing_fields": missing,
                "message": "Need price, gross margin and monthly churn to compute LTV"
            }
        
        # CAC Payback
        if cac > 0 and price > 0 and gm > 0:
            payback = cac / (price * gm)
            metrics["cac_payback_months"] = {
                "value": payback,
                "unit": "months",
                "status": "ok",
                "explainable_inputs": {
                    "cac": cac,
                    "price_month": price,
                    "gross_margin": gm
                }
            }
        else:
            missing = []
            if not cac: missing.append("cac")
            if not price: missing.append("price_month")
            if not gm: missing.append("gross_margin")
            metrics["cac_payback_months"] = {
                "status": "insufficient_data",
                "missing_fields": missing,
                "message": "Need CAC, price and gross margin to compute payback"
            }
        
        return metrics
    
    def _calculate_financials(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate NPV, IRR, Payback using real financial formulas.
        Uses finance_calculator.py functions.
        """
        budget = _safe_float(inputs.get("budget", 0))
        plan_months = _safe_float(inputs.get("plan_months", inputs.get("timeline_months", 12)))

        # Calculate annual benefit - try multiple methods
        subs = _safe_float(inputs.get("subscribers", 0))
        price = _safe_float(inputs.get("price_month", 0))
        gm = _safe_percent(inputs.get("gross_margin", inputs.get("margin_percent", 0)))
        revenue = _safe_float(inputs.get("revenue", 0))
        ebitda_margin = _safe_percent(inputs.get("ebitda_margin", 0))

        # Method 1: From subscribers × price × margin
        if subs > 0 and price > 0 and gm > 0:
            annual_benefit = subs * price * 12 * gm
            print(f"[DEBUG _calculate_financials] annual_benefit from subs*price*margin: {annual_benefit}")
        # Method 2: From revenue × gross margin
        elif revenue > 0 and gm > 0:
            annual_benefit = revenue * gm
            print(f"[DEBUG _calculate_financials] annual_benefit from revenue*gm: {annual_benefit}")
        # Method 3: From revenue × EBITDA margin (use as proxy for benefit)
        elif revenue > 0 and ebitda_margin > 0:
            annual_benefit = revenue * ebitda_margin
            print(f"[DEBUG _calculate_financials] annual_benefit from revenue*ebitda: {annual_benefit}")
        # Method 4: Use raw revenue as benefit (conservative)
        elif revenue > 0:
            annual_benefit = revenue * 0.20  # Assume 20% margin if not specified
            print(f"[DEBUG _calculate_financials] annual_benefit from revenue*0.2 (default): {annual_benefit}")
        else:
            annual_benefit = 0
            print(f"[DEBUG _calculate_financials] annual_benefit=0 (no revenue data)")

        if budget > 0 and annual_benefit > 0:
            # Generate cash flows (simple model: equal annual benefits)
            duration_years = max(1, int(plan_months / 12))
            cash_flows = [annual_benefit] * duration_years
            
            # Calculate using real formulas
            npv = calculate_npv(budget, cash_flows, self.default_discount_rate)
            irr = calculate_irr(budget, cash_flows)
            roi_data = calculate_roi(budget, annual_benefit, duration_years)
            sensitivity = calculate_sensitivity_analysis(budget, cash_flows)
            
            return {
                "npv": npv,
                "irr": irr if irr else 0.0,
                "payback_period": roi_data.get("payback_period", 0),
                "roi_percent": roi_data.get("roi_percent", 0),
                "annual_benefit": annual_benefit,
                "duration_years": duration_years,
                "discount_rate": self.default_discount_rate,
                "sensitivity": sensitivity,
                "projected_ebitda": annual_benefit * duration_years,
                "total_benefit": roi_data.get("total_benefit", 0)
            }
        
        return {
            "npv": 0,
            "irr": 0,
            "payback_period": 0,
            "roi_percent": 0,
            "annual_benefit": 0,
            "duration_years": 0,
            "discount_rate": self.default_discount_rate
        }
    
    def _calculate_scores(
        self,
        inputs: Dict[str, Any],
        metrics: Dict[str, Any]
    ) -> Dict[str, int]:
        """
        Calculate component scores based on actual inputs and metrics.
        Enhanced version of logic from scorecard_calc.py.
        Handles both SaaS-style inputs (subscribers, price) and revenue-based inputs.
        """
        # Get gross margin (try multiple field names)
        gm = _safe_percent(inputs.get("gross_margin", inputs.get("margin_percent", 0)))
        ebitda_margin = _safe_percent(inputs.get("ebitda_margin", 0))

        # Get revenue - either direct or calculated
        revenue = _safe_float(inputs.get("revenue", 0))
        subs = _safe_float(inputs.get("subscribers", 0))
        price = _safe_float(inputs.get("price_month", 0))
        if revenue == 0 and subs > 0 and price > 0:
            revenue = subs * price * 12

        # Get LTV and CAC for ratio calculations
        ltv = _safe_float(inputs.get("ltv", 0))
        cac = _safe_float(inputs.get("cac", 0))
        budget = _safe_float(inputs.get("budget", 0))

        print(f"[DEBUG _calculate_scores] gm={gm}, ebitda={ebitda_margin}, revenue={revenue}, ltv={ltv}, cac={cac}, budget={budget}")

        # =====================================================================
        # FINANCIAL HEALTH (30% weight)
        # Based on: margin quality, LTV/CAC ratio, revenue scale
        # =====================================================================
        financial_health = 50  # Base score

        # Gross margin impact
        if gm >= 0.70:
            financial_health += 20
        elif gm >= 0.50:
            financial_health += 15
        elif gm >= 0.40:
            financial_health += 10
        elif gm >= 0.30:
            financial_health += 5

        # LTV/CAC ratio impact (if both available)
        if ltv > 0 and cac > 0:
            ltv_cac_ratio = ltv / cac
            if ltv_cac_ratio >= 5:
                financial_health += 15
            elif ltv_cac_ratio >= 3:
                financial_health += 10
            elif ltv_cac_ratio >= 2:
                financial_health += 5
            elif ltv_cac_ratio < 1:
                financial_health -= 10

        # Revenue scale impact
        if revenue >= 10_000_000:
            financial_health += 10
        elif revenue >= 1_000_000:
            financial_health += 5

        financial_health = max(0, min(100, financial_health))
        print(f"[DEBUG _calculate_scores] financial_health={financial_health}")

        # =====================================================================
        # OPERATIONAL EFFICIENCY (20% weight)
        # Based on: margin efficiency, revenue per budget dollar, churn
        # =====================================================================
        operational_efficiency = 50  # Base score

        # Margin efficiency
        if gm >= 0.70:
            operational_efficiency += 15
        elif gm >= 0.50:
            operational_efficiency += 10
        elif gm >= 0.30:
            operational_efficiency += 5

        # Revenue efficiency (revenue vs budget spent)
        if budget > 0 and revenue > 0:
            efficiency_ratio = revenue / budget
            if efficiency_ratio >= 5:
                operational_efficiency += 20
            elif efficiency_ratio >= 3:
                operational_efficiency += 15
            elif efficiency_ratio >= 2:
                operational_efficiency += 10
            elif efficiency_ratio >= 1:
                operational_efficiency += 5

        # Churn impact
        churn = _safe_percent(inputs.get("churn_rate_mo", inputs.get("churn_rate", 0)))
        if churn > 0:
            if churn <= 0.02:  # ≤2% monthly
                operational_efficiency += 10
            elif churn <= 0.05:  # ≤5% monthly
                operational_efficiency += 5
            elif churn > 0.10:  # >10% monthly
                operational_efficiency -= 10

        operational_efficiency = max(0, min(100, operational_efficiency))
        print(f"[DEBUG _calculate_scores] operational_efficiency={operational_efficiency}")

        # =====================================================================
        # MARKET POSITION (30% weight)
        # Based on: revenue scale, LTV quality, growth rate
        # =====================================================================
        market_position = 45  # Base score

        # Revenue scale (proxy for market traction)
        if revenue >= 50_000_000:
            market_position += 30
        elif revenue >= 10_000_000:
            market_position += 25
        elif revenue >= 5_000_000:
            market_position += 20
        elif revenue >= 1_000_000:
            market_position += 15
        elif revenue >= 500_000:
            market_position += 10
        elif revenue >= 100_000:
            market_position += 5

        # LTV quality (customer value)
        if ltv >= 100_000:
            market_position += 15
        elif ltv >= 50_000:
            market_position += 12
        elif ltv >= 10_000:
            market_position += 8
        elif ltv >= 5_000:
            market_position += 5

        # Growth rate impact
        growth = _safe_percent(inputs.get("growth_rate", 0))
        if growth > 0:
            if growth >= 0.10:  # 10%+ monthly
                market_position += 10
            elif growth >= 0.05:  # 5%+ monthly
                market_position += 5

        market_position = max(0, min(100, market_position))
        print(f"[DEBUG _calculate_scores] market_position={market_position}")

        # =====================================================================
        # EXECUTION READINESS (20% weight)
        # Based on: data completeness, timeline realism, budget adequacy
        # =====================================================================
        # Count which key inputs are present
        key_fields = [
            ("budget", budget),
            ("plan_months", _safe_float(inputs.get("plan_months", inputs.get("timeline_months", 0)))),
            ("revenue", revenue),
            ("gross_margin", gm),
            ("cac", cac),
            ("ltv", ltv),
        ]
        present_count = sum(1 for _, val in key_fields if val > 0)
        completeness = present_count / len(key_fields)
        execution_readiness = int(40 + (completeness * 40))  # 40-80 based on completeness

        # Timeline realism adjustment
        plan_months = _safe_float(inputs.get("plan_months", inputs.get("timeline_months", 0)))
        if plan_months > 0:
            if 6 <= plan_months <= 24:
                execution_readiness += 10  # Realistic timeline
            elif plan_months < 3:
                execution_readiness -= 10  # Too aggressive
            elif plan_months > 36:
                execution_readiness -= 5   # Very long term

        # Budget adequacy (vs revenue)
        if budget > 0 and revenue > 0:
            budget_ratio = budget / revenue
            if 0.1 <= budget_ratio <= 0.5:
                execution_readiness += 5  # Reasonable investment level

        execution_readiness = max(0, min(100, execution_readiness))
        print(f"[DEBUG _calculate_scores] execution_readiness={execution_readiness}")

        # =====================================================================
        # OVERALL SCORE (weighted average)
        # =====================================================================
        overall = int(
            financial_health * 0.30 +
            operational_efficiency * 0.20 +
            market_position * 0.30 +
            execution_readiness * 0.20
        )
        print(f"[DEBUG _calculate_scores] overall={overall}")
        
        return {
            "financial_health": financial_health,
            "operational_efficiency": operational_efficiency,
            "market_position": market_position,
            "execution_readiness": execution_readiness,
            "overall": overall
        }
    
    def get_lever_schema(self, inputs: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Generate lever schema for scenario modeling.
        Returns list of editable inputs with constraints and display settings.
        """
        lever_definitions = {
            "budget": {
                "label": "Total Budget",
                "type": "currency",
                "min": 10000,
                "max": 10000000,
                "step": 10000,
                "display_multiplier": 1,
                "group": "financial",
                "description": "Total project investment including all costs"
            },
            "plan_months": {
                "label": "Project Timeline",
                "type": "months",
                "min": 1,
                "max": 60,
                "step": 1,
                "display_multiplier": 1,
                "group": "timeline",
                "description": "Project duration in months"
            },
            "subscribers": {
                "label": "Subscribers",
                "type": "number",
                "min": 0,
                "max": 1000000,
                "step": 100,
                "display_multiplier": 1,
                "group": "market",
                "description": "Total subscriber or customer count"
            },
            "price_month": {
                "label": "Monthly Price",
                "type": "currency",
                "min": 1,
                "max": 10000,
                "step": 1,
                "display_multiplier": 1,
                "group": "financial",
                "description": "Monthly subscription price per customer"
            },
            "gross_margin": {
                "label": "Gross Margin",
                "type": "percentage",
                "min": 0.01,
                "max": 0.99,
                "step": 0.01,
                "display_multiplier": 100,  # Display as 20 not 0.20
                "group": "financial",
                "description": "Gross profit margin (revenue - COGS) / revenue"
            },
            "churn_rate_mo": {
                "label": "Monthly Churn Rate",
                "type": "percentage",
                "min": 0.001,
                "max": 0.50,
                "step": 0.001,
                "display_multiplier": 100,  # Display as 5 not 0.05
                "group": "market",
                "description": "Percentage of customers lost per month"
            },
            "cac": {
                "label": "Customer Acquisition Cost",
                "type": "currency",
                "min": 1,
                "max": 10000,
                "step": 10,
                "display_multiplier": 1,
                "group": "financial",
                "description": "Average cost to acquire one new customer"
            }
        }
        
        # Build levers list with current values from inputs
        levers = []
        for key, config in lever_definitions.items():
            value = inputs.get(key)
            if value is not None:
                levers.append({
                    "key": key,
                    "value": _safe_float(value) if config["type"] != "percentage" else _safe_percent(value),
                    **config
                })
        
        return levers
