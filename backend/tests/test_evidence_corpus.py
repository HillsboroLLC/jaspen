"""Evidence is verified against what the user actually wrote.

The defect this pins: the chat tool passes a "concise description of the idea"
as the text to score, so the words the user typed never reached the scorer.
Quotes were then checked against that summary, failed to match, and were
discarded, leaving every scorecard with zero evidence references and every
dimension reading as "inferred".
"""

from app.evidence_references import attach_evidence_references

SUMMARY = "Expand into a new market next year."
WHAT_THE_USER_WROTE = (
    "We are paying roughly $40,000 a month in carrier penalties and the "
    "late-delivery rate sits at 22%."
)


def _dims():
    return {
        "financial_return": {
            "score": 60,
            "confidence": "medium",
            "evidence": ["roughly $40,000 a month in carrier penalties"],
        }
    }


def test_a_real_quote_is_discarded_when_only_the_summary_is_searched():
    """The old behaviour, kept as a regression witness."""
    dims = _dims()
    assert attach_evidence_references(dims, SUMMARY) == 0
    assert dims["financial_return"].get("evidence_references") in (None, [])


def test_the_same_quote_verifies_against_the_user_s_own_words():
    dims = _dims()
    corpus = f"{SUMMARY}\n\n{WHAT_THE_USER_WROTE}"
    assert attach_evidence_references(dims, corpus) == 1
    refs = dims["financial_return"]["evidence_references"]
    assert refs[0]["excerpt"] == "roughly $40,000 a month in carrier penalties"


def test_a_fabricated_quote_is_still_rejected_from_the_wider_corpus():
    """Widening the corpus must not weaken verification."""
    dims = {
        "financial_return": {
            "score": 60,
            "confidence": "medium",
            "evidence": ["a signed carrier contract at $9.00 per order"],
        }
    }
    corpus = f"{SUMMARY}\n\n{WHAT_THE_USER_WROTE}"
    assert attach_evidence_references(dims, corpus) == 0
