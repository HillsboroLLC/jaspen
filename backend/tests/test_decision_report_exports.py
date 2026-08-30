"""The Decision Confidence report as it leaves the building.

An export is the copy a customer forwards, so the tests here are mostly about
what must NOT travel: unverified quotes dressed as evidence, edited wording
passed off as Jaspen's finding, and the provenance caveat going missing once
the report is out of the workspace.
"""

from app.decision_report import build_report, evidence_source_label
from app.decision_report_email import render_report_html, render_report_text


def _criterion(**overrides):
    entry = {
        "key": "fin",
        "label": "Financial viability",
        "weight": 0.25,
        "confidence": "assumed",
        "score": 45,
        "raw_score": 95,
        "swing": 12.5,
        "severity": "material",
        "resolution": "Connect NetSuite or upload the cost model",
        "rationale": "The saving was stated as a target with no model behind it.",
        "source": "assumed",
        "evidence_references": [],
    }
    entry.update(overrides)
    return entry


def _scorecard(criteria=None, **overrides):
    card = {
        "project_name": "Add a second weekend shift",
        "jaspen_score": 66,
        "score_category": "Good",
        "scoring_weights": {"fin": 0.25, "ops": 0.75},
        "evidence_profile": {
            "evidence_backed_pct": 55,
            "assumption_dependent_pct": 45,
            "criteria": criteria if criteria is not None else [_criterion()],
            "counts": {"reversing": 0, "material": 1, "resolvable": 1},
            "claims": [{"kind": "material", "text": "1 assumption could materially change the score"}],
        },
    }
    card.update(overrides)
    return card


# --- what must not travel ----------------------------------------------------

def test_the_provenance_caveat_leaves_with_the_report():
    """Out of the workspace, the caveat is the only thing stopping the
    assessment being read as a citation by someone who never saw the app."""
    report = build_report(_scorecard())
    assert "audit trail" in report["provenance_note"]
    assert "audit trail" in render_report_html(report)
    assert "audit trail" in render_report_text(report)


def test_edited_wording_is_marked_in_the_email():
    """A narrative a person rewrote must not leave looking like the system's
    own finding."""
    report = build_report(_scorecard([_criterion(_edited=True, rationale="Ops confirmed verbally.")]))
    assert report["criteria"][0]["edited"] is True
    assert "Edited" in render_report_html(report)


def test_evidence_and_assessment_stay_separately_labelled():
    report = build_report(_scorecard([_criterion(
        evidence_references=[{
            "kind": "conversation", "excerpt": "roughly $40,000 a month",
            "locator": {"message_index": 0, "start": 5, "end": 28},
        }],
    )]))
    html = render_report_html(report)
    assert "Evidence used" in html
    assert "Jaspen&#x27;s assessment" in html
    # The excerpt is quoted; the assessment is not, because one was verified
    # against the input and the other is reasoning about it.
    assert "roughly $40,000 a month" in html


def test_raw_locators_never_reach_a_reader():
    report = build_report(_scorecard([_criterion(
        evidence_references=[{
            "kind": "conversation", "excerpt": "roughly $40,000 a month",
            "locator": {"message_index": 0, "start": 89, "end": 140},
        }],
    )]))
    html = render_report_html(report)
    assert "From your input" in html
    assert "message_index" not in html
    assert "89" not in html


# --- source labels -----------------------------------------------------------

def test_connector_evidence_says_when_it_was_retrieved():
    """A connector value can change after the decision, so when it was true is
    part of the evidence rather than a footnote."""
    label = evidence_source_label({
        "kind": "connector",
        "locator": {"system": "netsuite", "field": "monthly_penalty",
                    "retrieved_at": "2026-08-29T10:00:00"},
    })
    assert label == "NETSUITE · monthly_penalty · retrieved 2026-08-29"


def test_attachment_evidence_names_the_file_and_the_place_in_it():
    label = evidence_source_label({
        "kind": "attachment",
        "locator": {"filename": "Cost Model.xlsx",
                    "location": {"sheet": "Assumptions", "cell": "F18"}},
    })
    assert label == "Cost Model.xlsx · Assumptions · F18"


# --- degradation -------------------------------------------------------------

def test_a_scorecard_without_a_report_renders_nothing_rather_than_a_shell():
    """Cards scored before the report existed must not produce an empty
    Decision Confidence section that looks like a failure."""
    assert build_report({"project_name": "Legacy", "jaspen_score": 70}) is None
    assert render_report_html(None) == ""
    assert render_report_text(None) == ""


def test_standing_appears_only_when_peers_were_supplied():
    """No single scorecard can establish where it stands."""
    alone = build_report(_scorecard())
    assert "standing" not in (alone["summary"] or {})


# --- the deck is a different shape -------------------------------------------

def test_the_deck_carries_only_what_could_change_the_answer():
    """A deck listing every criterion is the email, and nobody reads the email
    from a projector."""
    report = build_report(_scorecard([
        _criterion(),
        _criterion(key="ops", label="Execution readiness", severity="none",
                   swing=0, confidence="high", resolution=None),
        _criterion(key="mkt", label="Market opportunity", severity="other",
                   swing=0.9, confidence="medium", resolution=None),
    ]))
    assert [c["label"] for c in report["criteria"]] == [
        "Financial viability", "Execution readiness", "Market opportunity",
    ]
    # Only the material one earns a slide.
    assert [c["label"] for c in report["material"]] == ["Financial viability"]


def test_the_email_carries_every_criterion():
    report = build_report(_scorecard([
        _criterion(),
        _criterion(key="ops", label="Execution readiness", severity="none",
                   swing=0, confidence="high", resolution=None),
    ]))
    html = render_report_html(report)
    assert "Financial viability" in html
    assert "Execution readiness" in html


# --- the improvement action travels ------------------------------------------

def test_the_action_reaches_the_email_even_when_scoring_named_none():
    """The point of the guidance is forwarding the report to whoever can close
    the gap. An export that states the exposure and omits the ask cannot do it."""
    report = build_report(_scorecard([_criterion(resolution=None, confidence="assumed")]))
    assert report["criteria"][0]["evidence_needed"]
    html = render_report_html(report)
    assert "How to improve this" in html
    assert "Nothing verifiable supports this yet" in html
    assert "How to improve this" in render_report_text(report)


def test_scoring_s_own_suggestion_wins_over_the_fallback():
    report = build_report(_scorecard([_criterion(resolution="Connect NetSuite", confidence="assumed")]))
    assert report["criteria"][0]["evidence_needed"] == "Connect NetSuite"
    assert "Nothing verifiable supports this yet" not in render_report_html(report)


def test_a_fully_evidenced_criterion_asks_for_nothing():
    report = build_report(_scorecard([_criterion(resolution=None, confidence="high")]))
    assert report["criteria"][0]["evidence_needed"] is None
