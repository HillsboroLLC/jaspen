from app.connector_store import update_connector_settings
from app.models import EmailSuppression, EnterpriseInquiry, Lead, LeadAttributionEvent, LeadDecisionProfile, LeadEmailDelivery, User


def test_admin_user_no_stripe_ids(client, admin_auth_headers, admin_user, test_user, db):
    test_user.stripe_customer_id = "cus_hidden"
    test_user.stripe_subscription_id = "sub_hidden"
    db.session.commit()

    resp = client.get("/api/v1/admin/users", headers=admin_auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    for user in data.get("users", []):
        assert "stripe_customer_id" not in user
        assert "stripe_subscription_id" not in user


def test_admin_connectors_no_credentials(client, admin_auth_headers, test_user):
    update_connector_settings(
        test_user.id,
        "jira_sync",
        {
            "connection_status": "connected",
            "auto_sync": True,
            "health_status": "healthy",
            "jira_api_token": "secret-token",
            "jira_email": "hidden@example.com",
            "jira_base_url": "https://example.atlassian.net",
        },
    )

    resp = client.get(f"/api/v1/admin/users/{test_user.id}/connectors", headers=admin_auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    for conn in data.get("connectors", []):
        assert "jira_api_token" not in conn
        assert "jira_email" not in conn
        assert "jira_base_url" not in conn


def test_master_analytics_support_only(client, admin_auth_headers, auth_headers, db):
    lead = Lead(email="lead@example.com", normalized_email="lead@example.com", source="decision-scorecard", utm_source="linkedin")
    db.session.add(lead)
    db.session.flush()
    db.session.add(LeadAttributionEvent(lead_id=lead.id, source="decision-scorecard", utm_source="linkedin"))
    db.session.commit()

    allowed = client.get("/api/v1/admin/master/analytics", headers=admin_auth_headers)
    assert allowed.status_code == 200
    data = allowed.get_json()
    assert data["metrics"]["emails_captured"] == 1
    assert data["metrics"]["linkedin_visitors"] == 1

    denied = client.get("/api/v1/admin/master/analytics", headers=auth_headers)
    assert denied.status_code == 403


def test_master_errors_support_only_for_global_admin(client, admin_auth_headers, app, db):
    other_admin = User(
        email="other-admin@example.com",
        name="Other Admin",
        password_hash="x",
        subscription_plan="enterprise",
    )
    db.session.add(other_admin)
    db.session.commit()
    app.config["ADMIN_EMAILS"] = "support@jaspen.ai,other-admin@example.com"

    from flask_jwt_extended import create_access_token
    with app.app_context():
        other_headers = {"Authorization": f"Bearer {create_access_token(identity=str(other_admin.id))}"}

    allowed = client.get("/api/v1/admin/master/errors", headers=admin_auth_headers)
    assert allowed.status_code == 200
    assert "sections" in allowed.get_json()

    denied = client.get("/api/v1/admin/master/errors", headers=other_headers)
    assert denied.status_code == 403


def test_master_leads_support_only_and_includes_safe_lead_summary(client, admin_auth_headers, auth_headers, db):
    lead = Lead(
        email="Lead@Example.com",
        normalized_email="lead@example.com",
        source="decision-style-assessment",
        first_name="Lead",
        last_name="Person",
        company="Example Co",
        utm_source="linkedin",
    )
    db.session.add(lead)
    db.session.flush()
    db.session.add(LeadAttributionEvent(
        lead_id=lead.id,
        source="decision-style-assessment",
        utm_source="linkedin",
        marketing_opt_in=True,
        email_delivery_requested=True,
    ))
    db.session.add(LeadAttributionEvent(
        lead_id=lead.id,
        source="decision-planning-toolkit",
        utm_source="linkedin",
        marketing_opt_in=False,
        email_delivery_requested=True,
    ))
    enterprise_event = LeadAttributionEvent(
        lead_id=lead.id,
        source="enterprise-investment-calculator",
        marketing_opt_in=False,
        email_delivery_requested=False,
    )
    db.session.add(enterprise_event)
    db.session.flush()
    db.session.add(EnterpriseInquiry(
        lead_id=lead.id,
        attribution_event_id=enterprise_event.id,
        participants=12,
        teams=2,
        usage="high",
        requirements_json='["sso_saml"]',
        hourly_cost=112.5,
        recommendation="Enterprise Strategic",
        annual_low=72000,
        annual_high=96000,
    ))
    db.session.add(LeadDecisionProfile(
        lead_id=lead.id,
        email="lead@example.com",
        normalized_email="lead@example.com",
        source="decision-style-assessment",
        answers={"pace": "fast"},
        verified_style_key="fast_mover",
        style_name="Fast Mover",
        affinity={"fast_mover": 2},
    ))
    db.session.add(LeadEmailDelivery(
        lead_id=lead.id,
        email="lead@example.com",
        email_type="decision_profile",
        status="sent",
    ))
    db.session.add(EmailSuppression(
        email="lead@example.com",
        normalized_email="lead@example.com",
        scope="marketing",
        reason="unsubscribe",
    ))
    db.session.commit()

    allowed = client.get("/api/v1/admin/master/leads?q=lead@example.com", headers=admin_auth_headers)
    assert allowed.status_code == 200
    data = allowed.get_json()
    assert data["pagination"]["total"] == 1
    assert data["leads"][0]["email"] == "Lead@Example.com"
    assert data["leads"][0]["name"] == "Lead Person"
    assert data["leads"][0]["decision_profile"]["style_name"] == "Fast Mover"
    assert data["leads"][0]["latest_email"]["status"] == "sent"
    assert len(data["leads"][0]["interactions"]["captures"]) == 3
    assert len(data["leads"][0]["interactions"]["emails"]) == 1
    assert data["leads"][0]["interactions"]["estimates"][0]["annual_low"] == 72000
    assert data["leads"][0]["interactions"]["estimates"][0]["requirements"] == ["sso_saml"]
    assert data["leads"][0]["lead_tools"]["decision_profile"]["used"] is True
    assert data["leads"][0]["lead_tools"]["decision_profile"]["count"] == 1
    assert data["leads"][0]["lead_tools"]["decision_planning_toolkit"]["used"] is True
    assert data["leads"][0]["lead_tools"]["decision_planning_toolkit"]["count"] == 1
    assert data["leads"][0]["lead_tools"]["enterprise_inquiry"]["used"] is True
    assert data["leads"][0]["suppression"]["reason"] == "unsubscribe"
    assert data["leads"][0]["subscription_preferences"]["marketing"]["subscribed"] is False
    assert data["leads"][0]["subscription_preferences"]["updates"]["subscribed"] is True
    assert data["leads"][0]["contact_status"] == "limited"
    assert data["leads"][0]["non_transactional_contact_blocked"] is False
    assert data["leads"][0]["account"]["exists"] is False
    assert "answers" not in data["leads"][0]["decision_profile"]

    denied = client.get("/api/v1/admin/master/leads", headers=auth_headers)
    assert denied.status_code == 403


def test_master_admin_can_delete_one_email_record_without_deleting_similar_contact(
    client, admin_auth_headers, db
):
    typo = Lead(
        email="lydia@hillsbrorow.com",
        normalized_email="lydia@hillsbrorow.com",
        source="enterprise-investment-calculator",
        first_name="Lydia",
        last_name="Bailey",
        company="Hillsboro Row LLC",
    )
    correct = Lead(
        email="lydia@hillsbororow.com",
        normalized_email="lydia@hillsbororow.com",
        source="enterprise-investment-calculator",
        first_name="Lydia",
        last_name="Bailey",
        company="Hillsboro Row LLC",
    )
    db.session.add_all([typo, correct])
    db.session.flush()
    event = LeadAttributionEvent(lead_id=typo.id, source="enterprise-investment-calculator")
    db.session.add(event)
    db.session.flush()
    db.session.add(EnterpriseInquiry(
        lead_id=typo.id,
        attribution_event_id=event.id,
        participants=10,
        teams=1,
        usage="standard",
        recommendation="Enterprise",
        annual_low=72000,
    ))
    db.session.commit()
    typo_id = typo.id
    correct_id = correct.id

    response = client.delete(f"/api/v1/admin/master/leads/{typo_id}", headers=admin_auth_headers)
    assert response.status_code == 200
    assert response.get_json()["records_deleted"] == 1
    assert db.session.get(Lead, typo_id) is None
    assert db.session.get(Lead, correct_id) is not None
    assert EnterpriseInquiry.query.filter_by(lead_id=typo_id).count() == 0
