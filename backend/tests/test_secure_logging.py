import json
import logging

from app.secure_logging import (
    REDACTED,
    SecretRedactingJsonFormatter,
    redact_text,
    sanitize_sentry_event,
)


def synthetic_live_key():
    return "sk" + "_live_" + ("A" * 24)


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
    event = {
        "request": {"headers": {"Authorization": f"Bearer {provider_key}"}},
        "extra": {"provider_response": f"failed with {provider_key}"},
    }

    sanitized = sanitize_sentry_event(event)

    assert event["request"]["headers"]["Authorization"].endswith(provider_key)
    serialized = json.dumps(sanitized)
    assert provider_key not in serialized
    assert REDACTED in serialized
