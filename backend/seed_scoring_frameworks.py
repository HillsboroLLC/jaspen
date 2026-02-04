#!/usr/bin/env python3
"""
Seed script for system scoring frameworks.
Creates default evaluation frameworks for AI Agent system.
Includes Market IQ Assessment framework matching existing scoring system.
"""

import sys
import os
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.models import ScoringFramework

def seed_frameworks():
    app = create_app()
    
    with app.app_context():
        print("🌱 Seeding scoring frameworks...")
        
        # Check if frameworks already exist
        existing = ScoringFramework.query.filter_by(is_system=True).count()
        if existing > 0:
            print(f"⚠️  {existing} system frameworks already exist. Skipping.")
            return
        
        frameworks = [
            # Framework 1: Market IQ Assessment (matches existing system)
            {
                "name": "Market IQ Assessment",
                "description": "Comprehensive business evaluation matching the Market IQ scoring system with four key dimensions",
                "criteria": [
                    {
                        "id": "execution_readiness",
                        "name": "Execution Readiness",
                        "description": "Ability to execute on the business plan with available resources and capabilities",
                        "weight": 0.25,
                        "factors": [
                            {"id": "team_capability", "name": "Team Capability", "description": "Skills and experience of the team"},
                            {"id": "resource_availability", "name": "Resource Availability", "description": "Access to required resources"},
                            {"id": "execution_plan", "name": "Execution Plan", "description": "Clarity and feasibility of execution plan"}
                        ]
                    },
                    {
                        "id": "financial_health",
                        "name": "Financial Health",
                        "description": "Financial viability and sustainability of the business model",
                        "weight": 0.25,
                        "factors": [
                            {"id": "revenue_model", "name": "Revenue Model", "description": "Strength and clarity of revenue generation"},
                            {"id": "profitability", "name": "Profitability", "description": "Path to profitability and margins"},
                            {"id": "cash_flow", "name": "Cash Flow", "description": "Cash flow management and runway"}
                        ]
                    },
                    {
                        "id": "market_position",
                        "name": "Market Position",
                        "description": "Competitive positioning and market opportunity",
                        "weight": 0.25,
                        "factors": [
                            {"id": "market_size", "name": "Market Size", "description": "Total addressable market"},
                            {"id": "competitive_advantage", "name": "Competitive Advantage", "description": "Unique value proposition"},
                            {"id": "market_timing", "name": "Market Timing", "description": "Market readiness and timing"}
                        ]
                    },
                    {
                        "id": "operational_efficiency",
                        "name": "Operational Efficiency",
                        "description": "Efficiency of operations and scalability potential",
                        "weight": 0.25,
                        "factors": [
                            {"id": "process_maturity", "name": "Process Maturity", "description": "Quality of operational processes"},
                            {"id": "scalability", "name": "Scalability", "description": "Ability to scale operations"},
                            {"id": "cost_structure", "name": "Cost Structure", "description": "Efficiency of cost management"}
                        ]
                    }
                ],
                "scoring_range": {"min": 0, "max": 100},
                "scale_labels": {
                    "0-25": "Poor",
                    "26-54": "Fair",
                    "55-69": "Good",
                    "70-84": "Excellent",
                    "85-100": "Outstanding"
                }
            },
            
            # Framework 2: Market Viability Assessment
            {
                "name": "Market Viability Assessment",
                "description": "Comprehensive evaluation of market opportunity, demand, and competitive positioning",
                "criteria": [
                    {
                        "id": "market_demand",
                        "name": "Market Demand",
                        "description": "Size and urgency of target market need",
                        "weight": 0.30,
                        "factors": [
                            {"id": "market_size", "name": "Total Addressable Market", "description": "Size of potential customer base"},
                            {"id": "growth_rate", "name": "Market Growth Rate", "description": "Speed of market expansion"},
                            {"id": "urgency", "name": "Customer Urgency", "description": "How pressing is the need"}
                        ]
                    },
                    {
                        "id": "competitive_advantage",
                        "name": "Competitive Advantage",
                        "description": "Uniqueness and defensibility of solution",
                        "weight": 0.25,
                        "factors": [
                            {"id": "differentiation", "name": "Differentiation", "description": "How unique is the solution"},
                            {"id": "barriers", "name": "Entry Barriers", "description": "Difficulty for competitors to copy"}
                        ]
                    },
                    {
                        "id": "revenue_potential",
                        "name": "Revenue Potential",
                        "description": "Ability to generate sustainable revenue",
                        "weight": 0.25,
                        "factors": [
                            {"id": "pricing_power", "name": "Pricing Power", "description": "Ability to command premium prices"},
                            {"id": "scalability", "name": "Scalability", "description": "Ease of scaling revenue"}
                        ]
                    },
                    {
                        "id": "customer_access",
                        "name": "Customer Access",
                        "description": "Ability to reach and acquire customers",
                        "weight": 0.20,
                        "factors": [
                            {"id": "channels", "name": "Distribution Channels", "description": "Available paths to customers"},
                            {"id": "acquisition_cost", "name": "Acquisition Cost", "description": "Cost to acquire each customer"}
                        ]
                    }
                ],
                "scoring_range": {"min": 0, "max": 100},
                "scale_labels": {
                    "0-25": "Weak Opportunity",
                    "26-50": "Moderate Potential",
                    "51-75": "Strong Opportunity",
                    "76-100": "Exceptional Opportunity"
                }
            },
            
            # Framework 3: Technical Feasibility
            {
                "name": "Technical Feasibility",
                "description": "Evaluation of technical complexity, resource requirements, and implementation risk",
                "criteria": [
                    {
                        "id": "technical_complexity",
                        "name": "Technical Complexity",
                        "description": "Difficulty of technical implementation",
                        "weight": 0.30,
                        "factors": [
                            {"id": "architecture", "name": "Architecture Complexity", "description": "System design difficulty"},
                            {"id": "integration", "name": "Integration Requirements", "description": "Complexity of system integration"}
                        ]
                    },
                    {
                        "id": "resource_availability",
                        "name": "Resource Availability",
                        "description": "Access to required skills and tools",
                        "weight": 0.25,
                        "factors": [
                            {"id": "talent", "name": "Talent Availability", "description": "Access to skilled personnel"},
                            {"id": "tools", "name": "Tools & Infrastructure", "description": "Availability of required tools"}
                        ]
                    },
                    {
                        "id": "time_to_market",
                        "name": "Time to Market",
                        "description": "Speed of development and deployment",
                        "weight": 0.25,
                        "factors": [
                            {"id": "development_time", "name": "Development Duration", "description": "Time to build"},
                            {"id": "deployment_ease", "name": "Deployment Ease", "description": "Difficulty of going live"}
                        ]
                    },
                    {
                        "id": "risk_factors",
                        "name": "Technical Risk",
                        "description": "Likelihood of technical challenges",
                        "weight": 0.20,
                        "factors": [
                            {"id": "unknowns", "name": "Unknown Factors", "description": "Level of technical uncertainty"},
                            {"id": "dependencies", "name": "External Dependencies", "description": "Reliance on third parties"}
                        ]
                    }
                ],
                "scoring_range": {"min": 0, "max": 100},
                "scale_labels": {
                    "0-25": "High Risk",
                    "26-50": "Moderate Risk",
                    "51-75": "Low Risk",
                    "76-100": "Very Feasible"
                }
            },
            
            # Framework 4: ROI Analysis
            {
                "name": "ROI Analysis",
                "description": "Financial return potential and cost-benefit evaluation",
                "criteria": [
                    {
                        "id": "revenue_impact",
                        "name": "Revenue Impact",
                        "description": "Expected revenue generation or increase",
                        "weight": 0.35,
                        "factors": [
                            {"id": "direct_revenue", "name": "Direct Revenue", "description": "New revenue streams"},
                            {"id": "revenue_growth", "name": "Revenue Growth", "description": "Impact on existing revenue"}
                        ]
                    },
                    {
                        "id": "cost_savings",
                        "name": "Cost Savings",
                        "description": "Reduction in operational costs",
                        "weight": 0.25,
                        "factors": [
                            {"id": "efficiency", "name": "Efficiency Gains", "description": "Process improvements"},
                            {"id": "automation", "name": "Automation Benefits", "description": "Labor cost reduction"}
                        ]
                    },
                    {
                        "id": "investment_required",
                        "name": "Investment Required",
                        "description": "Total capital and resource investment",
                        "weight": 0.20,
                        "factors": [
                            {"id": "upfront_cost", "name": "Initial Investment", "description": "Upfront capital required"},
                            {"id": "ongoing_cost", "name": "Ongoing Costs", "description": "Maintenance and operation"}
                        ]
                    },
                    {
                        "id": "payback_period",
                        "name": "Payback Period",
                        "description": "Time to recover investment",
                        "weight": 0.20,
                        "factors": [
                            {"id": "breakeven", "name": "Breakeven Timeline", "description": "When does it pay for itself"},
                            {"id": "cash_flow", "name": "Cash Flow Profile", "description": "Timing of costs vs returns"}
                        ]
                    }
                ],
                "scoring_range": {"min": 0, "max": 100},
                "scale_labels": {
                    "0-25": "Poor ROI",
                    "26-50": "Moderate ROI",
                    "51-75": "Strong ROI",
                    "76-100": "Exceptional ROI"
                }
            }
        ]
        
        created_count = 0
        for fw_data in frameworks:
            fw = ScoringFramework(
                user_id=None,  # System framework
                name=fw_data["name"],
                description=fw_data["description"],
                criteria=fw_data["criteria"],
                scoring_range=fw_data["scoring_range"],
                scale_labels=fw_data["scale_labels"],
                is_public=True,
                is_system=True,
                usage_count=0,
                version=1
            )
            db.session.add(fw)
            created_count += 1
            print(f"  ✓ Created: {fw.name}")
        
        db.session.commit()
        print(f"\n✅ Successfully created {created_count} system scoring frameworks!")
        print("\nFrameworks created:")
        print("  1. Market IQ Assessment (matches existing system)")
        print("  2. Market Viability Assessment")
        print("  3. Technical Feasibility")
        print("  4. ROI Analysis")

if __name__ == "__main__":
    seed_frameworks()