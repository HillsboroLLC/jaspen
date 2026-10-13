from datetime import datetime, timedelta

from app.connector_store import append_sync_audit_event, update_connector_settings
from app.models import ConnectorSyncLog

def test_connector_status_returns_catalog(client, auth_headers):
    resp = client.get("/api/v1/connectors/status", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "connectors" in data


def test_jira_webhook_requires_configured_secret(client, app):
    app.config["JIRA_WEBHOOK_SECRET"] = ""
    resp = client.post("/api/v1/connectors/jira/webhook", json={})
    assert resp.status_code == 503


def test_jira_webhook_rejects_invalid_secret(client, app):
    app.config["JIRA_WEBHOOK_SECRET"] = "expected-secret"
    resp = client.post(
        "/api/v1/connectors/jira/webhook",
        json={},
        headers={"X-Webhook-Secret": "wrong-secret"},
    )
    assert resp.status_code == 401


def test_connector_activity_combines_portfolio_and_plan_sync_events(client, auth_headers, db, test_user):
    older = datetime.utcnow() - timedelta(minutes=5)
    newer = datetime.utcnow()
    db.session.add_all([
        ConnectorSyncLog(
            user_id=test_user.id, connector_id="jira_sync", thread_id="thread-1",
            action="pm_sync", status="success", items_synced=2, created_at=older,
        ),
        ConnectorSyncLog(
            user_id=test_user.id, connector_id="jira_sync", thread_id=None,
            action="context_summary", status="success", items_synced=3, created_at=newer,
        ),
    ])
    db.session.commit()

    response = client.get("/api/v1/connectors/jira_sync/audit?limit=20", headers=auth_headers)

    assert response.status_code == 200
    events = response.get_json()["events"]
    assert [event["action"] for event in events[:2]] == ["context_summary", "pm_sync"]
    assert events[0]["items_synced"] == 3
    assert events[1]["thread_id"] == "thread-1"
    assert all(event["timestamp"].endswith("Z") for event in events[:2])


def test_connector_activity_deduplicates_store_and_persisted_log(client, auth_headers, test_user):
    append_sync_audit_event(
        test_user.id, "jira_sync", action="config_update", status="success",
        message="Jira connection saved", metadata={"connected": True},
    )

    response = client.get("/api/v1/connectors/jira_sync/audit?limit=20", headers=auth_headers)

    assert response.status_code == 200
    matching = [event for event in response.get_json()["events"] if event["action"] == "config_update"]
    assert len(matching) == 1


def test_connector_status_normalizes_naive_utc_timestamps(client, auth_headers, test_user):
    update_connector_settings(test_user.id, "jira_sync", {
        "last_verified_at": "2026-10-13T01:26:45",
        "last_sync_at": "2026-10-13T01:20:00",
    })

    response = client.get("/api/v1/connectors/status", headers=auth_headers)

    assert response.status_code == 200
    jira = next(item for item in response.get_json()["connectors"] if item["id"] == "jira_sync")
    assert jira["last_verified_at"] == "2026-10-13T01:26:45Z"
    assert jira["last_sync_at"] == "2026-10-13T01:20:00Z"
