from copy import deepcopy

import pytest

from app.decision_fingerprint import scoring_fingerprint
from app.decision_kits import get_decision_kit, list_decision_kits
from app.decision_kits.registry import validate_decision_kit
from app.decision_lineage import build_lineage_sources, schedule_backward, validate_plan_lineage
from app.decision_metrics import calculate_metrics
from app.decision_facts import normalize_option_facts
from app.decision_processing import apply_decision_kit, normalize_gates
from app.decision_recommendation import recommend
from app.decision_selection import select_options
from app.models_decision_record import DecisionRecord, OptionDecision
from app.scorecards import upsert_scorecard


def attr(value, source="user"):
    return {"value": value, "source": source}


def rubric_with_gate():
    return {"approved_by_user_at": "2026-10-04T12:00:00Z", "criteria": [
        {"key": "deadline", "label": "Deadline feasible", "gate": True, "gate_rule": "Can submit"},
        {"key": "fit", "label": "Fit", "weight": 1},
    ]}


def test_decision_kit_catalog_keeps_general_and_objective_independent():
    assert [item["key"] for item in list_decision_kits()] == [None, "rfp_bid", "rfp_vendor_selection"]
    fingerprint = scoring_fingerprint(option_key="a", attributes={}, rubric={}, objective="growth", decision_kit="rfp_bid", decision_kit_version=1, evidence_corpus="")
    assert fingerprint != scoring_fingerprint(option_key="a", attributes={}, rubric={}, objective="balanced", decision_kit="rfp_bid", decision_kit_version=1, evidence_corpus="")


def test_structured_fields_and_metric_provenance_round_trip():
    kit = get_decision_kit("rfp_bid")
    attributes = {"client": attr("JeffCo"), "contract_value": attr(42_000_000, "document"), "win_probability": attr(22.5), "margin_pct": attr(4.5), "pursuit_cost": attr(85_050)}
    card = apply_decision_kit({"jaspen_score": 65, "attributes": deepcopy(attributes), "dimensions": {"fit": {"score": 70, "confidence": "medium"}}}, decision_kit="rfp_bid", decision_kit_version=1)
    assert card["attributes"] == attributes
    assert card["metrics"]["expected_value"]["inputs"]["contract_value"]["source"] == "document"


def test_expected_margin_and_roi_are_deterministic():
    metrics = calculate_metrics({"contract_value": attr(42_000_000), "win_probability": attr(22.5), "margin_pct": attr(4.5), "pursuit_cost": attr(85_050)}, get_decision_kit("rfp_bid")["metrics"])
    assert metrics["expected_value"]["value"] == 425_250
    assert metrics["pursuit_roi"]["value"] == 5
    assert metrics["expected_value"]["formula"] == "expected_value"


def test_fractional_provider_percentages_normalize_to_percent_points_before_metrics():
    kit = get_decision_kit("rfp_bid")
    attributes = normalize_option_facts({
        "contract_value": {"value": 14_000_000, "source": "user", "evidence": "Contract value $14M"},
        "win_probability": {"value": 0.60, "source": "user", "evidence": "Win probability 60%"},
        "margin_pct": {"value": 0.08, "source": "user", "evidence": "Margin 8%"},
    }, kit=kit)
    assert attributes["win_probability"]["value"] == 60
    assert attributes["margin_pct"]["value"] == 8
    assert attributes["win_probability"]["unit"] == "percent_points"
    metrics = calculate_metrics(attributes, kit["metrics"])
    assert metrics["expected_value"]["value"] == 672_000


def test_missing_metric_input_never_invents_a_value():
    metrics = calculate_metrics({"contract_value": attr(42_000_000)}, get_decision_kit("rfp_bid")["metrics"])
    assert metrics["expected_value"]["value"] is None
    assert metrics["expected_value"]["missing_inputs"] == ["win_probability", "margin_pct"]


def test_mandatory_gate_requires_grounded_evidence_and_can_fail():
    rubric = rubric_with_gate()
    assumed = normalize_gates([{"key": "deadline", "status": "pass", "source": "assumed", "evidence": []}], rubric, "Can submit by Friday")
    assert assumed[0]["status"] == "unknown"
    failed = normalize_gates([{"key": "deadline", "status": "fail", "source": "document", "confidence": "high", "evidence": ["Cannot submit"]}], rubric, "The team said: Cannot submit")
    assert failed[0]["status"] == "fail"



def test_proposed_rubric_authorized_by_score_request_keeps_its_gates():
    rubric = {**rubric_with_gate(), "approval_status": "proposed", "scoring_authorized_by": "explicit_score_request"}
    rubric.pop("approved_by_user_at", None)
    gates = normalize_gates([], rubric, "")
    assert [gate["key"] for gate in gates] == ["deadline"]
    assert gates[0]["status"] == "unknown"
    unauthorized = {**rubric}
    unauthorized.pop("scoring_authorized_by")
    assert normalize_gates([], unauthorized, "") == []

@pytest.mark.parametrize("score,confidence,gates,expected", [
    (70, 75, [{"key": "g", "status": "pass"}], "advance"),
    (55, 75, [{"key": "g", "status": "pass"}], "advance_with_conditions"),
    (80, 80, [{"key": "g", "status": "fail"}], "decline"),
])
def test_recommendation_is_decomposable(score, confidence, gates, expected):
    card = {"jaspen_score": score, "gates": gates, "decision_confidence": {"confidence_pct": confidence}, "dimensions": {}}
    result = recommend(card, get_decision_kit("rfp_bid"))
    assert result["verdict_key"] == expected
    assert result["thresholds_used"]["version"] == 1
    assert {step["step"] for step in result["trace"]} >= {"score", "confidence"}


def test_prose_only_change_does_not_change_kit_fingerprint_but_fact_change_does():
    base = dict(option_key="opt-a", attributes={"client": attr("Aurora")}, rubric=rubric_with_gate(), objective="balanced", decision_kit="rfp_bid", decision_kit_version=1, evidence_corpus="same")
    first = scoring_fingerprint(**base, facts_text="first prose")
    assert first == scoring_fingerprint(**base, facts_text="rewritten prose")
    assert first != scoring_fingerprint(**{**base, "attributes": {"client": attr("Commerce City")}}, facts_text="rewritten prose")


def test_constrained_selection_finds_best_feasible_combination_and_honors_lock():
    options = [
        {"option_key": "a", "name": "A", "locked": True, "metrics": {"expected_value": attr(80)}, "attributes": {"capacity_draw": attr(40)}},
        {"option_key": "b", "name": "B", "metrics": {"expected_value": attr(70)}, "attributes": {"capacity_draw": attr(20)}},
        {"option_key": "c", "name": "C", "metrics": {"expected_value": attr(100)}, "attributes": {"capacity_draw": attr(30)}},
    ]
    result = select_options(options, [{"key": "cap_capacity_draw", "value": 60}, {"key": "max_selected", "value": 2}], objective_metric="expected_value")
    assert [item["option_key"] for item in result["best"]["options"]] == ["a", "b"]
    assert result["best"]["objective_value"] == 150


def test_constrained_selection_excludes_missing_bonding_without_fabricating_zero():
    options = [
        {"option_key": "complete", "name": "Complete bid", "jaspen_score": 70, "metrics": {"expected_value": attr(400_000)}, "attributes": {"capacity_draw": attr(40_000_000)}},
        {"option_key": "cdot", "name": "CDOT", "jaspen_score": 90, "metrics": {"expected_value": attr(900_000)}, "attributes": {"capacity_draw": attr(None)}},
    ]
    result = select_options(options, [{"key": "cap_capacity_draw", "value": 60_000_000}], objective_metric="expected_value")

    assert [item["option_key"] for item in result["best"]["options"]] == ["complete"]
    cdot = next(item for item in result["excluded"] if item["option_key"] == "cdot")
    assert cdot == {
        "option_key": "cdot",
        "name": "CDOT",
        "reason": "missing bonding requirement",
        "not_evaluable": True,
        "missing_values": {"capacity_draw": None},
    }


def test_constrained_selection_returns_cannot_evaluate_when_objective_input_is_missing():
    options = [{
        "option_key": "unknown-contract",
        "name": "Unknown contract",
        "jaspen_score": 80,
        "metrics": {"expected_value": {"value": None, "missing_inputs": ["contract_value"]}},
        "attributes": {"capacity_draw": attr(10_000_000), "contract_value": attr(None)},
    }]
    result = select_options(options, [{"key": "cap_capacity_draw", "value": 60_000_000}], objective_metric="expected_value")

    assert result["status"] == "cannot_evaluate"
    assert result["can_evaluate"] is False
    assert result["reason"] == "cannot evaluate with current inputs"
    assert result["best"] is None
    assert result["excluded"][0]["reason"] == "missing contract value"
    assert result["excluded"][0]["missing_values"] == {"contract_value": None}


def test_complete_seven_bid_fixture_keeps_mathematically_optimal_portfolio():
    def bid(key, name, bonding, expected_margin, score):
        return {
            "option_key": key,
            "name": name,
            "jaspen_score": score,
            "metrics": {"expected_value": attr(expected_margin)},
            "attributes": {"capacity_draw": attr(bonding)},
        }

    options = [
        bid("childrens", "Children's Hospital", 20_000_000, 700_000, 88),
        bid("du", "DU Residence Hall", 15_000_000, 500_000, 82),
        bid("commerce", "Commerce City", 20_000_000, 360_000, 74),
        bid("tech", "Tech TI", 15_000_000, 250_000, 72),
        bid("airport", "Airport Concourse", 30_000_000, 240_000, 69),
        bid("cdot", "CDOT", 25_000_000, 220_000, 67),
        bid("library", "Library Expansion", 10_000_000, 100_000, 65),
    ]
    result = select_options(
        options,
        [{"key": "cap_capacity_draw", "value": 60_000_000}, {"key": "max_selected", "value": 3}],
        objective_metric="expected_value",
    )

    assert [item["name"] for item in result["best"]["options"]] == ["Children's Hospital", "DU Residence Hall", "Commerce City"]
    assert result["best"]["constraints"]["cap_capacity_draw"]["used"] == 55_000_000
    assert result["best"]["objective_value"] == 1_560_000
    assert [item["name"] for item in result["runner_up"]["options"]] == ["Children's Hospital", "DU Residence Hall", "Tech TI"]
    assert result["runner_up"]["constraints"]["cap_capacity_draw"]["used"] == 50_000_000
    assert result["runner_up"]["objective_value"] == 1_450_000


def test_every_execution_task_must_have_valid_lineage_and_cover_every_source():
    sources = [{"type": "requirement", "ref": "r1", "label": "Submit form", "required": True}]
    valid, audit = validate_plan_lineage({"tasks": [{"id": "t1", "title": "Prepare form", "lineage": [{"type": "requirement", "ref": "r1"}]}]}, sources)
    assert valid["tasks"][0]["lineage"][0]["ref"] == "r1"
    invalid, audit = validate_plan_lineage({"tasks": [{"id": "t1", "title": "Generic kickoff", "lineage": []}]}, sources)
    assert invalid is None
    assert audit["dropped_tasks"] == ["t1"]
    assert audit["dropped_task_details"] == [{"task": "t1", "reason": "missing_lineage"}]


def test_validated_plan_preserves_phase_order_dependencies_and_drops_empty_phases():
    sources = [{"type": "decision_commitment", "ref": "d1", "label": "Proceed", "required": True}]
    lineage = [{"type": "decision_commitment", "ref": "d1"}]
    plan = {
        "name": "Complete launch",
        "phases": [
            {"name": "Mobilize", "tasks": [{"id": "a", "title": "Kick off launch", "lineage": lineage}]},
            {"name": "Build", "tasks": [{"id": "b", "title": "Build launch", "dependencies": ["a"], "lineage": lineage}]},
            {"name": "Empty after validation", "tasks": [{"id": "junk", "title": "Untraceable", "lineage": []}]},
            {"name": "Closeout", "tasks": [{"id": "c", "title": "Close launch", "dependencies": ["b", "future"], "lineage": lineage}]},
        ],
    }
    validated, audit = validate_plan_lineage(plan, sources)
    assert [phase["name"] for phase in validated["phases"]] == ["Mobilize", "Build", "Closeout"]
    assert [task["id"] for task in validated["tasks"]] == ["a", "b", "c"]
    assert validated["tasks"][1]["dependencies"] == ["a"]
    assert validated["tasks"][2]["dependencies"] == ["b"]
    assert audit["dropped_tasks"] == ["junk"]
    assert audit["dropped_task_details"] == [{"task": "junk", "reason": "missing_lineage"}]


def test_lineage_audit_distinguishes_missing_from_invalid_references():
    sources = [{"type": "requirement", "ref": "required", "label": "Required", "required": True}]
    _validated, audit = validate_plan_lineage({"tasks": [
        {"id": "missing", "title": "No lineage", "lineage": []},
        {"id": "invalid", "title": "Wrong lineage", "lineage": [
            {"type": "requirement", "ref": "other"},
        ]},
    ]}, sources)
    assert audit["dropped_task_details"] == [
        {"task": "missing", "reason": "missing_lineage"},
        {"task": "invalid", "reason": "invalid_lineage_reference"},
    ]


def test_materialize_keeps_real_phases_and_flat_plan_uses_plan_name():
    from app.routes.strategy import _materialize_ai_wbs

    phased = {"name": "Launch", "phases": [
        {"name": "Prepare", "tasks": [{"id": "a", "title": "Prepare launch", "lineage": [{"type": "decision_commitment", "ref": "d1"}]}]},
        {"name": "Deliver", "tasks": [{"id": "b", "title": "Deliver launch", "dependencies": ["a"], "lineage": [{"type": "decision_commitment", "ref": "d1"}]}]},
        {"name": "Close", "tasks": [{"id": "c", "title": "Close launch", "dependencies": ["b"], "lineage": [{"type": "decision_commitment", "ref": "d1"}]}]},
    ]}
    first = _materialize_ai_wbs(phased, start_date="2026-10-20")
    second = _materialize_ai_wbs(phased, start_date="2026-10-20")
    assert [phase["name"] for phase in first["phases"]] == ["Prepare", "Deliver", "Close"]
    assert [task["phase"] for task in first["tasks"]] == ["Prepare", "Deliver", "Close"]
    assert first == second

    flat = _materialize_ai_wbs({"name": "Named delivery plan", "tasks": [{"id": "x", "title": "Deliver result"}]}, start_date="2026-10-20")
    assert flat["phases"][0]["name"] == "Named delivery plan"
    assert flat["tasks"][0]["phase"] == "Named delivery plan"


def test_execution_prompt_restores_full_plan_rules_alongside_lineage():
    from pathlib import Path
    source = Path(__file__).parents[1].joinpath("app/routes/strategy.py").read_text()
    assert "Return 10-18 tasks total spread across 4-6 meaningful phases." in source
    assert "Phases must follow a logical sequence: Discovery -> Planning -> Build/Execute -> Validate -> Launch -> Operate." in source
    assert "Include every task required to deliver the decision end to end" in source
    assert "Do not pad with generic busywork, and do not omit necessary delivery work" in source
    assert "Include at least 1 risk-mitigation task, 1 change-management task, and 1 value-capture/measurement task." in source
    assert "Estimated_days should be realistic for the task complexity (range: 1-15)." in source
    assert "MINIMUM 10 tasks. If you return fewer than 10 the response will be rejected." in source
    assert "Necessary delivery tasks must cite the recorded decision through decision_commitment lineage." in source
    assert "Do not add tasks to reach a count" not in source


def test_four_phase_twelve_task_plan_survives_generation_validation_and_materialization(app, monkeypatch):
    import json
    from app.routes import strategy

    lineage = [{"type": "decision_commitment", "ref": "decision-1"}]
    phases = []
    prior_id = None
    task_number = 1
    for phase_name in ("Discovery", "Planning", "Build and Execute", "Validate and Launch"):
        tasks = []
        for _ in range(3):
            task_id = f"task-{task_number}"
            task = {
                "id": task_id,
                "title": f"Deliver Acme launch work item {task_number}",
                "description": f"Complete Acme launch work item {task_number}",
                "estimated_days": (task_number % 5) + 1,
                "activity_type": (
                    "risk_management" if task_number == 3
                    else "change_management" if task_number == 6
                    else "reporting" if task_number == 12
                    else "delivery"
                ),
                "dependencies": [prior_id] if prior_id else [],
                "lineage": lineage,
            }
            tasks.append(task)
            prior_id = task_id
            task_number += 1
        phases.append({"name": phase_name, "tasks": tasks})
    response = {"name": "Acme launch plan", "phases": phases}
    captured = {}

    def provider(messages, **_kwargs):
        captured["prompt"] = messages[0]["content"]
        return json.dumps(response), {"provider": "test", "total_tokens": 1}

    monkeypatch.setattr(strategy, "_strategy_generate_reply", provider)
    plan, _, success, error = strategy._generate_ai_wbs_suggestion(
        None,
        "test",
        scorecard={"project_name": "Acme launch"},
        instruction="Build the execution plan.",
        model_selection={"llm_model": "test"},
        return_usage=True,
        lineage_sources=[{
            "type": "decision_commitment", "ref": "decision-1",
            "label": "Proceed with Acme launch", "required": True,
        }],
    )

    assert success and error is None
    assert "Return 10-18 tasks total spread across 4-6 meaningful phases." in captured["prompt"]
    assert [phase["name"] for phase in plan["phases"]] == [phase["name"] for phase in phases]
    assert [len(phase["tasks"]) for phase in plan["phases"]] == [3, 3, 3, 3]
    assert len(plan["tasks"]) == 12

    materialized = strategy._materialize_ai_wbs(plan, start_date="2026-10-20")
    assert [phase["name"] for phase in materialized["phases"]] == [phase["name"] for phase in phases]
    assert [len(phase["task_ids"]) for phase in materialized["phases"]] == [3, 3, 3, 3]
    assert len(materialized["tasks"]) == 12
    assert materialized["tasks"][1]["depends_on"] == [materialized["tasks"][0]["id"]]


def test_lineage_sources_include_recorded_decision_and_backward_schedule():
    card = {"attributes": {"submission_due": attr("2026-11-14"), "mandatory_requirements": attr(["Signed form"])}, "dimensions": {}, "gates": []}
    sources = build_lineage_sources(card, get_decision_kit("rfp_bid"), {"id": "d1", "final_decision": "Bid"})
    assert {item["type"] for item in sources} == {"requirement", "decision_commitment"}
    plan = schedule_backward({"tasks": [{"id": "t1", "title": "Submit", "estimated_days": 2, "lineage": []}]}, "2026-11-14")
    assert plan["schedule_mode"] == "backward"
    assert plan["tasks"][0]["due_date"] < "2026-11-14"


def test_threshold_change_requires_kit_version_bump_and_existing_v1_stays_stable():
    v1 = get_decision_kit("rfp_bid")
    changed = deepcopy(v1)
    changed["verdict_thresholds"]["advance_min_score"] = 70
    with pytest.raises(ValueError, match="version bump"):
        validate_decision_kit(changed, previous=v1)
    card = {"jaspen_score": 65, "decision_confidence": {"confidence_pct": 70}, "attributes": {}, "gates": [], "dimensions": {}}
    scored = apply_decision_kit(card, decision_kit="rfp_bid", decision_kit_version=1)
    assert scored["recommendation"]["kit_version"] == 1


def test_only_human_recorded_bid_unlocks_rfp_execution_plan(client, db, test_user, auth_headers, monkeypatch):
    import json
    import sys
    from app.routes.sessions import save_user_sessions

    strategy = sys.modules["app.routes.strategy"]
    agent = sys.modules["app.routes.ai_agent"]
    thread_id = "rfp-plan-gate"
    card = {
        "id": "rfp-card", "analysis_id": "rfp-card", "option_key": "opt-rfp",
        "project_name": "JeffCo RFP", "jaspen_score": 70, "dimensions": {},
        "recommendation": {"verdict_key": "decline", "label": "No-Bid"},
        "attributes": {"submission_due": attr("2026-11-14")},
        "decision_kit": "rfp_bid", "decision_kit_version": 1,
    }
    session = {
        "session_id": thread_id, "user_id": test_user.id, "name": "RFP",
        "status": "completed", "decision_kit": "rfp_bid", "decision_kit_version": 1,
        "result": {**card, "_baseline_scorecard": card, "scorecard_snapshots": [card]},
        "chat_history": [], "scorecard_queue": [],
    }
    assert save_user_sessions(test_user.id, {thread_id: session})
    upsert_scorecard(user_id=test_user.id, thread_id=thread_id, payload=card)
    db.session.commit()

    blocked = client.post(f"/api/v1/strategy/threads/{thread_id}/ai-wbs", headers=auth_headers, json={"commit": True, "scorecard_id": "rfp-card"})
    assert blocked.status_code == 409
    assert blocked.get_json()["code"] == "recorded_advancing_decision_required"

    record = DecisionRecord(
        user_id=test_user.id, organization_id=None, thread_id=thread_id,
        title="JeffCo RFP", decision_type="rfp_bid", status="decided", final_decision="Bid",
        record={"decision_kit": "rfp_bid", "decision_kit_version": 1, "scorecards": [card], "kit_verdict": {"verdict_key": "advance", "option_key": "opt-rfp", "scorecard_id": "rfp-card"}},
    )
    db.session.add(record)
    db.session.commit()
    monkeypatch.setattr(strategy, "get_llm_client", lambda: object())
    monkeypatch.setattr(agent, "_reserve_preflight_credits", lambda *a, **k: {"ok": True, "reserved": 0})
    monkeypatch.setattr(agent, "_settle_reserved_credits", lambda *a, **k: {"ok": True, "charged": 0})
    monkeypatch.setattr(strategy, "_strategy_generate_reply", lambda *a, **k: (
        json.dumps({"tasks": [
            {
                "id": f"submit-{index}",
                "title": f"Complete JeffCo response work item {index}",
                "estimated_days": 2,
                "lineage": [{"type": "decision_commitment", "ref": record.id}],
            }
            for index in range(1, 11)
        ]}),
        {"provider": "anthropic", "model": "test", "input_tokens": 1, "output_tokens": 1},
    ))
    allowed = client.post(f"/api/v1/strategy/threads/{thread_id}/ai-wbs", headers=auth_headers, json={
        "commit": True, "scorecard_id": "rfp-card",
        "record_decision": {"acknowledged": True, "option_key": "opt-rfp"},
    })
    assert allowed.status_code == 200, allowed.get_json()
    assert allowed.get_json()["project_wbs"]["tasks"], allowed.get_json()
    assert allowed.get_json()["project_wbs"]["tasks"][0]["lineage"][0]["ref"] == record.id


def test_build_plan_decision_uses_shared_record_and_exposes_decline_override(db, test_user):
    from app.decision_records import record_execution_plan_decision
    from app.routes.sessions import save_user_sessions

    thread_id = "rfp-plan-decline-override"
    card = {
        "id": "decline-card", "analysis_id": "decline-card", "option_key": "opt-decline",
        "project_name": "CDOT Bridge", "jaspen_score": 20, "dimensions": {},
        "decision_kit": "rfp_bid", "decision_kit_version": 1,
        "recommendation": {"verdict_key": "decline", "label": "No-Bid"},
    }
    session = {
        "session_id": thread_id, "user_id": test_user.id, "name": "CDOT RFP",
        "status": "completed", "decision_kit": "rfp_bid", "decision_kit_version": 1,
        "result": card, "chat_history": [], "scorecard_queue": [],
    }
    assert save_user_sessions(test_user.id, {thread_id: session})
    upsert_scorecard(user_id=test_user.id, thread_id=thread_id, payload=card)
    db.session.commit()

    first = record_execution_plan_decision(
        test_user, thread_id, card, decision_kit=get_decision_kit("rfp_bid"),
    )
    second = record_execution_plan_decision(
        test_user, thread_id, card, decision_kit=get_decision_kit("rfp_bid"),
    )

    assert first.id == second.id
    assert DecisionRecord.query.filter_by(thread_id=thread_id).count() == 1
    verdict = second.kit_verdict
    assert verdict["verdict_key"] == "advance"
    assert verdict["override_of"] == "decline"
    assert verdict["source"] == "build_execution_plan"


def test_live_rfp_record_keeps_option_and_accepts_human_verdict(client, db, test_user, auth_headers):
    from app.decision_records import create_or_refresh_record
    from app.routes.sessions import save_user_sessions

    thread_id = "rfp-live-human-decision"
    card = {
        "id": "rfp-live-card",
        "analysis_id": "rfp-live-card",
        "option_key": "opt-live",
        "project_name": "Aurora RFP",
        "jaspen_score": 62,
        "dimensions": {"fit": {"score": 62, "confidence": "medium"}},
        "decision_kit": "rfp_bid",
        "decision_kit_version": 1,
        "recommendation": {"verdict_key": "advance_with_conditions", "label": "Bid with conditions", "trace": []},
    }
    session = {
        "session_id": thread_id,
        "user_id": test_user.id,
        "name": "Aurora RFP",
        "status": "completed",
        "decision_kit": "rfp_bid",
        "decision_kit_version": 1,
        "result": {**card, "_baseline_scorecard": card, "scorecard_snapshots": []},
        "chat_history": [],
    }
    assert save_user_sessions(test_user.id, {thread_id: session})
    upsert_scorecard(user_id=test_user.id, thread_id=thread_id, payload=card)
    db.session.commit()

    record, created = create_or_refresh_record(test_user, thread_id)
    assert created is True
    snapshot = record.record["scorecards"][0]
    assert snapshot["option_key"] == "opt-live"
    assert snapshot["recommendation"]["verdict_key"] == "advance_with_conditions"

    response = client.patch(
        f"/api/v1/decision-records/{record.id}",
        headers=auth_headers,
        json={
            "final_decision": "Bid with conditions for Aurora.",
            "kit_verdict": {
                "verdict_key": "advance_with_conditions",
                "scorecard_id": "rfp-live-card",
                "option_key": "opt-live",
            },
        },
    )
    assert response.status_code == 200, response.get_json()
    db.session.refresh(record)
    assert record.final_decision is None
    option_decision = OptionDecision.query.filter_by(
        decision_record_id=record.id, option_key='opt-live'
    ).one()
    assert option_decision.final_decision == "Bid with conditions for Aurora."
    assert option_decision.kit_verdict["option_key"] == "opt-live"
