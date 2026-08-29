"""The first-run Confidence Check.

The load-bearing tests here are the negative ones. This check runs before any
scoring exists, so its numbers measure context coverage, not evidence. The
suite exists mainly to stop a later change from quietly relabelling one as the
other.
"""

from app.confidence_check import (
    ASSUMED_CAP,
    EVIDENCE_CHECKS,
    build_confidence_check,
    check_claims,
    context_gaps,
    evidence_baseline,
)
from app.decision_confidence import CONFIDENCE_CAPS
from app.intake_readiness import _compute_readiness


def _readiness(text):
    return _compute_readiness([{"role": "user", "content": text}])


THIN = "I think we should probably expand into a new market next year."

# Says "finance report" rather than naming NetSuite on purpose.
# DATA_SOURCE_TERMS in intake_readiness is a generic list (dashboard, crm, erp,
# finance, system, report, spreadsheet) and does not recognise named systems,
# including the connectors Jaspen itself integrates with. Widening it would
# change what the shared homepage engine recognises, which is out of scope for
# this branch. Recorded as an input to the Option B decision.
GROUNDED = (
    "We want to cut fulfilment cost per order from $14.20 to $11.00 over the next "
    "two quarters. The baseline is in our finance report. The constraint is dock "
    "capacity at the Reno site, and the domain expert says the bottleneck is "
    "inbound scheduling. We would sequence the dock changes first, then "
    "replicate to Sparks."
)


# --- the distinction this module exists to protect ---------------------------

def test_the_check_never_reports_an_evidence_backed_percentage():
    """Context coverage is not Decision Confidence. They measure different things.

    Nothing has been scored at first run, so there are no graded criteria and
    no weights to grade them against. Publishing this figure as an
    evidence-backed percentage would be the exact unfounded number the product
    exists to surface.
    """
    check = build_confidence_check(_readiness(THIN))

    assert "evidence_backed_pct" not in check
    assert "assumption_dependent_pct" not in check
    assert check["scored"] is False
    assert "context_coverage_pct" in check
    assert "not an evidence-backed percentage" in check["measures"]


def test_no_claim_uses_evidence_backed_language():
    check = build_confidence_check(_readiness(GROUNDED))
    for claim in check["claims"]:
        assert "evidence-backed" not in claim["text"].lower()


# --- coverage ----------------------------------------------------------------

def test_coverage_rises_with_context_supplied():
    thin = build_confidence_check(_readiness(THIN))
    grounded = build_confidence_check(_readiness(GROUNDED))
    assert grounded["context_coverage_pct"] > thin["context_coverage_pct"]


def test_thin_input_still_produces_a_usable_finding():
    """The first run must be worth reading precisely when evidence is thin.

    This is the cold-start case: someone arrives with a sentence. The check
    has to return something specific rather than a refusal.
    """
    check = build_confidence_check(_readiness(THIN))
    assert check is not None
    assert check["gaps"], "a thin first message must surface named gaps"
    assert check["claims"], "a thin first message must still produce claims"


def test_check_is_none_without_a_readable_payload():
    assert build_confidence_check(None) is None
    assert build_confidence_check({}) is None
    assert build_confidence_check({"categories": []}) is None


# --- gap ranking -------------------------------------------------------------

def test_required_gates_rank_above_heavier_optional_gaps():
    """A blocking gate misdirects effort if a heavier optional gap sits above it."""
    readiness = {
        "categories": [
            {"key": "optional_heavy", "label": "Heavy", "weight": 0.90, "completed": False},
            {"key": "goal_definition", "label": "Goal", "weight": 0.20,
             "completed": False, "required": True},
        ],
    }
    gaps = context_gaps(readiness)
    assert [g["key"] for g in gaps] == ["goal_definition", "optional_heavy"]


def test_completed_categories_are_not_listed_as_gaps():
    readiness = {
        "categories": [
            {"key": "done", "label": "Done", "weight": 0.5, "completed": True},
            {"key": "open", "label": "Open", "weight": 0.5, "completed": False},
        ],
    }
    assert [g["key"] for g in context_gaps(readiness)] == ["open"]


def test_gaps_are_ranked_by_weight_within_the_same_tier():
    readiness = {
        "categories": [
            {"key": "light", "label": "Light", "weight": 0.10, "completed": False},
            {"key": "heavy", "label": "Heavy", "weight": 0.40, "completed": False},
        ],
    }
    assert [g["key"] for g in context_gaps(readiness)] == ["heavy", "light"]


# --- evidence baseline -------------------------------------------------------

def test_evidence_baseline_separates_what_is_present_from_what_is_missing():
    baseline = evidence_baseline(_readiness(GROUNDED))
    assert baseline is not None
    labels = {p["key"] for p in baseline["present"]}
    assert "has_number" in labels
    assert len(baseline["present"]) + len(baseline["missing"]) == len(EVIDENCE_CHECKS)


def test_thin_input_is_reported_as_ungrounded():
    baseline = evidence_baseline(_readiness(THIN))
    assert baseline["ungrounded"] is True
    assert baseline["assumed_cap"] == ASSUMED_CAP == CONFIDENCE_CAPS["assumed"] == 45


def test_evidence_baseline_is_none_when_the_spec_does_not_measure_it():
    """A profile that never measured evidence has not measured it."""
    assert evidence_baseline({"categories": []}) is None
    assert evidence_baseline(None) is None


# --- claims ------------------------------------------------------------------

def test_the_cap_consequence_claim_describes_the_mechanism_not_a_prediction():
    """The grade is a model judgment made after scoring, which this cannot make.

    The claim must describe what Jaspen does with ungrounded input, never
    assert what a criterion will be graded.
    """
    check = build_confidence_check(_readiness(THIN))
    cap_claims = [c for c in check["claims"] if c["kind"] == "cap_consequence"]
    assert len(cap_claims) == 1

    text = cap_claims[0]["text"]
    assert str(ASSUMED_CAP) in text
    assert "is graded assumed" in text
    assert "will be graded" not in text


def test_the_cap_claim_is_absent_once_a_source_is_supplied():
    check = build_confidence_check(_readiness(GROUNDED))
    kinds = {c["kind"] for c in check["claims"]}
    assert "cap_consequence" not in kinds


def test_blocking_claim_is_singular_and_plural_correctly():
    one = check_claims(40, [{"label": "Goal Definition", "required": True}], None)
    assert any("One thing has to be in place" in c["text"] for c in one)

    two = check_claims(
        40,
        [{"label": "Goal Definition", "required": True},
         {"label": "Current Evidence", "required": True}],
        None,
    )
    assert any("Two things have to be in place" in c["text"] for c in two)


def test_coverage_claim_is_always_present_but_never_leads():
    """A cold start legitimately scores near zero.

    Opening on "Jaspen has 0% of the context it needs" rebuilds the wall this
    branch exists to remove, so coverage closes the finding rather than
    introducing it.
    """
    claims = check_claims(0, [], None)
    assert claims[-1]["kind"] == "coverage"
    assert "0% of the context" in claims[-1]["text"]


def test_a_cold_start_opens_on_something_jaspen_found():
    readiness = _readiness(THIN)
    check = build_confidence_check(readiness)
    assert check["context_coverage_pct"] == 0
    assert check["claims"][0]["kind"] != "coverage"


# --- the Option A guarantee --------------------------------------------------

def test_building_a_check_does_not_mutate_the_readiness_payload():
    """This branch changes output framing only, never the shared engine."""
    readiness = _readiness(GROUNDED)
    import copy

    before = copy.deepcopy(readiness)
    build_confidence_check(readiness)
    assert readiness == before
