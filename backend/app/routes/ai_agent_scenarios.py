"""
Purpose: AI Agent scenario modeling endpoints with real financial calculations.

This module handles all scenario-related operations:
- Create scenarios (what-if variations)
- Calculate scenario results using real NPV/IRR/Payback formulas
- Provide lever schema for dynamic UI rendering
- Apply scenarios to create new analyses
- Adopt scenarios as current thread analysis

Endpoints:
  POST   /api/ai-agent/threads/<id>/scenarios        - Create scenario
  GET    /api/ai-agent/threads/<id>/scenarios        - List scenarios for thread
  GET    /api/ai-agent/threads/<id>/levers           - Get lever schema
  PUT    /api/ai-agent/scenarios/<id>                - Update scenario
  POST   /api/ai-agent/scenarios/<id>/apply          - Apply scenario → new analysis
  POST   /api/ai-agent/scenarios/<id>/adopt          - Adopt scenario as current
  DELETE /api/ai-agent/scenarios/<id>                - Delete scenario (soft)
"""

from datetime import datetime
import uuid
from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import desc
from sqlalchemy.orm.attributes import flag_modified

from app import db
from app.models import Analysis, AgentThread, MiqScenario
from app.services.scenario_calculator import ScenarioCalculator

ai_agent_scenarios_bp = Blueprint("ai_agent_scenarios", __name__)

# Initialize calculator
calculator = ScenarioCalculator()


# ============================================================================
# LEVER SCHEMA
# ============================================================================

@ai_agent_scenarios_bp.route("/threads/<thread_id>/levers", methods=["GET"])
@jwt_required()
def get_lever_schema(thread_id):
    """
    Get lever schema for scenario modeling.
    Returns editable inputs with constraints, types, and display settings.
    """
    try:
        thread = AgentThread.query.filter_by(id=thread_id, deleted_at=None).first()
        if not thread:
            return jsonify({"error": "thread_not_found"}), 404

        # Get baseline analysis
        baseline = Analysis.query.filter_by(
            thread_id=thread_id,
            deleted_at=None
        ).order_by(Analysis.analyzed_at.desc()).first()

        if not baseline:
            return jsonify({"error": "no_analysis_found", "message": "Run analysis first"}), 404

        # Get baseline inputs from analysis meta
        print(f"[DEBUG get_lever_schema] baseline.id={baseline.id}, baseline.meta={baseline.meta}")
        baseline_inputs = (baseline.meta or {}).get("extracted_levers", {})
        print(f"[DEBUG get_lever_schema] extracted_levers from meta={baseline_inputs}")

        if not baseline_inputs:
            # Fallback: re-extract from the thread's conversation history
            print("[DEBUG get_lever_schema] meta empty — falling back to conversation extraction")
            from app.routes.ai_agent import _extract_levers
            baseline_inputs = _extract_levers(thread.conversation_history or [])
            print(f"[DEBUG get_lever_schema] fallback extraction result={baseline_inputs}")

        if not baseline_inputs:
            return jsonify({"error": "no_inputs_found", "message": "Analysis missing input data"}), 404

        # Generate lever schema
        levers = calculator.get_lever_schema(baseline_inputs)

        return jsonify({
            "thread_id": thread_id,
            "baseline_analysis_id": baseline.id,
            "levers": levers,
            "baseline_inputs": baseline_inputs
        }), 200

    except Exception as e:
        current_app.logger.exception("get_lever_schema failed")
        return jsonify({"error": "server_error", "detail": str(e)}), 500


# ============================================================================
# SCENARIO CRUD
# ============================================================================

@ai_agent_scenarios_bp.route("/threads/<thread_id>/scenarios", methods=["POST"])
@jwt_required()
def create_scenario(thread_id):
    print(f"[DEBUG] create_scenario called with thread_id: {thread_id}")
    """
    Create a new scenario with what-if adjustments.
    Calculates results using real financial formulas.
    """
    try:
        user_id = get_jwt_identity()
        data = request.get_json() or {}
        print(f"[DEBUG] Request data: {data}")

        thread = AgentThread.query.filter_by(id=thread_id, deleted_at=None).first()
        if not thread:
            return jsonify({"error": "thread_not_found"}), 404

        # Get baseline analysis
        baseline = Analysis.query.filter_by(
            thread_id=thread_id,
            deleted_at=None
        ).order_by(Analysis.analyzed_at.desc()).first()

        if not baseline:
            return jsonify({"error": "no_baseline"}), 404

        # Get deltas (changes from baseline)
        deltas = data.get("deltas", {})
        if not deltas:
            return jsonify({"error": "deltas_required"}), 400

        # Get baseline inputs
        baseline_inputs = (baseline.meta or {}).get("extracted_levers", {})
        print(f"[DEBUG] baseline_inputs: {baseline_inputs}")

        # Calculate scenario results using real formulas
        scenario_result = calculator.calculate_scenario(baseline_inputs, deltas)
        print(f"[DEBUG] scenario_result: {scenario_result}")

        # Create scenario record
        scenario = MiqScenario(
            scenario_id=str(uuid.uuid4()),
            thread_id=thread_id,
            based_on=baseline.id,                          # was baseline_analysis_id (no such column)
            label=data.get("name", "Scenario"),            # was name (column is label)
            deltas=deltas,
            result={                                       # was results (column is result, singular)
                "scores": scenario_result["scores"],
                "overall_score": scenario_result["overall_score"],
                "financial_analysis": scenario_result["financial_analysis"],
                "metrics": scenario_result["metrics"],
            },
            meta={
                "inputs": scenario_result["inputs"],
                "calculation_method": scenario_result["calculation_method"],
            },
        )

        db.session.add(scenario)
        db.session.commit()

        # Return result with overall_score surfaced for easy frontend access
        _result = scenario.result or {}
        return jsonify({
            "scenario": {
                "id": scenario.scenario_id,
                "thread_id": scenario.thread_id,
                "label": scenario.label,
                "result": _result,                          # singular – matches bundle format
                "overall_score": _result.get("overall_score", 0),
                "scores": _result.get("scores", {}),
                "deltas": scenario.deltas,
            }
        }), 201

    except Exception as e:
        print(f"[ERROR] create_scenario failed: {e}")
        import traceback
        traceback.print_exc()
        db.session.rollback()
        current_app.logger.exception("create_scenario failed")
        return jsonify({"error": "server_error", "detail": str(e)}), 500


@ai_agent_scenarios_bp.route("/threads/<thread_id>/scenarios", methods=["GET"])
@jwt_required()
def list_scenarios(thread_id):
    """List all scenarios for a thread."""
    try:
        thread = AgentThread.query.filter_by(id=thread_id, deleted_at=None).first()
        if not thread:
            return jsonify({"error": "thread_not_found"}), 404

        scenarios = MiqScenario.query.filter_by(
            thread_id=thread_id,
        ).order_by(MiqScenario.created_at.desc()).all()

        def _scenario_row(s):
            _result = s.result or {}
            return {
                "id": s.scenario_id,
                "thread_id": s.thread_id,
                "label": s.label,
                "result": _result,                          # singular – matches bundle format
                "overall_score": _result.get("overall_score", 0),
                "scores": _result.get("scores", {}),
                "deltas": s.deltas,
            }

        return jsonify({
            "thread_id": thread_id,
            "scenarios": [_scenario_row(s) for s in scenarios]
        }), 200

    except Exception as e:
        current_app.logger.exception("list_scenarios failed")
        return jsonify({"error": "server_error", "detail": str(e)}), 500


@ai_agent_scenarios_bp.route("/scenarios/<scenario_id>", methods=["PUT"])
@jwt_required()
def update_scenario(scenario_id):
    """Update scenario metadata (label)."""
    try:
        user_id = get_jwt_identity()
        data = request.get_json() or {}

        scenario = MiqScenario.query.filter_by(scenario_id=scenario_id).first()
        if not scenario:
            return jsonify({"error": "scenario_not_found"}), 404

        # Update fields
        if "name" in data:
            scenario.label = data["name"]
        db.session.commit()

        return jsonify({
            "scenario": {
                "scenario_id": scenario.scenario_id,
                "thread_id": scenario.thread_id,
                "label": scenario.label,
                "deltas": scenario.deltas,
                "result": scenario.result,
                "based_on": scenario.based_on,
                "created_at": scenario.created_at.isoformat() if scenario.created_at else None,
                "meta": scenario.meta,
            }
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("update_scenario failed")
        return jsonify({"error": "server_error", "detail": str(e)}), 500


@ai_agent_scenarios_bp.route("/scenarios/<scenario_id>", methods=["DELETE"])
@jwt_required()
def delete_scenario(scenario_id):
    """Soft delete a scenario."""
    try:
        scenario = MiqScenario.query.filter_by(scenario_id=scenario_id).first()
        if not scenario:
            return jsonify({"error": "scenario_not_found"}), 404

        db.session.delete(scenario)
        db.session.commit()

        return jsonify({"message": "scenario_deleted"}), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("delete_scenario failed")
        return jsonify({"error": "server_error", "detail": str(e)}), 500


# ============================================================================
# SCENARIO ACTIONS
# ============================================================================

@ai_agent_scenarios_bp.route("/scenarios/<scenario_id>/apply", methods=["POST"])
@jwt_required()
def apply_scenario(scenario_id):
    """
    Apply scenario to create a new analysis.
    This creates a new Analysis record with the scenario's results.
    """
    try:
        user_id = get_jwt_identity()
        data = request.get_json() or {}

        scenario = MiqScenario.query.filter_by(scenario_id=scenario_id).first()
        if not scenario:
            return jsonify({"error": "scenario_not_found"}), 404

        # Get baseline analysis for framework reference
        baseline = Analysis.query.filter_by(
            id=scenario.based_on,
            deleted_at=None
        ).first()

        if not baseline:
            return jsonify({"error": "baseline_not_found"}), 404

        # Create new analysis from scenario results
        new_analysis = Analysis(
            thread_id=scenario.thread_id,
            scoring_framework_id=baseline.scoring_framework_id,
            user_id=user_id,
            name=data.get("name", f"{scenario.label} - Applied"),
            description=f"Analysis created from scenario: {scenario.label}",
            scores=scenario.result.get("scores", {}),
            overall_score=scenario.result.get("overall_score", 0),
            status="completed",
            input_context={
                "source": "scenario",
                "scenario_id": scenario.scenario_id,
                "baseline_analysis_id": baseline.id,
            },
            meta={
                "financial_analysis": scenario.result.get("financial_analysis", {}),
                "metrics": scenario.result.get("metrics", {}),
                "extracted_levers": (scenario.meta or {}).get("inputs", {}),
                "scenario_deltas": scenario.deltas,
            },
            analyzed_at=datetime.utcnow(),
        )

        db.session.add(new_analysis)
        db.session.commit()

        _meta = new_analysis.meta or {}
        return jsonify({
            "analysis": {
                "id": new_analysis.id,
                "analysis_id": new_analysis.id,
                "overall_score": new_analysis.overall_score,
                "market_iq_score": new_analysis.overall_score,
                "scores": new_analysis.scores,
                "financial_analysis": _meta.get("financial_analysis", {}),
                "financial_impact": _meta.get("financial_analysis", {}),
                "metrics": _meta.get("metrics", {}),
                "name": new_analysis.name,
                "label": new_analysis.name,
                "status": new_analysis.status,
                "created_at": new_analysis.created_at.isoformat(),
                "analyzed_at": new_analysis.analyzed_at.isoformat() if new_analysis.analyzed_at else None,
            },
            "message": "scenario_applied"
        }), 201

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("apply_scenario failed")
        return jsonify({"error": "server_error", "detail": str(e)}), 500


@ai_agent_scenarios_bp.route("/scenarios/<scenario_id>/adopt", methods=["POST"])
@jwt_required()
def adopt_scenario(scenario_id):
    """
    Adopt scenario as the current thread analysis.
    This creates a new analysis AND updates thread.adopted_analysis_id.
    """
    try:
        user_id = get_jwt_identity()
        data = request.get_json() or {}

        scenario = MiqScenario.query.filter_by(scenario_id=scenario_id).first()
        if not scenario:
            return jsonify({"error": "scenario_not_found"}), 404

        thread = AgentThread.query.filter_by(
            id=scenario.thread_id,
            deleted_at=None
        ).first()

        if not thread:
            return jsonify({"error": "thread_not_found"}), 404

        # Get baseline analysis for framework reference
        baseline = Analysis.query.filter_by(
            id=scenario.based_on,
            deleted_at=None
        ).first()

        if not baseline:
            return jsonify({"error": "baseline_not_found"}), 404

        # Create new analysis from scenario
        adopted_analysis = Analysis(
            thread_id=scenario.thread_id,
            scoring_framework_id=baseline.scoring_framework_id,
            user_id=user_id,
            name=data.get("name", f"{scenario.label} - Adopted"),
            description=f"Adopted scenario: {scenario.label}",
            scores=scenario.result.get("scores", {}),
            overall_score=scenario.result.get("overall_score", 0),
            status="completed",
            input_context={
                "source": "scenario_adopted",
                "scenario_id": scenario.scenario_id,
                "baseline_analysis_id": baseline.id,
            },
            meta={
                "financial_analysis": scenario.result.get("financial_analysis", {}),
                "metrics": scenario.result.get("metrics", {}),
                "extracted_levers": (scenario.meta or {}).get("inputs", {}),
                "scenario_deltas": scenario.deltas,
            },
            analyzed_at=datetime.utcnow(),
        )

        db.session.add(adopted_analysis)
        db.session.flush()  # Get the ID

        # Persist adopted_analysis_id inside thread.context (JSON).
        # AgentThread does NOT have a dedicated adopted_analysis_id column;
        # context is the designated JSON bag for this kind of thread-level state.
        ctx = dict(thread.context or {})
        ctx["adopted_analysis_id"] = adopted_analysis.id
        ctx.setdefault("scorecard_snapshots", []).append({
            "id": adopted_analysis.id,
            "label": scenario.label,
            "overall_score": scenario.result.get("overall_score", 0) if scenario.result else 0,
            "adopted_at": datetime.utcnow().isoformat(),
            "isBaseline": False,
        })
        thread.context = ctx
        flag_modified(thread, "context")
        thread.last_activity_at = datetime.utcnow()

        db.session.commit()

        _meta = adopted_analysis.meta or {}
        return jsonify({
            "analysis": {
                **adopted_analysis.to_dict(),
                "financial_analysis": _meta.get("financial_analysis"),
                "metrics": _meta.get("metrics"),
                "extracted_levers": _meta.get("extracted_levers"),
            },
            "thread": {
                "id": thread.id,
                "adopted_analysis_id": adopted_analysis.id,
                "scorecard_snapshots": ctx.get("scorecard_snapshots", []),
            },
            "message": "scenario_adopted"
        }), 201

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("adopt_scenario failed")
        return jsonify({"error": "server_error", "detail": str(e)}), 500
