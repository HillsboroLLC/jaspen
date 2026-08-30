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


# --- the risk register -------------------------------------------------------

RISK = {
    "id": "rk_abc",
    "risk": "Consolidation concentrates volume on one dock.",
    "probability": "Medium",
    "impact_dollars": 2100000,
    "impact_category": "operational_efficiency",
    "mitigation": "Retain Sparks as a warm standby for eight weeks.",
    "mitigation_cost": 180000,
    "residual_risk": "Low",
}


def _with_risks(risks):
    from app.decision_report import build_risk_register
    return build_risk_register({"top_risks": risks})


def test_a_proposed_mitigation_never_demotes_a_large_risk():
    """Nothing records whether a mitigation was carried out.

    Residual is the expected level IF the plan is executed, so ordering by it
    would demote a $5M risk on the strength of a plan nobody has confirmed was
    started. Impact and likelihood are what is actually known.
    """
    rows = _with_risks([
        {**RISK, "risk": "Small but live", "impact_dollars": 100000, "residual_risk": "High"},
        {**RISK, "risk": "Large with a plan", "impact_dollars": 5000000, "residual_risk": "Low"},
    ])
    assert [r["risk"] for r in rows] == ["Large with a plan", "Small but live"]


def test_likelihood_breaks_ties_on_equal_impact():
    rows = _with_risks([
        {**RISK, "risk": "Unlikely", "impact_dollars": 500000, "probability": "Low"},
        {**RISK, "risk": "Likely", "impact_dollars": 500000, "probability": "High"},
    ])
    assert [r["risk"] for r in rows] == ["Likely", "Unlikely"]


def test_an_unrecorded_mitigation_cost_is_not_reported_as_free():
    """Missing and zero are different findings, and free is the rarer one."""
    unknown = _with_risks([{**RISK, "mitigation_cost": None}])
    assert unknown[0]["mitigation_cost"] is None
    free = _with_risks([{**RISK, "mitigation_cost": 0}])
    assert free[0]["mitigation_cost"] == "No cost"


def test_money_reads_at_decision_precision():
    rows = _with_risks([RISK])
    assert rows[0]["impact"] == "$2.1M"
    assert rows[0]["mitigation_cost"] == "$180K"


def test_a_zero_cost_mitigation_says_so_rather_than_showing_nothing():
    """Free to mitigate is a finding, and an empty cell reads as unknown."""
    rows = _with_risks([{**RISK, "mitigation_cost": 0}])
    assert rows[0]["mitigation_cost"] == "No cost"


def test_every_captured_field_reaches_the_email():
    from app.decision_report_email import render_risks_html
    html = render_risks_html({"risks": _with_risks([RISK])})
    for fragment in ("Likelihood", "Medium", "Impact", "$2.1M", "Operational",
                     "If mitigated", "Low", "Mitigation", "$180K to mitigate"):
        assert fragment in html, fragment


def test_the_email_says_what_the_residual_level_assumes():
    """Without it, "If mitigated: Low" reads as "this risk is handled"."""
    from app.decision_report_email import render_risks_html, render_risks_text
    rows = _with_risks([RISK])
    assert "does not track whether it has been" in render_risks_html({"risks": rows})
    assert "does not track whether it has been" in render_risks_text({"risks": rows})


def test_edited_risk_wording_is_marked_in_the_email():
    from app.decision_report_email import render_risks_html
    html = render_risks_html({"risks": _with_risks([{**RISK, "_edited": True}])})
    assert "Edited" in html


def test_a_plain_string_risk_still_renders():
    """Older scorecards stored risks as bare strings."""
    rows = _with_risks(["Carriers may renegotiate rates."])
    assert rows[0]["risk"] == "Carriers may renegotiate rates."
    assert rows[0]["residual"] is None


def test_no_risks_renders_nothing_rather_than_an_empty_heading():
    from app.decision_report_email import render_risks_html, render_risks_text
    assert render_risks_html({"risks": []}) == ""
    assert render_risks_text({"risks": []}) == ""
