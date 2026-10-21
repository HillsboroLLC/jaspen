"""One unreadable extracted fact must never stop scoring (live: "due November 20")."""
from app.decision_facts import normalize_option_facts
from app.decision_kits import get_decision_kit

LIVE_MESSAGE = (
    "Help me evaluate this RFP for the City of Westminster water treatment SCADA replacement. "
    "It is about $1.8M and due November 20."
)


def test_unreadable_extracted_date_is_rejected_and_scoring_continues(app):
    rejected = []
    facts = normalize_option_facts(
        {}, kit=get_decision_kit('rfp_bid'), source_text=LIVE_MESSAGE,
        extract=True, extract_types={"date", "enum"}, rejected_fields=rejected,
    )
    assert 'submission_due' not in facts
    assert rejected and rejected[0]['field'] == 'submission_due'
    assert rejected[0]['value'] == 'November 20'
