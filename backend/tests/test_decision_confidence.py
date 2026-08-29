"""Decision Confidence and Assumption Exposure arithmetic.

These are the numbers the product publishes as statements about a customer's
decision, so the tests are written against the claims rather than the
implementation: what the evidence split means, what makes an assumption
material, and the boundary the reversal claim must not cross.
"""

from app.decision_confidence import (
    CONFIDENCE_CAPS,
    SEVERITY_MATERIAL,
    SEVERITY_MINOR,
    SEVERITY_REVERSING,
    criterion_entries,
    decision_exposure,
    evidence_profile,
    evidence_ratio,
    exposure_claims,
)

# app.routes.strategy binds the rate limiter at import time, so it cannot be
# imported before create_app has run. conftest's autouse fixtures build the app
# for every test, which makes an import inside the test body safe and matches
# the convention in the rest of this suite.
def _strategy():
    from app.routes import strategy
    return strategy


def _dim(score, confidence, *, improve=None, label=None):
    return {
        "score": score,
        "confidence": confidence,
        "what_would_improve": improve,
        "label": label,
    }


# --- the evidence split ------------------------------------------------------

def test_evidence_ratio_is_weighted_not_averaged():
    """A heavy assumed criterion must outweigh several light evidenced ones.

    This is the whole reason the figure is publishable. An unweighted mean
    would report the distribution of labels, not the state of the decision.
    """
    dimensions = {
        "money": _dim(80, "assumed"),
        "a": _dim(80, "high"),
        "b": _dim(80, "high"),
        "c": _dim(80, "high"),
    }
    weights = {"money": 0.70, "a": 0.10, "b": 0.10, "c": 0.10}

    entries = criterion_entries(dimensions, weights)
    # 30% of the weight is high-confidence, contributing fully. The 70%
    # assumed criterion contributes nothing to the evidenced share.
    assert evidence_ratio(entries) == 30

    unweighted = {"money": 0.25, "a": 0.25, "b": 0.25, "c": 0.25}
    assert evidence_ratio(criterion_entries(dimensions, unweighted)) == 75


def test_split_always_sums_to_one_hundred():
    profile = evidence_profile(
        {"a": _dim(70, "medium"), "b": _dim(60, "low")},
        {"a": 0.5, "b": 0.5},
    )
    assert profile["evidence_backed_pct"] + profile["assumption_dependent_pct"] == 100


def test_unweighted_criteria_are_skipped_not_assumed_equal():
    """A rubric that omits a dimension omitted it deliberately."""
    entries = criterion_entries(
        {"a": _dim(90, "high"), "ignored": _dim(10, "assumed")},
        {"a": 1.0},
    )
    assert [e["key"] for e in entries] == ["a"]


def test_profile_is_none_without_usable_dimensions():
    assert evidence_profile({}, {"a": 1.0}) is None
    assert evidence_profile({"a": _dim(50, "high")}, {}) is None


# --- raw score preservation --------------------------------------------------

def test_recompute_preserves_the_pre_cap_judgment():
    payload = {"dimensions": {"fin": _dim(80, "assumed")}}
    _strategy()._recompute_jaspen_score(payload, {"fin": 1.0})

    dim = payload["dimensions"]["fin"]
    assert dim["raw_score"] == 80, "the judgment must survive the cap"
    assert dim["score"] == CONFIDENCE_CAPS["assumed"] == 45
    assert payload["jaspen_score"] == 45


def test_recompute_is_idempotent_and_does_not_eat_its_own_cap():
    """Running twice must not record the cap as though it were a judgment.

    This function runs more than once over the same payload. Reading "score"
    on the second pass would set raw_score to 45, collapsing every exposure
    figure derived from it to zero while looking perfectly healthy.
    """
    payload = {"dimensions": {"fin": _dim(80, "assumed")}}
    _strategy()._recompute_jaspen_score(payload, {"fin": 1.0})
    first = dict(payload["dimensions"]["fin"])

    _strategy()._recompute_jaspen_score(payload, {"fin": 1.0})
    second = payload["dimensions"]["fin"]

    assert second["raw_score"] == first["raw_score"] == 80
    assert second["score"] == first["score"] == 45
    assert payload["evidence_profile"]["criteria"][0]["swing"] > 0


def test_recompute_persists_the_weights_that_produced_the_score():
    payload = {"dimensions": {"a": _dim(70, "high"), "b": _dim(70, "high")}}
    _strategy()._recompute_jaspen_score(payload, {"a": 0.6, "b": 0.4, "absent": 0.9})

    # Only weights whose dimension actually exists are persisted, so a
    # downstream reader cannot normalise against a criterion that was
    # never scored.
    assert payload["scoring_weights"] == {"a": 0.6, "b": 0.4}


# --- swing -------------------------------------------------------------------

def test_swing_is_expressed_in_final_score_points():
    """Swing must be comparable against the gap between two options."""
    entries = criterion_entries(
        {"fin": _dim(80, "assumed"), "ops": _dim(90, "high")},
        {"fin": 0.5, "ops": 0.5},
    )
    fin = next(e for e in entries if e["key"] == "fin")
    # Judged 80, capped at 45, carrying half the decision: 0.5 * 35 = 17.5
    assert fin["swing"] == 17.5


def test_evidenced_criteria_have_no_swing():
    entries = criterion_entries({"ops": _dim(90, "high")}, {"ops": 1.0})
    assert entries[0]["swing"] == 0
    assert entries[0]["capped"] is False


def test_missing_raw_score_yields_zero_swing_not_a_wrong_one():
    """Scorecards written before raw_score existed must degrade honestly."""
    legacy = {"fin": {"score": 45, "confidence": "assumed"}}
    entries = criterion_entries(legacy, {"fin": 1.0})
    assert entries[0]["swing"] == 0


def test_register_is_ordered_by_power_to_change_the_answer():
    profile = evidence_profile(
        {
            "small": _dim(90, "assumed"),
            "big": _dim(95, "assumed"),
            "solid": _dim(88, "high"),
        },
        {"small": 0.1, "big": 0.6, "solid": 0.3},
    )
    assert [e["key"] for e in profile["criteria"]] == ["big", "small", "solid"]


# --- severity ----------------------------------------------------------------

def test_material_when_the_swing_crosses_a_score_band():
    # fin is judged 90 but assumed, so it contributes 45. With ops at 60 the
    # option scores 52, which is Fair. Resolving fin adds 22.5 points and
    # carries it to 74.5, which is Good. The decision gets described
    # differently in the room, so the assumption is material.
    profile = evidence_profile(
        {"fin": _dim(90, "assumed"), "ops": _dim(60, "medium")},
        {"fin": 0.5, "ops": 0.5},
    )
    assert profile["score"] == 52
    fin = next(e for e in profile["criteria"] if e["key"] == "fin")
    assert fin["swing"] == 22.5
    assert fin["severity"] == SEVERITY_MATERIAL


def test_minor_when_the_swing_changes_nothing_anyone_would_describe():
    profile = evidence_profile(
        {"tiny": _dim(50, "assumed"), "ops": _dim(95, "high")},
        {"tiny": 0.02, "ops": 0.98},
    )
    tiny = next(e for e in profile["criteria"] if e["key"] == "tiny")
    assert tiny["severity"] == SEVERITY_MINOR


def test_reversal_requires_a_peer_to_overtake():
    """Without a leader to pass, reversal is not a claim we can make."""
    dimensions = {"fin": _dim(100, "assumed"), "ops": _dim(60, "high")}
    weights = {"fin": 0.5, "ops": 0.5}

    alone = evidence_profile(dimensions, weights)
    assert all(e["severity"] != SEVERITY_REVERSING for e in alone["criteria"])

    trailing = evidence_profile(dimensions, weights, leader_score=60)
    assert any(e["severity"] == SEVERITY_REVERSING for e in trailing["criteria"])


def test_the_leader_cannot_reverse_itself():
    """Caps only lower a score, so gaining points never unseats the leader.

    Guards the scope limit at the top of decision_confidence: this module
    models upside only, and must never imply it evaluated the downside.
    """
    profile = evidence_profile(
        {"fin": _dim(100, "assumed")},
        {"fin": 1.0},
        score=90,
        leader_score=40,
    )
    assert all(e["severity"] != SEVERITY_REVERSING for e in profile["criteria"])


# --- resolvability -----------------------------------------------------------

def test_resolvable_requires_a_named_next_step():
    profile = evidence_profile(
        {
            "actionable": _dim(80, "assumed", improve="Upload the signed term sheet"),
            "stuck": _dim(80, "assumed"),
        },
        {"actionable": 0.5, "stuck": 0.5},
    )
    by_key = {e["key"]: e for e in profile["criteria"]}
    assert by_key["actionable"]["resolvable"] is True
    assert by_key["actionable"]["resolution"] == "Upload the signed term sheet"
    assert by_key["stuck"]["resolvable"] is False


def test_evidenced_criteria_are_never_listed_as_resolvable():
    """Nothing to resolve on a criterion that already has strong evidence."""
    profile = evidence_profile(
        {"ops": _dim(90, "high", improve="Refresh the capacity model")},
        {"ops": 1.0},
    )
    assert profile["criteria"][0]["resolvable"] is False


# --- claims ------------------------------------------------------------------

def test_claims_are_absent_when_the_arithmetic_does_not_support_them():
    profile = evidence_profile({"ops": _dim(90, "high")}, {"ops": 1.0})
    assert exposure_claims(profile) == []


def test_claims_are_singular_and_plural_correctly():
    profile = evidence_profile(
        {"fin": _dim(90, "assumed", improve="Attach the model"), "ops": _dim(60, "medium")},
        {"fin": 0.5, "ops": 0.5},
    )
    texts = [c["text"] for c in exposure_claims(profile)]
    assert "1 assumption could materially change the score" in texts
    assert "1 gap can be resolved before you commit" in texts


# --- cross-option exposure ---------------------------------------------------

def test_decision_exposure_names_the_challenger_and_its_assumption():
    weights = {"fin": 0.5, "ops": 0.5}
    cards = [
        {
            "project_name": "Option A",
            "jaspen_score": 80,
            "dimensions": {"fin": _dim(80, "high"), "ops": _dim(80, "high")},
        },
        {
            "project_name": "Option B",
            "jaspen_score": 72,
            "dimensions": {
                "fin": _dim(100, "assumed", improve="Attach the pricing model"),
                "ops": _dim(99, "high"),
            },
        },
    ]

    result = decision_exposure(cards, weights)
    assert result["leader"]["name"] == "Option A"
    assert result["could_change_leader"] is True
    challenger = result["challengers"][0]
    assert challenger["name"] == "Option B"
    assert challenger["gap"] == 8
    assert challenger["assumptions"][0]["resolution"] == "Attach the pricing model"


def test_decision_exposure_reports_no_challenger_when_gaps_are_unbridgeable():
    weights = {"fin": 1.0}
    cards = [
        {"project_name": "A", "jaspen_score": 95, "dimensions": {"fin": _dim(95, "high")}},
        {"project_name": "B", "jaspen_score": 45, "dimensions": {"fin": _dim(50, "assumed")}},
    ]
    result = decision_exposure(cards, weights)
    assert result["could_change_leader"] is False
    assert result["challengers"] == []


def test_decision_exposure_is_none_without_cards():
    assert decision_exposure([], {"a": 1.0}) is None
    assert decision_exposure(None, {"a": 1.0}) is None


# --- data_confidence ---------------------------------------------------------

def test_conversation_length_no_longer_raises_confidence():
    """Talking more is not evidence.

    The removed grounding bonus added up to +8 points for a longer
    conversation, which let reported confidence rise with no new evidence
    behind it. That is the failure the caps exist to prevent, so it cannot
    live inside the number that reports on them.
    """
    dimensions = {"a": _dim(70, "medium"), "b": _dim(70, "medium")}
    assert _strategy()._data_confidence_from_dimensions(dimensions) == 70


def test_data_confidence_is_weighted_when_weights_are_available():
    dimensions = {"heavy": _dim(80, "assumed"), "light": _dim(80, "high")}
    weighted = _strategy()._data_confidence_from_dimensions(dimensions, {"heavy": 0.9, "light": 0.1})
    unweighted = _strategy()._data_confidence_from_dimensions(dimensions)

    # assumed=30, high=92. Weighted 0.9/0.1 sits near 36; the mean sits at 61.
    assert weighted == 36
    assert unweighted == 61
    assert weighted < unweighted


def test_data_confidence_falls_back_to_the_mean_without_weights():
    dimensions = {"a": _dim(70, "high"), "b": _dim(70, "assumed")}
    assert _strategy()._data_confidence_from_dimensions(dimensions, {}) == 61


def test_data_confidence_is_none_without_readable_dimensions():
    assert _strategy()._data_confidence_from_dimensions({}) is None
    assert _strategy()._data_confidence_from_dimensions({"a": {"score": 50}}) is None
