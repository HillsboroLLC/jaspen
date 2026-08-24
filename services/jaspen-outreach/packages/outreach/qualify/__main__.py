from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

import httpx
from pydantic import ValidationError

from qualification_core import (
    PROMPT_VERSION,
    RUBRIC_VERSION,
    QualificationRequest,
    qualify_with_openai,
)


def _response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": body,
    }


def _safe_request_id(event: dict[str, Any]) -> str:
    headers = event.get("http", {}).get("headers", {})
    return str(headers.get("x-request-id", ""))[:200]


def _safe_fingerprint(prospect_id: str) -> str:
    return hashlib.sha256(prospect_id.encode("utf-8")).hexdigest()[:16]


def _log(event_name: str, **fields: Any) -> None:
    safe_fields = {key: value for key, value in fields.items() if value not in (None, "")}
    print(json.dumps({"event": event_name, **safe_fields}, separators=(",", ":")))


def _json_body(event: dict[str, Any]) -> dict[str, Any]:
    http = event.get("http", {})
    raw_body = http.get("body", "")
    if http.get("isBase64Encoded"):
        raw_body = base64.b64decode(raw_body, validate=True).decode("utf-8")
    if not isinstance(raw_body, str):
        raise ValueError("Request body must be JSON text")
    parsed = json.loads(raw_body)
    if not isinstance(parsed, dict):
        raise ValueError("Request body must be a JSON object")
    return parsed


def main(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    started = time.monotonic()
    http = event.get("http", {})
    headers = http.get("headers", {})
    request_id = _safe_request_id(event)

    if str(http.get("method", "")).upper() != "POST":
        return _response(405, {"error": "Method not allowed"})

    expected_secret = os.environ.get("JASPEN_OUTREACH_SHARED_SECRET", "")
    supplied_secret = str(headers.get("x-jaspen-outreach-secret", ""))
    if not expected_secret or not hmac.compare_digest(supplied_secret, expected_secret):
        _log("qualification_rejected", request_id=request_id, reason="unauthorized")
        return _response(401, {"error": "Unauthorized"})

    try:
        request = QualificationRequest.model_validate(_json_body(event))
    except (ValueError, ValidationError, json.JSONDecodeError, UnicodeDecodeError):
        _log("qualification_rejected", request_id=request_id, reason="invalid_request")
        return _response(400, {"error": "Invalid qualification request"})

    fingerprint = _safe_fingerprint(request.prospect.id)
    try:
        result = asyncio.run(qualify_with_openai(request))
    except httpx.HTTPStatusError as exc:
        openai_request_id = exc.response.headers.get("x-request-id", "")[:200]
        _log(
            "qualification_failed",
            request_id=request_id,
            prospect=fingerprint,
            reason="openai_http_error",
            openai_status=exc.response.status_code,
            openai_request_id=openai_request_id,
            duration_ms=round((time.monotonic() - started) * 1000),
        )
        return _response(502, {"error": "Qualification provider request failed"})
    except (ValueError, RuntimeError, ValidationError):
        _log(
            "qualification_failed",
            request_id=request_id,
            prospect=fingerprint,
            reason="qualification_guardrail_failure",
            duration_ms=round((time.monotonic() - started) * 1000),
        )
        return _response(502, {"error": "Qualification guardrail failed"})
    except Exception:
        _log(
            "qualification_failed",
            request_id=request_id,
            prospect=fingerprint,
            reason="unexpected_error",
            duration_ms=round((time.monotonic() - started) * 1000),
        )
        return _response(500, {"error": "Qualification service failed"})

    duration_ms = round((time.monotonic() - started) * 1000)
    _log(
        "qualification_succeeded",
        request_id=request_id,
        prospect=fingerprint,
        overall=result.overall_qualification,
        proceed=result.proceed_to_outreach,
        review_route=result.review_route,
        evidence_count=result.evidence_count,
        prompt_version=PROMPT_VERSION,
        rubric_version=RUBRIC_VERSION,
        duration_ms=duration_ms,
    )
    return _response(200, result.model_dump(mode="json"))
