#!/usr/bin/env python3
"""Aggregate-only, read-only audit for Phase 1 C4.

This script intentionally emits only two account counts and their most recent
usage timestamps. It never prints account identifiers, connector settings, or
credentials. Connector JSON is opened directly instead of through
``connector_store`` so reading cannot rotate or rewrite encrypted secrets.

DO NOT RUN without the product owner's separate C4 authorization.

Required environment:
  DATABASE_URL       SQLAlchemy database URL for the environment being audited.
Optional environment:
  CONNECTORS_DATA_DIR  Directory containing user_*_connectors.json files.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text


CONNECTOR_IDS = {"jira_sync", "smartsheet_sync"}
LEGACY_USAGE_ACTIONS = {
    "import",
    "webhook",
    "sync",
    "push",
    "legacy_sync",
    "session_sync",
}


def _utc_iso(value):
    if value is None:
        return None
    if isinstance(value, str):
        token = value.strip()
        if not token:
            return None
        try:
            value = datetime.fromisoformat(token.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _latest(current, candidate):
    current_iso = _utc_iso(current)
    candidate_iso = _utc_iso(candidate)
    if not candidate_iso:
        return current_iso
    if not current_iso:
        return candidate_iso
    return max(current_iso, candidate_iso)


def _selected(profile, connector_id):
    if not isinstance(profile, dict):
        return False
    preferred = str(profile.get("preferred_pm_tool") or "").strip().lower()
    selected = {
        str(item or "").strip().lower()
        for item in (profile.get("connector_ids") or [])
    }
    return preferred == connector_id or connector_id in selected


def _connector_data_dir():
    configured = str(os.getenv("CONNECTORS_DATA_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(__file__).resolve().parents[1] / "backend" / "connectors_data").resolve()


def _scan_connector_files():
    jira_accounts = set()
    smartsheet_accounts = set()
    latest = {"jira_sync": None, "smartsheet_sync": None}

    for path in sorted(_connector_data_dir().glob("user_*_connectors.json")):
        # The id is used only for in-memory de-duplication and is never emitted.
        account_key = path.name[len("user_") : -len("_connectors.json")]
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        connectors = state.get("connectors") if isinstance(state.get("connectors"), dict) else {}
        profiles = state.get("thread_sync") if isinstance(state.get("thread_sync"), dict) else {}
        audit_log = state.get("audit_log") if isinstance(state.get("audit_log"), list) else []

        jira = connectors.get("jira_sync") if isinstance(connectors.get("jira_sync"), dict) else {}
        smartsheet = connectors.get("smartsheet_sync") if isinstance(connectors.get("smartsheet_sync"), dict) else {}
        jira_configured = bool(str(jira.get("jira_project_key") or "").strip())
        smartsheet_connected = str(
            smartsheet.get("lifecycle_status") or smartsheet.get("connection_status") or ""
        ).strip().lower() in {"connected", "ready"}

        for profile in profiles.values():
            if _selected(profile, "jira_sync"):
                jira_configured = True
                if profile.get("last_full_sync_at"):
                    latest["jira_sync"] = _latest(latest["jira_sync"], profile.get("last_full_sync_at"))
            if _selected(profile, "smartsheet_sync"):
                smartsheet_connected = True
                if profile.get("last_full_sync_at"):
                    latest["smartsheet_sync"] = _latest(latest["smartsheet_sync"], profile.get("last_full_sync_at"))

        for event in audit_log:
            if not isinstance(event, dict):
                continue
            connector_id = str(event.get("connector_id") or "").strip().lower()
            action = str(event.get("action") or "").strip().lower()
            if connector_id not in CONNECTOR_IDS or action not in LEGACY_USAGE_ACTIONS:
                continue
            latest[connector_id] = _latest(latest[connector_id], event.get("timestamp"))
            if connector_id == "jira_sync":
                jira_configured = True
            else:
                smartsheet_connected = True

        if jira_configured:
            jira_accounts.add(account_key)
        if smartsheet_connected:
            smartsheet_accounts.add(account_key)

    return jira_accounts, smartsheet_accounts, latest


def _scan_database_logs(database_url, jira_accounts, smartsheet_accounts, latest):
    engine = create_engine(database_url)
    query = text("""
        SELECT user_id, connector_id, action, created_at
        FROM connector_sync_logs
        WHERE connector_id IN ('jira_sync', 'smartsheet_sync')
          AND action IN ('import', 'webhook', 'sync', 'push', 'legacy_sync', 'session_sync')
    """)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            if connection.dialect.name == "postgresql":
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            for row in connection.execute(query).mappings():
                connector_id = str(row["connector_id"])
                account_key = str(row["user_id"])
                if connector_id == "jira_sync":
                    jira_accounts.add(account_key)
                else:
                    smartsheet_accounts.add(account_key)
                latest[connector_id] = _latest(latest[connector_id], row["created_at"])
        finally:
            # Roll back even though the transaction contains SELECT statements only.
            transaction.rollback()


def main():
    database_url = str(os.getenv("DATABASE_URL") or "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL is required")
    jira_accounts, smartsheet_accounts, latest = _scan_connector_files()
    _scan_database_logs(database_url, jira_accounts, smartsheet_accounts, latest)
    print(json.dumps({
        "read_only": True,
        "legacy_session_wide_jira": {
            "account_count": len(jira_accounts),
            "most_recent_usage_at": latest["jira_sync"],
        },
        "smartsheet_connected_or_used": {
            "account_count": len(smartsheet_accounts),
            "most_recent_usage_at": latest["smartsheet_sync"],
        },
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
