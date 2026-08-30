"""An AI risk edit must not silently drop the fields it did not mention.

The capability is deliberate: the sidebar may change a risk, including its
numbers. The guard is against data loss, not against the agent.
"""

import pytest


@pytest.fixture
def merge(app):
    """Imported inside the app fixture: strategy pulls config at import time."""
    from app.routes.strategy import _merge_scorecard_patch
    return _merge_scorecard_patch

STORED = {
    "top_risks": [{
        "id": "rk_1",
        "risk": "Consolidation concentrates volume on one dock.",
        "probability": "Medium",
        "impact_dollars": 2100000,
        "impact_category": "operational_efficiency",
        "mitigation": "Retain Sparks as a warm standby.",
        "mitigation_cost": 180000,
        "residual_risk": "Low",
    }],
}


def test_rewording_a_risk_keeps_its_structured_findings(merge):
    patched = merge(STORED, {
        "top_risks": [{"id": "rk_1", "risk": "Volume concentrates on a single dock."}],
    })
    row = patched["top_risks"][0]
    assert row["risk"] == "Volume concentrates on a single dock."
    assert str(row["impact_dollars"]) == "2100000"
    assert row["probability"] == "Medium"
    assert str(row["mitigation_cost"]) == "180000"
    assert row["residual_risk"] == "Low"


def test_the_agent_may_still_change_a_number_when_it_says_so(merge):
    """Capability intact: an explicit value wins."""
    patched = merge(STORED, {
        "top_risks": [{"id": "rk_1", "impact_dollars": 900000}],
    })
    assert str(patched["top_risks"][0]["impact_dollars"]) == "900000"
    assert patched["top_risks"][0]["risk"] == "Consolidation concentrates volume on one dock."


def test_a_risk_matched_by_text_when_no_id_is_carried(merge):
    patched = merge(STORED, {
        "top_risks": [{
            "risk": "Consolidation concentrates volume on one dock.",
            "mitigation": "Hold Sparks for twelve weeks.",
        }],
    })
    row = patched["top_risks"][0]
    assert row["mitigation"] == "Hold Sparks for twelve weeks."
    assert str(row["impact_dollars"]) == "2100000"


def test_a_genuinely_new_risk_is_added_untouched(merge):
    patched = merge(STORED, {
        "top_risks": [{"risk": "Carrier renegotiates mid-term.", "probability": "Low"}],
    })
    assert len(patched["top_risks"]) == 1
    assert patched["top_risks"][0]["risk"] == "Carrier renegotiates mid-term."
    # Normalisation fills the schema; the point is nothing was inherited.
    assert patched["top_risks"][0].get("impact_dollars") is None
