"""W8: the numeric safeguard removes untraceable numbers without breaking the prose."""
import sys


def _sanitize(reply, user_message):
    agent = sys.modules['app.routes.ai_agent']
    return agent._sanitize_assistant_numeric_claims(reply, user_message=user_message, session={})


USER = "We're choosing between a full-time content marketer at about $95K a year and an agency at $6K a month with a 6-month minimum."


def test_lead_in_is_dropped_when_everything_it_introduced_was_removed(app):
    reply = (
        "The two options to score:\n"
        "- Agency over the minimum term: $36K committed.\n"
        "- Hire, fully loaded: $123,500 a year.\n"
        "\n"
        "Note the real cost gap is the switching cost, not the sticker price."
    )
    cleaned = _sanitize(reply, USER)
    assert "$36K" not in cleaned and "$123,500" not in cleaned
    assert "The two options to score" not in cleaned
    assert cleaned == "Note the real cost gap is the switching cost, not the sticker price."


def test_lists_and_paragraphs_keep_their_shape(app):
    reply = (
        "Here's a starter rubric, yours to edit:\n"
        "- Expected pipeline contribution\n"
        "- Speed to first results: 40% weight.\n"
        "- Switching cost if it doesn't work\n"
        "\n"
        "The hire costs about $95K a year. Want me to score both now?"
    )
    cleaned = _sanitize(reply, USER)
    assert cleaned == (
        "Here's a starter rubric, yours to edit:\n"
        "- Expected pipeline contribution\n"
        "- Switching cost if it doesn't work\n"
        "\n"
        "The hire costs about $95K a year. Want me to score both now?"
    )


def test_a_lead_in_on_the_same_line_is_dropped_with_its_removed_content(app):
    cleaned = _sanitize("Quick math: the agency totals $36K over the term. What matters more to you, speed or cost?", USER)
    assert cleaned == "What matters more to you, speed or cost?"


def test_untouched_replies_are_returned_exactly(app):
    reply = "Two paths:\n\n1. Hire for the long game.\n2. Agency for speed."
    assert _sanitize(reply, USER) == reply
