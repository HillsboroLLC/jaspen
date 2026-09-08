"""Regression tests for scorecard claims that must remain deterministic."""


def _strategy():
    from app.routes import strategy
    return strategy


def _reference(excerpt="Signed invoices show six months of costs.", role="support"):
    return {"excerpt": excerpt, "evidence_role": role}


def test_every_public_objective_has_its_own_weight_map():
    strategy = _strategy()
    assert set(strategy._OBJECTIVE_DIMENSION_WEIGHTS) == set(strategy.STRATEGY_OBJECTIVE_OPTIONS)
    assert strategy._OBJECTIVE_DIMENSION_WEIGHTS["cost"]["financial_viability"] == 0.25
    assert strategy._OBJECTIVE_DIMENSION_WEIGHTS["speed"]["execution_readiness"] == 0.28
    assert strategy._OBJECTIVE_DIMENSION_WEIGHTS["cost"] != strategy._OBJECTIVE_DIMENSION_WEIGHTS["balanced"]
    assert all(abs(sum(weights.values()) - 1.0) < 1e-9 for weights in strategy._OBJECTIVE_DIMENSION_WEIGHTS.values())


def test_user_corpus_prevents_the_system_from_citing_its_own_summary():
    strategy = _strategy()
    generated_summary = "Three-year lease at $42k per month."
    user_words = "The landlord's proposal says monthly base rent is $42,000."
    assert strategy._evidence_verification_text(generated_summary, user_words) == user_words
    assert strategy._evidence_verification_text(generated_summary, "") == generated_summary


def test_confidence_is_calibrated_to_affirmative_verified_support():
    strategy = _strategy()
    payload = {"dimensions": {
        "supported": {"confidence": "medium", "evidence_references": [_reference()]},
        "gap_only": {"confidence": "high", "evidence_references": [_reference("I have no data.", "gap")]},
        "unlocated": {"confidence": "medium", "evidence_references": []},
    }}
    strategy._calibrate_confidence_to_verified_evidence(payload)
    assert payload["dimensions"]["supported"]["confidence"] == "medium"
    assert payload["dimensions"]["gap_only"]["confidence"] == "low"
    assert payload["dimensions"]["unlocated"]["confidence"] == "assumed"


def test_unverified_model_numbers_are_removed_but_dimension_judgments_remain():
    strategy = _strategy()
    payload = {
        "dimensions": {"financial_viability": {"score": 70}},
        "financial_impact": {
            "potential_loss": 500000,
            "_numeric": {"potential_loss": 500000},
        },
        "before_after_financials": {
            "before": {"revenue": 10, "_numeric": {"revenue": 10}},
            "after": {"revenue": 15, "_numeric": {"revenue": 15}},
        },
        "top_risks": [{"impact_dollars": 80000, "impact_numeric": 80000, "mitigation_cost": 5000}],
        "decision_framework": {"confidence_level": 80, "downside_scenario": 100, "upside_scenario": 900},
        "recommendations": [{"expected_impact": "$250,000"}],
    }
    strategy._remove_unverified_model_numbers(payload)
    assert payload["dimensions"]["financial_viability"]["score"] == 70
    assert payload["financial_impact"]["potential_loss"] is None
    assert payload["financial_impact"]["_numeric"]["potential_loss"] is None
    assert payload["before_after_financials"]["before"]["revenue"] is None
    assert payload["before_after_financials"]["before"]["_numeric"]["revenue"] is None
    assert payload["top_risks"][0]["impact_dollars"] is None
    assert payload["top_risks"][0]["mitigation_cost"] is None
    assert payload["decision_framework"]["confidence_level"] is None
    assert payload["decision_framework"]["downside_scenario"] is None
    assert payload["recommendations"][0]["expected_impact"] is None


def test_executive_summary_is_derived_from_computed_score_and_coverage():
    strategy = _strategy()
    payload = {
        "name": "Atlanta warehouse lease",
        "dimensions": {
            "financial_viability": {
                "score": 72, "confidence": "medium",
                "evidence_references": [_reference()],
                "what_would_improve": None,
            },
            "execution_readiness": {
                "score": 80, "confidence": "assumed",
                "evidence_references": [],
                "what_would_improve": "complete the staffing study.",
            },
        },
    }
    strategy._recompute_jaspen_score(payload, {"financial_viability": 0.6, "execution_readiness": 0.4})
    summary = strategy._deterministic_executive_summary(payload)
    assert f"scores {payload['jaspen_score']}/100" in summary
    assert f"{payload['evidence_profile']['evidence_backed_pct']}%" in summary
    assert "complete the staffing study" in summary
    assert "not the probability of a successful outcome" in summary


def test_normalization_replaces_stale_model_summary_with_current_arithmetic():
    strategy = _strategy()
    payload = {
        "project_name": "Atlanta warehouse lease",
        "executive_summary": "This decision is guaranteed to succeed because every assumption is proven.",
        "jaspen_score": 91,
        "scoring_weights": {
            "financial_viability": 0.6,
            "execution_readiness": 0.4,
        },
        "dimensions": {
            "financial_viability": {
                "score": 72,
                "confidence": "medium",
                "evidence_references": [_reference()],
            },
            "execution_readiness": {
                "score": 80,
                "confidence": "assumed",
                "evidence_references": [],
                "what_would_improve": "complete the staffing study.",
            },
        },
    }

    normalized = strategy._normalize_scorecard_payload(payload)

    assert "guaranteed to succeed" not in normalized["executive_summary"]
    assert f"scores {normalized['jaspen_score']}/100" in normalized["executive_summary"]
    assert "not the probability of a successful outcome" in normalized["executive_summary"]
    assert normalized["section_provenance"]["executive_summary"] == "deterministic"
