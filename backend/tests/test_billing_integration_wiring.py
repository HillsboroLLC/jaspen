"""I1-I5 integration: the shared routes answer a modern organization through its families."""

from datetime import timedelta

from app import billing_cutover as bc
from app import billing_runtime_funding as funding
from tests.test_billing_cutover import _establish, _org

ALL = "identity,financial_events,credit_funding,ai_reservation,readers"


def _modern_free_org(app, session, user):
    org = _org(session, user)
    user.active_organization_id = org.id
    session.commit()
    _establish(session, org, config=bc.load_cutover_config({bc.SETTING: ALL}))
    session.commit()
    funding.define_test_catalog(session, approver_user_id=user.id, app_config=app.config,
                                effective_at=bc._database_now(session) - timedelta(days=400))
    session.commit()
    funding.allocate_free(session, bc.modern_context(session, family="credit_funding", organization_id=org.id))
    session.commit()
    return org


def test_billing_status_answers_a_modern_organization_from_the_readers_family(
        app, client, db, test_user, auth_headers, monkeypatch):
    monkeypatch.setenv(bc.SETTING, ALL)
    _modern_free_org(app, db.session, test_user)
    response = client.get("/api/v1/billing/status", headers=auth_headers)
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["billing_model"] == "modern" and body["plan_key"] == "free"
    assert body["credits_remaining"] == 300  # the Free lot, 300,000 ledger units, in displayed credits
    assert isinstance(body["tool_entitlements"], list)


def test_billing_status_answers_503_while_a_modern_organizations_readers_family_is_off(
        app, client, db, test_user, auth_headers, monkeypatch):
    monkeypatch.setenv(bc.SETTING, ALL)
    _modern_free_org(app, db.session, test_user)
    monkeypatch.setenv(bc.SETTING, "identity,financial_events,credit_funding,ai_reservation")
    response = client.get("/api/v1/billing/status", headers=auth_headers)
    assert response.status_code == 503 and response.get_json()["error"] == "billing_family_disabled"


def test_a_legacy_account_keeps_the_legacy_status_body(client, db, test_user, auth_headers):
    response = client.get("/api/v1/billing/status", headers=auth_headers)
    assert response.status_code == 200
    assert "billing_model" not in response.get_json()
