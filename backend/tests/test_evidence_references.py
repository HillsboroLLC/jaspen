"""Evidence references: the record of which input supported a judgment.

The load-bearing tests here are the rejections. A reference that cannot be
verified against the actual source must never be stored, because an unverified
quote recorded under the word "evidence" is precisely the confident,
unsupported artifact the product exists to expose.
"""

from app.evidence_references import (
    ATTACHMENT,
    CONNECTOR,
    CONVERSATION,
    MAX_REFERENCES_PER_CRITERION,
    MIN_EXCERPT_CHARS,
    attach_evidence_references,
    attachment_reference,
    connector_reference,
    conversation_reference,
    locate_excerpt,
    verify_claimed_evidence,
)


HISTORY = [
    {"role": "user", "content": (
        "We are paying roughly $40,000 a month in carrier penalties, and the "
        "late-delivery rate sits at 22%. Dock capacity at Reno is the constraint."
    )},
    {"role": "assistant", "content": "Understood. What is driving the late deliveries?"},
    {"role": "user", "content": "Inbound scheduling is manual, handled by one dispatcher."},
]


# --- verification, the rule that makes this provenance ------------------------

def test_a_quote_that_is_not_in_the_source_is_rejected():
    """The model proposes; the source decides.

    Storing an unverifiable quote under "evidence" would be worse than storing
    nothing: it would look like an audit trail while being another model claim.
    """
    assert conversation_reference(
        "The board approved a $12M budget for this", HISTORY,
    ) is None


def test_a_verified_quote_records_where_it_was_found():
    reference = conversation_reference(
        "late-delivery rate sits at 22%", HISTORY, criterion="evidence_quality",
    )
    assert reference is not None
    assert reference["kind"] == CONVERSATION
    assert reference["criterion"] == "evidence_quality"
    assert reference["locator"]["message_index"] == 0
    assert reference["locator"]["role"] == "user"

    # The offsets must actually address the passage in the original message.
    locator = reference["locator"]
    source = HISTORY[0]["content"]
    assert source[locator["start"]:locator["end"]] == reference["excerpt"]


def test_the_stored_excerpt_is_the_source_wording_not_the_models():
    """A model restates what it quotes. The record keeps what the source said.

    Otherwise the excerpt is the model's paraphrase wearing the source's
    authority, which is the failure this module exists to prevent.
    """
    reference = conversation_reference(
        "LATE-DELIVERY   RATE\n  SITS AT 22%", HISTORY,
    )
    assert reference is not None
    assert reference["excerpt"] == "late-delivery rate sits at 22%"


def test_reformatting_does_not_defeat_verification():
    """Rejecting correct quotes over whitespace would leave us with none."""
    assert locate_excerpt("roughly $40,000 a month", HISTORY[0]["content"]) is not None
    assert locate_excerpt("roughly    $40,000\n\na month", HISTORY[0]["content"]) is not None


def test_assistant_turns_are_never_citable():
    """Jaspen citing itself is a loop that looks like corroboration."""
    assert conversation_reference(
        "What is driving the late deliveries?", HISTORY,
    ) is None


def test_excerpts_too_short_to_identify_anything_are_rejected():
    # "22%" would match somewhere in almost any conversation.
    assert conversation_reference("22%", HISTORY) is None
    assert len("22%") < MIN_EXCERPT_CHARS


def test_a_wall_of_text_is_not_an_excerpt():
    assert locate_excerpt("x" * 5000, "x" * 6000) is None


def test_locate_handles_empty_input_without_guessing():
    assert locate_excerpt("", "some source text here") is None
    assert locate_excerpt("some excerpt here", "") is None


# --- claimed evidence --------------------------------------------------------

def test_only_verifiable_claims_survive():
    claimed = [
        "Dock capacity at Reno is the constraint",   # present
        "We modelled three scenarios in detail",      # absent
        {"excerpt": "Inbound scheduling is manual"},  # present, object form
    ]
    references = verify_claimed_evidence(claimed, HISTORY, criterion="ops")

    assert len(references) == 2
    assert all(r["criterion"] == "ops" for r in references)
    assert all("modelled three scenarios" not in r["excerpt"] for r in references)


def test_the_same_passage_cited_twice_counts_once():
    """Two citations of one sentence is one piece of evidence.

    Counting it twice would overstate how grounded the judgment is, which is
    the specific error this whole feature exists to prevent.
    """
    claimed = ["Dock capacity at Reno is the constraint"] * 3
    assert len(verify_claimed_evidence(claimed, HISTORY)) == 1


def test_a_criterion_cannot_cite_unboundedly():
    """Past a handful, a judgment is being justified rather than evidenced."""
    claimed = [
        "roughly $40,000 a month in carrier penalties",
        "late-delivery rate sits at 22%",
        "Dock capacity at Reno is the constraint",
        "Inbound scheduling is manual",
        "handled by one dispatcher",
        "We are paying roughly $40,000",
    ]
    references = verify_claimed_evidence(claimed, HISTORY)
    assert len(references) <= MAX_REFERENCES_PER_CRITERION


def test_no_claims_yields_no_references_rather_than_an_error():
    assert verify_claimed_evidence(None, HISTORY) == []
    assert verify_claimed_evidence([], HISTORY) == []
    assert verify_claimed_evidence("not a list", HISTORY) == []


def test_plain_text_is_verifiable_the_same_way_a_transcript_is():
    """Scoring is handed a description string, not a transcript.

    That string is the only thing the model could have quoted from, so it has
    to be a valid verification source or the whole path goes unverified.
    """
    description = "Fulfilment cost per order is $14.20 and we want it at $11.00."
    reference = conversation_reference("cost per order is $14.20", description)
    assert reference is not None
    assert reference["locator"]["message_index"] == 0
    assert reference["excerpt"] == "cost per order is $14.20"


# --- attaching to dimensions -------------------------------------------------

def test_attaching_replaces_the_claim_with_the_verified_record():
    dimensions = {
        "ops": {
            "score": 70, "confidence": "medium",
            "evidence": ["Dock capacity at Reno is the constraint"],
        },
        "fin": {
            "score": 80, "confidence": "assumed",
            "evidence": ["A competitor did the same thing last year"],
        },
    }
    verified = attach_evidence_references(dimensions, HISTORY)

    assert verified == 1
    # The unverified claim is gone, not demoted to a sibling field where
    # something downstream could later read it as evidence.
    assert "evidence" not in dimensions["ops"]
    assert "evidence" not in dimensions["fin"]
    assert len(dimensions["ops"]["evidence_references"]) == 1
    assert "evidence_references" not in dimensions["fin"]


def test_attaching_is_safe_on_dimensions_that_claimed_nothing():
    dimensions = {"ops": {"score": 70, "confidence": "high"}}
    assert attach_evidence_references(dimensions, HISTORY) == 0
    assert dimensions["ops"] == {"score": 70, "confidence": "high"}


# --- the other two paths, schema only ----------------------------------------

def test_attachment_reference_carries_a_location_inside_the_file():
    reference = attachment_reference(
        "Penalty accrual: $40,000/mo",
        attachment_id="att_123",
        filename="Cost Model.xlsx",
        location={"sheet": "Assumptions", "cell": "F18"},
        criterion="financial_viability",
    )
    assert reference["kind"] == ATTACHMENT
    assert reference["locator"]["filename"] == "Cost Model.xlsx"
    assert reference["locator"]["location"]["cell"] == "F18"


def test_connector_reference_preserves_the_value_and_when_it_was_true():
    """The snapshot rule, and the reason it matters most on this path.

    A connector value can change after the decision. A reference that only
    pointed at the field would let a Decision Record silently re-describe
    itself, looking authoritative while no longer describing the decision
    anyone actually took.
    """
    reference = connector_reference(
        "40217.55",
        system="NetSuite",
        object_name="Expense",
        record_id="EXP-8841",
        field="monthly_penalty",
        retrieved_at="2026-08-29T10:00:00",
        criterion="financial_viability",
    )
    assert reference["kind"] == CONNECTOR
    assert reference["excerpt"] == "40217.55", "the observed value must be kept"
    assert reference["locator"]["retrieved_at"] == "2026-08-29T10:00:00"
    assert reference["locator"]["system"] == "netsuite"


def test_every_path_produces_the_same_shape():
    """One schema from the start, so adding a path later is not a migration."""
    references = [
        conversation_reference("Dock capacity at Reno is the constraint", HISTORY),
        attachment_reference("some quoted line", attachment_id="a1", filename="f.pdf"),
        connector_reference("123.45", system="netsuite"),
    ]
    for reference in references:
        assert set(reference) == {
            "id", "kind", "criterion", "captured_at", "excerpt", "locator",
        }
        assert reference["id"].startswith("ev_")
        assert reference["excerpt"]
