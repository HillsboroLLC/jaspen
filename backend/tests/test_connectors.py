import importlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import connector_store
from app.connector_store import append_sync_audit_event, mark_connector_sync_result, update_connector_settings
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


def _connector_status(client, auth_headers, connector_id):
    response = client.get("/api/v1/connectors/status", headers=auth_headers)
    assert response.status_code == 200
    return next(item for item in response.get_json()["connectors"] if item["id"] == connector_id)


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


def test_dual_purpose_connector_reports_data_context_freshness_separately(
    client, auth_headers, test_user,
):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    execution_success = now - timedelta(hours=1)
    data_read = now - timedelta(days=8)
    _store_connector_status(
        test_user.id,
        connection_status="connected",
        lifecycle_status="connected",
        last_success_at=execution_success.isoformat(),
        last_verified_at=execution_success.isoformat(),
        data_context_verified_at=data_read.isoformat(),
    )

    jira = _jira_status(client, auth_headers)

    assert jira["freshness"] == "confirmed"
    assert jira["last_confirmed_at"] == execution_success.isoformat().replace("+00:00", "Z")
    assert jira["data_context_freshness"] == "unconfirmed"
    assert jira["data_context_last_confirmed_at"] == data_read.isoformat().replace("+00:00", "Z")


def test_failed_jira_portfolio_refresh_unconfirms_data_context_until_next_success(
    client, auth_headers, test_user, monkeypatch,
):
    portfolio = importlib.import_module("app.jira_portfolio")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    confirmed_at = now - timedelta(days=2)
    cached = {
        "fetched_at": confirmed_at.isoformat().replace("+00:00", "Z"),
        "portfolio": {"project_count": 1},
        "projects": [{"project_key": "DATA"}],
        "provenance": {"source": "connector"},
    }
    _store_connector_status(
        test_user.id,
        connection_status="connected",
        lifecycle_status="connected",
        last_verified_at=confirmed_at.isoformat(),
        data_context_verified_at=confirmed_at.isoformat(),
        jira_base_url="https://synthetic.atlassian.test",
        jira_email="dev@example.test",
        jira_api_token="synthetic-token",
        jira_data_enabled=True,
        jira_portfolio_snapshot=cached,
        jira_data_last_refresh_failed=False,
    )

    assert _jira_status(client, auth_headers)["data_context_freshness"] == "confirmed"

    monkeypatch.setattr(
        portfolio,
        "_list_projects",
        lambda *_: (_ for _ in ()).throw(RuntimeError("HTTP 429")),
    )
    failed = portfolio.refresh_portfolio(test_user.id, force=True, now=now)

    assert failed["refresh_failed"] is True
    assert _jira_status(client, auth_headers)["data_context_freshness"] == "unconfirmed"

    monkeypatch.setattr(portfolio, "_list_projects", lambda *_: [])
    monkeypatch.setattr(
        portfolio,
        "_discover_fields",
        lambda *_: {"story_points": None, "flagged": None, "sprint": None, "start_date": None},
    )
    portfolio.refresh_portfolio(test_user.id, force=True, now=now + timedelta(minutes=1))

    refreshed = connector_store.get_connector_settings(test_user.id, "jira_sync")
    assert refreshed["jira_data_last_refresh_failed"] is False
    assert _jira_status(client, auth_headers)["data_context_freshness"] == "confirmed"


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


def test_data_context_check_ignores_incomplete_jira_execution_config_and_is_throttled(
    client, auth_headers, test_user, monkeypatch,
):
    connector_routes = importlib.import_module("app.routes.connectors")
    stale = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=8)
    _store_connector_status(
        test_user.id,
        connection_status="connected",
        lifecycle_status="connected",
        last_verified_at=stale.isoformat(),
        jira_base_url="https://synthetic.atlassian.test",
        jira_email="dev@example.test",
        jira_api_token="synthetic-token",
        jira_project_key="",
        jira_issue_type="",
        jira_field_mapping={},
        jira_data_enabled=True,
        jira_data_project_scope="selected",
        jira_data_selected_projects=["DATA"],
    )
    calls = []
    monkeypatch.setattr(
        connector_routes,
        "refresh_portfolio",
        lambda user_id, force=False: calls.append((user_id, force)) or {"stale": False, "refresh_failed": False},
    )

    first = client.get("/api/v1/connectors/jira_sync/data-context/check", headers=auth_headers)
    second = client.get("/api/v1/connectors/jira_sync/data-context/check", headers=auth_headers)

    assert first.status_code == 200
    assert first.get_json()["status"] == "confirmed"
    assert second.status_code == 200
    assert second.get_json()["throttled"] is True
    assert calls == [(test_user.id, True)]
    settings = connector_store.get_connector_settings(test_user.id, "jira_sync")
    assert settings["jira_project_key"] == ""
    assert settings["jira_issue_type"] == ""
    assert settings["jira_field_mapping"] == {}
    assert settings["jira_data_selected_projects"] == ["DATA"]
    assert settings["data_context_verified_at"]
    assert settings["last_verified_at"] == settings["data_context_verified_at"]
    assert settings["last_sync_at"] is None
    assert settings["last_success_at"] is None

    jira = _jira_status(client, auth_headers)
    assert jira["freshness"] == "confirmed"
    assert jira["data_context_freshness"] == "confirmed"


def test_jira_context_summary_updates_sync_health_for_success_and_failure(
    client, auth_headers, test_user, monkeypatch,
):
    connector_routes = importlib.import_module("app.routes.connectors")
    successful_snapshot = {
        "portfolio": {"project_count": 1, "blocked_count": 0},
        "evidence": [],
        "refresh_failed": False,
    }
    monkeypatch.setattr(connector_routes, "refresh_portfolio", lambda *_args, **_kwargs: successful_snapshot)

    success = client.get("/api/v1/connectors/jira/context/summary", headers=auth_headers)

    assert success.status_code == 200
    settings = connector_store.get_connector_settings(test_user.id, "jira_sync")
    assert settings["last_sync_result"] == "success"
    assert settings["health_status"] == "healthy"
    assert settings["consecutive_failures"] == 0
    assert settings["last_success_at"]
    assert settings["last_verified_at"]

    failed_snapshot = {
        **successful_snapshot,
        "refresh_failed": True,
        "refresh_error": {"message": "synthetic Jira read failed"},
    }
    monkeypatch.setattr(connector_routes, "refresh_portfolio", lambda *_args, **_kwargs: failed_snapshot)

    failed = client.get("/api/v1/connectors/jira/context/summary", headers=auth_headers)

    assert failed.status_code == 200
    settings = connector_store.get_connector_settings(test_user.id, "jira_sync")
    assert settings["last_sync_result"] == "failed"
    assert settings["health_status"] == "degraded"
    assert settings["consecutive_failures"] == 1
    assert settings["last_error_at"]
    assert settings["last_error_message"] == "synthetic Jira read failed"


def test_failed_jira_data_context_check_does_not_change_plan_sync_state(
    client, auth_headers, test_user, monkeypatch,
):
    connector_routes = importlib.import_module("app.routes.connectors")
    stale = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=8)
    original = {
        "connection_status": "connected",
        "lifecycle_status": "connected",
        "last_verified_at": stale.isoformat(),
        "data_context_verified_at": stale.isoformat(),
        "jira_base_url": "https://synthetic.atlassian.test",
        "jira_email": "dev@example.test",
        "jira_api_token": "synthetic-token",
        "jira_project_key": "EXEC",
        "jira_issue_type": "Task",
        "jira_field_mapping": {"title": "summary"},
        "jira_data_enabled": True,
        "jira_data_project_scope": "selected",
        "jira_data_selected_projects": ["DATA"],
    }
    _store_connector_status(test_user.id, **original)

    def fail_read(*_args, **_kwargs):
        raise RuntimeError("synthetic data read failed")

    monkeypatch.setattr(connector_routes, "refresh_portfolio", fail_read)
    response = client.get("/api/v1/connectors/jira_sync/data-context/check", headers=auth_headers)
    throttled = client.get("/api/v1/connectors/jira_sync/data-context/check", headers=auth_headers)

    assert response.status_code == 200
    assert response.get_json()["status"] == "failed"
    assert throttled.status_code == 200
    assert throttled.get_json()["status"] == "failed"
    assert throttled.get_json()["throttled"] is True
    settings = connector_store.get_connector_settings(test_user.id, "jira_sync")
    for field in (
        "connection_status", "lifecycle_status", "jira_project_key", "jira_issue_type",
        "jira_field_mapping", "jira_data_project_scope", "jira_data_selected_projects",
    ):
        assert settings[field] == original[field]
    assert settings["last_verified_at"] == original["last_verified_at"]
    assert settings["data_context_verified_at"] == original["data_context_verified_at"]


def test_salesforce_data_context_failure_uses_safe_reason_and_throttles_it(
    client, auth_headers, test_user, monkeypatch, caplog,
):
    connector_routes = importlib.import_module("app.routes.connectors")
    update_connector_settings(test_user.id, "salesforce_insights", {
        "connection_status": "connected",
        "lifecycle_status": "connected",
    })
    raw_error = "HTTP 420: {'raw': '<!DOCTYPE HTML><html>provider failure</html>'}"

    def fail_read(*_args, **_kwargs):
        raise RuntimeError(raw_error)

    monkeypatch.setattr(connector_routes, "fetch_pipeline_summary", fail_read)

    response = client.get(
        "/api/v1/connectors/salesforce_insights/data-context/check", headers=auth_headers
    )
    throttled = client.get(
        "/api/v1/connectors/salesforce_insights/data-context/check", headers=auth_headers
    )

    assert response.status_code == 200
    assert response.get_json()["error"] == "Salesforce returned an error (HTTP 420)."
    assert "<" not in response.get_json()["error"]
    assert "DOCTYPE" not in response.get_json()["error"]
    assert throttled.status_code == 200
    assert throttled.get_json()["throttled"] is True
    assert throttled.get_json()["error"] == response.get_json()["error"]
    audit = ConnectorSyncLog.query.filter_by(
        user_id=test_user.id,
        connector_id="salesforce_insights",
        action="data_context_check",
    ).order_by(ConnectorSyncLog.created_at.desc()).first()
    assert audit.error_message == response.get_json()["error"]
    assert raw_error in caplog.text


def test_snowflake_data_context_failure_hides_host_from_response_and_audit(
    client, auth_headers, test_user, monkeypatch,
):
    connector_routes = importlib.import_module("app.routes.connectors")
    update_connector_settings(test_user.id, "snowflake_insights", {
        "connection_status": "connected",
        "lifecycle_status": "connected",
        "snowflake_table_allowlist": ["analytics.context"],
    })
    account_host = "customer-account.us-east-1.snowflakecomputing.com"

    def fail_read(*_args, **_kwargs):
        raise RuntimeError(f"{account_host}: trial account is suspended")

    monkeypatch.setattr(connector_routes, "run_allowlisted_query", fail_read)

    response = client.get(
        "/api/v1/connectors/snowflake_insights/data-context/check", headers=auth_headers
    )

    assert response.status_code == 200
    assert response.get_json()["error"] == "Snowflake account is unavailable or suspended."
    assert account_host not in response.get_json()["error"]
    audit = ConnectorSyncLog.query.filter_by(
        user_id=test_user.id,
        connector_id="snowflake_insights",
        action="data_context_check",
    ).order_by(ConnectorSyncLog.created_at.desc()).first()
    assert audit.error_message == response.get_json()["error"]
    assert account_host not in audit.error_message


@pytest.mark.parametrize(
    ("connector_id", "message"),
    [
        ("jira_sync", "Jira data analysis is turned off."),
        ("snowflake_insights", "Snowflake table allowlist is empty."),
    ],
)
def test_safe_data_context_failure_reason_preserves_jaspen_messages(
    connector_id, message,
):
    connector_routes = importlib.import_module("app.routes.connectors")

    assert connector_routes._safe_data_context_failure_reason(
        connector_id, RuntimeError(message)
    ) == message


def test_safe_data_context_failure_reason_caps_long_exceptions():
    connector_routes = importlib.import_module("app.routes.connectors")

    reason = connector_routes._safe_data_context_failure_reason(
        "smartsheet_sync", RuntimeError("x" * 5000)
    )

    assert reason == "Smartsheet data could not be read."
    assert len(reason) <= 200


def test_safe_data_context_failure_reason_uses_jira_public_message():
    connector_routes = importlib.import_module("app.routes.connectors")

    reason = connector_routes._safe_data_context_failure_reason(
        "jira_sync", RuntimeError("HTTP 401 from private-jira-host.example.test")
    )

    assert reason == "Your saved Jira connection no longer works. Reconnect Jira to continue."
    assert "private-jira-host" not in reason


def test_generate_ideas_connector_fetch_failure_uses_safe_labelled_reason(
    client, auth_headers, monkeypatch, caplog,
):
    connector_routes = importlib.import_module("app.routes.connectors")
    provider_host = "customer-account.provider.example.test"
    raw_error = f"HTTP 420 from {provider_host}: <!DOCTYPE HTML><html>failed</html>"

    def fail_fetch(*_args, **_kwargs):
        raise RuntimeError(raw_error)

    monkeypatch.setattr(connector_routes, "fetch_pipeline_summary", fail_fetch)

    response = client.post(
        "/api/v1/connectors/generate-ideas",
        headers=auth_headers,
        json={"connector_id": "salesforce_insights"},
    )

    assert response.status_code == 400
    error = response.get_json()["error"]
    assert error == "Salesforce returned an error (HTTP 420)."
    assert "<" not in error
    assert "DOCTYPE" not in error
    assert provider_host not in error
    assert raw_error in caplog.text


def test_generate_ideas_ai_provider_failure_returns_safe_message(
    client, auth_headers, monkeypatch, caplog,
):
    connector_routes = importlib.import_module("app.routes.connectors")
    raw_error = "provider SDK failed at private-provider.example.test"
    monkeypatch.setattr(
        connector_routes,
        "fetch_pipeline_summary",
        lambda *_args, **_kwargs: {"summary": {"opportunity_count": 3}},
    )

    def fail_ai(*_args, **_kwargs):
        raise RuntimeError(raw_error)

    monkeypatch.setattr(connector_routes, "execute_customer_text_operation", fail_ai)

    response = client.post(
        "/api/v1/connectors/generate-ideas",
        headers=auth_headers,
        json={"connector_id": "salesforce_insights"},
    )

    assert response.status_code == 500
    assert response.get_json() == {
        "error": "Jaspen couldn't generate ideas from this data. Please try again."
    }
    assert raw_error in caplog.text


def test_generate_ideas_invalid_ai_json_returns_safe_message(
    client, auth_headers, monkeypatch,
):
    connector_routes = importlib.import_module("app.routes.connectors")
    monkeypatch.setattr(
        connector_routes,
        "fetch_pipeline_summary",
        lambda *_args, **_kwargs: {"summary": {"opportunity_count": 3}},
    )
    monkeypatch.setattr(
        connector_routes,
        "execute_customer_text_operation",
        lambda *_args, **_kwargs: ("not valid JSON", {}, {}),
    )

    response = client.post(
        "/api/v1/connectors/generate-ideas",
        headers=auth_headers,
        json={"connector_id": "salesforce_insights"},
    )

    assert response.status_code == 500
    error = response.get_json()["error"]
    assert error == "Jaspen couldn't generate ideas from this data. Please try again."
    assert "Expecting value" not in error


def test_generate_ideas_preserves_payment_required_response(
    client, auth_headers, monkeypatch,
):
    connector_routes = importlib.import_module("app.routes.connectors")
    monkeypatch.setattr(
        connector_routes,
        "fetch_pipeline_summary",
        lambda *_args, **_kwargs: {"summary": {"opportunity_count": 3}},
    )
    payment_payload = {"error": "Thinking Power exhausted", "code": "payment_required"}

    def require_payment(*_args, **_kwargs):
        raise connector_routes.AIOperationPaymentRequired(payment_payload)

    monkeypatch.setattr(connector_routes, "execute_customer_text_operation", require_payment)

    response = client.post(
        "/api/v1/connectors/generate-ideas",
        headers=auth_headers,
        json={"connector_id": "salesforce_insights"},
    )

    assert response.status_code == 402
    assert response.get_json() == payment_payload


def test_generate_ideas_preserves_unsupported_connector_response(client, auth_headers):
    response = client.post(
        "/api/v1/connectors/generate-ideas",
        headers=auth_headers,
        json={"connector_id": "unsupported_insights"},
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "error": "Connector 'unsupported_insights' does not support idea generation yet."
    }


@pytest.mark.parametrize("connector_id", ["jira_sync", "smartsheet_sync"])
def test_execution_result_used_by_plan_sync_import_and_webhooks_does_not_verify_data_context(
    client, auth_headers, test_user, connector_id,
):
    update_connector_settings(test_user.id, connector_id, {
        "connection_status": "connected",
        "lifecycle_status": "connected",
        "data_context_verified_at": None,
    })

    mark_connector_sync_result(test_user.id, connector_id, "success")

    settings = connector_store.get_connector_settings(test_user.id, connector_id)
    assert settings["last_sync_result"] == "success"
    assert settings["last_sync_at"]
    assert settings["last_success_at"]
    assert settings["last_verified_at"]
    assert settings["data_context_verified_at"] is None
    status = _connector_status(client, auth_headers, connector_id)
    assert status["freshness"] == "confirmed"
    assert status["data_context_freshness"] == "unconfirmed"


def test_jira_credential_health_and_setup_checks_do_not_verify_data_context(
    client, auth_headers, test_user, monkeypatch,
):
    connector_routes = importlib.import_module("app.routes.connectors")
    update_connector_settings(test_user.id, "jira_sync", {
        "connection_status": "connected",
        "lifecycle_status": "connected",
        "jira_base_url": "https://synthetic.atlassian.test",
        "jira_email": "dev@example.test",
        "jira_api_token": "synthetic-token",
        "jira_project_key": "EXEC",
        "data_context_verified_at": None,
    })
    monkeypatch.setattr(
        connector_routes,
        "jira_check_connection",
        lambda *_args, **_kwargs: {"ok": True},
    )

    health = client.get("/api/v1/connectors/jira_sync/health", headers=auth_headers)
    setup = client.get("/api/v1/connectors/jira_sync/check", headers=auth_headers)

    assert health.status_code == 200
    assert setup.status_code == 200, setup.get_json()
    settings = connector_store.get_connector_settings(test_user.id, "jira_sync")
    assert settings["last_verified_at"]
    assert settings["data_context_verified_at"] is None
    assert _jira_status(client, auth_headers)["data_context_freshness"] == "unconfirmed"


def test_salesforce_setup_check_verifies_with_minimal_data_read(
    client, auth_headers, test_user, monkeypatch,
):
    connector_routes = importlib.import_module("app.routes.connectors")
    update_connector_settings(test_user.id, "salesforce_insights", {
        "connection_status": "disconnected",
        "lifecycle_status": "configured",
        "last_verified_at": None,
        "salesforce_auth_base_url": "https://login.salesforce.test",
        "salesforce_instance_url": "https://synthetic.salesforce.test",
        "salesforce_client_id": "synthetic-client-id",
        "salesforce_client_secret": "synthetic-client-secret",
    })
    calls = []
    monkeypatch.setattr(
        connector_routes,
        "fetch_pipeline_summary",
        lambda *args, **kwargs: calls.append((args, kwargs)) or {"records": []},
    )

    response = client.get(
        "/api/v1/connectors/salesforce_insights/check", headers=auth_headers
    )

    assert response.status_code == 200, response.get_json()
    assert calls == [((test_user.id,), {"lookback_days": 1, "max_records": 1})]
    settings = connector_store.get_connector_settings(test_user.id, "salesforce_insights")
    assert settings["connection_status"] == "connected"
    assert settings["lifecycle_status"] == "connected"
    assert settings["last_verified_at"]
    assert _connector_status(client, auth_headers, "salesforce_insights")["freshness"] == "confirmed"


def test_salesforce_setup_check_failed_read_does_not_verify_data_chip(
    client, auth_headers, test_user, monkeypatch,
):
    connector_routes = importlib.import_module("app.routes.connectors")
    update_connector_settings(test_user.id, "salesforce_insights", {
        "connection_status": "connected",
        "lifecycle_status": "connected",
        "last_verified_at": None,
        "salesforce_auth_base_url": "https://login.salesforce.test",
        "salesforce_instance_url": "https://synthetic.salesforce.test",
        "salesforce_client_id": "synthetic-client-id",
        "salesforce_client_secret": "synthetic-client-secret",
    })

    def fail_read(*_args, **_kwargs):
        raise RuntimeError("synthetic Salesforce read failed")

    monkeypatch.setattr(connector_routes, "fetch_pipeline_summary", fail_read)

    response = client.get(
        "/api/v1/connectors/salesforce_insights/check", headers=auth_headers
    )

    assert response.status_code == 503
    assert response.get_json()["lifecycle_status"] == "degraded"
    settings = connector_store.get_connector_settings(test_user.id, "salesforce_insights")
    assert settings["connection_status"] == "disconnected"
    assert settings["lifecycle_status"] == "degraded"
    assert settings["last_verified_at"] is None
    assert _connector_status(client, auth_headers, "salesforce_insights")["freshness"] != "confirmed"


def test_smartsheet_data_context_read_updates_analysis_and_data_sources_freshness(
    client, auth_headers, test_user, monkeypatch,
):
    connector_routes = importlib.import_module("app.routes.connectors")
    update_connector_settings(test_user.id, "smartsheet_sync", {
        "connection_status": "connected",
        "lifecycle_status": "connected",
        "last_verified_at": None,
        "data_context_verified_at": None,
        "smartsheet_base_url": "https://synthetic.smartsheet.test",
        "smartsheet_sheet_id": "sheet-1",
        "smartsheet_api_token": "synthetic-token",
        "smartsheet_data_enabled": True,
    })
    monkeypatch.setattr(connector_routes, "smartsheet_get_sheet", lambda *_args, **_kwargs: {"id": "sheet-1"})

    response = client.get(
        "/api/v1/connectors/smartsheet_sync/data-context/check", headers=auth_headers
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "confirmed"
    settings = connector_store.get_connector_settings(test_user.id, "smartsheet_sync")
    assert settings["data_context_verified_at"]
    assert settings["last_verified_at"] == settings["data_context_verified_at"]
    assert settings["last_sync_at"] is None
    assert settings["last_success_at"] is None
    status = _connector_status(client, auth_headers, "smartsheet_sync")
    assert status["freshness"] == "confirmed"
    assert status["data_context_freshness"] == "confirmed"


@pytest.mark.parametrize("connector_id", ["salesforce_insights", "snowflake_insights"])
def test_data_only_connector_success_keeps_existing_freshness_rule(
    client, auth_headers, test_user, connector_id,
):
    update_connector_settings(test_user.id, connector_id, {
        "connection_status": "connected",
        "lifecycle_status": "connected",
    })

    mark_connector_sync_result(test_user.id, connector_id, "success")

    status = _connector_status(client, auth_headers, connector_id)
    assert status["freshness"] == "confirmed"
    assert "data_context_freshness" not in status


def test_connected_settings_save_does_not_refresh_last_verified_at(test_user):
    verified_at = "2026-10-13T01:26:45+00:00"
    _store_connector_status(
        test_user.id,
        connection_status="connected",
        lifecycle_status="connected",
        last_verified_at=verified_at,
    )

    update_connector_settings(test_user.id, "jira_sync", {
        "jira_project_key": "EXEC",
        "jira_issue_type": "Task",
        "jira_field_mapping": {"title": "summary"},
    })

    saved = connector_store.get_connector_settings(test_user.id, "jira_sync")
    assert saved["last_verified_at"] == verified_at


@pytest.mark.parametrize(
    ("connector_id", "settings", "probe_name"),
    [
        ("jira_sync", {"jira_data_enabled": True}, "refresh_portfolio"),
        ("smartsheet_sync", {"smartsheet_data_enabled": True, "smartsheet_sheet_id": "sheet-1"}, "smartsheet_get_sheet"),
        ("salesforce_insights", {}, "fetch_pipeline_summary"),
        ("snowflake_insights", {"snowflake_table_allowlist": ["analytics.context"]}, "run_allowlisted_query"),
    ],
)
def test_each_discovery_source_uses_a_live_read(app, monkeypatch, connector_id, settings, probe_name):
    connector_routes = importlib.import_module("app.routes.connectors")
    calls = []

    def probe(*args, **kwargs):
        calls.append((args, kwargs))
        return {"stale": False, "refresh_failed": False}

    monkeypatch.setattr(connector_routes, probe_name, probe)
    connector_routes._verify_data_context_read("user-1", connector_id, settings)

    assert len(calls) == 1
