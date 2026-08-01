"""The workspace PDF must reproduce the canvas the user actually arranged.

Layout used to live only in the browser (localStorage 'jw-layout-*'), so the
exporter had no way to know it and always emitted a fixed arrangement. These
tests pin the behaviour now that display_overrides.section_layout carries it.
"""

import importlib

import pytest


@pytest.fixture
def export_routes(app):
    return importlib.import_module("app.routes.export")


def _card(section_layout=None, custom_blocks=None, **extra):
    overrides = {}
    if section_layout is not None:
        overrides["section_layout"] = section_layout
    card = {
        "project_name": "Existing GridPoint multi-site customers",
        "jaspen_score": 75,
        "score_category": "Good",
        "executive_summary": "Strongest execution foundation and best market economics.",
        "dimensions": {
            "deployment": {"label": "Deployment Readiness", "score": 75},
            "relationship": {"label": "Existing Relationship", "score": 75},
            "customer": {"label": "Customer Readiness", "score": 75},
        },
        "risks": ["Pilot willingness not confirmed."],
        "top_risks": ["Pilot willingness not confirmed."],
        "recommendations": ["Confirm willingness with the top three sites."],
        "recommended_scenario": "Confirm willingness with the top three sites.",
        "custom_blocks": custom_blocks or [],
        "display_overrides": overrides,
        "component_scores": {},
        "financial_impact": {},
        "accent_color": "#A0036C",
    }
    card.update(extra)
    return card


def test_saved_layout_places_sections_side_by_side(export_routes):
    """Two half-width cards on the same grid row export as one row."""
    layout = [
        {"key": "score", "x": 0, "y": 0, "w": 4},
        {"key": "executive", "x": 4, "y": 0, "w": 8},
        {"key": "dimensions", "x": 0, "y": 4, "w": 12},
        {"key": "risks", "x": 0, "y": 12, "w": 6},
        {"key": "scenario", "x": 6, "y": 12, "w": 6},
    ]
    resolved = export_routes._scorecard_section_layout(_card(layout))
    assert resolved["score"]["w"] == 4
    assert resolved["executive"]["w"] == 8
    assert resolved["_fallback"] is False

    rows = export_routes._pack_layout_rows([
        {"y": 0, "x": 0, "w": 4, "flowable": "score"},
        {"y": 0, "x": 4, "w": 8, "flowable": "executive"},
        {"y": 4, "x": 0, "w": 12, "flowable": "dimensions"},
        {"y": 12, "x": 0, "w": 6, "flowable": "risks"},
        {"y": 12, "x": 6, "w": 6, "flowable": "scenario"},
    ])
    assert [[item["flowable"] for item in row] for row in rows] == [
        ["score", "executive"],
        ["dimensions"],
        ["risks", "scenario"],
    ]


def test_custom_block_shares_a_row_with_a_built_in_section(export_routes):
    """A user block dragged beside Top risks exports beside Top risks."""
    layout = [
        {"key": "score", "x": 0, "y": 0, "w": 4},
        {"key": "executive", "x": 4, "y": 0, "w": 8},
        {"key": "dimensions", "x": 0, "y": 4, "w": 12},
        {"key": "risks", "x": 0, "y": 12, "w": 6},
    ]
    blocks = [{"id": "blk_1", "heading": "Mitigation", "body": "Ready to test.",
               "x": 6, "y": 12, "w": 6, "h": 4}]
    parsed = export_routes._scorecard_custom_blocks(_card(layout, blocks))
    assert parsed[0]["x"] == 6 and parsed[0]["y"] == 12 and parsed[0]["w"] == 6

    rows = export_routes._pack_layout_rows([
        {"y": 12, "x": 0, "w": 6, "flowable": "risks"},
        {"y": 12, "x": 6, "w": 6, "flowable": "mitigation"},
    ])
    assert len(rows) == 1


def test_layout_omitting_a_section_drops_it_from_the_pdf(export_routes):
    """A saved layout lists every section on the canvas, so a missing key means
    the user removed it — the export must not resurrect it at a guessed spot."""
    layout = [
        {"key": "score", "x": 0, "y": 0, "w": 4},
        {"key": "executive", "x": 4, "y": 0, "w": 8},
    ]
    resolved = export_routes._scorecard_section_layout(_card(layout))
    assert "scenario" not in resolved
    assert "risks" not in resolved


def test_no_saved_layout_falls_back_to_the_historical_arrangement(export_routes):
    """Scorecards that predate layout persistence keep exporting as before."""
    resolved = export_routes._scorecard_section_layout(_card(None))
    assert resolved["_fallback"] is True
    # Score beside the summary, dimensions full width.
    assert resolved["score"]["w"] == 3
    assert resolved["executive"]["w"] == 9
    assert resolved["dimensions"]["w"] == 12


def test_collapsed_and_single_column_flags_survive(export_routes):
    layout = [
        {"key": "dimensions", "x": 0, "y": 4, "w": 12, "dimCols": 1},
        {"key": "risks", "x": 0, "y": 12, "w": 6, "collapsed": True},
    ]
    resolved = export_routes._scorecard_section_layout(_card(layout))
    assert resolved["dimensions"]["dim_cols"] == 1
    assert resolved["risks"]["collapsed"] is True


def test_pdf_renders_with_a_saved_layout(export_routes):
    """End-to-end: the rich renderer must succeed, not fall back to markdown."""
    layout = [
        {"key": "score", "x": 0, "y": 0, "w": 4},
        {"key": "executive", "x": 4, "y": 0, "w": 8},
        {"key": "dimensions", "x": 0, "y": 4, "w": 12, "dimCols": 1},
        {"key": "risks", "x": 0, "y": 12, "w": 6},
    ]
    blocks = [{"id": "blk_1", "heading": "Mitigation", "body": "Ready to test.",
               "x": 6, "y": 12, "w": 6, "h": 4}]

    called = {"fallback": False}
    original = export_routes._markdown_to_pdf_bytes

    def _spy(*args, **kwargs):
        called["fallback"] = True
        return original(*args, **kwargs)

    export_routes._markdown_to_pdf_bytes = _spy
    try:
        payload = export_routes._scorecard_pdf_bytes(_card(layout, blocks))
    finally:
        export_routes._markdown_to_pdf_bytes = original

    assert payload.startswith(b"%PDF")
    assert called["fallback"] is False, "rich renderer silently fell back to markdown"


def test_section_layout_survives_the_overrides_patch_whitelist(app):
    """The PATCH endpoint drops unknown keys, so section_layout must be listed
    and sanitized — otherwise the layout never reaches storage at all."""
    strategy = importlib.import_module("app.routes.strategy")
    assert "section_layout" in strategy._ALLOWED_OVERRIDE_KEYS

    cleaned = strategy._coerce_override_value("section_layout", [
        {"key": "score", "x": 0, "y": 0, "w": 4},
        {"key": "bogus", "x": 0, "y": 0, "w": 4},          # unknown section
        {"key": "dimensions", "x": 0, "y": 4, "w": 99, "dimCols": 1},  # clamp w
        "not-a-dict",
    ])
    keys = [row["key"] for row in cleaned]
    assert keys == ["score", "dimensions"]
    assert cleaned[1]["w"] == 12
    assert cleaned[1]["dimCols"] == 1

    assert strategy._coerce_override_value("section_layout", "nonsense") is None
    assert strategy._coerce_override_value("section_layout", []) is None
