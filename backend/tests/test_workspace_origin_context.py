import sys

import pytest


def _context_helpers():
    module = sys.modules["app.routes.ai_agent"]
    return module._sanitize_view_context, module._view_context_prompt_suffix


def test_workspace_origin_context_is_bounded_and_keeps_a_matching_back_link(app):
    sanitize, _ = _context_helpers()
    raw = {
        "surface": "workspace",
        "origin": {
            "session_id": "session-123",
            "session_name": "S" * 220,
            "scorecard_name": "C" * 220,
            "origin_request": "R" * 260,
            "back_link": "/new?sid=session-123",
        },
    }

    cleaned = sanitize(raw)

    assert cleaned["surface"] == "workspace"
    assert cleaned["origin"]["session_id"] == "session-123"
    assert len(cleaned["origin"]["session_name"]) == 160
    assert len(cleaned["origin"]["scorecard_name"]) == 160
    assert len(cleaned["origin"]["origin_request"]) == 200
    assert cleaned["origin"]["back_link"] == "/new?sid=session-123"


@pytest.mark.parametrize("back_link", [
    "/new?sid=session-elsewhere",
    "https://jaspen.ai/new?sid=session-123",
    "/new?sid=session-123&extra=true",
    "/new?sid=" + ("x" * 300),
])
def test_workspace_origin_context_drops_an_invalid_back_link(app, back_link):
    sanitize, _ = _context_helpers()
    cleaned = sanitize({
        "surface": "workspace",
        "origin": {
            "session_id": "session-123",
            "back_link": back_link,
        },
    })

    assert "back_link" not in cleaned["origin"]


def test_workspace_prompt_names_the_origin_request_and_back_link(app):
    _, prompt_suffix = _context_helpers()
    suffix = prompt_suffix({
        "surface": "workspace",
        "origin": {
            "session_id": "session-123",
            "session_name": "City of Aurora bid",
            "scorecard_name": "Bid option",
            "origin_request": "Should we bid on this contract?",
            "back_link": "/new?sid=session-123",
        },
    })

    assert "You are in the Workspace" in suffix
    assert "City of Aurora bid" in suffix
    assert "Should we bid on this contract?" in suffix
    assert "Open scorecard or option: \"Bid option\"" in suffix
    assert "Link back to the originating session: /new?sid=session-123" in suffix


def test_workspace_prompt_names_one_pager_layout_and_editable_slots(app):
    sanitize, prompt_suffix = _context_helpers()
    raw = {
        "surface": "workspace",
        "current_view": "scorecard",
        "workspace_layout": "one-pager",
        "presentation_text_slots": ["headline", "summary", "not_a_slot", "headline"],
        "presentation_color_slots": ["accent", "ink", "tint", "legacy_accent"],
    }

    cleaned = sanitize(raw)
    suffix = prompt_suffix(raw)

    assert cleaned["workspace_layout"] == "one-pager"
    assert cleaned["presentation_text_slots"] == ["headline", "summary"]
    assert cleaned["presentation_color_slots"] == ["accent", "ink", "tint"]
    assert "Open Workspace layout: one-pager" in suffix
    assert "report_presentation text slots: headline, summary" in suffix
    assert "report_presentation color slots: accent, ink, tint" in suffix
