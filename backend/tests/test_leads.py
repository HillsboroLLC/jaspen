import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from unittest.mock import Mock

from app.models import Lead, LeadAttributionEvent, LeadEmailDelivery


LEADS_URL = "/api/v1/public/leads"


@pytest.fixture(autouse=True)
def _disable_rate_limiting_for_this_file():
    from app import limiter

    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


def test_successful_lead_creation(client, db):
    response = client.post(LEADS_URL, json={"email": "person@example.com", "source": "decision-scorecard"})

    assert response.status_code == 201
    assert response.get_json() == {"ok": True, "delivery": None}
    lead = Lead.query.one()
    assert lead.email == "person@example.com"
    assert lead.normalized_email == "person@example.com"
    assert lead.source == "decision-scorecard"
    event = LeadAttributionEvent.query.one()
    assert event.lead_id == lead.id
    assert event.source == "decision-scorecard"


def test_repeated_submission_updates_non_empty_metadata(client, db):
    first = client.post(LEADS_URL, json={"email": "person@example.com", "source": "decision-scorecard"})
    second = client.post(
        LEADS_URL,
        json={
            "email": "person@example.com",
            "source": "decision-scorecard",
            "company": "Jaspen",
            "utm_campaign": "scorecard-launch",
        },
    )

    assert first.status_code == 201
    assert second.status_code == 200
    leads = Lead.query.all()
    assert len(leads) == 1
    assert leads[0].company == "Jaspen"
    assert leads[0].utm_campaign == "scorecard-launch"
    assert LeadAttributionEvent.query.count() == 2


def test_email_normalization(client, db):
    response = client.post(LEADS_URL, json={"email": "  PERSON@Example.COM  ", "source": "decision-scorecard"})

    assert response.status_code == 201
    assert Lead.query.one().email == "person@example.com"
    assert Lead.query.one().normalized_email == "person@example.com"


def test_missing_email(client, db):
    response = client.post(LEADS_URL, json={"source": "decision-scorecard"})

    assert response.status_code == 400
    assert response.get_json()["code"] == "email_required"


def test_invalid_email(client, db):
    response = client.post(LEADS_URL, json={"email": "not-an-email", "source": "decision-scorecard"})

    assert response.status_code == 400
    assert response.get_json()["code"] == "invalid_email"


def test_malformed_json(client, db):
    response = client.post(LEADS_URL, data="{", content_type="application/json")

    assert response.status_code == 400
    assert response.get_json()["code"] == "invalid_json"


def test_unexpected_payload_type(client, db):
    response = client.post(LEADS_URL, json=["person@example.com"])

    assert response.status_code == 400
    assert response.get_json()["code"] == "invalid_payload"


def test_unexpected_field_type(client, db):
    response = client.post(LEADS_URL, json={"email": ["person@example.com"], "source": "decision-scorecard"})

    assert response.status_code == 400
    assert response.get_json()["code"] == "email_invalid_type"


def test_field_length_limit(client, db):
    response = client.post(
        LEADS_URL,
        json={"email": "person@example.com", "source": "x" * 81},
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "source_too_long"


def test_database_failure_returns_sanitized_500(client, db, monkeypatch):
    def fail_commit():
        raise SQLAlchemyError("database details should not leak")

    monkeypatch.setattr(db.session, "commit", fail_commit)

    response = client.post(LEADS_URL, json={"email": "person@example.com", "source": "decision-scorecard"})

    assert response.status_code == 500
    assert response.get_json() == {"error": "Internal server error"}


def test_same_normalized_email_across_sources_reuses_contact_and_records_events(client, db):
    first = client.post(LEADS_URL, json={"email": "person@example.com", "source": "decision-scorecard"})
    second = client.post(LEADS_URL, json={"email": " PERSON@example.com ", "source": "webinar"})

    assert first.status_code == 201
    assert second.status_code == 200
    assert Lead.query.count() == 1
    assert Lead.query.one().source == "webinar"
    assert sorted(event.source for event in LeadAttributionEvent.query.all()) == ["decision-scorecard", "webinar"]


def test_database_uniqueness_constraint_blocks_same_normalized_email(db):
    db.session.add(Lead(email="person@example.com", normalized_email="person@example.com", source="decision-scorecard"))
    db.session.add(Lead(email="person@example.com", normalized_email="person@example.com", source="webinar"))

    with pytest.raises(IntegrityError):
        db.session.commit()


def test_toolkit_lead_sends_email_before_success(client, db, monkeypatch):
    sent = []

    def send(msg):
        sent.append(msg)

    monkeypatch.setattr("app.routes.leads.mail.send", send)
    response = client.post(
        LEADS_URL,
        json={
            "email": "person@example.com",
            "source": "decision-planning-toolkit",
            "marketing_opt_in": False,
        },
    )

    assert response.status_code == 201
    assert response.get_json() == {"ok": True, "delivery": "email"}
    assert len(sent) == 1
    assert sent[0].recipients == ["person@example.com"]
    assert "List-Unsubscribe" in sent[0].extra_headers
    assert Lead.query.count() == 1
    assert LeadAttributionEvent.query.one().email_delivery_requested is True
    delivery = LeadEmailDelivery.query.one()
    assert delivery.status == "sent"
    assert delivery.sent_at is not None


def test_toolkit_email_failure_returns_failure_without_success(client, db, monkeypatch):
    def fail(_msg):
        raise RuntimeError("smtp unavailable")

    monkeypatch.setattr("app.routes.leads.mail.send", fail)
    response = client.post(
        LEADS_URL,
        json={"email": "person@example.com", "source": "decision-planning-toolkit"},
    )

    assert response.status_code == 502
    assert response.get_json()["error"] == "We could not email the toolkit right now. Please try again."
    assert Lead.query.count() == 1
    assert LeadAttributionEvent.query.count() == 1
    assert LeadEmailDelivery.query.one().status == "failed"


def test_invalid_email_does_not_send_toolkit_email(client, db, monkeypatch):
    send = Mock()
    monkeypatch.setattr("app.routes.leads.mail.send", send)

    response = client.post(
        LEADS_URL,
        json={"email": "not-an-email", "source": "decision-planning-toolkit"},
    )

    assert response.status_code == 400
    assert send.call_count == 0
    assert Lead.query.count() == 0
