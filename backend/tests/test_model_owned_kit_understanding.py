import pytest


def _judge(kit, confidence, quote):
    return {"kit": kit, "confidence": confidence, "evidence_quote": quote}


@pytest.mark.parametrize(
    "message,kit,quote",
    [
        ("We're responding to these RFPs. We are the bidder.", "rfp_bid", "We are the bidder"),
        ("We received an RFP and need to decide whether to respond.", "rfp_bid", "whether to respond"),
        ("Our committee is evaluating three contractor bids.", "rfp_vendor_selection", "evaluating three contractor bids"),
        ("We received vendor proposals and need to select one.", "rfp_vendor_selection", "select one"),
    ],
)
def test_model_owned_classifier_accepts_grounded_natural_language(app, monkeypatch, message, kit, quote):
    from app.routes import ai_agent

    monkeypatch.setattr(
        ai_agent,
        "_anthropic_json_completion",
        lambda *_args, **_kwargs: (_judge(kit, "high", quote), {}),
    )
    assert ai_agent._classify_decision_kit(message, {"llm_model": "test"}) == _judge(kit, "high", quote)


def test_classifier_rejects_a_quote_not_present_in_the_user_message(app, monkeypatch):
    from app.routes import ai_agent

    monkeypatch.setattr(
        ai_agent,
        "_anthropic_json_completion",
        lambda *_args, **_kwargs: (_judge("rfp_bid", "high", "invented quote"), {}),
    )
    with pytest.raises(ValueError, match="not in the user message"):
        ai_agent._classify_decision_kit("We are the bidder.", {"llm_model": "test"})


def test_low_confidence_rfp_asks_once_then_natural_answer_locks_subtype(app):
    from app.routes import ai_agent

    session = {}
    ambiguous = "The bond is still pending for Bid 3, CDOT. Score all three bids."
    ai_agent._apply_rfp_decision_context(
        session,
        ambiguous,
        judgment=_judge("none", "low", "Bid 3, CDOT"),
    )
    assert ai_agent._rfp_subtype_question_needed(session)

    answer = "We're responding to these RFPs. We are the bidder."
    ai_agent._apply_rfp_decision_context(
        session,
        answer,
        judgment=_judge("rfp_bid", "high", "We are the bidder"),
    )
    assert session["decision_kit"] == "rfp_bid"
    assert session["decision_kit_locked"] is True
    assert not ai_agent._rfp_subtype_question_needed(session)


def test_locked_kit_cannot_silently_flip_on_later_score_request(app):
    from app.routes import ai_agent

    session = {
        "decision_kit": "rfp_bid",
        "decision_kit_version": 1,
        "decision_kit_family": "rfp",
        "decision_kit_locked": True,
        "decision_kit_source": "model_inference",
    }
    ai_agent._apply_rfp_decision_context(
        session,
        "Approved. Score all three bids.",
        judgment=_judge("rfp_vendor_selection", "high", "three bids"),
    )
    assert session["decision_kit"] == "rfp_bid"
    assert session.get("decision_kit_change_pending") is None


def test_manual_and_inferred_activation_reach_the_same_canonical_scoring_identity(app):
    from app.decision_fingerprint import scoring_fingerprint
    from app.routes import ai_agent

    message = "We're responding to these RFPs. We are the bidder."
    judgment = _judge("rfp_bid", "high", "We are the bidder")
    manual, inferred = {}, {}
    ai_agent._apply_rfp_decision_context(manual, message, explicit_selection="rfp", judgment=judgment)
    ai_agent._apply_rfp_decision_context(inferred, message, judgment=judgment)
    facts = {"contract_value": {"value": 42_000_000, "source": "user", "evidence": "contract value is $42M"}}
    rubric = {"criteria": [{"key": "fit", "label": "Fit", "weight": 1.0}]}
    common = dict(option_key="aurora", attributes=facts, rubric=rubric, objective="balanced", evidence_corpus="contract value is $42M")
    manual_fp = scoring_fingerprint(
        **common, decision_kit=manual["decision_kit"], decision_kit_version=manual["decision_kit_version"],
    )
    inferred_fp = scoring_fingerprint(
        **common, decision_kit=inferred["decision_kit"], decision_kit_version=inferred["decision_kit_version"],
    )
    assert manual["decision_kit"] == inferred["decision_kit"] == "rfp_bid"
    assert manual_fp == inferred_fp


def test_explicit_change_on_established_decision_requires_confirmation(app):
    from app.routes import ai_agent

    session = {
        "active_evaluation_scorecard_id": "card-1",
        "decision_kit": "rfp_bid",
        "decision_kit_version": 1,
        "decision_kit_family": "rfp",
        "decision_kit_locked": True,
    }
    message = "Change this Decision Kit to vendor selection."
    ai_agent._apply_rfp_decision_context(
        session,
        message,
        judgment=_judge("rfp_vendor_selection", "high", "vendor selection"),
    )
    assert session["decision_kit"] == "rfp_bid"
    assert session["decision_kit_change_pending"]["target"] == "rfp_vendor_selection"


def test_unknown_kit_fields_are_partitioned_into_auditable_notes(app):
    from app.routes import ai_agent

    rejected = [
        {"field": "local_partner_history", "value": "Strong", "source": "user", "evidence": "local partner history is strong", "reason": "Unknown decision field: local_partner_history"},
        {"field": "margin_pct", "value": "not a number", "source": "user", "evidence": "margin is unclear", "reason": "Invalid value for margin_pct"},
    ]
    notes, invalid = ai_agent._partition_unknown_fact_notes(rejected, "Our local partner history is strong; margin is unclear.")
    assert notes == [{
        "label": "local_partner_history", "value": "Strong", "source": "user",
        "evidence": "local partner history is strong", "reason": "not_in_active_decision_kit",
    }]
    assert invalid == [rejected[1]]


def test_tradeoff_tolerates_null_display_overrides(app, db, test_user, monkeypatch):
    from app.routes import ai_agent
    from app.routes.sessions import save_user_sessions

    thread_id = "null-display-overrides"
    save_user_sessions(test_user.id, {thread_id: {"session_id": thread_id, "user_id": test_user.id}})
    monkeypatch.setattr(ai_agent, "_collect_session_scorecards", lambda *_args, **_kwargs: [
        {"id": "a", "name": "A", "jaspen_score": 60, "display_overrides": None},
        {"id": "b", "name": "B", "jaspen_score": 50, "display_overrides": {}},
    ])
    result = ai_agent._execute_mutation_tool(
        "generate_tradeoff_comparison", {}, user=test_user, user_id=test_user.id, thread_id=thread_id,
    )
    assert result["ok"] is True
