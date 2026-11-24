"""Restore-copy authorization for the billing migration evidence run (BI-2, review N4).

A Phase 15 rehearsal or Phase 16 shadow comparison on ``restore_copy`` runs on
a copy of production data. Before BI-2 the shadow comparison refused it
outright, because nothing proved a database was an authorized, non-production
restore. This module is that proof. It is deliberately narrow:

* **Explicit founder approval.** The authorization is a staging-only JSON
  value (``BILLING_RESTORE_COPY_AUTHORIZATION``) naming the approval
  reference, ``approved_by: "founder"``, when it was approved and when it
  expires (at most 14 days later).
* **Restore provenance.** It names the source cluster, the restore cluster,
  the method and the point in time the copy was restored from.
* **Database identity.** It names the database host, database name and
  PostgreSQL ``system_identifier`` it applies to; the live connection must
  match all three. A physical restore keeps the source's
  ``system_identifier``, so the host is part of the identity.
* **Never production.** ``BILLING_PRODUCTION_DATABASE_HOSTS`` must name the
  production database hosts (missing: refused), and the connected host must
  not be one of them; a production runtime or live Stripe key is refused; and
  any role in ``BILLING_PRODUCTION_LOGIN_ROLES`` (default ``jaspen_app_prod``)
  that can log in on the connected database marks it as production.

Missing, malformed or expired authorization is refused before any database
connection opens. The identity checks run inside the caller's read-only
transaction. Everything fails closed; nothing here writes.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from .rate_limits import is_production_runtime

AUTHORIZATION_KEY = "BILLING_RESTORE_COPY_AUTHORIZATION"
PRODUCTION_HOSTS_KEY = "BILLING_PRODUCTION_DATABASE_HOSTS"
PRODUCTION_LOGIN_ROLES_KEY = "BILLING_PRODUCTION_LOGIN_ROLES"
DEFAULT_PRODUCTION_LOGIN_ROLES = ("jaspen_app_prod",)
MAX_VALIDITY = timedelta(days=14)
SYSTEM_IDENTIFIER = re.compile(r"^[0-9]{1,20}$")
ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class RestoreCopyAuthorizationError(ValueError):
    """The restore copy is not authorized (missing, malformed, expired, mismatched, or production)."""


def _text(value, field, maximum=255):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise RestoreCopyAuthorizationError(f"the restore-copy authorization needs {field}")
    return value.strip()


def _instant(value, field):
    raw = _text(value, field, 64)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RestoreCopyAuthorizationError(f"{field} must be an ISO 8601 UTC time") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise RestoreCopyAuthorizationError(f"{field} must be an ISO 8601 UTC time")
    return parsed


def _hosts(value):
    hosts = [h.strip().lower() for h in str(value or "").split(",") if h.strip()]
    if not hosts:
        raise RestoreCopyAuthorizationError(
            f"{PRODUCTION_HOSTS_KEY} must name the production database hosts before any restore copy runs")
    return hosts


def _roles(value):
    roles = [r.strip() for r in str(value or "").split(",") if r.strip()] or list(DEFAULT_PRODUCTION_LOGIN_ROLES)
    for role in roles:
        if not ROLE_NAME.match(role):
            raise RestoreCopyAuthorizationError(f"{PRODUCTION_LOGIN_ROLES_KEY} holds an invalid role name")
    return roles


def check_authorization_configuration(config, *, now=None):
    """Everything that can be checked before connecting. Returns the parsed authorization."""
    if is_production_runtime():
        raise RestoreCopyAuthorizationError("a restore copy is never used from a production runtime")
    raw = (config or {}).get(AUTHORIZATION_KEY)
    if not raw:
        raise RestoreCopyAuthorizationError(f"no restore-copy authorization ({AUTHORIZATION_KEY} is not set)")
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError as exc:
        raise RestoreCopyAuthorizationError("the restore-copy authorization is not valid JSON") from exc
    expected = {"approval_reference", "approved_by", "approved_at", "expires_at", "database", "restore_provenance"}
    if not isinstance(value, dict) or set(value) != expected:
        raise RestoreCopyAuthorizationError(f"the restore-copy authorization names exactly {sorted(expected)}")
    if value["approved_by"] != "founder":
        raise RestoreCopyAuthorizationError("a restore copy is authorized only by the founder")
    now = now or datetime.now(timezone.utc)
    approved_at = _instant(value["approved_at"], "approved_at")
    expires_at = _instant(value["expires_at"], "expires_at")
    if approved_at > now:
        raise RestoreCopyAuthorizationError("the restore-copy authorization is dated in the future")
    if not approved_at < expires_at <= approved_at + MAX_VALIDITY:
        raise RestoreCopyAuthorizationError("a restore-copy authorization expires within 14 days of its approval")
    if now >= expires_at:
        raise RestoreCopyAuthorizationError("the restore-copy authorization has expired")
    database = value["database"]
    if not isinstance(database, dict) or set(database) != {"host", "name", "system_identifier"}:
        raise RestoreCopyAuthorizationError("the authorization names the database host, name and system_identifier")
    identifier = _text(database["system_identifier"], "database.system_identifier", 20)
    if not SYSTEM_IDENTIFIER.match(identifier):
        raise RestoreCopyAuthorizationError("database.system_identifier must be the decimal PostgreSQL identifier")
    provenance = value["restore_provenance"]
    keys = {"source_cluster", "restore_cluster", "method", "restored_from_utc"}
    if not isinstance(provenance, dict) or set(provenance) != keys:
        raise RestoreCopyAuthorizationError(f"the restore provenance names exactly {sorted(keys)}")
    restored_from = _instant(provenance["restored_from_utc"], "restore_provenance.restored_from_utc")
    if restored_from > approved_at:
        raise RestoreCopyAuthorizationError("the copy must have been restored before it was authorized")
    host = _text(database["host"], "database.host").lower()
    production_hosts = _hosts((config or {}).get(PRODUCTION_HOSTS_KEY))
    if any(host == p or host.startswith(p + ".") or p in host for p in production_hosts):
        raise RestoreCopyAuthorizationError("the authorized database host is a production database host")
    restore_cluster = _text(provenance["restore_cluster"], "restore_provenance.restore_cluster").lower()
    # Production entries may be cluster names or hosts (a host contains its cluster name).
    if any(restore_cluster == p or restore_cluster in p or p in restore_cluster for p in production_hosts):
        raise RestoreCopyAuthorizationError("the restore cluster is a production cluster")
    return {
        "approval_reference": _text(value["approval_reference"], "approval_reference"),
        "approved_at": approved_at.isoformat(), "expires_at": expires_at.isoformat(),
        "database": {"host": host, "name": _text(database["name"], "database.name", 63),
                     "system_identifier": identifier},
        "restore_provenance": {
            "source_cluster": _text(provenance["source_cluster"], "restore_provenance.source_cluster"),
            "restore_cluster": _text(provenance["restore_cluster"], "restore_provenance.restore_cluster"),
            "method": _text(provenance["method"], "restore_provenance.method"),
            "restored_from_utc": restored_from.isoformat(),
        },
        "production_hosts": production_hosts,
        "production_login_roles": _roles((config or {}).get(PRODUCTION_LOGIN_ROLES_KEY)),
    }


def verify_restore_copy_database(connection, authorization, *, host):
    """Inside the caller's (read-only) transaction: the connected database is the authorized restore copy."""
    if connection.dialect.name != "postgresql":
        raise RestoreCopyAuthorizationError("a restore copy is a PostgreSQL database")
    connected_host = str(host or "").strip().lower()
    if not connected_host:
        raise RestoreCopyAuthorizationError("the connected database host is unknown")
    if any(connected_host == p or connected_host.startswith(p + ".") or p in connected_host
           for p in authorization["production_hosts"]):
        raise RestoreCopyAuthorizationError("the connected database host is a production database host")
    try:
        name = connection.execute(text("SELECT current_database()")).scalar()
        identifier = str(connection.execute(text("SELECT system_identifier FROM pg_control_system()")).scalar())
    except Exception as exc:  # noqa: BLE001 - any failure to read the identity refuses
        raise RestoreCopyAuthorizationError("the database identity (system_identifier) cannot be read") from exc
    expected = authorization["database"]
    if (connected_host, name, identifier) != (expected["host"], expected["name"], expected["system_identifier"]):
        raise RestoreCopyAuthorizationError("the connected database is not the authorized restore copy")
    production_logins = connection.execute(text(
        "SELECT rolname FROM pg_roles WHERE rolcanlogin AND rolname = ANY(:roles) ORDER BY rolname"),
        {"roles": list(authorization["production_login_roles"])}).scalars().all()
    if production_logins:
        raise RestoreCopyAuthorizationError("a production login role exists on the connected database")
    return {"approval_reference": authorization["approval_reference"], "expires_at": authorization["expires_at"],
            "database": expected, "restore_provenance": authorization["restore_provenance"],
            "identity_verified": True}


def app_config():
    """The Flask config when there is an application context, else an empty mapping (fails closed)."""
    from flask import current_app, has_app_context
    return current_app.config if has_app_context() else {}
