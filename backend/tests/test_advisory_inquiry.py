"""Executive Partnership Request capture.

An advisory enquiry is a $25,000–$100,000 conversation, so the inquiry must
survive anything that goes wrong with email, and the acknowledgement must not
read as though the engagement has been accepted.
"""

import json

import pytest

from app.models import AdvisoryInquiry, Lead

URL = "/api/v1/public/leads/advisory-inquiry"


def _payload(**overrides):
    body = {
        "source": "advisory-partnerships",
        "email": "cfo@acme.co",
        "first_name": "Dana",
        "last_name": "Reyes",
        "company": "Acme Industrial",
        "title": "CFO",
        "phone": "+1 555 0100",
        "engagement": "executive_decision_intensive",
        "decision_description": "We are choosing between consolidating two plants or investing in automation at both.",
        "desired_outcome": "Decide where to allocate capital next fiscal year.",
        "financial_impact_band": "5m_25m",
        "decision_timeline": "1_3_months",
        "participants": ["ceo", "cfo", "business_unit_leader"],
        "decision_authority": "shared",
        "additional_notes": "Board reviews this in October.",
        "source_url": "https://www.jaspen.ai/#pricing-variant-b",
    }
    body.update(overrides)
    return body


@pytest.fixture
def sent(monkeypatch):
    outbox = []
    monkeypatch.setattr("app.routes.leads.mail.send", lambda message: outbox.append(message))
    return outbox


# --- Happy path -------------------------------------------------------------

def test_a_request_is_stored_with_every_answer(client, db, sent):
    response = client.post(URL, json=_payload())

    assert response.status_code == 201
    body = response.get_json()
    assert body["ok"] is True

    inquiry = AdvisoryInquiry.query.one()
    assert inquiry.engagement == "executive_decision_intensive"
    assert inquiry.decision_timeline == "1_3_months"
    assert inquiry.financial_impact_band == "5m_25m"
    assert inquiry.decision_authority == "shared"
    assert inquiry.participants == ["ceo", "cfo", "business_unit_leader"]
    assert "consolidating two plants" in inquiry.decision_description
    assert inquiry.additional_notes == "Board reviews this in October."
    # The lead record ties it into existing attribution.
    assert Lead.query.filter_by(normalized_email="cfo@acme.co").one() is not None
    assert inquiry.attribution_event_id is not None


def test_it_emails_the_advisory_mailbox_and_acknowledges_the_requester(client, db, sent):
    response = client.post(URL, json=_payload())

    assert response.get_json() == {
        "ok": True,
        "inquiry_id": AdvisoryInquiry.query.one().id,
        "notified": True,
        "acknowledged": True,
    }
    assert len(sent) == 2

    notification, acknowledgement = sent
    assert notification.recipients == ["partnerships@jaspen.ai"]
    assert "partnerships@jaspen.ai" in notification.sender
    # Replying to the notification reaches the requester, not the mailbox.
    assert notification.reply_to == "cfo@acme.co"
    assert "Acme Industrial" in notification.subject
    assert "consolidating two plants" in notification.body

    assert acknowledgement.recipients == ["cfo@acme.co"]
    assert "partnerships@jaspen.ai" in acknowledgement.sender
    assert acknowledgement.reply_to == "partnerships@jaspen.ai"


def test_the_acknowledgement_confirms_receipt_without_promising_an_engagement(client, db, sent):
    client.post(URL, json=_payload())
    ack = sent[1]

    for part in (ack.body, ack.html):
        assert "received" in part.lower()
        assert "Thank you for your interest in Jaspen Executive Partnerships" in part
        assert "Executive Decision Intensive ($25,000)" in part
        assert "1–3 months" in part
        # Roles read the way the form read them, not as stored keys.
        assert "CFO" in part
        # Conditional, so it cannot be read as an acceptance or a promise of a
        # reply by a given date.
        assert "We review every request personally" in part
        assert "If your request aligns with our current capacity and expertise" in part
        assert "business days" not in part
        # No outcome promises, matching the pricing copy's restraint.
        assert "guarantee" not in part.lower()
        assert "EBITDA" not in part

    assert ack.html.lstrip().startswith("<!doctype html>")
    assert "Jaspen" in ack.html


def test_an_undecided_requester_is_still_a_valid_request(client, db, sent):
    response = client.post(URL, json=_payload(engagement="undecided"))

    assert response.status_code == 201
    assert AdvisoryInquiry.query.one().engagement == "undecided"
    assert "Not sure yet" in sent[1].body


def test_the_impact_band_is_optional(client, db, sent):
    payload = _payload()
    del payload["financial_impact_band"]

    assert client.post(URL, json=payload).status_code == 201
    assert AdvisoryInquiry.query.one().financial_impact_band is None


# --- The inquiry outlives email failures ------------------------------------

def test_a_mail_outage_never_loses_the_request(client, db, monkeypatch):
    def explode(_message):
        raise RuntimeError("SMTP is down")

    monkeypatch.setattr("app.routes.leads.mail.send", explode)

    response = client.post(URL, json=_payload())

    assert response.status_code == 201
    assert response.get_json()["notified"] is False
    assert response.get_json()["acknowledged"] is False
    # The enquiry is what matters; it is stored regardless.
    assert AdvisoryInquiry.query.count() == 1


def test_a_failed_acknowledgement_still_notifies_the_team(client, db, monkeypatch):
    calls = []

    def flaky(message):
        calls.append(message)
        if len(calls) > 1:
            raise RuntimeError("bounced")

    monkeypatch.setattr("app.routes.leads.mail.send", flaky)

    body = client.post(URL, json=_payload()).get_json()

    assert body["notified"] is True
    assert body["acknowledged"] is False
    assert AdvisoryInquiry.query.count() == 1


# --- Validation -------------------------------------------------------------

@pytest.mark.parametrize("field,value", [
    ("engagement", "platinum_tier"),
    ("decision_timeline", "someday"),
    ("decision_authority", "maybe"),
    ("financial_impact_band", "a_lot"),
    ("participants", ["ceo", "chief_vibes_officer"]),
])
def test_values_outside_the_form_are_rejected(client, db, sent, field, value):
    response = client.post(URL, json=_payload(**{field: value}))

    assert response.status_code == 400
    assert AdvisoryInquiry.query.count() == 0
    assert sent == []


@pytest.mark.parametrize("field", ["decision_description", "desired_outcome"])
def test_the_decision_context_is_required(client, db, sent, field):
    response = client.post(URL, json=_payload(**{field: "   "}))

    assert response.status_code == 400
    assert AdvisoryInquiry.query.count() == 0


def test_at_least_one_participant_is_required(client, db, sent):
    assert client.post(URL, json=_payload(participants=[])).status_code == 400
    assert AdvisoryInquiry.query.count() == 0


def test_a_personal_email_is_refused(client, db, sent):
    response = client.post(URL, json=_payload(email="dana@gmail.com"))

    assert response.status_code == 400
    assert response.get_json()["code"] == "business_email_required"
    assert AdvisoryInquiry.query.count() == 0


def test_the_honeypot_rejects_bots_silently(client, db, sent):
    response = client.post(URL, json=_payload(website="http://spam.example"))

    assert response.status_code == 400
    assert AdvisoryInquiry.query.count() == 0
    assert sent == []


def test_a_long_description_is_truncated_rather_than_rejected(client, db, sent):
    response = client.post(URL, json=_payload(decision_description="x" * 2500))

    assert response.status_code == 201
    assert len(AdvisoryInquiry.query.one().decision_description) == 2000


def test_a_thorough_answer_in_every_free_text_field_still_fits(client, db, sent):
    """The lead endpoints cap a request at 8KB. The three free-text fields are
    the only ones that can grow, so filling all of them to their limit must
    still be accepted rather than rejected as too large."""
    response = client.post(URL, json=_payload(
        decision_description="d" * 2000,
        desired_outcome="o" * 1000,
        additional_notes="n" * 2000,
    ))

    assert response.status_code == 201
    inquiry = AdvisoryInquiry.query.one()
    assert len(inquiry.decision_description) == 2000
    assert len(inquiry.additional_notes) == 2000


def test_the_enterprise_inquiry_path_is_untouched(client, db, sent):
    """Advisory has its own table; it must not disturb the calculator flow."""
    from app.models import EnterpriseInquiry

    client.post(URL, json=_payload())

    assert AdvisoryInquiry.query.count() == 1
    assert EnterpriseInquiry.query.count() == 0
