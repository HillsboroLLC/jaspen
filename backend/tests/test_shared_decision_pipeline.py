import json


def test_canonical_rfp_facts_normalize_types_units_and_provenance(app):
    from app.decision_facts import normalize_option_facts
    from app.decision_kits import get_decision_kit

    text = (
        "Aurora RFP has expected margin 4.5%, win probability 25%, contract value $60M, "
        "submission deadline November 14, 2026. Pursuit team includes Lee and Morgan. "
        "Mandatory requirements include a bid bond; signed form"
    )
    facts = normalize_option_facts({}, kit=get_decision_kit("rfp_bid"), source_text=text, option_name="Aurora RFP")

    assert facts["margin_pct"] == {"value": 4.5, "source": "user", "evidence": "expected margin 4.5%"}
    assert facts["win_probability"]["value"] == 25
    assert facts["contract_value"]["value"] == 60_000_000
    assert facts["contract_value"]["unit"] == "USD"
    assert facts["submission_due"]["value"] == "2026-11-14"
    assert facts["team"]["value"] == [{"name": "Lee"}, {"name": "Morgan"}]
    assert facts["mandatory_requirements"]["value"] == ["a bid bond", "signed form"]


def test_unknown_and_invalid_fields_are_rejected_without_losing_valid_facts(app):
    from app.decision_facts import normalize_option_facts
    from app.decision_kits import get_decision_kit

    kit = get_decision_kit("rfp_bid")
    rejected = []
    facts = normalize_option_facts({
        "proposal_due_date": {"value": "11/14/2026", "source": "user"},
        "fictional_total": {"value": 10},
        "margin_pct": {"value": 140},
        "contract_value": {"value": "$60M"},
    }, kit=kit, rejected_fields=rejected)

    assert facts["submission_due"]["value"] == "2026-11-14"
    assert facts["contract_value"]["value"] == 60_000_000
    assert "fictional_total" not in facts
    assert "margin_pct" not in facts
    assert {item["field"] for item in rejected} == {"fictional_total", "margin_pct"}


def test_five_year_tco_alias_maps_to_vendor_selection_tco(app):
    from app.decision_facts import normalize_option_facts
    from app.decision_kits import get_decision_kit

    facts = normalize_option_facts(
        {"5yr_tco": {"value": "$12.5M", "source": "document", "evidence": "5yr TCO $12.5M"}},
        kit=get_decision_kit("rfp_vendor_selection"),
    )

    assert facts["tco"]["value"] == 12_500_000
    assert facts["tco"]["unit"] == "USD"


def test_assumed_fact_deterministically_caps_affected_confidence(app):
    from app.decision_facts import apply_assumption_confidence_caps
    from app.decision_kits import get_decision_kit

    card = {"dimensions": {
        "financial_attractiveness": {"score": 80, "confidence": "high"},
        "strategic_fit_relationship": {"score": 80, "confidence": "high"},
    }}
    facts = {"margin_pct": {
        "value": 4.5,
        "source": "assumed",
        "evidence": "",
        "assumption": {"basis": "working estimate", "bounds": [3, 6]},
    }}
    result = apply_assumption_confidence_caps(card, facts, get_decision_kit("rfp_bid"))

    assert result["dimensions"]["financial_attractiveness"]["confidence"] == "assumed"
    assert result["dimensions"]["strategic_fit_relationship"]["confidence"] == "high"
    assert result["assumption_register"][0]["field"] == "margin_pct"


def test_batch_uses_the_same_scorer_and_result_as_single(app, monkeypatch):
    from app.routes import strategy

    response = {
        "dimensions": {
            "fit": {"score": 72, "confidence": "medium", "source": "conversation", "evidence": ["strong fit"], "rationale": "Strong fit."},
            "risk": {"score": 62, "confidence": "low", "source": "inferred", "evidence": [], "rationale": "Risk is unresolved."},
        },
        "gates": [],
    }
    monkeypatch.setattr(strategy, "_strategy_generate_reply", lambda *a, **k: (json.dumps(response), {"provider": "test", "input_tokens": 1, "output_tokens": 1}))
    rubric = {"approved_by_user_at": "2026-10-05T00:00:00Z", "criteria": [
        {"key": "fit", "label": "Fit", "weight": 0.6},
        {"key": "risk", "label": "Risk", "weight": 0.4, "is_risk": True},
    ]}
    corpus = "The user described strong fit."
    single = strategy._generate_jaspen_scorecard(None, "Option A", "test", rubric=rubric, evidence_corpus=corpus)
    batch, _summary = strategy._generate_batch_scorecards(None, [{"name": "Option A"}], rubric=rubric, evidence_corpus=corpus, llm_model="test")

    for key in ("jaspen_score", "score_category", "dimensions", "evidence_profile", "data_confidence"):
        assert batch[0][key] == single[key]


def test_batch_and_single_apply_identical_per_option_gates(app, monkeypatch):
    from app.routes import strategy

    response = {
        "dimensions": {"fit": {"score": 70, "confidence": "medium", "source": "conversation", "evidence": ["deadline is feasible"], "rationale": "Feasible."}},
        "gates": [{"key": "deadline", "status": "pass", "confidence": "medium", "source": "conversation", "evidence": ["deadline is feasible"]}],
    }
    monkeypatch.setattr(strategy, "_strategy_generate_reply", lambda *a, **k: (json.dumps(response), {"provider": "test"}))
    rubric = {"approved_by_user_at": "2026-10-05T00:00:00Z", "criteria": [
        {"key": "deadline", "label": "Deadline", "gate": True, "gate_rule": "Can submit", "option_key": "opt-a"},
        {"key": "fit", "label": "Fit", "weight": 1},
    ]}
    kwargs = dict(rubric=rubric, evidence_corpus="deadline is feasible", decision_kit="rfp_bid", decision_kit_version=1, option_key="opt-a")
    single = strategy._generate_jaspen_scorecard(None, "A", "test", **kwargs)
    batch, _ = strategy._generate_batch_scorecards(None, [{"name": "A", "option_key": "opt-a"}], rubric=rubric, evidence_corpus="deadline is feasible", llm_model="test", decision_kit="rfp_bid", decision_kit_version=1)
    assert batch[0]["gates"] == single["gates"]
    assert single["gates"][0]["status"] == "pass"


def test_gate_scoped_to_another_option_is_not_applied(app):
    from app.decision_processing import normalize_gates

    rubric = {"approved_by_user_at": "now", "criteria": [
        {"key": "bond", "label": "Bond", "gate": True, "option_key": "aurora"},
    ]}
    raw = [{"key": "bond", "status": "fail", "evidence": ["bond unavailable"], "source": "user"}]
    assert normalize_gates(raw, rubric, "bond unavailable", option_key="commerce") == []


def test_natural_language_option_only_gate_applies_to_one_option(app):
    from app.decision_processing import normalize_gates
    rubric = {"approved_by_user_at": "now", "criteria": [
        {"key": "bond", "label": "Bond", "gate": True, "scope": "Option C only"},
    ]}
    raw = [{"key": "bond", "status": "fail", "source": "user", "confidence": "high", "evidence": ["bond unavailable"]}]
    assert normalize_gates(raw, rubric, "bond unavailable", option_name="Option A") == []
    assert normalize_gates(raw, rubric, "bond unavailable", option_name="Option B") == []
    assert normalize_gates(raw, rubric, "bond unavailable", option_name="Option C")[0]["status"] == "fail"


def test_explicit_gate_evidence_resolves_pass_fail_and_unknown_without_model_status(app):
    from app.decision_processing import normalize_gates
    rubric = {"approved_by_user_at": "now", "criteria": [
        {"key": "sbe", "label": "SBE participation", "gate": True, "gate_rule": "Reach 25% SBE participation"},
        {"key": "epic", "label": "Epic integration", "gate": True, "gate_rule": "Vendor has integrated with Epic"},
        {"key": "insurance", "label": "Insurance", "gate": True, "gate_rule": "Insurance is confirmed"},
    ]}
    corpus = (
        "We cannot reach 25% SBE participation. RegionalERP has never integrated with Epic. "
        "Insurance documentation is still under review."
    )
    result = {gate["key"]: gate for gate in normalize_gates([], rubric, corpus)}
    assert result["sbe"]["status"] == "fail"
    assert result["sbe"]["evidence"] == ["We cannot reach 25% SBE participation."]
    assert result["epic"]["status"] == "fail"
    assert result["insurance"]["status"] == "unknown"

    passed = normalize_gates([], rubric, "Workday has successfully integrated with Epic.")
    assert {gate["key"]: gate["status"] for gate in passed}["epic"] == "pass"


def test_model_overall_math_is_ignored_and_missing_values_stay_null(app, monkeypatch):
    from app.routes import strategy

    response = {"jaspen_score": 99, "component_scores": {}, "dimensions": {
        "fit": {"score": 50, "confidence": "medium", "source": "conversation", "evidence": ["Revenue is $5M"], "rationale": "Supported."},
        "value": {"score": 70, "confidence": "medium", "source": "conversation", "evidence": ["Revenue is $5M"], "rationale": "Supported."},
    }}
    monkeypatch.setattr(strategy, "_strategy_generate_reply", lambda *a, **k: (json.dumps(response), {"provider": "test"}))
    rubric = {"criteria": [{"key": "fit", "weight": 0.5}, {"key": "value", "weight": 0.5}]}
    card = strategy._generate_jaspen_scorecard(None, "A", "test", rubric=rubric, evidence_corpus="Revenue is $5M")
    assert card["jaspen_score"] == 60
    assert all(value is None for value in card["component_scores"].values())


def test_unsupported_numeric_chat_claim_is_removed(app):
    from app.routes.ai_agent import _sanitize_assistant_numeric_claims

    reply = _sanitize_assistant_numeric_claims(
        "The verified score is 72. ROI should be 18.5%.",
        user_message="",
        session={"result": {"id": "a", "jaspen_score": 72}},
    )
    assert "72" in reply
    assert "18.5%" not in reply

    wrong_context = _sanitize_assistant_numeric_claims(
        "The win probability is 25%. ROI is 25%.",
        user_message="The win probability is 25%.",
        session={},
    )
    assert "win probability is 25%" in wrong_context
    assert "ROI is 25%" not in wrong_context

    derived = _sanitize_assistant_numeric_claims(
        "$42M leaves $48M of your $90M headroom.",
        user_message="Contract value is $42M and maximum headroom is $90M.",
        session={},
    )
    assert "$48M" not in derived and "leaves" not in derived

    quoted = _sanitize_assistant_numeric_claims(
        "The user stated the contract value is $42M.",
        user_message="The user stated the contract value is $42M.",
        session={},
    )
    assert "$42M" in quoted


def test_score_it_now_bypasses_first_turn_confirmation_when_rubric_is_ready(app):
    from app.routes import ai_agent as agent
    ready = {"scoring_rubric": {"criteria": [{"key": "fit", "weight": 1}]}}
    assert agent._guard_mutation_tool(
        "generate_scorecard", user_turn_count=1, mutations_this_turn=0,
        user_message="Score it now", session=ready,
    ) is None
    blocked = agent._guard_mutation_tool(
        "generate_scorecard", user_turn_count=1, mutations_this_turn=0,
        user_message="Tell me about it", session=ready,
    )
    assert blocked["code"] == "confirmation_required"


def test_proposed_rubric_is_not_self_approved_and_same_turn_score_approves(app, test_user, monkeypatch):
    from app.routes import ai_agent as agent
    criteria = [{"label": "Fit", "weight": 60}, {"label": "Risk", "weight": 40}]
    proposed = agent._execute_mutation_tool(
        "set_scoring_rubric", {"criteria": criteria}, user=test_user,
        user_id=test_user.id, thread_id="rubric-proposed", user_message="Here is a possible approach.",
    )
    assert proposed["rubric"]["approval_status"] == "proposed"
    assert "approved_by_user_at" not in proposed["rubric"]
    assert proposed["rubric"]["source"] == "jaspen_proposed"

    approved = agent._execute_mutation_tool(
        "set_scoring_rubric", {"criteria": criteria}, user=test_user,
        user_id=test_user.id, thread_id="rubric-approved", user_message="Score it now",
    )
    assert approved["rubric"]["approval_status"] == "approved"
    assert approved["rubric"]["approved_by_user_at"]

    session = {}
    monkeypatch.setattr(agent, "_execute_mutation_tool", lambda *a, **k: {
        "ok": True, "tool": "set_scoring_rubric",
        "rubric": approved["rubric"],
    })
    result, _ = agent._execute_local_tool(
        "set_scoring_rubric", {"criteria": criteria}, readiness={}, user=test_user,
        user_id=test_user.id, thread_id="rubric-proposed", user_turn_count=1,
        mutations_this_turn=0, user_message="Score it now", session=session,
    )
    assert result["ok"] and session["scoring_rubric"]["approved_by_user_at"]
    assert agent._guard_mutation_tool(
        "generate_scorecard", user_turn_count=1, mutations_this_turn=0,
        user_message="Score it now", session=session,
    ) is None


def test_gate_narration_uses_only_canonical_result(app):
    from app.routes.ai_agent import _sanitize_assistant_numeric_claims
    actions = [{"result": {"scorecard": {"gates": [
        {"key": "epic", "label": "Epic integration", "status": "fail"},
    ]}}}]
    corrected = _sanitize_assistant_numeric_claims(
        "The Epic integration gate passes. Continue evaluation.", actions=actions,
    )
    assert "Epic integration: FAIL." in corrected
    assert "gate passes" not in corrected
    premature = _sanitize_assistant_numeric_claims(
        "The SBE gate fails. Continue evaluation.", actions=[],
    )
    assert "SBE gate fails" not in premature
    assert "Continue evaluation" in premature


def test_single_and_batch_use_identical_judge_contract_and_outputs(app, monkeypatch):
    from app.routes import strategy
    from app.decision_facts import normalize_option_facts
    from app.decision_kits import get_decision_kit
    kit = get_decision_kit("rfp_bid")
    rubric = {"approved_by_user_at": "now", "criteria": list(kit["starter_rubric"])}
    corpus = "Workday: Contract value $14M. Margin 8%. Surety confirmed."
    attributes = normalize_option_facts({
        "contract_value": {"value": 14_000_000, "source": "user", "evidence": "Contract value $14M"},
        "margin_pct": {"value": 8, "source": "user", "evidence": "Margin 8%"},
    }, kit=kit, extract=False)
    response = {"dimensions": {
        item["key"]: {"score": 63, "confidence": "medium", "source": "conversation", "evidence": ["Contract value $14M"], "rationale": "Grounded."}
        for item in kit["starter_rubric"]
    }, "gates": []}
    prompts = []
    def judge(messages, **kwargs):
        prompts.append(messages[0]["content"])
        return json.dumps(response), {"provider": "test"}
    monkeypatch.setattr(strategy, "_strategy_generate_reply", judge)
    common = dict(
        rubric=rubric, strategy_objective="balanced", evidence_corpus=corpus,
        decision_kit="rfp_bid", decision_kit_version=1, kit_context={},
    )
    single = strategy._generate_jaspen_scorecard(
        None, "Agent-authored single summary", "test", attributes=attributes,
        option_key="workday", option_name="Workday", **common,
    )
    batch, _ = strategy._generate_batch_scorecards(
        None, [{"name": "Workday", "description": "Different queued summary", "option_key": "workday", "attributes": attributes}],
        llm_model="test", **common,
    )
    assert prompts[0] == prompts[1]
    def stable(value):
        if isinstance(value, dict):
            return {key: stable(item) for key, item in value.items() if key not in {"id", "captured_at", "computed_at"}}
        if isinstance(value, list):
            return [stable(item) for item in value]
        return value
    for key in ("dimensions", "gates", "jaspen_score", "data_confidence", "recommendation"):
        assert stable(single[key]) == stable(batch[0][key])
