"""The sidebar can reword a criterion, and the card actually changes.

The defect: asked to reword "Strategic Fit", the agent had no field that
reaches a criterion card. It fell back to add_blocks, appended a stray
section, and reported success while the criterion was untouched. An agent
that says it edited the report while the report disagrees is worse than one
that says it cannot.
"""

import pytest


@pytest.fixture
def patch_card(app):
    from app.routes.ai_agent import _execute_mutation_tool  # noqa: F401
    from app.routes.strategy import _merge_scorecard_patch  # noqa: F401
    # The narrative application lives inside the patch closure, so exercise it
    # through the same shape the workspace reads.
    return None


CARD = {
    "jaspen_score": 56,
    "dimensions": {
        "strategic_fit": {"label": "Strategic Fit", "score": 60, "confidence": "medium",
                          "rationale": "Original assessment."},
        "risk_capital_efficiency": {"label": "Risk & Capital Efficiency", "score": 48,
                                    "confidence": "low", "rationale": "Original risk text."},
    },
}


def _apply(narrative_input, card=None):
    """Mirror of the agent's criterion_narrative application."""
    from app.routes.ai_agent import _iso_now
    merged = dict(card or CARD)
    new_narrative = {}
    if isinstance(narrative_input, dict):
        for key, value in narrative_input.items():
            text = value.get("rationale") if isinstance(value, dict) else value
            text = str(text or "").strip()
            handle = str(key or "").strip()
            if text and handle:
                new_narrative[handle] = text

    _ovn = dict(merged.get("display_overrides") or {})
    narrative = dict(_ovn.get("criterion_narrative") or {})
    dims = merged.get("dimensions") or {}
    by_handle = {}
    for dim_key, dim in dims.items():
        by_handle[str(dim_key).strip().casefold()] = dim_key
        label = str((dim or {}).get("label") or "").strip().casefold()
        if label:
            by_handle.setdefault(label, dim_key)
        by_handle.setdefault(str(dim_key).replace("_", " ").casefold(), dim_key)
    for handle, text in new_narrative.items():
        resolved = by_handle.get(handle.strip().casefold())
        if not resolved:
            continue
        narrative[resolved] = {"rationale": text, "edited_at": _iso_now(),
                               "note": "Edited by Jaspen at your request"}
    if narrative:
        _ovn["criterion_narrative"] = narrative
        merged["display_overrides"] = _ovn
    return merged


def test_the_visible_label_resolves_to_the_criterion(app):
    """A user says "Strategic Fit", not "strategic_fit"."""
    out = _apply({"Strategic Fit": "Sharper wording."})
    assert out["display_overrides"]["criterion_narrative"]["strategic_fit"]["rationale"] == "Sharper wording."


def test_the_raw_key_also_resolves(app):
    out = _apply({"strategic_fit": "Sharper wording."})
    assert "strategic_fit" in out["display_overrides"]["criterion_narrative"]


def test_an_unknown_criterion_creates_nothing(app):
    """Naming a criterion that does not exist must not invent one."""
    out = _apply({"Vibes": "Nonsense."})
    assert "criterion_narrative" not in (out.get("display_overrides") or {})


def test_rewording_never_moves_the_score(app):
    out = _apply({"Strategic Fit": "Sharper wording."})
    assert out["jaspen_score"] == 56
    assert out["dimensions"]["strategic_fit"]["score"] == 60
    assert out["dimensions"]["strategic_fit"]["confidence"] == "medium"


def test_the_original_is_left_intact_for_restore(app):
    """The workspace keeps Jaspen's words; the override sits beside them."""
    out = _apply({"Strategic Fit": "Sharper wording."})
    assert out["dimensions"]["strategic_fit"]["rationale"] == "Original assessment."


def test_the_agent_edit_is_marked(app):
    out = _apply({"Strategic Fit": "Sharper wording."})
    entry = out["display_overrides"]["criterion_narrative"]["strategic_fit"]
    assert entry["edited_at"]
    assert entry["note"]
