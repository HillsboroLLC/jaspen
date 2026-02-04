"""
Enhanced Finance Calculator for MarketIQ
Includes: NPV, IRR, ROI, Payback, Sensitivity Analysis, Valuation, Decision Framework
"""
import re
import math
from typing import Dict, Any, List, Optional, Tuple

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _safe_float(value, default=0.0) -> float:
    """Safely convert value to float"""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        # Remove currency symbols, commas
        cleaned = re.sub(r'[$,]', '', value.strip())
        # Handle K, M, B suffixes
        match = re.match(r'^([-+]?\d+(?:\.\d+)?)\s*([KMBkmb])?$', cleaned)
        if match:
            num = float(match.group(1))
            suffix = (match.group(2) or '').upper()
            multipliers = {'K': 1e3, 'M': 1e6, 'B': 1e9}
            return num * multipliers.get(suffix, 1.0)
        try:
            return float(cleaned)
        except:
            return default
    return default

def _safe_percent(value, default=0.0) -> float:
    """Convert percentage string to decimal (e.g., '10%' -> 0.10)"""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        # If already decimal (0.10), return as-is; if percentage (10), convert
        return value / 100.0 if value > 1 else value
    if isinstance(value, str):
        match = re.search(r'([-+]?\d+(?:\.\d+)?)\s*%?', value)
        if match:
            num = float(match.group(1))
            return num / 100.0 if num > 1 or '%' in value else num
    return default

# ============================================================================
# CORE FINANCIAL CALCULATIONS
# ============================================================================

def calculate_roi(initial_investment: float, annual_benefit: float, duration_years: int) -> Dict[str, Any]:
    """
    Calculate ROI and Payback Period
    
    Returns:
        {
            "initial_investment": float,
            "annual_benefit": float,
            "duration_years": int,
            "total_benefit": float,
            "roi_percent": float,
            "payback_period": float (years)
        }
    """
    if not initial_investment or initial_investment <= 0:
        return {}
    
    total_benefit = annual_benefit * duration_years
    roi_percent = ((total_benefit - initial_investment) / initial_investment) * 100
    payback_period = initial_investment / annual_benefit if annual_benefit > 0 else 999
    
    return {
        "initial_investment": initial_investment,
        "annual_benefit": annual_benefit,
        "duration_years": duration_years,
        "total_benefit": total_benefit,
        "roi_percent": roi_percent,
        "payback_period": payback_period
    }

def calculate_npv(initial_investment: float, cash_flows: List[float], discount_rate: float) -> float:
    """
    Calculate Net Present Value
    
    NPV = Σ(CF_t / (1 + r)^t) - Initial Investment
    
    Args:
        initial_investment: Upfront investment (positive number)
        cash_flows: List of annual cash flows
        discount_rate: Discount rate as decimal (e.g., 0.10 for 10%)
    
    Returns:
        NPV as float
    """
    if not cash_flows:
        return 0.0
    
    npv = -initial_investment
    for t, cf in enumerate(cash_flows, start=1):
        npv += cf / ((1 + discount_rate) ** t)
    
    return npv

def calculate_irr(initial_investment: float, cash_flows: List[float], max_iterations: int = 100) -> Optional[float]:
    """
    Calculate Internal Rate of Return using Newton-Raphson method
    
    IRR is the rate where NPV = 0
    
    Args:
        initial_investment: Upfront investment (positive number)
        cash_flows: List of annual cash flows
        max_iterations: Maximum iterations for convergence
    
    Returns:
        IRR as decimal (e.g., 0.15 for 15%) or None if not found
    """
    if not cash_flows or initial_investment <= 0:
        return None
    
    # Start with initial guess
    rate = 0.10  # 10%
    
    for _ in range(max_iterations):
        # Calculate NPV at current rate
        npv = -initial_investment
        npv_derivative = 0.0
        
        for t, cf in enumerate(cash_flows, start=1):
            discount_factor = (1 + rate) ** t
            npv += cf / discount_factor
            npv_derivative -= t * cf / ((1 + rate) ** (t + 1))
        
        # Check convergence
        if abs(npv) < 0.01:  # Close enough to zero
            return rate
        
        # Newton-Raphson update
        if npv_derivative != 0:
            rate = rate - npv / npv_derivative
        else:
            return None
        
        # Bounds check
        if rate < -0.99 or rate > 10.0:  # IRR between -99% and 1000%
            return None
    
    return None

def calculate_sensitivity_analysis(initial_investment: float, cash_flows: List[float]) -> Dict[str, float]:
    """
    Calculate NPV at different discount rates for sensitivity analysis
    
    Returns:
        {
            "npv_at_6": float,
            "npv_at_8": float,
            "npv_at_10": float,
            "npv_at_12": float,
            "npv_at_14": float
        }
    """
    rates = [0.06, 0.08, 0.10, 0.12, 0.14]
    result = {}
    
    for rate in rates:
        npv = calculate_npv(initial_investment, cash_flows, rate)
        key = f"npv_at_{int(rate * 100)}"
        result[key] = npv
    
    return result

def calculate_valuation(ebitda: float, multiple: float) -> Dict[str, Any]:
    """
    Calculate Enterprise Value using EBITDA multiple
    
    Returns:
        {
            "ebitda": float,
            "multiple": float,
            "enterprise_value": float
        }
    """
    enterprise_value = ebitda * multiple if ebitda and multiple else 0.0
    
    return {
        "ebitda": ebitda,
        "multiple": multiple,
        "enterprise_value": enterprise_value
    }

def evaluate_decision_framework(
    strategic_alignment: bool,
    npv: float,
    irr: float,
    discount_rate: float,
    payback_period: float,
    sensitivity: Dict[str, float]
) -> Dict[str, Any]:
    """
    Evaluate 5-question decision framework
    
    Returns:
        {
            "strategic_alignment": bool,
            "npv_positive": bool,
            "irr_above_hurdle": bool,
            "acceptable_payback": bool,
            "robust_sensitivity": bool,
            "overall_recommendation": str
        }
    """
    npv_positive = npv > 0
    irr_above_hurdle = irr > discount_rate if irr is not None else False
    acceptable_payback = payback_period <= 4.0
    
    # Robust sensitivity: NPV positive in at least 3 out of 5 scenarios
    positive_scenarios = sum(1 for v in sensitivity.values() if v > 0)
    robust_sensitivity = positive_scenarios >= 3
    
    # Count passing criteria
    criteria = [
        strategic_alignment,
        npv_positive,
        irr_above_hurdle,
        acceptable_payback,
        robust_sensitivity
    ]
    passing_count = sum(criteria)
    
    # Overall recommendation
    if passing_count == 5:
        recommendation = "Strong Investment"
    elif passing_count == 4:
        recommendation = "Moderate"
    elif passing_count == 3:
        recommendation = "High Risk"
    else:
        recommendation = "Do Not Proceed"
    
    return {
        "strategic_alignment": strategic_alignment,
        "npv_positive": npv_positive,
        "irr_above_hurdle": irr_above_hurdle,
        "acceptable_payback": acceptable_payback,
        "robust_sensitivity": robust_sensitivity,
        "overall_recommendation": recommendation
    }

# ============================================================================
# COMPREHENSIVE ANALYSIS
# ============================================================================

def run_comprehensive_analysis(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run comprehensive financial analysis
    
    Expected data keys:
        - initial_investment: float
        - annual_benefit: float
        - duration_years: int
        - discount_rate: float (decimal, e.g., 0.10)
        - ebitda_after: float
        - ebitda_multiple: float
        - strategic_alignment: bool
        - cash_flows: List[float] (optional, will generate if not provided)
    
    Returns:
        {
            "investment_analysis": {...},
            "npv_irr_analysis": {...},
            "valuation": {...},
            "decision_framework": {...}
        }
    """
    result = {}
    
    # Extract and clean inputs
    initial_investment = _safe_float(data.get('initial_investment'))
    annual_benefit = _safe_float(data.get('annual_benefit'))
    duration_years = int(_safe_float(data.get('duration_years', 5)))
    discount_rate = _safe_percent(data.get('discount_rate', 0.10))
    ebitda_after = _safe_float(data.get('ebitda_after'))
    ebitda_multiple = _safe_float(data.get('ebitda_multiple', 8.0))
    strategic_alignment = data.get('strategic_alignment', True)
    
    # Generate cash flows if not provided
    cash_flows = data.get('cash_flows')
    if not cash_flows and annual_benefit > 0:
        cash_flows = [annual_benefit] * duration_years
    
    # 1. Investment Analysis (ROI & Payback)
    if initial_investment > 0 and annual_benefit > 0:
        result['investment_analysis'] = calculate_roi(
            initial_investment, annual_benefit, duration_years
        )
    
    # 2. NPV & IRR Analysis
    if initial_investment > 0 and cash_flows:
        npv = calculate_npv(initial_investment, cash_flows, discount_rate)
        irr = calculate_irr(initial_investment, cash_flows)
        sensitivity = calculate_sensitivity_analysis(initial_investment, cash_flows)
        
        result['npv_irr_analysis'] = {
            "initial_investment": initial_investment,
            "discount_rate": discount_rate,
            "cash_flows": cash_flows,
            "npv": npv,
            "irr": irr if irr is not None else 0.0,
            "sensitivity": sensitivity
        }
    
    # 3. Valuation
    if ebitda_after > 0:
        result['valuation'] = calculate_valuation(ebitda_after, ebitda_multiple)
    
    # 4. Decision Framework
    if 'npv_irr_analysis' in result and 'investment_analysis' in result:
        npv = result['npv_irr_analysis']['npv']
        irr = result['npv_irr_analysis']['irr']
        payback = result['investment_analysis']['payback_period']
        sensitivity = result['npv_irr_analysis']['sensitivity']
        
        result['decision_framework'] = evaluate_decision_framework(
            strategic_alignment, npv, irr, discount_rate, payback, sensitivity
        )
    
    return result

# ============================================================================
# DYNAMIC SCORING BASED ON FINANCIAL METRICS
# ============================================================================

def calculate_dynamic_scores(
    npv: Optional[float],
    irr: Optional[float],
    discount_rate: float,
    payback_period: Optional[float],
    ebitda_margin: Optional[float],
    roi_percent: Optional[float],
    market_position_qualitative: int = 70,
    execution_readiness_qualitative: int = 65
) -> Dict[str, int]:
    """
    Calculate component scores dynamically based on financial metrics
    
    Returns:
        {
            "financial_health": int (0-100),
            "operational_efficiency": int (0-100),
            "market_position": int (0-100),
            "execution_readiness": int (0-100),
            "overall": int (0-100)
        }
    """
    
    # Financial Health (30% weight) - Based on NPV, IRR, ROI
    financial_health = 50  # Default
    if npv is not None:
        if npv > 1_000_000:
            financial_health = 85
        elif npv > 500_000:
            financial_health = 75
        elif npv > 0:
            financial_health = 65
        elif npv > -500_000:
            financial_health = 45
        else:
            financial_health = 25
        
        # Adjust based on IRR
        if irr is not None and irr > discount_rate:
            if irr > discount_rate * 2:
                financial_health = min(100, financial_health + 15)
            else:
                financial_health = min(100, financial_health + 5)
        elif irr is not None and irr < discount_rate:
            financial_health = max(0, financial_health - 10)
        
        # Adjust based on ROI
        if roi_percent is not None:
            if roi_percent > 100:
                financial_health = min(100, financial_health + 10)
            elif roi_percent < 20:
                financial_health = max(0, financial_health - 10)
    
    # Operational Efficiency (20% weight) - Based on EBITDA margin
    operational_efficiency = 60  # Default
    if ebitda_margin is not None:
        if ebitda_margin > 0.25:
            operational_efficiency = 90
        elif ebitda_margin > 0.15:
            operational_efficiency = 75
        elif ebitda_margin > 0.10:
            operational_efficiency = 60
        elif ebitda_margin > 0.05:
            operational_efficiency = 45
        else:
            operational_efficiency = 30
        
        # Adjust based on payback period
        if payback_period is not None:
            if payback_period < 2:
                operational_efficiency = min(100, operational_efficiency + 10)
            elif payback_period > 4:
                operational_efficiency = max(0, operational_efficiency - 10)
    
    # Market Position (30% weight) - Keep qualitative assessment from Claude
    market_position = market_position_qualitative
    
    # Execution Readiness (20% weight) - Keep qualitative assessment from Claude
    execution_readiness = execution_readiness_qualitative
    
    # Overall Score (weighted average)
    overall = int(
        financial_health * 0.30 +
        operational_efficiency * 0.20 +
        market_position * 0.30 +
        execution_readiness * 0.20
    )
    
    return {
        "financial_health": int(financial_health),
        "operational_efficiency": int(operational_efficiency),
        "market_position": int(market_position),
        "execution_readiness": int(execution_readiness),
        "overall": overall
    }

# ============================================================================
# LEGACY COMPATIBILITY
# ============================================================================

def enrich_financials(transcript: str, analysis_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enhanced version that adds comprehensive financial analysis
    Maintains backward compatibility with existing code
    """
    result = dict(analysis_result or {})
    
    # Extract financial data from transcript or analysis_result
    data = {}
    
    # Try to extract from analysis_result first
    if 'investment_analysis' in result:
        inv = result['investment_analysis']
        data['initial_investment'] = inv.get('initial_investment')
        data['annual_benefit'] = inv.get('annual_benefit')
        data['duration_years'] = inv.get('duration_years', 5)
    
    if 'npv_irr_analysis' in result:
        npv_data = result['npv_irr_analysis']
        data['discount_rate'] = npv_data.get('discount_rate', 0.10)
        data['cash_flows'] = npv_data.get('cash_flows')
    
    # Extract EBITDA from before_after_financials
    if 'before_after_financials' in result:
        after = result['before_after_financials'].get('after', {})
        data['ebitda_after'] = after.get('ebitda')
    
    # Run comprehensive analysis if we have enough data
    if data.get('initial_investment') and data.get('annual_benefit'):
        comprehensive = run_comprehensive_analysis(data)
        result.update(comprehensive)
    
    # Ensure project name
    if not result.get('project_name'):
        sent = (transcript or "").strip().split('\n')[0]
        result['project_name'] = (sent[:60] or "Market IQ Project").strip()
    
    return result
