import json
import inspect
import logging

from app import _setup_sentry
from app.secure_logging import (
    REDACTED,
    SecretRedactingJsonFormatter,
    redact_text,
    sanitize_sentry_event,
)


def synthetic_live_key():
    return "sk" + "_live_" + ("A" * 24)


def test_sentry_disables_request_bodies_and_local_variables():
    source = inspect.getsource(_setup_sentry)

    assert 'max_request_body_size="never"' in source
    assert "include_local_variables=False" in source
    assert "before_send=sanitize_sentry_event" in source


def test_redact_text_removes_configured_and_pattern_credentials():
    configured = "configured-value-123456"
    provider_key = synthetic_live_key()
    result = redact_text(
        f"configured={configured} provider={provider_key}",
        environ={"GOOGLE_CLIENT_SECRET": configured},
    )

    assert configured not in result
    assert provider_key not in result
    assert REDACTED in result


def test_formatter_redacts_message_arguments_and_traceback():
    provider_key = synthetic_live_key()
    formatter = SecretRedactingJsonFormatter("%(message)s")
    try:
        raise RuntimeError(f"request failed for {provider_key}")
    except RuntimeError:
        record = logging.LogRecord(
            "security-test",
            logging.ERROR,
            __file__,
            1,
            "provider rejected %s",
            (provider_key,),
            __import__("sys").exc_info(),
        )

    output = formatter.format(record)
    assert provider_key not in output
    assert output.count(REDACTED) >= 2


def test_sentry_hook_redacts_sensitive_fields_without_mutating_input():
    provider_key = synthetic_live_key()
    share_token = "share-token-that-must-not-leave-jaspen"
    event = {
        "request": {
            "method": "POST",
            "url": f"https://jaspen.ai/s/{share_token}?private=yes",
            "headers": {"Authorization": f"Bearer {provider_key}", "User-Agent": "test-agent"},
            "data": {"chat": "private customer decision"},
            "query_string": "private=yes",
            "cookies": {"session": provider_key},
        },
        "user": {"id": "user-1", "email": "private@example.test", "name": "Private User"},
        "exception": {"values": [{"type": "RuntimeError", "value": "private customer decision", "stacktrace": {"frames": []}}]},
        "extra": {"provider_response": f"failed with {provider_key}"},
        "breadcrumbs": [{"message": "private customer decision"}],
    }

    sanitized = sanitize_sentry_event(event)

    assert event["request"]["headers"]["Authorization"].endswith(provider_key)
    serialized = json.dumps(sanitized)
    assert provider_key not in serialized
    assert share_token not in serialized
    assert "private customer decision" not in serialized
    assert "private@example.test" not in serialized
    assert REDACTED in serialized
    assert sanitized["request"]["headers"] == {"User-Agent": "test-agent"}
    assert sanitized["user"] == {"id": "user-1"}
    assert sanitized["exception"]["values"][0]["type"] == "RuntimeError"
    assert "stacktrace" in sanitized["exception"]["values"][0]
    assert "extra" not in sanitized and "breadcrumbs" not in sanitized
