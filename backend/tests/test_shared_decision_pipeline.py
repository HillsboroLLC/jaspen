import json


def test_governed_extraction_candidates_normalize_types_units_and_provenance(app):
    from app.decision_facts import normalize_option_facts
    from app.decision_kits import get_decision_kit

    facts = normalize_option_facts({
        "margin": {"value": "4.5%", "source": "user", "evidence": "expected margin 4.5%"},
        "win_chance": {"value": "25%", "source": "user", "evidence": "win probability 25%"},
        "contract_amount": {"value": "$60M", "source": "user", "evidence": "contract value $60M"},
        "proposal_due_date": {"value": "November 14, 2026", "source": "user", "evidence": "submission deadline November 14, 2026"},
        "team": {"value": ["Lee", "Morgan"], "source": "user", "evidence": "Pursuit team includes Lee and Morgan"},
        "requirements": {"value": ["a bid bond", "signed form"], "source": "user", "evidence": "Mandatory requirements include a bid bond; signed form"},
    }, kit=get_decision_kit("rfp_bid"))

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


def test_gate_judgments_are_grounded_but_never_inferred_from_words(app):
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
    raw = [
        {"key": "sbe", "status": "fail", "source": "conversation", "confidence": "medium", "evidence": ["We cannot reach 25% SBE participation."]},
        {"key": "epic", "status": "fail", "source": "conversation", "confidence": "medium", "evidence": ["RegionalERP has never integrated with Epic."]},
        {"key": "insurance", "status": "pass", "source": "conversation", "confidence": "medium", "evidence": ["invented quote"]},
    ]
    result = {gate["key"]: gate for gate in normalize_gates(raw, rubric, corpus)}
    assert result["sbe"]["status"] == "fail"
    assert result["sbe"]["evidence"] == ["We cannot reach 25% SBE participation."]
    assert result["epic"]["status"] == "fail"
    assert result["insurance"]["status"] == "unknown"

    passed = normalize_gates([{
        "key": "epic", "status": "pass", "source": "conversation", "confidence": "medium",
        "evidence": ["Workday has successfully integrated with Epic."],
    }], rubric, "Workday has successfully integrated with Epic.")
    assert {gate["key"]: gate["status"] for gate in passed}["epic"] == "pass"
    # Code does not reinterpret even strongly worded prose without a judgment.
    assert {gate["key"]: gate["status"] for gate in normalize_gates([], rubric, corpus)} == {
        "sbe": "unknown", "epic": "unknown", "insurance": "unknown",
    }


def test_typed_gate_fact_resolves_in_code_and_free_text_gate_is_not_cacheable(app):
    from app.decision_processing import normalize_gates
    from app.decision_state import canonical_decision_state, state_is_reusable

    rubric = {"approval_status": "approved", "criteria": [
        {
            "key": "epic", "label": "Epic integration", "gate": True,
            "gate_rule": "Integration verified", "fact_key": "epic_verified",
            "pass_value": True,
        },
        {"key": "fit", "label": "Fit", "weight": 1.0},
    ]}
    attributes = {"epic_verified": {
        "value": False, "source": "document", "evidence": "Integration record: not verified",
    }}
    result = normalize_gates(
        [{"key": "epic", "status": "pass", "evidence": ["Integration record: not verified"]}],
        rubric,
        "Integration record: not verified",
        attributes=attributes,
    )
    assert result[0]["status"] == "fail"
    assert result[0]["basis"] == "Resolved from canonical fact epic_verified."
    typed_state = canonical_decision_state(
        option_key="vendor", attributes=attributes, rubric=rubric,
        gates=rubric["criteria"],
    )
    assert state_is_reusable(typed_state) is True

    prose_gate = {**rubric, "criteria": [
        {"key": "epic", "label": "Epic integration", "gate": True, "gate_rule": "Integration verified"},
        rubric["criteria"][1],
    ]}
    assert state_is_reusable(canonical_decision_state(
        option_key="vendor", attributes=attributes, rubric=prose_gate,
        gates=prose_gate["criteria"],
    )) is False


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
    ready = {"scoring_rubric": {
        "criteria": [{"key": "fit", "weight": 1}],
        "approval_status": "proposed", "presented_at": "2026-10-06T00:00:00Z",
    }}
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

    unseen = agent._execute_mutation_tool(
        "set_scoring_rubric", {"criteria": criteria}, user=test_user,
        user_id=test_user.id, thread_id="rubric-approved", user_message="Score it now",
    )
    assert unseen["rubric"]["approval_status"] == "proposed"
    assert "approved_by_user_at" not in unseen["rubric"]

    shown_session = {}
    agent._apply_rubric_action_to_session(shown_session, [{"result": unseen}])
    assert shown_session["scoring_rubric"]["presented_at"]
    assert agent._guard_mutation_tool(
        "generate_scorecard", user_turn_count=2, mutations_this_turn=0,
        user_message="Score it now", session=shown_session,
    ) is None
    approved = shown_session["scoring_rubric"]
    assert approved["approval_status"] == "approved"

    session = {}
    monkeypatch.setattr(agent, "_execute_mutation_tool", lambda *a, **k: {
        "ok": True, "tool": "set_scoring_rubric",
        "rubric": approved,
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


def test_paraphrases_and_approval_timestamps_have_one_decision_identity(app):
    from app.decision_fingerprint import scoring_fingerprint
    from app.decision_facts import normalize_option_facts
    from app.decision_kits import get_decision_kit
    from app.decision_state import canonical_decision_state

    kit = get_decision_kit("rfp_bid")
    a = normalize_option_facts({
        "bonding_requirement": {
            "value": None, "source": "user",
            "evidence": "Surety has not yet confirmed whether it will bond this project.",
        },
    }, kit=kit)
    b = normalize_option_facts({
        "capacity_draw": {
            "value": None, "source": "user",
            "evidence": "We are waiting for the surety to tell us whether this job is bondable.",
        },
    }, kit=kit)
    rubric_a = {"approval_status": "approved", "approved_by_user_at": "first", "criteria": [
        {"key": "fit", "label": "Fit", "weight": 1.0},
    ]}
    rubric_b = {**rubric_a, "approved_by_user_at": "later"}
    state_a = canonical_decision_state(
        option_key="hospital", attributes=a, rubric=rubric_a, objective="balanced",
        decision_kit="rfp_bid", decision_kit_version=1,
    )
    state_b = canonical_decision_state(
        option_key="hospital", attributes=b, rubric=rubric_b, objective="balanced",
        decision_kit="rfp_bid", decision_kit_version=1,
    )
    assert state_a == state_b
    base = dict(
        option_key="hospital", attributes=a, rubric=rubric_a, objective="balanced",
        decision_kit="rfp_bid", decision_kit_version=1,
    )
    assert scoring_fingerprint(**base, evidence_corpus="Bond approval is pending.") == scoring_fingerprint(
        **{**base, "attributes": b, "rubric": rubric_b},
        evidence_corpus="Waiting for surety confirmation.",
    )
    changed = normalize_option_facts({
        "capacity_draw": {"value": "$5M", "source": "user", "evidence": "Bond is $5M"},
    }, kit=kit)
    assert scoring_fingerprint(**base, evidence_corpus="a") != scoring_fingerprint(
        **{**base, "attributes": changed}, evidence_corpus="b",
    )


def test_same_fingerprint_batch_reuses_judgment_without_model_call(app, monkeypatch):
    from app.routes import strategy

    calls = []
    monkeypatch.setattr(strategy, "_strategy_generate_reply", lambda *a, **k: calls.append(1))
    rubric = {"approval_status": "approved", "criteria": [
        {"key": "fit", "label": "Fit", "weight": 1.0},
    ]}
    cached = {
        "jaspen_score": 64,
        "score_category": "Promising",
        "dimensions": {"fit": {"score": 64, "confidence": "medium"}},
        "gates": [],
    }
    cards, _summary, usage = strategy._generate_batch_scorecards(
        None,
        [{"name": "Workday", "option_key": "workday", "attributes": {
            "cost": {"value": 10, "source": "user", "evidence": "Cost is 10"},
        }}],
        rubric=rubric,
        llm_model="test",
        return_usage=True,
        reuse_lookup=lambda fingerprint, state: cached,
    )
    assert calls == []
    assert cards[0]["jaspen_score"] == 64
    assert cards[0]["reused_stored_result"] is True
    assert usage["total_tokens"] == 0


def test_explicit_assumption_affects_only_declared_criteria(app):
    from app.decision_facts import apply_assumption_confidence_caps, normalize_option_facts

    facts = normalize_option_facts({
        "market_size": {
            "value": 10, "source": "assumed", "evidence": "",
            "basis": "working estimate", "bounds": [5, 15], "affects": ["growth"],
        },
    })
    result = apply_assumption_confidence_caps({"dimensions": {
        "growth": {"score": 80, "confidence": "high"},
        "risk": {"score": 70, "confidence": "high"},
    }}, facts)
    assert result["dimensions"]["growth"]["confidence"] == "assumed"
    assert result["dimensions"]["risk"]["confidence"] == "high"
    assert result["assumption_register"][0]["basis"] == "working estimate"


def test_score_intent_is_structured_and_unseen_rubric_is_not_approved(app):
    from app.routes import ai_agent as agent

    session = {"scoring_rubric": {
        "approval_status": "proposed",
        "criteria": [{"key": "fit", "weight": 1.0}],
    }}
    error = agent._guard_mutation_tool(
        "generate_scorecard", user_turn_count=2, mutations_this_turn=0,
        user_message="Score it now", session=session,
    )
    assert error["code"] == "rubric_approval_required"
    assert session["scoring_intent"] == {"status": "requested", "source": "user"}
    assert session["scoring_rubric"]["approval_status"] == "proposed"


def test_general_and_rfp_use_the_same_state_schema_with_kit_as_overlay(app):
    from app.decision_state import canonical_decision_state

    common = dict(
        option_key="workday",
        attributes={"cost": {"value": 10, "source": "user", "evidence": "Cost is 10"}},
        rubric={"approval_status": "approved", "criteria": [{"key": "fit", "weight": 1}]},
        objective="cost",
    )
    general = canonical_decision_state(**common)
    rfp = canonical_decision_state(**common, decision_kit="rfp_vendor_selection", decision_kit_version=1)
    assert general.keys() == rfp.keys()
    assert {key: value for key, value in general.items() if key != "decision_kit"} == {
        key: value for key, value in rfp.items() if key != "decision_kit"
    }
    assert general["decision_kit"]["key"] is None
    assert rfp["decision_kit"] == {"key": "rfp_vendor_selection", "version": 1}


def test_canonical_judgment_is_reusable_across_sessions_and_org_members(db, test_user):
    from werkzeug.security import generate_password_hash
    from app.models import Organization, User
    from app.scorecards import find_scorecard_by_fingerprint, upsert_scorecard

    org = Organization(name="Decision Org", owner_user_id=test_user.id)
    colleague = User(
        email="colleague@example.com", name="Colleague",
        password_hash=generate_password_hash("ValidPass1", method="pbkdf2:sha256"),
        subscription_plan="free", credits_remaining=300, seat_limit=1, max_seats=1,
    )
    db.session.add_all([org, colleague])
    db.session.flush()
    upsert_scorecard(
        user_id=test_user.id,
        thread_id="source-session",
        organization_id=org.id,
        payload={
            "id": "canonical-source",
            "project_name": "Workday",
            "jaspen_score": 64,
            "decision_fingerprint": "same-state",
            "decision_state_reusable": True,
        },
    )
    db.session.commit()

    found = find_scorecard_by_fingerprint(
        colleague.id, "same-state", organization_id=org.id,
    )
    assert found is not None and found.thread_id == "source-session"
    assert find_scorecard_by_fingerprint(colleague.id, "same-state") is None
