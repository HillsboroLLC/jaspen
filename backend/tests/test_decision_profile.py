from app.models import LeadDecisionProfile, LeadDecisionProfileResponse, User


PROFILE_URL = "/api/v1/decision-profile"
LEADS_URL = "/api/v1/public/leads"

FAST_MOVER_ANSWERS = {
    "q1_instinct_vs_research": "q1_a",
    "q2_confidence": "q2_e",
    "q3_documenting": "q3_a",
    "q4_alternatives": "q4_none",
    "q5_explain_later": "q5_a",
    "q6_what_would_change": "q6_a",
    "q7_reflection": "q7_a",
}

EVIDENCE_BUILDER_ANSWERS = {
    "q1_instinct_vs_research": "q1_e",
    "q2_confidence": "q2_d",
    "q3_documenting": "q3_e",
    "q4_alternatives": "q4_3_5",
    "q5_explain_later": "q5_e",
    "q6_what_would_change": "q6_e",
    "q7_reflection": "q7_d",
}


def test_logged_in_decision_profile_empty_state(client, db, auth_headers):
    response = client.get(PROFILE_URL, headers=auth_headers)

    assert response.status_code == 200
    assert response.get_json() == {"has_profile": False, "profile": None}


def test_logged_in_decision_profile_save_serializes_responses(client, db, auth_headers):
    response = client.post(
        PROFILE_URL,
        json={"assessment_answers": FAST_MOVER_ANSWERS},
        headers=auth_headers,
    )

    assert response.status_code == 201
    data = response.get_json()
    assert data["has_profile"] is True
    assert data["profile"]["style_key"] == "fast_mover"
    assert data["profile"]["style_name"] == "Fast Mover"
    assert len(data["profile"]["responses"]) == 7
    assert data["profile"]["responses"][0]["question"] == "When an important decision comes up, where do you naturally start?"
    assert data["profile"]["responses"][0]["answer_label"] == "With my gut read of the situation"
    assert data["profile"]["sections"]["jaspen_support"]
    assert LeadDecisionProfile.query.count() == 1
    assert LeadDecisionProfileResponse.query.count() == 7


def test_logged_in_decision_profile_retake_versions_current_profile(client, db, auth_headers):
    first = client.post(PROFILE_URL, json={"assessment_answers": FAST_MOVER_ANSWERS}, headers=auth_headers)
    second = client.post(PROFILE_URL, json={"assessment_answers": EVIDENCE_BUILDER_ANSWERS}, headers=auth_headers)

    assert first.status_code == 201
    assert second.status_code == 201
    data = second.get_json()
    assert data["profile"]["style_key"] == "evidence_builder"
    assert data["profile"]["version"] == 2
    profiles = LeadDecisionProfile.query.order_by(LeadDecisionProfile.version.asc()).all()
    assert [profile.is_current for profile in profiles] == [False, True]


def test_logged_in_decision_profile_rejects_invalid_answers(client, db, auth_headers):
    response = client.post(
        PROFILE_URL,
        json={"assessment_answers": {"q1_instinct_vs_research": "unknown"}},
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "assessment_option_invalid"
    assert LeadDecisionProfile.query.count() == 0


def test_signup_links_matching_public_decision_profile(client, db, monkeypatch):
    monkeypatch.setattr("app.routes.leads.mail.send", lambda _msg: None)
    lead_response = client.post(
        LEADS_URL,
        json={
            "email": " ProfileOwner@Example.com ",
            "source": "decision-style-assessment",
            "assessment_answers": FAST_MOVER_ANSWERS,
            "decision_style": "fast_mover",
        },
    )
    assert lead_response.status_code == 201
    public_profile = LeadDecisionProfile.query.one()
    assert public_profile.user_id is None

    signup_response = client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Profile Owner",
            "email": "profileowner@example.com",
            "password": "StrongPass1",
            "plan_key": "free",
        },
    )

    assert signup_response.status_code == 201
    created = User.query.filter_by(email="profileowner@example.com").one()
    linked_profile = LeadDecisionProfile.query.one()
    assert linked_profile.user_id == created.id
    assert linked_profile.is_current is True
    assert LeadDecisionProfileResponse.query.count() == 7


def test_signup_does_not_link_different_email_profile(client, db, monkeypatch):
    monkeypatch.setattr("app.routes.leads.mail.send", lambda _msg: None)
    client.post(
        LEADS_URL,
        json={
            "email": "someoneelse@example.com",
            "source": "decision-style-assessment",
            "assessment_answers": FAST_MOVER_ANSWERS,
        },
    )

    signup_response = client.post(
        "/api/v1/auth/signup",
        json={
            "name": "New Person",
            "email": "newperson@example.com",
            "password": "StrongPass1",
            "plan_key": "free",
        },
    )

    assert signup_response.status_code == 201
    assert LeadDecisionProfile.query.one().user_id is None
