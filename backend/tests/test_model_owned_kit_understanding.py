import pytest


def _judge(kit, confidence, quote):
    return {
        "kit": kit,
        "confidence": confidence,
        "evidence_quote": quote,
    }


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


def test_classifier_receives_no_keyword_hints(app, monkeypatch):
    from app.routes import ai_agent

    captured = {}

    def fake_completion(system_prompt, user_payload, **_kwargs):
        captured["system_prompt"] = system_prompt
        captured["payload"] = user_payload
        return _judge("none", "high", ""), {}

    monkeypatch.setattr(ai_agent, "_anthropic_json_completion", fake_completion)
    ai_agent._classify_decision_kit("Help me think this through.", {"llm_model": "test"})

    assert "advisory_hints" not in captured["payload"]
    assert "regex hints" not in captured["system_prompt"]


def test_low_confidence_rfp_is_suggested_and_never_auto_applied(app):
    from app.routes import ai_agent

    session = {}
    ambiguous = "The bond is still pending for Bid 3, CDOT. Score all three bids."
    ai_agent._apply_rfp_decision_context(
        session,
        ambiguous,
        judgment=_judge("none", "low", "Bid 3, CDOT"),
    )
    assert session.get("decision_kit") is None
    assert session["decision_kit_suggestion"]["kit"] == "rfp"

    answer = "We're responding to these RFPs. We are the bidder."
    ai_agent._apply_rfp_decision_context(session, answer, judgment=_judge("rfp_bid", "high", "We are the bidder"))
    assert session.get("decision_kit") is None
    assert session["decision_kit_suggestion"]["kit"] == "rfp_bid"
    ai_agent._apply_rfp_decision_context(session, answer, explicit_selection="rfp_bid")
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


@pytest.mark.parametrize("session", [
    {"active_evaluation_scorecard_id": "card-1"},
    {"decision_kit": "rfp_bid", "decision_kit_locked": True},
])
def test_established_or_locked_session_skips_classifier(app, monkeypatch, session):
    from app.routes import ai_agent

    def unexpected_call(*_args, **_kwargs):
        raise AssertionError("classifier must not run")

    monkeypatch.setattr(ai_agent, "_classify_decision_kit", unexpected_call)
    assert ai_agent._decision_kit_judgment_for_turn(
        session, "Can we switch kits?", {"llm_model": "test"},
    ) is None


def test_suggested_kit_reaches_manual_canonical_identity_only_after_click(app):
    from app.decision_fingerprint import scoring_fingerprint
    from app.routes import ai_agent

    message = "We're responding to these RFPs. We are the bidder."
    judgment = _judge("rfp_bid", "high", "We are the bidder")
    manual, inferred = {}, {}
    ai_agent._apply_rfp_decision_context(manual, message, explicit_selection="rfp", judgment=judgment)
    ai_agent._apply_rfp_decision_context(inferred, message, judgment=judgment)
    assert inferred.get("decision_kit") is None
    assert inferred["decision_kit_suggestion"]["kit"] == "rfp_bid"
    ai_agent._apply_rfp_decision_context(inferred, message, explicit_selection="rfp_bid")
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
    result = ai_agent._execute_decision_kit_change_tool(
        "request_decision_kit_change",
        {"target": "rfp_vendor_selection", "user_request_quote": "Change this Decision Kit"},
        session=session,
        user_message=message,
    )
    assert result["confirmation_required"] is True
    assert session["decision_kit"] == "rfp_bid"
    assert session["decision_kit_change_pending"]["target"] == "rfp_vendor_selection"


def test_kit_change_and_confirmation_require_verified_quotes(app):
    from app.routes import ai_agent

    request = "Can we switch this to vendor selection?"
    session = {
        "active_evaluation_scorecard_id": "card-1",
        "decision_kit": "rfp_bid",
        "decision_kit_version": 1,
        "decision_kit_family": "rfp",
        "decision_kit_locked": True,
    }
    requested = ai_agent._execute_decision_kit_change_tool(
        "request_decision_kit_change",
        {"target": "rfp_vendor_selection", "user_request_quote": request},
        session=session,
        user_message=request,
    )
    assert requested["ok"] is True
    assert session["decision_kit"] == "rfp_bid"
    assert session["decision_kit_change_pending"]["target"] == "rfp_vendor_selection"

    confirmation = "Yes, make that change."
    confirmed = ai_agent._execute_decision_kit_change_tool(
        "confirm_decision_kit_change",
        {"user_request_quote": confirmation},
        session=session,
        user_message=confirmation,
    )
    assert confirmed["ok"] is True
    assert session["decision_kit"] == "rfp_vendor_selection"
    assert session["decision_kit_source"] == "user_confirmed"
    assert session.get("decision_kit_change_pending") is None


def test_verified_change_quote_applies_immediately_to_unlocked_kit(app):
    from app.routes import ai_agent

    message = "Can we switch this to vendor selection?"
    session = {
        "decision_kit": "rfp_bid",
        "decision_kit_version": 1,
        "decision_kit_family": "rfp",
        "decision_kit_locked": False,
    }

    result = ai_agent._execute_decision_kit_change_tool(
        "request_decision_kit_change",
        {"target": "rfp_vendor_selection", "user_request_quote": message},
        session=session,
        user_message=message,
    )

    assert result["ok"] is True
    assert session["decision_kit"] == "rfp_vendor_selection"
    assert session["decision_kit_source"] == "user"
    assert session["decision_kit_remap_required"] is True
    assert session.get("decision_kit_change_pending") is None


def test_cancel_with_verified_quote_drops_pending_change(app):
    from app.routes import ai_agent

    session = {
        "decision_kit": "rfp_bid",
        "decision_kit_change_pending": {"from": "rfp_bid", "target": "rfp_vendor_selection"},
    }
    message = "Keep the current kit after all."
    result = ai_agent._execute_decision_kit_change_tool(
        "cancel_decision_kit_change",
        {"user_request_quote": message},
        session=session,
        user_message=message,
    )

    assert result["ok"] is True
    assert session["decision_kit"] == "rfp_bid"
    assert session.get("decision_kit_change_pending") is None


@pytest.mark.parametrize("tool_name,tool_input", [
    ("request_decision_kit_change", {"target": "rfp_vendor_selection", "user_request_quote": "invented request"}),
    ("confirm_decision_kit_change", {"user_request_quote": "invented confirmation"}),
    ("cancel_decision_kit_change", {"user_request_quote": "invented cancellation"}),
])
def test_unverified_kit_tool_quotes_change_nothing(app, tool_name, tool_input):
    from app.routes import ai_agent

    pending = {"from": "rfp_bid", "target": "rfp_vendor_selection"}
    session = {
        "active_evaluation_scorecard_id": "card-1",
        "decision_kit": "rfp_bid",
        "decision_kit_locked": True,
        "decision_kit_change_pending": pending.copy(),
    }
    result = ai_agent._execute_decision_kit_change_tool(
        tool_name,
        tool_input,
        session=session,
        user_message="Do something else.",
    )

    assert result["ok"] is False
    assert session["decision_kit"] == "rfp_bid"
    assert session["decision_kit_change_pending"] == pending


def test_unknown_kit_fields_are_partitioned_into_auditable_notes(app):
    from app.routes import ai_agent

    rejected = [
        {"field": "local_partner_history", "value": "Strong", "source": "user", "evidence": "local partner history is strong", "reason": "Unknown decision field: local_partner_history"},
        {"field": "margin_pct", "value": "not a number", "source": "user", "evidence": "margin is unclear", "reason": "Invalid value for margin_pct"},
    ]
    notes, invalid = ai_agent._partition_unknown_fact_notes(rejected, "Our local partner history is strong; margin is unclear.")
    assert notes == [{
        "label": "local_partner_history", "value": "Strong", "source": "user",
        "attribution": "user-stated", "evidence": "local partner history is strong",
        "affects": [], "reason": "not_in_active_decision_kit",
    }, {
        "label": "margin_pct", "value": "margin is unclear", "source": "user",
        "attribution": "user-stated", "evidence": "margin is unclear",
        "affects": [], "reason": "not_stored_as_canonical_fact",
    }]
    assert invalid == []


def test_rfp_similar_jobs_maps_to_past_project_experience(app):
    from app.decision_facts import normalize_fact_entry
    from app.decision_kits import get_decision_kit

    key, fact = normalize_fact_entry(
        "similar_project_experience",
        {
            "value": "Three similar water main jobs in the last two years",
            "source": "user",
            "evidence": "We have done three similar water main jobs in the last two years.",
        },
        kit=get_decision_kit("rfp_bid"),
    )

    assert key == "past_project_experience"
    assert fact["source"] == "user"


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
