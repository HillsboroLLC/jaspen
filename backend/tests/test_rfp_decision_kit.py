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
from app.models_decision_record import DecisionRecord
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
        json.dumps({"tasks": [{"id": "submit", "title": "Submit JeffCo response", "estimated_days": 2, "lineage": [{"type": "decision_commitment", "ref": record.id}]}]}),
        {"provider": "anthropic", "model": "test", "input_tokens": 1, "output_tokens": 1},
    ))
    allowed = client.post(f"/api/v1/strategy/threads/{thread_id}/ai-wbs", headers=auth_headers, json={"commit": True, "scorecard_id": "rfp-card"})
    assert allowed.status_code == 200, allowed.get_json()
    assert allowed.get_json()["project_wbs"]["tasks"], allowed.get_json()
    assert allowed.get_json()["project_wbs"]["tasks"][0]["lineage"][0]["ref"] == record.id


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
    assert record.final_decision == "Bid with conditions for Aurora."
    assert record.record["kit_verdict"]["option_key"] == "opt-live"
