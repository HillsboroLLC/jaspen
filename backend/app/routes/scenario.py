# app/routes/scenario.py

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scenario_bp = Blueprint('scenario', __name__)

def calculate_scenario(base_analysis, changes):
    """
    Calculate adjusted scenario based on parameter changes
    
    Args:
        base_analysis: Original analysis result dict
        changes: Dict with budgetPct, monthShift, pricePct, cacPct
    
    Returns:
        Updated analysis dict with adjusted values
    """
    import copy
    
    # Deep copy to avoid mutating original
    scenario = copy.deepcopy(base_analysis)
    
    # Extract base financial values
    financial_impact = scenario.get('financial_impact', {})
    component_scores = scenario.get('component_scores', {})
    
    # Parse financial values (remove $ and convert to float)
    def parse_currency(value):
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            # Remove $, K, M, B and convert
            clean = value.replace('$', '').replace(',', '').strip()
            if 'M' in clean:
                return float(clean.replace('M', '')) * 1_000_000
            elif 'K' in clean:
                return float(clean.replace('K', '')) * 1_000
            elif 'B' in clean:
                return float(clean.replace('B', '')) * 1_000_000_000
            else:
                try:
                    return float(clean)
                except:
                    return 0
        return 0
    
    def format_currency(value):
        """Format number as currency string"""
        if value >= 1_000_000_000:
            return f"${value/1_000_000_000:.1f}B"
        elif value >= 1_000_000:
            return f"${value/1_000_000:.1f}M"
        elif value >= 1_000:
            return f"${value/1_000:.1f}K"
        else:
            return f"${value:.0f}"
    
    # Get base values
    base_ebitda = parse_currency(financial_impact.get('projected_ebitda', 0))
    base_roi = parse_currency(financial_impact.get('roi_opportunity', 0))
    base_risk = parse_currency(financial_impact.get('ebitda_at_risk', 0))
    base_loss = parse_currency(financial_impact.get('potential_loss', 0))
    
    # Extract change percentages
    budget_pct = changes.get('budgetPct', 0) / 100.0
    month_shift = changes.get('monthShift', 0)
    price_pct = changes.get('pricePct', 0) / 100.0
    cac_pct = changes.get('cacPct', 0) / 100.0
    
    # Calculate adjustments
    # Budget increase = higher EBITDA, higher ROI
    budget_multiplier = 1 + budget_pct
    
    # Timeline shift: negative = faster (better), positive = slower (worse)
    # Each month shift affects efficiency by ~3%
    timeline_multiplier = 1 - (month_shift * 0.03)
    
    # Price increase = higher revenue = higher EBITDA
    price_multiplier = 1 + price_pct
    
    # CAC increase = higher costs = lower EBITDA
    cac_multiplier = 1 - (cac_pct * 0.5)  # CAC has 50% impact on EBITDA
    
    # Apply multipliers
    new_ebitda = base_ebitda * budget_multiplier * timeline_multiplier * price_multiplier * cac_multiplier
    new_roi = base_roi * budget_multiplier * timeline_multiplier * price_multiplier
    new_risk = base_risk * (1 - budget_pct * 0.5) * timeline_multiplier  # More budget = less risk
    new_loss = base_loss * (1 - budget_pct * 0.3) * (1 + month_shift * 0.05)  # Delays increase loss
    
    # Update financial impact
    scenario['financial_impact'] = {
        'projected_ebitda': format_currency(new_ebitda),
        'roi_opportunity': format_currency(new_roi),
        'ebitda_at_risk': format_currency(new_risk),
        'potential_loss': format_currency(new_loss),
        'risk_level': 'Low' if new_risk < base_risk * 0.7 else 'Moderate' if new_risk < base_risk else 'High'
    }
    
    # Adjust component scores based on changes
    # Financial Health: affected by budget and price
    financial_health = component_scores.get('financial_health', 50)
    financial_health_adj = financial_health + (budget_pct * 20) + (price_pct * 15) - (cac_pct * 10)
    financial_health_adj = max(0, min(100, financial_health_adj))
    
    # Operational Efficiency: affected by timeline and CAC
    operational_efficiency = component_scores.get('operational_efficiency', 50)
    operational_efficiency_adj = operational_efficiency - (month_shift * 3) - (cac_pct * 8)
    operational_efficiency_adj = max(0, min(100, operational_efficiency_adj))
    
    # Market Position: affected by price and budget
    market_position = component_scores.get('market_position', 50)
    market_position_adj = market_position + (budget_pct * 15) - (price_pct * 5)  # Higher price can hurt position
    market_position_adj = max(0, min(100, market_position_adj))
    
    # Execution Readiness: affected by timeline
    execution_readiness = component_scores.get('execution_readiness', 50)
    execution_readiness_adj = execution_readiness - (month_shift * 5)  # Delays hurt readiness
    execution_readiness_adj = max(0, min(100, execution_readiness_adj))
    
    # Update component scores
    scenario['component_scores'] = {
        'financial_health': round(financial_health_adj),
        'operational_efficiency': round(operational_efficiency_adj),
        'market_position': round(market_position_adj),
        'execution_readiness': round(execution_readiness_adj)
    }
    
    # Recalculate Market IQ Score (weighted average)
    new_score = (
        financial_health_adj * 0.30 +
        operational_efficiency_adj * 0.20 +
        market_position_adj * 0.30 +
        execution_readiness_adj * 0.20
    )
    scenario['market_iq_score'] = round(new_score)
    
    # Add scenario metadata
    scenario['scenario_changes'] = changes
    scenario['scenario_description'] = f"Budget {changes.get('budgetPct', 0):+d}%, Timeline {changes.get('monthShift', 0):+d}mo, Price {changes.get('pricePct', 0):+d}%, CAC {changes.get('cacPct', 0):+d}%"
    
    return scenario


@scenario_bp.route('/calculate', methods=['POST'])
@jwt_required()
def calculate_scenario_endpoint():
    """
    Calculate a scenario based on parameter adjustments
    
    Request body:
    {
        "base_analysis": {...},  # Original analysis result
        "changes": {
            "budgetPct": -20,
            "monthShift": 2,
            "pricePct": 0,
            "cacPct": 10
        }
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        base_analysis = data.get('base_analysis')
        changes = data.get('changes')
        
        if not base_analysis:
            return jsonify({'error': 'base_analysis is required'}), 400
        
        if not changes:
            return jsonify({'error': 'changes is required'}), 400
        
        # Calculate the scenario
        result = calculate_scenario(base_analysis, changes)
        
        return jsonify({
            'success': True,
            'scenario_result': result
        })
        
    except Exception as e:
        logger.error(f"Error calculating scenario: {e}")
        return jsonify({'error': str(e)}), 500
