import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from unittest.mock import Mock

from app.decision_profile import STYLES, derive_decision_style
from app.email_templates.decision_profile_results import PREVIEW_TEXT, SUBJECT, render_decision_profile_email
from app.models import Lead, LeadAttributionEvent, LeadDecisionProfile, LeadEmailDelivery


LEADS_URL = "/api/v1/public/leads"

STYLE_SCENARIOS = {
    "evidence_builder": {
        "q1_instinct_vs_research": "q1_e",
        "q3_documenting": "q3_e",
        "q5_explain_later": "q5_e",
    },
    "fast_mover": {
        "q1_instinct_vs_research": "q1_a",
        "q2_confidence": "q2_e",
        "q3_documenting": "q3_a",
    },
    "thoughtful_explorer": {
        "q4_alternatives": "q4_5_plus",
        "q6_what_would_change": "q6_c",
    },
    "consensus_seeker": {
        "q1_instinct_vs_research": "q1_c",
    },
    "practical_optimizer": {
        "q1_instinct_vs_research": "q1_b",
        "q4_alternatives": "q4_1_2",
    },
    "reflective_analyzer": {
        "q2_confidence": "q2_a",
        "q7_reflection": "q7_e",
    },
}


def decision_profile_payload(email="person@example.com", answers=None, decision_style="fast_mover"):
    return {
        "email": email,
        "source": "decision-style-assessment",
        "assessment_answers": answers or STYLE_SCENARIOS["fast_mover"],
        "decision_style": decision_style,
    }


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


def test_decision_profile_style_mapping_covers_all_styles():
    for key, answers in STYLE_SCENARIOS.items():
        result = derive_decision_style(answers)
        assert result["style"] == STYLES[key]
        assert result["is_fallback"] is False


def test_decision_profile_template_renders_every_style():
    for key, style in STYLES.items():
        rendered = render_decision_profile_email(
            style,
            workspace_url="https://www.jaspen.ai/account",
            unsubscribe_url="https://api.jaspen.ai/api/v1/public/leads/unsubscribe?token=test",
        )
        assert rendered["subject"] == SUBJECT
        assert PREVIEW_TEXT in rendered["html"]
        assert style["name"] in rendered["html"]
        assert style["name"] in rendered["body"]
        assert "Create or open your Jaspen workspace" in rendered["body"]
        assert "Create or open your workspace" in rendered["html"]
        assert "unsubscribe" in rendered["body"].lower()


def test_decision_profile_submission_saves_result_and_sends_email(client, db, monkeypatch):
    sent = []

    def send(msg):
        sent.append(msg)

    monkeypatch.setattr("app.routes.leads.mail.send", send)
    response = client.post(LEADS_URL, json=decision_profile_payload(email=" Person@Example.COM "))

    assert response.status_code == 201
    assert response.get_json() == {
        "ok": True,
        "delivery": "email",
        "decision_style": {"key": "fast_mover", "name": "Fast Mover"},
    }
    assert len(sent) == 1
    assert sent[0].subject == "Your Jaspen Decision Profile"
    assert sent[0].recipients == ["person@example.com"]
    assert "A closer look at how you naturally approach important decisions." in sent[0].html
    assert "Fast Mover" in sent[0].body
    assert "List-Unsubscribe" in sent[0].extra_headers

    lead = Lead.query.one()
    assert lead.normalized_email == "person@example.com"
    event = LeadAttributionEvent.query.one()
    assert event.email_delivery_requested is True
    profile = LeadDecisionProfile.query.one()
    assert profile.lead_id == lead.id
    assert profile.attribution_event_id == event.id
    assert profile.normalized_email == "person@example.com"
    assert profile.client_style_key == "fast_mover"
    assert profile.verified_style_key == "fast_mover"
    assert profile.answers["q1_instinct_vs_research"] == "q1_a"
    delivery = LeadEmailDelivery.query.one()
    assert delivery.email_type == "decision_profile_results"
    assert delivery.status == "sent"


def test_decision_profile_backend_overrides_client_style_mismatch(client, db, monkeypatch):
    monkeypatch.setattr("app.routes.leads.mail.send", lambda _msg: None)
    response = client.post(
        LEADS_URL,
        json=decision_profile_payload(
            answers=STYLE_SCENARIOS["evidence_builder"],
            decision_style="fast_mover",
        ),
    )

    assert response.status_code == 201
    assert response.get_json()["decision_style"] == {
        "key": "evidence_builder",
        "name": "Evidence Builder",
    }
    profile = LeadDecisionProfile.query.one()
    assert profile.client_style_key == "fast_mover"
    assert profile.verified_style_key == "evidence_builder"


def test_decision_profile_missing_answers_rejected_without_email(client, db, monkeypatch):
    send = Mock()
    monkeypatch.setattr("app.routes.leads.mail.send", send)
    response = client.post(
        LEADS_URL,
        json={"email": "person@example.com", "source": "decision-style-assessment"},
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "assessment_answers_required"
    assert send.call_count == 0
    assert Lead.query.count() == 0


def test_decision_profile_malformed_answers_rejected_without_email(client, db, monkeypatch):
    send = Mock()
    monkeypatch.setattr("app.routes.leads.mail.send", send)
    response = client.post(
        LEADS_URL,
        json=decision_profile_payload(answers={"q1_instinct_vs_research": "unknown_option"}),
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "assessment_option_invalid"
    assert send.call_count == 0
    assert Lead.query.count() == 0


def test_decision_profile_email_failure_preserves_data_without_success(client, db, monkeypatch):
    def fail(_msg):
        raise RuntimeError("smtp unavailable")

    monkeypatch.setattr("app.routes.leads.mail.send", fail)
    response = client.post(LEADS_URL, json=decision_profile_payload())

    assert response.status_code == 502
    assert response.get_json()["error"] == "We could not email your Decision Profile right now. Please try again."
    assert Lead.query.count() == 1
    assert LeadAttributionEvent.query.count() == 1
    assert LeadDecisionProfile.query.one().verified_style_key == "fast_mover"
    delivery = LeadEmailDelivery.query.one()
    assert delivery.email_type == "decision_profile_results"
    assert delivery.status == "failed"


def test_decision_profile_duplicate_normalized_email_preserves_each_result(client, db, monkeypatch):
    monkeypatch.setattr("app.routes.leads.mail.send", lambda _msg: None)
    first = client.post(LEADS_URL, json=decision_profile_payload(email="person@example.com"))
    second = client.post(
        LEADS_URL,
        json=decision_profile_payload(
            email=" PERSON@example.com ",
            answers=STYLE_SCENARIOS["reflective_analyzer"],
            decision_style="reflective_analyzer",
        ),
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert Lead.query.count() == 1
    assert LeadAttributionEvent.query.count() == 2
    assert LeadDecisionProfile.query.count() == 2
    assert sorted(profile.verified_style_key for profile in LeadDecisionProfile.query.all()) == [
        "fast_mover",
        "reflective_analyzer",
    ]
    assert LeadEmailDelivery.query.count() == 2
