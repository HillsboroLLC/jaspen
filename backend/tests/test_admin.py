from app.connector_store import update_connector_settings
from app.models import Lead, LeadAttributionEvent, User


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
