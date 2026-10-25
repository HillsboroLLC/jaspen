from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import connector_store
from app.connector_store import append_sync_audit_event, update_connector_settings
from app.models import ConnectorSyncLog

def test_connector_status_returns_catalog(client, auth_headers):
    resp = client.get("/api/v1/connectors/status", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert "connectors" in data


def _store_connector_status(user_id, **updates):
    state = connector_store.load_connector_state(user_id)
    connector = state.setdefault("connectors", {}).setdefault("jira_sync", {})
    connector.update(updates)
    connector_store.save_connector_state(user_id, state)


def _jira_status(client, auth_headers):
    response = client.get("/api/v1/connectors/status", headers=auth_headers)
    assert response.status_code == 200
    return next(item for item in response.get_json()["connectors"] if item["id"] == "jira_sync")


def test_connector_status_reports_fresh_and_stale_confirmations(client, auth_headers, test_user):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    fresh_success = now - timedelta(days=2)
    older_verification = now - timedelta(days=3)
    _store_connector_status(
        test_user.id,
        connection_status="connected",
        lifecycle_status="connected",
        last_success_at=fresh_success.isoformat(),
        last_verified_at=older_verification.isoformat(),
    )

    fresh = _jira_status(client, auth_headers)

    assert fresh["freshness"] == "confirmed"
    assert fresh["last_confirmed_at"] == fresh_success.isoformat().replace("+00:00", "Z")

    stale_success = now - timedelta(days=8)
    _store_connector_status(
        test_user.id,
        last_success_at=stale_success.isoformat(),
        last_verified_at=None,
    )

    stale = _jira_status(client, auth_headers)

    assert stale["freshness"] == "unconfirmed"
    assert stale["last_confirmed_at"] == stale_success.isoformat().replace("+00:00", "Z")


def test_connector_status_reports_never_confirmed_problem_and_disconnected_states(client, auth_headers, test_user):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    _store_connector_status(
        test_user.id,
        connection_status="connected",
        lifecycle_status="connected",
        last_success_at=None,
        last_verified_at=None,
    )
    never = _jira_status(client, auth_headers)
    assert never["freshness"] == "unconfirmed"
    assert never["last_confirmed_at"] is None

    _store_connector_status(
        test_user.id,
        lifecycle_status="degraded",
        last_success_at=now.isoformat(),
    )
    degraded = _jira_status(client, auth_headers)
    assert degraded["freshness"] == "degraded"
    assert degraded["last_confirmed_at"] == now.isoformat().replace("+00:00", "Z")

    _store_connector_status(
        test_user.id,
        connection_status="disconnected",
        lifecycle_status="disconnected",
    )
    disconnected = _jira_status(client, auth_headers)
    assert disconnected["freshness"] == "disconnected"


def test_connector_status_respects_fresh_window_without_writing_settings(client, auth_headers, test_user, app, monkeypatch):
    monkeypatch.setitem(app.config, "CONNECTOR_FRESH_DAYS", 2)
    confirmed_at = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=3)
    _store_connector_status(
        test_user.id,
        connection_status="connected",
        lifecycle_status="connected",
        last_success_at=confirmed_at.isoformat(),
        last_verified_at=None,
    )
    settings_path = Path(connector_store._connector_file(test_user.id))
    before = settings_path.read_bytes()

    connector = _jira_status(client, auth_headers)

    assert connector["freshness"] == "unconfirmed"
    assert settings_path.read_bytes() == before


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
