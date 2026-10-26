"""Redact credentials from logs and external error-reporting events."""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Mapping

from pythonjsonlogger import jsonlogger


REDACTED = "[REDACTED]"
SECRET_ENV_NAMES = (
    "SECRET_KEY",
    "JWT_SECRET_KEY",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "ANTHROPIC_API_KEY",
    "CLAUDE_API_KEY",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_CLIENT_SECRET",
    "MAIL_PASSWORD",
    "CONNECTOR_ENCRYPTION_KEY",
    "JIRA_API_TOKEN",
    "JIRA_WEBHOOK_SECRET",
    "WORKFRONT_API_TOKEN",
    "WORKFRONT_WEBHOOK_SECRET",
    "SMARTSHEET_API_TOKEN",
    "SMARTSHEET_WEBHOOK_SECRET",
    "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE",
    "DATABASE_URL",
    "SQLALCHEMY_DATABASE_URI",
    "RATELIMIT_STORAGE_URI",
)
SENSITIVE_FIELD_NAMES = re.compile(
    r"(?i)(authorization|cookie|set-cookie|password|passwd|secret|token|api[_-]?key|private[_-]?key|database[_-]?url|dsn)"
)
TEXT_PATTERNS = (
    re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^\s/:@]+:)[^\s/@]+(@)"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\b(?:gh[pousr]_|sk-(?:proj-)?|sk-ant-|(?:sk|rk)_live_|whsec_|xox[baprs]-)[A-Za-z0-9_-]{12,}\b"),
    re.compile(
        r"(?i)([\"']?(?:password|passwd|secret|token|api[_-]?key|private[_-]?key|database[_-]?url)[\"']?\s*[:=]\s*[\"']?)[^\s,;\"']+"
    ),
    re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----.*?-----END (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----", re.DOTALL),
)
SHARE_URL_PATTERN = re.compile(
    r"(?P<prefix>/(?:s|api/v1/shares/(?:public|manage))/)[^/?#\s]+",
    re.IGNORECASE,
)
SENTRY_ALLOWED_REQUEST_HEADERS = {"content-type", "user-agent"}


def redact_text(value: Any, *, environ: Mapping[str, str] | None = None) -> str:
    """Return safe text without ever emitting configured credential values."""

    text = str(value)
    text = SHARE_URL_PATTERN.sub(rf"\g<prefix>{REDACTED}", text)
    source = os.environ if environ is None else environ
    for name in SECRET_ENV_NAMES:
        secret = str(source.get(name) or "")
        if len(secret) >= 8:
            text = text.replace(secret, REDACTED)

    for pattern in TEXT_PATTERNS:
        if pattern.groups == 2:
            text = pattern.sub(rf"\1{REDACTED}\2", text)
        elif pattern.groups == 1:
            text = pattern.sub(rf"\1 {REDACTED}", text)
        else:
            text = pattern.sub(REDACTED, text)
    return text


def sanitize_structure(value: Any, *, environ: Mapping[str, str] | None = None) -> Any:
    """Recursively sanitize an error-reporting structure without mutating it."""

    if isinstance(value, Mapping):
        return {
            key: REDACTED if SENSITIVE_FIELD_NAMES.search(str(key)) else sanitize_structure(item, environ=environ)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_structure(item, environ=environ) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_structure(item, environ=environ) for item in value)
    if isinstance(value, str):
        return redact_text(value, environ=environ)
    return value


def sanitize_sentry_event(event: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """Strip customer content while preserving error type and stack location."""

    del hint
    sanitized = sanitize_structure(event)

    request = sanitized.get("request")
    if isinstance(request, Mapping):
        headers = request.get("headers") if isinstance(request.get("headers"), Mapping) else {}
        safe_headers = {
            key: value
            for key, value in headers.items()
            if str(key).lower() in SENTRY_ALLOWED_REQUEST_HEADERS
        }
        sanitized["request"] = {
            key: value
            for key, value in request.items()
            if key in {"method", "url"}
        }
        if safe_headers:
            sanitized["request"]["headers"] = safe_headers

    user = sanitized.get("user")
    if isinstance(user, Mapping):
        sanitized["user"] = {"id": user["id"]} if user.get("id") is not None else {}

    exception = sanitized.get("exception")
    if isinstance(exception, Mapping) and isinstance(exception.get("values"), list):
        for item in exception["values"]:
            if isinstance(item, dict) and "value" in item:
                item["value"] = "Exception details suppressed"

    logentry = sanitized.get("logentry")
    if isinstance(logentry, Mapping):
        sanitized["logentry"] = {"message": "Application error captured"}

    sanitized.pop("extra", None)
    sanitized.pop("breadcrumbs", None)
    return sanitized


class SecretRedactingJsonFormatter(jsonlogger.JsonFormatter):
    """Apply redaction after message, arguments, and traceback are formatted."""

    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record))
