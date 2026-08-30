"""The batch scorer holds the same evidence contract as the single scorer.

This is the path the product uses for a multi-option decision, and it used to
hardcode source to "inferred", null what_would_improve, and drop the model's
evidence entirely. Every card it produced reported that nothing the user said
had been used, however much they had provided.
"""

import pytest


@pytest.fixture
def strategy(app):
    from app.routes import strategy as mod
    return mod


WHAT_THE_USER_WROTE = (
    "The 3PL charges us $6.80 per return and we processed 31,400 returns last "
    "quarter. Standing up an in-house line would cost about $340,000."
)


def test_the_batch_prompt_asks_for_the_same_contract(strategy):
    """A prompt that never asks cannot receive."""
    import inspect
    src = inspect.getsource(strategy._generate_batch_scorecards)
    assert '"evidence"' in src
    assert "what_would_improve" in src
    assert "EVIDENCE QUOTES" in src
    assert "SOURCE MATERIAL" in src


def test_the_batch_scorer_verifies_rather_than_trusting(strategy):
    import inspect
    src = inspect.getsource(strategy._generate_batch_scorecards)
    assert "attach_evidence_references" in src


def test_source_is_no_longer_hardcoded(strategy):
    import inspect
    src = inspect.getsource(strategy._generate_batch_scorecards)
    assert '"source": "inferred"' not in src


def test_a_real_quote_verifies_against_the_conversation(app):
    from app.evidence_references import attach_evidence_references
    dims = {"financial_return": {"score": 70, "confidence": "medium",
                                 "evidence": ["$6.80 per return"]}}
    assert attach_evidence_references(dims, WHAT_THE_USER_WROTE) == 1
    assert dims["financial_return"]["evidence_references"][0]["excerpt"] == "$6.80 per return"


def test_a_fabricated_quote_is_rejected(app):
    from app.evidence_references import attach_evidence_references
    dims = {"financial_return": {"score": 70, "confidence": "medium",
                                 "evidence": ["a signed contract at $4.10 per return"]}}
    assert attach_evidence_references(dims, WHAT_THE_USER_WROTE) == 0
    assert dims["financial_return"].get("evidence_references") in (None, [])


def test_the_corpus_reaches_every_chunk(strategy):
    """A long batch splits into chunks; each must carry the corpus or every
    option past the first chunk silently loses its evidence."""
    import inspect
    src = inspect.getsource(strategy._generate_batch_scorecards)
    assert src.count("evidence_corpus=evidence_corpus") >= 1


def test_only_user_turns_enter_the_corpus(strategy, app):
    """Quoting the assistant back would let the model cite its own prose as
    evidence for its own score."""
    import inspect
    src = inspect.getsource(strategy._thread_user_corpus)
    assert '"user"' in src


def test_ai_authored_option_text_is_not_a_valid_source(strategy):
    """A live run quoted the agent's own option description and it verified.

    The option description is written upstream by the agent, so admitting it to
    the verification corpus let the model cite AI-authored text as evidence for
    an AI-authored score. Only the user's words count when we have them.
    """
    import inspect
    src = inspect.getsource(strategy._generate_batch_scorecards)
    assert "_verification_text = _corpus_text or" in src
